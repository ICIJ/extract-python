from collections.abc import Callable
from copy import copy
from enum import StrEnum
from functools import cache
from typing import Any, ClassVar

from pydantic import Field
from pydantic_extra_types.language_code import LanguageAlpha2

from .configs import BasePipelineConfig, PipelineType
from .objects import BaseModel, SupportedExt

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

    def as_parse_kwargs(self) -> dict[str, Any]:
        kwargs = copy(self._get_default_kwargs())
        kwargs["backend"] = self.backend
        kwargs["parse_method"] = self.parse_method
        kwargs["formula_enable"] = self.enable_formula_extraction
        kwargs["table_enable"] = self.enable_table_extraction
        return kwargs

    @classmethod
    @cache
    def _get_default_kwargs(cls) -> dict[str, Any]:
        from mineru.utils.enum_class import MakeMode  # noqa: PLC0415

        return {
            "server_url": None,
            # We don't dump md directly we process, we dump the middle json in order
            # to be able to get page indexes
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


class MinerUPipelineConfig(BasePipelineConfig):  # noqa: F821
    pipeline: ClassVar[PipelineType] = Field(frozen=True, default=PipelineType.MINER_U)

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
