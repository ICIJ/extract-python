import json
import shutil
from collections.abc import AsyncGenerator, Callable, Iterable
from copy import copy
from enum import StrEnum
from functools import cache, partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, Self

from mineru.backend.pipeline.pipeline_middle_json_mkcontent import (
    union_make as pipeline_union_make,
)
from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make as vlm_union_make
from mineru.cli.common import aio_do_parse
from mineru.utils.enum_class import MakeMode
from pydantic import Field
from pydantic_extra_types.language_code import LanguageAlpha2

from .constants import ARTIFACTS, DEFAULT_MD_PAGE_SEP, MINER_U_GROUP
from .objects import (
    BaseModel,
    ConversionOutput,
    InputDoc,
    OutputFormat,
    PageIndexes,
    Result,
    Status,
    SupportedExt,
)
from .pipeline import Pipeline, PipelineConfig, PipelineType
from .utils import path_to_artifacts_dirname

_MINER_U_CONVERSION_ERRORS = tuple()
MDMakeFunction = Callable[[list, str, str], str | None]


class MinerUBackend(StrEnum):
    PIPELINE = "pipeline"
    VLM = "vlm"


class MinerUConfig(BaseModel):
    backend: MinerUBackend = MinerUBackend.PIPELINE
    enable_formula_extraction: bool = True
    enable_table_extraction: bool = True
    # TODO: use enum or literal here
    parse_method: str = "auto"

    default_kwargs: ClassVar[dict] = {
        "server_url": None,
        # We don't dump md directly we process, we dump the middle json in order to be
        # able to get page indexes
        "parse_method": "auto",
        "dump_md": False,
        "dump_middle_json": True,
        "f_draw_layout_bbox": False,
        "f_draw_span_bbox": False,
        "f_dump_model_output": False,  # might be useful for debug though
        "f_dump_orig_pdf": False,
        "f_dump_content_list": False,  # might be useful for debug though
        "start_page_id": 0,
        "f_make_md_mode": MakeMode.MM_MD,
        "image_analysis": True,
        "end_page_id": None,
        "client_side_output_generation": False,
    }

    def as_parse_kwargs(self) -> dict[str, Any]:
        kwargs = copy(self.default_kwargs)
        kwargs["backend"] = self.backend
        kwargs["parse_method"] = self.parse_method
        kwargs["formula_enable"] = self.enable_formula_extraction
        kwargs["table_enable"] = self.enable_table_extraction
        return kwargs


@PipelineConfig.register()  # noqa: F821
class MinerUPipelineConfig(PipelineConfig):  # noqa: F821
    pipeline: PipelineType = Field(frozen=True, default=PipelineType.MINER_U)
    task_group: ClassVar[str] = Field(frozen=True, default=MINER_U_GROUP)

    config: MinerUConfig = Field(frozen=True, default=MinerUConfig())
    language: LanguageAlpha2 = Field(frozen=True, default="en")

    @classmethod
    @cache
    def supported_exts(cls) -> set[SupportedExt]:
        return {
            SupportedExt.PDF,
            SupportedExt.DOCX,
            SupportedExt.PPTX,
            SupportedExt.XLSX,
        }


@Pipeline.register(PipelineType.MINER_U)
class MinerUPipeline(Pipeline):
    def __init__(self, config: MinerUConfig, language: str):
        self._config = config
        self._language = language
        self._md_make_fn = _parse_md_make_fn(config.backend)

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]:
        docs = list(docs)
        # TODO: exclude files which are not pdf and return an error
        pdfs_bytes = [d.path.read_bytes() for d in docs]
        pdfs_names = [d.path.name for d in docs]
        p_lang_list = [self._language for _ in pdfs_names]
        # TODO: we should only process valid PDFs
        with TemporaryDirectory(prefix="mineru-") as workdir:
            workdir = Path(workdir)  # noqa: PLW2901
            await aio_do_parse(
                output_dir=workdir,
                pdf_file_names=pdfs_names,
                pdf_bytes_list=pdfs_bytes,
                p_lang_list=p_lang_list,
                **self._config.as_parse_kwargs(),
            )
            res_paths = [
                _revert_mineru_output(workdir, pdf_filename=p) for p in pdfs_names
            ]
            for doc, res_path in zip(docs, res_paths, strict=True):
                yield _process_doc(
                    doc,
                    md_make_fn=self._md_make_fn,
                    res_path=res_path,
                    output_format=output_format,
                    output_path=output_path,
                )

    @classmethod
    def _from_config(cls, config: MinerUPipelineConfig) -> Self:
        return cls(config.config, language=config.language)


def _revert_mineru_output(output_dir: Path, *, pdf_filename: str) -> Path:
    output_path = output_dir / pdf_filename
    if not output_path.exists():
        msg = f"couldn't find result for {pdf_filename}"
        raise FileNotFoundError(msg)
    dirs = [p for p in output_path.iterdir() if p.is_dir()]
    if len(dirs) != 1:
        msg = f"expected exactly one result directory, found: {dirs}"
        raise ValueError(msg)
    return output_dir / dirs[0]


def _parse_md_make_fn(backend: MinerUBackend) -> MDMakeFunction:
    match backend:
        case MinerUBackend.PIPELINE:
            return pipeline_union_make
        case MinerUBackend.VLM:
            return vlm_union_make
        case _:
            raise ValueError(f"Unsupported backend: {backend}")


def _process_doc(
    doc: InputDoc,
    *,
    md_make_fn: MDMakeFunction,
    res_path: Path,
    output_format: OutputFormat,
    output_path: Path,
) -> Result:
    md_dir_name = path_to_artifacts_dirname(doc.path)
    md_dir = Path(output_path) / md_dir_name
    md_dir.mkdir(parents=True, exist_ok=False)
    artifacts_dir = md_dir / ARTIFACTS
    md_path = (md_dir / md_dir_name).with_suffix(OutputFormat.MARKDOWN.value)
    # Fail early
    match output_format:
        case OutputFormat.MARKDOWN:
            im_rel_dir = artifacts_dir.relative_to(md_dir)
            dump_content_fn = partial(
                _dump_md_content,
                md_make_fn=md_make_fn,
                output_path=output_path,
                md_path=md_path,
                im_dir=im_rel_dir,
            )
        case _:
            raise NotImplementedError(f"unsupported output format {output_format}")
    middle_json_path = res_path / f"{doc.path.name}_middle.json"
    middle_json = json.loads(middle_json_path.read_text())
    pdf_info = middle_json["pdf_info"]
    shutil.move(res_path / "images", artifacts_dir)
    output = dump_content_fn(pdf_info)
    input_doc = doc.without_content()
    return Result(input=input_doc, status=Status.SUCCESS, output=output)


def _dump_md_content(
    pdf_info: list[dict],
    *,
    md_make_fn: MDMakeFunction,
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
            content = md_make_fn([page], md_make_mode, str(im_dir))
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
