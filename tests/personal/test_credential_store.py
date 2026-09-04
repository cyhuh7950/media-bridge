from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from media_bridge_personal.credential_store import CredentialStore, CredentialStoreError


def test_credential_store_writes_private_atomic_file_without_echoing_secret(tmp_path: Path) -> None:
    target = tmp_path / "secrets" / "providers.json"
    store = CredentialStore(target)

    store.set("text-llm", "secret-value")

    assert store.get("text-llm") == "secret-value"
    assert store.status() == {"text-llm": True}
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "schemaVersion": 1,
        "credentials": {"text-llm": "secret-value"},
    }
    assert not list(target.parent.glob("*.tmp"))
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


def test_credential_store_rejects_unsafe_reference_and_never_returns_it_in_status(
    tmp_path: Path,
) -> None:
    store = CredentialStore(tmp_path / "providers.json")

    with pytest.raises(CredentialStoreError):
        store.set("../escape", "secret")
    store.set("media-processor", "another-secret")

    assert store.status() == {"media-processor": True}
    assert "another-secret" not in repr(store.status())


def test_credential_store_resolves_local_value_then_environment_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = CredentialStore(tmp_path / "providers.json")
    monkeypatch.setenv("LEGACY_PROVIDER_KEY", "environment-secret")

    assert store.resolve("text-llm", "LEGACY_PROVIDER_KEY") == "environment-secret"
    store.set("text-llm", "stored-secret")
    assert store.resolve("text-llm", "LEGACY_PROVIDER_KEY") == "stored-secret"

