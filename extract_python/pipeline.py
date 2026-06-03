from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Iterable
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from icij_common.pydantic_utils import icij_config, merge_configs, no_enum_values_config
from icij_common.registrable import RegistrableConfig, RegistrableFromConfig
from pydantic import Field

from .objects import InputDoc, OutputFormat, Result, SupportedExt

StructuredContent = str


class PipelineType(StrEnum):
    DOCLING = "docling"
    MARKER = "marker"
    MINER_U = "miner_u"


class PipelineConfig(RegistrableConfig, ABC):
    # TODO: move this icij_config() to RegistrableConfig
    model_config = merge_configs(icij_config(), no_enum_values_config())

    registry_key: ClassVar[str] = Field(frozen=True, default="pipeline")
    pipeline: PipelineType

    task_group: ClassVar[str] = Field(frozen=True)

    @classmethod
    @abstractmethod
    def supported_formats(cls) -> set[SupportedExt]: ...


class Pipeline(RegistrableFromConfig, ABC):
    @abstractmethod
    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]: ...
