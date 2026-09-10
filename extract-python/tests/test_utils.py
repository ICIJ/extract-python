import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from extract_core import InputDoc, SupportedExt
from extract_python.utils import (
    ProcessedPages,
    ResultBuffer,
    batch_per_pages,
    write_pages,
)
from pympler import asizeof


def _read_page(doc: BytesIO, start: int, *, end: int) -> str:
    doc.seek(start)
    return doc.read(end - start).decode("utf-8")


_MD_DOC_0 = """
# First page
content
<div style="page-break-after: always;"></div>
# Second page
content
<div style="page-break-after: always;"></div>
# Third page
content"""

_MD_DOC_0_PAGE_0 = """
# First page
content"""

_MD_DOC_0_PAGE_1 = """
# Second page
content"""

_MD_DOC_0_PAGE_2 = """
# Third page
content"""


@pytest.mark.parametrize(
    ("pages", "page_sep", "expected_n_pages", "expected_page_contents"),
    [
        ([], '\n<div style="page-break-after: always;"></div>\n', 0, []),
        (
            [_MD_DOC_0_PAGE_0],
            '\n<div style="page-break-after: always;"></div>\n',
            1,
            [_MD_DOC_0_PAGE_0],
        ),
        (
            [_MD_DOC_0_PAGE_0, _MD_DOC_0_PAGE_1, _MD_DOC_0_PAGE_2],
            '\n<div style="page-break-after: always;"></div>\n',
            3,
            [
                f'{_MD_DOC_0_PAGE_0}\n<div style="page-break-after: always;"></div>\n',
                f'{_MD_DOC_0_PAGE_1}\n<div style="page-break-after: always;"></div>\n',
                f"{_MD_DOC_0_PAGE_2}",
            ],
        ),
        (
            [_MD_DOC_0_PAGE_0, _MD_DOC_0_PAGE_1, _MD_DOC_0_PAGE_2],
            "\n\n",
            3,
            [
                f"{_MD_DOC_0_PAGE_0}\n\n",
                f"{_MD_DOC_0_PAGE_1}\n\n",
                f"{_MD_DOC_0_PAGE_2}",
            ],
        ),
        (
            [_MD_DOC_0_PAGE_0, _MD_DOC_0_PAGE_1, _MD_DOC_0_PAGE_2],
            "",
            3,
            [f"{_MD_DOC_0_PAGE_0}", f"{_MD_DOC_0_PAGE_1}", f"{_MD_DOC_0_PAGE_2}"],
        ),
    ],
)
def test_write_pages(
    pages: list[str],
    page_sep: str,
    expected_n_pages: int,
    expected_page_contents: list[str],
) -> None:
    # Given
    output = BytesIO()
    # When
    written_pages = write_pages(pages, page_sep, out=output)
    # Then
    assert written_pages.total == expected_n_pages
    byte_ranges = written_pages.byte_ranges
    assert len(byte_ranges) == len(expected_page_contents)
    for byte_range, expected_content in zip(
        byte_ranges, expected_page_contents, strict=True
    ):
        start, end = byte_range
        page = _read_page(output, start, end=end)
        assert page == expected_content


class TestResultBuffer(ResultBuffer):
    @property
    def current_size(self) -> int:
        return self._current_size

    @property
    def root(self) -> Path:
        return self._root


def _json_save(obj: Any, path: Path) -> None:
    path.write_text(json.dumps(obj))


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text())


def test_result_buffer_in_memory() -> None:
    # Given
    max_size_bytes = sys.maxsize
    save_fn = MagicMock()
    load_fn = MagicMock()
    buffer = TestResultBuffer(
        max_size_bytes=max_size_bytes, save_fn=save_fn, load_fn=load_fn
    )
    doc_idx = 0
    first = ProcessedPages(
        doc=InputDoc(ext=SupportedExt.PDF, path=Path(""), n_pages=2),
        doc_idx=doc_idx,
        page_range=(0, 1),
    )
    last = ProcessedPages(
        doc=InputDoc(ext=SupportedExt.PDF, path=Path(""), n_pages=2),
        doc_idx=doc_idx,
        page_range=(1, 2),
    )
    # When
    with buffer:
        buffer.add(first, 0)
        buffer.add(last, -1)
        # Then
        assert buffer.current_size == 64
        assert buffer.is_complete(doc_idx)
        all_res = buffer.pop_complete(doc_idx)
        assert all_res == [0, -1]
        assert buffer.current_size == 0


def test_result_buffer_offload_on_fs() -> None:
    # Given
    first_res = 1
    max_size_bytes = asizeof.asizeof(first_res) + 1

    save_fn = MagicMock(side_effect=_json_save)
    load_fn = MagicMock(side_effect=_json_load)
    buffer = TestResultBuffer(
        max_size_bytes=max_size_bytes, save_fn=save_fn, load_fn=load_fn
    )
    doc_idx = 0
    first = ProcessedPages(
        doc=InputDoc(ext=SupportedExt.PDF, path=Path(""), n_pages=2),
        doc_idx=doc_idx,
        page_range=(0, 1),
    )
    last = ProcessedPages(
        doc=InputDoc(ext=SupportedExt.PDF, path=Path(""), n_pages=2),
        doc_idx=doc_idx,
        page_range=(1, 2),
    )
    # When
    with buffer:
        buffer.add(first, 0)
        save_fn.assert_not_called()
        buffer.add(last, -1)
        save_fn.assert_called_once()
        # Then
        assert buffer.current_size == 32
        assert buffer.is_complete(doc_idx)
        all_res = buffer.pop_complete(doc_idx)
        assert all_res == [0, -1]
        assert buffer.current_size == 0
    assert not buffer.root.exists()


