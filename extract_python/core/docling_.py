import os
import shutil
import tempfile
from collections.abc import AsyncGenerator, Generator, Iterable, Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import Any, Literal, Self, TypeVar

from docling.backend.abstract_backend import AbstractDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    PdfPipelineOptions,
    PipelineOptions,
    VlmPipelineOptions,
)
from docling.document_converter import DocumentConverter, FormatOption
from docling.models.factories import get_ocr_factory
from docling.pipeline.base_pipeline import BasePipeline
from docling_core.types.doc import ImageRefMode
from docling_core.types.io import DocumentStream
from icij_common.pydantic_utils import safe_copy
from icij_common.registrable import FromConfig
from pydantic import Field, model_validator

from extract_python.constants import DEFAULT_MD_PAGE_SEP
from extract_python.core.pipeline import Pipeline, PipelineConfig, PipelineType
from extract_python.objects import (
    BaseModel,
    Error,
    InputDoc,
    MarkdownDoc,
    OutputFormat,
    Result,
    Status,
)
from extract_python.utils import (
    all_subclasses,
    map_and_preserve,
    path_to_artifacts_dirname,
)

DEFAULT_ARTIFACTS_PATH = Path.home().joinpath(".cache", "docling", "models")


class _PdfPipelineOptions(PdfPipelineOptions):
    generate_picture_images: bool = Field(default=True, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def validate_ocr_options(cls, data: Any) -> Any:
        if isinstance(data, dict):
            ocr_options = data.get("ocr_options")
            if not isinstance(ocr_options, dict):
                return data
            allow_external_plugins = ocr_options.get("allow_external_plugins", False)
            ocr_factory = get_ocr_factory(allow_external_plugins=allow_external_plugins)
            kind = ocr_options.pop("kind")
            data["ocr_options"] = ocr_factory.create_options(kind=kind, **ocr_options)
        return data


OptionsByPipeline = list[
    tuple[Literal["pdf"], _PdfPipelineOptions]
    | tuple[Literal["vlm"], VlmPipelineOptions]
]


def _default_pipeline_options() -> OptionsByPipeline:
    pipeline_options = _PdfPipelineOptions(ocr_options=EasyOcrOptions())
    return [("pdf", pipeline_options), ("vlm", VlmPipelineOptions())]


class DoclingFormatOption(BaseModel):
    pipeline_cls: str
    backend_cls: str

    def to_docling(
        self, pipeline_options: dict[Literal["pdf", "vlm"], PipelineOptions]
    ) -> FormatOption:
        pipeline_cls = _find_subcls(BasePipeline, self.pipeline_cls)
        backend_cls = _find_subcls(AbstractDocumentBackend, self.backend_cls)
        if "vlm" in self.pipeline_cls.lower():
            pipeline_options = pipeline_options.get("vlm")
            if pipeline_options is not None:
                pipeline_options = VlmPipelineOptions.model_validate(pipeline_options)
        elif "pdf" in self.pipeline_cls.lower():
            pipeline_options = pipeline_options.get("pdf")
            if pipeline_options is not None:
                pipeline_options = _PdfPipelineOptions.model_validate(pipeline_options)
        else:
            raise ValueError(
                f"invalid pipeline_cls: {pipeline_cls}, expected a VLM or PDF pipeline"
            )
        return FormatOption(
            pipeline_cls=pipeline_cls,
            pipeline_options=pipeline_options,
            backend=backend_cls,
        )


@cache
def _default_format_options() -> dict[InputFormat, DoclingFormatOption]:
    supported_fmt = {InputFormat.PDF}
    return {
        fmt: DoclingFormatOption(
            pipeline_cls=opt.pipeline_cls.__name__, backend_cls=opt.backend.__name__
        )
        for fmt, opt in DocumentConverter().format_to_options.items()
        if fmt in supported_fmt
    }


T = TypeVar("T")


def _find_subcls(cls: type[T], name: str) -> type[T]:
    for c in all_subclasses(cls):
        if c.__name__ == name:
            return c
    raise ValueError(f"unknown {cls.__name__} subclass {name}")


@PipelineConfig.register()
class DoclingPipelineConfig(PipelineConfig):
    pipeline: PipelineType = Field(frozen=True, default=PipelineType.DOCLING)
    test: bool = False

    pipeline_options: OptionsByPipeline = Field(
        default_factory=_default_pipeline_options
    )
    format_options: dict[InputFormat, DoclingFormatOption] = Field(
        default_factory=_default_format_options
    )

    @model_validator(mode="after")
    def test_default_artifact_dir(self) -> Self:
        if not self.test:
            for i, (k, v) in enumerate(self.pipeline_options):
                self.pipeline_options[i] = (
                    k,
                    safe_copy(v, update={"artifacts_path": DEFAULT_ARTIFACTS_PATH}),
                )
        return self

    def to_format_options(self) -> dict[InputFormat, FormatOption]:
        pipeline_options = dict(self.pipeline_options)
        return {
            InputFormat(f): opt.to_docling(pipeline_options)
            for f, opt in self.format_options.items()
        }


@Pipeline.register(PipelineType.DOCLING)
class DoclingPipeline(Pipeline):
    def __init__(self, format_options: dict[InputFormat, FormatOption] | None = None):
        self._convert = DocumentConverter(format_options=format_options)

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]:
        docs, path_or_streams = map_and_preserve(_to_docling, docs)
        outputs = self._convert.convert_all(path_or_streams, raises_on_error=False)
        for doc, res in zip(docs, outputs):
            yield _to_result(res, doc, output_format, output_path=output_path)

    @classmethod
    def _from_config(cls, config: DoclingPipelineConfig) -> FromConfig:
        return cls(config.to_format_options())


