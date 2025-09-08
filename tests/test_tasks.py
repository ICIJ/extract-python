from pathlib import Path

from extract_python.app import extract_content
from extract_python.config import AppConfig
from extract_python.objects import ExtractionResponse, Status


async def test_extract_content(
    with_worker_lifespan_deps: None,  # noqa: ARG001
    test_data_dir: Path,  # noqa: ARG001
    test_app_config: AppConfig,
) -> None:
    # Given
    docs = "."
    pipeline_config = {
        "pipeline": "docling",
        "pipeline_options": [
            ["pdf", {"ocr_options": {"kind": "tesserocr", "lang": ["auto"]}}]
        ],
        "format_options": {
            "pdf": {
                "pipeline_cls": "StandardPdfPipeline",
                "backend_cls": "DoclingParseV4DocumentBackend",
            },
        },
    }
    output_path = "outputs"
    output_format = ".md"
    # When
    response = await extract_content(docs, pipeline_config, output_path, output_format)
    # Then
    res = ExtractionResponse.model_validate(response)
    assert not any(r.errors for r in res.results)
    assert all(r.status is Status.SUCCESS for r in res.results)
    expected_paths = ["computer_generated_pdf", "scanned_pdf"]
    expected_paths = [Path(p) for p in expected_paths]
    for expected_path, r in zip(expected_paths, res.results):
        assert r.output_path == expected_path
        expected_dir = test_app_config.work_dir / output_path / r.output_path
        assert expected_dir.exists()
