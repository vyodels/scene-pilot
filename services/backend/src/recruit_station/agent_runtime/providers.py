from __future__ import annotations

import json
from http.client import HTTPException
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from .types import (
    AbortSignal,
    LLMInvocationResult,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    TokenUsage,
    ToolSchema,
    ToolUse,
)


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_kind: str = "provider_error",
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_kind = error_kind
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


Transport = Callable[..., Any]


def _signal_aborted(abort_signal: AbortSignal | None) -> bool:
    return bool(abort_signal is not None and abort_signal.aborted)


def _aborted_invocation_result(request: LLMRequest) -> LLMInvocationResult:
    return LLMInvocationResult(
        events=[],
        response=LLMResponse(
            id="",
            request_id=request.id,
            invocation_id=request.invocation_id,
            stop_reason="aborted",
            raw={"aborted": True, "abort_reason": request.abort_signal.reason if request.abort_signal else None},
        ),
    )


@dataclass(slots=True)
class ProviderConfig:
    provider_name: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int = 30
    extra: dict[str, Any] = field(default_factory=dict)

    def has_http_credentials(self) -> bool:
        return bool(self.base_url and self.api_key)

    def resolved_timeout_seconds(self) -> int:
        return max(int(self.timeout_seconds), 1)


@dataclass(slots=True)
class ProviderRegistry:
    providers: dict[str, "LLMProvider"] = field(default_factory=dict)
    fallback_order: list[str] = field(default_factory=list)

    def register(self, provider: "LLMProvider") -> None:
        self.providers[provider.provider_name] = provider
        if provider.provider_name not in self.fallback_order:
            self.fallback_order.append(provider.provider_name)

    def get(self, provider_name: str) -> "LLMProvider":
        try:
            return self.providers[provider_name]
        except KeyError as exc:
            raise ProviderError(f"Unknown provider: {provider_name}") from exc


@dataclass(slots=True)
class UnavailableProvider:
    reason: str
    provider_name: str = "unavailable"

    def invoke(self, request: LLMRequest) -> LLMInvocationResult:
        raise ProviderError(self.reason)


