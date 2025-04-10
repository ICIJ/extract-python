from collections.abc import AsyncGenerator, Iterable
from functools import partial
from pathlib import Path
from typing import Any, ClassVar

from magic_pdf.config.enums import SupportedPdfParseMethod
from magic_pdf.config.make_content_config import DropMode, MakeMode
from magic_pdf.data.data_reader_writer import FileBasedDataReader, FileBasedDataWriter
from magic_pdf.data.dataset import PymuDocDataset
from magic_pdf.dict2md.ocr_mkcontent import union_make
from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
from magic_pdf.operators import PipeResult
from pydantic import Field
from typing_extensions import Self

from extract_python.constants import ARTIFACTS, DEFAULT_MD_PAGE_SEP, MINER_U_GROUP
from extract_python.core import Pipeline, PipelineConfig, PipelineType
from extract_python.core.utils import report_recoverable_errors
from extract_python.objects import (
    ConversionOutput,
    InputDoc,
    OutputFormat,
    Result,
    Status,
    SupportedExt,
)
from extract_python.utils import path_to_artifacts_dirname

_MINER_U_CONVERSION_ERRORS = tuple()


@PipelineConfig.register()  # noqa: F821
class MinerUPipelineConfig(PipelineConfig):  # noqa: F821
    pipeline: PipelineType = Field(frozen=True, default=PipelineType.MINER_U)
    task_group: ClassVar[str] = Field(frozen=True, default=MINER_U_GROUP)

    config: dict[str, Any] = dict()


@Pipeline.register(PipelineType.MINER_U)
class MinerUPipeline(Pipeline):
    def __init__(self, marker_config: dict[str, Any]):
        self._marker_config = marker_config

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]:
        for doc in docs:
            yield _process_doc(doc, output_format, output_path)

    @classmethod
    def _from_config(cls, config: MinerUPipelineConfig) -> Self:
        return cls(config.config)


@report_recoverable_errors(_MINER_U_CONVERSION_ERRORS)
def _process_doc(
    doc: InputDoc,
    output_format: OutputFormat,
    output_path: Path,
) -> Result:
    md_dir_name = path_to_artifacts_dirname(doc.path)
    md_dir = Path(output_path) / md_dir_name
    md_dir.mkdir(parents=True, exist_ok=False)
    artifacts_dir = md_dir / ARTIFACTS
    md_path = (md_dir / md_dir_name).with_suffix(OutputFormat.MARKDOWN.value)
    artifacts_dir.mkdir(parents=True)
    im_writer = FileBasedDataWriter(str(artifacts_dir))
    # Fail early
    match output_format:
        case OutputFormat.MARKDOWN:
            dump_content_fn = partial(
                _dump_md_content, output_path=output_path, md_path=md_path
            )
        case _:
            raise NotImplementedError(f"unsupported output format {output_format}")
    pipe_output = _apply_pipe(doc, im_writer)
    output = dump_content_fn(pipe_output)
    input_doc = doc.without_content()
    return Result(input=input_doc, status=Status.SUCCESS, output=output)


def _apply_pipe(doc: InputDoc, im_writer: FileBasedDataWriter) -> PipeResult:
    reader = FileBasedDataReader()
    doc_bytes = reader.read(str(doc.path))
    match doc.ext:
        case SupportedExt.PDF:
            dataset = PymuDocDataset(doc_bytes)
            if dataset.classify() == SupportedPdfParseMethod.OCR:
                infer_result = dataset.apply(doc_analyze, ocr=True)
                return infer_result.pipe_ocr_mode(im_writer)
            infer_result = dataset.apply(doc_analyze, ocr=False)
            return infer_result.pipe_txt_mode(im_writer)
        case _:
            raise ValueError(f"Unsupported input format {doc.ext}")


def _dump_md_content(
    pipe_result: PipeResult,
    *,
    page_sep: str = DEFAULT_MD_PAGE_SEP,
    output_path: Path,
    md_path: Path,
    drop_mode: DropMode.NONE = DropMode.NONE,
    md_make_mode: MakeMode = MakeMode.MM_MD,
) -> ConversionOutput:
    pdf_info_list = pipe_result._pipe_res["pdf_info"]
    total_length = 0
    pages = [0]
    with md_path.open("w") as f:
        n_pages = len(pdf_info_list)
        for page_i, page in enumerate(pdf_info_list):
            content = union_make([page], make_mode=md_make_mode, drop_mode=drop_mode)
            # MinerU doesn't provide fine-grained control on the image we have to handle
            # them the dirty way
            content = content.replace("![](/", f"![]({ARTIFACTS}/")
            if page_i > 0:
                content += "\n"
            if page_i < n_pages - 1:
                content += page_sep
            total_length += len(content)
            pages.append(total_length)
            f.write(content)
            f.flush()
    output_path = md_path.parent.relative_to(output_path)
    output = ConversionOutput(path=output_path, pages=pages)
    return output
