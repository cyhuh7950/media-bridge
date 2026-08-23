"""Secure media acquisition and content validation."""

from __future__ import annotations

import base64
import binascii
import inspect
import ipaddress
import os
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from media_bridge.assets import AssetStore
from media_bridge.contracts import (
    AssetSource,
    Base64Source,
    LocalPathSource,
    MediaPart,
    UrlSource,
)


class AcquisitionError(RuntimeError):
    """Raised when media input crosses a denied or unverifiable boundary."""


@dataclass(frozen=True, slots=True)
class MediaLimits:
    max_bytes: int = 2 * 1024 * 1024
    max_pixels: int = 25_000_000
    max_dimension: int = 16_384
    max_pdf_pages: int = 20


@dataclass(frozen=True, slots=True)
class FetchedUrl:
    body: bytes
    content_type: str | None
    status_code: int = 200
    redirect_location: str | None = None


HostResolver = Callable[[str], tuple[str, ...] | Awaitable[tuple[str, ...]]]
PinnedUrlFetcher = Callable[
    [str, tuple[str, ...], int],
    FetchedUrl | Awaitable[FetchedUrl],
]


def _system_resolve(host: str) -> tuple[str, ...]:
    addresses = {
        str(address[4][0])
        for address in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    }
    return tuple(sorted(addresses))


@dataclass(frozen=True, slots=True)
class AcquisitionPolicy:
    allow_local: bool = False
    local_roots: tuple[Path, ...] = ()
    allow_urls: bool = False
    url_hosts: frozenset[str] = frozenset()
    resolve_host: HostResolver = _system_resolve
    fetch_url: PinnedUrlFetcher | None = None


@dataclass(frozen=True, slots=True)
class AcquiredMedia:
    data: bytes
    media_type: str
    mime_type: str
    filename: str | None
    forbidden_locators: tuple[str, ...]


