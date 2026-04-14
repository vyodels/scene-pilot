from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .models import LLMResponse, Message


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
    ) -> LLMResponse:
        if not self.responses:
            raise ProviderError(f"{self.provider_name} has no scripted responses left")
        response = self.responses.pop(0)
        if response.usage.total_tokens == 0 and self.default_usage_total:
            response.usage.total_tokens = self.default_usage_total
        return response


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
            "Accept": "application/json",
        }

        def _transport(payload: dict[str, Any]) -> dict[str, Any]:
            return _post_json(url, payload, headers=headers, timeout_seconds=self.config.resolved_timeout_seconds())

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
                )
            except Exception as exc:  # pragma: no cover - fallback path
                last_error = exc
        raise ProviderError("All providers failed") from last_error


def _post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str], timeout_seconds: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # type: ignore[arg-type]
            return _read_json_response(response)
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        message = error_body.strip() or exc.reason or f"HTTP {exc.code}"
        raise ProviderError(f"HTTP {exc.code} calling {url}: {message}") from exc
    except URLError as exc:
        raise ProviderError(f"Transport error calling {url}: {exc.reason}") from exc


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
