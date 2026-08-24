"""Console entrypoints for stdio and authenticated Streamable HTTP."""

from __future__ import annotations

import asyncio
import os

import uvicorn

from media_bridge.http_app import build_http_app
from media_bridge.runtime import (
    MediaBridgeRuntime,
    RuntimeConfigurationError,
    build_runtime_from_environment,
)


def _close_runtime(runtime: MediaBridgeRuntime) -> None:
    asyncio.run(runtime.close())


def run_stdio() -> None:
    runtime = build_runtime_from_environment()
    try:
        runtime.server.run("stdio")
    finally:
        _close_runtime(runtime)


def run_http() -> None:
    runtime = build_runtime_from_environment()
    host = os.environ.get("MEDIA_BRIDGE_HTTP_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("MEDIA_BRIDGE_HTTP_PORT", "8000"))
    except ValueError as error:
        raise RuntimeConfigurationError("HTTP port must be an integer") from error
    if port < 1 or port > 65_535:
        raise RuntimeConfigurationError("HTTP port is outside the valid range")
    app = build_http_app(
        server=runtime.server,
        asset_store=runtime.asset_store,
        responses_gateway=runtime.responses_gateway,
    )
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            access_log=False,
            server_header=False,
        )
    finally:
        _close_runtime(runtime)


def run_gateway() -> None:
    from media_bridge_gateway.entrypoints import run_gateway as run_product_gateway

    run_product_gateway()
