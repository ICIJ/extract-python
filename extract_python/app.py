import logging

from icij_worker import AsyncApp
from icij_worker.typing_ import RateProgress
from icij_worker.utils.progress import to_raw_progress

from extract_python.constants import (
    CPU_GROUP,
    EXTRACT_CONTENT_MINER_U_TASK,
    EXTRACT_CONTENT_TASK,
    MINER_U_GROUP,
)
from extract_python.objects import (
    ExtractionResponse,
    OutputFormat,
    parse_extraction_request,
)
from extract_python.tasks.dependencies import APP_LIFESPAN_DEPS, lifespan_config

logger = logging.getLogger(__name__)

app = AsyncApp("content-extraction", dependencies=APP_LIFESPAN_DEPS)


@app.task(name=EXTRACT_CONTENT_TASK, group=CPU_GROUP)
async def extract_content(
    docs: str | list[dict | str],
    pipeline_config: dict,
    output_path: str,
    output_format: str = OutputFormat.MARKDOWN.value,
    progress: RateProgress | None = None,
) -> dict:
    return await _extract_content(
        docs,
        pipeline_config,
        output_path,
        output_format=output_format,
        progress=progress,
        expected_group=CPU_GROUP,
    )


@app.task(name=EXTRACT_CONTENT_MINER_U_TASK, group=MINER_U_GROUP)
async def extract_content_miner_u(
    docs: str | list[dict | str],
    pipeline_config: dict,
    output_path: str,
    output_format: str = OutputFormat.MARKDOWN.value,
    progress: RateProgress | None = None,
) -> dict:
    return await _extract_content(
        docs,
        pipeline_config,
        output_path,
        output_format=output_format,
        progress=progress,
        expected_group=MINER_U_GROUP,
    )


async def _extract_content(
    docs: str | list[dict | str],
    pipeline_config: dict,
    output_path: str,
    *,
    output_format: str,
    progress: RateProgress,
    expected_group: str,
) -> dict:
    from extract_python.core import Pipeline, PipelineConfig

    pipeline_config = PipelineConfig.model_validate(pipeline_config)
    if pipeline_config.task_group.default != expected_group:
        pipeline = pipeline_config.pipeline.value
        msg = (
            f"invalid task for pipeline {pipeline}."
            f'Task "extract_content" runs on task group "{expected_group}". '
            f"{pipeline} is supposed to run task group"
            f" {pipeline_config.task_group.default}, please provide the appropriate"
            f" task name."
        )
        raise ValueError(msg)

    app_config = lifespan_config()
    data_dir = app_config.data_dir
    work_dir = app_config.work_dir
    docs = parse_extraction_request(docs, data_dir=data_dir)
    if progress is not None:
        progress = to_raw_progress(progress, max_progress=len(docs))
    output_format = OutputFormat(output_format)
    output_path = work_dir / output_path
    output_path.mkdir(parents=True, exist_ok=True)

    results = list()
    pipeline = Pipeline.from_config(pipeline_config)
    # TODO: potentially add caching to avoid preprocessing the same file
    n_processed = 0
    async for result in pipeline.extract_content(docs, output_format, output_path):
        results.append(result.to_response())
        if progress is not None:
            n_processed += 1
            await progress(n_processed)
    return ExtractionResponse(results=results).model_dump()
