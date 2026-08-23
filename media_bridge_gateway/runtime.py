"""Immutable signed-snapshot generations for the product Gateway."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from media_bridge.config_snapshot import (
    MAX_SNAPSHOT_BYTES,
    SignedSnapshot,
    SnapshotVerificationError,
    SnapshotVerifier,
)
from media_bridge.gate import PreRequestGate
from media_bridge.receipts import GateReceiptSigner
from media_bridge.responses_state import ResponsesStateStore
from media_bridge_gateway.auth import SnapshotCredentialVerifier
from media_bridge_gateway.contracts import (
    DataPlaneSubject,
    GatewayResult,
    ResponsesDownstream,
)
from media_bridge_gateway.transaction import GatewayTransaction


@dataclass(frozen=True, slots=True)
class GatewayGeneration:
    version: int
    snapshot_id: str
    snapshot_digest: str
    gate: PreRequestGate
    downstream: ResponsesDownstream
    credential_verifier: SnapshotCredentialVerifier
    transaction: GatewayTransaction


class GenerationFactory(Protocol):
    def build(self, snapshot: SignedSnapshot) -> GatewayGeneration: ...


class GatewayTransactionFactory:
    """Build Core gate and downstream from the same verified snapshot."""

    def __init__(
        self,
        *,
        gate_factory: Callable[[SignedSnapshot], PreRequestGate],
        downstream_factory: Callable[[SignedSnapshot], ResponsesDownstream],
        receipt_signer: GateReceiptSigner,
        state_store_factory: Callable[[], ResponsesStateStore],
        credential_pepper: bytes,
    ) -> None:
        self._gate_factory = gate_factory
        self._downstream_factory = downstream_factory
        self._receipt_signer = receipt_signer
        self._state_store_factory = state_store_factory
        self._credential_pepper = credential_pepper

    def build(self, snapshot: SignedSnapshot) -> GatewayGeneration:
        gate = self._gate_factory(snapshot)
        downstream = self._downstream_factory(snapshot)
        credential_verifier = SnapshotCredentialVerifier(
            snapshot=snapshot,
            pepper=self._credential_pepper,
        )
        transaction = GatewayTransaction(
            gate=gate,
            downstream=downstream,
            receipt_signer=self._receipt_signer,
            state_store=self._state_store_factory(),
            snapshot_version=snapshot.version,
        )
        return GatewayGeneration(
            version=snapshot.version,
            snapshot_id=str(snapshot.snapshot_id),
            snapshot_digest=snapshot.digest,
            gate=gate,
            downstream=downstream,
            credential_verifier=credential_verifier,
            transaction=transaction,
        )


class VerifiedSnapshotRuntime:
    """Verify and atomically swap generations while retaining the last valid one."""

    def __init__(
        self,
        *,
        verifier: SnapshotVerifier,
        generation_factory: GenerationFactory,
    ) -> None:
        self._verifier = verifier
        self._generation_factory = generation_factory
        self._lock = threading.Lock()
        self._current: GatewayGeneration | None = None

    def load(self, path: Path) -> GatewayGeneration:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SNAPSHOT_BYTES:
                raise SnapshotVerificationError("snapshot file is unavailable or oversized")
            serialized = path.read_text(encoding="utf-8")
        except OSError as error:
            raise SnapshotVerificationError("snapshot file could not be read") from error
        candidate = self._verifier.verify_json(serialized)
        with self._lock:
            if self._current is not None and candidate.version <= self._current.version:
                raise SnapshotVerificationError("snapshot version is stale or replayed")
        generation = self._generation_factory.build(candidate)
        with self._lock:
            if self._current is not None and candidate.version <= self._current.version:
                raise SnapshotVerificationError("snapshot version is stale or replayed")
            self._current = generation
            return generation

    def current(self) -> GatewayGeneration:
        with self._lock:
            if self._current is None:
                raise SnapshotVerificationError("no valid snapshot generation has been loaded")
            return self._current

    async def invoke(self, payload: object, *, subject: DataPlaneSubject) -> GatewayResult:
        generation = self.current()
        return await generation.transaction.invoke(payload, subject=subject)
