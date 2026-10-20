import asyncio
import logging
import os
from collections import defaultdict
from collections.abc import AsyncIterable, Callable, Generator, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cache
from itertools import batched
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self, cast

from extract_core import (
    ConversionOutput,
    Error,
    InputDoc,
    OutputFormat,
    Pipeline,
    PipelineType,
    Result,
    Status,
    SupportedExt,
)
from pydantic import TypeAdapter

from .constants import ARTIFACTS, DEFAULT_MD_PAGE_SEP
from .utils import (
    ProcessedPages,
    Range,
    ResultBuffer,
    UsageTracker,
    chunk_docs,
    path_to_artifacts_dirname,
    publish_and_consume,
    write_pages,
)

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from liteparse import LiteParse
    from liteparse.types import (
        ExtractedImage,
        PageComplexityStats,
        PageError,
        ParsedPage,
        ParseResult,
    )
    from PIL import Image
    from tesserocr import PyTessBaseAPI

_LITEPARSE_CONVERSION_ERRORS = tuple()


OrientedBatch = tuple[int | None, tuple[ProcessedPages]]
LiteParseOutputFormat = Literal["text", "json", "markdown"]


@cache
def get_parse_result_ta() -> TypeAdapter:
    from liteparse.types import ParseResult  # noqa: PLC0415

    return TypeAdapter(ParseResult)


@dataclass
class LiteParsePageResult:
    pages: list["ParsedPage"] = field(default_factory=list)
    images: list["ExtractedImage"] = field(default_factory=list)
    errors: list["PageError"] = field(default_factory=list)
    _by_ix: (
        dict[int, tuple["ParsedPage", list["ExtractedImage"], list["PageError"]]] | None
    ) = None

    def filter(self, page: ProcessedPages) -> Self:
        if self._by_ix is None:
            self._by_ix = self._results_by_index()
        pages, images, errors = [], [], []
        for p_i in range(page.page_range[0], page.page_range[1]):
            p, ims, errors = self._by_ix[p_i]
            pages.append(p)
            images.extend(ims)
            errors.extend(errors)
        return LiteParsePageResult(pages=pages, images=images, errors=errors)

    def _results_by_index(
        self,
    ) -> dict[int, tuple["ParsedPage", list["ExtractedImage"], list["PageError"]]]:
        by_ix = dict()
        for p in self.pages:
            rng_ix = p.page_num - 1
            ims = [i for i in self.images if i.page == p.page_num]
            errors = [e for e in self.errors if e.page_num == p.page_num]
            by_ix[rng_ix] = (p, ims, errors)
        return by_ix


ResultAggregator = Callable[[InputDoc, list[LiteParsePageResult], Path], Result]


