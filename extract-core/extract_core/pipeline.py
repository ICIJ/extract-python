from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Iterable
from pathlib import Path
from typing import Generic, Self, TypeVar

from icij_common.registrable import RegistrableFromConfig

from extract_core import BasePipelineConfig

from .objects import InputDoc, OutputFormat, Result

C = TypeVar("C", bound="BasePipelineConfig")


class Pipeline(RegistrableFromConfig, Generic[C], ABC):
    def __init__(self, config: C):
        self._config = config
        self._device = self._config.device

    @abstractmethod
    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]: ...

    @classmethod
    def _from_config(cls, config: C) -> Self:
        return cls(config)
