"""Validation and explicit no-overwrite writes for adapter configuration."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from media_bridge_adapters.contracts import RenderedConfig

_ADAPTER_PATH = "/adapter/v1/pre-upstream"


def validate_adapter_endpoint(value: str) -> str:
    if value != value.strip():
        raise ValueError("Adapter endpoint must be canonical")
    parsed = urlsplit(value)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != _ADAPTER_PATH
        or not parsed.hostname
    ):
        raise ValueError("Adapter endpoint is invalid")
    if parsed.scheme == "https":
        return value
    if parsed.scheme != "http":
        raise ValueError("Adapter endpoint must use HTTPS or loopback HTTP")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.lower() != "localhost":
            raise ValueError("Plain HTTP adapter endpoint must use loopback") from None
    else:
        if not address.is_loopback:
            raise ValueError("Plain HTTP adapter endpoint must use loopback")
    return value


def write_rendered_config(rendered: RenderedConfig) -> Path:
    path = rendered.output_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(rendered.content)
    return path
