"""Executable product Gateway composition from strict environment settings."""

from __future__ import annotations

import asyncio
import base64
import binascii
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import httpx
import uvicorn
from starlette.types import ASGIApp

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import (
    OpenAICompatibleVisionBackend,
    SolarAnalysisBackend,
    UpstageOcrBackend,
    load_secret,
)
from media_bridge.config_snapshot import SignedSnapshot, SnapshotVerifier
from media_bridge.gate import PreRequestGate
from media_bridge.pdf_pipeline import PdfiumPageRenderer
from media_bridge.receipts import GateReceiptSigner
from media_bridge.runtime_snapshot import capability_registry_from_snapshot
from media_bridge_gateway.app import build_gateway_app
from media_bridge_gateway.downstream import GuardedResponsesDownstream
from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter
from media_bridge_gateway.runtime import (
    GatewayTransactionFactory,
    SnapshotFileReloader,
    VerifiedSnapshotRuntime,
)
from media_bridge_gateway.state import GatewayStateStore


class GatewayConfigurationError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise GatewayConfigurationError(f"required environment setting {name} is missing")
    return value


def _absolute_path(name: str) -> Path:
    path = Path(_required(name))
    if not path.is_absolute() or path.is_symlink():
        raise GatewayConfigurationError(f"{name} must be an absolute non-symlink path")
    return path


def _backend_tls_verify() -> bool | str:
    name = "MEDIA_BRIDGE_BACKEND_CA_FILE"
    if not os.environ.get(name, "").strip():
        return True
    path = _absolute_path(name)
    try:
        if not path.is_file():
            raise GatewayConfigurationError(f"{name} must reference a regular file")
    except OSError as error:
        raise GatewayConfigurationError(f"{name} is unavailable") from error
    return str(path)


