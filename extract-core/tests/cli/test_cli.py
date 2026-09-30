import pytest
from extract_core.cli import cli_app
from typer.testing import CliRunner


@pytest.fixture  # noqa: F405
def typer_asyncio_patch() -> None:
    import nest_asyncio  # noqa: PLC0415

    nest_asyncio.apply()


async def test_get_models(
    typer_asyncio_patch,  # noqa: ANN001, ARG001
) -> None:
    # Given
    runner = CliRunner()
    cmd = ["config", "get-default", "--size", "small", "-d", "cuda", "docling"]
    # When
    result = runner.invoke(cli_app, cmd, catch_exceptions=False)
    # Then
    assert int(result.exit_code) == 0
    assert '"device": "cuda"' in result.output
    assert '"pipeline": "docling"' in result.output
