import logging
from collections.abc import AsyncIterable, Iterable, Iterator
from itertools import chain, groupby
from pathlib import Path
from typing import TYPE_CHECKING, Self

from extract_core import (
    HybridLiteParsePipelineConfig,
    InputDoc,
    InputPages,
    LiteParseLayoutReason,
    LiteParseOCRReason,
    LiteParseRouterConfig,
    OutputFormat,
    Pipeline,
    PipelineType,
    Result,
)

from .liteparse_ import LiteParsePipeline

_IS_ADVANCED = "is_advanced"

LITEPARSE_RANGE = "liteparse_range"

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from liteparse.types import PageComplexityStats


class LiteParseRouter:
    def __init__(self, config: LiteParseRouterConfig):
        self._config = config

    def is_advanced(self, complexity: "PageComplexityStats") -> bool:
        config = self._config
        if config.needs_ocr_is_advanced and complexity.needs_ocr:
            return True
        layout = complexity.layout
        if config.complex_layout_is_advanced and layout.is_complex:
            return True
        if config.advanced_ocr_reasons and any(
            LiteParseOCRReason(r) in config.advanced_ocr_reasons
            for r in complexity.reasons
        ):
            return True
        if config.advanced_layout_reasons and any(  # noqa: SIM103
            LiteParseLayoutReason(r) in config.advanced_layout_reasons
            for r in layout.reasons
        ):
            return True
        return False


@Pipeline.register(PipelineType.HYBRID_LITEPARSE)
class HybridLiteParsePipeline(Pipeline):
    def __init__(
        self, router: LiteParseRouter, liteparse: LiteParsePipeline, advanced: Pipeline
    ):
        self._router = router
        self._liteparse = liteparse
        self._advanced = advanced

    @classmethod
    def _from_config(cls, config: HybridLiteParsePipelineConfig) -> Self:
        router = LiteParseRouter(config.router)
        liteparse = LiteParsePipeline(config.liteparse)
        advanced = Pipeline.from_config(config.advanced)
        return cls(router, liteparse, advanced)

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncIterable[Result]:
        complexities = await self._liteparse.compute_complexities(docs)
        simple, advanced = self._route(complexities)
        async for res in self.extract_pages_content(simple, output_format, output_path):
            yield res
        async for res in self.extract_pages_content(
            advanced, output_format, output_path
        ):
            yield res

    async def extract_pages_content(
        self,
        pages: Iterable[InputPages],
        output_format: OutputFormat,
        output_path: Path,
    ) -> AsyncIterable[Result]:
        pages = _ensure_same_parser(pages)
        first = next(pages, None)
        if first is None:
            return
        pages = chain((first,), pages)
        is_advanced = first.metadata[_IS_ADVANCED]
        pipeline = self._advanced if is_advanced else self._liteparse
        async for res in pipeline.extract_pages_content(
            pages, output_format, output_path
        ):
            yield res

    def _route(
        self, complexities: list[tuple[InputDoc, list["PageComplexityStats"]]]
    ) -> tuple[list[InputPages], list[InputPages]]:
        simple, advanced = [], []
        for doc_ix, (doc, doc_complexities) in enumerate(complexities):
            current_page = 0
            grouped = groupby(doc_complexities, key=self._router.is_advanced)
            for is_advanced, group in grouped:
                group = tuple(group)  # noqa: PLW2901
                input_pages = _group_to_input_pages(
                    group, current_page, doc, doc_ix=doc_ix, is_advanced=is_advanced
                )
                if is_advanced:
                    advanced.append(input_pages)
                else:
                    simple.append(input_pages)
                current_page += input_pages.n_pages
        return simple, advanced


def _group_to_input_pages(
    group: tuple["PageComplexityStats", ...],
    rng_start: int,
    doc: InputDoc,
    *,
    doc_ix: int,
    is_advanced: bool,
) -> InputPages:
    n_pages = len(group)
    start = rng_start
    end = start + n_pages
    rng = (start, end)
    expected_page_nums = list(range(start + 1, end + 1))
    page_nums = [p.page_number for p in group]
    if page_nums != expected_page_nums:
        msg = (
            f"inconsistent page numbers within group, expected {page_nums} found {rng}"
        )
        raise ValueError(msg)
    meta = {_IS_ADVANCED: is_advanced}
    input_pages = InputPages(doc=doc, doc_idx=doc_ix, page_range=rng, metadata=meta)
    return input_pages


def _ensure_same_parser(pages: Iterable[InputPages]) -> Iterator[InputPages]:
    is_advanced = None
    for p in pages:
        if is_advanced is None:
            is_advanced = p.metadata["is_advanced"]
        elif p.metadata["is_advanced"] != is_advanced:
            raise ValueError("expected all pages to have the same complexities")
        yield p
