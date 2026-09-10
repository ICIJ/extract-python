import os
import platform
import shutil
from pathlib import Path

import pytest
from extract_core import Device, InputDoc

from tests import TEST_DATA_DIR


@pytest.fixture(scope="session")
def device() -> Device:
    if "darwin" in platform.system().lower():
        return Device.MPS
    return Device.CPU


@pytest.fixture(scope="session")
def docs() -> list[InputDoc]:
    docs = (("scanned.pdf", 1), ("computer_generated.pdf", 3))
    docs = ((TEST_DATA_DIR / path, n_pages) for path, n_pages in docs)
    docs = [InputDoc.from_path(path, n_pages=n_pages) for path, n_pages in docs]
    return docs


@pytest.fixture(scope="session")
def test_work_dir_session(tmpdir_factory) -> Path:  # noqa: ANN001
    return Path(tmpdir_factory.mktemp("passport_workdir"))


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
