from functools import cache
from typing import Any, ClassVar

from pydantic import Field

from .configs import BasePipelineConfig, PipelineType
from .objects import SupportedExt


class MarkerPipelineConfig(BasePipelineConfig):
    pipeline: ClassVar[PipelineType] = Field(frozen=True, default=PipelineType.MARKER)

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
