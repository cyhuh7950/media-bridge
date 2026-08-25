"""Product-neutral router adapters for the Media Bridge Gateway API."""

from media_bridge_adapters.contracts import (
    AdapterConfigRequest,
    AdapterManifest,
    AdapterProbeResult,
    CompatibilityResult,
    PreUpstreamRequest,
    PreUpstreamResult,
    RenderedConfig,
)
from media_bridge_adapters.service import PreUpstreamService

__all__ = [
    "AdapterConfigRequest",
    "AdapterManifest",
    "AdapterProbeResult",
    "CompatibilityResult",
    "PreUpstreamRequest",
    "PreUpstreamResult",
    "PreUpstreamService",
    "RenderedConfig",
]
