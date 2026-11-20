import logging

logger = logging.getLogger(__name__)

try:
    from .docling_ import DOCLING_DEFAULT_ARTIFACTS_PATH, DoclingPipeline
except ModuleNotFoundError:
    logger.warning("docling is not available, might be optional...")
    DOCKING_DEFAULT_ARTIFACTS_PATH, DoclingPipeline = None, None

try:
    from .marker_ import MarkerPipeline
except ModuleNotFoundError:
    logger.warning("marker is not available, might be optional...")
    MarkerPipeline = None


try:
    from .mineru_ import MinerUPipeline
except ModuleNotFoundError:
    logger.warning("mineru is not available, might be optional...")
    MinerUPipeline = None

try:
    from .hybrid_liteparse_ import (
        HybridLiteParsePipeline,
        LiteParseLayoutReason,
        LiteParseOCRReason,
    )
    from .liteparse_ import LiteParsePipeline
except ModuleNotFoundError:
    logger.warning("liteparse is not available, might be optional...")
    HybridLiteParsePipeline, LiteParseLayoutReason, LiteParseOCRReason = (
        None,
        None,
        None,
    )
    LiteParsePipeline = None

__all__ = [
    "DoclingPipeline",
    "DOCLING_DEFAULT_ARTIFACTS_PATH",
    "HybridLiteParsePipeline",
    "LiteParseLayoutReason",
    "LiteParseOCRReason",
    "LiteParsePipeline",
    "MarkerPipeline",
    "MinerUPipeline",
]
