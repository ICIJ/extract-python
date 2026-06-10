from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    TesseractOcrOptions,
    ThreadedPdfPipelineOptions,
)
from docling.document_converter import PdfFormatOption
from extract_core import DoclingPipelineConfig, PipelineConfig
from pydantic import TypeAdapter


def test_docling_pipeline_config() -> None:
    # Given
    ta = TypeAdapter(PipelineConfig)
    config = {
        "pipeline": "docling",
        "format_options": {
            "pdf": {
                "pipeline_cls": "StandardPdfPipeline",
                "backend": "DoclingParseDocumentBackend",
                "pipeline_options": {
                    "ocr_options": {"kind": "tesserocr", "lang": ["auto"]},
                    "generate_picture_images": True,
                },
            }
        },
    }
    # When
    pipeline_config = ta.validate_python(config)
    # Then
    assert isinstance(pipeline_config, DoclingPipelineConfig)
    format_options = pipeline_config.format_options
    pdf_options = format_options[InputFormat.PDF]
    pdf_pipeline_options = pdf_options.to_docling()
    expected_options = PdfFormatOption(
        pipeline_options=ThreadedPdfPipelineOptions(
            ocr_options=TesseractOcrOptions(lang=["auto"]),
            generate_picture_images=True,
        )
    )
    assert pdf_pipeline_options.model_dump() == expected_options.model_dump()
