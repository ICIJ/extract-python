from collections.abc import AsyncGenerator, Iterable
from functools import partial
from pathlib import Path
from typing import ClassVar

from mineru.backend.pipeline.model_json_to_middle_json import result_to_middle_json
from mineru.backend.pipeline.pipeline_analyze import doc_analyze
from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make
from mineru.data.data_reader_writer import FileBasedDataWriter
from mineru.utils.enum_class import MakeMode
from pydantic import Field
from pydantic_extra_types.language_code import LanguageAlpha2
from pypdfium2 import PdfDocument
from typing_extensions import Self

from extract_python.constants import ARTIFACTS, DEFAULT_MD_PAGE_SEP, MINER_U_GROUP
from extract_python.core import Pipeline, PipelineConfig, PipelineType
from extract_python.objects import (
    BaseModel,
    ConversionOutput,
    InputDoc,
    OutputFormat,
    PageIndexes,
    Result,
    Status,
)
from extract_python.utils import path_to_artifacts_dirname

_MINER_U_CONVERSION_ERRORS = tuple()


class MinerUConfig(BaseModel):
    enable_formula_extraction: bool = True
    enable_table_extraction: bool = True
    # TODO: use enum or literal here
    parse_method: str = "auto"

    def as_mineru_dict(self) -> dict:
        return {
            "formula_enable": self.enable_formula_extraction,
            "table_enable": self.enable_table_extraction,
            "parse_method": self.parse_method,
        }


@PipelineConfig.register()  # noqa: F821
class MinerUPipelineConfig(PipelineConfig):  # noqa: F821
    pipeline: PipelineType = Field(frozen=True, default=PipelineType.MINER_U)
    task_group: ClassVar[str] = Field(frozen=True, default=MINER_U_GROUP)

    config: MinerUConfig = Field(frozen=True, default=MinerUConfig())
    language: LanguageAlpha2 = Field(frozen=True, default="en")


@Pipeline.register(PipelineType.MINER_U)
class MinerUPipeline(Pipeline):
    def __init__(self, config: MinerUConfig, language: str):
        self._config = config
        self._language = language

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]:
        docs = list(docs)
        # TODO: exclude files which are not pdf and return an error
        pdfs_bytes = [d.path.read_bytes() for d in docs]
        pdfs_langs = [self._language for _ in pdfs_bytes]
        # TODO: we should only process valid PDFs
        processing_results = zip(
            *doc_analyze(pdfs_bytes, pdfs_langs, **self._config.as_mineru_dict())
        )
        for doc, res in zip(docs, processing_results):
            parsing_result, pdf_images, pdf_doc, _, _ = res
            yield _process_doc(
                doc,
                language=self._language,
                parsing_result=parsing_result,
                pdf_images=pdf_images,
                pdf_doc=pdf_doc,
                formula_enabled=self._config.enable_formula_extraction,
                output_format=output_format,
                output_path=output_path,
            )

    @classmethod
    def _from_config(cls, config: MinerUPipelineConfig) -> Self:
        return cls(config.config, language=config.language)


def _process_doc(
    doc: InputDoc,
    *,
    language: str,
    parsing_result: dict,
    pdf_images: list[dict],
    pdf_doc: PdfDocument,
    formula_enabled: bool,
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
            im_rel_dir = artifacts_dir.relative_to(md_dir)
            dump_content_fn = partial(
                _dump_md_content,
                output_path=output_path,
                md_path=md_path,
                im_dir=im_rel_dir,
            )
        case _:
            raise NotImplementedError(f"unsupported output format {output_format}")
    middle_json = result_to_middle_json(
        parsing_result,
        pdf_images,
        pdf_doc,
        im_writer,
        language,
        ocr_enable=True,
        formula_enabled=formula_enabled,
    )
    pdf_info = middle_json["pdf_info"]
    output = dump_content_fn(pdf_info)
    input_doc = doc.without_content()
    return Result(input=input_doc, status=Status.SUCCESS, output=output)


def _dump_md_content(
    pdf_info: list[dict],
    *,
    page_sep: str = DEFAULT_MD_PAGE_SEP,
    output_path: Path,
    md_path: Path,
    im_dir: Path,
    md_make_mode: str = MakeMode.MM_MD,
) -> ConversionOutput:
    total_length = 0
    end_indices = []
    with md_path.open("w") as f:
        n_pages = len(pdf_info)
        for page_i, page in enumerate(pdf_info):
            content = union_make(
                [page], make_mode=md_make_mode, img_buket_path=str(im_dir)
            )
            if page_i > 0:
                content += "\n"
            if page_i < n_pages - 1:
                content += page_sep
            total_length += len(content)
            end_indices.append(total_length)
            f.write(content)
            f.flush()
    end_indices = PageIndexes.from_page_end_indices(end_indices)
    output_path = md_path.parent.relative_to(output_path)
    output = ConversionOutput(path=output_path, pages=end_indices)
    return output
