import asyncio
import json
import logging
import operator
import shutil
import tempfile
from collections.abc import AsyncIterable, Iterable
from contextlib import AbstractContextManager
from functools import partial, reduce
from pathlib import Path
from typing import Any, Self

from docling.datamodel.document import ConversionAssets
from docling.datamodel.pipeline_options import PipelineOptions
from docling.datamodel.settings import (
    DEFAULT_PAGE_RANGE,
    AppSettings,
    scoped,
)
from docling.document_converter import DocumentConverter, FormatOption
from docling_core.types import DoclingDocument

# TODO: this is long to load improve it
from docling_core.types.doc import ImageRefMode
from extract_core import (
    BaseModel,
    DoclingFormatOption,
    DoclingPipelineConfig,
    Error,
    InputDoc,
    MarkdownDoc,
    OutputFormat,
    Pipeline,
    PipelineType,
    Result,
    Status,
)
from icij_common.pydantic_utils import merge_configs
from pydantic import ConfigDict, field_serializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler

from .constants import ARTIFACTS, DEFAULT_MD_PAGE_SEP
from .utils import (
    Range,
    ResultBuffer,
    batch_per_pages,
    chdir,
    path_to_artifacts_dirname,
    write_pages,
)

logger = logging.getLogger(__name__)

DOCLING_DEFAULT_ARTIFACTS_PATH = Path.home().joinpath(".cache", "docling", "models")


@Pipeline.register(PipelineType.DOCLING)
class DoclingPipeline(Pipeline):
    def __init__(self, config: DoclingPipelineConfig):
        super().__init__(config)
        format_options = {
            k: v.to_docling(self._device)
            for k, v in self._config.format_options.items()
        }
        logger.info(
            "resolved format options to: %s",
            lambda: partial(json.dumps, format_options, indent=2),
        )
        allowed_format = [
            f.to_docling() for f in DoclingPipelineConfig.supported_exts()
        ]
        self._converter = DocumentConverter(
            allowed_formats=allowed_format, format_options=format_options
        )

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncIterable[Result]:
        settings = self._config.settings
        logger.info("starting extraction with settings: %s", settings)
        with self._scoped_settings, self._result_buffer as buffer:
            max_page_batches = settings.perf.max_page_batches
            page_batch_size = settings.perf.page_batch_size
            batches = batch_per_pages(
                docs, page_batch_size, max_page_batches=max_page_batches
            )
            for batch in batches:
                page_range = list({pages.page_range for pages in batch})
                if len(page_range) > 1:
                    msg = "convert_all only accept 1 page range for all docs"
                    raise ValueError(msg)
                page_range = page_range[0]
                page_range = _docling_range(page_range)
                docling_docs = (pages.doc.to_docling() for pages in batch)
                outputs = self._converter.convert_all(
                    docling_docs, raises_on_error=False, page_range=page_range
                )
                processed = iter(batch)
                sentinel = object()
                while True:
                    res = await asyncio.to_thread(next, outputs, sentinel)
                    if res is sentinel:
                        break
                    pages = next(processed)
                    buffer.add(pages, res)
                    if buffer.is_complete(pages.doc_idx):
                        doc_pages = buffer.pop_complete(pages.doc_idx)
                        yield _to_result(
                            doc_pages, pages.doc, output_format, output_path=output_path
                        )

    @property
    def _scoped_settings(self) -> AbstractContextManager[AppSettings]:
        settings = self._config.settings
        docling_settings = scoped(
            perf=settings.perf, debug=settings.debug, inference=settings.inference
        )
        return docling_settings

    @property
    def _result_buffer(self) -> ResultBuffer:
        buffer = ResultBuffer(
            max_size_bytes=self._config.result_buffer.max_size,
            root=self._config.result_buffer.root,
            save_fn=_save_conversion_result,
            load_fn=_load_conversion_result,
        )
        return buffer


def _save_conversion_result(res: ConversionAssets, path: Path) -> None:
    return res.save(filename=path)


def _load_conversion_result(path: Path) -> ConversionAssets:
    return ConversionAssets.load(path)


