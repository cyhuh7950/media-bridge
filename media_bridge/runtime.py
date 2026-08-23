"""Strict environment and registry wiring for executable transports."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
import yaml
from mcp.server import MCPServer
from pydantic import Field, StringConstraints, ValidationError, field_validator

from media_bridge.acquisition import MediaAcquirer
from media_bridge.assets import AssetAccessError, AssetStore, validate_tenant_id
from media_bridge.backends import (
    OpenAICompatibleVisionBackend,
    SecretConfigurationError,
    SolarAnalysisBackend,
    UpstageOcrBackend,
    load_secret,
)
from media_bridge.capabilities import CapabilityRegistry, ModelCapability
from media_bridge.contracts import StrictModel
from media_bridge.gate import PreRequestGate
from media_bridge.http_app import current_tenant
from media_bridge.mcp_server import build_mcp_server
from media_bridge.receipts import GateReceiptSigner
from media_bridge.service import MediaBridgeService


class RuntimeConfigurationError(RuntimeError):
    """Raised before serving when trusted runtime configuration is invalid."""


class RegistryModelEntry(StrictModel):
    model_id: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z0-9][a-z0-9./:_-]{0,127}$"),
    ] = Field(alias="id")
    input_modalities: set[Literal["text", "image", "pdf"]]
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        return value


class RegistryDocument(StrictModel):
    version: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    models: list[RegistryModelEntry]


@dataclass(slots=True)
class MediaBridgeRuntime:
    service: MediaBridgeService
    asset_store: AssetStore
    server: MCPServer[None]
    http_client: httpx.AsyncClient

    async def close(self) -> None:
        try:
            self.asset_store.clear()
        finally:
            await self.http_client.aclose()


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeConfigurationError(f"required environment setting {name} is missing")
    return value


def _load_registry(path: Path) -> CapabilityRegistry:
    try:
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise RuntimeConfigurationError("model registry file is unavailable or oversized")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        document = RegistryDocument.model_validate(raw)
    except (OSError, ValidationError, yaml.YAMLError, UnicodeError) as error:
        raise RuntimeConfigurationError("model registry is invalid") from error

    model_ids = [entry.model_id for entry in document.models]
    if len(model_ids) != len(set(model_ids)):
        raise RuntimeConfigurationError("model registry contains duplicate exact identifiers")
    capabilities = [
        ModelCapability(
            model_id=entry.model_id,
            input_modalities=set(entry.input_modalities),
            expires_at=entry.expires_at,
        )
        for entry in document.models
    ]
    return CapabilityRegistry(capabilities, version=document.version)


def _tenant_provider() -> str:
    tenant_id = current_tenant.get() or os.environ.get("MEDIA_BRIDGE_TENANT_ID", "").strip()
    try:
        validate_tenant_id(tenant_id)
    except AssetAccessError as error:
        raise RuntimeConfigurationError("authenticated tenant context is missing") from error
    return tenant_id


def build_runtime_from_environment() -> MediaBridgeRuntime:
    registry = _load_registry(Path(_required_environment("MEDIA_BRIDGE_MODEL_REGISTRY")))
    asset_root = Path(_required_environment("MEDIA_BRIDGE_ASSET_ROOT"))
    if not asset_root.is_absolute() or asset_root.is_symlink():
        raise RuntimeConfigurationError("asset root must be an absolute non-symlink path")
    asset_store = AssetStore(asset_root)

    try:
        receipt_secret = load_secret(
            "MEDIA_BRIDGE_RECEIPT_SECRET",
            "MEDIA_BRIDGE_RECEIPT_SECRET_FILE",
        ).encode("utf-8")
        signer = GateReceiptSigner(secret=receipt_secret)
    except (SecretConfigurationError, ValueError) as error:
        raise RuntimeConfigurationError("receipt secret is missing or too short") from error

    ocr_endpoint = _required_environment("MEDIA_BRIDGE_OCR_ENDPOINT")
    vision_endpoint = _required_environment("MEDIA_BRIDGE_VISION_ENDPOINT")
    vision_model = _required_environment("MEDIA_BRIDGE_VISION_MODEL")
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(30),
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    ocr = UpstageOcrBackend(endpoint=ocr_endpoint, client=client)
    vision = OpenAICompatibleVisionBackend(
        endpoint=vision_endpoint,
        model=vision_model,
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
        client=client,
    )
    gate = PreRequestGate(
        registry=registry,
        acquirer=MediaAcquirer(asset_store=asset_store),
        ocr_backend=ocr,
        vision_backend=vision,
        receipt_signer=signer,
    )
    service = MediaBridgeService(gate=gate, analysis_backends={"solar": solar})
    server = build_mcp_server(service, tenant_provider=_tenant_provider)
    return MediaBridgeRuntime(
        service=service,
        asset_store=asset_store,
        server=server,
        http_client=client,
    )
