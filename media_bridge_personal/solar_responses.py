"""Guarded OpenAI Responses to Solar Chat Completions adapter."""

from __future__ import annotations

import codecs
import hashlib
import json
import secrets
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

from media_bridge.backends import SecretConfigurationError, load_secret
from media_bridge.receipts import GateReceiptSigner, ReceiptValidationError
from media_bridge_gateway.contracts import (
    DownstreamError,
    DownstreamGuardError,
    GatewayResponse,
    SealedGatewayRequest,
)
from media_bridge_gateway.normalizer import digest_gateway_payload
from media_bridge_personal.credential_store import CredentialStoreError


def _usage_count(value: object) -> int:
    if value is None:
        return 0
    if not isinstance(value, (str, bytes, int, float)):
        raise TypeError("usage count must be numeric")
    return int(value)


def _contains_media(value: object) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return lowered.startswith("data:image/") or lowered.startswith("data:application/pdf")
    if isinstance(value, list):
        return any(_contains_media(item) for item in value)
    if not isinstance(value, dict):
        return False
    item = cast(dict[object, object], value)
    if isinstance(item.get("type"), str) and item["type"] in {
        "input_image", "input_file", "image_url"
    }:
        return True
    return any(_contains_media(child) for child in item.values())


def _validate_endpoint(endpoint: str, protocol: str) -> None:
    parsed = urlsplit(endpoint)
    expected_path = (
        "/v1/chat/completions" if protocol == "openai-chat-completions" else "/v1/responses"
    )
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        protocol not in {"openai-chat-completions", "openai-responses"}
        or (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback))
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.endswith(expected_path)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("text LLM endpoint is not valid for the selected protocol")


def _text_content(value: object) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
        raise DownstreamGuardError("Responses message text is empty")
    if not isinstance(value, list):
        raise DownstreamGuardError("Responses message content is unsupported")
    parts: list[str] = []
    for part in value:
        if not isinstance(part, dict) or part.get("type") not in {"input_text", "output_text"}:
            raise DownstreamGuardError("Responses message contains unsupported non-text content")
        part_text = part.get("text")
        if not isinstance(part_text, str) or not part_text.strip():
            raise DownstreamGuardError("Responses message text is empty")
        parts.append(part_text.strip())
    if not parts:
        raise DownstreamGuardError("Responses message content is empty")
    return "\n".join(parts)


def _tool_name(name: str, namespace: str | None = None) -> str:
    if namespace is None:
        return name
    if not isinstance(namespace, str) or not namespace:
        raise DownstreamGuardError("Tool namespace is malformed")
    identity = json.dumps([namespace, name], ensure_ascii=False).encode()
    return "mb_ns_" + hashlib.sha256(identity).hexdigest()[:48]


def _chat_tools(value: object) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    if not isinstance(value, list):
        raise DownstreamGuardError("Unsupported Responses tool definition")
    converted: list[dict[str, Any]] = []
    identities: dict[str, dict[str, str]] = {}

    def add(tool: object, namespace: str | None = None, description: str = "") -> None:
        if (not isinstance(tool, dict) or tool.get("type") != "function"
                or not isinstance(tool.get("name"), str) or not tool["name"]
                or not isinstance(tool.get("parameters"), dict)):
            raise DownstreamGuardError("Unsupported Responses tool definition")
        name = _tool_name(tool["name"], namespace)
        if name in identities:
            raise DownstreamGuardError("Duplicate or colliding tool name")
        identities[name] = {"name": tool["name"]}
        function = {k: tool[k] for k in ("description", "parameters", "strict") if k in tool}
        function["name"] = name
        if namespace is not None:
            identities[name]["namespace"] = namespace
            function["description"] = (
                f"{namespace}.{tool['name']}: {description}\n{tool.get('description', '')}")
        converted.append({"type": "function", "function": function})

    for tool in value:
        if isinstance(tool, dict) and tool.get("type") == "namespace":
            if (not isinstance(tool.get("name"), str) or not tool["name"]
                    or not isinstance(tool.get("tools"), list)):
                raise DownstreamGuardError("Tool namespace is malformed")
            for child in tool["tools"]:
                add(child, tool["name"], tool.get("description", ""))
        else:
            add(tool)
    return converted, identities