class MediaAcquirer:
    """Resolve explicit media sources and validate their actual content."""

    def __init__(
        self,
        *,
        asset_store: AssetStore,
        policy: AcquisitionPolicy | None = None,
        limits: MediaLimits | None = None,
    ) -> None:
        self._asset_store = asset_store
        self._policy = policy or AcquisitionPolicy()
        self._limits = limits or MediaLimits()

    async def acquire(self, part: MediaPart, *, tenant_id: str) -> AcquiredMedia:
        source = part.source
        filename = part.filename
        declared_mime = part.declared_mime
        forbidden_locators: tuple[str, ...]

        if isinstance(source, Base64Source):
            try:
                data = base64.b64decode(source.data, validate=True)
            except (binascii.Error, ValueError) as error:
                raise AcquisitionError("invalid base64 media input") from error
            forbidden_locators = ()
        elif isinstance(source, AssetSource):
            consumed = self._asset_store.consume(asset_id=source.asset_id, tenant_id=tenant_id)
            data = consumed.data
            filename = filename or consumed.filename
            declared_mime = declared_mime or consumed.declared_mime
            forbidden_locators = (source.asset_id,)
        elif isinstance(source, LocalPathSource):
            data = self._read_local(source.path)
            filename = filename or Path(source.path).name
            forbidden_locators = (source.path,)
        elif isinstance(source, UrlSource):
            fetched = await self._read_url(source.url)
            data = fetched.body
            declared_mime = declared_mime or fetched.content_type
            filename = filename or Path(urlsplit(source.url).path).name or None
            forbidden_locators = (source.url,)
        else:  # pragma: no cover - the discriminated contract prevents this branch
            raise AcquisitionError("unsupported media source")

        if len(data) > self._limits.max_bytes:
            raise AcquisitionError("media exceeds the configured byte limit")
        detected_type, detected_mime = self._detect_content(data)
        if detected_type != part.media_type:
            raise AcquisitionError("declared media type does not match content")
        if declared_mime is not None:
            normalized_mime = declared_mime.partition(";")[0].strip().lower()
            if normalized_mime != detected_mime:
                raise AcquisitionError("declared MIME does not match content")

        if detected_type == "image":
            self._validate_image(data)
        else:
            self._validate_pdf(data)
        return AcquiredMedia(
            data=data,
            media_type=detected_type,
            mime_type=detected_mime,
            filename=filename,
            forbidden_locators=forbidden_locators,
        )

    def _read_local(self, source_path: str) -> bytes:
        if not self._policy.allow_local:
            raise AcquisitionError("local path media input is disabled")
        lexical_path = Path(os.path.abspath(source_path))
        if not lexical_path.is_absolute():
            raise AcquisitionError("local path must be absolute")

        matched_root: Path | None = None
        relative_path: Path | None = None
        for configured_root in self._policy.local_roots:
            root = configured_root.resolve(strict=True)
            if configured_root.is_symlink():
                raise AcquisitionError("configured local root cannot be a symlink")
            try:
                candidate_relative = lexical_path.relative_to(root)
            except ValueError:
                continue
            matched_root = root
            relative_path = candidate_relative
            break
        if matched_root is None or relative_path is None:
            raise AcquisitionError("local path is outside the configured roots")

        current = matched_root
        for component in relative_path.parts:
            current /= component
            if current.is_symlink():
                raise AcquisitionError("local path symlinks are not permitted")
        try:
            resolved_path = lexical_path.resolve(strict=True)
        except OSError as error:
            raise AcquisitionError("local media path is unavailable") from error
        if resolved_path != lexical_path or not resolved_path.is_file():
            raise AcquisitionError("local media path is not a regular direct file")
        if resolved_path.stat().st_size > self._limits.max_bytes:
            raise AcquisitionError("media exceeds the configured byte limit")
        return resolved_path.read_bytes()

    async def _read_url(self, url: str) -> FetchedUrl:
        if not self._policy.allow_urls:
            raise AcquisitionError("URL media input is disabled")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise AcquisitionError("URL must be a credential-free HTTPS URL")
        try:
            port = parsed.port
        except ValueError as error:
            raise AcquisitionError("URL port is invalid") from error
        if port not in (None, 443):
            raise AcquisitionError("URL port is not permitted")
        hostname = parsed.hostname.lower()
        if hostname not in {host.lower() for host in self._policy.url_hosts}:
            raise AcquisitionError("URL host is not allowlisted")

        resolved = self._policy.resolve_host(hostname)
        addresses = await resolved if inspect.isawaitable(resolved) else resolved
        if not addresses:
            raise AcquisitionError("URL host did not resolve")
        try:
            if any(not ipaddress.ip_address(address).is_global for address in addresses):
                raise AcquisitionError("URL host must resolve only to public addresses")
        except ValueError as error:
            raise AcquisitionError("URL host resolution returned an invalid address") from error
        if self._policy.fetch_url is None:
            raise AcquisitionError("URL input requires a DNS-pinning fetcher")

        result = self._policy.fetch_url(url, tuple(addresses), self._limits.max_bytes)
        fetched = await result if inspect.isawaitable(result) else result
        if fetched.redirect_location is not None:
            raise AcquisitionError("URL redirects are not permitted")
        if fetched.status_code != 200:
            raise AcquisitionError("URL fetch did not return a successful response")
        if len(fetched.body) > self._limits.max_bytes:
            raise AcquisitionError("media exceeds the configured byte limit")
        return fetched

    @staticmethod
    def _detect_content(data: bytes) -> tuple[str, str]:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image", "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image", "image/jpeg"
        if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image", "image/webp"
        if data.startswith(b"%PDF-"):
            return "pdf", "application/pdf"
        raise AcquisitionError("unsupported or unrecognized media content")

    def _validate_image(self, data: bytes) -> None:
        try:
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                if width > self._limits.max_dimension or height > self._limits.max_dimension:
                    raise AcquisitionError("image dimension limit exceeded")
                if width * height > self._limits.max_pixels:
                    raise AcquisitionError("image pixel limit exceeded")
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise AcquisitionError("image content is malformed") from error

    def _validate_pdf(self, data: bytes) -> None:
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise AcquisitionError("encrypted PDF input is not permitted")
            if len(reader.pages) > self._limits.max_pdf_pages:
                raise AcquisitionError("PDF page limit exceeded")
        except AcquisitionError:
            raise
        except Exception as error:
            raise AcquisitionError("PDF content is malformed") from error
