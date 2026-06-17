from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Iterable
from pathlib import Path

from icij_common.registrable import RegistrableFromConfig

from .objects import Device, InputDoc, OutputFormat, Result


class Pipeline(RegistrableFromConfig, ABC):
    def __init__(self, device: Device = Device.CPU):
        self._device = device

    @abstractmethod
    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]: ...
