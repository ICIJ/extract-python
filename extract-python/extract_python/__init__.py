import logging

logger = logging.getLogger(__name__)

try:
    from .docling_ import DOCLING_DEFAULT_ARTIFACTS_PATH, DoclingPipeline
except ModuleNotFoundError:
    logger.exception("docling is not available, might be optional...")
    DOCKING_DEFAULT_ARTIFACTS_PATH, DoclingPipeline = None, None

try:
    from .marker_ import MarkerPipeline
except ModuleNotFoundError:
    logger.exception("marker is not available, might be optional...")
    MarkerPipeline = None


try:
    from .miner_u import MinerUPipeline
except ModuleNotFoundError:
    logger.exception("mineru is not available, might be optional...")
    MinerUPipeline = None


__all__ = [
    "DoclingPipeline",
    "DOCLING_DEFAULT_ARTIFACTS_PATH",
    "MarkerPipeline",
    "MinerUPipeline",
]
