import gc
from collections.abc import AsyncGenerator, Iterable
from copy import deepcopy
from functools import cache
from pathlib import Path
from typing import Any, ClassVar, Self

from marker.config.parser import ConfigParser
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from marker.renderers.markdown import MarkdownRenderer
from PIL.Image import Image
from pydantic import Field

from .constants import ARTIFACTS, CPU_GROUP
from .objects import (
    InputDoc,
    MarkdownDoc,
    OutputFormat,
    PageIndexes,
    Result,
    Status,
    SupportedExt,
)
from .pipeline import Pipeline, PipelineConfig, PipelineType
from .utils import path_to_artifacts_dirname, report_recoverable_errors


@PipelineConfig.register()
class MarkerPipelineConfig(PipelineConfig):
    pipeline: PipelineType = Field(frozen=True, default=PipelineType.MARKER)
    task_group: ClassVar[str] = Field(frozen=True, default=CPU_GROUP)

    config: dict[str, Any] = dict()

    @classmethod
    @cache
    def supported_exts(cls) -> set[SupportedExt]:
        # Subset of https://documentation.datalab.to/docs/common/supportedfiletypes
        return {
            SupportedExt.PDF,
            SupportedExt.XLS,
            SupportedExt.XLSX,
            SupportedExt.XLSM,
            SupportedExt.CSV,
            SupportedExt.ODS,
            SupportedExt.DOC,
            SupportedExt.DOCX,
            SupportedExt.ODT,
            SupportedExt.PPT,
            SupportedExt.PPTX,
            SupportedExt.ODP,
            SupportedExt.HTLM,
            SupportedExt.EPUB,
            SupportedExt.PNG,
            SupportedExt.JPG,
            SupportedExt.JPEG,
            SupportedExt.WEBP,
            SupportedExt.GIF,
            SupportedExt.TIFF,
        }


_MARKER_CONVERSION_ERRORS = tuple()


@Pipeline.register(PipelineType.MARKER)
class MarkerPipeline(Pipeline):
    def __init__(self, marker_config: dict[str, Any] | None = None):
        if marker_config is None:
            marker_config = dict()
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
            yield _process_doc(doc, converter, output_format, output_path)

    @classmethod
    def _from_config(cls, config: MarkerPipelineConfig) -> Self:
        return cls(config.config)


@report_recoverable_errors(_MARKER_CONVERSION_ERRORS)
def _process_doc(
    doc: InputDoc,
    converter: PdfConverter,
    output_format: OutputFormat,
    output_path: Path,
) -> Result:
    rendered = converter(str(doc.path))
    content, _, images = text_from_rendered(rendered)
    match output_format:
        case OutputFormat.MARKDOWN:
            output = _to_markdown_doc(doc, content, images, output_path)
        case _:
            raise NotImplementedError(f"unsupported output format {output_format}")
    input_doc = doc.without_content()
    return Result(input=input_doc, status=Status.SUCCESS, output=output)


def _to_markdown_doc(
    input_doc: InputDoc, content: str, images: dict[str, Image], output_path: Path
) -> MarkdownDoc:
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
    page_sep = MarkdownRenderer.page_separator
    content = content.split(page_sep)
    n_pages = len(content)
    md_path = (output_path / md_dir_name / md_dir_name).with_suffix(
        OutputFormat.MARKDOWN.value
    )
    total_length = 0
    end_indices = []
    with md_path.open("w", encoding="utf-8") as f:
        for page_i, page_content in enumerate(content):
            content = page_content
            if page_i > 0:
                content += "\n"
            if page_i < n_pages - 1:
                content += page_sep
            total_length += len(content)
            end_indices.append(total_length)
            f.write(content)
            f.flush()
    pages = PageIndexes.from_page_end_indices(end_indices)
    return MarkdownDoc(path=Path(md_dir_name), pages=pages)
