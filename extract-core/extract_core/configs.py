from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Self

from icij_common.pydantic_utils import icij_config, merge_configs, no_enum_values_config
from icij_common.registrable import RegistrableConfig
from pydantic import ByteSize, Field

from .objects import BaseModel, Device, PipelineSize, SupportedExt


class PipelineType(StrEnum):
    DOCLING = "docling"
    MARKER = "marker"
    MINER_U = "miner_u"


class BasePipelineConfig(RegistrableConfig, ABC):
    # TODO: move this icij_config() to RegistrableConfig
    model_config = merge_configs(icij_config(), no_enum_values_config())

    registry_key: ClassVar[str] = Field(frozen=True, default="pipeline")

    pipeline: ClassVar[PipelineType]
    device: Device = Device.CPU

    @classmethod
    @abstractmethod
    def supported_exts(cls) -> set[SupportedExt]: ...

    @abstractmethod
    def to_device(self) -> Self: ...


class ResultBufferConfig(BaseModel):
    max_size: ByteSize = "500MiB"
    root: Path | None = None


class PipelineBySize(BaseModel):
    pipeline: PipelineType = PipelineType.DOCLING
    size: PipelineSize = PipelineSize.MEDIUM

    def to_config(self, device: Device = Device.CPU) -> BasePipelineConfig:
        from .default_config import default_config  # noqa: PLC0415

        return default_config(
            pipeline_type=self.pipeline, size=self.size, device=device
        )
