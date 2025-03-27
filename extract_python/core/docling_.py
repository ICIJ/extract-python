from collections.abc import AsyncGenerator, Iterable, Iterator
from pathlib import Path
from typing import Any, Literal, TypeVar

from docling.backend.abstract_backend import AbstractDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    PdfPipelineOptions,
    PipelineOptions,
    VlmPipelineOptions,
)
from docling.document_converter import DocumentConverter, FormatOption
from docling.models.factories import get_ocr_factory
from docling.pipeline.base_pipeline import BasePipeline
from docling_core.types.io import DocumentStream
from icij_common.registrable import FromConfig
from pydantic import Field, model_validator

from extract_python.core.pipeline import Pipeline, PipelineConfig, PipelineType
from extract_python.objects import BaseModel, InputDoc, OutputFormat, Result
from extract_python.utils import all_subclasses, map_and_preserve

DEFAULT_ARTIFACTS_PATH = Path.home().joinpath(".cache", "docling", "models")


class _PdfPipelineOptions(PdfPipelineOptions):
    @model_validator(mode="before")
    @classmethod
    def validate_ocr_options(cls, data: Any) -> Any:
        if isinstance(data, dict):
            ocr_options = data.get("ocr_options")
            if not isinstance(ocr_options, dict):
                return data
            allow_external_plugins = ocr_options.get("allow_external_plugins", False)
            ocr_factory = get_ocr_factory(allow_external_plugins=allow_external_plugins)
            kind = ocr_options.pop("kind")
            data["ocr_options"] = ocr_factory.create_options(kind=kind, **ocr_options)
        return data


OptionsByPipeline = list[
    tuple[Literal["pdf"], _PdfPipelineOptions]
    | tuple[Literal["vlm"], VlmPipelineOptions]
]


def _default_format_options() -> OptionsByPipeline:
    pipeline_options = _PdfPipelineOptions(
        ocr_options=EasyOcrOptions(),
        artifacts_path=str(DEFAULT_ARTIFACTS_PATH),
    )
    return [
        ("pdf", pipeline_options),
        ("vlm", VlmPipelineOptions(artifacts_path=str(DEFAULT_ARTIFACTS_PATH))),
    ]


class DoclingFormatOption(BaseModel):
    pipeline_cls: str
    backend_cls: str

    def to_docling(
        self, pipeline_options: dict[Literal["pdf", "vlm"], PipelineOptions]
    ) -> FormatOption:
        pipeline_cls = _find_subcls(BasePipeline, self.pipeline_cls)
        backend_cls = _find_subcls(AbstractDocumentBackend, self.backend_cls)
        if "vlm" in self.pipeline_cls.lower():
            pipeline_options = pipeline_options.get("vlm")
            if pipeline_options is not None:
                pipeline_options = VlmPipelineOptions.model_validate(pipeline_options)
        elif "pdf" in self.pipeline_cls.lower():
            pipeline_options = pipeline_options.get("pdf")
            if pipeline_options is not None:
                pipeline_options = _PdfPipelineOptions.model_validate(pipeline_options)
        else:
            raise ValueError(
                f"invalid pipeline_cls: {pipeline_cls}, expected a VLM or PDF pipeline"
            )
        return FormatOption(
            pipeline_cls=pipeline_cls,
            pipeline_options=pipeline_options,
            backend=backend_cls,
        )


T = TypeVar("T")


def _find_subcls(cls: type[T], name: str) -> type[T]:
    for c in all_subclasses(cls):
        if c.__name__ == name:
            return c
    raise ValueError(f"unknown {cls.__name__} subclass {name}")


@PipelineConfig.register()
class DoclingPipelineConfig(PipelineConfig):
    pipeline: PipelineType = Field(frozen=True, default=PipelineType.DOCLING)

    pipeline_options: OptionsByPipeline = Field(default_factory=_default_format_options)
    format_options: dict[InputFormat, DoclingFormatOption] = dict()

    def to_format_options(self) -> dict[InputFormat, FormatOption]:
        pipeline_options = dict(self.pipeline_options)
        return {
            InputFormat(f): opt.to_docling(pipeline_options)
            for f, opt in self.format_options.items()
        }


@Pipeline.register(PipelineType.DOCLING.value)
class DoclingPipeline(Pipeline):
    def __init__(self, format_options: dict[InputFormat, FormatOption] | None = None):
        self._convert = DocumentConverter(format_options=format_options)

    async def extract_content(
        self, docs: Iterable[InputDoc], output_format: OutputFormat
    ) -> AsyncGenerator[Result, None]:
        docs, path_or_streams = map_and_preserve(_to_docling, docs)
        outputs = self._convert.convert_all(path_or_streams, raises_on_error=False)
        for doc, res in zip(docs, outputs):
            yield Result.from_docling(res, doc, output_format)

    @classmethod
    def _from_config(cls, config: DoclingPipelineConfig) -> FromConfig:
        return cls(config.to_format_options())


def _to_docling(docs: Iterable[InputDoc]) -> Iterator[Path | DocumentStream]:
    for d in docs:
        yield d.to_docling()
