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
