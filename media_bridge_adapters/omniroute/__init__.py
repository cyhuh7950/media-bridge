"""OmniRoute security-critical plugin configuration."""

from media_bridge_adapters.omniroute.config import render_config
from media_bridge_adapters.omniroute.downstream import GuardedOmniRouteAdapter

__all__ = ["GuardedOmniRouteAdapter", "render_config"]