@dataclass(slots=True)
class OpenAIProvider:
    config: ProviderConfig
    transport: Transport | None = None

    @property
    def provider_name(self) -> str:
        return self.config.provider_name

    def invoke(self, request: LLMRequest) -> LLMInvocationResult:
        if _signal_aborted(request.abort_signal):
            return _aborted_invocation_result(request)
        payload = self._build_payload(request)
        url = urljoin((self.config.base_url or "").rstrip("/") + "/", "responses")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        }
        if _signal_aborted(request.abort_signal):
            return _aborted_invocation_result(request)
        raw = _invoke_transport(
            url,
            lambda: (
                self.transport(url, payload, headers, self.config.resolved_timeout_seconds())
                if self.transport is not None
                else self._post(url, payload, headers, request.abort_signal)
            ),
        )
        if _signal_aborted(request.abort_signal):
            return _aborted_invocation_result(request)
        return _parse_openai_result(raw, request)

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self.config.model,
            "input": _openai_input_payload(request.messages),
            "stream": True,
        }
        instructions = _join_nonempty(
            [request.system_prompt, *[_message_text(message) for message in request.messages if message.role == "system"]]
        )
        if instructions:
            payload["instructions"] = instructions
        if request.tools:
            payload["tools"] = [_openai_tool_payload(tool) for tool in request.tools]
        if request.max_tokens is not None:
            payload["max_output_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.tool_choice is not None:
            payload["tool_choice"] = _openai_tool_choice(request.tool_choice)
        if request.reasoning is not None:
            payload["reasoning"] = dict(request.reasoning)
        if request.text_format is not None:
            payload["text"] = {"format": dict(request.text_format)}
            _ensure_openai_json_object_input_hint(payload, request.text_format)
        if request.parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = request.parallel_tool_calls
        if request.max_tool_calls is not None:
            payload["max_tool_calls"] = request.max_tool_calls
        if request.previous_response_id is not None:
            payload["previous_response_id"] = request.previous_response_id
        if request.store is not None:
            payload["store"] = request.store
        if request.truncation is not None:
            payload["truncation"] = request.truncation
        payload.update(dict(self.config.extra.get("openai_payload_overrides") or {}))
        payload.update(dict(request.openai_payload_overrides or {}))
        return payload

    def _post(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        abort_signal: AbortSignal | None = None,
    ) -> Any:
        if not self.config.has_http_credentials():
            raise ProviderError("OpenAIProvider has no transport configured")
        return _post_json(
            url,
            payload,
            headers=headers,
            timeout_seconds=self.config.resolved_timeout_seconds(),
            abort_signal=abort_signal,
        )


@dataclass(slots=True)
class AnthropicProvider:
    config: ProviderConfig
    transport: Transport | None = None

    @property
    def provider_name(self) -> str:
        return self.config.provider_name

    def invoke(self, request: LLMRequest) -> LLMInvocationResult:
        if _signal_aborted(request.abort_signal):
            return _aborted_invocation_result(request)
        payload = self._build_payload(request)
        base_url = (self.config.base_url or "").rstrip("/") + "/"
        endpoint = "v1/messages" if not urlparse(base_url).path.strip("/") else "messages"
        url = urljoin(base_url, endpoint)
        headers = {
            "X-api-key": str(self.config.api_key),
            "Anthropic-version": str(self.config.extra.get("anthropic_version", "2023-06-01")),
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        }
        if _signal_aborted(request.abort_signal):
            return _aborted_invocation_result(request)
        raw = _invoke_transport(
            url,
            lambda: (
                self.transport(url, payload, headers, self.config.resolved_timeout_seconds())
                if self.transport is not None
                else self._post(url, payload, headers, request.abort_signal)
            ),
        )
        if _signal_aborted(request.abort_signal):
            return _aborted_invocation_result(request)
        return _parse_anthropic_result(raw, request)

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        system = _join_nonempty(
            [request.system_prompt, *[_message_text(message) for message in request.messages if message.role == "system"]]
        )
        payload: dict[str, Any] = {
            "model": request.model or self.config.model,
            "messages": [
                _anthropic_message_payload(message) for message in request.messages if message.role != "system"
            ],
            "max_tokens": request.max_tokens
            if request.max_tokens is not None
            else int(self.config.extra.get("default_max_tokens", 1024)),
            "stream": True,
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [_anthropic_tool_payload(tool) for tool in request.tools]
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop_sequences:
            payload["stop_sequences"] = list(request.stop_sequences)
        if request.tool_choice is not None:
            payload["tool_choice"] = _anthropic_tool_choice(request.tool_choice)
        if request.thinking is not None:
            payload["thinking"] = dict(request.thinking)
        payload.update(dict(self.config.extra.get("anthropic_payload_overrides") or {}))
        payload.update(dict(request.anthropic_payload_overrides or {}))
        return payload

    def _post(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        abort_signal: AbortSignal | None = None,
    ) -> Any:
        if not self.config.has_http_credentials():
            raise ProviderError("AnthropicProvider has no transport configured")
        return _post_json(
            url,
            payload,
            headers=headers,
            timeout_seconds=self.config.resolved_timeout_seconds(),
            abort_signal=abort_signal,
        )


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout_seconds: int,
    abort_signal: AbortSignal | None = None,
) -> Any:
    if _signal_aborted(abort_signal):
        return []
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with _open_url(request, url=url, timeout_seconds=timeout_seconds) as response:  # type: ignore[arg-type]
            if "text/event-stream" in _response_content_type(response):
                return list(_iter_sse_events(response, abort_signal=abort_signal))
            return _read_json_response(response)
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        message = error_body.strip() or exc.reason or f"HTTP {exc.code}"
        raise ProviderError(
            f"HTTP {exc.code} calling {url}: {message}",
            status_code=int(exc.code),
            error_kind="provider_http_error",
            retryable=_is_retryable_provider_http_status(int(exc.code)),
            retry_after_seconds=_retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None),
        ) from exc
    except URLError as exc:
        raise ProviderError(
            f"Transport error calling {url}: {exc.reason}",
            error_kind="provider_transport_error",
            retryable=True,
        ) from exc
    except (HTTPException, TimeoutError, OSError) as exc:
        raise _transport_error(url, exc) from exc
    except RuntimeError as exc:
        if _is_transient_transport_message(str(exc)):
            raise _transport_error(url, exc) from exc
        raise


