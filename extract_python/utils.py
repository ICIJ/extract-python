from collections.abc import Iterable, Iterator
from itertools import tee
from typing import Callable, TypeVar

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
