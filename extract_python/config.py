from pathlib import Path
from typing import ClassVar

import icij_worker
from icij_common.pydantic_utils import ICIJSettings, icij_config, merge_configs
from icij_worker.utils.logging_ import LogWithWorkerIDMixin
from pydantic import Field
from pydantic_settings import SettingsConfigDict

import extract_python

_ALL_LOGGERS = [extract_python.__name__, icij_worker.__name__]


class AppConfig(ICIJSettings, LogWithWorkerIDMixin):
    model_config = merge_configs(
        icij_config(), SettingsConfigDict(env_prefix="EXTRACT_")
    )

    loggers: ClassVar[list[str]] = Field(_ALL_LOGGERS, frozen=True)
    log_level: str = Field(default="INFO")

    data_dir: Path
    work_dir: Path