def _invoke_transport(url: str, invoke: Callable[[], Any]) -> Any:
    try:
        return invoke()
    except ProviderError:
        raise
    except (HTTPException, TimeoutError, OSError) as exc:
        raise _transport_error(url, exc) from exc
    except RuntimeError as exc:
        if _is_transient_transport_message(str(exc)):
            raise _transport_error(url, exc) from exc
        raise


def _transport_error(url: str, exc: BaseException) -> ProviderError:
    return ProviderError(
        f"Transport error calling {url}: {exc}",
        error_kind="provider_transport_error",
        retryable=True,
    )


def _is_transient_transport_message(message: str) -> bool:
    lowered = message.strip().lower()
    if not lowered:
        return False
    return any(
        marker in lowered
        for marker in (
            "unexpected eof",
            " eof",
            "end of file",
            "connection reset",
            "connection aborted",
            "connection closed",
            "remote end closed",
            "server disconnected",
            "incompleteread",
            "incomplete read",
            "broken pipe",
            "timed out",
        )
    )


def _open_url(request: Request, *, url: str, timeout_seconds: int) -> Any:
    if _should_bypass_proxies(url):
        opener = build_opener(ProxyHandler({}))
        return opener.open(request, timeout=timeout_seconds)
    return urlopen(request, timeout=timeout_seconds)


def _is_retryable_provider_http_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or status_code >= 500


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value.strip())
    except ValueError:
        return None
    return max(parsed, 0.0)


def _should_bypass_proxies(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").strip().lower()
    if not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _response_content_type(response: Any) -> str:
    headers = getattr(response, "headers", None)
    if headers is not None:
        get_content_type = getattr(headers, "get_content_type", None)
        if callable(get_content_type):
            try:
                return str(get_content_type() or "").strip().lower()
            except Exception:
                pass
        get_header = getattr(headers, "get", None)
        if callable(get_header):
            value = get_header("Content-Type", "")
            if value:
                return str(value).strip().lower()
    getheader = getattr(response, "getheader", None)
    if callable(getheader):
        value = getheader("Content-Type")
        if value:
            return str(value).strip().lower()
    return ""


def _read_json_response(response: Any) -> dict[str, Any]:
    body = response.read()
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ProviderError("Invalid JSON response from provider") from exc
    if not isinstance(payload, dict):
        raise ProviderError("Provider response must be a JSON object")
    return payload


def _iter_sse_events(response: Any, *, abort_signal: AbortSignal | None = None) -> Iterable[dict[str, Any]]:
    event_name = ""
    data_lines: list[str] = []
    while True:
        if _signal_aborted(abort_signal):
            break
        line = response.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line)
        stripped = text.strip()
        if not stripped:
            if data_lines:
                yield _decode_sse_event(event_name, "\n".join(data_lines))
                event_name = ""
                data_lines = []
            continue
        if stripped.startswith(":"):
            continue
        if stripped.startswith("event:"):
            event_name = stripped[6:].strip()
        elif stripped.startswith("data:"):
            data_lines.append(stripped[5:].lstrip())
    if data_lines:
        yield _decode_sse_event(event_name, "\n".join(data_lines))


def _decode_sse_event(event_name: str, data: str) -> dict[str, Any]:
    if data == "[DONE]":
        return {"type": event_name or "done", "data": "[DONE]"}
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "Invalid JSON event in provider stream response",
            error_kind="provider_stream_error",
            retryable=True,
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderError("Provider stream event must be a JSON object")
    payload.setdefault("type", event_name)
    return payload


