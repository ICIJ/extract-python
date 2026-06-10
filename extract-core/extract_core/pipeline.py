from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Iterable
from pathlib import Path

from icij_common.registrable import RegistrableFromConfig

from .objects import InputDoc, OutputFormat, Result


class Pipeline(RegistrableFromConfig, ABC):
    @abstractmethod
    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]: ...
