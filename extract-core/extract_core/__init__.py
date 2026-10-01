from typing import Annotated, Any

from icij_common.pydantic_utils import make_enum_discriminator, tagged_union
from pydantic import Discriminator, Tag

from .configs import (
    BasePipelineConfig,
    PipelineBySize,
    PipelineType,
    ResultBufferConfig,
)
from .objects import (
    BaseModel,
    ConversionOutput,
    Device,
    Error,
    InputDoc,
    MarkdownDoc,
    OutputFormat,
    Pages,
    PipelineSize,
    Ranges,
    Result,
    Status,
    SupportedExt,
)
from .pipeline import Pipeline

try:
    from .docling_ import (
        BatchConcurrencySettings,
        DoclingFormatOption,
        DoclingPipelineConfig,
        DoclingSettings,
    )
except ModuleNotFoundError:
    (
        BatchConcurrencySettings,
        DoclingFormatOption,
        DoclingPipelineConfig,
        DoclingSettings,
    ) = (
        None,
        None,
        None,
        None,
    )

try:
    from .marker_ import MarkerPipelineConfig
except ModuleNotFoundError:
    MarkerPipelineConfig = None

try:
    from .miner_u import MinerUBackend, MinerUConfig, MinerUPipelineConfig
except ModuleNotFoundError:
    MinerUBackend, MinerUPipelineConfig, MinerUConfig = None, None, None


_pipeline_type_discriminator = make_enum_discriminator("pipeline", PipelineType)


def pipeline_config_discriminator(v: Any) -> str:
    if isinstance(v, dict):
        size = v.get("size")
        if size is not None:
            return "by_size"
        return _pipeline_type_discriminator(v)
    if isinstance(v, PipelineBySize):
        return "by_size"
    return _pipeline_type_discriminator(v)


PipelineConfig = Annotated[
    tagged_union(
        BasePipelineConfig.__subclasses__(), lambda t: t.pipeline.default.value
    )
    | Annotated[PipelineBySize, Tag("by_size")],
    Discriminator(pipeline_config_discriminator),
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
    "Ranges",
    "Pages",
    "Pipeline",
    "PipelineSize",
    "PipelineBySize",
    "PipelineType",
    "Result",
    "Status",
    "SupportedExt",
    "ResultBufferConfig",
    "DoclingSettings",
    "BatchConcurrencySettings",
]
