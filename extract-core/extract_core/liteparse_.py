import os
from copy import copy
from datetime import timedelta
from pathlib import Path
from typing import ClassVar, Self

from pydantic import Field

from .configs import BasePipelineConfig, PipelineType, ResultBufferConfig
from .objects import BaseModel, Device, SupportedExt

_SUPPORTED_EXTS = {
    SupportedExt.PDF,
    SupportedExt.DOC,
    SupportedExt.DOCX,
    SupportedExt.DOCM,
    SupportedExt.ODT,
    SupportedExt.RTF,
    SupportedExt.PAGES,
    SupportedExt.PPT,
    SupportedExt.PPTX,
    SupportedExt.PPTM,
    SupportedExt.ODP,
    SupportedExt.KEY,
    SupportedExt.XLS,
    SupportedExt.XLSX,
    SupportedExt.XLSM,
    SupportedExt.ODS,
    SupportedExt.CSV,
    SupportedExt.TSV,
    SupportedExt.NUMBERS,
    SupportedExt.JPG,
    SupportedExt.JPEG,
    SupportedExt.PNG,
    SupportedExt.GIF,
    SupportedExt.BMP,
    SupportedExt.TIFF,
    SupportedExt.WEBP,
    SupportedExt.SVG,
}


class LiteParseConfig(BaseModel):
    # TODO: move this to extract API
    ocr_language: str = "eng"
    dpi: float = 300
    preserve_very_small_text: bool = False
    quiet: bool = False
    extract_annotations: bool = True
    extract_form_fields: bool = True
    extract_xfa_packets: bool = True
    extract_document_metadata: bool = False
    extract_content_bounds: bool = True
    detect_screenshot_rects: bool = False
    render_form_fields: bool = False
    emit_word_boxes: bool = False
    extract_text_metadata: bool = False
    skip_diagonal_text: bool = False
    extract_vector_graphics: bool = False


class LiteParsePipelineConfig(BasePipelineConfig):
    pipeline: ClassVar[PipelineType] = Field(
        frozen=True, default=PipelineType.LITEPARSE
    )
    device: Device = Field(default=Device.CPU, frozen=True)

    config: LiteParseConfig = Field(default_factory=LiteParseConfig)
    tessdata_path: Path | None = None

    detect_page_orientation: bool = True

    n_cpus: int = Field(default_factory=os.cpu_count)
    page_batch_size: int = 8
    per_page_timeout: timedelta | None = None

    result_buffer: ResultBufferConfig = Field(default_factory=ResultBufferConfig)

    @classmethod
    def supported_exts(cls) -> set[SupportedExt]:
        return copy(_SUPPORTED_EXTS)

    def to_device(self) -> Self:
        return self
