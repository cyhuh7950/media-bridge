from __future__ import annotations

import base64
import json

from media_bridge_control.connections import ConnectionService, RuntimeConnection
from media_bridge_control.schemas import TestLabPreviewRequest as PreviewRequest
from media_bridge_control.secrets import GatewaySecretResolver
from media_bridge_control.test_lab import TestLabService as LabService
from tests.control.p2b_helpers import StubGatewayClient
from tests.gateway.helpers import png_bytes


async def test_preview_uses_db_connection_and_secret_reference(monkeypatch: object) -> None:
    monkeypatch.setenv("MEDIA_BRIDGE_GATEWAY_CREDENTIAL", "mbc_gateway.db-reference")
    request = PreviewRequest.model_validate_json(
        json.dumps(
            {
                "connection_id": "00000000-0000-0000-0000-000000000001",
                "target_model": "text-model",
                "conversion_profile": "generic",
                "user_request": "test",
                "media_type": "image",
                "filename": "error.png",
                "declared_mime": "image/png",
                "media_base64": base64.b64encode(png_bytes()).decode(),
            }
        )
    )
    connection = RuntimeConnection(
        id=str(request.connection_id),
        gateway_url="https://gateway.example.test",
        secret_ref_kind="env",  # noqa: S106
        secret_ref_identifier="MEDIA_BRIDGE_GATEWAY_CREDENTIAL",  # noqa: S106
    )

    class FakeConnections:
        def runtime(self, connection_id: str) -> RuntimeConnection:
            assert connection_id == connection.id
            return connection

        @staticmethod
        def secret_reference(value: RuntimeConnection):
            return ConnectionService.secret_reference(value)

    gateway = StubGatewayClient()
    service = LabService(
        connections=FakeConnections(),
        gateway_client=gateway,
        database=None,
        security=None,
        secret_resolver=GatewaySecretResolver(),
    )

    result = await service.preview(request)

    assert result["gateway"]["execution"] == "data-plane"
    assert gateway.calls == ["upload", "prepare", "delete"]
