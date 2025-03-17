from typing import cast

import pytest

from extract_python.core.docling_ import DoclingPipeline, DoclingPipelineConfig
from extract_python.core.pipeline import Pipeline
from extract_python.objects import InputDoc, OutputFormat, Status
from tests import TEST_DATA_DIR


@pytest.fixture(scope="session")
def config() -> DoclingPipelineConfig:
    # TODO: for testing add a lightweight configuration
    return DoclingPipelineConfig()


@pytest.fixture(scope="session")
def pipeline(config: DoclingPipelineConfig) -> DoclingPipeline:
    return cast(DoclingPipeline, Pipeline.from_config(config=config))


@pytest.fixture(scope="session")
def docs() -> list[InputDoc]:
    doc_paths = ("scanned.pdf", "computer_generated.pdf")
    doc_paths = (TEST_DATA_DIR / p for p in doc_paths)
    docs = [InputDoc.from_path(p) for p in doc_paths]
    return docs


@pytest.mark.integration
async def test_docling_pdf_to_markdown(
    pipeline: DoclingPipeline, docs: list[InputDoc]
) -> None:
    # When
    output_format = OutputFormat.MARKDOWN
    res = [r async for r in pipeline.extract_content(docs, output_format)]
    # Then
    assert all(r.status == Status.SUCCESS for r in res)
    assert all(r.result.content for r in res)
    assert all(r.result.pages for r in res)
    assert not any(r.errors for r in res)
    input_path = [r.input.path for r in res]
    expected_path = [
        TEST_DATA_DIR / "scanned.pdf",
        TEST_DATA_DIR / "computer_generated.pdf",
    ]
    assert input_path == expected_path
