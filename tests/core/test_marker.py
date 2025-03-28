from pathlib import Path
from typing import cast

import pytest

from extract_python.core import MarkerPipeline, MarkerPipelineConfig, Pipeline
from extract_python.objects import InputDoc, OutputFormat, Status
from tests import TEST_DATA_DIR


@pytest.fixture(scope="session")
def config() -> MarkerPipelineConfig:
    return MarkerPipelineConfig()


@pytest.fixture(scope="session")
def pipeline(config: MarkerPipelineConfig) -> MarkerPipeline:
    return cast(MarkerPipeline, Pipeline.from_config(config=config))


@pytest.mark.integration
async def test_marker_pdf_to_markdown(
    pipeline: MarkerPipeline, docs: list[InputDoc], tmpdir: Path
) -> None:
    # Given
    output_path = Path(tmpdir)
    # When
    output_format = OutputFormat.MARKDOWN
    res = [r async for r in pipeline.extract_content(docs, output_format, output_path)]
    # Then
    assert all(r.status == Status.SUCCESS for r in res)
    expected_output_paths = ["scanned_pdf", "computer_generated_pdf"]
    expected_output_paths = [Path(p) for p in expected_output_paths]
    output_paths = [r.output.path for r in res]
    assert output_paths == expected_output_paths
    assert all(r.output.pages for r in res)
    assert not any(r.errors for r in res)
    input_path = [r.input.path for r in res]
    expected_path = [
        TEST_DATA_DIR / "scanned.pdf",
        TEST_DATA_DIR / "computer_generated.pdf",
    ]
    assert input_path == expected_path
