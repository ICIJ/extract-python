from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, Iterable
from pathlib import Path
from typing import Self

from icij_common.registrable import RegistrableFromConfig

from extract_core import BasePipelineConfig

from .objects import InputDoc, OutputFormat, Result


class Pipeline[C: BasePipelineConfig](RegistrableFromConfig, ABC):
    def __init__(self, config: C):
        self._config = config
        self._device = self._config.device

    @abstractmethod
    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncIterable[Result]: ...

    @classmethod
    def _from_config(cls, config: C) -> Self:
        return cls(config)
