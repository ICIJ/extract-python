from functools import wraps
from typing import Callable, Protocol

from extract_python.objects import Error, InputDoc, Result, Status


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
