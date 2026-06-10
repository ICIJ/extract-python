from pathlib import Path
from tempfile import TemporaryDirectory

import markdown2
import pypdfium2
from extract_core import BaseModel, OutputFormat, PageIndexes
from extract_python.utils import chdir
from html2image import Html2Image
from PIL import Image, ImageDraw

_WHITE_BACKGROUND_CSS = "body {background: white;}"


class ComparisonItem(BaseModel):
    ref: Path
    compared: list[Path]


def compare(comparisons: list[ComparisonItem], root: Path, output_path: Path) -> None:
    output_path.mkdir(parents=True)
    if not comparisons:
        return
    first_item = comparisons[0]
    if not first_item.compared:
        return
    if (root / first_item.compared[0]).is_dir():
        output_format = OutputFormat.MARKDOWN
    else:
        output_format = OutputFormat[first_item.compared[0].suffix]
    match output_format:
        case OutputFormat.MARKDOWN:
            side_by_side_page_comp_fn = side_by_side_md_page_comp
        case _:
            raise ValueError(f"unsupported output format {output_format}")
    for comparison in comparisons:
        if not comparison.compared:
            continue
        # We flatten everything and will fail if 2 refs have the same file name, even
        # if they have different paths. To be improved, potentially using nested
        # structure or concatenating the path into a single dir name
        comparison_dir = output_path / path_to_compared_name(comparison.ref)
        comparison_dir.mkdir()
        ref_path = root / comparison.ref
        ref_pdf = pypdfium2.PdfDocument(ref_path)
        # TODO: create TIFF or PDF
        pages = _scan_pages(root, comparison)
        for page_i, page_idxs in enumerate(pages):
            pdf_page_im = ref_pdf.get_page(page_i).render().to_pil()
            page_comparisons = []
            for compared in comparison.compared:
                compared_name = compared.parent.name
                page_ix = page_idxs[compared_name]
                page_comp_im = side_by_side_page_comp_fn(
                    ref_im=pdf_page_im,
                    compared_path=root / compared,
                    page_ix=page_ix,
                    compared_name=compared_name,
                )
                page_comparisons.append(page_comp_im)
            page_comparison_path = comparison_dir / f"page_{page_i}.tiff"
            page_comparisons[0].save(
                page_comparison_path, save_all=True, append_images=page_comparisons[1:]
            )
            for p in page_comparisons:
                p.close()


def discover_comparison(refs: list[Path], root: Path) -> list[ComparisonItem]:
    name_to_ref = {path_to_compared_name(r): r for r in refs}
    comparisons = {r: [] for r in refs}
    for d in root.iterdir():
        if not d.is_dir():
            continue
        for parsing in d.iterdir():
            ref = name_to_ref.get(parsing.name)
            if ref is None:
                continue
            comparisons[ref].append(parsing.relative_to(root))
    comparisons = [
        ComparisonItem(ref=ref, compared=compared)
        for ref, compared in comparisons.items()
    ]
    return comparisons


def side_by_side_md_page_comp(
    ref_im: Image,
    compared_path: Path,
    page_ix: tuple[int, int],
    compared_name: str,
) -> Image.Image:
    md_files = list(compared_path.glob("*.md"))
    if len(md_files) != 1:
        msg = f"unexpected number of md files ({len(md_files)}) in {compared_path}"
        raise ValueError(msg)
    md_content = md_files[0].read_text()[page_ix[0] : page_ix[1]]
    # change the current dir so that the browser renders images properly
    with chdir(compared_path):
        md_page_im = _render_md(md_content, compared_path, html_size=ref_im.size)
    ref_im = _add_compared_name(ref_im, compared_name)
    comparison_im = Image.new("RGB", (ref_im.width * 2, ref_im.height))
    comparison_im.paste(ref_im, (0, 0))
    comparison_im.paste(md_page_im, (ref_im.width, 0))
    ref_im.close()
    md_page_im.close()
    return comparison_im


def path_to_compared_name(path: Path) -> str:
    return f"{path.stem}_{path.suffix.replace('.', '')}"


def _add_compared_name(ref_im: Image, compared_name: str) -> Image:
    with_name = ref_im.copy()
    d = ImageDraw.Draw(with_name)
    d.text((0, 0), compared_name, font_size=24, fill=(255, 0, 0))
    return with_name


def _render_md(md_content: str, md_path: Path, html_size: tuple[int, int]) -> Image:
    with TemporaryDirectory() as tmpdir:
        # TODO: check that we're handling images correctly,
        #  maybe make md images absolute or something like this
        hti = Html2Image(size=html_size, output_path=tmpdir)
        html = markdown2.markdown(md_content)
        html = html.replace('<img src="', f'<img src="file://{md_path.absolute()}/')
        screen_files = hti.screenshot(html_str=html, css_str=_WHITE_BACKGROUND_CSS)
        if len(screen_files) > 1:
            msg = (
                "unexpected state, found multiple screenshots, "
                "either set a large html_size or find a way to combine them into a"
                " single image"
            )
            raise RuntimeError(msg)
        im_path = screen_files[0]
        return Image.open(im_path)


def _scan_pages(
    root: Path, comparison: ComparisonItem
) -> list[dict[str, tuple[int, int]]]:
    all_pages = [
        PageIndexes.model_validate_json(
            (root / compared / "artifacts" / "pages.json").read_text()
        ).root
        for compared in comparison.compared
    ]
    all_pages = zip(*all_pages, strict=True)
    compared_names = (p.parent.name for p in comparison.compared)
    pages = [
        dict(zip(compared_names, page_comp_ixs, strict=True))
        for page_comp_ixs in all_pages
    ]
    return pages
