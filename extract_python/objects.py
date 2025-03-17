from __future__ import annotations

import traceback
import uuid
from enum import Enum
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Any, Self

from icij_common.pydantic_utils import (
    icij_config,
    merge_configs,
    no_enum_config,
    safe_copy,
)
from pydantic import BaseModel

try:
    from docling.datamodel.base_models import ConversionStatus, ErrorItem, InputFormat
    from docling.datamodel.document import InputDocument
    from docling.document_converter import FormatOption
    from docling_core.types.io import DocumentStream
except ImportError:
    ConversionStatus, ErrorItem, InputFormat = None, None, None
    InputDocument = None
    FormatOption = None
    DocumentStream = None

base_config = merge_configs(icij_config(), no_enum_config())


class SupportedExt(str, Enum):
    PDF = ".pdf"

    def to_docling(self) -> InputFormat:
        return InputFormat(self.value[1:])


class OutputFormat(str, Enum):
    MARKDOWN = "markdown"


class Status(str, Enum):
    FAILURE = "failure"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"

    @classmethod
    def from_docling(cls, v: Any) -> Self:
        from docling.datamodel.base_models import ConversionStatus

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
    model_config = base_config

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
    model_config = base_config

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


PageIndexes = list[int]


class MarkdownDoc(BaseModel):
    model_config = base_config

    content: str
    pages: PageIndexes = []

    @classmethod
    def from_docling(cls, res: Any, **kwargs) -> Self:
        from docling.datamodel.document import ConversionResult
        from docling_core.types.doc import ImageRefMode

        if not isinstance(res, ConversionResult):
            raise TypeError(f"expected {ConversionResult.__name__} but got {type(res)}")
        if res.status not in cls._valid_conversion_statuses:
            raise ValueError("can't convert unsuccessful result")
        md = ""
        pages = [0]
        for page_i in range(len(res.pages)):
            md += "\n" + res.document.export_to_markdown(
                page_no=page_i + 1, image_mode=ImageRefMode.REFERENCED, **kwargs
            )
            pages.append(len(md))
        return cls(content=md, pages=pages)

    @classmethod
    @property
    @cache
    def _valid_conversion_statuses(cls) -> set[ConversionStatus]:
        from docling.datamodel.base_models import ConversionStatus

        return {ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS}


class Result(BaseModel):
    model_config = base_config

    input: InputDoc

    status: Status
    errors: list[Error] = []

    # TODO: use generics here when we add more output formats
    result: MarkdownDoc | None

    @classmethod
    def from_docling(
        cls, res: Any, input_document: InputDoc, output_format: OutputFormat, **kwargs
    ) -> Self:
        from docling.datamodel.document import ConversionResult

        if not isinstance(res, ConversionResult):
            raise TypeError(f"expected {ConversionResult.__name__} but got {type(res)}")

        result = None
        status = Status.from_docling(res.status)
        if status.allows_conversion:
            if output_format is OutputFormat.MARKDOWN:
                result = MarkdownDoc.from_docling(res, **kwargs)
            else:
                raise NotImplementedError(f"unsupported output format {output_format}")
        errors = [Error.from_docling(e) for e in res.errors]
        input_doc = input_document.without_content()
        return cls(input=input_doc, status=status, errors=errors, result=result)
