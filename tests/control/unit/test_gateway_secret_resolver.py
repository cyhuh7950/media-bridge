from pathlib import Path

import pytest
from media_bridge_control.secrets import GatewaySecretResolver, SecretResolutionError

from media_bridge_control.schemas import SecretReference


def test_gateway_secret_resolver_reads_exact_env_and_bounded_secret_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAY_TEST_KEY", "env-value")
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    (secret_root / "gateway-key").write_text("file-value\n", encoding="utf-8")
    resolver = GatewaySecretResolver(docker_secret_root=secret_root)

    assert resolver.resolve(SecretReference(kind="env", identifier="GATEWAY_TEST_KEY")) == (
        "env-value"
    )
    assert resolver.resolve(
        SecretReference(kind="docker_secret", identifier="gateway-key")
    ) == "file-value"


@pytest.mark.parametrize("failure", ["missing", "empty", "symlink", "oversized"])
def test_gateway_secret_resolver_fails_closed_for_unsafe_files(
    tmp_path: Path,
    failure: str,
) -> None:
    root = tmp_path / "secrets"
    root.mkdir()
    target = root / "gateway-key"
    if failure == "empty":
        target.write_bytes(b"")
    elif failure == "symlink":
        outside = tmp_path / "outside"
        outside.write_text("value", encoding="utf-8")
        target.symlink_to(outside)
    elif failure == "oversized":
        target.write_bytes(b"x" * 4097)
    resolver = GatewaySecretResolver(docker_secret_root=root, max_bytes=4096)

    with pytest.raises(SecretResolutionError) as captured:
        resolver.resolve(SecretReference(kind="docker_secret", identifier="gateway-key"))

    assert str(captured.value) == "secret_unavailable"


def test_external_secret_reference_requires_an_injected_resolver() -> None:
    resolver = GatewaySecretResolver()

    with pytest.raises(SecretResolutionError) as captured:
        resolver.resolve(
            SecretReference(
                kind="external",
                identifier="vault://media-bridge/gateway",
            )
        )

    assert str(captured.value) == "secret_resolver_unavailable"