@Pipeline.register(PipelineType.LITEPARSE)
class LiteParsePipeline(Pipeline):
    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncIterable[Result]:
        tessdata_path = self._config.tessdata_path
        if tessdata_path is None:
            tessdata_path = os.getenv("TESSDATA_PREFIX")
        if tessdata_path is None:
            msg = "couldn't find tessdata path in config nor TESSDATA_PREFIX env var"
            raise RuntimeError(msg)
        self._tessdata_path = str(tessdata_path)
        if self._config.detect_page_orientation:
            logger.info("reading docs page orientation detection...")
            batches = await self._batch_per_orientation(docs)
            logger.info("done with page orientation detection !")
        else:
            batches = chunk_docs(docs, self._config.page_batch_size)
            batches = ((None, (c,)) for c in batches)
        async for res in self._parse(batches, output_format, output_path):
            yield res

    async def _batch_per_orientation(
        self, docs: Iterable[InputDoc]
    ) -> list[OrientedBatch]:
        result_queue = asyncio.Queue()
        publisher = self._batch_publisher(docs, result_queue)
        consumer = self._batch_consumer(result_queue)
        batches = [b async for b in publish_and_consume(publisher, consumer=consumer)]
        return batches

    async def _batch_publisher(
        self, docs: Iterable[InputDoc], queue: asyncio.Queue
    ) -> None:
        sem = asyncio.Semaphore(self._config.n_cpus - 1)
        logger.debug("creating page complexity parser...")
        parser = self._make_complexity_parser()
        logger.debug("creating page complexity parser...")
        parser.warm_up()
        with parser:
            async with asyncio.TaskGroup() as tg:
                for doc in docs:
                    if doc.ext == SupportedExt.PDF:
                        task = self._detect_complexity_and_queue(
                            parser, doc, queue, sem
                        )
                        tg.create_task(task)
                    else:
                        queue.put_nowait((doc, None))
        queue.put_nowait(None)

    async def _batch_consumer(
        self, queue: asyncio.Queue
    ) -> AsyncIterable[OrientedBatch]:
        import pypdfium2 as pdfium  # noqa: PLC0415
        import tesserocr  # noqa: PLC0415
        from liteparse.types import PageComplexityStats  # noqa: PLC0415

        batch_size = self._config.page_batch_size
        osd_reader = tesserocr.PyTessBaseAPI(
            self._tessdata_path,
            lang="osd",
            oem=tesserocr.OEM.DEFAULT,
            psm=tesserocr.PSM.OSD_ONLY,
        )
        pages_per_orientation = defaultdict(list)
        doc_ix = -1
        with osd_reader:
            while (res := await queue.get()) is not None:
                doc_ix += 1
                doc, pdf_pages = res
                if pdf_pages is None:
                    for batch in chunk_docs([doc], batch_size):
                        rng = _liteparse_range(batch.page_range)
                        pages_per_orientation[(rng, None)].append(batch)
                    continue
                buffer = defaultdict(list)
                try:
                    pdf_doc = None
                    pages = cast(list[PageComplexityStats], pdf_pages)
                    for page in pages:
                        # We don't use orientation for regular page, we reserve osd for
                        # pages were OCR is required
                        if not _should_detect_orientation(page):
                            buffer[None].append(page)
                            continue
                        if pdf_doc is None:
                            pdf_doc = pdfium.PdfDocument(doc.path)
                        page_im = (
                            pdf_doc[page.page_number - 1].render(scale=3.0).to_pil()
                        )
                        orientation = _detect_orientation(osd_reader, page_im)
                        buffer[orientation].append(page)
                finally:
                    if pdf_doc is not None:
                        pdf_doc.close()
                for orientation, pages in buffer.items():
                    for batch in batched(pages, batch_size, strict=False):
                        batch = _pages_from_complexities(doc, doc_ix, *batch)  # noqa: PLW2901
                        rng = _liteparse_range_from_pages(*batch)
                        pages_per_orientation[(rng, orientation)].append(batch)
        # We yield pages per orientation only here to make sure to yield
        # (orientation, range) in the most regular way and avoid reload
        for (_, orientation), batches in pages_per_orientation.items():
            for batch in batches:
                yield orientation, batch

    async def _parse(
        self,
        batches: Iterable[OrientedBatch],
        output_format: OutputFormat,
        output_path: Path,
    ) -> AsyncIterable[Result]:
        match output_format:
            case OutputFormat.MARKDOWN:
                liteparse_o_fmt, postprocess_fn = "markdown", aggregate_pages_md
            case _:
                fmt = (
                    f"unsupported output format for {LiteParsePipeline.__name__}"
                    f" {output_format}"
                )
                raise NotImplementedError(fmt)
        result_queue = asyncio.Queue()
        with self._result_buffer() as buffer:
            publisher = self._parse_publisher(batches, liteparse_o_fmt, result_queue)
            consumer = self._parse_consumer(
                result_queue, buffer, postprocess_fn, output_path
            )
            async for res in publish_and_consume(publisher, consumer=consumer):
                yield res

    async def _parse_publisher(
        self,
        batches: Iterable[OrientedBatch],
        output_format: LiteParseOutputFormat,
        queue: asyncio.Queue,
    ) -> None:
        parser = None
        # Buffer partial conversion to filesystem as large docs are chunked into pieces
        # Prevent more than n_cpu concurrent processing
        sem = asyncio.Semaphore(self._config.n_cpus - 1)
        # Results may return in arbitrary order, we need to wait until parser is not
        # used any longer before
        tracker = UsageTracker()
        current_key = None
        with _close_parser(parser):
            async with asyncio.TaskGroup() as tg:
                for orientation, batch in batches:
                    # We avoid recreating the parser at each iteration since it creates
                    # a worker pool, instead process in (orientation, page range) order
                    # and cache the parser
                    page_range = _liteparse_range_from_pages(*batch)
                    n_pages = sum(p.n_pages for p in batch)
                    key = (page_range, orientation)
                    if key != current_key:
                        if parser is not None:
                            await tracker.wait_until_free()
                            parser.__exit__()
                        logger.debug("loading parser for %s", key)
                        parser = self._make_parser(output_format, key, n_pages=n_pages)
                        parser.__enter__().warm_up()
                        current_key = key
                    await sem.acquire(), await tracker.acquire()
                    task = self._convert_and_queue(parser, batch, queue, sem, tracker)
                    tg.create_task(task)
        queue.put_nowait(None)

    async def _parse_consumer(
        self,
        queue: asyncio.Queue,
        buffer: ResultBuffer,
        result_aggregator: ResultAggregator,
        output_path: Path,
    ) -> AsyncIterable[Result]:
        while (queued := await queue.get()) is not None:
            pages, res = queued
            for p in pages:
                filtered = res.filter(p)
                buffer.add(p, filtered)
            doc_ix = pages[0].doc_idx
            doc = pages[0].doc
            if buffer.is_complete(doc_ix):
                res = result_aggregator(doc, buffer.pop_complete(doc_ix), output_path)
                yield res
        logger.info("done consuming !")

    async def _detect_complexity_and_queue(
        self,
        parser: "LiteParse",
        doc: InputDoc,
        queue: asyncio.Queue,
        sem: asyncio.Semaphore,
    ) -> None:
        pages = await asyncio.to_thread(parser.is_complex, doc.path)
        sem.release()
        queue.put_nowait((doc, pages))

    async def _convert_and_queue(
        self,
        parser: "LiteParse",
        pages: tuple[ProcessedPages],
        queue: asyncio.Queue,
        sem: asyncio.Semaphore,
        tracker: UsageTracker,
    ) -> None:
        res = await asyncio.to_thread(parser.parse, pages[0].doc.path)
        sem.release(), await tracker.release()
        res = LiteParsePageResult(
            pages=res.pages, errors=res.page_errors, images=res.images
        )
        queue.put_nowait((pages, res))

    def _make_parser(
        self,
        output_format: LiteParseOutputFormat,
        key: tuple[str, int | None],
        n_pages: int,
    ) -> "LiteParse":
        from liteparse.parser import LiteParse  # noqa: PLC0415

        page_batch_size = self._config.page_batch_size
        parse_timeout = self._config.per_page_timeout
        if parse_timeout is not None:
            parse_timeout = parse_timeout * page_batch_size
        target_pages, orientation = key
        if orientation is not None:
            orientation = [(p + 1, orientation) for p in range(n_pages)]
        pool_size = self._config.n_cpus - 1
        return LiteParse(
            ocr_enabled=True,
            extract_links=True,
            keep_headers_footers=True,
            extract_structure_tree=True,
            extract_blocks=True,
            ocr_failure_fatal=True,
            # Corrections are per docs we would have to create 1 parser per doc
            page_orientation_corrections=orientation,
            pool_size=pool_size,
            parse_timeout=parse_timeout,
            target_pages=target_pages,
            continue_on_page_error=True,
            output_format=output_format,
            extract_images=True,
            extract_screenshots=False,
            include_complexity=True,
            image_mode="placeholder",
            num_workers=1,
            image_output_dir=None,
            **self._config.config.model_dump(),
        )

    def _make_complexity_parser(self) -> "LiteParse":
        from liteparse.parser import LiteParse  # noqa: PLC0415

        return LiteParse(ocr_enabled=False, pool_size=self._config.n_cpus - 1)

    def _result_buffer(self) -> ResultBuffer:

        buffer = ResultBuffer(
            max_size_bytes=self._config.result_buffer.max_size,
            root=self._config.result_buffer.root,
            save_fn=_save_conversion_result,
            load_fn=_load_conversion_result,
        )
        return buffer


