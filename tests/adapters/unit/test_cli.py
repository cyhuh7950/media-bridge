from __future__ import annotations

import json
from pathlib import Path

from media_bridge_adapters.cli import main


def test_inspect_reports_exact_compatibility_without_runtime_secrets(capsys) -> None:
    result = main(
        [
            "inspect",
            "--adapter",
            "opencodex",
            "--external-version",
            "2.28.0",
            "--external-base-commit",
            "5840591322117f3ee9568b35b135a6d4339f7711",
            "--extension-commit",
            "fbd539bc1a68a4a9ce85823096daa537a67ec742",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["compatible"] is True
    assert output["adapter_id"] == "opencodex"


def test_render_config_requires_explicit_output_and_writes_once(
    tmp_path: Path, capsys
) -> None:
    output_path = tmp_path / "opencodex-fragment.json"
    arguments = [
        "render-config",
        "--adapter",
        "opencodex",
        "--external-version",
        "2.28.0",
        "--external-base-commit",
        "5840591322117f3ee9568b35b135a6d4339f7711",
        "--extension-commit",
        "fbd539bc1a68a4a9ce85823096daa537a67ec742",
        "--endpoint",
        "http://127.0.0.1:8765/adapter/v1/pre-upstream",
        "--credential-env",
        "MEDIA_BRIDGE_ADAPTER_CREDENTIAL",
        "--decision-hmac-env",
        "MEDIA_BRIDGE_ADAPTER_DECISION_HMAC",
        "--output",
        str(output_path),
    ]
    assert main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"adapter_id": "opencodex", "status": "written"}
    assert output_path.exists()

    assert main(arguments) == 2
    error = json.loads(capsys.readouterr().err)
    assert error == {"error": "output_exists"}


def test_parser_does_not_offer_raw_credential_or_secret_arguments(capsys) -> None:
    result = main(["render-config", "--credential", "mbc_private"])
    assert result == 2
    error = capsys.readouterr().err
    assert "mbc_private" not in error
