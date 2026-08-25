from __future__ import annotations

from pathlib import Path

from media_bridge_adapters.contracts import AdapterConfigRequest
from media_bridge_adapters.opencodex.config import render_config


def test_rendered_config_and_repr_do_not_contain_runtime_secret_values(tmp_path: Path) -> None:
    raw_credential = "mbc_private_runtime_credential"
    raw_hmac = "private-runtime-hmac-material"
    request = AdapterConfigRequest(
        adapter_id="opencodex",
        external_version="2.28.0",
        external_base_commit="5840591322117f3ee9568b35b135a6d4339f7711",
        extension_commit="fbd539bc1a68a4a9ce85823096daa537a67ec742",
        endpoint="https://bridge.example/adapter/v1/pre-upstream",
        credential_env="MEDIA_BRIDGE_ADAPTER_CREDENTIAL",
        decision_hmac_env="MEDIA_BRIDGE_ADAPTER_DECISION_HMAC",
        timeout_ms=15_000,
        max_response_bytes=524_288,
        output_path=tmp_path / "fragment.json",
    )

    rendered = render_config(request)
    combined = f"{request!r}\n{rendered!r}\n{rendered.content}"
    assert raw_credential not in combined
    assert raw_hmac not in combined
    assert "MEDIA_BRIDGE_ADAPTER_CREDENTIAL" in rendered.content
    assert "MEDIA_BRIDGE_ADAPTER_DECISION_HMAC" in rendered.content
