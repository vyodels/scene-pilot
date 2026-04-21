# mypy: ignore-errors
from __future__ import annotations

import json
from ipaddress import ip_address
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from .models import CancellationToken, LLMResponse, Message


class ProviderError(RuntimeError):
    pass


class LLMProvider(Protocol):
    provider_name: str

    def generate(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> LLMResponse: ...


Transport = Callable[[dict[str, Any]], dict[str, Any]]


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
class ScriptedProvider:
    provider_name: str
    responses: list[LLMResponse]
    default_usage_total: int = 0

    def generate(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> LLMResponse:
        if not self.responses:
            raise ProviderError(f"{self.provider_name} has no scripted responses left")
        response = self.responses.pop(0)
        if response.usage.total_tokens == 0 and self.default_usage_total:
            response.usage.total_tokens = self.default_usage_total
        if cancel_token is not None and cancel_token.cancelled:
            raise ProviderError(cancel_token.reason or "provider generation cancelled")
        return response


@dataclass(slots=True)
class UnavailableProvider:
    reason: str
    provider_name: str = "unavailable"

    def generate(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> LLMResponse:
        raise ProviderError(self.reason)


@dataclass(slots=True)
class OpenAICompatibleProvider:
    config: ProviderConfig
    transport: Transport | None = None

    @property
    def provider_name(self) -> str:
        return self.config.provider_name

    def generate(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> LLMResponse:
        if self.transport is None:
            if self.config.has_http_credentials():
                self.transport = self._build_default_transport()
            else:
                raise ProviderError("OpenAI-compatible provider has no transport configured")

        payload = self._build_payload(messages, tools=tools, task=task, max_tokens=max_tokens, temperature=temperature)
        raw = self.transport(payload)
        return LLMResponse.from_payload(raw)

    def _build_payload(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [message.to_dict() for message in messages],
        }
        if tools is not None:
            payload["tools"] = tools
        if task is not None:
            payload["task"] = task
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        return payload

    def _build_default_transport(self) -> Transport:
        if not self.config.has_http_credentials():
            raise ProviderError("OpenAI-compatible provider has no transport configured")

        base_url = self.config.base_url or ""
        api_key = self.config.api_key or ""
        url = urljoin(base_url.rstrip("/") + "/", "chat/completions")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        def _transport(payload: dict[str, Any]) -> dict[str, Any]:
            stream_payload = dict(payload)
            stream_payload["stream"] = True
            stream_options = dict(stream_payload.get("stream_options") or {})
            stream_options.setdefault("include_usage", True)
            stream_payload["stream_options"] = stream_options
            return _post_json(
                url,
                stream_payload,
                headers=headers,
                timeout_seconds=self.config.resolved_timeout_seconds(),
                stream_mode="openai_chat_completions",
            )

        return _transport


@dataclass(slots=True)
class AnthropicProvider:
    config: ProviderConfig
    transport: Transport | None = None

    @property
    def provider_name(self) -> str:
        return self.config.provider_name

    def generate(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> LLMResponse:
        if self.transport is None:
            if self.config.has_http_credentials():
                self.transport = self._build_default_transport()
            else:
                raise ProviderError("Anthropic provider has no transport configured")

        payload = self._build_payload(messages, tools=tools, task=task, max_tokens=max_tokens, temperature=temperature)
        raw = self.transport(payload)
        return LLMResponse.from_payload(raw)

    def _build_payload(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        system_messages = [message.content for message in messages if message.role == "system" and message.content]
        conversation_messages = [message.to_dict() for message in messages if message.role != "system"]
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": conversation_messages,
            "system": "\n\n".join(system_messages),
            "max_tokens": max_tokens if max_tokens is not None else int(self.config.extra.get("default_max_tokens", 1024)),
        }
        if tools is not None:
            payload["tools"] = tools
        if task is not None:
            payload["task"] = task
        if temperature is not None:
            payload["temperature"] = temperature
        return payload

    def _build_default_transport(self) -> Transport:
        if not self.config.has_http_credentials():
            raise ProviderError("Anthropic provider has no transport configured")

        base_url = self.config.base_url or ""
        api_key = self.config.api_key or ""
        url = urljoin(base_url.rstrip("/") + "/", "messages")
        headers = {
            "x-api-key": api_key,
            "anthropic-version": str(self.config.extra.get("anthropic_version", "2023-06-01")),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        def _transport(payload: dict[str, Any]) -> dict[str, Any]:
            return _post_json(url, payload, headers=headers, timeout_seconds=self.config.resolved_timeout_seconds())

        return _transport


@dataclass(slots=True)
class ProviderRegistry:
    providers: dict[str, LLMProvider] = field(default_factory=dict)
    fallback_order: list[str] = field(default_factory=list)

    def register(self, provider: LLMProvider) -> None:
        self.providers[provider.provider_name] = provider
        if provider.provider_name not in self.fallback_order:
            self.fallback_order.append(provider.provider_name)

    def get(self, provider_name: str) -> LLMProvider:
        try:
            return self.providers[provider_name]
        except KeyError as exc:
            raise ProviderError(f"Unknown provider: {provider_name}") from exc

    def generate(
        self,
        messages: list[Message],
        *,
        preferred_provider: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> LLMResponse:
        ordered = [preferred_provider] if preferred_provider else []
        ordered.extend(name for name in self.fallback_order if name not in ordered)
        if not ordered:
            raise ProviderError("No providers registered")

        last_error: Exception | None = None
        for provider_name in ordered:
            provider = self.providers.get(provider_name)
            if provider is None:
                continue
            try:
                return provider.generate(
                    messages,
                    tools=tools,
                    task=task,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    cancel_token=cancel_token,
                )
            except Exception as exc:  # pragma: no cover - fallback path
                last_error = exc
        raise ProviderError("All providers failed") from last_error


@dataclass(slots=True)
class ProviderRegistryAdapter:
    registry: ProviderRegistry
    preferred_provider: str | None = None
    provider_name: str = "provider_registry"

    def generate(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> LLMResponse:
        return self.registry.generate(
            messages,
            preferred_provider=self.preferred_provider,
            tools=tools,
            task=task,
            max_tokens=max_tokens,
            temperature=temperature,
            cancel_token=cancel_token,
        )


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout_seconds: int,
    stream_mode: str | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with _open_url(request, url=url, timeout_seconds=timeout_seconds) as response:  # type: ignore[arg-type]
            return _read_provider_response(response, stream_mode=stream_mode)
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        message = error_body.strip() or exc.reason or f"HTTP {exc.code}"
        raise ProviderError(f"HTTP {exc.code} calling {url}: {message}") from exc
    except URLError as exc:
        raise ProviderError(f"Transport error calling {url}: {exc.reason}") from exc


def _open_url(request: Request, *, url: str, timeout_seconds: int) -> Any:
    if _should_bypass_proxies(url):
        opener = build_opener(ProxyHandler({}))
        return opener.open(request, timeout=timeout_seconds)
    return urlopen(request, timeout=timeout_seconds)


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


def _read_json_response(response: Any) -> dict[str, Any]:
    body = response.read()
    if isinstance(body, bytes):
        text = body.decode("utf-8")
    else:
        text = str(body)
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ProviderError("Invalid JSON response from provider") from exc
    if not isinstance(payload, dict):
        raise ProviderError("Provider response must be a JSON object")
    return payload


def _read_provider_response(response: Any, *, stream_mode: str | None = None) -> dict[str, Any]:
    if stream_mode == "openai_chat_completions" and "text/event-stream" in _response_content_type(response):
        return _read_openai_chat_completion_stream(response)
    return _read_json_response(response)


def _response_content_type(response: Any) -> str:
    headers = getattr(response, "headers", None)
    if headers is not None:
        get_content_type = getattr(headers, "get_content_type", None)
        if callable(get_content_type):
            try:
                return str(get_content_type() or "").strip().lower()
            except Exception:  # pragma: no cover - defensive fallback
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


def _read_openai_chat_completion_stream(response: Any) -> dict[str, Any]:
    usage_payload: dict[str, Any] = {}
    choices: dict[int, dict[str, Any]] = {}

    for event_data in _iter_sse_data_events(response):
        if event_data == "[DONE]":
            break
        try:
            payload = json.loads(event_data)
        except json.JSONDecodeError as exc:
            raise ProviderError("Invalid JSON event in provider stream response") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Provider stream event must be a JSON object")
        error_payload = payload.get("error")
        if isinstance(error_payload, dict):
            message = error_payload.get("message") or error_payload.get("type") or "Unknown provider stream error"
            raise ProviderError(str(message))
        if isinstance(payload.get("usage"), dict):
            usage_payload = dict(payload["usage"])
        for raw_choice in list(payload.get("choices") or []):
            if not isinstance(raw_choice, dict):
                continue
            choice_index = int(raw_choice.get("index", 0) or 0)
            state = choices.setdefault(
                choice_index,
                {
                    "index": choice_index,
                    "finish_reason": "stop",
                    "message_role": "assistant",
                    "content_parts": [],
                    "tool_calls": {},
                },
            )
            delta = raw_choice.get("delta") or raw_choice.get("message") or {}
            if not isinstance(delta, dict):
                delta = {}
            role = delta.get("role")
            if isinstance(role, str) and role:
                state["message_role"] = role
            content = delta.get("content")
            if isinstance(content, str):
                state["content_parts"].append(content)
            elif content is not None:
                state["content_parts"].append(json.dumps(content, ensure_ascii=False))
            raw_tool_calls = delta.get("tool_calls")
            if isinstance(raw_tool_calls, list):
                _merge_openai_stream_tool_calls(state["tool_calls"], raw_tool_calls)
            finish_reason = raw_choice.get("finish_reason")
            if finish_reason is not None:
                state["finish_reason"] = str(finish_reason)

    if not choices:
        raise ProviderError("Provider stream ended without any completion choices")

    aggregated_choices: list[dict[str, Any]] = []
    for choice_index in sorted(choices):
        state = choices[choice_index]
        message: dict[str, Any] = {
            "role": state["message_role"],
            "content": "".join(state["content_parts"]),
        }
        tool_calls = _finalize_openai_stream_tool_calls(state["tool_calls"])
        if tool_calls:
            message["tool_calls"] = tool_calls
        aggregated_choices.append(
            {
                "index": choice_index,
                "finish_reason": state["finish_reason"],
                "message": message,
            }
        )

    return {
        "choices": aggregated_choices,
        "usage": usage_payload,
    }


def _iter_sse_data_events(response: Any) -> list[str]:
    events: list[str] = []
    buffer: list[str] = []

    while True:
        line = response.readline()
        if not line:
            break
        if isinstance(line, bytes):
            text = line.decode("utf-8", errors="replace")
        else:
            text = str(line)
        stripped = text.strip()
        if not stripped:
            if buffer:
                events.append("\n".join(buffer))
                buffer = []
            continue
        if stripped.startswith(":"):
            continue
        if stripped.startswith("data:"):
            buffer.append(stripped[5:].lstrip())

    if buffer:
        events.append("\n".join(buffer))
    return events


def _merge_openai_stream_tool_calls(target: dict[int, dict[str, Any]], raw_tool_calls: list[Any]) -> None:
    for position, raw_tool_call in enumerate(raw_tool_calls):
        if not isinstance(raw_tool_call, dict):
            continue
        tool_call_index = int(raw_tool_call.get("index", position) or 0)
        state = target.setdefault(
            tool_call_index,
            {
                "id": "",
                "type": "function",
                "function_name": "",
                "arguments_parts": [],
            },
        )
        tool_call_id = raw_tool_call.get("id")
        if isinstance(tool_call_id, str) and tool_call_id:
            state["id"] = tool_call_id
        tool_call_type = raw_tool_call.get("type")
        if isinstance(tool_call_type, str) and tool_call_type:
            state["type"] = tool_call_type
        function_payload = raw_tool_call.get("function")
        if isinstance(function_payload, dict):
            function_name = function_payload.get("name")
            if isinstance(function_name, str) and function_name:
                state["function_name"] = function_name
            arguments = function_payload.get("arguments")
            if isinstance(arguments, str):
                state["arguments_parts"].append(arguments)
            elif arguments is not None:
                state["arguments_parts"].append(json.dumps(arguments, ensure_ascii=False))


def _finalize_openai_stream_tool_calls(tool_call_states: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for tool_call_index in sorted(tool_call_states):
        state = tool_call_states[tool_call_index]
        payloads.append(
            {
                "id": state["id"],
                "type": state["type"],
                "function": {
                    "name": state["function_name"],
                    "arguments": "".join(state["arguments_parts"]),
                },
            }
        )
    return payloads
