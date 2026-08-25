"""Safe inspect, configuration rendering, and adapter connectivity commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Never, TextIO

import httpx
from pydantic import ValidationError

from media_bridge_adapters.compatibility import inspect_compatibility
from media_bridge_adapters.contracts import (
    AdapterConfigRequest,
    AdapterProbeResult,
    PreUpstreamResult,
)
from media_bridge_adapters.omniroute.config import render_config as render_omniroute_config
from media_bridge_adapters.opencodex.config import render_config as render_opencodex_config
from media_bridge_adapters.validation import validate_adapter_endpoint, write_rendered_config

_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> Never:
        raise ValueError("invalid_arguments")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(prog="media-bridge-adapter")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser("inspect")
    _add_build_arguments(inspect_parser)

    render_parser = commands.add_parser("render-config")
    _add_build_arguments(render_parser)
    render_parser.add_argument("--endpoint", required=True)
    render_parser.add_argument("--credential-env", required=True)
    render_parser.add_argument("--decision-hmac-env", required=True)
    render_parser.add_argument("--timeout-ms", type=int, default=15_000)
    render_parser.add_argument("--max-response-bytes", type=int, default=512 * 1024)
    render_parser.add_argument("--output", type=Path, required=True)

    probe_parser = commands.add_parser("test-connection")
    probe_parser.add_argument("--endpoint", required=True)
    probe_parser.add_argument("--credential-env", required=True)
    probe_parser.add_argument("--timeout-ms", type=int, default=15_000)
    probe_parser.add_argument("--max-response-bytes", type=int, default=512 * 1024)
    return parser


def _add_build_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--adapter", choices=("opencodex", "omniroute"), required=True)
    parser.add_argument("--external-version", required=True)
    parser.add_argument("--external-base-commit", required=True)
    parser.add_argument("--extension-commit", required=True)


async def probe_connection(
    *,
    endpoint: str,
    credential_env: str,
    environ: Mapping[str, str] = os.environ,
    timeout_ms: int = 15_000,
    max_response_bytes: int = 512 * 1024,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AdapterProbeResult:
    try:
        endpoint = validate_adapter_endpoint(endpoint)
    except ValueError:
        return AdapterProbeResult(reachable=False, http_status=None, error="endpoint_invalid")
    if not _ENV_NAME.fullmatch(credential_env):
        return AdapterProbeResult(reachable=False, http_status=None, error="credential_unavailable")
    credential = environ.get(credential_env)
    if (
        credential is None
        or not credential.startswith("mbc_")
        or credential.strip() != credential
        or len(credential) > 160
    ):
        return AdapterProbeResult(reachable=False, http_status=None, error="credential_unavailable")
    if not 1 <= timeout_ms <= 120_000 or not 1 <= max_response_bytes <= 4 * 1024 * 1024:
        return AdapterProbeResult(reachable=False, http_status=None, error="probe_failed")
    payload = {
        "contract_version": "media-bridge-pre-upstream/v1",
        "request_id": "media-bridge-connectivity-probe",
        "wire_format": "openai-responses",
        "provider": "media-bridge-probe",
        "target_model": "media-bridge-probe-text",
        "body": {"model": "media-bridge-probe-text", "input": "Media Bridge connectivity probe"},
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_ms / 1000),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            response = await client.post(
                endpoint,
                headers={"authorization": f"Bearer {credential}", "accept": "application/json"},
                json=payload,
            )
    except httpx.HTTPError:
        return AdapterProbeResult(reachable=False, http_status=None, error="probe_failed")
    if response.is_redirect:
        return AdapterProbeResult(
            reachable=False, http_status=response.status_code, error="redirect_rejected"
        )
    if len(response.content) > max_response_bytes:
        return AdapterProbeResult(
            reachable=False, http_status=response.status_code, error="response_too_large"
        )
    if (
        response.status_code not in {200, 422}
        or response.headers.get("content-type", "").partition(";")[0] != "application/json"
    ):
        return AdapterProbeResult(
            reachable=False, http_status=response.status_code, error="response_invalid"
        )
    try:
        PreUpstreamResult.model_validate_json(response.content)
    except ValidationError:
        return AdapterProbeResult(
            reachable=False, http_status=response.status_code, error="response_invalid"
        )
    return AdapterProbeResult(reachable=True, http_status=response.status_code, error=None)


def _write_json(stream: TextIO, payload: object) -> None:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    stream.write(text + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "inspect":
            compatibility = inspect_compatibility(
                adapter_id=args.adapter,
                external_version=args.external_version,
                external_base_commit=args.external_base_commit,
                extension_commit=args.extension_commit,
            )
            _write_json(sys.stdout, compatibility.model_dump(mode="json"))
            return 0 if compatibility.compatible else 2
        if args.command == "render-config":
            request = AdapterConfigRequest(
                adapter_id=args.adapter,
                external_version=args.external_version,
                external_base_commit=args.external_base_commit,
                extension_commit=args.extension_commit,
                endpoint=args.endpoint,
                credential_env=args.credential_env,
                decision_hmac_env=args.decision_hmac_env,
                timeout_ms=args.timeout_ms,
                max_response_bytes=args.max_response_bytes,
                output_path=args.output.resolve(),
            )
            renderer = (
                render_opencodex_config if args.adapter == "opencodex" else render_omniroute_config
            )
            write_rendered_config(renderer(request))
            _write_json(sys.stdout, {"adapter_id": args.adapter, "status": "written"})
            return 0
        probe_result = asyncio.run(
            probe_connection(
                endpoint=args.endpoint,
                credential_env=args.credential_env,
                timeout_ms=args.timeout_ms,
                max_response_bytes=args.max_response_bytes,
            )
        )
        _write_json(sys.stdout, probe_result.model_dump(mode="json"))
        return 0 if probe_result.reachable else 2
    except FileExistsError:
        _write_json(sys.stderr, {"error": "output_exists"})
    except (ValidationError, ValueError):
        _write_json(sys.stderr, {"error": "invalid_arguments"})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
