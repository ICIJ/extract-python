import importlib
from functools import cache
from typing import Annotated, Any, ClassVar, TypeVar, get_type_hints

from docling.datamodel.backend_options import BackendOptions, BaseBackendOptions
from docling.datamodel.base_models import (
    BaseFormatOption,
    FormatToExtensions,
    InputFormat,
)
from docling.datamodel.pipeline_options import (
    BaseLayoutOptions,
    BaseTableStructureOptions,
    EasyOcrOptions,
    LayoutOptions,
    OcrOptions,
    PictureDescriptionBaseOptions,
    PictureDescriptionVlmEngineOptions,
    PipelineOptions,
    TableStructureOptions,
    ThreadedPdfPipelineOptions,
)
from icij_common.pydantic_utils import (
    merge_configs,
    tagged_union,
    to_lower_snake_case,
)
from pydantic import (
    ConfigDict,
    Discriminator,
    Field,
    TypeAdapter,
    WrapSerializer,
)
from pydantic_core.core_schema import SerializerFunctionWrapHandler

from .configs import BasePipelineConfig, PipelineType
from .objects import BaseModel, SupportedExt
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
    generate_picture_images = getattr(v, "generate_picture_images", None)
    if generate_picture_images is False:
        msg = "generate_picture_images should be set to True"
        raise ValueError(msg)
    return v


T = TypeVar("T")


def _find_subcls(cls: type[T], name: str) -> type[T]:
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
        Discriminator(lambda x: x["kind"]),
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
    pipeline_options: dict[str, Any] | None | PipelineOptions, pipeline_cls: type
) -> PipelineOptions:
    option_cls = _find_init_arg_type(pipeline_cls, "pipeline_options")
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


@cache
def _default_format_opts() -> dict[InputFormat, DoclingFormatOption]:
    pipeline_opts = ThreadedPdfPipelineOptions(
        ocr_options=EasyOcrOptions(), generate_picture_images=True
    ).model_dump(polymorphic_serialization=True)
    pipeline_opts["picture_description_options"]["kind"] = (
        PictureDescriptionVlmEngineOptions.kind
    )
    pipeline_opts["ocr_options"]["kind"] = EasyOcrOptions.kind
    pipeline_opts["layout_options"]["kind"] = LayoutOptions.kind
    pipeline_opts["table_structure_options"]["kind"] = TableStructureOptions.kind
    return {
        InputFormat.PDF: DoclingFormatOption(
            pipeline_cls="StandardPdfPipeline",
            backend="DoclingParseDocumentBackend",
            pipeline_options=pipeline_opts,
        ),
    }


class DoclingPipelineConfig(BasePipelineConfig):
    pipeline: ClassVar[PipelineType] = Field(frozen=True, default=PipelineType.DOCLING)

    format_options: dict[InputFormat, DoclingFormatOption] = Field(
        default_factory=_default_format_opts
    )

    @classmethod
    @cache
    def supported_exts(cls) -> set[SupportedExt]:
        unsupported = {InputFormat.AUDIO, InputFormat.METS_GBS, InputFormat.VTT}
        supported = set()
        for f in InputFormat:
            if f in unsupported:
                continue
            for ext in FormatToExtensions[f]:
                supported.add(SupportedExt(f".{ext.lower()}"))
        return supported
