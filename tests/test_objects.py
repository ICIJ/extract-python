try:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TesseractOcrOptions,
    )
except ImportError:
    InputFormat = None
    PdfPipelineOptions, TesseractOcrOptions = None, None


def test_docling_pipeline_config() -> None:
    from extract_python import DoclingPipelineConfig, PipelineConfig  # noqa: PLC0415

    # Given
    config = {
        "pipeline": "docling",
        "pipeline_options": [
            ["pdf", {"ocr_options": {"kind": "tesserocr", "lang": ["auto"]}}]
        ],
        "format_options": {
            "pdf": {
                "pipeline_cls": "StandardPdfPipeline",
                "backend_cls": "DoclingParseDocumentBackend",
            },
        },
    }
    # When

    pipeline_config = PipelineConfig.model_validate(config)
    # Then
    assert isinstance(pipeline_config, DoclingPipelineConfig)
    format_options = pipeline_config.to_format_options()
    pdf_options = format_options[InputFormat.PDF]
    pdf_pipeline_options = pdf_options.pipeline_options
    expected_options = PdfPipelineOptions(
        ocr_options=TesseractOcrOptions(lang=["auto"]),
        generate_picture_images=True,
    )
    assert pdf_pipeline_options.model_dump() == expected_options.model_dump()
