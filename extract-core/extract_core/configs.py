from abc import ABC, abstractmethod
from enum import StrEnum
from typing import ClassVar

from icij_common.pydantic_utils import icij_config, merge_configs, no_enum_values_config
from icij_common.registrable import RegistrableConfig
from pydantic import Field

from .objects import Device, SupportedExt


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
