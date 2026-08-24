"""Backward-compatible wrapper for the product-neutral Gateway transaction."""

from __future__ import annotations

from media_bridge.gate import PreRequestGate
from media_bridge.omniroute_adapter import GuardedOmniRouteAdapter
from media_bridge.receipts import GateReceiptSigner
from media_bridge.responses_state import ResponsesStateStore
from media_bridge_gateway.contracts import DataPlaneSubject, GatewayResult
from media_bridge_gateway.state import LegacyResponsesStateAdapter
from media_bridge_gateway.transaction import GatewayTransaction

ResponsesGatewayResult = GatewayResult


class ResponsesIngressGateway:
    """Preserve the A안 constructor while delegating to the neutral transaction."""

    def __init__(
        self,
        *,
        gate: PreRequestGate,
        adapter: GuardedOmniRouteAdapter,
        receipt_signer: GateReceiptSigner,
        state_store: ResponsesStateStore,
    ) -> None:
        self._transaction = GatewayTransaction(
            gate=gate,
            downstream=adapter,
            receipt_signer=receipt_signer,
            state_store=LegacyResponsesStateAdapter(state_store),
        )

    def clear_state(self) -> None:
        self._transaction.clear_state()

    async def invoke(self, payload: object, *, tenant_id: str) -> ResponsesGatewayResult:
        subject = DataPlaneSubject(
            credential_selector=f"legacy:{tenant_id}",
            tenant_id=tenant_id,
            scopes=frozenset({"responses:invoke"}),
        )
        return await self._transaction.invoke(payload, subject=subject)


__all__ = ["ResponsesGatewayResult", "ResponsesIngressGateway"]
