from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfWriter

from media_bridge.acquisition import (
    AcquisitionError,
    AcquisitionPolicy,
    FetchedUrl,
    MediaAcquirer,
    MediaLimits,
)
from media_bridge.assets import AssetAccessError, AssetStore
from media_bridge.contracts import Base64Source, LocalPathSource, MediaPart, UrlSource


def _png(width: int = 2, height: int = 2) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), color="red").save(output, format="PNG")
    return output.getvalue()


def _pdf(page_count: int) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()


def _base64_part(data: bytes, *, media_type: str = "image", mime: str | None = None) -> MediaPart:
    return MediaPart.model_validate(
        {
            "type": "media",
            "media_type": media_type,
            "source": {"kind": "base64", "data": base64.b64encode(data).decode("ascii")},
            "declared_mime": mime,
        }
    )


@pytest.mark.asyncio
async def test_base64_is_strict_and_bounded(tmp_path: Path) -> None:
    acquirer = MediaAcquirer(
        asset_store=AssetStore(tmp_path / "assets", max_bytes=16),
        limits=MediaLimits(max_bytes=16),
    )
    invalid = MediaPart(
        media_type="image",
        source=Base64Source(data="this-is-not+valid/base64==="),
    )
    oversized = MediaPart(
        media_type="image",
        source=Base64Source(data=base64.b64encode(b"x" * 17).decode("ascii")),
    )

    with pytest.raises(AcquisitionError, match="base64"):
        await acquirer.acquire(invalid, tenant_id="tenant-a")
    with pytest.raises(AcquisitionError, match="limit"):
        await acquirer.acquire(oversized, tenant_id="tenant-a")


def test_contract_rejects_base64_larger_than_public_limit() -> None:
    with pytest.raises(ValidationError):
        Base64Source(data="A" * 2_796_205)


@pytest.mark.asyncio
async def test_asset_is_tenant_scoped_consumed_once_and_deleted(tmp_path: Path) -> None:
    store = AssetStore(tmp_path / "assets")
    asset_id = store.put(
        tenant_id="tenant-a",
        data=_png(),
        filename="capture.png",
        declared_mime="image/png",
    )
    part = MediaPart(
        media_type="image",
        source={"kind": "asset_id", "asset_id": asset_id},
    )
    acquirer = MediaAcquirer(asset_store=store)

    with pytest.raises(AssetAccessError):
        await acquirer.acquire(part, tenant_id="tenant-b")

    acquired = await acquirer.acquire(part, tenant_id="tenant-a")
    assert acquired.mime_type == "image/png"
    assert list((tmp_path / "assets").glob("*.bin")) == []

    with pytest.raises(AssetAccessError):
        await acquirer.acquire(part, tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_local_paths_are_disabled_by_default(tmp_path: Path) -> None:
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(_png())
    part = MediaPart(media_type="image", source=LocalPathSource(path=str(image_path)))
    acquirer = MediaAcquirer(asset_store=AssetStore(tmp_path / "assets"))

    with pytest.raises(AcquisitionError, match="disabled"):
        await acquirer.acquire(part, tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_local_path_rejects_traversal_and_symlinks(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png())
    link = allowed / "linked.png"
    link.symlink_to(outside)
    acquirer = MediaAcquirer(
        asset_store=AssetStore(tmp_path / "assets"),
        policy=AcquisitionPolicy(allow_local=True, local_roots=(allowed,)),
    )

    for candidate in (allowed / ".." / "outside.png", link):
        part = MediaPart(media_type="image", source=LocalPathSource(path=str(candidate)))
        with pytest.raises(AcquisitionError):
            await acquirer.acquire(part, tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_url_is_default_deny_and_private_resolution_is_blocked(tmp_path: Path) -> None:
    part = MediaPart(
        media_type="image",
        source=UrlSource(url="https://media.example/capture.png"),
    )
    default_acquirer = MediaAcquirer(asset_store=AssetStore(tmp_path / "assets-default"))
    with pytest.raises(AcquisitionError, match="disabled"):
        await default_acquirer.acquire(part, tenant_id="tenant-a")

    fetch_called = False

    async def forbidden_fetch(_url: str, _ips: tuple[str, ...], _limit: int) -> FetchedUrl:
        nonlocal fetch_called
        fetch_called = True
        return FetchedUrl(body=_png(), content_type="image/png")

    private_acquirer = MediaAcquirer(
        asset_store=AssetStore(tmp_path / "assets-private"),
        policy=AcquisitionPolicy(
            allow_urls=True,
            url_hosts=frozenset({"media.example"}),
            resolve_host=lambda _host: ("127.0.0.1",),
            fetch_url=forbidden_fetch,
        ),
    )
    with pytest.raises(AcquisitionError, match="public"):
        await private_acquirer.acquire(part, tenant_id="tenant-a")
    assert fetch_called is False


@pytest.mark.asyncio
async def test_url_requires_pinning_fetcher_and_rejects_redirects(tmp_path: Path) -> None:
    part = MediaPart(
        media_type="image",
        source=UrlSource(url="https://media.example/capture.png"),
    )
    no_fetcher = MediaAcquirer(
        asset_store=AssetStore(tmp_path / "assets-none"),
        policy=AcquisitionPolicy(
            allow_urls=True,
            url_hosts=frozenset({"media.example"}),
            resolve_host=lambda _host: ("93.184.216.34",),
        ),
    )
    with pytest.raises(AcquisitionError, match="pinning fetcher"):
        await no_fetcher.acquire(part, tenant_id="tenant-a")

    async def redirecting_fetch(_url: str, _ips: tuple[str, ...], _limit: int) -> FetchedUrl:
        return FetchedUrl(
            body=b"",
            content_type="text/plain",
            redirect_location="https://internal.example/secret",
        )

    redirect_acquirer = MediaAcquirer(
        asset_store=AssetStore(tmp_path / "assets-redirect"),
        policy=AcquisitionPolicy(
            allow_urls=True,
            url_hosts=frozenset({"media.example"}),
            resolve_host=lambda _host: ("93.184.216.34",),
            fetch_url=redirecting_fetch,
        ),
    )
    with pytest.raises(AcquisitionError, match="redirect"):
        await redirect_acquirer.acquire(part, tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_magic_mime_pixel_and_pdf_page_limits(tmp_path: Path) -> None:
    acquirer = MediaAcquirer(
        asset_store=AssetStore(tmp_path / "assets"),
        limits=MediaLimits(max_pixels=100, max_pdf_pages=2),
    )

    with pytest.raises(AcquisitionError, match="MIME"):
        await acquirer.acquire(
            _base64_part(_png(), mime="image/jpeg"),
            tenant_id="tenant-a",
        )
    with pytest.raises(AcquisitionError, match="pixel"):
        await acquirer.acquire(_base64_part(_png(11, 11)), tenant_id="tenant-a")
    with pytest.raises(AcquisitionError, match="page"):
        await acquirer.acquire(
            _base64_part(_pdf(3), media_type="pdf", mime="application/pdf"),
            tenant_id="tenant-a",
        )
