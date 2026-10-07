import importlib
import itertools
from collections import defaultdict
from copy import deepcopy
from functools import cache
from typing import Annotated, Any, ClassVar, Self, get_type_hints

from docling.datamodel.backend_options import BackendOptions, BaseBackendOptions
from docling.datamodel.base_models import (
    BaseFormatOption,
    FormatToExtensions,
    InputFormat,
)
from docling.datamodel.pipeline_options import (
    BaseLayoutOptions,
    BaseTableStructureOptions,
    OcrOptions,
    PictureDescriptionBaseOptions,
    PipelineOptions,
)
from docling.datamodel.settings import (
    BatchConcurrencySettings as DoclingBatchConcurrencySettings,
)
from docling.datamodel.settings import DebugSettings
from docling.datamodel.settings import InferenceSettings as DoclingInferenceSettings
from icij_common.pydantic_utils import (
    merge_configs,
    safe_copy,
    tagged_union,
    to_lower_snake_case,
)
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Discriminator, Field, TypeAdapter, WrapSerializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler

from .configs import BasePipelineConfig, PipelineType, ResultBufferConfig
from .constants import DOCLING_DEFAULT_FORMAT_OPTIONS_PATH
from .objects import BaseModel, Device, PipelineSize, SupportedExt
from .utils import all_subclasses


@cache
def _ext_to_docling_input_format() -> dict:

    mapping = dict()
    supported = DoclingPipelineConfig.supported_exts()
    for input_f, exts in FormatToExtensions.items():
        for ext in exts:
            try:
                ext = SupportedExt(f".{ext.lower()}")  # noqa: PLW2901
            except ValueError:
                continue
            if ext in supported:
                mapping[ext] = input_f
    return mapping


def _validate_pipeline_opts(v: PipelineOptions) -> PipelineOptions:
    if hasattr(v, "generate_picture_images") and not v.generate_picture_images:
        msg = "generate_picture_images should be set to True"
        raise ValueError(msg)
    return v


def _find_subcls[T](cls: type[T], name: str) -> type[T]:
    # Check if the class available
    for c in all_subclasses(cls):
        if c.__name__ == name:
            return c
    # Then apply ad-hoc search
    if "pipeline" in cls.__name__.lower():
        module_name = f"docling.pipeline.{to_lower_snake_case(name)}"
        try:
            module = importlib.import_module(module_name)
            return getattr(module, name)
        except (ModuleNotFoundError, AttributeError):
            pass
    raise ValueError(f"unknown {cls.__name__} subclass {name}")


def _find_init_arg_type(cls: type[Any], arg: str) -> type[BaseModel]:
    hints = get_type_hints(cls.__init__)
    return hints[arg]


def _resolve_pipeline_cls(v: str) -> Any:
    if isinstance(v, str):
        from docling.pipeline.base_pipeline import BasePipeline  # noqa: PLC0415

        return _find_subcls(BasePipeline, v)
    return v


def _ser_as_str(v: type) -> str:
    return v.__name__


def _ser_with_backend_option_kind(
    v: Any, handler: SerializerFunctionWrapHandler
) -> Any:
    serialized = handler(v)
    if isinstance(v, BaseBackendOptions):
        kind = getattr(v, "kind", None)
        if kind is not None:
            serialized["kind"] = kind
    return serialized


def _resolve_backend(v: Any) -> Any:
    from docling.backend.abstract_backend import (  # noqa: PLC0415
        AbstractDocumentBackend,
    )

    if isinstance(v, str):
        return _find_subcls(AbstractDocumentBackend, v)
    return v


@cache
def _picture_descr_opts_type_adapter() -> TypeAdapter:
    _PictureDescriptionModel = Annotated[  # noqa: N806
        tagged_union(
            PictureDescriptionBaseOptions.__subclasses__(), tag_getter=lambda x: x.kind
        ),
        Discriminator(lambda x: x["kind"]),
    ]
    return TypeAdapter(_PictureDescriptionModel)


@cache
def _ocr_opts_type_adapter() -> TypeAdapter:
    _OcrOptions = Annotated[  # noqa: N806
        tagged_union(OcrOptions.__subclasses__(), tag_getter=lambda x: x.kind),
        Discriminator(lambda x: x.pop("kind")),
    ]
    return TypeAdapter(_OcrOptions)


