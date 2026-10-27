import asyncio
import logging
import os
from collections import defaultdict
from collections.abc import AsyncIterable, Callable, Generator, Iterable, Sequence
from concurrent import futures
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cache
from itertools import batched
from multiprocessing import get_context
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self

from extract_core import (
    ConversionOutput,
    Error,
    InputDoc,
    LiteParsePipelineConfig,
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
    _run_with_concurrency,
    chunk_docs,
    path_to_artifacts_dirname,
    publish_and_consume,
    write_pages,
)

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    import pypdfium2 as pdfium
    from liteparse import LiteParse
    from liteparse.types import (
        ExtractedImage,
        PageComplexityStats,
        PageError,
        ParsedPage,
        ParseResult,
    )

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
    def __init__(self, config: LiteParsePipelineConfig):
        super().__init__(config)

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncIterable[Result]:
        tessdata_path = self._config.tessdata_path
        if tessdata_path is None:
            tessdata_path = os.getenv("TESSDATA_PREFIX")
        if tessdata_path is None:
            msg = "couldn't find tessdata path in config nor TESSDATA_PREFIX env var"
            raise RuntimeError(msg)
        self._tessdata_path = Path(tessdata_path)
        if self._config.detect_page_orientation:
            logger.info("reading docs page orientation detection...")
            batches = await self._batch_per_orientation(docs)
        else:
            batches = chunk_docs(docs, self._config.page_batch_size)
            batches = ((None, (c,)) for c in batches)
        logger.info("parsing pages...")
        async for res in self._parse(batches, output_format, output_path):
            yield res

    async def _batch_per_orientation(
        self, docs: Iterable[InputDoc]
    ) -> list[OrientedBatch]:
        logger.info("computing page complexities...")
        complexities = await self._compute_complexities(docs)
        batches = [b async for b in self._batch_with_orientation(complexities)]
        return batches

    async def _compute_complexities(
        self, docs: Iterable[InputDoc]
    ) -> list[tuple[InputDoc, list["PageComplexityStats"]]]:
        docs = list(docs)
        batches = (pages for pages in chunk_docs(docs, self._config.page_batch_size))
        aws = (_compute_batch_complexities(batch) for batch in batches)
        batches = defaultdict(list)
        async for pages, res in _run_with_concurrency(aws, self._config.n_cpus):
            batches[pages.doc_idx].extend(res)
        batches = [
            (docs[doc_idx], sorted(comps, key=lambda c: c.page_number))
            for doc_idx, comps in batches.items()
        ]
        return batches

    async def _batch_with_orientation(
        self, complexities: list[tuple[InputDoc, list["PageComplexityStats"]]]
    ) -> AsyncIterable[OrientedBatch]:
        batch_size = self._config.page_batch_size
        batches_per_orientation = defaultdict(list)
        not_pdfs = [doc for doc, comps in complexities if comps is None]
        for doc in not_pdfs:
            for batch in chunk_docs([doc], batch_size):
                rng = _liteparse_range(batch.page_range)
                batches_per_orientation[(rng, None)].append(batch)
        complexities = [
            (doc, comps) for doc, comps in complexities if comps is not None
        ]
        logger.info("reading complex pages orientation...")
        offset = len(not_pdfs)
        with self._executor() as executor:
            for doc, comps in complexities:
                pages_by_orientation = await _doc_pages_by_orientation(
                    doc, comps, executor, self._tessdata_path
                )
                for orientation, pages in pages_by_orientation.items():
                    for batch in batched(pages, batch_size, strict=False):
                        batch = _pages_from_complexities(doc, offset, *batch)  # noqa: PLW2901
                        rng = _liteparse_range_from_pages(*batch)
                        batches_per_orientation[(rng, orientation)].append(batch)
                offset += 1
        # We yield pages per orientation only here to make sure to yield
        # (orientation, range) in the most regular way and avoid reload
        for (_, orientation), batches in batches_per_orientation.items():
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
        # Buffer partial conversion to filesystem as large docs are chunked into pieces
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
        parsers = []
        close_parsers_tasks = []
        # Prevent more than n_cpu concurrent processing
        sem = asyncio.Semaphore(max(1, self._config.n_cpus - 1))
        # Results may return in arbitrary order, we need to wait until parser is not
        # used any longer before
        tracker = UsageTracker()
        current_key = None
        publish_tasks = []
        with _close_parsers(parsers):
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
                            close_t = tg.create_task(_await_and_close(tracker, parser))
                            close_parsers_tasks.append(close_t)
                        logger.debug("loading parser for %s", key)
                        parser = self._make_parser(output_format, key, n_pages=n_pages)
                        parsers.append(parser)
                        parser.__enter__().warm_up()
                        current_key = key
                    await sem.acquire(), await tracker.acquire(parser)
                    task = self._convert_and_queue(parser, batch, queue, sem, tracker)
                    publish_tasks.append(tg.create_task(task))
                await asyncio.gather(*publish_tasks)
                queue.put_nowait(None)
                await asyncio.gather(*close_parsers_tasks)

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

    async def _convert_and_queue(
        self,
        parser: "LiteParse",
        pages: tuple[ProcessedPages],
        queue: asyncio.Queue,
        sem: asyncio.Semaphore,
        tracker: UsageTracker,
    ) -> None:
        res = await parser.aparse(pages[0].doc.path)
        sem.release(), await tracker.release(parser)
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
        pool_size = max(1, self._config.n_cpus - 1)
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

    @contextmanager
    def _executor(self) -> Generator[ProcessPoolExecutor]:
        executor = ProcessPoolExecutor(
            max_workers=self._config.n_cpus, mp_context=get_context("spawn")
        )
        with executor:
            yield executor

    def _result_buffer(self) -> ResultBuffer:

        buffer = ResultBuffer(
            max_size_bytes=self._config.result_buffer.max_size,
            root=self._config.result_buffer.root,
            save_fn=_save_conversion_result,
            load_fn=_load_conversion_result,
        )
        return buffer