def _to_result(
    buffer: list[ConversionAssets],
    input_doc: InputDoc,
    output_format: OutputFormat,
    output_path: Path,
    **kwargs,
) -> Result:
    import numpy as np  # noqa: PLC0415

    if not buffer:
        raise ValueError("empty buffer")
    merged = DoclingDocument.concatenate([res.document for res in buffer])
    output_path.mkdir(parents=True, exist_ok=True)
    status = reduce(operator.iadd, (Status.from_docling(d.status) for d in buffer))
    # TODO: implement confidence weight
    confidence = np.mean([res.confidence.mean_score for res in buffer])
    output = None
    if status.allows_conversion:
        match output_format:
            case OutputFormat.MARKDOWN:
                output = _to_markdown_doc(
                    merged,
                    input_path=input_doc.path,
                    output_path=output_path,
                    confidence=confidence,
                    **kwargs,
                )
            case _:
                raise NotImplementedError(f"unsupported output format {output_format}")
    errors = [Error.from_docling(e) for res in buffer for e in res.errors]
    return Result(input=input_doc, status=status, errors=errors, output=output)


def _to_markdown_doc(
    doc: DoclingDocument,
    input_path: Path,
    *,
    output_path: Path,
    page_sep: str = DEFAULT_MD_PAGE_SEP,
    confidence: float,
    **kwargs,
) -> MarkdownDoc:
    # TODO: Should we add a hash to avoid collision between files with same names
    #  nested in the tree structured
    md_dir_name = path_to_artifacts_dirname(input_path)
    md_dir = output_path / md_dir_name
    if md_dir.exists():
        raise FileExistsError(f"directory {md_dir} already exists")
    # Let's avoid issue of duplicated input file names flattened top level
    md_filename = md_dir_name + OutputFormat.MARKDOWN
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_dir = Path(td)
        md_path = tmp_dir / md_filename
        current_page_path = tmp_dir / "page.md"
        with chdir(tmp_dir):
            # We do a chdir to bypass a Docling bug which only allows to maintain
            # relative image ref when saving the markdown to a relative path
            pages = _docling_pages_it(doc, current_page_path, **kwargs)
            with md_path.open("wb") as f:
                pages = write_pages(pages, page_sep, f)
        # Clean up the tmp page file before move everything to the end destination
        current_page_path.unlink(missing_ok=True)
        shutil.move(tmp_dir, md_dir)
    return MarkdownDoc(path=Path(md_dir_name), pages=pages, confidence=confidence)


def _docling_pages_it(
    doc: DoclingDocument, output_path: Path, **kwargs
) -> Iterable[str]:
    n_pages = len(doc.pages)
    for page_i in range(n_pages):
        doc.save_as_markdown(
            output_path,
            page_no=page_i + 1,
            image_mode=ImageRefMode.REFERENCED,
            artifacts_dir=Path(ARTIFACTS),
            **kwargs,
        )
        content = output_path.read_text()
        yield content


class SerializableFormatOptions(DoclingFormatOption):
    # Utility class to serialize Python format options into a JSON which can be
    # correctly deserialized into a docling FormatOption
    # via DoclingFormatOption.to_docling
    model_config = merge_configs(
        BaseModel.model_config, ConfigDict(polymorphic_serialization=True)
    )

    pipeline_options: PipelineOptions | None = None

    @classmethod
    def from_docling(cls, format_opts: FormatOption) -> Self:
        return cls(
            pipeline_cls=format_opts.pipeline_cls.__name__,
            pipeline_options=format_opts.pipeline_options,
            backend=format_opts.backend.__name__,
            backend_options=format_opts.backend_options,
        )

    @field_serializer("pipeline_options", mode="wrap")
    def _serialize_pipeline_opts(
        self, v: PipelineOptions | None, handler: SerializerFunctionWrapHandler
    ) -> Any:
        if v is None:
            return handler(v)
        serialized = handler(v)
        picture_desc_opts = getattr(v, "picture_description_options", None)
        if picture_desc_opts is not None:
            if "picture_description_options" not in serialized:
                serialized["picture_description_options"] = dict()
            serialized["picture_description_options"]["kind"] = picture_desc_opts.kind
        ocr_opts = getattr(v, "ocr_options", None)
        if ocr_opts is not None:
            if "ocr_options" not in serialized:
                serialized["ocr_options"] = dict()
            serialized["ocr_options"]["kind"] = ocr_opts.kind
        layout_opts = getattr(v, "layout_options", None)
        if layout_opts is not None:
            if "layout_options" not in serialized:
                serialized["layout_options"] = dict()
            serialized["layout_opts"]["kind"] = layout_opts.kind
        table_structure_opts = getattr(v, "table_structure_options", None)
        if table_structure_opts is not None:
            if "table_structure_options" not in serialized:
                serialized["table_structure_options"] = dict()
            serialized["table_structure_options"]["kind"] = table_structure_opts.kind
        return serialized


def _docling_range(rng: Range | None) -> tuple[int, int]:
    if rng is None:
        return DEFAULT_PAGE_RANGE
    return (rng[0] + 1, rng[1] + 1)
