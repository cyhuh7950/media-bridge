from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from media_bridge_control.schemas import TestLabRunRequest as RunRequest
from media_bridge_control.secrets import GatewaySecretResolver
from media_bridge_control.security import SecurityContext
from media_bridge_control.test_lab import TestLabService as Service


class RecordingGateway:
    def __init__(self) -> None:
        self.responses_payloads: list[dict[str, Any]] = []

    async def upload(self, **_kwargs: Any) -> str:
        return "asset_test"

    async def responses(self, **kwargs: Any) -> dict[str, object]:
        self.responses_payloads.append(kwargs["payload"])
        return {"id": "resp_test"}

    async def delete(self, **_kwargs: Any) -> None:
        return None


@pytest.mark.parametrize(
    ("selected_model", "expected_model"),
    [(None, None), ("auto", "auto"), ("vendor/public-model", "vendor/public-model")],
)
async def test_external_flow_preserves_selected_model_semantics_for_gateway(
    selected_model: str | None,
    expected_model: str | None,
) -> None:
    gateway = RecordingGateway()
    def scalar(_statement: object) -> SimpleNamespace:
        if selected_model not in (None, "auto"):
            return SimpleNamespace(model_id=selected_model)
        return SimpleNamespace(model_id="control-db-only/model")

    database = SimpleNamespace(session=lambda: nullcontext(SimpleNamespace(scalar=scalar)))
    service = Service(
        gateway_client=gateway,
        database=database,
        security=SecurityContext(pepper=b"p" * 32),
        secret_resolver=GatewaySecretResolver(),
    )
    request = RunRequest(
        target_model=selected_model,
        user_request="이 이미지의 내용을 설명해줘",
        media_type="image",
        filename="test.png",
        declared_mime="image/png",
        media_base64="AA==",
        gateway_url="https://gateway.example.test",
        api_key="mbc_selector.secret",
        execute_downstream=True,
    )

    result = await service.run(request)

    assert result == {"id": "resp_test"}
    assert len(gateway.responses_payloads) == 1
    assert ("model" in gateway.responses_payloads[0]) is (expected_model is not None)
    assert gateway.responses_payloads[0].get("model") == expected_model