def aggregate_pages_md(
    doc: InputDoc,
    results: Sequence[LiteParsePageResult],
    output_path: Path,
    sep: str = DEFAULT_MD_PAGE_SEP,
) -> Result:
    md_dir_name = path_to_artifacts_dirname(doc.path)
    md_dir = output_path / md_dir_name
    md_dir.mkdir(parents=True, exist_ok=True)
    im_dir = md_dir / ARTIFACTS
    im_dir.mkdir(parents=True, exist_ok=True)
    pages, errors = [], []
    results = sorted(results, key=lambda p: p.pages[0].page_num)
    for res in results:
        if res.errors:
            errors.extend(Error.from_liteparse(err) for err in res.errors)
        per_page_md = {p.page_num: md_from_page(p) for p in res.pages}
        for im in res.images:
            if im.bytes is None:
                msg = "images were not extracted, extract_images must be set to True"
                raise ValueError(msg)
            im_path = im_dir / im.name
            im_path.write_bytes(im.bytes)
            page_md = per_page_md[im.page]
            page_md = page_md.replace(im.name, f"{ARTIFACTS}/{im.name}")
            per_page_md[im.page] = page_md
        for _, p in sorted(per_page_md.items()):
            pages.append(p)
    if not errors:
        status = Status.SUCCESS
    else:
        errors_on_all_pages = all(bool(len(p.errors)) for p in pages)
        status = Status.FAILURE if errors_on_all_pages else Status.FAILURE
    md_file = (md_dir / md_dir.name).with_suffix(OutputFormat.MARKDOWN)
    with md_file.open(mode="wb") as f:
        pages = write_pages(pages, sep, f)
    output = ConversionOutput(
        path=md_dir.relative_to(output_path), pages=pages, confidence=None
    )
    return Result(input=doc, status=status, output=output, errors=errors)


