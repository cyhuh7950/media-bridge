from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from media_bridge_gateway.contracts import (
    DataPlaneSubject,
    GatewayResponse,
    ResponsesDownstream,
    SealedGatewayRequest,
)


class FakeDownstream:
    async def invoke(self, request: SealedGatewayRequest) -> GatewayResponse:
        return GatewayResponse(
            body=b'{"id":"resp_contract"}',
            content_type="application/json",
            response_id="resp_contract",
            status_code=200,
        )


def test_product_neutral_downstream_contract_has_no_router_dependency() -> None:
    downstream = FakeDownstream()
    assert isinstance(downstream, ResponsesDownstream)


def test_sealed_request_and_subject_are_immutable() -> None:
    subject = DataPlaneSubject(
        credential_selector="mbc-selector",
        tenant_id="tenant-a",
        scopes=frozenset({"responses:invoke"}),
    )
    sealed = SealedGatewayRequest(
        target_id="vendor/text-model",
        capability="non_vision",
        action="passthrough",
        payload={"model": "vendor/text-model", "input": "safe"},
        input_digest="a" * 64,
        output_digest="b" * 64,
        receipt="receipt",
        request_nonce="contract-nonce-0001",
        snapshot_version=7,
    )

    with pytest.raises(FrozenInstanceError):
        subject.tenant_id = "tenant-b"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        sealed.snapshot_version = 8  # type: ignore[misc]


@pytest.mark.parametrize(
    ("credential_selector", "tenant_id", "scopes"),
    [
        ("", "tenant-a", frozenset({"responses:invoke"})),
        ("selector", "bad tenant", frozenset({"responses:invoke"})),
        ("selector", "tenant-a", frozenset()),
    ],
)
def test_subject_rejects_invalid_identity(
    credential_selector: str,
    tenant_id: str,
    scopes: frozenset[str],
) -> None:
    with pytest.raises(ValueError):
        DataPlaneSubject(
            credential_selector=credential_selector,
            tenant_id=tenant_id,
            scopes=scopes,
        )
