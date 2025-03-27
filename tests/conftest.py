import os
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from icij_worker import AMQPWorkerConfig

from extract_python.app import app
from extract_python.config import AppConfig
from tests import TEST_DATA_DIR


@pytest.fixture(scope="session")
def test_work_dir_session(tmpdir_factory) -> Path:  # noqa: ANN001
    return Path(tmpdir_factory.mktemp("passport_workdir"))


@pytest.fixture(scope="session")
def test_app_config(test_work_dir_session: Path) -> AppConfig:
    return AppConfig(
        data_dir=test_work_dir_session / "data", work_dir=test_work_dir_session
    )


@pytest.fixture
def test_work_dir(test_work_dir_session: Path) -> Path:
    for path in test_work_dir_session.iterdir():
        if path.is_file():
            os.unlink(path)
        else:
            shutil.rmtree(path)
    return test_work_dir_session


@pytest.fixture
def test_data_dir(test_work_dir: Path) -> Path:
    dir_name = TEST_DATA_DIR.name
    shutil.copytree(TEST_DATA_DIR, test_work_dir / dir_name)
    return test_work_dir / dir_name


@pytest.fixture(scope="session")
def test_app_config_path(tmpdir_factory, test_app_config: AppConfig) -> Path:  # noqa: ANN001
    config_path = Path(tmpdir_factory.mktemp("app_config")).joinpath("app_config.json")
    config_path.write_text(test_app_config.model_dump_json())
    return config_path


@pytest.fixture(scope="session")
def test_worker_config(test_app_config_path: Path) -> AMQPWorkerConfig:
    return AMQPWorkerConfig(
        log_level="DEBUG", app_bootstrap_config_path=test_app_config_path
    )


@pytest.fixture(scope="session")
async def with_worker_lifespan_deps(
    test_worker_config: AMQPWorkerConfig,
) -> AsyncGenerator[None, None]:
    worker_id = "test-worker-id"
    async with app.lifetime_dependencies(
        worker_config=test_worker_config, worker_id=worker_id
    ):
        yield
