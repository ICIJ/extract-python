import os
from copy import copy
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Self

from pydantic import Field, model_validator

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


class LiteParseOCRReason(StrEnum):
    SCANNED = "scanned"
    NO_TEXT = "no-text"
    SPARSE_TEXT = "sparse-text"
    EMBEDDED_IMAGES = "embedded-images"
    GARBLED = "garbled"
    VECTOR_TEXT = "vector-text"
    ANNOTATION_TEXT = "annotation-text"


class LiteParseLayoutReason(StrEnum):
    MULTI_COLUMN = "multi-column"
    TABLE_LIKELY = "table-likely"
    DENSE_GRAPHICS = "dense-graphics"


def _all_ocr_reasons() -> set[LiteParseOCRReason]:
    return set(LiteParseOCRReason)


class LiteParseRouterConfig(BaseModel):
    needs_ocr_is_advanced: bool = True
    complex_layout_is_advanced: bool = True
    advanced_ocr_reasons: set[LiteParseOCRReason] | None = None
    advanced_layout_reasons: set[LiteParseLayoutReason] | None = None

    @model_validator(mode="after")
    def reasons_are_consistent_with_flags(self) -> Self:
        if self.needs_ocr_is_advanced and self.advanced_ocr_reasons is not None:
            msg = (
                "advanced_ocr_reasons can be supplied when needs_ocr_is_advanced"
                "is set to True. When needs_ocr_is_advanced ocr reasons are ignored."
            )
            raise ValueError(msg)
        if self.complex_layout_is_advanced and self.advanced_layout_reasons is not None:
            msg = (
                "complex_layout_is_advanced can be supplied when "
                "advanced_layout_reasons is set to True."
                " When advanced_layout_reasons ocr reasons are ignored."
            )
            raise ValueError(msg)
        return self
