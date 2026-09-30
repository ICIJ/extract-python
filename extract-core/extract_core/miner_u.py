from collections.abc import Callable
from enum import StrEnum
from functools import cache
from typing import ClassVar, Literal

from mineru.config import VlmConfig
from mineru.types import Tier
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

    tier: Tier = "basic"
    parse_mode: Literal["auto", "txt", "ocr"] = "auto"
    image_analysis: bool = True
    vlm_config: VlmConfig | None = None


class MinerUPipelineConfig(BasePipelineConfig):  # noqa: F821
    pipeline: ClassVar[PipelineType] = Field(frozen=True, default=PipelineType.MINER_U)

    config: MinerUConfig = Field(frozen=True, default_factory=MinerUConfig)
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
