from pathlib import Path
from typing import cast

import pytest
from extract_core import (
    InputDoc,
    LiteParsePipelineConfig,
    OutputFormat,
    Pipeline,
    Status,
)
from extract_python import DoclingPipeline
from extract_python.liteparse_ import LiteParsePipeline

from . import TEST_DATA_DIR


@pytest.fixture(scope="session")
def config() -> LiteParsePipelineConfig:
    config = LiteParsePipelineConfig(page_batch_size=1)
    return config


@pytest.fixture(scope="session")
def pipeline(config: LiteParsePipelineConfig) -> DoclingPipeline:
    return cast(LiteParsePipeline, Pipeline.from_config(config=config))


def test_pipeline_should_initialize_from_default() -> None:
    # Given
    config = LiteParsePipelineConfig()
    # When
    pipeline = Pipeline.from_config(config)
    # Then
    assert isinstance(pipeline, LiteParsePipeline)


@pytest.mark.integration
async def test_liteparse_pdf_to_markdown(
    pipeline: LiteParsePipeline, docs: list[InputDoc], tmpdir: Path
) -> None:
    # Given
    output_path = Path(tmpdir)
    # When
    output_format = OutputFormat.MARKDOWN
    res = [r async for r in pipeline.extract_content(docs, output_format, output_path)]
    # Then
    assert all(r.status == Status.SUCCESS for r in res)
    expected_output_paths = ["computer_generated_pdf", "scanned_pdf"]
    expected_output_paths = [Path(p) for p in expected_output_paths]
    output_paths = sorted(r.output.path for r in res)
    assert output_paths == expected_output_paths
    for p in expected_output_paths:
        assert (output_path / p).exists()
        assert (output_path / p).is_dir()
        assert (output_path / p / p.name).with_suffix(".md").exists()
        assert any((output_path / p).glob("artifacts/*.png"))
    assert all(r.output.pages.byte_ranges for r in res)
    assert not any(r.errors for r in res)
    input_path = sorted(r.input.path for r in res)
    expected_input_path = [
        TEST_DATA_DIR / "computer_generated.pdf",
        TEST_DATA_DIR / "scanned.pdf",
    ]
    assert input_path == expected_input_path
