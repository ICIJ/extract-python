from typing import Annotated

import typer

from extract_core import PipelineSize

from ..configs import PipelineType
from ..default_config import default_config
from ..objects import Device
from .utils import AsyncTyper

_CONFIGS = "config"

_DEFAULT_CONFIG_HELP = (
    "display default configuration for a given pipeline type,"
    " device and computing power"
)
_DEFAULT_CONFIG_DEVICE_HELP = "device for which the default config should be displayed"
_DEFAULT_CONFIG_SIZE_HELP = "pipeline size, smaller is faster"

configs_app = AsyncTyper(name=_CONFIGS)


@configs_app.async_command(name="get-default", help=_DEFAULT_CONFIG_HELP)
async def display_default_config(
    pipeline_type: PipelineType,
    device: Annotated[
        Device,
        typer.Option("-d", "--device", help=_DEFAULT_CONFIG_DEVICE_HELP),
    ] = Device.CUDA,
    size: Annotated[
        PipelineSize,
        typer.Option("-s", "--size", help=_DEFAULT_CONFIG_SIZE_HELP),
    ] = PipelineSize.SMALL,
) -> None:
    config = default_config(pipeline_type=pipeline_type, device=device, size=size)
    print(config.model_dump_json(indent=2))


_GENERATE_DEFAULT_DOCLING_FORMAT_OPTIONS = (
    "generate docling format option to persist "
    "them and avoid depending on docling runtime dependencies at runtime"
)


@configs_app.async_command(help=_GENERATE_DEFAULT_DOCLING_FORMAT_OPTIONS)
async def generate_docling_default_format_options() -> None:

    from extract_core.constants import DOCLING_DEFAULT_FORMAT_OPTIONS_PATH
    from extract_core.docling_ import (
        FMT_OPTS_TA,
        generate_default_format_options,
    )

    fmt_opts = generate_default_format_options()
    fmt_opts = FMT_OPTS_TA.dump_json(fmt_opts, polymorphic_serialization=True, indent=2)
    DOCLING_DEFAULT_FORMAT_OPTIONS_PATH.write_bytes(fmt_opts)
    print(fmt_opts.decode())
