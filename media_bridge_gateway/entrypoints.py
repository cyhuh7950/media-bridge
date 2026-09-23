"""Executable product Gateway composition from strict environment settings."""

from __future__ import annotations

import asyncio
import base64
import binascii
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx
import uvicorn
from sqlalchemy import select
from starlette.types import ASGIApp

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetStore
from media_bridge.backends import (
    AnalysisBackend,
    BackendStatus,
    OpenAICompatibleVisionBackend,
    SolarAnalysisBackend,
    UpstageOcrBackend,
    VisionBackend,
    VisionResult,
    load_secret,
)
from media_bridge.config_snapshot import SignedSnapshot, SnapshotVerifier
from media_bridge.gate import PreRequestGate
from media_bridge.llm_backends import build_llm_backend
from media_bridge.pdf_pipeline import PdfiumPageRenderer
from media_bridge.receipts import GateReceiptSigner
from media_bridge.runtime_snapshot import capability_registry_from_snapshot
from media_bridge_control.db import Database
from media_bridge_control.models import Provider
from media_bridge_control.security import SecurityContext
from media_bridge_gateway.app import build_gateway_app
from media_bridge_gateway.contracts import ResponsesDownstream
from media_bridge_gateway.downstream import ProviderResponsesDownstream
from media_bridge_gateway.rate_limit import CredentialRouteRateLimiter
from media_bridge_gateway.runtime import (
    GatewayTransactionFactory,
    SnapshotFileReloader,
    VerifiedSnapshotRuntime,
)
from media_bridge_gateway.state import GatewayStateStore


class GatewayConfigurationError(RuntimeError):
    pass


class _UnavailableVisionBackend:
    """Keep the gateway available when no optional Vision Provider is registered."""

    async def describe(
        self,
        *,
        data: bytes,
        mime_type: str,
        profile: str,
    ) -> VisionResult:
        del data, mime_type, profile
        return VisionResult(BackendStatus.FAILURE, error_code="configuration")


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
    downstream: ResponsesDownstream
    http_client: httpx.AsyncClient
    database: Database

    async def close(self) -> None:
        try:
            self.runtime.current().state_store.clear()
            self.asset_store.clear()
        finally:
            try:
                await self.downstream.close()
            finally:
                await self.http_client.aclose()
                self.database.close()


async def _close_partial_http_resources(
    *,
    downstream: ResponsesDownstream | None,
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
    downstream: ResponsesDownstream | None,
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
    downstream: ResponsesDownstream | None = None
    runtime: VerifiedSnapshotRuntime | None = None
    database: Database | None = None
    try:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(30),
            follow_redirects=False,
            trust_env=False,
            verify=_backend_tls_verify(),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        database_url = load_secret(
            "MEDIA_BRIDGE_CONTROL_DATABASE_URL",
            "MEDIA_BRIDGE_CONTROL_DATABASE_URL_FILE",
        )
        database = Database(database_url)
        db = database
        security = SecurityContext(pepper=credential_pepper)

        def db_provider(catalog_id: str, *, required: bool = True) -> Provider | None:
            with db.session() as session:
                provider = session.scalar(
                    select(Provider).where(
                        Provider.catalog_id == catalog_id,
                        Provider.enabled.is_(True),
                    )
                )
            if provider is None and required:
                raise ValueError("provider is not configured")
            return provider

        def db_provider_by_id(provider_id: str) -> Provider:
            try:
                parsed_id = UUID(provider_id)
            except (TypeError, ValueError) as error:
                raise ValueError("provider is not configured") from error
            with db.session() as session:
                provider = session.get(Provider, parsed_id)
            if provider is None or not provider.enabled:
                raise ValueError("provider is not configured")
            return provider

        def db_provider_credential(provider_id: str) -> str:
            provider = db_provider_by_id(provider_id)
            if not provider.encrypted_api_key:
                raise ValueError("provider credential is not configured")
            return security.decrypt_secret(provider.encrypted_api_key)

        ocr_provider = db_provider("upstage-document-parse", required=False)
        if ocr_provider is None:
            with db.session() as session:
                ocr_provider = session.scalar(
                    select(Provider).where(
                        Provider.kind == "analysis",
                        Provider.enabled.is_(True),
                    ).order_by(Provider.name)
                )
        if ocr_provider is None:
            raise GatewayConfigurationError("analysis Provider is not configured")
        vision_provider = db_provider("openai-vision", required=False)
        solar_provider = db_provider("upstage-solar", required=False)
        ocr = UpstageOcrBackend(
            endpoint=ocr_provider.endpoint,
            api_key_env=None,
            credential_loader=lambda: db_provider_credential(str(ocr_provider.id)),
            client=client,
        )
        vision: VisionBackend
        if vision_provider is None:
            vision = _UnavailableVisionBackend()
        else:
            if not vision_provider.model_id:
                raise GatewayConfigurationError("vision Provider model is not configured")
            vision = OpenAICompatibleVisionBackend(
                endpoint=vision_provider.endpoint,
                model=vision_provider.model_id,
                api_key_env=None,
                credential_loader=lambda: db_provider_credential(str(vision_provider.id)),
                client=client,
            )
        solar = None
        if solar_provider is not None:
            solar_endpoint = solar_provider.endpoint.rstrip("/")
            if not solar_endpoint.endswith("/chat/completions"):
                solar_endpoint = f"{solar_endpoint}/chat/completions"
            solar_model = solar_provider.model_id or "solar-pro4"
            solar = SolarAnalysisBackend(
                endpoint=solar_endpoint,
                model=solar_model,
                api_key_env=None,
                credential_loader=lambda: db_provider_credential(str(solar_provider.id)),
                client=client,
            )

        def provider_backend(provider: dict[str, object]) -> AnalysisBackend:
            provider_id = provider.get("id")
            if not isinstance(provider_id, str) or not provider_id:
                raise ValueError("provider identifier is invalid")

            def credential_loader() -> str:
                return db_provider_credential(provider_id)

            return build_llm_backend(
                provider,
                credential_loader=credential_loader,
                client=client,
            )

        def downstream_factory(snapshot: SignedSnapshot) -> ProviderResponsesDownstream:
            return ProviderResponsesDownstream(
                snapshot=snapshot.body,
                receipt_signer=receipt_signer,
                backend_factory=provider_backend,
            )

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
            downstream_factory=downstream_factory,
            receipt_signer=receipt_signer,
            state_store_factory=GatewayStateStore,
            credential_pepper=credential_pepper,
            analysis_backends_factory=lambda _snapshot: (
                {"solar": solar} if solar is not None else {}
            ),
        )
        runtime = VerifiedSnapshotRuntime(verifier=verifier, generation_factory=factory)
        runtime.load(snapshot_path)
        downstream = runtime.current().downstream
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
            downstream=downstream,
            http_client=client,
            database=database,
        )
    except BaseException:
        _cleanup_partial_build(
            downstream=downstream,
            client=client,
            runtime=runtime,
            asset_store=asset_store,
        )
        if database is not None:
            database.close()
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
