from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Iterable
from enum import Enum
from typing import ClassVar

from icij_common.pydantic_utils import icij_config, merge_configs, no_enum_values_config
from icij_common.registrable import RegistrableConfig, RegistrableFromConfig
from pydantic import Field

from extract_python.objects import InputDoc, OutputFormat, Result

StructuredContent = str


class PipelineType(str, Enum):
    DOCLING = "docling"


class PipelineConfig(RegistrableConfig, ABC):
    # TODO: move this icij_config() to RegistrableConfig
    model_config = merge_configs(icij_config(), no_enum_values_config())

    registry_key: ClassVar[str] = Field(frozen=True, default="pipeline")
    pipeline: PipelineType


class Pipeline(RegistrableFromConfig, ABC):
    @abstractmethod
    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat
    ) -> AsyncGenerator[Result, None]: ...
