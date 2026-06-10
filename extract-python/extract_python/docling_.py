import shutil
import tempfile
from collections.abc import AsyncGenerator, Iterable, Iterator
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import ConversionResult
from docling.document_converter import DocumentConverter

# TODO: this is long to load improve it
from docling_core.types.doc import ImageRefMode
from docling_core.types.io import DocumentStream
from extract_core import (
    DoclingFormatOption,
    DoclingPipelineConfig,
    Error,
    InputDoc,
    MarkdownDoc,
    OutputFormat,
    PageIndexes,
    Pipeline,
    PipelineType,
    Result,
    Status,
)
from icij_common.registrable import FromConfig

from .constants import ARTIFACTS, DEFAULT_MD_PAGE_SEP
from .utils import chdir, map_and_preserve, path_to_artifacts_dirname

DOCLING_DEFAULT_ARTIFACTS_PATH = Path.home().joinpath(".cache", "docling", "models")


@Pipeline.register(PipelineType.DOCLING)
class DoclingPipeline(Pipeline):
    def __init__(
        self, format_options: dict["InputFormat", DoclingFormatOption] | None = None
    ):
        format_options = {k: v.to_docling() for k, v in format_options.items()}
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
