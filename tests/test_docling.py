from pathlib import Path
from typing import cast

import pytest
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.backend_options import PdfBackendOptions
from docling.datamodel.base_models import InputFormat
from docling.pipeline.legacy_standard_pdf_pipeline import LegacyStandardPdfPipeline

from extract_python import DoclingPipeline, DoclingPipelineConfig, Pipeline
from extract_python.docling_ import DoclingFormatOption
from extract_python.objects import InputDoc, OutputFormat, Status

from . import TEST_DATA_DIR


@pytest.fixture(scope="session")
def config() -> DoclingPipelineConfig:
    # TODO: for testing add a lightweight configuration
    config = DoclingPipelineConfig()
    return config


@pytest.fixture(scope="session")
def pipeline(config: DoclingPipelineConfig) -> DoclingPipeline:
    return cast(DoclingPipeline, Pipeline.from_config(config=config))


def test_format_option_derser() -> None:
    # Given
    config = {
        "format_options": {
            "pdf": {
                "pipeline_cls": "LegacyStandardPdfPipeline",
                "backend": "PyPdfiumDocumentBackend",
                "backend_options": {"kind": "pdf"},
            }
        }
    }
    # When
    deserialized = DoclingPipelineConfig.model_validate(config)
    # Then
    expected = DoclingPipelineConfig(
        format_options={
            InputFormat.PDF: DoclingFormatOption(
                pipeline_cls=LegacyStandardPdfPipeline,
                backend_options=PdfBackendOptions(),
                backend=PyPdfiumDocumentBackend,
            )
        },
    )
    assert deserialized == expected


@pytest.mark.integration
async def test_docling_pdf_to_markdown(
    pipeline: DoclingPipeline, docs: list[InputDoc], tmpdir: Path
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
        assert any((output_path / p).glob("artifacts/*.png"))
    assert all(r.output.pages for r in res)
    assert not any(r.errors for r in res)
    input_path = [r.input.path for r in res]
    expected_input_path = [
        TEST_DATA_DIR / "scanned.pdf",
        TEST_DATA_DIR / "computer_generated.pdf",
    ]
    assert input_path == expected_input_path