async def _compute_batch_complexities(
    pages: ProcessedPages,
) -> tuple[ProcessedPages, list["PageComplexityStats"]]:
    from liteparse.parser import LiteParse  # noqa: PLC0415

    target_pages = _liteparse_range_from_pages(pages)
    parser = LiteParse(ocr_enabled=False, target_pages=target_pages)
    with parser:
        comps = await asyncio.to_thread(parser.is_complex, pages.doc.path)
    return pages, comps


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
def _close_parsers(parsers: Iterable["LiteParse"]) -> Generator[None]:
    try:
        yield
    finally:
        for p in parsers:
            p.close()


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


async def _doc_pages_by_orientation(
    doc: InputDoc,
    complexities: list["PageComplexityStats"],
    executor: ProcessPoolExecutor,
    tessdata_path: Path,
) -> dict[int, list["PageComplexityStats"]]:
    pages_by_orientation = defaultdict(list)
    complexities = [(p, _should_detect_orientation(p)) for p in complexities]
    for p, should_detect in complexities:
        if not should_detect:
            pages_by_orientation[None].append(p)
    complexities = [p for p, should_detect in complexities if should_detect]
    if not complexities:
        return pages_by_orientation
    futs = []
    for c in complexities:
        fut = executor.submit(_detect_page_orientation, doc.path, c, tessdata_path)
        futs.append(fut)
    for fut in futures.as_completed(futs):
        orientation, p = fut.result()
        pages_by_orientation[orientation].append(p)
    return pages_by_orientation


async def _detect_complexity(
    parser: "LiteParse", doc: InputDoc
) -> tuple[InputDoc, list["PageComplexityStats"] | None]:
    if doc.ext != SupportedExt.PDF:
        return doc, None
    complexities = await asyncio.to_thread(parser.is_complex, doc.path)
    return doc, complexities


def _detect_page_orientation(
    doc: Path, complexity: "PageComplexityStats", tessdata_path: Path
) -> tuple[int, "PageComplexityStats"]:
    pdf_doc = _PDF_DOC_CACHE.get(doc)
    page = pdf_doc.get_page(complexity.page_number - 1)
    page = page.render(scale=3)
    osd_reader = _get_osd_reader(tessdata_path)
    osd_reader.SetImage(page.to_pil())
    orientation = osd_reader.DetectOrientationScript()
    return _clipped_orientation(orientation["orient_deg"]), complexity


def _clipped_orientation(angle: float) -> int:
    return min((abs(angle - o) % 360, o) for o in _CLIPPED_ORIENTATIONS)[1]


async def _await_and_close(tracker: UsageTracker, parser: "LiteParse") -> None:
    await tracker.wait_until_free(parser)
    parser.close()


def _get_osd_reader(tessdata_path: Path) -> "tesserocr.PyTessBaseAPI":
    import tesserocr  # noqa: PLC0415

    global _TESSERACT
    if _TESSERACT is None:
        osd_reader = tesserocr.PyTessBaseAPI(
            str(tessdata_path),
            lang="osd",
            oem=tesserocr.OEM.DEFAULT,
            psm=tesserocr.PSM.OSD_ONLY,
        )
        _TESSERACT = osd_reader
    return _TESSERACT


class _PDFDocCache:
    def __init__(self):
        self._path: Path | None = None
        self._doc: pdfium.PdfDocument | None = None

    def get(self, path: Path) -> "pdfium.PdfDocument":
        import pypdfium2 as pdfium  # noqa: PLC0415

        if path != self._path:
            if self._doc is not None:
                self._doc.close()
            self._doc = pdfium.PdfDocument(path)
            self._path = path
        return self._doc

    def __del__(self):
        if self._doc is not None:
            self._doc.close()


# we have to use a global cache because pdfnium is not thread safe and not
# pickleable
_PDF_DOC_CACHE = _PDFDocCache()
# tesseract is also not pickleable
_TESSERACT: "tesserocr.PyTessBaseAPI | None" = None
