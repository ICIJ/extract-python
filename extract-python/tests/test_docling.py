from pathlib import Path
from typing import cast

import pytest
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.pipeline_options import VlmConvertOptions, VlmPipelineOptions
from extract_core import (
    DoclingFormatOption,
    DoclingPipelineConfig,
    InputDoc,
    OutputFormat,
    Pipeline,
    Status,
)
from extract_core.objects import Device
from extract_python import DoclingPipeline

from . import TEST_DATA_DIR


@pytest.fixture(scope="session")
def config() -> DoclingPipelineConfig:
    # TODO: for testing add a lightweight configuration
    config = DoclingPipelineConfig()
    return config


@pytest.fixture(scope="session")
def pipeline(config: DoclingPipelineConfig, device: Device) -> DoclingPipeline:
    return cast(DoclingPipeline, Pipeline.from_config(config=config, device=device))


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


def test_should_serialize_and_deserialize_format_options() -> None:
    # Given
    from docling.document_converter import PdfFormatOption  # noqa: PLC0415
    from docling.pipeline.vlm_pipeline import VlmPipeline  # noqa: PLC0415
    from docling_ import SerializableFormatOptions  # noqa: PLC0415

    vlm_options = VlmConvertOptions.from_preset("granite_docling")
    format_opts = PdfFormatOption(
        pipeline_cls=VlmPipeline,
        pipeline_options=VlmPipelineOptions(
            vlm_options=vlm_options,
            generate_picture_images=True,
            accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU),
        ),
    )
    serializable = SerializableFormatOptions.from_docling(format_opts)
    # When
    serialized = serializable.model_dump(polymorphic_serialization=True)
    # Then
    deserialized = DoclingFormatOption.model_validate(serialized)
    assert deserialized.to_docling(Device.CPU).model_dump() == format_opts.model_dump()
