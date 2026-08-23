from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfWriter

from media_bridge.pdf_pipeline import PdfRenderingError, PdfiumPageRenderer


def _pdf(*, pages: int = 1, width: float = 72, height: float = 72) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width, height=height)
    writer.write(output)
    return output.getvalue()


def test_pdfium_renderer_returns_png_for_every_page() -> None:
    renderer = PdfiumPageRenderer(scale=2.0)

    rendered = renderer.render(_pdf(pages=2))

    assert [page.page_number for page in rendered] == [1, 2]
    assert all(page.mime_type == "image/png" for page in rendered)
    assert all(page.filename.endswith(".png") for page in rendered)
    for page in rendered:
        assert page.data.startswith(b"\x89PNG\r\n\x1a\n")
        with Image.open(BytesIO(page.data)) as image:
            assert image.size == (144, 144)


def test_pdfium_renderer_blocks_before_allocating_over_pixel_budget() -> None:
    renderer = PdfiumPageRenderer(scale=2.0, max_total_pixels=50_000)

    with pytest.raises(PdfRenderingError, match="pixel budget"):
        renderer.render(_pdf(pages=2, width=100, height=100))


def test_pdfium_renderer_rejects_zero_page_pdf() -> None:
    with pytest.raises(PdfRenderingError, match="page count"):
        PdfiumPageRenderer().render(_pdf(pages=0))
