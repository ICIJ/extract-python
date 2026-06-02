from pathlib import Path
from typing import cast

import pytest

from extract_python import (
    InputDoc,
    MinerUPipeline,
    MinerUPipelineConfig,
    OutputFormat,
    Pipeline,
    Status,
)
from tests import TEST_DATA_DIR


@pytest.fixture(scope="session")
def config() -> MinerUPipelineConfig:
    return MinerUPipelineConfig()


@pytest.fixture(scope="session")
def pipeline(config: MinerUPipelineConfig) -> MinerUPipeline:
    return cast(MinerUPipelineConfig, Pipeline.from_config(config=config))


@pytest.mark.miner_u
@pytest.mark.integration
async def test_miner_u_pdf_to_markdown(
    pipeline: MinerUPipeline, docs: list[InputDoc], tmpdir: Path
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
    for p in expected_output_paths:
        assert (output_path / p).exists()
        assert (output_path / p).is_dir()
        assert (output_path / p / p.name).with_suffix(".md").exists()
        assert any((output_path / p).glob("artifacts/*.jpg"))
    assert all(r.output.pages for r in res)
    assert not any(r.errors for r in res)
    input_path = [r.input.path for r in res]
    expected_path = [
        TEST_DATA_DIR / "scanned.pdf",
        TEST_DATA_DIR / "computer_generated.pdf",
    ]
    assert input_path == expected_path
