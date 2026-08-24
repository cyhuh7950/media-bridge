from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from media_bridge_control.bootstrap import ControlPlaneService
from media_bridge_control.db import Database
from media_bridge_control.models import User
from media_bridge_control.security import SecurityContext


def sample_password() -> str:
    return "correct horse battery staple"


class StubGatewayClient:
    def __init__(self, *, fail_action: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_action = fail_action

    def _called(self, action: str, credential: str) -> None:
        assert credential.startswith("mbc_")
        self.calls.append(action)
        if self.fail_action == action:
            from media_bridge_control.gateway_client import GatewayClientError

            raise GatewayClientError("gateway_unavailable")

    async def status(self, *, base_url: str, credential: str) -> dict[str, object]:
        assert base_url == "https://gateway.example.test"
        self._called("status", credential)
        return {"status": "ready", "snapshot_version": 7}

    async def upload(
        self,
        *,
        base_url: str,
        credential: str,
        data: bytes,
        filename: str | None,
        declared_mime: str,
    ) -> str:
        assert base_url == "https://gateway.example.test"
        assert data
        assert filename == "error.png"
        assert declared_mime == "image/png"
        self._called("upload", credential)
        return "mb_abcdefghijklmnopqrstuvwxyz123456"

    async def prepare(
        self,
        *,
        base_url: str,
        credential: str,
        payload: dict[str, Any],
    ) -> dict[str, object]:
        assert base_url == "https://gateway.example.test"
        assert payload["target"] == {"registry_id": "text-model"}
        self._called("prepare", credential)
        return {
            "action": "converted",
            "target_model": "text-model",
            "contains_media": True,
            "contains_image": True,
            "contains_pdf": False,
            "target_supports_vision": False,
            "sanitized_text": "OCR SAFE RESULT",
            "original_image_removed": True,
            "error": None,
        }

    async def responses(
        self,
        *,
        base_url: str,
        credential: str,
        payload: dict[str, Any],
    ) -> dict[str, object]:
        assert base_url == "https://gateway.example.test"
        assert payload["model"] == "text-model"
        self._called("responses", credential)
        return {"id": "resp_test", "output": []}

    async def delete(
        self,
        *,
        base_url: str,
        credential: str,
        asset_id: str,
    ) -> None:
        assert base_url == "https://gateway.example.test"
        assert asset_id.startswith("mb_")
        self._called("delete", credential)


def configured_control(database_url: str) -> tuple[Database, ControlPlaneService]:
    database = Database(database_url)
    security = SecurityContext(pepper=b"r" * 32)
    service = ControlPlaneService(
        database=database,
        security=security,
        now=lambda: datetime(2026, 8, 25, 4, 0, tzinfo=UTC),
    )
    token = service.issue_bootstrap_token()
    service.complete_bootstrap(
        token=token,
        username="admin",
        password=sample_password(),
    )
    with database.session() as session:
        session.add_all(
            [
                User(
                    username="operator",
                    password_hash=security.passwords.hash(sample_password()),
                    role="operator",
                    is_active=True,
                ),
                User(
                    username="viewer",
                    password_hash=security.passwords.hash(sample_password()),
                    role="viewer",
                    is_active=True,
                ),
            ]
        )
    return database, service
