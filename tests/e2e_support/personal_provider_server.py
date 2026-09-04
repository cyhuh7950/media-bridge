"""Loopback-only synthetic providers for the personal settings console E2E."""

from __future__ import annotations

import argparse
import json

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def build_app() -> Starlette:
    async def document_parse(request: Request) -> JSONResponse:
        if request.headers.get("authorization") != "Bearer synthetic-provider-secret":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        form = await request.form()
        document = form.get("document")
        if document is None:
            return JSONResponse({"error": "document required"}, status_code=400)
        return JSONResponse({"content": {"text": "E2E 화면에서 추출한 문장"}})

    async def chat_completions(request: Request) -> JSONResponse:
        if request.headers.get("authorization") != "Bearer synthetic-provider-secret":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        payload = await request.json()
        serialized = json.dumps(payload, ensure_ascii=False)
        if "input_image" in serialized or "data:image" in serialized:
            return JSONResponse({"error": "original media forwarded"}, status_code=400)
        return JSONResponse(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "텍스트 전용 연결 정상"}}
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11},
            }
        )

    async def responses(request: Request) -> JSONResponse:
        if request.headers.get("authorization") != "Bearer synthetic-provider-secret":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        payload = await request.json()
        serialized = json.dumps(payload, ensure_ascii=False)
        if "input_image" in serialized or "data:image" in serialized:
            return JSONResponse({"error": "original media forwarded"}, status_code=400)
        return JSONResponse(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Responses 연결 정상"}],
                    }
                ],
                "usage": {"input_tokens": 7, "output_tokens": 4, "total_tokens": 11},
            }
        )

    return Starlette(
        routes=[
            Route("/v1/document-digitization", document_parse, methods=["POST"]),
            Route("/v1/chat/completions", chat_completions, methods=["POST"]),
            Route("/v1/responses", responses, methods=["POST"]),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
