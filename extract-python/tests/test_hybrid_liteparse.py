from collections.abc import AsyncIterable, Iterable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from extract_core import (
    ConversionOutput,
    InputDoc,
    InputPages,
    LiteParseLayoutReason,
    LiteParseOCRReason,
    LiteParseRouterConfig,
    OutputFormat,
    Pages,
    Range,
    Result,
    Status,
)
from liteparse.types import LayoutComplexityStats, PageComplexityStats

from extract_python import HybridLiteParsePipeline
from extract_python.hybrid_liteparse_ import LiteParseRouter


def _make_complexity(
    *,
    needs_ocr: bool = False,
    complex_layout: bool = False,
    ocr_reasons: list[str] | None = None,
    layout_reasons: list[str] | None = None,
    page_number: int = 1,
) -> PageComplexityStats:
    if ocr_reasons is None:
        ocr_reasons = []
    if layout_reasons is None:
        layout_reasons = []
    return PageComplexityStats(
        page_number=page_number,
        text_length=2,
        text_coverage=0.5,
        has_substantial_images=True,
        image_block_count=1,
        image_coverage=0.5,
        largest_image_coverage=0.8,
        full_page_image=True,
        uncovered_vector_area=0.5,
        is_garbled=True,
        page_area=0.5,
        needs_ocr=needs_ocr,
        reasons=ocr_reasons,
        layout=LayoutComplexityStats(
            column_count=1,
            ruled_table_count=1,
            ruled_table_coverage=0.5,
            text_table_run_count=1,
            figure_count=1,
            figure_coverage=0.5,
            is_complex=complex_layout,
            reasons=layout_reasons,
        ),
    )


@pytest.mark.parametrize(
    ("config", "complexity", "expected_is_advanced"),
    [
        (
            LiteParseRouterConfig(
                needs_ocr_is_advanced=False, complex_layout_is_advanced=False
            ),
            _make_complexity(),
            False,
        ),
        (
            LiteParseRouterConfig(
                needs_ocr_is_advanced=True, complex_layout_is_advanced=False
            ),
            _make_complexity(needs_ocr=True),
            True,
        ),
        (
            LiteParseRouterConfig(
                needs_ocr_is_advanced=False, complex_layout_is_advanced=True
            ),
            _make_complexity(complex_layout=True),
            True,
        ),
        (
            LiteParseRouterConfig(
                needs_ocr_is_advanced=False,
                complex_layout_is_advanced=False,
                advanced_ocr_reasons={LiteParseOCRReason.SCANNED},
            ),
            _make_complexity(complex_layout=True, ocr_reasons=["no-text"]),
            False,
        ),
        (
            LiteParseRouterConfig(
                needs_ocr_is_advanced=False,
                complex_layout_is_advanced=False,
                advanced_ocr_reasons={LiteParseOCRReason.SCANNED},
            ),
            _make_complexity(complex_layout=True, ocr_reasons=["scanned"]),
            True,
        ),
        (
            LiteParseRouterConfig(
                needs_ocr_is_advanced=False,
                complex_layout_is_advanced=False,
                advanced_layout_reasons={LiteParseLayoutReason.MULTI_COLUMN},
            ),
            _make_complexity(complex_layout=True, layout_reasons=["dense-graphics"]),
            False,
        ),
        (
            LiteParseRouterConfig(
                needs_ocr_is_advanced=False,
                complex_layout_is_advanced=False,
                advanced_layout_reasons={LiteParseLayoutReason.DENSE_GRAPHICS},
            ),
            _make_complexity(complex_layout=True, layout_reasons=["dense-graphics"]),
            True,
        ),
    ],
)
def test_liteparse_router(
    config: LiteParseRouterConfig,
    complexity: PageComplexityStats,
    *,
    expected_is_advanced: bool,
) -> None:
    # Given
    router = LiteParseRouter(config)
    # When
    is_advanced = router.is_advanced(complexity=complexity)
    assert is_advanced == expected_is_advanced


class _PageCapture:
    def __init__(self) -> None:
        self._pages = []

    @property
    def pages(self) -> list[tuple[int, Range]]:
        return self._pages

    async def __call__(
        self,
        pages: Iterable[InputPages],
        output_format: OutputFormat,  # noqa: ARG002
        output_path: Path,  # noqa: ARG002
    ) -> AsyncIterable[Result]:
        current = None
        mocked_output = ConversionOutput(path=Path(""), pages=Pages(), confidence=0.8)
        for page in pages:
            self._pages.append((page.doc_idx, page.page_range))
            if page.doc is not current:
                current = page.doc
                yield Result(
                    input=page.doc, status=Status.SUCCESS, output=mocked_output
                )


async def test_hybrid_liteparse(docs: list[InputDoc], tmpdir: Path) -> None:
    # Given
    output_path = Path(tmpdir)
    router = LiteParseRouter(
        LiteParseRouterConfig(
            needs_ocr_is_advanced=True, complex_layout_is_advanced=False
        )
    )
    liteparse = AsyncMock()
    mocked_complexities = [
        (docs[0], [_make_complexity(needs_ocr=True)]),
        (
            docs[0],
            [
                _make_complexity(needs_ocr=False, page_number=1),
                _make_complexity(needs_ocr=True, page_number=2),
                _make_complexity(needs_ocr=False, page_number=3),
            ],
        ),
    ]
    liteparse.compute_complexities.return_value = mocked_complexities
    liteparse_capture = _PageCapture()
    liteparse.extract_pages_content = MagicMock(side_effect=liteparse_capture)
    advanced = AsyncMock()
    advanced_capture = _PageCapture()
    advanced.extract_pages_content = MagicMock(side_effect=advanced_capture)
    pipeline = HybridLiteParsePipeline(router, liteparse, advanced)
    output_format = OutputFormat.MARKDOWN
    # When
    async for _ in pipeline.extract_content(docs, output_format, output_path):
        pass
    # Then
    assert liteparse_capture.pages == [(1, (0, 1)), (1, (2, 3))]
    assert advanced_capture.pages == [(0, (0, 1)), (1, (1, 2))]
