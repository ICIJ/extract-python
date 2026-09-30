import os
from collections.abc import AsyncIterable, Callable, Iterable
from functools import cache, partial
from pathlib import Path

from docvortex.export import materialize_middle, validate_materialized_assets
from docvortex.render import RenderMode, render_markdown
from docvortex.schema import DocumentMetadata, PageInfo, Producer
from extract_core import (
    ConversionOutput,
    InputDoc,
    MinerUPipelineConfig,
    OutputFormat,
    Pipeline,
    PipelineType,
    Result,
    Status,
)
from mineru import MiddleJson, ParseResult

from .constants import ARTIFACTS, DEFAULT_MD_PAGE_SEP
from .utils import path_to_artifacts_dirname, reset_env, write_pages

_MINER_U_CONVERSION_ERRORS = tuple()
MDMakeFunction = Callable[[list, str, str], str | None]


@Pipeline.register(PipelineType.MINER_U)
class MinerUPipeline(Pipeline):
    def __init__(self, config: MinerUPipelineConfig):
        super().__init__(config)
        self._language = self._config.language

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat, output_path: Path
    ) -> AsyncIterable[Result]:
        from mineru import MinerUParser  # noqa: PLC0415

        with reset_env():
            os.environ["MINERU_DEVICE_MODE"] = self._device
            # TODO: exclude files which are not pdf and return an error
            # TODO: we should only process valid PDFs
            config = self._config.config
            parser = MinerUParser(
                tier=config.tier,
                parse_mode=config.parse_mode,
                image_analysis=config.image_analysis,
                vlm_config=config.vlm_config,
            )
            for doc in docs:
                res = await parser.parse_async(doc.path)
                yield _process_doc(
                    doc, res, output_format=output_format, output_path=output_path
                )


def _process_doc(
    doc: InputDoc,
    result: ParseResult,
    *,
    output_format: OutputFormat,
    output_path: Path,
) -> Result:
    output_path_dir_name = path_to_artifacts_dirname(doc.path)
    output_dir = Path(output_path) / output_path_dir_name
    output_dir.mkdir(parents=True)
    # Fail early
    match output_format:
        case OutputFormat.MARKDOWN:
            dump_content_fn = partial(
                _dump_md_content, output_path=output_path, md_path=output_dir
            )
        case _:
            raise NotImplementedError(f"unsupported output format {output_format}")
    output = dump_content_fn(result.middle_json)
    return Result(input=doc, status=Status.SUCCESS, output=output)


@cache
def _mineru_md_page_sep() -> str:
    dummy_json = MiddleJson(
        pages=[PageInfo(page_idx=0), PageInfo(page_idx=1)],
        is_full_document=True,
        metadata=DocumentMetadata(
            file_suffix="pdf", producer=Producer(name="dummy", version="1.0")
        ),
    )
    md = render_markdown(dummy_json, mode=RenderMode.FULL)
    return md.replace(" ", "")


def _dump_md_content(
    middle_json: MiddleJson,
    *,
    page_sep: str = DEFAULT_MD_PAGE_SEP,
    output_path: Path,
    md_path: Path,
) -> ConversionOutput:
    middle_json, assets = materialize_middle(middle_json)
    exported = ParseResult(middle_json=middle_json)
    validate_materialized_assets(middle_json, assets)
    md = exported.markdown(mode=RenderMode.FULL)
    for path, im_bytes in assets.items():
        im_path = md_path / ARTIFACTS / path
        im_path.parent.mkdir(parents=True, exist_ok=True)
        im_path.write_bytes(im_bytes)
        md = md.replace(path, str(im_path.relative_to(md_path)))
    pages = md.split(_mineru_md_page_sep())
    md_content_path = (md_path / md_path.name).with_suffix(OutputFormat.MARKDOWN)
    with open(md_content_path, "wb") as f:
        pages = write_pages(pages, page_sep, f)
    path = md_path.relative_to(output_path)
    output = ConversionOutput(path=path, pages=pages, confidence=None)
    return output