def _parse_openai_result(raw: Any, request: LLMRequest) -> LLMInvocationResult:
    if isinstance(raw, dict):
        return _openai_response_from_final_payload(raw, request, [])
    events = raw or []
    neutral_events: list[LLMStreamEvent] = []
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_states: dict[int | str, dict[str, Any]] = {}
    final_payload: dict[str, Any] = {}
    stop_reason = "stop"
    usage = TokenUsage()

    for raw_event in events:
        if _signal_aborted(request.abort_signal):
            break
        event = _coerce_event(raw_event)
        event_type = str(event.get("type") or "")
        if event.get("data") == "[DONE]":
            continue
        error_payload = event.get("error")
        if event_type in {"error", "response.failed"} or isinstance(error_payload, dict):
            raise _provider_stream_error(event)
        if event_type == "response.output_text.delta":
            delta = str(event.get("delta") or "")
            text_parts.append(delta)
            neutral_events.append(LLMStreamEvent(type="assistant_delta", data={"delta": delta}, raw=event))
        elif "reasoning" in event_type and event_type.endswith(".delta"):
            delta = str(event.get("delta") or event.get("text") or "")
            reasoning_parts.append(delta)
            neutral_events.append(LLMStreamEvent(type="reasoning_delta", data={"delta": delta}, raw=event))
        elif event_type == "response.output_item.added":
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            if item.get("type") == "function_call":
                state = _openai_tool_state(tool_states, event, item)
                neutral_events.append(
                    LLMStreamEvent(
                        type="tool_use_delta",
                        data={"id": state["id"], "name": state["name"], "delta": ""},
                        raw=event,
                    )
                )
        elif event_type == "response.function_call_arguments.delta":
            state = _openai_tool_state(tool_states, event, None)
            delta = str(event.get("delta") or "")
            state["arguments_parts"].append(delta)
            neutral_events.append(
                LLMStreamEvent(
                    type="tool_use_delta",
                    data={"id": state["id"], "name": state["name"], "delta": delta},
                    raw=event,
                )
            )
        elif event_type in {"response.function_call_arguments.done", "response.output_item.done"}:
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            if item.get("type") in {None, "function_call"} and (
                item.get("arguments") is not None or item.get("name") is not None
            ):
                state = _openai_tool_state(tool_states, event, item)
                if isinstance(item.get("arguments"), str):
                    state["arguments_parts"] = [str(item["arguments"])]
                if isinstance(item.get("name"), str):
                    state["name"] = item["name"]
                neutral_events.append(
                    LLMStreamEvent(
                        type="tool_use_completed",
                        data={
                            "id": state["id"],
                            "name": state["name"],
                            "input": _json_object("".join(state["arguments_parts"])),
                        },
                        raw=event,
                    )
                )
        elif event_type in {"response.completed", "response.done"}:
            final_payload = event.get("response") if isinstance(event.get("response"), dict) else event
            usage = _usage_openai(final_payload.get("usage") if isinstance(final_payload, dict) else None)
            if isinstance(final_payload, dict):
                stop_reason = str(final_payload.get("status") or final_payload.get("stop_reason") or stop_reason)

    tool_uses = [_tool_use_from_openai_state(state) for _, state in sorted(tool_states.items(), key=lambda pair: str(pair[0]))]
    if final_payload:
        final_result = _openai_response_from_final_payload(final_payload, request, neutral_events)
        assistant_text = "".join(text_parts)
        if assistant_text:
            if final_result.response.assistant_message is None:
                final_result.response.assistant_message = LLMMessage(
                    role="assistant",
                    content=assistant_text,
                    tool_uses=tool_uses,
                )
            else:
                final_result.response.assistant_message.content = assistant_text
        if reasoning_parts:
            final_result.response.reasoning = "".join(reasoning_parts)
        if tool_uses and not final_result.response.tool_uses:
            final_result.response.tool_uses = tool_uses
            if final_result.response.assistant_message is not None:
                final_result.response.assistant_message.tool_uses = tool_uses
        return final_result
    assistant_text = "".join(text_parts)
    response = LLMResponse(
        id="",
        request_id=request.id,
        invocation_id=request.invocation_id,
        assistant_message=LLMMessage(role="assistant", content=assistant_text, tool_uses=tool_uses)
        if assistant_text or tool_uses
        else None,
        reasoning="".join(reasoning_parts) or None,
        tool_uses=tool_uses,
        stop_reason=stop_reason,
        usage=usage,
        raw={},
    )
    return LLMInvocationResult(events=neutral_events, response=response)


