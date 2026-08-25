from __future__ import annotations

import json
from base64 import b64encode
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from media_bridge_adapters.contracts import AdapterConfigRequest
from media_bridge_adapters.omniroute.config import bundled_plugin_source
from media_bridge_adapters.omniroute.config import render_config as render_omniroute_config
from media_bridge_adapters.opencodex.config import render_config as render_opencodex_config
from media_bridge_adapters.validation import write_rendered_config

OPEN_CODEX_EXTENSION = "fbd539bc1a68a4a9ce85823096daa537a67ec742"
OPEN_CODEX_BASE = "5840591322117f3ee9568b35b135a6d4339f7711"
OMNIROUTE_EXTENSION = "eaa5ba08579f93db2d3e5b0046792ce8f70fb208"
OMNIROUTE_BASE = "f95b03d70929a6a850d4b986a7bbad6740dd02e0"


def request(
    tmp_path: Path,
    *,
    adapter_id: str = "opencodex",
    external_version: str = "2.28.0",
    external_base_commit: str = OPEN_CODEX_BASE,
    extension_commit: str = OPEN_CODEX_EXTENSION,
    endpoint: str = "http://127.0.0.1:8765/adapter/v1/pre-upstream",
) -> AdapterConfigRequest:
    return AdapterConfigRequest(
        adapter_id=adapter_id,
        external_version=external_version,
        external_base_commit=external_base_commit,
        extension_commit=extension_commit,
        endpoint=endpoint,
        credential_env="MEDIA_BRIDGE_ADAPTER_CREDENTIAL",
        decision_hmac_env="MEDIA_BRIDGE_ADAPTER_DECISION_HMAC",
        timeout_ms=15_000,
        max_response_bytes=524_288,
        output_path=tmp_path / f"{adapter_id}.json",
    )


def test_opencodex_config_is_an_exact_secret_reference_only_fragment(tmp_path: Path) -> None:
    rendered = render_opencodex_config(request(tmp_path))
    payload = json.loads(rendered.content)
    assert payload == {
        "preUpstreamPolicy": {
            "enabled": True,
            "endpoint": "http://127.0.0.1:8765/adapter/v1/pre-upstream",
            "credentialEnv": "MEDIA_BRIDGE_ADAPTER_CREDENTIAL",
            "decisionHmacEnv": "MEDIA_BRIDGE_ADAPTER_DECISION_HMAC",
            "timeoutMs": 15_000,
            "maxResponseBytes": 524_288,
        }
    }
    assert rendered.output_path == tmp_path / "opencodex.json"


def test_omniroute_config_declares_the_critical_hook_and_secret_refs(tmp_path: Path) -> None:
    rendered = render_omniroute_config(
        request(
            tmp_path,
            adapter_id="omniroute",
            external_version="3.8.50",
            external_base_commit=OMNIROUTE_BASE,
            extension_commit=OMNIROUTE_EXTENSION,
        )
    )
    payload = json.loads(rendered.content)
    source = bundled_plugin_source()
    integrity = f"sha256-{b64encode(sha256(source).digest()).decode()}"
    assert payload["status"] == "preview_only"
    assert payload["plugin_asset"] == "media_bridge_adapters/omniroute/plugin/index.mjs"
    assert payload["plugin"]["hooks"] == {"onRequest": True, "securityCritical": True}
    assert payload["plugin"]["integrity"] == integrity
    assert payload["plugin"]["requires"]["omniroute"] == "=3.8.50"
    assert payload["plugin"]["requires"]["secretEnv"] == [
        "MEDIA_BRIDGE_ADAPTER_ENDPOINT",
        "MEDIA_BRIDGE_ADAPTER_CREDENTIAL",
        "MEDIA_BRIDGE_ADAPTER_DECISION_HMAC",
    ]
    assert payload["adapter"]["credentialEnv"] == "MEDIA_BRIDGE_ADAPTER_CREDENTIAL"
    assert payload["adapter"]["decisionHmacEnv"] == "MEDIA_BRIDGE_ADAPTER_DECISION_HMAC"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://bridge.internal/adapter/v1/pre-upstream",
        "https://bridge.example/other",
        "https://user:pass@bridge.example/adapter/v1/pre-upstream",
        "https://bridge.example/adapter/v1/pre-upstream?secret=value",
    ],
)
def test_endpoint_boundary_rejects_plain_remote_http_and_noncanonical_urls(
    tmp_path: Path, endpoint: str
) -> None:
    with pytest.raises(ValidationError):
        request(tmp_path, endpoint=endpoint)


def test_raw_secret_values_are_rejected_as_environment_references(tmp_path: Path) -> None:
    base = request(tmp_path).model_dump()
    base["credential_env"] = "mbc_raw-secret-value"
    with pytest.raises(ValidationError):
        AdapterConfigRequest.model_validate(base)

    base = request(tmp_path).model_dump()
    base["decision_hmac_env"] = "actual-secret-material"
    with pytest.raises(ValidationError):
        AdapterConfigRequest.model_validate(base)


def test_writer_requires_explicit_nonexisting_output_and_never_overwrites(tmp_path: Path) -> None:
    rendered = render_opencodex_config(request(tmp_path))
    written = write_rendered_config(rendered)
    assert written == tmp_path / "opencodex.json"
    assert written.read_text(encoding="utf-8") == rendered.content

    with pytest.raises(FileExistsError):
        write_rendered_config(rendered)


def test_incompatible_external_build_is_blocked_before_render(tmp_path: Path) -> None:
    incompatible = request(tmp_path).model_copy(update={"external_version": "2.28.1"})
    with pytest.raises(ValueError, match="unsupported_external_build"):
        render_opencodex_config(incompatible)


def test_omniroute_rejects_env_names_the_bundled_plugin_does_not_read(tmp_path: Path) -> None:
    incompatible = request(
        tmp_path,
        adapter_id="omniroute",
        external_version="3.8.50",
        external_base_commit=OMNIROUTE_BASE,
        extension_commit=OMNIROUTE_EXTENSION,
    ).model_copy(update={"credential_env": "CUSTOM_ADAPTER_CREDENTIAL"})

    with pytest.raises(ValueError, match="adapter_secret_env_mismatch"):
        render_omniroute_config(incompatible)
