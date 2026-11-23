from extract_core import HybridLiteParsePipelineConfig


def test_hybrid_liteparse_supported_exts() -> None:
    # Given
    config = HybridLiteParsePipelineConfig()
    # When
    supported = config.supported_exts()
    # Then
    assert supported
    assert isinstance(supported, set)