@cache
def _layout_opts_type_adapter() -> TypeAdapter:
    _LayoutOptions = Annotated[  # noqa: N806
        tagged_union(BaseLayoutOptions.__subclasses__(), tag_getter=lambda x: x.kind),
        Discriminator(lambda x: x["kind"]),
    ]
    return TypeAdapter(_LayoutOptions)


@cache
def _table_structure_opts_type_adapter() -> TypeAdapter:
    _TableStructureOptions = Annotated[  # noqa: N806
        tagged_union(
            BaseTableStructureOptions.__subclasses__(), tag_getter=lambda x: x.kind
        ),
        Discriminator(lambda x: x["kind"]),
    ]
    return TypeAdapter(_TableStructureOptions)


def _resolve_pipeline_options(
    pipeline_options: dict[str, Any] | None,
    pipeline_cls: type,
) -> PipelineOptions:
    option_cls = _find_init_arg_type(pipeline_cls, "pipeline_options")
    if pipeline_options is None:
        pipeline_options = {"generate_picture_images": True}
    picture_descr_opts = pipeline_options.get("picture_description_options")
    if picture_descr_opts is not None:
        if "kind" not in picture_descr_opts:
            msg = f"missing picture description options kind: {picture_descr_opts}"
            raise ValueError(msg)

        picture_descr_opts = _picture_descr_opts_type_adapter().validate_python(
            picture_descr_opts
        )
        pipeline_options["picture_description_options"] = picture_descr_opts
    ocr_opts = pipeline_options.get("ocr_options")
    if ocr_opts is not None:
        if "kind" not in ocr_opts:
            msg = f"missing ocr options kind: {ocr_opts}"
            raise ValueError(msg)
        ocr_opts = _ocr_opts_type_adapter().validate_python(ocr_opts)
        pipeline_options["ocr_options"] = ocr_opts
    layout_opts = pipeline_options.get("layout_options")
    if layout_opts is not None:
        if "kind" not in layout_opts:
            msg = f"missing layout options kind: {layout_opts}"
            raise ValueError(msg)
        layout_opts = _layout_opts_type_adapter().validate_python(layout_opts)
        pipeline_options["layout_options"] = layout_opts
    table_structure_opts = pipeline_options.get("table_structure_options")
    if table_structure_opts is not None:
        if "kind" not in table_structure_opts:
            msg = f"missing table structure options kind: {table_structure_opts}"
            raise ValueError(msg)
        table_structure_opts = _table_structure_opts_type_adapter().validate_python(
            table_structure_opts
        )
        pipeline_options["table_structure_options"] = table_structure_opts
    pipeline_options = option_cls.model_validate(pipeline_options)
    return pipeline_options


# Mimics the docling FormatOption but only with lightweight types,
# the heavy convertion is done at runtime
class DoclingFormatOption(BaseFormatOption):
    model_config = merge_configs(
        BaseModel.model_config, ConfigDict(polymorphic_serialization=True)
    )
    backend: str
    backend_options: Annotated[
        BackendOptions | None, WrapSerializer(_ser_with_backend_option_kind)
    ] = None
    pipeline_cls: str
    pipeline_options: dict[str, Any] | None = None

    def to_docling(self) -> BaseFormatOption:  # noqa: ANN201
        from docling.document_converter import FormatOption  # noqa: PLC0415

        pipeline_cls = _resolve_pipeline_cls(self.pipeline_cls)
        pipeline_opts = _resolve_pipeline_options(self.pipeline_options, pipeline_cls)
        pipeline_opts = _validate_pipeline_opts(pipeline_opts)
        return FormatOption(
            pipeline_cls=pipeline_cls,
            pipeline_options=pipeline_opts,
            backend=_resolve_backend(self.backend),
            backend_options=self.backend_options,
        )


FormatOptionsBySizeAndDevice = dict[
    PipelineSize, dict[Device, dict[InputFormat, DoclingFormatOption]]
]
FMT_OPTS_TA = TypeAdapter(FormatOptionsBySizeAndDevice)


def default_format_opts(
    *, size: PipelineSize = PipelineSize.SMALL, device: Device = Device.CPU
) -> dict[InputFormat, DoclingFormatOption]:
    # Load options from the FS rather than generating them. This factory is used as a
    # default in Pydantic deserialization. Sadly _default_format_options import
    # functions which are not in the core of docling and require a lot of deps we don't
    # want to install.
    # To avoid this we generate options at build time, serialize them and load them
    # at runtime
    return deepcopy(_load_format_opts()[size][device])