def _integer(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise GatewayConfigurationError(f"{name} must be an integer") from error
    if value < minimum or value > maximum:
        raise GatewayConfigurationError(f"{name} is outside the allowed range")
    return value


def _public_key() -> bytes:
    encoded = load_secret(
        "MEDIA_BRIDGE_SNAPSHOT_PUBLIC_KEY",
        "MEDIA_BRIDGE_SNAPSHOT_PUBLIC_KEY_FILE",
    )
    try:
        value = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (binascii.Error, ValueError) as error:
        raise GatewayConfigurationError("snapshot public key is invalid") from error
    if len(value) != 32:
        raise GatewayConfigurationError("snapshot public key is invalid")
    return value


@dataclass(slots=True)
class GatewayProcess:
    app: ASGIApp
    runtime: VerifiedSnapshotRuntime
    asset_store: AssetStore
    downstream: GuardedResponsesDownstream
    http_client: httpx.AsyncClient

    async def close(self) -> None:
        try:
            self.runtime.current().state_store.clear()
            self.asset_store.clear()
        finally:
            try:
                await self.downstream.close()
            finally:
                await self.http_client.aclose()


async def _close_partial_http_resources(
    *,
    downstream: GuardedResponsesDownstream | None,
    client: httpx.AsyncClient | None,
) -> None:
    if downstream is not None:
        with suppress(Exception):
            await downstream.close()
    if client is not None:
        with suppress(Exception):
            await client.aclose()


def _cleanup_partial_build(
    *,
    downstream: GuardedResponsesDownstream | None,
    client: httpx.AsyncClient | None,
    runtime: VerifiedSnapshotRuntime | None,
    asset_store: AssetStore,
) -> None:
    if runtime is not None:
        with suppress(Exception):
            runtime.current().state_store.clear()
    with suppress(Exception):
        asset_store.clear()
    close = _close_partial_http_resources(downstream=downstream, client=client)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(close)
    else:
        loop.create_task(close)


def build_gateway_process_from_environment() -> GatewayProcess:
    key_id = _required("MEDIA_BRIDGE_SNAPSHOT_KEY_ID")
    verifier = SnapshotVerifier({key_id: _public_key()})
    snapshot_path = _absolute_path("MEDIA_BRIDGE_SNAPSHOT_PATH")
    asset_store = AssetStore(_absolute_path("MEDIA_BRIDGE_ASSET_ROOT"))
    credential_pepper = load_secret(
        "MEDIA_BRIDGE_GATEWAY_AUTH_PEPPER",
        "MEDIA_BRIDGE_GATEWAY_AUTH_PEPPER_FILE",
    ).encode()
    receipt_signer = GateReceiptSigner(
        secret=load_secret(
            "MEDIA_BRIDGE_RECEIPT_SECRET",
            "MEDIA_BRIDGE_RECEIPT_SECRET_FILE",
        ).encode()
    )
    client: httpx.AsyncClient | None = None
    downstream: GuardedResponsesDownstream | None = None
    runtime: VerifiedSnapshotRuntime | None = None
    try:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(30),
            follow_redirects=False,
            trust_env=False,
            verify=_backend_tls_verify(),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        ocr = UpstageOcrBackend(
            endpoint=_required("MEDIA_BRIDGE_OCR_ENDPOINT"),
            api_key_env="MEDIA_BRIDGE_OCR_API_KEY",
            api_key_file_env="MEDIA_BRIDGE_OCR_API_KEY_FILE",
            client=client,
        )
        vision = OpenAICompatibleVisionBackend(
            endpoint=_required("MEDIA_BRIDGE_VISION_ENDPOINT"),
            model=_required("MEDIA_BRIDGE_VISION_MODEL"),
            api_key_env="MEDIA_BRIDGE_VISION_API_KEY",
            api_key_file_env="MEDIA_BRIDGE_VISION_API_KEY_FILE",
            client=client,
        )
        solar = SolarAnalysisBackend(
            endpoint=os.environ.get(
                "MEDIA_BRIDGE_SOLAR_ENDPOINT",
                "https://api.upstage.ai/v1/chat/completions",
            ),
            model=os.environ.get("MEDIA_BRIDGE_SOLAR_MODEL", "solar-pro4"),
            api_key_env="MEDIA_BRIDGE_SOLAR_API_KEY",
            api_key_file_env="MEDIA_BRIDGE_SOLAR_API_KEY_FILE",
            client=client,
        )
        configured_downstream = GuardedResponsesDownstream(
            endpoint=_required("MEDIA_BRIDGE_DOWNSTREAM_RESPONSES_URL"),
            receipt_signer=receipt_signer,
            verify=_backend_tls_verify(),
        )
        downstream = configured_downstream

        def gate_factory(snapshot: SignedSnapshot) -> PreRequestGate:
            return PreRequestGate(
                registry=capability_registry_from_snapshot(snapshot),
                acquirer=MediaAcquirer(asset_store=asset_store),
                ocr_backend=ocr,
                vision_backend=vision,
                receipt_signer=receipt_signer,
                pdf_renderer=PdfiumPageRenderer(),
            )

        factory = GatewayTransactionFactory(
            gate_factory=gate_factory,
            downstream_factory=lambda _snapshot: configured_downstream,
            receipt_signer=receipt_signer,
            state_store_factory=GatewayStateStore,
            credential_pepper=credential_pepper,
            analysis_backends_factory=lambda _snapshot: {"solar": solar},
        )
        runtime = VerifiedSnapshotRuntime(verifier=verifier, generation_factory=factory)
        runtime.load(snapshot_path)
        app = build_gateway_app(
            runtime=runtime,
            asset_store=asset_store,
            snapshot_reloader=SnapshotFileReloader(path=snapshot_path, runtime=runtime),
            rate_limiter=CredentialRouteRateLimiter(
                capacity=_integer(
                    "MEDIA_BRIDGE_GATEWAY_RATE_CAPACITY",
                    60,
                    minimum=1,
                    maximum=10_000,
                ),
                refill_per_second=float(
                    _integer(
                        "MEDIA_BRIDGE_GATEWAY_RATE_PER_SECOND",
                        10,
                        minimum=1,
                        maximum=1_000,
                    )
                ),
                max_keys=_integer(
                    "MEDIA_BRIDGE_GATEWAY_RATE_MAX_KEYS",
                    100_000,
                    minimum=1,
                    maximum=1_000_000,
                ),
                idle_ttl_seconds=600,
            ),
        )
        return GatewayProcess(
            app=app,
            runtime=runtime,
            asset_store=asset_store,
            downstream=configured_downstream,
            http_client=client,
        )
    except BaseException:
        _cleanup_partial_build(
            downstream=downstream,
            client=client,
            runtime=runtime,
            asset_store=asset_store,
        )
        raise


def run_gateway() -> None:
    host = os.environ.get("MEDIA_BRIDGE_GATEWAY_HOST", "127.0.0.1")
    port = _integer("MEDIA_BRIDGE_GATEWAY_PORT", 8001, minimum=1, maximum=65_535)
    process = build_gateway_process_from_environment()
    try:
        uvicorn.run(
            process.app,
            host=host,
            port=port,
            access_log=False,
            server_header=False,
        )
    finally:
        asyncio.run(process.close())
