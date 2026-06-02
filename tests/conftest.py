import os
import shutil
from pathlib import Path

import pytest

from extract_python.objects import InputDoc
from tests import TEST_DATA_DIR


@pytest.fixture(scope="session")
def docs() -> list[InputDoc]:
    doc_paths = ("scanned.pdf", "computer_generated.pdf")
    doc_paths = (TEST_DATA_DIR / p for p in doc_paths)
    docs = [InputDoc.from_path(p) for p in doc_paths]
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
