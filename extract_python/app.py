import logging

from icij_worker import AsyncApp

from extract_python.constants import CPU_GROUP, EXTRACT_CONTENT_TASK
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
) -> dict:
    from extract_python.core import PipelineConfig
    from extract_python.core.pipeline import Pipeline

    app_config = lifespan_config()
    data_dir = app_config.data_dir
    work_dir = app_config.work_dir
    docs = parse_extraction_request(docs, data_dir=data_dir)
    pipeline_config = PipelineConfig.model_validate(pipeline_config)
    output_format = OutputFormat(output_format)
    output_path = work_dir / output_path
    output_path.mkdir(parents=True, exist_ok=True)

    results = list()
    pipeline = Pipeline.from_config(pipeline_config)
    # TODO: potentially add caching to avoid preprocessing the same file
    async for result in pipeline.extract_content(docs, output_format=output_format):
        # TODO: improve output serialization here... We don't want the results to be
        #  saved on the task broker, at the same time using the disk might not be the
        #  best option...
        rel_path = result.input.path.relative_to(data_dir).with_suffix(
            output_format.value
        )
        file_path = output_path / rel_path
        file_path.write_text(result.result.content)
        results.append(result.to_response(rel_path))
    return ExtractionResponse(results=results).model_dump()