def _parse_anthropic_result(raw: Any, request: LLMRequest) -> LLMInvocationResult:
    if isinstance(raw, dict):
        return _anthropic_response_from_final_payload(raw, request, [])
    neutral_events: list[LLMStreamEvent] = []
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    blocks: dict[int, dict[str, Any]] = {}
    stop_reason = "stop"
    usage_payload: dict[str, Any] = {}
    response_id = ""

    for raw_event in raw or []:
        if _signal_aborted(request.abort_signal):
            break
        event = _coerce_event(raw_event)
        event_type = str(event.get("type") or "")
        if event_type == "error":
            raise _provider_stream_error(event)
        if event_type == "message_start":
            message = event.get("message") if isinstance(event.get("message"), dict) else {}
            response_id = str(message.get("id") or "")
            if isinstance(message.get("usage"), dict):
                usage_payload.update(message["usage"])
        elif event_type == "content_block_start":
            index = int(event.get("index", 0) or 0)
            block = event.get("content_block") if isinstance(event.get("content_block"), dict) else {}
            blocks[index] = {
                "type": block.get("type"),
                "id": block.get("id") or "",
                "name": block.get("name") or "",
                "input_parts": [],
                "input": block.get("input") if isinstance(block.get("input"), dict) else {},
            }
            if block.get("type") == "tool_use":
                neutral_events.append(
                    LLMStreamEvent(
                        type="tool_use_delta",
                        data={"id": blocks[index]["id"], "name": blocks[index]["name"], "delta": ""},
                        raw=event,
                    )
                )
        elif event_type == "content_block_delta":
            index = int(event.get("index", 0) or 0)
            delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
            if delta.get("type") == "text_delta":
                text = str(delta.get("text") or "")
                text_parts.append(text)
                neutral_events.append(LLMStreamEvent(type="assistant_delta", data={"delta": text}, raw=event))
            elif delta.get("type") == "thinking_delta":
                text = str(delta.get("thinking") or "")
                reasoning_parts.append(text)
                neutral_events.append(LLMStreamEvent(type="reasoning_delta", data={"delta": text}, raw=event))
            elif delta.get("type") == "input_json_delta":
                partial = str(delta.get("partial_json") or "")
                block = blocks.setdefault(index, {"type": "tool_use", "id": "", "name": "", "input_parts": [], "input": {}})
                block["input_parts"].append(partial)
                neutral_events.append(
                    LLMStreamEvent(
                        type="tool_use_delta",
                        data={"id": block["id"], "name": block["name"], "delta": partial},
                        raw=event,
                    )
                )
        elif event_type == "content_block_stop":
            index = int(event.get("index", 0) or 0)
            block = blocks.get(index)
            if block and block.get("type") == "tool_use":
                input_payload = _json_object("".join(block["input_parts"])) if block["input_parts"] else dict(block["input"])
                block["input"] = input_payload
                neutral_events.append(
                    LLMStreamEvent(
                        type="tool_use_completed",
                        data={"id": block["id"], "name": block["name"], "input": input_payload},
                        raw=event,
                    )
                )
        elif event_type == "message_delta":
            delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
            stop_reason = str(delta.get("stop_reason") or stop_reason)
            if isinstance(event.get("usage"), dict):
                usage_payload.update(event["usage"])

    tool_uses = []
    for _, block in sorted(blocks.items()):
        if block.get("type") != "tool_use":
            continue
        input_payload = _json_object("".join(block["input_parts"])) if block["input_parts"] else dict(block["input"])
        tool_uses.append(
            ToolUse(id=str(block["id"]), name=str(block["name"]), input=input_payload, raw=dict(block))
        )
    assistant_text = "".join(text_parts)
    response = LLMResponse(
        id=response_id,
        request_id=request.id,
        invocation_id=request.invocation_id,
        assistant_message=LLMMessage(role="assistant", content=assistant_text, tool_uses=tool_uses)
        if assistant_text or tool_uses
        else None,
        reasoning="".join(reasoning_parts) or None,
        tool_uses=tool_uses,
        stop_reason=stop_reason,
        usage=_usage_anthropic(usage_payload),
        raw={},
    )
    return LLMInvocationResult(events=neutral_events, response=response)


