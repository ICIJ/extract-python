from __future__ import annotations

import logging
import os
import traceback
import uuid
from abc import ABC
from enum import StrEnum
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, NoReturn, Self

from icij_common.pydantic_utils import (
    icij_config,
    merge_configs,
    no_enum_values_config,
    safe_copy,
)
from pydantic import AfterValidator, RootModel, TypeAdapter
from pydantic import BaseModel as _BaseModel

try:
    from docling.datamodel.base_models import ConversionStatus, ErrorItem, InputFormat
    from docling.datamodel.document import InputDocument
    from docling_core.types.io import DocumentStream
except ImportError:
    ConversionStatus, ErrorItem, InputFormat = None, None, None
    InputDocument = None
    DocumentStream = None

logger = logging.getLogger(__name__)
base_config = merge_configs(icij_config(), no_enum_values_config())


class BaseModel(_BaseModel):
    model_config = base_config


class SupportedExt(StrEnum):
    ADOC = ".adoc"
    ASCIIDOC = ".asciidoc"
    BMP = ".bmp"
    CSV = ".csv"
    DOC = ".doc"
    DOCX = ".docx"
    EPUB = ".epub"
    GIF = ".gif"
    HTLM = ".html"
    JPEG = ".jpeg"
    JPG = ".jpg"
    MD = ".md"
    ODP = ".odp"
    ODS = ".ods"
    ODT = ".odt"
    PDF = ".pdf"
    PNG = ".png"
    PPT = ".ppt"
    PPTX = ".pptx"
    TEX = ".tex"
    TIFF = ".tiff"
    TXT = ".txt"
    WEBP = ".webp"
    XHTML = ".xhtml"
    XLS = ".xls"
    XLSM = ".xlsm"
    XLSX = ".xlsx"
    XLTX = ".xltx"

    def to_docling(self) -> InputFormat:
        return InputFormat(self.value[1:])


class OutputFormat(StrEnum):
    MARKDOWN = ".md"

    @property
    def suffix(self) -> str:
        return self.value[1:]

    def to_marker(self) -> str:
        match self:
            case OutputFormat.MARKDOWN:
                return "markdown"
            case _:
                raise ValueError(f"{self} is unsupported by marker")


class Status(StrEnum):
    FAILURE = "failure"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"

    @classmethod
    def from_docling(cls, v: Any) -> Self:
        from docling.datamodel.base_models import ConversionStatus  # noqa: PLC0415

        if v is ConversionStatus.SUCCESS:
            return cls.SUCCESS
        if v is ConversionStatus.PARTIAL_SUCCESS:
            return cls.PARTIAL_SUCCESS
        if isinstance(v, ConversionStatus):
            return cls.FAILURE
        raise TypeError(f"can't convert {v!r} to {cls.__name__!r}")

    @property
    def allows_conversion(self) -> bool:
        return self is Status.SUCCESS or self is Status.PARTIAL_SUCCESS


class Error(BaseModel):
    id: str
    title: str
    detail: str

    @classmethod
    def from_exception(cls, exception: BaseException) -> Self:
        title = exception.__class__.__name__
        trace_lines = traceback.format_exception(
            None, value=exception, tb=exception.__traceback__
        )
        detail = f"{exception}\n{''.join(trace_lines)}"
        error_id = f"{_id_title(title)}-{uuid.uuid4().hex}"
        error = cls(id=error_id, title=title, detail=detail)
        return error

    @classmethod
    def from_docling(cls, docling_error: ErrorItem) -> Self:
        title = "DoclingConversionError"
        error_id = f"{_id_title(title)}-{uuid.uuid4().hex}"
        detail = (
            f"error in module {docling_error.module_name} of"
            f" {docling_error.component_type}:\n{docling_error.error_message}"
        )
        return cls(id=error_id, title=title, detail=detail)


def _id_title(title: str) -> str:
    id_title = []
    for i, letter in enumerate(title):
        if i and letter.isupper():
            id_title.append("-")
        id_title.append(letter.lower())
    return "".join(id_title)