def _chat_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    instructions = payload.get("instructions")
    if instructions is not None:
        if not isinstance(instructions, str) or not instructions.strip():
            raise DownstreamGuardError("Responses instructions are invalid")
        messages.append({"role": "system", "content": instructions.strip()})
    input_value = payload.get("input")
    if isinstance(input_value, str):
        messages.append({"role": "user", "content": _text_content(input_value)})
    elif isinstance(input_value, list):
        for item in input_value:
            if isinstance(item, dict) and item.get("type") == "function_call":
                if not all(isinstance(item.get(k), str) and item[k]
                           for k in ("call_id", "name", "arguments")):
                    raise DownstreamGuardError("Function call is malformed")
                call = {"id": item["call_id"], "type": "function", "function": {
                    "name": _tool_name(item["name"], item.get("namespace")),
                    "arguments": item["arguments"]}}
                if messages and messages[-1].get("tool_calls"):
                    messages[-1]["tool_calls"].append(call)
                else:
                    messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
                continue
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                if not isinstance(item.get("call_id"), str) or not item["call_id"] \
                        or not isinstance(item.get("output"), str):
                    raise DownstreamGuardError("Function result is malformed")
                messages.append({"role": "tool", "tool_call_id": item["call_id"],
                                 "content": item["output"]})
                continue
            if not isinstance(item, dict) or item.get("type", "message") != "message":
                raise DownstreamGuardError("Responses input item is unsupported")
            role = item.get("role")
            if role not in {"user", "assistant", "system", "developer"}:
                raise DownstreamGuardError("Responses message role is unsupported")
            chat_role = "system" if role == "developer" else cast(str, role)
            messages.append({"role": chat_role, "content": _text_content(item.get("content"))})
    else:
        raise DownstreamGuardError("Responses input is missing or unsupported")
    if not messages:
        raise DownstreamGuardError("Responses input is empty")
    return messages