@cache
def _load_format_opts() -> FormatOptionsBySizeAndDevice:
    opts = FMT_OPTS_TA.validate_json(DOCLING_DEFAULT_FORMAT_OPTIONS_PATH.read_text())
    return opts


def generate_default_format_options() -> FormatOptionsBySizeAndDevice:
    opts = defaultdict(dict)
    for size, device in itertools.product(PipelineSize, Device):
        default = _default_format_options()
        accelerator_opts = deepcopy(default[InputFormat.PDF].pipeline_options)[
            "accelerator_options"
        ]
        accelerator_opts["device"] = device.to_docling()
        pdf_pipeline_opts = default[InputFormat.PDF].pipeline_options
        pdf_pipeline_opts["accelerator_options"] = accelerator_opts
        match size:
            case PipelineSize.LARGE:
                pipeline = "VlmPipeline"
            case _:
                pipeline = "ThreadedStandardPdfPipeline"
        backend_opts = default[InputFormat.PDF].backend_options
        pdf_fmt_opts = DoclingFormatOption(
            pipeline_options=pdf_pipeline_opts,
            pipeline_cls=pipeline,
            backend="ThreadedDoclingParseDocumentBackend",
            backend_options=backend_opts,
        )
        default[InputFormat.PDF] = pdf_fmt_opts
        image_fmt_opts = DoclingFormatOption(
            pipeline_options=deepcopy(pdf_pipeline_opts),
            pipeline_cls=pipeline,
            backend="ImageDocumentBackend",
            backend_options=deepcopy(backend_opts),
        )
        default[InputFormat.IMAGE] = image_fmt_opts
        opts[size][device] = default
    return opts


def _default_format_options() -> dict[InputFormat, DoclingFormatOption]:
    from docling.backend.json.docling_json_backend import (  # noqa: PLC0415
        DoclingJSONBackend,
    )
    from docling.backend.mets_gbs_backend import MetsGbsDocumentBackend  # noqa: PLC0415
    from docling.backend.webvtt_backend import WebVTTDocumentBackend  # noqa: PLC0415
    from docling.document_converter import (  # noqa: PLC0415  # noqa: PLC0415
        AsciiDocFormatOption,
        AudioFormatOption,
        BoxNoteFormatOption,
        CsvFormatOption,
        DclxFormatOption,
        EbcdicFormatOption,
        EmailFormatOption,
        EpubFormatOption,
        ExcelFormatOption,
        FormatOption,
        HTMLFormatOption,
        ImageFormatOption,
        IWorkPagesFormatOption,
        LatexFormatOption,
        MarkdownFormatOption,
        OdpFormatOption,
        OdsFormatOption,
        OdtFormatOption,
        PatentUsptoFormatOption,
        PdfFormatOption,
        PowerpointFormatOption,
        VideoFormatOption,
        WordFormatOption,
        XBRLFormatOption,
        XMLDocLangFormatOption,
        XMLJatsFormatOption,
    )
    from docling.pipeline.simple_pipeline import SimplePipeline  # noqa: PLC0415
    from docling.pipeline.standard_pdf_pipeline import (  # noqa: PLC0415
        StandardPdfPipeline,
    )

    default = {
        InputFormat.CSV: CsvFormatOption(),
        InputFormat.BOXNOTE: BoxNoteFormatOption(),
        InputFormat.XLSX: ExcelFormatOption(),
        InputFormat.XLS: ExcelFormatOption(),
        InputFormat.DOCX: WordFormatOption(),
        InputFormat.DOC: WordFormatOption(),
        InputFormat.PPTX: PowerpointFormatOption(),
        InputFormat.PPT: PowerpointFormatOption(),
        InputFormat.ODT: OdtFormatOption(),
        InputFormat.ODS: OdsFormatOption(),
        InputFormat.ODP: OdpFormatOption(),
        InputFormat.MD: MarkdownFormatOption(),
        InputFormat.ASCIIDOC: AsciiDocFormatOption(),
        InputFormat.HTML: HTMLFormatOption(),
        InputFormat.XML_USPTO: PatentUsptoFormatOption(),
        InputFormat.XML_JATS: XMLJatsFormatOption(),
        InputFormat.XML_DOCLANG: XMLDocLangFormatOption(),
        InputFormat.DCLX: DclxFormatOption(),
        InputFormat.XML_XBRL: XBRLFormatOption(),
        InputFormat.METS_GBS: FormatOption(
            pipeline_cls=StandardPdfPipeline, backend=MetsGbsDocumentBackend
        ),
        InputFormat.IMAGE: ImageFormatOption(),
        InputFormat.PDF: PdfFormatOption(),
        InputFormat.JSON_DOCLING: FormatOption(
            pipeline_cls=SimplePipeline, backend=DoclingJSONBackend
        ),
        InputFormat.AUDIO: AudioFormatOption(),
        InputFormat.VIDEO: VideoFormatOption(),
        InputFormat.VTT: FormatOption(
            pipeline_cls=SimplePipeline, backend=WebVTTDocumentBackend
        ),
        InputFormat.LATEX: LatexFormatOption(),
        InputFormat.EMAIL: EmailFormatOption(),
        InputFormat.EPUB: EpubFormatOption(),
        InputFormat.IWORK_PAGES: IWorkPagesFormatOption(),
        InputFormat.EBCDIC: EbcdicFormatOption(),
    }
    for fmt, opts in default.items():
        pipeline_opts = opts.pipeline_options
        if pipeline_opts is not None:
            pipeline_opts = _dump_pipeline_opts_with_kind(pipeline_opts)
        opts = DoclingFormatOption(  # noqa: PLW2901
            backend=opts.backend.__name__,
            backend_options=opts.backend_options,
            pipeline_cls=opts.pipeline_cls.__name__,
            pipeline_options=pipeline_opts,
        )
        default[fmt] = opts
    return default


