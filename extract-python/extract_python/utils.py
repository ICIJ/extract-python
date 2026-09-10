import itertools
import logging
import os
import shutil
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Generator, Iterable, Iterator
from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass
from functools import wraps
from itertools import tee
from pathlib import Path, PurePath
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import BinaryIO, Protocol, Self

from extract_core import Error, InputDoc, Pages, Result, Status
from pympler import asizeof

logger = logging.getLogger(__name__)


def map_and_preserve[I, R](
    fn: Callable[[Iterable[I]], Iterator[R]], inputs: Iterable[I]
) -> tuple[Iterable[I], Iterator[R]]:
    save_inputs, function_inputs = tee(inputs)
    outputs = iter(fn(function_inputs))
    return save_inputs, outputs


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
                    input=doc, status=Status.FAILURE, errors=[error], output=None
                )

        return wrapped

    return make_decorator


@contextmanager
def chdir(path: Path) -> Generator[None]:
    cwd = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)


@contextmanager
def reset_env() -> Generator[None]:
    old_env = copy(dict(os.environ))
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_env)


def write_pages(pages: Iterable[str], page_sep: str, out: BinaryIO) -> Pages:
    pages_byte_sizes = []
    pages = iter(pages)
    content = None
    for p in pages:
        if content:
            pages_byte_sizes.append(out.write((content + page_sep).encode()))
        content = p
    if content:
        pages_byte_sizes.append(out.write(content.encode()))
    return Pages.from_pages_bytes_sizes(pages_byte_sizes)


Range = tuple[int, int]


@dataclass(frozen=True)
class ProcessedPages:
    doc: InputDoc
    doc_idx: int
    page_range: Range | None = None

    @property
    def page_length(self) -> int:
        if self.page_range is None:
            return self.doc.n_pages
        return self.page_range[1] - self.page_range[0]


class ResultBuffer[R]:
    def __init__(
        self,
        max_size_bytes: int,
        save_fn: Callable[[R, Path], None],
        *,
        load_fn: Callable[[Path], R],
        root: Path | None = None,
    ):
        self._max_bytes = max_size_bytes
        self._save_fn = save_fn
        self._load_fn = load_fn
        self._tmp_dir = None
        if root is None:
            self._tmp_dir = TemporaryDirectory()
            root = Path(self._tmp_dir.name)
        self._root = root
        self.__fs_buffer_path = None
        self._mem_buffer: dict[int, list[R | Path]] = defaultdict(list)
        self._missing_pages: dict[int, int] = dict()
        self._current_size: int = 0

    def __enter__(self) -> Self:
        if self._tmp_dir is not None:
            self._tmp_dir.__enter__()
        self.__fs_buffer_path = self._root / uuid.uuid4().hex
        self.__fs_buffer_path.mkdir()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._mem_buffer or self._missing_pages:
            logger.warning("closing an non empty buffer")
        if self._tmp_dir is not None:
            self._tmp_dir.__exit__(exc_type, exc_val, exc_tb)
        if self._fs_buffer_path.exists():
            shutil.rmtree(self._fs_buffer_path)
        self._mem_buffer = dict()
        self._missing_pages = dict()

    @property
    def _fs_buffer_path(self) -> Path:
        if not self.__fs_buffer_path:
            msg = (
                f"inconsistent state, {ResultBuffer.__class__.__name__} is a context"
                f" manager, call __enter__ before using it"
            )
            raise ValueError(msg)
        return self.__fs_buffer_path

    def add(self, processed: ProcessedPages, result: R) -> None:
        size = asizeof.asizeof(result)
        if self._current_size + size > self._max_bytes:
            path = self._page_path(processed.doc_idx)
            self._save_fn(result, path)
            result = path
        else:
            self._current_size += size
        self._mem_buffer[processed.doc_idx].append(result)
        if processed.doc_idx not in self._missing_pages:
            self._missing_pages[processed.doc_idx] = processed.doc.n_pages
        self._missing_pages[processed.doc_idx] -= processed.page_length

    def is_complete(self, doc: int) -> bool:
        return self._missing_pages[doc] == 0

    def pop_complete(self, doc: int) -> list[R]:
        if not self.is_complete(doc):
            raise ValueError(f"{doc} is incomplete")
        pages = self._mem_buffer.pop(doc)
        self._missing_pages.pop(doc)
        for i, page in enumerate(pages):
            if isinstance(page, Path):
                page = self._load_fn(page)  # noqa: PLW2901
            else:
                self._current_size -= asizeof.asizeof(page)
            pages[i] = page
        return pages

    def _page_path(self, doc_id: int) -> Path:
        pages = self._mem_buffer[doc_id]
        return self._fs_buffer_path / f"doc-{doc_id}-pages-{len(pages)}"

    def __len__(self) -> int:
        return len(self._mem_buffer)


