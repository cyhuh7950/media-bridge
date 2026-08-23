"""Public input contracts shared by MCP tools and router adapters."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictModel(BaseModel):
    """Base model that rejects unreviewed input fields."""

    model_config = ConfigDict(extra="forbid")


class Base64Source(StrictModel):
    kind: Literal["base64"] = "base64"
    data: Annotated[str, StringConstraints(max_length=2_796_204)]


class AssetSource(StrictModel):
    kind: Literal["asset_id"] = "asset_id"
    asset_id: Annotated[
        str,
        StringConstraints(pattern=r"^mb_[A-Za-z0-9_-]{22,64}$"),
    ]


class UrlSource(StrictModel):
    kind: Literal["url"] = "url"
    url: Annotated[str, StringConstraints(max_length=2_048, pattern=r"^https://")]


class LocalPathSource(StrictModel):
    kind: Literal["local_path"] = "local_path"
    path: Annotated[str, StringConstraints(max_length=4_096)]


MediaSource = Annotated[
    Base64Source | AssetSource | UrlSource | LocalPathSource,
    Field(discriminator="kind"),
]


class TextPart(StrictModel):
    type: Literal["text"] = "text"
    text: Annotated[str, StringConstraints(max_length=200_000)]


class MediaPart(StrictModel):
    type: Literal["media"] = "media"
    media_type: Literal["image", "pdf"]
    source: MediaSource
    filename: Annotated[str, StringConstraints(max_length=255)] | None = None
    declared_mime: Annotated[str, StringConstraints(max_length=100)] | None = None


ContentPart = Annotated[TextPart | MediaPart, Field(discriminator="type")]


class TargetModel(StrictModel):
    registry_id: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9./:_-]{0,127}$"),
    ]


class PrepareForModelRequest(StrictModel):
    content: Annotated[list[ContentPart], Field(min_length=1, max_length=32)]
    target: TargetModel
    conversion_profile: Literal["generic", "error_screenshot", "document"] = "generic"


class SafeError(StrictModel):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    message: Annotated[str, StringConstraints(max_length=200)]


class PrepareForModelResult(StrictModel):
    action: Literal["passthrough", "converted", "blocked"]
    target_model: str
    contains_media: bool
    contains_image: bool
    contains_pdf: bool
    target_supports_vision: bool | None
    sanitized_text: Annotated[str, StringConstraints(max_length=200_000)] | None
    original_image_removed: bool
    error: SafeError | None


class ExtractImageContextRequest(StrictModel):
    content: Annotated[list[ContentPart], Field(min_length=1, max_length=32)]
    conversion_profile: Literal["generic", "error_screenshot", "document"] = "generic"


class ExtractImageContextResult(StrictModel):
    status: Literal["converted", "blocked"]
    media_type: Literal["generic", "error_screenshot", "document"]
    media_modalities: list[Literal["image", "pdf"]]
    ocr_text: Annotated[str, StringConstraints(max_length=200_000)] | None
    visual_description: Annotated[str, StringConstraints(max_length=200_000)] | None
    structured_context: Annotated[str, StringConstraints(max_length=200_000)] | None
    original_image_removed: bool
    error: SafeError | None


class AnalyzeErrorImageRequest(ExtractImageContextRequest):
    user_request: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
    analysis_backend: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$"),
    ] = "solar"


class AnalyzeErrorImageResult(StrictModel):
    status: Literal["analyzed", "blocked"]
    analysis_backend: str
    analysis: Annotated[str, StringConstraints(max_length=200_000)] | None
    structured_context: Annotated[str, StringConstraints(max_length=200_000)] | None
    original_image_removed: bool
    error: SafeError | None