def _openai_response_from_final_payload(
    payload: dict[str, Any], request: LLMRequest, events: list[LLMStreamEvent]
) -> LLMInvocationResult:
    text_parts: list[str] = []
    tool_uses: list[ToolUse] = []
    for item in list(payload.get("output") or []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for content in list(item.get("content") or []):
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    text_parts.append(str(content.get("text") or ""))
        elif item.get("type") == "function_call":
            tool_uses.append(
                ToolUse(
                    id=str(item.get("call_id") or item.get("id") or ""),
                    name=str(item.get("name") or ""),
                    input=_json_object(str(item.get("arguments") or "")),
                    raw=dict(item),
                )
            )
    text = "".join(text_parts)
    response = LLMResponse(
        id=str(payload.get("id") or ""),
        request_id=request.id,
        invocation_id=request.invocation_id,
        assistant_message=LLMMessage(role="assistant", content=text, tool_uses=tool_uses) if text or tool_uses else None,
        tool_uses=tool_uses,
        stop_reason=str(payload.get("status") or payload.get("stop_reason") or "stop"),
        usage=_usage_openai(payload.get("usage") if isinstance(payload.get("usage"), dict) else None),
        raw=payload,
    )
    return LLMInvocationResult(events=events, response=response)


def _anthropic_response_from_final_payload(
    payload: dict[str, Any], request: LLMRequest, events: list[LLMStreamEvent]
) -> LLMInvocationResult:
    text_parts: list[str] = []
    tool_uses: list[ToolUse] = []
    for block in list(payload.get("content") or []):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_use":
            tool_uses.append(
                ToolUse(
                    id=str(block.get("id") or ""),
                    name=str(block.get("name") or ""),
                    input=dict(block.get("input") or {}),
                    raw=dict(block),
                )
            )
    text = "".join(text_parts)
    response = LLMResponse(
        id=str(payload.get("id") or ""),
        request_id=request.id,
        invocation_id=request.invocation_id,
        assistant_message=LLMMessage(role="assistant", content=text, tool_uses=tool_uses) if text or tool_uses else None,
        tool_uses=tool_uses,
        stop_reason=str(payload.get("stop_reason") or "stop"),
        usage=_usage_anthropic(payload.get("usage") if isinstance(payload.get("usage"), dict) else None),
        raw=payload,
    )
    return LLMInvocationResult(events=events, response=response)


def _openai_tool_state(
    states: dict[int | str, dict[str, Any]], event: dict[str, Any], item: dict[str, Any] | None
) -> dict[str, Any]:
    key: int | str = event.get("output_index") if event.get("output_index") is not None else event.get("item_id", "")
    if item and item.get("id"):
        key = str(item["id"])
    state = states.setdefault(key, {"id": "", "name": "", "arguments_parts": []})
    if item:
        state["id"] = str(item.get("call_id") or item.get("id") or state["id"])
        state["name"] = str(item.get("name") or state["name"])
    if event.get("item_id") and not state["id"]:
        state["id"] = str(event["item_id"])
    return state


def _tool_use_from_openai_state(state: dict[str, Any]) -> ToolUse:
    return ToolUse(
        id=str(state.get("id") or ""),
        name=str(state.get("name") or ""),
        input=_json_object("".join(state.get("arguments_parts") or [])),
        raw=dict(state),
    )


def _openai_message_payload(message: LLMMessage) -> dict[str, Any]:
    if message.role == "tool":
        return {"type": "function_call_output", "call_id": message.tool_use_id or message.name or "", "output": _content_text(message.content)}
    return {"role": message.role, "content": message.content}


def _ensure_openai_json_object_input_hint(payload: dict[str, Any], text_format: dict[str, Any]) -> None:
    if str(text_format.get("type") or "").strip().lower() != "json_object":
        return
    input_payload = payload.get("input")
    if not isinstance(input_payload, list):
        return
    if _openai_user_input_contains_json_keyword(input_payload):
        return
    input_payload.insert(
        0,
        {
            "role": "user",
            "content": "Provider formatting requirement: final response must be a valid json object.",
        },
    )


def _openai_user_input_contains_json_keyword(input_payload: list[dict[str, Any]]) -> bool:
    for item in input_payload:
        if str(item.get("role") or "").lower() != "user":
            continue
        if "json" in json.dumps(item.get("content"), ensure_ascii=False, default=str).lower():
            return True
    return False


def _openai_input_payload(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        text = _message_text(message)
        if message.role != "assistant" or text or not message.tool_uses:
            payload.append(_openai_message_payload(message))
        if message.role == "assistant":
            payload.extend(
                {
                    "type": "function_call",
                    "call_id": tool.id,
                    "name": tool.name,
                    "arguments": json.dumps(tool.input, ensure_ascii=False, sort_keys=True),
                }
                for tool in message.tool_uses
            )
    return payload


def _anthropic_message_payload(message: LLMMessage) -> dict[str, Any]:
    if message.role == "tool":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_use_id or "",
                    "content": _content_text(message.content),
                    "is_error": bool(message.metadata.get("is_error", False)),
                }
            ],
        }
    content: Any = message.content
    if message.tool_uses:
        blocks: list[dict[str, Any]] = []
        text = _message_text(message)
        if text:
            blocks.append({"type": "text", "text": text})
        blocks.extend(
            {"type": "tool_use", "id": tool.id, "name": tool.name, "input": dict(tool.input)}
            for tool in message.tool_uses
        )
        content = blocks
    return {"role": message.role, "content": content}