def _dump_pipeline_opts_with_kind(opts: PipelineOptions) -> dict:
    if hasattr(opts, "generate_picture_images"):
        opts = safe_copy(opts, update={"generate_picture_images": True})
    as_dict = dict()
    for field, value in opts:
        value_as_dict = value
        if isinstance(value, PydanticBaseModel):
            value_as_dict = dict()
            if hasattr(value, "kind"):
                value_as_dict = {"kind": value.kind}
            value_as_dict.update(value.model_dump(mode="python"))
        as_dict[field] = value_as_dict
    return as_dict


class BatchConcurrencySettings(DoclingBatchConcurrencySettings):
    # process up to 16 pages in || on GPU
    page_batch_size: int = 16
    # call convert_all with at most page_batch_size * page_batch_size
    max_page_batches: int = 2


class InferenceSettings(DoclingInferenceSettings):
    document_timeout: float | None = None


class DoclingSettings(BaseModel):
    perf: BatchConcurrencySettings = Field(default_factory=BatchConcurrencySettings)
    debug: DebugSettings = Field(default_factory=DebugSettings)
    inference: InferenceSettings = Field(default_factory=InferenceSettings)


class DoclingPipelineConfig(BasePipelineConfig):
    pipeline: ClassVar[PipelineType] = Field(frozen=True, default=PipelineType.DOCLING)

    format_options: dict[InputFormat, DoclingFormatOption] = Field(
        default_factory=default_format_opts
    )

    settings: DoclingSettings = Field(default_factory=DoclingSettings)
    result_buffer: ResultBufferConfig = Field(default_factory=ResultBufferConfig)

    @classmethod
    def supported_exts(cls) -> set[SupportedExt]:
        unsupported = {
            InputFormat.AUDIO,
            InputFormat.METS_GBS,
            InputFormat.VIDEO,
            InputFormat.VTT,
            InputFormat.BOXNOTE,  # maps to octet-stream
            InputFormat.DCLX,  # maps to octet-stream
            InputFormat.EBCDIC,  # maps to octet-stream
        }
        supported = set()
        for f in InputFormat:
            if f in unsupported:
                continue
            for ext in FormatToExtensions[f]:
                supported.add(SupportedExt(f".{ext.lower()}"))
        return supported

    def with_setting(self, settings: DoclingSettings) -> "DoclingPipelineConfig":
        update = {"settings": settings}
        return safe_copy(self, update=update)

    def to_device(self) -> Self:
        device = self.device.to_docling()
        new_format_opts = dict()
        for fmt, fmt_opts in self.format_options.items():
            pipeline_opts = fmt_opts.pipeline_options
            if pipeline_opts is None:
                pipeline_opts = {"generate_picture_images": True}
            accelerator_opts = pipeline_opts.get("accelerator_options", dict())
            accelerator_opts["device"] = device
            pipeline_opts["accelerator_options"] = accelerator_opts
            update = {"pipeline_options": pipeline_opts}
            new_format_opts[fmt] = safe_copy(fmt_opts, update=update)

        return DoclingPipelineConfig(
            device=self.device,
            format_options=new_format_opts,
            settings=self.settings,
            result_buffer=self.result_buffer,
        )
