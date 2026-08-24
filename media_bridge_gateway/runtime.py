"""Immutable signed-snapshot generations for the product Gateway."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from media_bridge.backends import AnalysisBackend
from media_bridge.config_snapshot import (
    MAX_SNAPSHOT_BYTES,
    SignedSnapshot,
    SnapshotVerificationError,
    SnapshotVerifier,
)
from media_bridge.gate import PreRequestGate
from media_bridge.receipts import GateReceiptSigner
from media_bridge.service import MediaBridgeService
from media_bridge_gateway.auth import SnapshotCredentialVerifier
from media_bridge_gateway.contracts import (
    DataPlaneSubject,
    GatewayResult,
    ResponsesDownstream,
)
from media_bridge_gateway.state import GatewayStateStore
from media_bridge_gateway.transaction import GatewayTransaction


@dataclass(frozen=True, slots=True)
class GatewayGeneration:
    version: int
    snapshot_id: str
    snapshot_digest: str
    gate: PreRequestGate
    downstream: ResponsesDownstream
    credential_verifier: SnapshotCredentialVerifier
    service: MediaBridgeService
    state_store: GatewayStateStore
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
        state_store_factory: Callable[[], GatewayStateStore],
        credential_pepper: bytes,
        analysis_backends_factory: (
            Callable[[SignedSnapshot], dict[str, AnalysisBackend]] | None
        ) = None,
    ) -> None:
        self._gate_factory = gate_factory
        self._downstream_factory = downstream_factory
        self._receipt_signer = receipt_signer
        self._state_store = state_store_factory()
        self._credential_pepper = credential_pepper
        self._analysis_backends_factory = analysis_backends_factory

    def build(self, snapshot: SignedSnapshot) -> GatewayGeneration:
        gate = self._gate_factory(snapshot)
        downstream = self._downstream_factory(snapshot)
        credential_verifier = SnapshotCredentialVerifier(
            snapshot=snapshot,
            pepper=self._credential_pepper,
        )
        analysis_backends = (
            self._analysis_backends_factory(snapshot)
            if self._analysis_backends_factory is not None
            else {}
        )
        service = MediaBridgeService(gate=gate, analysis_backends=analysis_backends)
        state_store = self._state_store
        transaction = GatewayTransaction(
            gate=gate,
            downstream=downstream,
            receipt_signer=self._receipt_signer,
            state_store=state_store,
            snapshot_version=snapshot.version,
        )
        return GatewayGeneration(
            version=snapshot.version,
            snapshot_id=str(snapshot.snapshot_id),
            snapshot_digest=snapshot.digest,
            gate=gate,
            downstream=downstream,
            credential_verifier=credential_verifier,
            service=service,
            state_store=state_store,
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


class SnapshotFileReloader:
    """Apply atomic signed-snapshot replacements while retaining the LKG."""

    def __init__(self, *, path: Path, runtime: VerifiedSnapshotRuntime) -> None:
        self._path = path
        self._runtime = runtime
        self._lock = threading.Lock()
        self._seen: tuple[int, int, int, int] | None = None

    def refresh_if_changed(self) -> bool:
        with self._lock:
            try:
                stat = self._path.stat()
            except OSError:
                return False
            fingerprint = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if fingerprint == self._seen:
                return False
            self._seen = fingerprint
            try:
                self._runtime.load(self._path)
            except (SnapshotVerificationError, ValueError):
                return False
            return True
