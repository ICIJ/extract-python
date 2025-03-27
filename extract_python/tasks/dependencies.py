import logging

from icij_worker import WorkerConfig
from icij_worker.utils.dependencies import DependencyInjectionError

from extract_python.config import AppConfig

logger = logging.getLogger(__name__)

_ASYNC_APP_CONFIG: AppConfig | None = None


def app_config_setup(worker_config: WorkerConfig, **_) -> None:
    global _ASYNC_APP_CONFIG
    if worker_config.app_bootstrap_config_path is not None:
        _ASYNC_APP_CONFIG = AppConfig.model_validate_json(
            worker_config.app_bootstrap_config_path.read_text()
        )
    else:
        # Load from env
        _ASYNC_APP_CONFIG = AppConfig()


def loggers_setup(worker_id: str, **_) -> None:
    config = lifespan_config()
    config.setup_loggers(worker_id=worker_id)
    logger.info("worker loggers ready to log 💬")
    logger.info("app config: %s", config.model_dump_json(indent=2))


def lifespan_config() -> AppConfig:
    if _ASYNC_APP_CONFIG is None:
        raise DependencyInjectionError("config")
    return _ASYNC_APP_CONFIG


APP_LIFESPAN_DEPS = [
    ("loading async app configuration", app_config_setup, None),
    ("loggers", loggers_setup, None),
]