class InputDoc(BaseModel):
    ext: SupportedExt
    path: Path
    content: bytes | None = None

    @classmethod
    def from_path(cls, path: str | Path) -> Self:
        if isinstance(path, str):
            path = Path(path)
        ext = SupportedExt(path.suffix)
        return cls(path=path, ext=ext)

    def to_docling(self) -> Path | DocumentStream:
        if self.content is not None:
            return DocumentStream(name=str(self.path), stream=BytesIO(self.content))
        if not self.path.suffix:
            return DocumentStream(
                name=str(self.path), stream=BytesIO(self.path.read_bytes())
            )
        return self.path

    def without_content(self) -> Self:
        return safe_copy(self, update={"content": None})


class PageIndexes(RootModel[list[tuple[int, int]]]):
    # Stores page end index
    @classmethod
    def from_page_end_indices(cls, lengths: list[int]) -> Self:
        return [
            ((lengths[p - 1] if p > 0 else 0), lengths[p]) for p in range(len(lengths))
        ]


class ConversionOutput(BaseModel):
    path: Path
    pages: PageIndexes = []


class MarkdownDoc(ConversionOutput):
    @classmethod
    @property
    @cache
    def _valid_conversion_statuses(cls) -> set[ConversionStatus]:
        from docling.datamodel.base_models import ConversionStatus  # noqa: PLC0415

        return {ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS}


def _input_should_not_have_content(value: InputDoc) -> InputDoc:
    if value.content is not None:
        raise ValueError(f"response input can't have content, but got {value}")
    return value


class _BaseResult(BaseModel, ABC):
    input: InputDoc
    status: Status
    errors: list[Error] = []


class Result(_BaseResult):
    # TODO: we could also use generics here when we add more output formats
    output: ConversionOutput | None

    def to_response(self) -> ResponseResult:
        return ResponseResult(
            input=self.input.without_content(),
            status=self.status,
            errors=self.errors,
            output_path=self.output.path,
        )


class ResponseResult(_BaseResult):
    input: Annotated[InputDoc, AfterValidator(func=_input_should_not_have_content)]
    output_path: Path


class ExtractionResponse(BaseModel):
    results: list[ResponseResult]


_INPUT_DOCS_ADAPTER = TypeAdapter(list[InputDoc | Path])


def parse_extraction_request(
    docs: str | list[dict | str], *, data_dir: Path
) -> list[InputDoc]:
    if isinstance(docs, str):
        logger.debug("exploring files in %s", data_dir.absolute())
        docs_dir = Path(data_dir) / docs
        docs = _as_input_docs(docs_dir)
        msg = "found %s"
        if len(docs) > 10:
            msg = msg + ", and more..."
        logger.debug("found %s", docs[:10])
        return docs
    docs = _INPUT_DOCS_ADAPTER.validate_python(docs)
    if not docs:
        return []
    if isinstance(docs[0], Path):
        doc_meta = []
        unknown_exts = []
        for doc in docs:
            _, ext = os.path.splitext(str(doc))
            if not ext:
                unknown_exts.append(doc)
            else:
                doc_meta.append(InputDoc.from_path(path=doc.relative_to(data_dir)))
        if unknown_exts:
            raise ValueError(f"found files with unknown extensions {unknown_exts}")
        return doc_meta
    return docs


def _raise(err: OSError) -> NoReturn:
    raise err


def _as_input_docs(
    docs_dir: Path, *, supported_ext: set[str] | None = None
) -> list[InputDoc]:
    if supported_ext is None:
        supported_ext = {v.value for v in SupportedExt}
    docs = []
    for root, _, files in os.walk(docs_dir, onerror=_raise):
        root = Path(root)  # noqa: PLW2901
        for f in files:
            ext = Path(f).suffix
            if not ext or ext not in supported_ext:
                continue
            docs.append(InputDoc.from_path(path=root / f))
    docs = sorted(docs, key=lambda x: x.path)
    return docs
