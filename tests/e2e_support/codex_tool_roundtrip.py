"""실제 격리 Codex → 개인 runtime → 합성 Chat provider 도구 왕복 QA."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
from pathlib import Path

import httpx
import uvicorn

from media_bridge_personal.npm_runtime import build_personal_app, build_personal_runtime
from media_bridge_personal.solar_responses import SolarResponsesDownstream


async def main() -> None:
    root = Path(__file__).resolve().parents[2] / "qa-codex"
    profile, project = root / "profile", root / "project"
    requests = []
    tool_results = []

    class NoMedia:
        async def extract(self, **_kwargs: object) -> None:
            raise AssertionError("텍스트 도구 시험에서 OCR을 호출하면 안 됩니다")

    def provider(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"message_roles": [m["role"] for m in body["messages"]],
                         "tool_names": [t["function"]["name"] for t in body.get("tools", [])]})
        results = [m for m in body["messages"] if m["role"] == "tool"]
        if results:
            tool_results.extend(results)
            assert results[-1]["tool_call_id"] == "call_mb_probe"
            assert "MB_TOOL_OK" in results[-1]["content"]
            assert "Process exited with code 0" in results[-1]["content"]
            message = {"role": "assistant", "content": "ROUNDTRIP_OK"}
        else:
            assert "exec_command" in requests[-1]["tool_names"]
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_mb_probe", "type": "function", "function": {
                    "name": "exec_command", "arguments": json.dumps({
                        "cmd": "printf MB_TOOL_OK", "workdir": str(project),
                        "max_output_tokens": 100})}}]}
        assert body["stream"] is True

        class ProviderStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                delta = dict(message)
                if "tool_calls" in delta:
                    delta["tool_calls"] = [{"index": 0, **delta["tool_calls"][0]}]
                for event in [
                    {"choices": [{"index": 0, "delta": delta}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason":
                                  "tool_calls" if "tool_calls" in message else "stop"}],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
                ]:
                    yield ("data: " + json.dumps(event) + "\n\n").encode()
                yield b"data: [DONE]\n\n"

        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              stream=ProviderStream())

    runtime = build_personal_runtime(
        model="solar-pro4", asset_root=root / "tool-assets", receipt_secret=b"q" * 32,
        ocr_backend=NoMedia(),
        downstream_factory=lambda signer: SolarResponsesDownstream(
            endpoint="https://synthetic.example.test/v1/chat/completions", model="solar-pro4",
            receipt_signer=signer, credential_loader=lambda: "synthetic-qa-only",
            transport=httpx.MockTransport(provider)),
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(build_personal_app(runtime), log_level="error"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    env = {**os.environ, "HOME": str(profile), "CODEX_HOME": str(profile),
           "XDG_CACHE_HOME": str(root / "cache")}
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "SOLAR_API_KEY"):
        env.pop(key, None)
    cmd = [str(root / "node_modules/.bin/codex"), "exec", "--ephemeral",
           "--ignore-user-config", "--skip-git-repo-check", "--sandbox", "read-only",
           "-C", str(project), "-c", 'model_provider="probe"', "-c", 'model="solar-pro4"',
           "-c", 'model_providers.probe.name="probe"',
           "-c", f'model_providers.probe.base_url="http://127.0.0.1:{listener.getsockname()[1]}/v1"',
           "-c", 'model_providers.probe.wire_api="responses"',
           "-c", 'model_providers.probe.requires_openai_auth=false',
           "-c", 'web_search="disabled"',
           "Run printf MB_TOOL_OK once, then reply ROUNDTRIP_OK."]
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.02)
        assert server.started
        result = await asyncio.to_thread(
            subprocess.run, cmd, env=env, input="", text=True, capture_output=True, timeout=55,
        )
        print(json.dumps({"returncode": result.returncode, "requests": requests,
                          "tool_results": tool_results, "stdout": result.stdout,
                          "stderr": result.stderr}, ensure_ascii=False))
        assert result.returncode == 0
        assert "ROUNDTRIP_OK" in result.stdout
        assert len(requests) == 2 and len(tool_results) == 1
    finally:
        server.should_exit = True
        await serving
        listener.close()
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
