from typing import Annotated

from icij_common.pydantic_utils import make_enum_discriminator, tagged_union
from pydantic import Discriminator

from .configs import BasePipelineConfig, PipelineType
from .objects import (
    BaseModel,
    ConversionOutput,
    Device,
    Error,
    InputDoc,
    MarkdownDoc,
    OutputFormat,
    PageIndexes,
    Result,
    Status,
)
from .pipeline import Pipeline

try:
    from .docling_ import DoclingFormatOption, DoclingPipelineConfig
except ModuleNotFoundError:
    DoclingPipelineConfig, DoclingFormatOption = None, None
try:
    from .marker_ import MarkerPipelineConfig
except ModuleNotFoundError:
    MarkerPipelineConfig = None


try:
    from .miner_u import MinerUBackend, MinerUConfig, MinerUPipelineConfig
except ModuleNotFoundError:
    MinerUBackend, MinerUPipelineConfig, MinerUConfig = None, None, None


pipeline_type_discriminator = make_enum_discriminator("pipeline", PipelineType)
PipelineConfig = Annotated[
    tagged_union(
        BasePipelineConfig.__subclasses__(), lambda t: t.pipeline.default.value
    ),
    Discriminator(pipeline_type_discriminator),
]


__all__ = [
    "BaseModel",
    "BasePipelineConfig",
    "ConversionOutput",
    "Device",
    "DoclingPipelineConfig",
    "Error",
    "InputDoc",
    "MarkdownDoc",
    "MarkerPipelineConfig",
    "MinerUBackend",
    "MinerUConfig",
    "MinerUPipelineConfig",
    "OutputFormat",
    "PageIndexes",
    "Pipeline",
    "PipelineType",
    "Result",
    "Status",
]
