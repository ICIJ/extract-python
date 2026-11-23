from typing import Annotated, Any, ClassVar, Self

from icij_common.pydantic_utils import make_enum_discriminator, safe_copy, tagged_union
from pydantic import Discriminator, Field, Tag

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
    InputPages,
    MarkdownDoc,
    OutputFormat,
    Pages,
    PipelineSize,
    Range,
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
    from .mineru_ import MinerUBackend, MinerUConfig, MinerUPipelineConfig
except ModuleNotFoundError:
    MinerUBackend, MinerUPipelineConfig, MinerUConfig = None, None, None

try:
    from .liteparse_ import (
        LiteParseConfig,
        LiteParseLayoutReason,
        LiteParseOCRReason,
        LiteParsePipelineConfig,
        LiteParseRouterConfig,
    )
except ModuleNotFoundError:
    LiteParsePipelineConfig, LiteParseConfig, LiteParseRouterConfig = None, None, None


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


if LiteParsePipelineConfig is not None:
    PipelineConfigNoHybrid = PipelineConfig = Annotated[
        tagged_union(
            BasePipelineConfig.__subclasses__(), lambda t: t.pipeline.default.value
        )
        | Annotated[PipelineBySize, Tag("by_size")],
        Discriminator(pipeline_config_discriminator),
    ]

    class HybridLiteParsePipelineConfig(BasePipelineConfig):
        pipeline: ClassVar[PipelineType] = Field(
            frozen=True, default=PipelineType.HYBRID_LITEPARSE
        )
        router: LiteParseRouterConfig = Field(default_factory=LiteParseRouterConfig)
        liteparse: LiteParsePipelineConfig = Field(
            default_factory=LiteParsePipelineConfig
        )
        advanced: PipelineConfigNoHybrid = Field(default_factory=DoclingPipelineConfig)

        @classmethod
        def supported_exts(cls) -> set[SupportedExt]:
            exts = set()
            for sub_cls in BasePipelineConfig.__subclasses__():
                exts.update(sub_cls.supported_exts())
            return exts

        def to_device(self) -> Self:
            advanced_to_device = safe_copy(self.advanced, {"device": self.device})
            update = {"advanced": advanced_to_device, "device": self.device}
            return safe_copy(self, update=update)

else:
    HybridLiteParsePipelineConfig = None

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
    "BatchConcurrencySettings",
    "ConversionOutput",
    "Device",
    "DoclingPipelineConfig",
    "DoclingSettings",
    "Error",
    "InputDoc",
    "InputPages",
    "LiteParseConfig",
    "LiteParseLayoutReason",
    "LiteParseOCRReason",
    "LiteParsePipelineConfig",
    "LiteParseRouterConfig",
    "MarkdownDoc",
    "MarkerPipelineConfig",
    "MinerUBackend",
    "MinerUConfig",
    "MinerUPipelineConfig",
    "OutputFormat",
    "Pages",
    "Pipeline",
    "PipelineConfig",
    "PipelineBySize",
    "PipelineSize",
    "PipelineType",
    "Range",
    "Ranges",
    "Result",
    "ResultBufferConfig",
    "Status",
    "SupportedExt",
]
