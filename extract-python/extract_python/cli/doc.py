import logging
import os
from pathlib import Path
from typing import Annotated, Never

import typer
from extract_core import (
    Device,
    InputDoc,
    OutputFormat,
    Pipeline,
    PipelineConfig,
    PipelineSize,
    PipelineType,
)
from extract_core.default_config import default_config
from pydantic import TypeAdapter

from .utils import AsyncTyper

logger = logging.getLogger(__name__)

_DOC = "doc"

_DOC_CONVERT_HELP = "Converts documents to the provided output format"
_DOC_CONVERT_DOCS_HELP = "input documents (can be file or directories)"
_DOC_CONVERT_OUTPUT_PATH_HELP = "directory where the converted documents will be saved"
_DOC_CONVERT_DEVICE_HELP = "device used to run inference"
_DOC_CONVERT_OUTPUT_FMT_HELP = "output format"
_DOC_CONVERT_PIPELINE_CONFIG = "path to a JSON pipeline configuration"


configs_app = AsyncTyper(name=_DOC)


@configs_app.async_command(help=_DOC_CONVERT_HELP)
async def convert(
    docs: Annotated[list[Path], typer.Argument(help=_DOC_CONVERT_DOCS_HELP)],
    output_path: Annotated[Path, typer.Argument(help=_DOC_CONVERT_OUTPUT_PATH_HELP)],
    output_format: Annotated[
        OutputFormat, typer.Option(help=_DOC_CONVERT_OUTPUT_FMT_HELP)
    ] = OutputFormat.MARKDOWN,
    config: Annotated[
        Path | None,
        typer.Option("-c", "--config", help=_DOC_CONVERT_PIPELINE_CONFIG),
    ] = None,
) -> None:
    if config is not None:
        config = TypeAdapter(PipelineConfig).validate_json(config.read_text())
    else:
        config = default_config(
            pipeline_type=PipelineType.DOCLING,
            device=Device.CPU,
            size=PipelineSize.SMALL,
        )
    config = config.to_device()
    docs = [InputDoc.from_path(d, n_pages=1) for p in docs for d in _walkdir(p)]
    pipeline = Pipeline.from_config(config)
    output_paths = []
    async for res in pipeline.extract_content(docs, output_format, output_path):
        output_path = res.output.path
        logger.info("converted %s to %s", res.input.path, output_path / output_path)
        output_paths.append(output_path / output_path)
    print("\n".join(output_paths))


def _raise(exc: OSError) -> Never:
    raise exc


def _walkdir(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    paths = []
    for root, _, files in os.walk(path, onerror=_raise):
        root = Path(root)  # noqa: PLW2901
        paths.extend(root / f for f in files)
    return paths
