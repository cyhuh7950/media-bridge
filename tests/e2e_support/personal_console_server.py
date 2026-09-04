"""Source-level personal console server for browser acceptance testing."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import uvicorn

from media_bridge_personal.credential_store import CredentialStore
from media_bridge_personal.npm_runtime import (
    ReloadablePersonalRuntime,
    _write_npm_config,
    build_personal_app,
    build_personal_runtime_from_config,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--provider-port", type=int, required=True)
    args = parser.parse_args()
    args.profile_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_file = args.profile_root / "config.json"
    provider_base = f"http://127.0.0.1:{args.provider_port}"
    config = {
        "runtimeMode": "personal",
        "host": "127.0.0.1",
        "port": args.port,
        "codingAgent": {
            "preset": "opencodex",
            "protocol": "openai-responses",
            "baseUrl": f"http://127.0.0.1:{args.port}/v1",
        },
        "textLlm": {
            "preset": "custom",
            "protocol": "openai-chat-completions",
            "endpoint": f"{provider_base}/v1/chat/completions",
            "model": "synthetic-text-model",
            "credentialRef": "text-llm",
            "credentialEnv": "SYNTHETIC_LLM_KEY",
        },
        "mediaProcessor": {
            "preset": "upstage-document-parse",
            "protocol": "upstage-document-parse",
            "endpoint": f"{provider_base}/v1/document-digitization",
            "model": "document-parse",
            "credentialRef": "media-processor",
            "credentialEnv": "SYNTHETIC_OCR_KEY",
        },
        "opencodex": {"baseUrl": f"http://127.0.0.1:{args.port}/v1"},
        "solar": {
            "endpoint": f"{provider_base}/v1/chat/completions",
            "model": "synthetic-text-model",
            "apiKeyEnv": "SYNTHETIC_LLM_KEY",
        },
        "ocr": {
            "endpoint": f"{provider_base}/v1/document-digitization",
            "model": "document-parse",
            "apiKeyEnv": "SYNTHETIC_OCR_KEY",
        },
        "conversion": {"maxBytes": 8_388_608, "ocrEnabled": True, "visionEnabled": True},
        "failurePolicy": {"blockSolarOnPreparationFailure": True},
    }
    _write_npm_config(config_file, config)
    store = CredentialStore(args.profile_root / "secrets" / "providers.json")
    store.set("text-llm", "synthetic-provider-secret")
    store.set("media-processor", "synthetic-provider-secret")
    os.environ["MEDIA_BRIDGE_ASSET_ROOT"] = str(args.profile_root / "assets")
    os.environ["MEDIA_BRIDGE_RECEIPT_SECRET"] = "r" * 32
    runtime = ReloadablePersonalRuntime(
        build_personal_runtime_from_config(config_file, store),
        lambda: build_personal_runtime_from_config(config_file, store),
    )
    try:
        uvicorn.run(
            build_personal_app(runtime, config_file=config_file, credential_store=store),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
            server_header=False,
        )
    finally:
        asyncio.run(runtime.close())


if __name__ == "__main__":
    main()