def test_result_buffer_offload_on_fs_should_preserve_root(tmpdir: Path) -> None:
    # Given
    root = Path(tmpdir)
    max_size_bytes = 0
    buffer = TestResultBuffer(
        max_size_bytes=max_size_bytes, save_fn=_json_save, load_fn=_json_load, root=root
    )
    # When
    with buffer:
        pass
    assert buffer.root.exists()


def test_result_buffer_raise_for_inconsistent_state() -> None:
    # Given
    max_size_bytes = 0
    pages = ProcessedPages(
        doc=InputDoc(ext=SupportedExt.PDF, path=Path(""), n_pages=2),
        doc_idx=0,
        page_range=(0, 1),
    )
    buffer = TestResultBuffer(
        max_size_bytes=max_size_bytes, save_fn=_json_save, load_fn=_json_load
    )
    # When/Then
    expected = (
        "inconsistent state, type is a context manager, call __enter__ before using it"
    )
    with pytest.raises(ValueError, match=expected):
        buffer.add(pages, 0)


def test_batch_per_pages_should_yield_short_docs_first() -> None:
    # Given
    page_batch_size = 3
    max_page_batches = 2
    docs = [
        InputDoc(ext=SupportedExt.PDF, path=Path("0"), n_pages=8),
        InputDoc(ext=SupportedExt.PDF, path=Path("1"), n_pages=6),
    ]
    # When
    batches = list(
        batch_per_pages(docs, page_batch_size, max_page_batches=max_page_batches)
    )
    # Then
    expected_batches = [
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("1"), n_pages=6), doc_idx=0
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("0"), n_pages=8),
                doc_idx=1,
                page_range=(0, 6),
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("0"), n_pages=8),
                doc_idx=1,
                page_range=(6, 8),
            ),
        ),
    ]
    assert batches == expected_batches


def test_batch_per_pages_should_bin_short_docs() -> None:
    # Given
    page_batch_size = 3
    max_page_batches = 2
    docs = [
        InputDoc(ext=SupportedExt.PDF, path=Path("0"), n_pages=3),
        InputDoc(ext=SupportedExt.PDF, path=Path("1"), n_pages=4),
        InputDoc(ext=SupportedExt.PDF, path=Path("2"), n_pages=5),
        InputDoc(ext=SupportedExt.PDF, path=Path("3"), n_pages=2),
        InputDoc(ext=SupportedExt.PDF, path=Path("4"), n_pages=1),
    ]
    # When
    batches = list(
        batch_per_pages(docs, page_batch_size, max_page_batches=max_page_batches)
    )
    # Then
    expected_batches = [
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("1"), n_pages=4), doc_idx=1
            ),
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("3"), n_pages=2), doc_idx=3
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("2"), n_pages=5), doc_idx=2
            ),
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("4"), n_pages=1),
                doc_idx=4,
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("0"), n_pages=3), doc_idx=0
            ),
        ),
    ]
    assert batches == expected_batches


def test_batch_per_pages_should_group_long_docs_by_page_ranges() -> None:
    # Given
    page_batch_size = 4
    max_page_batches = 2
    docs = [
        InputDoc(ext=SupportedExt.PDF, path=Path("0"), n_pages=12),
        InputDoc(ext=SupportedExt.PDF, path=Path("1"), n_pages=11),
        InputDoc(ext=SupportedExt.PDF, path=Path("2"), n_pages=12),
        InputDoc(ext=SupportedExt.PDF, path=Path("3"), n_pages=11),
        InputDoc(ext=SupportedExt.PDF, path=Path("4"), n_pages=9),
        InputDoc(ext=SupportedExt.PDF, path=Path("5"), n_pages=10),
    ]
    # When
    batches = list(
        batch_per_pages(docs, page_batch_size, max_page_batches=max_page_batches)
    )
    # Then
    expected_batches = [
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("0"), n_pages=12),
                doc_idx=0,
                page_range=(0, 8),
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("1"), n_pages=11),
                doc_idx=1,
                page_range=(0, 8),
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("2"), n_pages=12),
                doc_idx=2,
                page_range=(0, 8),
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("0"), n_pages=12),
                doc_idx=0,
                page_range=(8, 12),
            ),
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("2"), n_pages=12),
                doc_idx=2,
                page_range=(8, 12),
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("3"), n_pages=11),
                doc_idx=3,
                page_range=(0, 8),
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("1"), n_pages=11),
                doc_idx=1,
                page_range=(8, 11),
            ),
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("3"), n_pages=11),
                doc_idx=3,
                page_range=(8, 11),
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("4"), n_pages=9),
                doc_idx=4,
                page_range=(0, 8),
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("5"), n_pages=10),
                doc_idx=5,
                page_range=(0, 8),
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("4"), n_pages=9),
                doc_idx=4,
                page_range=(8, 9),
            ),
        ),
        (
            ProcessedPages(
                doc=InputDoc(ext=SupportedExt.PDF, path=Path("5"), n_pages=10),
                doc_idx=5,
                page_range=(8, 10),
            ),
        ),
    ]
    assert batches == expected_batches
