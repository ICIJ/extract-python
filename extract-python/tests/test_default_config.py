from itertools import product

import pytest
from extract_core import BasePipelineConfig, Device, PipelineSize, PipelineType
from extract_core.default_config import default_config


# This test should belong to the core but the core has no split test between
# conflicting miner_u/marker
@pytest.mark.parametrize(
    ("pipeline_type", "device", "size"),
    list(product([PipelineType.DOCLING, PipelineType.MARKER], Device, PipelineSize)),
)
def test_default_config_should_be_define_for_all_input_parameters(
    pipeline_type: PipelineType, device: Device, size: PipelineSize
) -> None:
    # When
    config = default_config(pipeline_type=pipeline_type, device=device, size=size)
    # Then
    assert isinstance(config, BasePipelineConfig)


@pytest.mark.miner_u
@pytest.mark.parametrize(
    ("device", "size"),
    list(product(Device, PipelineSize)),
)
def test_default_config_should_be_define_for_all_input_parameters_mineru(
    device: Device, size: PipelineSize
) -> None:
    # When
    config = default_config(
        pipeline_type=PipelineType.MINER_U, device=device, size=size
    )
    # Then
    assert isinstance(config, BasePipelineConfig)
