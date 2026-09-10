import json
import os
import shutil
from collections.abc import AsyncIterable, Callable, Iterable
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

from extract_core import (
    ConversionOutput,
    InputDoc,
    MinerUBackend,
    MinerUPipelineConfig,
    OutputFormat,
    Pipeline,
    PipelineType,
    Result,
    Status,
)

from .constants import ARTIFACTS, DEFAULT_MD_PAGE_SEP
from .utils import path_to_artifacts_dirname, reset_env, write_pages

_MINER_U_CONVERSION_ERRORS = tuple()
MDMakeFunction = Callable[[list, str, str], str | None]


@Pipeline.register(PipelineType.MINER_U)
class MinerUPipeline(Pipeline):
    def __init__(self, config: MinerUPipelineConfig):
        super().__init__(config)
        self._language = self._config.language
        self._md_make_fn = _parse_md_make_fn(self._config.config.backend)

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncIterable[Result]:
        from mineru.cli.common import aio_do_parse  # noqa: PLC0415

        with reset_env():
            os.environ["MINERU_DEVICE_MODE"] = self._device
            docs = list(docs)
            # TODO: exclude files which are not pdf and return an error
            pdfs_bytes = [d.path.read_bytes() for d in docs]
            pdfs_names = [d.path.name for d in docs]
            p_lang_list = [self._language for _ in pdfs_names]
            # TODO: we should only process valid PDFs
            with TemporaryDirectory(prefix="mineru-") as workdir:
                workdir = Path(workdir)  # noqa: PLW2901
                await aio_do_parse(
                    output_dir=workdir,
                    pdf_file_names=pdfs_names,
                    pdf_bytes_list=pdfs_bytes,
                    p_lang_list=p_lang_list,
                    **self._config.config.as_parse_kwargs(),
                )
                res_paths = [
                    _revert_mineru_output(workdir, pdf_filename=p) for p in pdfs_names
                ]
                for doc, res_path in zip(docs, res_paths, strict=True):
                    yield _process_doc(
                        doc,
                        md_make_fn=self._md_make_fn,
                        res_path=res_path,
                        output_format=output_format,
                        output_path=output_path,
                    )


def _revert_mineru_output(output_dir: Path, *, pdf_filename: str) -> Path:
    output_path = output_dir / pdf_filename
    if not output_path.exists():
        msg = f"couldn't find result for {pdf_filename}"
        raise FileNotFoundError(msg)
    dirs = [p for p in output_path.iterdir() if p.is_dir()]
    if len(dirs) != 1:
        msg = f"expected exactly one result directory, found: {dirs}"
        raise ValueError(msg)
    return output_dir / dirs[0]


def _parse_md_make_fn(backend: MinerUBackend) -> MDMakeFunction:

    match backend:
        case MinerUBackend.PIPELINE:
            from mineru.backend.pipeline.pipeline_middle_json_mkcontent import (  # noqa: PLC0415
                union_make,
            )

            return union_make
        case MinerUBackend.VLM:
            from mineru.backend.vlm.vlm_middle_json_mkcontent import (  # noqa: PLC0415
                union_make,
            )

            return union_make
        case _:
            raise ValueError(f"Unsupported backend: {backend}")


def _process_doc(
    doc: InputDoc,
    *,
    md_make_fn: MDMakeFunction,
    res_path: Path,
    output_format: OutputFormat,
    output_path: Path,
) -> Result:
    md_dir_name = path_to_artifacts_dirname(doc.path)
    md_dir = Path(output_path) / md_dir_name
    md_dir.mkdir(parents=True, exist_ok=False)
    artifacts_dir = md_dir / ARTIFACTS
    md_path = (md_dir / md_dir_name).with_suffix(OutputFormat.MARKDOWN.value)
    # Fail early
    match output_format:
        case OutputFormat.MARKDOWN:
            im_rel_dir = artifacts_dir.relative_to(md_dir)
            dump_content_fn = partial(
                _dump_md_content,
                md_make_fn=md_make_fn,
                output_path=output_path,
                md_path=md_path,
                im_dir=im_rel_dir,
            )
        case _:
            raise NotImplementedError(f"unsupported output format {output_format}")
    middle_json_path = res_path / f"{doc.path.name}_middle.json"
    middle_json = json.loads(middle_json_path.read_text())
    shutil.move(res_path / "images", artifacts_dir)
    output = dump_content_fn(middle_json)
    return Result(input=doc, status=Status.SUCCESS, output=output)


def _dump_md_content(
    middle_json: dict,
    *,
    md_make_fn: MDMakeFunction,
    page_sep: str = DEFAULT_MD_PAGE_SEP,
    output_path: Path,
    md_path: Path,
    im_dir: Path,
    md_make_mode: str | None = None,
) -> ConversionOutput:
    from mineru.utils.enum_class import MakeMode  # noqa: PLC0415

    pdf_info = middle_json["pdf_info"]
    if md_make_mode is None:
        md_make_mode = MakeMode.MM_MD
    pages = (md_make_fn([p], md_make_mode, str(im_dir)) for p in pdf_info)
    with md_path.open("wb") as f:
        pages = write_pages(pages, page_sep, f)
    output_path = md_path.parent.relative_to(output_path)
    confidence = _mineru_confidence(pdf_info)
    output = ConversionOutput(path=output_path, pages=pages, confidence=confidence)
    return output


def _mineru_confidence(pdf_info: list[dict]) -> float:
    if not pdf_info:
        return 1.0
    block_conf = _mineru_block_confidence(pdf_info)
    line_config = _mineru_line_confidence(pdf_info)
    return (block_conf + line_config) / 2.0


def _mineru_block_confidence(pdf_info: list[dict]) -> float:
    import numpy as np  # noqa: PLC0415

    scores = []
    for info in pdf_info:
        for block in info["para_blocks"]:
            score = block.get("score")
            if score is not None:
                scores.append(score)
    if scores:
        return np.average(scores)
    return 1.0


def _mineru_line_confidence(pdf_info: list[dict]) -> float:
    import numpy as np  # noqa: PLC0415

    scores = []
    lengths = []
    for info in pdf_info:
        for block in info["para_blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    score = span.get("score")
                    if score is not None:
                        scores.append(score)
                        lengths.append(len(span["content"]))
    if scores:
        return np.average(scores, weights=lengths)
    return 1.0


def _parse_block(block: dict) -> tuple[list[float], list[float]]:
    if "lines" in block:
        scores = []
        lengths = []
        for line in block.get("lines", []):
            for span in line["spans"]:
                score = span.get("score")
                if score is not None:
                    scores.append(score)
                    lengths.append(len(span["content"]))
        return scores, lengths
    if "blocs" in block:
        scores, lengths = (_parse_block(b) for b in block["blocs"])
        scores = sum(*scores, start=[])
        lengths = sum(*lengths, start=[])
        return scores, lengths
    raise NotImplementedError(f"unsupported block: {block}")