def _to_docling(docs: Iterable[InputDoc]) -> Iterator[Path | DocumentStream]:
    for d in docs:
        yield d.to_docling()


def _to_result(
    res: ConversionResult,
    input_document: InputDoc,
    output_format: OutputFormat,
    output_path: Path,
    **kwargs,
) -> Result:
    output_path.mkdir(parents=True, exist_ok=True)
    output = None
    status = Status.from_docling(res.status)
    if status.allows_conversion:
        match output_format:
            case OutputFormat.MARKDOWN:
                output = _to_markdown_doc(res, output_path, **kwargs)
            case _:
                raise NotImplementedError(f"unsupported output format {output_format}")
    errors = [Error.from_docling(e) for e in res.errors]
    input_doc = input_document.without_content()
    return Result(input=input_doc, status=status, errors=errors, output=output)


def _to_markdown_doc(
    res: ConversionResult,
    output_path: Path,
    page_sep: str = DEFAULT_MD_PAGE_SEP,
    **kwargs,
) -> MarkdownDoc:
    # TODO: Should we add a hash to avoid collision between files with same names
    #  nested in the tree structured
    md_dir_name = path_to_artifacts_dirname(res.input.file)
    md_dir = output_path / md_dir_name
    # Let's avoid issue of duplicated input file names flattened top level
    md_filename = md_dir_name + OutputFormat.MARKDOWN
    total_length = 0
    n_pages = len(res.pages)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_dir = Path(td)
        page_path = Path("page.md")
        # We do a chdir to bypass a Docling bug which only allows to maintain relative
        # image ref when saving the markdown to a relative path
        with (tmp_dir / md_filename).open("w") as f, chdir(tmp_dir):
            pages = [0]
            for page_i in range(n_pages):
                res.document.save_as_markdown(
                    page_path,
                    page_no=page_i + 1,
                    image_mode=ImageRefMode.REFERENCED,
                    **kwargs,
                )
                content = page_path.read_text()
                if page_i > 0:
                    content += "\n"
                if page_i < n_pages - 1:
                    content += page_sep
                total_length += len(content)
                pages.append(total_length)
                f.write(content)
                f.flush()
                page_path.unlink()
        shutil.move(tmp_dir, md_dir)
    return MarkdownDoc(path=Path(md_dir_name), pages=pages)


@contextmanager
def chdir(path: Path) -> Generator[None, None, None]:
    cwd = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)
