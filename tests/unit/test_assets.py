from pathlib import Path

import pytest

from media_bridge.assets import AssetAccessError, AssetStore


def test_asset_delete_is_tenant_scoped_and_idempotent(tmp_path: Path) -> None:
    store = AssetStore(tmp_path / "assets")
    asset_id = store.put(tenant_id="tenant-a", data=b"media")

    assert store.delete(asset_id=asset_id, tenant_id="tenant-b") is False
    assert store.delete(asset_id=asset_id, tenant_id="tenant-a") is True
    assert store.delete(asset_id=asset_id, tenant_id="tenant-a") is False
    assert list((tmp_path / "assets").iterdir()) == []


def test_asset_delete_fails_closed_when_unlink_cannot_be_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AssetStore(tmp_path / "assets")
    asset_id = store.put(tenant_id="tenant-a", data=b"media")

    def fail_unlink(_path: Path, *, missing_ok: bool = False) -> None:
        del missing_ok
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(AssetAccessError, match="could not be deleted safely"):
        store.delete(asset_id=asset_id, tenant_id="tenant-a")
