from docling.datamodel.backend_options import PdfBackendOptions
from docling.datamodel.base_models import InputFormat
from extract_core import DoclingFormatOption, DoclingPipelineConfig


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
                pipeline_cls="LegacyStandardPdfPipeline",
                backend_options=PdfBackendOptions(),
                backend="PyPdfiumDocumentBackend",
            )
        },
    )
    assert deserialized == expected


def test_format_option_ser() -> None:
    # Given
    config = DoclingPipelineConfig(
        format_options={
            InputFormat.PDF: DoclingFormatOption(
                pipeline_cls="LegacyStandardPdfPipeline",
                backend_options=PdfBackendOptions(),
                backend="PyPdfiumDocumentBackend",
            )
        },
    )
    # When
    serialized = config.model_dump_json(indent=2)
    deserialized = DoclingPipelineConfig.model_validate_json(serialized)
    assert deserialized == config
