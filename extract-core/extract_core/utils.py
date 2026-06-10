from typing import TypeVar

T = TypeVar("T")


def all_subclasses(cls: type[T]) -> set[type[T]]:
    return set(cls.__subclasses__()).union(
        [s for c in cls.__subclasses__() for s in all_subclasses(c)]
    )
