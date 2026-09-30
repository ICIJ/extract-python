from .configs import BasePipelineConfig, Device, PipelineType
from .objects import PipelineSize


def default_config(
    *, pipeline_type: PipelineType, device: Device, size: PipelineSize
) -> BasePipelineConfig:
    match pipeline_type:
        case PipelineType.DOCLING:
            return _default_docling_config(device=device, size=size)
        case PipelineType.MARKER:
            return _default_marker_config(size)
        case PipelineType.MINER_U:
            return _default_mineru_config(size)
        case _:
            raise NotImplementedError(f"unsupported pipeline type {pipeline_type}")


def _default_docling_config(
    *, device: Device, size: PipelineSize
) -> BasePipelineConfig:
    from .docling_ import DoclingPipelineConfig, default_format_opts  # noqa: PLC0415

    format_opts = default_format_opts(device=device, size=size)
    pipeline_cfg = DoclingPipelineConfig(format_options=format_opts)
    return pipeline_cfg


def _default_marker_config(size: PipelineSize) -> BasePipelineConfig:
    from .marker_ import MarkerPipelineConfig  # noqa: PLC0415

    mode = "balanced" if size is PipelineSize.LARGE else "fast"
    return MarkerPipelineConfig(config={"mode": mode})


def _default_mineru_config(size: PipelineSize) -> BasePipelineConfig:
    from .miner_u import MinerUConfig, MinerUPipelineConfig  # noqa: PLC0415

    match size:
        case PipelineSize.SMALL:
            tier = "basic"
        case PipelineSize.MEDIUM:
            tier = "standard"
        case PipelineSize.LARGE:
            tier = "advanced"
        case _:
            raise TypeError(f"unsupported pipeline size {size}")
    return MinerUPipelineConfig(config=MinerUConfig(tier=tier))
