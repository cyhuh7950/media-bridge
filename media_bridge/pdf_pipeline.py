"""Bounded in-memory PDF page rasterization for image-only backends."""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from pypdf import PdfReader


class PdfRenderingError(RuntimeError):
    """Raised without exposing PDF content or provider details."""


@dataclass(frozen=True, slots=True)
class RenderedPdfPage:
    page_number: int
    data: bytes
    mime_type: str
    filename: str


class PdfPageRenderer(Protocol):
    def render(self, data: bytes) -> tuple[RenderedPdfPage, ...]: ...


class PdfiumPageRenderer:
    """Render every PDF page to a bounded PNG at 144 DPI by default."""

    def __init__(
        self,
        *,
        scale: float = 2.0,
        max_pages: int = 20,
        max_dimension: int = 16_384,
        max_page_pixels: int = 25_000_000,
        max_total_pixels: int = 50_000_000,
        max_page_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("PDF render scale must be positive and finite")
        if min(
            max_pages,
            max_dimension,
            max_page_pixels,
            max_total_pixels,
            max_page_bytes,
        ) <= 0:
            raise ValueError("PDF render limits must be positive")
        self._scale = scale
        self._max_pages = max_pages
        self._max_dimension = max_dimension
        self._max_page_pixels = max_page_pixels
        self._max_total_pixels = max_total_pixels
        self._max_page_bytes = max_page_bytes

    def render(self, data: bytes) -> tuple[RenderedPdfPage, ...]:
        if not data.startswith(b"%PDF-"):
            raise PdfRenderingError("PDF content is invalid")
        document = None
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise PdfRenderingError("encrypted PDF input is not permitted")
            validated_page_count = len(reader.pages)
            if validated_page_count < 1 or validated_page_count > self._max_pages:
                raise PdfRenderingError("PDF page count is outside the allowed range")
            document = pdfium.PdfDocument(data)
            page_count = len(document)
            if page_count != validated_page_count:
                raise PdfRenderingError("PDF page count validation mismatch")

            dimensions: list[tuple[int, int]] = []
            total_pixels = 0
            for index in range(page_count):
                page = document[index]
                try:
                    width_points, height_points = page.get_size()
                finally:
                    page.close()
                width = math.ceil(width_points * self._scale)
                height = math.ceil(height_points * self._scale)
                if width <= 0 or height <= 0:
                    raise PdfRenderingError("PDF page dimensions are invalid")
                if width > self._max_dimension or height > self._max_dimension:
                    raise PdfRenderingError("PDF page dimension limit exceeded")
                page_pixels = width * height
                if page_pixels > self._max_page_pixels:
                    raise PdfRenderingError("PDF page pixel budget exceeded")
                total_pixels += page_pixels
                if total_pixels > self._max_total_pixels:
                    raise PdfRenderingError("PDF total pixel budget exceeded")
                dimensions.append((width, height))

            rendered: list[RenderedPdfPage] = []
            for index, expected_size in enumerate(dimensions):
                page = document[index]
                bitmap = None
                try:
                    bitmap = page.render(scale=self._scale)
                    image = bitmap.to_pil()
                    try:
                        if image.size != expected_size:
                            raise PdfRenderingError("PDF renderer returned unexpected dimensions")
                        output = BytesIO()
                        image.save(output, format="PNG", optimize=True)
                    finally:
                        image.close()
                finally:
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
                encoded = output.getvalue()
                if not encoded or len(encoded) > self._max_page_bytes:
                    raise PdfRenderingError("rendered PDF page byte limit exceeded")
                rendered.append(
                    RenderedPdfPage(
                        page_number=index + 1,
                        data=encoded,
                        mime_type="image/png",
                        filename=f"page-{index + 1}.png",
                    )
                )
            return tuple(rendered)
        except PdfRenderingError:
            raise
        except Exception as error:
            raise PdfRenderingError("PDF rasterization failed") from error
        finally:
            if document is not None:
                document.close()
