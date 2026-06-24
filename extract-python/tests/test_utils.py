from io import BytesIO

import pytest
from extract_python.utils import write_pages


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