# The converter process page_batch_size in parallel (GPU sees page_batch_size batches).
#
# The batching tradeoff is: avoid calling convert_all to many times vs. releasing the
# GIL often enough.
#
# Calling convert_all to many times on the same doc results in overhead. Each time we
# call the function, we create a doc processing backend + reload the doc.
#
# On the other hand we have to use a reasonable max_page_batches otherwise we process
# all the stream in a single call and take the risk to lock the GIL for too long. Some
# docling ops are sadly not async (numpy or torch inference are, but document loading
# and conversion aren't, so the asyncio.to_thread is not helping)
def batch_per_pages(
    docs: Iterable[InputDoc],
    page_batch_size: int,
    *,
    max_page_batches: int,
    chunk_size: int = 1000,
) -> Iterable[tuple[ProcessedPages]]:
    # convert_all only accept to process docs on the exact same page_range
    #
    # We collect by chunk to avoid collecting too many inputs, input docs are
    # lightweight anyway so memory impact should stay limited
    #
    # Additionally, results can be output unordered and partial results are buffered
    # it's OK to process doc pages unordered.
    # TODO: if it's not OK to sort because inputs is l
    max_pages = page_batch_size * max_page_batches
    docs = itertools.batched(docs, chunk_size, strict=False)
    for chunk in docs:
        short_docs = (d for d in chunk if d.n_pages <= max_pages)
        long_docs = (d for d in chunk if d.n_pages > max_pages)
        # Bin fill for docs smaller than max_pages
        offset = yield from _bin_fill(short_docs, max_pages=max_pages)
        # otherwise we just yield chunks of max_pages except the last chunk which is
        # grouped by page_range
        yield from _by_page_ranges(long_docs, max_pages=max_pages, offset=offset)


def _bin_fill(
    docs: Iterable[InputDoc], max_pages: int, offset: int = 0
) -> Generator[tuple[ProcessedPages], None, int]:
    bins = defaultdict(deque)
    doc_idx = offset
    for doc in docs:
        if doc.n_pages > max_pages:
            msg = f"expected docs to have <= {max_pages} pages"
            raise ValueError(msg)
        pages = ProcessedPages(doc=doc, doc_idx=doc_idx)
        doc_idx += 1
        available_space = (s for s in sorted(bins.keys()) if doc.n_pages <= s)
        available_space = next(available_space, max_pages)
        selected = bins[available_space]
        selected = selected.pop() if selected else []
        selected.append(pages)
        available_space -= doc.n_pages
        if available_space == 0:
            yield tuple(selected)
            continue
        bins[available_space].append(selected)
    for range_bins in bins.values():
        for b in range_bins:
            yield tuple(b)
    return doc_idx


def _by_page_ranges(
    docs: Iterable[InputDoc], max_pages: int, offset: int = 0
) -> Generator[tuple[ProcessedPages], None, int]:
    by_range = defaultdict(list)
    doc_idx = offset
    for doc in docs:
        if doc.n_pages < max_pages:
            msg = f"expected docs to have >= {max_pages} pages"
            raise ValueError(msg)

        for i in range(0, doc.n_pages, max_pages):
            start = i
            end = min(start + max_pages, doc.n_pages)
            rng = (start, end)
            rng_size = end - start
            alone_in_batch = rng_size == max_pages
            pages = ProcessedPages(doc=doc, doc_idx=doc_idx, page_range=rng)
            if alone_in_batch:
                yield (pages,)
                continue
            by_range[rng].append(pages)
            is_complete = len(by_range[rng]) == (max_pages // rng_size)
            if is_complete:
                yield tuple(by_range.pop(rng))
        doc_idx += 1
    for v in by_range.values():
        yield tuple(v)
    return doc_idx
