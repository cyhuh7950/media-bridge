from pathlib import Path
from urllib.error import URLError

import pytest

from deploy.health import control_plane, data_plane


def test_data_readiness_fails_without_first_snapshot(tmp_path: Path) -> None:
    with pytest.raises(data_plane.HealthCheckError, match="snapshot_not_ready"):
        data_plane.check(snapshot_path=tmp_path / "active.json", url="http://127.0.0.1/status")


def test_data_readiness_accepts_last_known_good_during_control_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "active.json"
    snapshot.write_text('{"version": 7}', encoding="utf-8")
    monkeypatch.setattr(data_plane, "gateway_listening", lambda _url: True)
    data_plane.check(snapshot_path=snapshot, url="http://127.0.0.1/status")


def test_data_readiness_fails_closed_on_bad_gateway_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "active.json"
    snapshot.write_text('{"version": 7}', encoding="utf-8")
    monkeypatch.setattr(data_plane, "gateway_listening", lambda _url: False)
    with pytest.raises(data_plane.HealthCheckError, match="gateway_not_ready"):
        data_plane.check(snapshot_path=snapshot, url="http://127.0.0.1/status")


def test_control_health_rejects_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_url: str) -> dict[str, object]:
        raise URLError("closed")

    monkeypatch.setattr(control_plane, "fetch_json", fail)
    with pytest.raises(control_plane.HealthCheckError, match="control_not_ready"):
        control_plane.check("http://127.0.0.1/admin/v1/health")
