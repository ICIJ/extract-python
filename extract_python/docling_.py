import importlib
import shutil
import tempfile
from collections.abc import AsyncGenerator, Iterable, Iterator
from functools import cache
from pathlib import Path
from typing import Annotated, Any, ClassVar, Self, TypeVar, get_type_hints

from docling.backend.abstract_backend import AbstractDocumentBackend
from docling.datamodel.backend_options import BackendOptions

# Data model import are quick it's ok to leave it there
from docling.datamodel.base_models import FormatToExtensions, InputFormat
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    PdfPipelineOptions,
    PipelineOptions,
    ThreadedPdfPipelineOptions,
)
from docling.document_converter import DocumentConverter, FormatOption
from docling.pipeline.base_pipeline import BasePipeline

# TODO: this is long to load improve it
from docling_core.types.doc import ImageRefMode
from docling_core.types.io import DocumentStream
from icij_common.pydantic_utils import to_lower_snake_case
from icij_common.registrable import FromConfig
from pydantic import AfterValidator, BeforeValidator, Field, model_validator

from .constants import ARTIFACTS, DEFAULT_MD_PAGE_SEP
from .objects import (
    Error,
    InputDoc,
    MarkdownDoc,
    OutputFormat,
    PageIndexes,
    Result,
    Status,
    SupportedExt,
)
from .pipeline import Pipeline, PipelineConfig, PipelineType
from .utils import all_subclasses, chdir, map_and_preserve, path_to_artifacts_dirname

DOCLING_DEFAULT_ARTIFACTS_PATH = Path.home().joinpath(".cache", "docling", "models")


def _validate_pipeline_opts(v: "PipelineOptions") -> None:
    if isinstance(v, PdfPipelineOptions) and not v.generate_picture_images:
        msg = "generate_picture_images should be set to true"
        raise ValueError(msg)
    return v


T = TypeVar("T")


def _find_subcls(cls: type[T], name: str) -> type[T]:
    # Check if the class available
    for c in all_subclasses(cls):
        if c.__name__ == name:
            return c
    # Then apply ad-hoc search
    if "pipeline" in cls.__name__.lower():
        module_name = f"docling.pipeline.{to_lower_snake_case(name)}"
        try:
            module = importlib.import_module(module_name)
            return getattr(module, name)
        except (ModuleNotFoundError, AttributeError):
            pass
    raise ValueError(f"unknown {cls.__name__} subclass {name}")


def _find_init_arg_type(cls: type[Any], arg: str) -> type:
    hints = get_type_hints(cls.__init__)
    return hints[arg].__class__


def _resolve_pipeline_cls(v: Any) -> Any:
    if isinstance(v, str):
        return _find_subcls(BasePipeline, v)
    return v


def _resolve_backend(v: Any) -> Any:
    if isinstance(v, str):
        return _find_subcls(AbstractDocumentBackend, v)
    return v


class DoclingFormatOption(FormatOption):
    pipeline_cls: Annotated[
        str | type[BasePipeline], BeforeValidator(_resolve_pipeline_cls)
    ]
    pipeline_options: Annotated[
        dict | PipelineOptions | None, AfterValidator(_validate_pipeline_opts)
    ] = None
    backend: Annotated[
        str | type[AbstractDocumentBackend], BeforeValidator(_resolve_backend)
    ]
    backend_options: BackendOptions | None = None

    @model_validator(mode="after")
    def _resolve_pipeline_options(self) -> Self:
        if isinstance(self.pipeline_options, dict):
            option_cls = _find_init_arg_type(self.pipeline_cls, "pipeline_options")
            self.pipeline_options = option_cls.model_validate(self.pipeline_options)
        return self


@cache
def _default_format_opts() -> dict[InputFormat, DoclingFormatOption]:
    from docling.backend.docling_parse_backend import (  # noqa: PLC0415
        DoclingParseDocumentBackend,
    )
    from docling.pipeline.standard_pdf_pipeline import (  # noqa: PLC0415
        StandardPdfPipeline,
    )

    return {
        InputFormat.PDF: DoclingFormatOption(
            pipeline_cls=StandardPdfPipeline,
            backend=DoclingParseDocumentBackend,
            pipeline_options=ThreadedPdfPipelineOptions(
                ocr_options=EasyOcrOptions(), generate_picture_images=True
            ),
        ),
    }


class DoclingPipelineConfig(PipelineConfig):
    pipeline: ClassVar[PipelineType] = Field(frozen=True, default=PipelineType.DOCLING)

    format_options: dict[InputFormat, DoclingFormatOption | FormatOption] = Field(
        default_factory=_default_format_opts
    )

    @classmethod
    @cache
    def supported_exts(cls) -> set[SupportedExt]:
        unsupported = {InputFormat.AUDIO, InputFormat.METS_GBS, InputFormat.VTT}
        supported = set()
        for f in InputFormat:
            if f in unsupported:
                continue
            for ext in FormatToExtensions[f]:
                supported.add(SupportedExt(f".{ext.lower()}"))
        return supported


@Pipeline.register(PipelineType.DOCLING)
class DoclingPipeline(Pipeline):
    def __init__(
        self, format_options: dict["InputFormat", "FormatOption"] | None = None
    ):

        allowed_format = [
            f.to_docling() for f in DoclingPipelineConfig.supported_exts()
        ]
        self._converter = DocumentConverter(
            allowed_formats=allowed_format, format_options=format_options
        )

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]:
        docs, path_or_streams = map_and_preserve(_to_docling, docs)
        outputs = self._converter.convert_all(path_or_streams, raises_on_error=False)
        for doc, res in zip(docs, outputs, strict=True):
            yield _to_result(res, doc, output_format, output_path=output_path)

    @classmethod
    def _from_config(cls, config: DoclingPipelineConfig) -> FromConfig:
        return cls(config.format_options)


def _to_docling(docs: Iterable[InputDoc]) -> Iterator["Path | DocumentStream"]:
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
    if md_dir.exists():
        raise FileExistsError(f"directory {md_dir} already exists")
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
            end_indices = []
            for page_i in range(n_pages):
                res.document.save_as_markdown(
                    page_path,
                    page_no=page_i + 1,
                    image_mode=ImageRefMode.REFERENCED,
                    artifacts_dir=Path(ARTIFACTS),
                    **kwargs,
                )
                content = page_path.read_text()
                if page_i > 0:
                    content += "\n"
                if page_i < n_pages - 1:
                    content += page_sep
                total_length += len(content)
                end_indices.append(total_length)
                f.write(content)
                f.flush()
                page_path.unlink()
        shutil.move(tmp_dir, md_dir)
    pages = PageIndexes.from_page_end_indices(end_indices)
    return MarkdownDoc(path=Path(md_dir_name), pages=pages)
