"""격리 Codex CLI의 요청 형태만 확인하는 합성 응답 서버."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from media_bridge_personal.solar_responses import _response_payload, _sse_event


def main() -> None:
    root = Path(__file__).resolve().parents[2] / "qa-codex"
    profile = root / "profile"
    project = root / "project"
    profile.mkdir(exist_ok=True)
    project.mkdir(exist_ok=True)
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({
                "path": self.path,
                "stream": body.get("stream"),
                "fields": sorted(body),
                "tools": [{"type": t.get("type"), "name": t.get("name"),
                           "keys": sorted(t)} for t in body.get("tools", [])],
                "input": [{"type": t.get("type"), "role": t.get("role")}
                          for t in body.get("input", [])],
            })
            response = _response_payload(response_id="resp_probe", message_id="msg_probe",
                                         model="solar-pro4", text="PROBE_OK", usage={
                                             "input_tokens": 1, "output_tokens": 1,
                                             "total_tokens": 2})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(_sse_event("response.created", {
                "type": "response.created", "response": {**response, "output": [],
                                                           "status": "in_progress"}}))
            self.wfile.write(_sse_event("response.output_item.done", {
                "type": "response.output_item.done", "output_index": 0,
                "item": response["output"][0]}))
            self.wfile.write(_sse_event("response.completed", {
                "type": "response.completed", "response": response}))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {**os.environ, "CODEX_HOME": str(profile), "HOME": str(profile),
           "XDG_CACHE_HOME": str(root / "cache")}
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "SOLAR_API_KEY"):
        env.pop(key, None)
    cmd = [str(root / "node_modules/.bin/codex"), "exec", "--ephemeral",
           "--ignore-user-config", "--skip-git-repo-check", "--sandbox", "read-only",
           "-C", str(project), "-c", 'model_provider="probe"',
           "-c", 'model="solar-pro4"', "-c", 'model_providers.probe.name="probe"',
           "-c", f'model_providers.probe.base_url="http://127.0.0.1:{server.server_port}/v1"',
           "-c", 'model_providers.probe.wire_api="responses"',
           "-c", 'model_providers.probe.requires_openai_auth=false',
           "Reply PROBE_OK only. Do not use tools."]
    try:
        completed = subprocess.run(cmd, env=env, input="", capture_output=True, text=True, timeout=55)
        print(json.dumps({"returncode": completed.returncode, "requests": requests,
                          "stdout": completed.stdout, "stderr": completed.stderr},
                         ensure_ascii=False))
    except subprocess.TimeoutExpired as error:
        print(json.dumps({"timeout": True, "requests": requests,
                          "stdout": (error.stdout or b"").decode(errors="replace"),
                          "stderr": (error.stderr or b"").decode(errors="replace")},
                         ensure_ascii=False))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
