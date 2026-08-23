"""Structural media detection for normalized request content."""

from dataclasses import dataclass

from media_bridge.contracts import ContentPart, MediaPart


@dataclass(frozen=True, slots=True)
class MediaDetection:
    media_count: int
    modalities: frozenset[str]

    @property
    def contains_image(self) -> bool:
        return "image" in self.modalities

    @property
    def contains_pdf(self) -> bool:
        return "pdf" in self.modalities


def detect_media(content: list[ContentPart]) -> MediaDetection:
    media_parts = [part for part in content if isinstance(part, MediaPart)]
    return MediaDetection(
        media_count=len(media_parts),
        modalities=frozenset(part.media_type for part in media_parts),
    )
