"""Preview-only OmniRoute security-critical plugin configuration."""

from __future__ import annotations

import json
from base64 import b64encode
from hashlib import sha256
from importlib.resources import files

from media_bridge_adapters.compatibility import inspect_compatibility
from media_bridge_adapters.contracts import AdapterConfigRequest, RenderedConfig

_PLUGIN_ASSET = "media_bridge_adapters/omniroute/plugin/index.mjs"
_CREDENTIAL_ENV = "MEDIA_BRIDGE_ADAPTER_CREDENTIAL"
_DECISION_HMAC_ENV = "MEDIA_BRIDGE_ADAPTER_DECISION_HMAC"


def bundled_plugin_source() -> bytes:
    return files("media_bridge_adapters.omniroute").joinpath("plugin/index.mjs").read_bytes()


def render_config(request: AdapterConfigRequest) -> RenderedConfig:
    if request.adapter_id != "omniroute":
        raise ValueError("adapter_id_mismatch")
    if (
        request.credential_env != _CREDENTIAL_ENV
        or request.decision_hmac_env != _DECISION_HMAC_ENV
    ):
        raise ValueError("adapter_secret_env_mismatch")
    result = inspect_compatibility(
        adapter_id=request.adapter_id,
        external_version=request.external_version,
        external_base_commit=request.external_base_commit,
        extension_commit=request.extension_commit,
    )
    if not result.compatible:
        raise ValueError(result.reason)
    source = bundled_plugin_source()
    integrity = f"sha256-{b64encode(sha256(source).digest()).decode()}"
    payload = {
        "status": "preview_only",
        "plugin_asset": _PLUGIN_ASSET,
        "adapter": {
            "contractVersion": "media-bridge-pre-upstream/v1",
            "credentialEnv": request.credential_env,
            "decisionHmacEnv": request.decision_hmac_env,
            "endpoint": request.endpoint,
            "maxResponseBytes": request.max_response_bytes,
            "timeoutMs": request.timeout_ms,
        },
        "plugin": {
            "description": "Media Bridge resolved-target pre-upstream gate",
            "hooks": {"onRequest": True, "securityCritical": True},
            "integrity": integrity,
            "main": "index.mjs",
            "name": "media-bridge-pre-upstream",
            "requires": {
                "omniroute": f"={request.external_version}",
                "permissions": ["network", "env"],
                "secretEnv": [
                    "MEDIA_BRIDGE_ADAPTER_ENDPOINT",
                    "MEDIA_BRIDGE_ADAPTER_CREDENTIAL",
                    "MEDIA_BRIDGE_ADAPTER_DECISION_HMAC",
                ],
            },
            "version": "0.1.0",
        },
    }
    return RenderedConfig(
        adapter_id=request.adapter_id,
        external_version=request.external_version,
        content=json.dumps(payload, indent=2, sort_keys=True) + "\n",
        output_path=request.output_path,
    )
