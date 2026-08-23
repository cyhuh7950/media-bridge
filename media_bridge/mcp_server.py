"""MCP tool registration over the transport-independent application service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from mcp.server import MCPServer

from media_bridge.contracts import (
    AnalyzeErrorImageRequest,
    AnalyzeErrorImageResult,
    ContentPart,
    ExtractImageContextRequest,
    ExtractImageContextResult,
    PrepareForModelRequest,
    PrepareForModelResult,
    TargetModel,
)
from media_bridge.service import MediaBridgeService


def build_mcp_server(
    service: MediaBridgeService,
    *,
    tenant_provider: Callable[[], str],
) -> MCPServer[None]:
    server: MCPServer[None] = MCPServer(
        name="nonvision-media-bridge",
        title="Non-Vision Media Bridge",
        description="Fail-closed media conversion and pre-request model gate",
        version="0.1.0",
    )

    @server.tool(structured_output=True)
    async def extract_image_context(
        content: list[ContentPart],
        conversion_profile: Literal["generic", "error_screenshot", "document"] = "generic",
    ) -> ExtractImageContextResult:
        return await service.extract_image_context(
            ExtractImageContextRequest(
                content=content,
                conversion_profile=conversion_profile,
            ),
            tenant_id=tenant_provider(),
        )

    @server.tool(structured_output=True)
    async def analyze_error_image(
        content: list[ContentPart],
        user_request: str,
        analysis_backend: str = "solar",
        conversion_profile: Literal["generic", "error_screenshot", "document"] = "error_screenshot",
    ) -> AnalyzeErrorImageResult:
        return await service.analyze_error_image(
            AnalyzeErrorImageRequest(
                content=content,
                user_request=user_request,
                analysis_backend=analysis_backend,
                conversion_profile=conversion_profile,
            ),
            tenant_id=tenant_provider(),
        )

    @server.tool(structured_output=True)
    async def prepare_for_model(
        content: list[ContentPart],
        target: TargetModel,
        conversion_profile: Literal["generic", "error_screenshot", "document"] = "generic",
    ) -> PrepareForModelResult:
        return await service.prepare_for_model(
            PrepareForModelRequest(
                content=content,
                target=target,
                conversion_profile=conversion_profile,
            ),
            tenant_id=tenant_provider(),
        )

    return server