def md_from_page(page: "ParsedPage") -> str:
    md = page.markdown
    if "scanned" not in page.complexity.reasons:
        return md
    if md.startswith("![]("):
        md = md.split("\n")[1:]
        if not md[0]:
            md = md[1:]
        md = "\n".join(md)
    return md


def _save_conversion_result(res: "ParseResult", path: Path) -> None:
    path.write_bytes(get_parse_result_ta().dump_json(res))


def _load_conversion_result(path: Path) -> "ParseResult":
    return get_parse_result_ta().validate_json(path.read_text())


@contextmanager
def _close_parser(parser: "LiteParse | None") -> Generator[None]:
    try:
        yield
    finally:
        if parser is not None:
            parser.close()


def _liteparse_range(rng: Range) -> str:
    # page range is a Python range, liteparse indexes from 1 and upper bound
    # is inclusive
    return f"{rng[0] + 1}-{rng[1]}"


def _liteparse_range_from_pages(*pages: ProcessedPages) -> str:
    pages = sorted(pages, key=lambda p: p.page_range[0])
    ranges = (_liteparse_range(p.page_range) for p in pages)
    return ",".join(ranges)


def _pages_from_complexities(
    doc: InputDoc, doc_ix: int, *complexities: "PageComplexityStats"
) -> tuple[ProcessedPages]:
    complexities = sorted(complexities, key=lambda p: p.page_number)
    pages = []
    start, end = None, None
    for p in complexities:
        if start is None:
            start = p.page_number - 1
            end = start + 1
        if p.page_number != end:
            processed = ProcessedPages(doc=doc, doc_idx=doc_ix, page_range=(start, end))
            pages.append(processed)
            start = p.page_number - 1
        end = p.page_number
    processed = ProcessedPages(doc=doc, doc_idx=doc_ix, page_range=(start, end))
    pages.append(processed)
    return pages


_CLIPPED_ORIENTATIONS = [0, 90, 180, 270]


def _should_detect_orientation(page: "PageComplexityStats") -> bool:
    if not page.needs_ocr:
        return False
    reasons = set(page.reasons)
    if "scanned" in reasons:
        return True
    if "garbled" in reasons:
        return True
    if "vector-text" in reasons:  # noqa: SIM103
        return True
    return False


def _detect_orientation(osd_reader: "PyTessBaseAPI", page_im: "Image.Image") -> int:
    osd_reader.SetImage(page_im)
    orientation = osd_reader.DetectOrientationScript()["orient_deg"]
    return _clipped_orientation(orientation)


def _clipped_orientation(angle: float) -> int:
    return min((abs(angle - o) % 360, o) for o in _CLIPPED_ORIENTATIONS)[1]
