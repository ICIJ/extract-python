from collections.abc import AsyncIterator, Iterable, Iterator
from pathlib import Path
from typing import ClassVar

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    OcrMacOptions,
    PdfPipelineOptions,
    RapidOcrOptions,
    TesseractCliOcrOptions,
    TesseractOcrOptions,
)
from docling.document_converter import DocumentConverter, FormatOption, PdfFormatOption
from docling_core.types.io import DocumentStream
from icij_common.registrable import FromConfig
from pydantic import Field

from extract_python.core.pipeline import Pipeline, PipelineConfig, PipelineType
from extract_python.objects import InputDoc, OutputFormat, Result
from extract_python.utils import map_and_preserve

DoclingOCR = (
    EasyOcrOptions
    | TesseractCliOcrOptions
    | TesseractOcrOptions
    | OcrMacOptions
    | RapidOcrOptions
)


@PipelineConfig.register()
class DoclingPipelineConfig(PipelineConfig):
    pipeline: ClassVar[str] = Field(frozen=True, default=PipelineType.DOCLING.value)

    force_full_page_ocr: bool = False
    ocr_options: DoclingOCR = Field(EasyOcrOptions(), discriminator="kind")

    def to_format_options(self) -> dict[InputFormat, FormatOption]:
        pipeline_options = PdfPipelineOptions(do_ocr=True, ocr_options=self.ocr_options)
        return {InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}


@Pipeline.register(PipelineType.DOCLING.value)
class DoclingPipeline(Pipeline):
    def __init__(self, format_options: dict[InputFormat, FormatOption] | None = None):
        self._convert = DocumentConverter(format_options=format_options)

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat
    ) -> AsyncIterator[Result]:
        docs, path_or_streams = map_and_preserve(_to_docling, docs)
        outputs = self._convert.convert_all(path_or_streams, raises_on_error=False)
        for doc, res in zip(docs, outputs):
            yield Result.from_docling(res, doc, output_format)

    @classmethod
    def _from_config(cls, config: DoclingPipelineConfig) -> FromConfig:
        return cls(config.to_format_options())


def _to_docling(docs: Iterable[InputDoc]) -> Iterator[Path | DocumentStream]:
    for d in docs:
        yield d.to_docling()
