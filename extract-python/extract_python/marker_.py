import asyncio
import gc
from collections.abc import AsyncGenerator, Iterable
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

from extract_core import (
    InputDoc,
    MarkdownDoc,
    OutputFormat,
    Pipeline,
    PipelineType,
    Result,
    Status,
)

from .constants import ARTIFACTS, DEFAULT_MD_PAGE_SEP
from .utils import path_to_artifacts_dirname, report_recoverable_errors, write_pages

if TYPE_CHECKING:
    from marker.converters.pdf import PdfConverter
    from PIL import Image


_MARKER_CONVERSION_ERRORS = tuple()


@Pipeline.register(PipelineType.MARKER)
class MarkerPipeline(Pipeline):
    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncGenerator[Result, None]:
        from marker.config.parser import ConfigParser  # noqa: PLC0415
        from marker.converters.pdf import PdfConverter  # noqa: PLC0415
        from marker.models import create_model_dict  # noqa: PLC0415

        config = deepcopy(self._config.config)
        config["output_format"] = output_format.to_marker()
        config_parser = ConfigParser(config)
        renderer = config_parser.get_renderer()
        converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=create_model_dict(device=self._device),
            processor_list=config_parser.get_processors(),
            renderer=renderer,
        )
        for doc in docs:
            yield await _process_doc(doc, converter, output_format, output_path)


@report_recoverable_errors(_MARKER_CONVERSION_ERRORS)
async def _process_doc(
    doc: InputDoc,
    converter: "PdfConverter",
    output_format: OutputFormat,
    output_path: Path,
) -> Result:
    from marker.output import text_from_rendered  # noqa: PLC0415

    rendered = await asyncio.to_thread(converter, str(doc.path))
    content, _, images = text_from_rendered(rendered)
    match output_format:
        case OutputFormat.MARKDOWN:
            output = _to_markdown_doc(
                doc, content, images, output_path, page_sep=DEFAULT_MD_PAGE_SEP
            )
        case _:
            raise NotImplementedError(f"unsupported output format {output_format}")
    input_doc = doc.without_content()
    return Result(input=input_doc, status=Status.SUCCESS, output=output)


def _to_markdown_doc(
    input_doc: InputDoc,
    content: str,
    images: dict[str, "Image"],
    output_path: Path,
    *,
    page_sep: str = DEFAULT_MD_PAGE_SEP,
) -> MarkdownDoc:
    from marker.renderers.markdown import MarkdownRenderer  # noqa: PLC0415

    # TODO: Should we add a hash to avoid collision between files with same names
    #  nested in the tree structured
    md_dir_name = path_to_artifacts_dirname(input_doc.path)
    md_dir = output_path / md_dir_name
    artifacts_dir = md_dir / ARTIFACTS
    artifacts_dir.mkdir(parents=True)
    for im_name, im in images.items():
        im.save(artifacts_dir / im_name)
    del images
    gc.collect()
    pages = content.split(MarkdownRenderer.page_separator)
    md_path = output_path / md_dir_name / md_dir_name
    md_path = md_path.with_suffix(OutputFormat.MARKDOWN.value)
    with md_path.open("wb") as f:
        pages = write_pages(pages, page_sep, f)
    return MarkdownDoc(path=Path(md_dir_name), pages=pages)
