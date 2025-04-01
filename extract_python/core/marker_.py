import gc
from collections.abc import AsyncGenerator, Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any, Self

from marker.config.parser import ConfigParser
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from marker.renderers.markdown import MarkdownRenderer
from PIL.Image import Image
from pydantic import Field

from extract_python.core.pipeline import Pipeline, PipelineConfig, PipelineType
from extract_python.objects import (
    Error,
    InputDoc,
    MarkdownDoc,
    OutputFormat,
    Result,
    Status,
)
from extract_python.utils import path_to_artifacts_dirname


@PipelineConfig.register()
class MarkerPipelineConfig(PipelineConfig):
    pipeline: PipelineType = Field(frozen=True, default=PipelineType.MARKER)

    config: dict[str, Any] = dict()


_MARKER_CONVERSION_ERRORS = tuple()


@Pipeline.register(PipelineType.MARKER)
class MarkerPipeline(Pipeline):
    def __init__(self, marker_config: dict[str, Any]):
        self._marker_config = marker_config

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]:
        config = deepcopy(self._marker_config)
        config["output_format"] = output_format.to_marker()
        config_parser = ConfigParser(config)
        renderer = config_parser.get_renderer()
        converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=create_model_dict(),
            processor_list=config_parser.get_processors(),
            renderer=renderer,
        )
        for doc in docs:
            try:
                rendered = converter(str(doc.path))
                content, _, images = text_from_rendered(rendered)
                yield _to_result(doc, content, images, output_format, output_path)
            # TODO: precisely list recoverable errors
            except _MARKER_CONVERSION_ERRORS as e:
                error = Error.from_exception(e)
                yield Result(
                    input=doc.without_content(),
                    status=Status.FAILURE,
                    errors=[error],
                    output=None,
                )

    @classmethod
    def _from_config(cls, config: MarkerPipelineConfig) -> Self:
        return cls(config.config)


def _to_result(
    input_doc: InputDoc,
    content: str,
    images: dict[str, Image],
    output_format: OutputFormat,
    output_path: Path,
) -> Result:
    output_path.mkdir(parents=True, exist_ok=True)
    match output_format:
        case OutputFormat.MARKDOWN:
            output = _to_markdown_doc(input_doc, content, images, output_path)
        case _:
            raise NotImplementedError(f"unsupported output format {output_format}")
    input_doc = input_doc.without_content()
    return Result(input=input_doc, status=Status.SUCCESS, output=output)


def _to_markdown_doc(
    input_doc: InputDoc, content: str, images: dict[str, Image], output_path: Path
) -> MarkdownDoc:
    # TODO: Should we add a hash to avoid collision between files with same names
    #  nested in the tree structured
    md_dir_name = path_to_artifacts_dirname(input_doc.path)
    md_dir = output_path / md_dir_name
    # Let's avoid issue of duplicated input file names flattened top level
    md_dir.mkdir(parents=True, exist_ok=False)
    for im_name, im in images.items():
        im.save(md_dir / im_name)
    del images
    gc.collect()
    page_sep = MarkdownRenderer.page_separator
    content = content.split(page_sep)
    n_pages = len(content)
    md_path = (output_path / md_dir_name / md_dir_name).with_suffix(
        OutputFormat.MARKDOWN.value
    )
    total_length = 0
    with md_path.open("w", encoding="utf-8") as f:
        pages = [0]
        for page_i, page_content in enumerate(content):
            content = page_content
            if page_i > 0:
                content += "\n"
            if page_i < n_pages - 1:
                content += page_sep
            total_length += len(content)
            pages.append(total_length)
            f.write(content)
            f.flush()
    return MarkdownDoc(path=Path(md_dir_name), pages=pages)
