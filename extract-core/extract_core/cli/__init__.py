import importlib
import os
from typing import Annotated

import typer
from icij_common.logging_utils import setup_loggers

import extract_core

from .configs import configs_app
from .utils import AsyncTyper

cli_app = AsyncTyper(
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,
)
cli_app.add_typer(configs_app)


def version_callback(value: bool) -> None:  # noqa: FBT001
    if value:
        package_version = importlib.metadata.version(extract_core.__name__)
        print(package_version)
        raise typer.Exit()


def pretty_exc_callback(value: bool) -> None:  # noqa: FBT001
    if not value:
        os.environ["TYPER_STANDARD_TRACEBACK"] = "1"


@cli_app.callback()
def main(
    version: Annotated[  # noqa: ARG001
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True),
    ] = None,
    *,
    pretty_exceptions: Annotated[  # noqa: ARG001
        bool,
        typer.Option(
            "--pretty-exceptions", callback=pretty_exc_callback, is_eager=True
        ),
    ] = False,
) -> None:
    setup_loggers(["__main__", extract_core.__name__])
