import os
from collections.abc import Callable, Generator, Iterable, Iterator
from contextlib import contextmanager
from functools import wraps
from itertools import tee
from pathlib import Path, PurePath
from typing import Protocol, TypeVar

from .objects import Error, InputDoc, Result, Status

R = TypeVar("R")
T = TypeVar("T")


def map_and_preserve(
    fn: Callable[[Iterable[T]], Iterator[R]], inputs: Iterable[T]
) -> tuple[Iterable[T], Iterator[R]]:
    save_inputs, function_inputs = tee(inputs)
    outputs = iter(fn(function_inputs))
    return save_inputs, outputs


def all_subclasses(cls: type[T]) -> set[type[T]]:
    return set(cls.__subclasses__()).union(
        [s for c in cls.__subclasses__() for s in all_subclasses(c)]
    )


def path_to_artifacts_dirname(path: PurePath, sep: str = "_") -> str:
    dirname = f"{path.name[: -len(path.suffix)]}"
    ext = path.suffix
    if ext:
        dirname += sep + ext[1:]
    return dirname


class DocProcessingFn(Protocol):
    def __call__(self, doc: InputDoc, *arg, **kwargs) -> Result: ...


def report_recoverable_errors(
    recoverable_errors: tuple[type[Exception], ...] = tuple(),
) -> Callable[[DocProcessingFn], DocProcessingFn]:
    def make_decorator(f: DocProcessingFn) -> DocProcessingFn:
        @wraps(f)
        def wrapped(doc: InputDoc, *args, **kwargs) -> Result:
            try:
                return f(doc, *args, **kwargs)
            except recoverable_errors as e:
                error = Error.from_exception(e)
                return Result(
                    input=doc.without_content(),
                    status=Status.FAILURE,
                    errors=[error],
                    output=None,
                )

        return wrapped

    return make_decorator


@contextmanager
def chdir(path: Path) -> Generator[None, None, None]:
    cwd = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)