def _response_payload(
    *,
    response_id: str,
    message_id: str,
    model: str,
    text: str,
    usage: dict[str, int],
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": model,
        "output": [
            {
                "id": message_id,
                "type": "message",
                "status": status,
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": usage,
    }


def _sse_event(event_type: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {body}\n\n".encode()


class SolarResponsesDownstream:
    """Translate a sealed text-only Responses request into a Solar chat request."""

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        receipt_signer: GateReceiptSigner,
        api_key_env: str = "SOLAR_API_KEY",
        credential_loader: Callable[[], str] | None = None,
        protocol: str = "openai-chat-completions",
        provider_name: str = "Solar",
        error_prefix: str = "solar",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        max_request_bytes: int = 4 * 1024 * 1024,
        max_response_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        _validate_endpoint(endpoint, protocol)
        if (
            not model.strip()
            or timeout_seconds <= 0
            or min(max_request_bytes, max_response_bytes) < 1
        ):
            raise ValueError("Solar personal downstream configuration is invalid")
        self._endpoint = endpoint
        self._model = model
        self._receipt_signer = receipt_signer
        self._api_key_env = api_key_env
        self._credential_loader = credential_loader
        self._protocol = protocol
        self._provider_name = provider_name
        self._error_prefix = error_prefix
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def invoke(self, sealed: SealedGatewayRequest) -> GatewayResponse:
        self._verify_seal(sealed)
        if self._protocol == "openai-responses" and (
            sealed.payload.get("tools") or any(
                isinstance(item, dict) and item.get("type") in {
                    "function_call", "function_call_output"}
                for item in sealed.payload.get("input", [])
            )
        ):
            raise DownstreamGuardError("Responses upstream tool passthrough is not yet supported")
        messages = _chat_messages(sealed.payload)
        tool_identities: dict[str, dict[str, str]] = {}
        solar_payload: dict[str, Any]
        if self._protocol == "openai-chat-completions":
            solar_payload = {"model": self._model, "messages": messages,
                             "stream": sealed.payload.get("stream") is True}
            if sealed.payload.get("tools"):
                solar_payload["tools"], tool_identities = _chat_tools(sealed.payload["tools"])
            if "tool_choice" in sealed.payload:
                choice = sealed.payload["tool_choice"]
                if isinstance(choice, str) and choice in {"none", "auto", "required"}:
                    solar_payload["tool_choice"] = choice
                elif (isinstance(choice, dict) and set(choice) <= {"type", "name", "namespace"}
                      and choice.get("type") == "function"
                      and isinstance(choice.get("name"), str)
                      and _tool_name(choice["name"], choice.get("namespace")) in tool_identities):
                    solar_payload["tool_choice"] = {
                        "type": "function", "function": {
                            "name": _tool_name(choice["name"], choice.get("namespace"))}}
                else:
                    raise DownstreamGuardError("Unsupported Responses tool choice")
            if "parallel_tool_calls" in sealed.payload:
                parallel = sealed.payload["parallel_tool_calls"]
                if not isinstance(parallel, bool):
                    raise DownstreamGuardError("Parallel tool calls must be boolean")
                solar_payload["parallel_tool_calls"] = parallel
        else:
            solar_payload = {
                "model": self._model,
                "input": [
                    {
                        "type": "message",
                        "role": message["role"],
                        "content": [{"type": "input_text", "text": message["content"]}],
                    }
                    for message in messages
                ],
                "stream": False,
            }
        encoded = json.dumps(
            solar_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > self._max_request_bytes:
            raise DownstreamGuardError("Solar request exceeded the configured limit")
        try:
            secret = (
                self._credential_loader()
                if self._credential_loader is not None
                else load_secret(self._api_key_env, None)
            )
        except (SecretConfigurationError, CredentialStoreError) as error:
            raise DownstreamError(
                f"{self._error_prefix}_configuration",
                f"{self._provider_name} credentials are not configured.",
                http_status=500,
            ) from error
        try:
            request = self._client.build_request(
                "POST", self._endpoint,
                headers={
                    "Authorization": f"Bearer {secret}",
                    "Content-Type": "application/json",
                },
                content=encoded,
            )
            response = await self._client.send(request, stream=True)
        except httpx.TimeoutException as error:
            raise DownstreamError(
                f"{self._error_prefix}_timeout", f"{self._provider_name} request timed out."
            ) from error
        except httpx.RequestError as error:
            raise DownstreamError(
                f"{self._error_prefix}_transport", f"{self._provider_name} request failed."
            ) from error
        if response.status_code >= 400:
            await response.aclose()
            code = (
                f"{self._error_prefix}_authentication"
                if response.status_code in {401, 403}
                else f"{self._error_prefix}_rate_limit"
                if response.status_code == 429
                else f"{self._error_prefix}_upstream_http"
            )
            raise DownstreamError(code, f"{self._provider_name} rejected the request.")
        content_type = response.headers.get("content-type", "").partition(";")[0].strip()
        if (content_type == "text/event-stream" and solar_payload["stream"]
                and self._protocol == "openai-chat-completions"):
            response_id = f"resp_mb_{secrets.token_urlsafe(12)}"
            return GatewayResponse(
                body=b"", content_type="text/event-stream", response_id=response_id,
                status_code=200, stream=self._stream_live(response, response_id, tool_identities),
            )
        try:
            await response.aread()
        except httpx.TimeoutException as error:
            raise DownstreamError(f"{self._error_prefix}_timeout",
                                  f"{self._provider_name} request timed out.") from error
        except httpx.RequestError as error:
            raise DownstreamError(f"{self._error_prefix}_transport",
                                  f"{self._provider_name} request failed.") from error
        finally:
            await response.aclose()
        if content_type != "application/json" or len(response.content) > self._max_response_bytes:
            raise DownstreamError(
                f"{self._error_prefix}_response_invalid",
                f"{self._provider_name} returned an invalid response.",
            )
        tool_calls: list[dict[str, Any]] = []
        try:
            solar_response = response.json()
            if self._protocol == "openai-chat-completions":
                choice = solar_response["choices"][0]
                message = choice["message"]
                text = (message.get("content") or "").strip()
                calls = message.get("tool_calls", [])
                if not isinstance(calls, list):
                    raise ValueError("Invalid tool calls")
                for call in calls:
                    function = call["function"]
                    if call.get("type") != "function" or not all(
                        isinstance(v, str) and v for v in
                        (call.get("id"), function.get("name"), function.get("arguments"))
                    ):
                        raise ValueError("Invalid tool call")
                    tool_calls.append({"id": f"fc_mb_{secrets.token_urlsafe(12)}",
                                       "type": "function_call", "status": "completed",
                                       "call_id": call["id"], "name": function["name"],
                                       "arguments": function["arguments"]})
                    if function["name"] in tool_identities:
                        tool_calls[-1].update(tool_identities[function["name"]])
            else:
                text = "\n".join(
                    str(part.get("text", "")).strip()
                    for item in solar_response["output"]
                    if isinstance(item, dict)
                    for part in item.get("content", [])
                    if isinstance(part, dict) and part.get("type") == "output_text"
                ).strip()
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as error:
            raise DownstreamError(
                f"{self._error_prefix}_response_invalid",
                f"{self._provider_name} returned an invalid response.",
            ) from error
        if not text and not tool_calls:
            raise DownstreamError(
                f"{self._error_prefix}_response_invalid",
                f"{self._provider_name} returned an empty response.",
            )
        usage_source = solar_response.get("usage", {})
        try:
            if not isinstance(usage_source, dict):
                raise TypeError("usage must be an object")
            usage = {
                "input_tokens": _usage_count(
                    usage_source.get("prompt_tokens", usage_source.get("input_tokens", 0))
                ),
                "output_tokens": _usage_count(
                    usage_source.get("completion_tokens", usage_source.get("output_tokens", 0))
                ),
                "total_tokens": _usage_count(usage_source.get("total_tokens", 0)),
            }
        except (TypeError, ValueError, OverflowError) as error:
            raise DownstreamError(
                f"{self._error_prefix}_response_invalid",
                f"{self._provider_name} returned an invalid response.",
            ) from error
        response_id = f"resp_mb_{secrets.token_urlsafe(12)}"
        message_id = f"msg_mb_{secrets.token_urlsafe(12)}"
        body_payload = _response_payload(
            response_id=response_id,
            message_id=message_id,
            model=self._model,
            text=text,
            usage=usage,
        )
        if tool_calls:
            body_payload["output"] = (body_payload["output"] if text else []) + tool_calls
        if sealed.payload.get("stream") is True:
            return GatewayResponse(
                body=b"",
                content_type="text/event-stream",
                response_id=response_id,
                status_code=200,
                stream=self._stream(
                    response_id=response_id,
                    message_id=message_id,
                    text=text,
                    completed=body_payload,
                ),
            )
        return GatewayResponse(
            body=json.dumps(body_payload, ensure_ascii=False, separators=(",", ":")).encode(),
            content_type="application/json",
            response_id=response_id,
            status_code=200,
        )

    async def _stream_live(
        self, response: httpx.Response, response_id: str,
        tool_identities: dict[str, dict[str, str]],
    ) -> AsyncIterator[bytes]:
        message_id = f"msg_mb_{secrets.token_urlsafe(12)}"
        text = ""
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        buffer = ""
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        received = 0
        finished = False
        done = False
        started = False
        output: list[dict[str, Any]] = []
        calls: dict[int, tuple[int, dict[str, Any]]] = {}
        text_index = 0
        initial = _response_payload(response_id=response_id, message_id=message_id,
                                    model=self._model, text="", usage=usage)
        try:
            yield _sse_event("response.created", {"type": "response.created", "response": {
                **initial, "output": [], "status": "in_progress"}})
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > self._max_response_bytes:
                    raise ValueError("Stream exceeds configured limit")
                buffer = (buffer + decoder.decode(chunk)).replace("\r\n", "\n")
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    data = "\n".join(line[5:].lstrip(" ") for line in frame.splitlines()
                                     if line.startswith("data:"))
                    if not data:
                        continue
                    if data == "[DONE]":
                        done = True
                        break
                    event = json.loads(data)
                    if not isinstance(event, dict) or "error" in event:
                        raise ValueError("Invalid stream event")
                    if event.get("usage") is not None:
                        source = event["usage"]
                        usage = {"input_tokens": _usage_count(source.get("prompt_tokens", 0)),
                                 "output_tokens": _usage_count(source.get("completion_tokens", 0)),
                                 "total_tokens": _usage_count(source.get("total_tokens", 0))}
                    for choice in event.get("choices", []):
                        if choice.get("index", 0) != 0:
                            raise ValueError("Multiple stream choices are unsupported")
                        delta = choice.get("delta", {})
                        for fragment in delta.get("tool_calls", []):
                            index = fragment["index"]
                            if type(index) is not int or index < 0 or finished:
                                raise ValueError("Invalid tool index")
                            function = fragment["function"]
                            if index not in calls:
                                name = function.get("name")
                                if (not isinstance(name, str) or name not in tool_identities
                                        or not isinstance(fragment.get("id"), str)
                                        or not fragment["id"]):
                                    raise ValueError("Undeclared or malformed tool call")
                                call = {"id": f"fc_mb_{secrets.token_urlsafe(12)}",
                                        "type": "function_call", "status": "in_progress",
                                        "call_id": fragment["id"], "arguments": "",
                                        **tool_identities[name]}
                                calls[index] = (len(output), call)
                                output.append(call)
                                yield _sse_event("response.output_item.added", {
                                    "type": "response.output_item.added",
                                    "output_index": len(output) - 1, "item": dict(call)})
                            output_index, call = calls[index]
                            if fragment.get("id") not in {None, call["call_id"]}:
                                raise ValueError("Tool call ID changed")
                            if function.get("name") is not None and tool_identities.get(
                                function["name"]
                            ) != {k: call[k] for k in ("name", "namespace") if k in call}:
                                raise ValueError("Tool call name changed")
                            arguments = function.get("arguments", "")
                            if not isinstance(arguments, str):
                                raise ValueError("Invalid arguments delta")
                            call["arguments"] += arguments
                            if arguments:
                                yield _sse_event("response.function_call_arguments.delta", {
                                    "type": "response.function_call_arguments.delta",
                                    "output_index": output_index, "item_id": call["id"],
                                    "delta": arguments})
                        content = delta.get("content")
                        if content is not None:
                            if not isinstance(content, str) or finished:
                                raise ValueError("Invalid text delta")
                            if not started:
                                started = True
                                text_index = len(output)
                                output.append({**initial["output"][0], "content": []})
                                yield _sse_event("response.output_item.added", {
                                    "type": "response.output_item.added",
                                    "output_index": text_index,
                                    "item": {**initial["output"][0], "status": "in_progress",
                                             "content": []}})
                                yield _sse_event("response.content_part.added", {
                                    "type": "response.content_part.added",
                                    "output_index": text_index,
                                    "item_id": message_id, "content_index": 0,
                                    "part": {"type": "output_text", "text": "", "annotations": []}})
                            text += content
                            yield _sse_event("response.output_text.delta", {
                                "type": "response.output_text.delta", "output_index": text_index,
                                "item_id": message_id, "content_index": 0, "delta": content})
                        reason = choice.get("finish_reason")
                        if reason is not None:
                            if reason not in {"stop", "tool_calls"}:
                                raise ValueError("Stream did not finish normally")
                            finished = True
                if done:
                    break
            if not done or not finished or (not text and not calls):
                raise ValueError("Incomplete upstream stream")
            for index, item in enumerate(output):
                item["status"] = "completed"
                if item["type"] == "function_call":
                    if not isinstance(json.loads(item["arguments"]), dict):
                        raise ValueError("Tool arguments must be a JSON object")
                    yield _sse_event("response.function_call_arguments.done", {
                        "type": "response.function_call_arguments.done", "output_index": index,
                        "item_id": item["id"], "arguments": item["arguments"]})
                else:
                    part = {"type": "output_text", "text": text, "annotations": []}
                    item["content"] = [part]
                    yield _sse_event("response.output_text.done", {
                        "type": "response.output_text.done", "output_index": index,
                        "item_id": item["id"], "content_index": 0, "text": text})
                    yield _sse_event("response.content_part.done", {
                        "type": "response.content_part.done", "output_index": index,
                        "item_id": item["id"], "content_index": 0, "part": part})
                yield _sse_event("response.output_item.done", {
                    "type": "response.output_item.done", "output_index": index, "item": item})
            yield _sse_event("response.completed", {"type": "response.completed", "response": {
                **initial, "output": output, "usage": usage}})
            yield b"data: [DONE]\n\n"
        except (ValueError, TypeError, KeyError, AttributeError, httpx.HTTPError) as error:
            safe = DownstreamError(f"{self._error_prefix}_stream_failed",
                                   f"{self._provider_name} stream failed.")
            yield _sse_event("response.failed", {"type": "response.failed", "response": {
                **initial, "status": "failed", "output": [],
                "error": {"code": safe.code, "message": safe.safe_message}}})
            raise safe from error
        finally:
            await response.aclose()

    async def _stream(
        self,
        *,
        response_id: str,
        message_id: str,
        text: str,
        completed: dict[str, Any],
    ) -> AsyncIterator[bytes]:
        calls = [item for item in completed["output"] if item["type"] == "function_call"]
        if calls:
            messages = [item for item in completed["output"] if item["type"] == "message"]
            if messages:
                async for event in self._stream(
                    response_id=response_id, message_id=message_id, text=text,
                    completed={**completed, "output": messages},
                ):
                    if not event.startswith((b"event: response.completed", b"data: [DONE]")):
                        yield event
            else:
                yield _sse_event("response.created", {"type": "response.created", "response": {
                    **completed, "status": "in_progress", "output": []}})
            for index, call in enumerate(calls, start=len(messages)):
                yield _sse_event("response.output_item.added", {
                    "type": "response.output_item.added", "output_index": index,
                    "item": {**call, "status": "in_progress", "arguments": ""}})
                yield _sse_event("response.function_call_arguments.delta", {
                    "type": "response.function_call_arguments.delta", "output_index": index,
                    "item_id": call["id"], "delta": call["arguments"]})
                yield _sse_event("response.function_call_arguments.done", {
                    "type": "response.function_call_arguments.done", "output_index": index,
                    "item_id": call["id"], "arguments": call["arguments"]})
                yield _sse_event("response.output_item.done", {
                    "type": "response.output_item.done", "output_index": index, "item": call})
            yield _sse_event("response.completed", {
                "type": "response.completed", "response": completed})
            yield b"data: [DONE]\n\n"
            return
        created = {**completed, "status": "in_progress", "output": []}
        item = {
            "id": message_id,
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [],
        }
        part = {"type": "output_text", "text": "", "annotations": []}
        yield _sse_event("response.created", {"type": "response.created", "response": created})
        yield _sse_event(
            "response.output_item.added",
            {"type": "response.output_item.added", "output_index": 0, "item": item},
        )
        yield _sse_event(
            "response.content_part.added",
            {
                "type": "response.content_part.added",
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "part": part,
            },
        )
        yield _sse_event(
            "response.output_text.delta",
            {
                "type": "response.output_text.delta",
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "delta": text,
            },
        )
        yield _sse_event(
            "response.output_text.done",
            {
                "type": "response.output_text.done",
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "text": text,
            },
        )
        completed_part = {"type": "output_text", "text": text, "annotations": []}
        yield _sse_event(
            "response.content_part.done",
            {
                "type": "response.content_part.done",
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "part": completed_part,
            },
        )
        completed_item = {
            **item,
            "status": "completed",
            "content": [completed_part],
        }
        yield _sse_event(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": completed_item,
            },
        )
        yield _sse_event(
            "response.completed",
            {"type": "response.completed", "response": completed},
        )
        yield b"data: [DONE]\n\n"

    def _verify_seal(self, sealed: SealedGatewayRequest) -> None:
        try:
            computed = digest_gateway_payload(
                {"payload": sealed.payload, "request_nonce": sealed.request_nonce}
            )
        except (TypeError, ValueError, OverflowError) as error:
            raise DownstreamGuardError("Solar payload digest could not be computed") from error
        if not secrets.compare_digest(computed, sealed.output_digest):
            raise DownstreamGuardError("Solar payload digest does not match the receipt")
        try:
            self._receipt_signer.verify(sealed.receipt, expected=sealed.binding)
        except ReceiptValidationError as error:
            raise DownstreamGuardError("Solar payload has no valid receipt") from error
        if sealed.capability != "non_vision" or sealed.action not in {"passthrough", "converted"}:
            raise DownstreamGuardError("Solar payload capability boundary is invalid")
        if sealed.payload.get("model") != sealed.target_id or sealed.target_id != self._model:
            raise DownstreamGuardError("Solar target does not match the sealed target")
        if _contains_media(sealed.payload):
            raise DownstreamGuardError("Solar payload contains media")
