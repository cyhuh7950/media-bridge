"""Preview-only OpenCodex pre-upstream policy configuration."""

from __future__ import annotations

import json

from media_bridge_adapters.compatibility import inspect_compatibility
from media_bridge_adapters.contracts import AdapterConfigRequest, RenderedConfig


def render_config(request: AdapterConfigRequest) -> RenderedConfig:
    if request.adapter_id != "opencodex":
        raise ValueError("adapter_id_mismatch")
    result = inspect_compatibility(
        adapter_id=request.adapter_id,
        external_version=request.external_version,
        external_base_commit=request.external_base_commit,
        extension_commit=request.extension_commit,
    )
    if not result.compatible:
        raise ValueError(result.reason)
    payload = {
        "preUpstreamPolicy": {
            "enabled": True,
            "endpoint": request.endpoint,
            "credentialEnv": request.credential_env,
            "decisionHmacEnv": request.decision_hmac_env,
            "timeoutMs": request.timeout_ms,
            "maxResponseBytes": request.max_response_bytes,
        }
    }
    return RenderedConfig(
        adapter_id=request.adapter_id,
        external_version=request.external_version,
        content=json.dumps(payload, indent=2, sort_keys=True) + "\n",
        output_path=request.output_path,
    )
