from __future__ import annotations

import inspect

import pytest

from media_bridge_adapters.compatibility import inspect_compatibility
from media_bridge_adapters.registry import AdapterRegistry, default_registry
from media_bridge_adapters.service import PreUpstreamService

OPEN_CODEX_EXTENSION = "fbd539bc1a68a4a9ce85823096daa537a67ec742"
OPEN_CODEX_BASE = "5840591322117f3ee9568b35b135a6d4339f7711"
OMNIROUTE_EXTENSION = "eaa5ba08579f93db2d3e5b0046792ce8f70fb208"
OMNIROUTE_BASE = "f95b03d70929a6a850d4b986a7bbad6740dd02e0"


def test_exact_supported_versions_and_extension_commits_are_required() -> None:
    compatible = inspect_compatibility(
        adapter_id="opencodex",
        external_version="2.28.0",
        external_base_commit=OPEN_CODEX_BASE,
        extension_commit=OPEN_CODEX_EXTENSION,
    )
    assert compatible.compatible is True
    assert compatible.reason is None

    for version, base, extension in (
        ("2.28.1", OPEN_CODEX_BASE, OPEN_CODEX_EXTENSION),
        ("2.28.0", "0" * 40, OPEN_CODEX_EXTENSION),
        ("2.28.0", OPEN_CODEX_BASE, "0" * 40),
    ):
        rejected = inspect_compatibility(
            adapter_id="opencodex",
            external_version=version,
            external_base_commit=base,
            extension_commit=extension,
        )
        assert rejected.compatible is False
        assert rejected.reason == "unsupported_external_build"


def test_unknown_adapter_is_fail_closed() -> None:
    result = inspect_compatibility(
        adapter_id="unknown-router",
        external_version="1.0.0",
        external_base_commit="0" * 40,
        extension_commit="1" * 40,
    )
    assert result.compatible is False
    assert result.reason == "unknown_adapter"


def test_registry_removal_is_local_and_does_not_import_core_or_gateway_internals() -> None:
    registry = default_registry()
    assert set(registry.adapter_ids()) == {"omniroute", "opencodex"}
    removed = registry.unregister("opencodex")
    assert removed.adapter_id == "opencodex"
    assert registry.adapter_ids() == ("omniroute",)

    fresh = default_registry()
    assert set(fresh.adapter_ids()) == {"omniroute", "opencodex"}
    assert PreUpstreamService is not None

    source = inspect.getsource(AdapterRegistry)
    assert "media_bridge." not in source
    assert "media_bridge_control" not in source
    assert "media_bridge_gateway" not in source


def test_registry_rejects_duplicate_or_missing_adapter() -> None:
    registry = default_registry()
    with pytest.raises(ValueError, match="already registered"):
        registry.register(registry.get("opencodex"))
    with pytest.raises(KeyError, match="missing"):
        registry.unregister("missing")