def _openai_tool_payload(tool: ToolSchema) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": dict(tool.input_schema),
    }


def _anthropic_tool_payload(tool: ToolSchema) -> dict[str, Any]:
    return {"name": tool.name, "description": tool.description, "input_schema": dict(tool.input_schema)}


def _openai_tool_choice(choice: str | dict[str, Any]) -> str | dict[str, Any]:
    if isinstance(choice, str):
        return choice
    return dict(choice)


def _anthropic_tool_choice(choice: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(choice, dict):
        return dict(choice)
    if choice == "required":
        return {"type": "any"}
    if choice in {"auto", "any", "none"}:
        return {"type": choice}
    return {"type": "tool", "name": choice}


def _usage_openai(payload: dict[str, Any] | None) -> TokenUsage:
    if not payload:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=int(payload.get("input_tokens", payload.get("prompt_tokens", 0)) or 0),
        completion_tokens=int(payload.get("output_tokens", payload.get("completion_tokens", 0)) or 0),
        total_tokens=int(payload.get("total_tokens", 0) or 0)
        or int(payload.get("input_tokens", payload.get("prompt_tokens", 0)) or 0)
        + int(payload.get("output_tokens", payload.get("completion_tokens", 0)) or 0),
    )


def _usage_anthropic(payload: dict[str, Any] | None) -> TokenUsage:
    return TokenUsage.anthropic(payload)


def _coerce_event(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    raise ProviderError("Provider stream event must be a JSON object")


def _provider_error_message(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "Unknown provider stream error")
    return str(event.get("message") or event.get("type") or "Unknown provider stream error")


def _provider_stream_error(event: dict[str, Any]) -> ProviderError:
    message = _provider_error_message(event)
    return ProviderError(
        message,
        error_kind="provider_stream_error",
        retryable=_is_transient_transport_message(message),
    )


def _json_object(text: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError("Invalid tool call arguments JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderError("Tool call arguments must decode to a JSON object")
    return payload


def _message_text(message: LLMMessage) -> str:
    return _content_text(message.content)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if "text" in block:
                    parts.append(str(block.get("text") or ""))
                elif "content" in block:
                    parts.append(str(block.get("content") or ""))
            else:
                parts.append(str(block))
        return "".join(parts)
    return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)


def _join_nonempty(values: Iterable[str | None]) -> str:
    return "\n\n".join(value for value in values if value)
