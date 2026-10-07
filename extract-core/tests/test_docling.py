from docling.datamodel.accelerator_options import AcceleratorDevice
from docling.datamodel.backend_options import PdfBackendOptions
from docling.datamodel.base_models import InputFormat
from extract_core import Device, DoclingFormatOption, DoclingPipelineConfig


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


def test_docling_pipeline_should_resolve_cuda_accelerator() -> None:
    # Given
    format_opts = DoclingFormatOption(
        backend="PdfDocumentBackend",
        pipeline_cls="VlmPipeline",
    )
    config = DoclingPipelineConfig(
        device=Device.CUDA, format_options={InputFormat.PDF: format_opts}
    )
    # When
    config = config.to_device()
    # Then
    pdf_fmt_opts = config.format_options[InputFormat.PDF]
    device = pdf_fmt_opts.pipeline_options["accelerator_options"]["device"]
    assert device is AcceleratorDevice.CUDA
