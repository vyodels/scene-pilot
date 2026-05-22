from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from recruit_station.agent_runtime.providers import AnthropicProvider, OpenAIProvider, ProviderConfig, ProviderError, _post_json
from recruit_station.agent_runtime.types import LLMMessage, LLMRequest, ToolSchema, ToolUse


def test_post_json_maps_retryable_http_errors(monkeypatch) -> None:
    def raise_http_error(*args, **kwargs):
        raise HTTPError(
            url="https://api.test/v1/responses",
            code=500,
            msg="server error",
            hdrs={},
            fp=BytesIO(b'{"error":{"message":"temporary outage"}}'),
        )

    monkeypatch.setattr("recruit_station.agent_runtime.providers._open_url", raise_http_error)

    with pytest.raises(ProviderError) as raised:
        _post_json("https://api.test/v1/responses", {}, headers={}, timeout_seconds=1)

    assert raised.value.status_code == 500
    assert raised.value.error_kind == "provider_http_error"
    assert raised.value.retryable is True


def test_post_json_maps_terminal_http_errors(monkeypatch) -> None:
    def raise_http_error(*args, **kwargs):
        raise HTTPError(
            url="https://api.test/v1/responses",
            code=401,
            msg="unauthorized",
            hdrs={},
            fp=BytesIO(b"unauthorized"),
        )

    monkeypatch.setattr("recruit_station.agent_runtime.providers._open_url", raise_http_error)

    with pytest.raises(ProviderError) as raised:
        _post_json("https://api.test/v1/responses", {}, headers={}, timeout_seconds=1)

    assert raised.value.status_code == 401
    assert raised.value.error_kind == "provider_http_error"
    assert raised.value.retryable is False


def test_post_json_maps_transport_error_as_retryable(monkeypatch) -> None:
    def raise_url_error(*args, **kwargs):
        raise URLError("connection reset")

    monkeypatch.setattr("recruit_station.agent_runtime.providers._open_url", raise_url_error)

    with pytest.raises(ProviderError) as raised:
        _post_json("https://api.test/v1/responses", {}, headers={}, timeout_seconds=1)

    assert raised.value.error_kind == "provider_transport_error"
    assert raised.value.retryable is True


def test_post_json_maps_stream_unexpected_eof_as_retryable_transport_error(monkeypatch) -> None:
    class BrokenSSEResponse:
        headers = {"Content-Type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def readline(self):
            raise RuntimeError("unexpected EOF")

    monkeypatch.setattr("recruit_station.agent_runtime.providers._open_url", lambda *args, **kwargs: BrokenSSEResponse())

    with pytest.raises(ProviderError) as raised:
        _post_json("https://api.test/v1/responses", {}, headers={}, timeout_seconds=1)

    assert raised.value.error_kind == "provider_transport_error"
    assert raised.value.retryable is True


def test_openai_stream_transient_failure_event_is_retryable() -> None:
    provider = OpenAIProvider(
        ProviderConfig(provider_name="openai", model="gpt", base_url="https://api.openai.com/v1", api_key="key"),
        transport=lambda *args, **kwargs: [
            {"type": "response.failed", "error": {"message": "Post https://api.test/responses: unexpected EOF"}}
        ],
    )

    with pytest.raises(ProviderError) as raised:
        provider.invoke(_request())

    assert raised.value.error_kind == "provider_stream_error"
    assert raised.value.retryable is True


def test_openai_responses_stream_maps_text_tool_and_usage() -> None:
    events = [
        {"type": "response.output_text.delta", "response_id": "resp-1", "delta": "hello"},
        {"type": "response.output_item.added", "response_id": "resp-1", "item": {"type": "function_call", "id": "call-1", "name": "upsert_candidate"}},
        {"type": "response.function_call_arguments.delta", "response_id": "resp-1", "item_id": "call-1", "delta": "{\"name\":\"Ada\"}"},
        {"type": "response.function_call_arguments.done", "response_id": "resp-1", "item": {"id": "call-1", "name": "upsert_candidate", "arguments": "{\"name\":\"Ada\"}"}},
        {"type": "response.completed", "response": {"id": "resp-1", "status": "completed", "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}}},
    ]

    def transport(url, payload, headers, timeout):
        assert url.endswith("/responses")
        assert payload["stream"] is True
        assert payload["tools"][0]["name"] == "upsert_candidate"
        return events

    provider = OpenAIProvider(
        ProviderConfig(provider_name="openai", model="gpt", base_url="https://api.openai.com/v1", api_key="key"),
        transport=transport,
    )
    result = provider.invoke(_request())

    assert result.response.assistant_message.content == "hello"
    assert result.response.tool_uses[0].name == "upsert_candidate"
    assert result.response.tool_uses[0].input["name"] == "Ada"
    assert result.response.usage.total_tokens == 5
    assert any(event.type == "assistant_delta" for event in result.events)
    assert any(event.type == "tool_use_completed" for event in result.events)


def test_anthropic_messages_stream_maps_text_tool_and_usage() -> None:
    events = [
        {"type": "message_start", "message": {"id": "msg-1", "usage": {"input_tokens": 2, "output_tokens": 0}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hello"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu-1", "name": "upsert_candidate"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"name\":\"Ada\"}"}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"input_tokens": 2, "output_tokens": 4}},
        {"type": "message_stop"},
    ]

    def transport(url, payload, headers, timeout):
        assert url.endswith("/messages")
        assert payload["stream"] is True
        assert payload["tools"][0]["name"] == "upsert_candidate"
        return events

    provider = AnthropicProvider(
        ProviderConfig(provider_name="anthropic", model="claude", base_url="https://api.anthropic.com", api_key="key"),
        transport=transport,
    )
    result = provider.invoke(_request())

    assert result.response.assistant_message.content == "hello"
    assert result.response.tool_uses[0].id == "toolu-1"
    assert result.response.tool_uses[0].input["name"] == "Ada"
    assert result.response.usage.prompt_tokens == 2
    assert result.response.usage.completion_tokens == 4


def test_provider_options_are_mapped_only_when_supported() -> None:
    request = LLMRequest(
        id="req-1",
        turn_id="turn-1",
        invocation_id="llm-1",
        messages=[LLMMessage(role="user", content="hello")],
        tools=[
            ToolSchema(
                name="upsert_candidate",
                description="Create or update a candidate.",
                input_schema={"type": "object"},
            )
        ],
        max_tokens=123,
        temperature=0.2,
        top_p=0.9,
        stop_sequences=["END"],
        tool_choice="required",
        thinking={"type": "enabled", "budget_tokens": 1024},
        reasoning={"effort": "high"},
        text_format={"type": "json_object"},
        parallel_tool_calls=False,
        max_tool_calls=3,
        previous_response_id="resp-prev",
        store=False,
        truncation="auto",
        openai_payload_overrides={"service_tier": "flex"},
        anthropic_payload_overrides={"metadata": {"provider": "request-anthropic"}},
        metadata={"ignored_by_providers": True},
    )
    captured: dict[str, dict[str, object]] = {}

    def openai_transport(url, payload, headers, timeout):
        captured["openai"] = dict(payload)
        return {"id": "resp-openai", "output": []}

    def anthropic_transport(url, payload, headers, timeout):
        captured["anthropic"] = dict(payload)
        return {"id": "msg-anthropic", "content": []}

    OpenAIProvider(
        ProviderConfig(
            provider_name="openai",
            model="gpt",
            base_url="https://api.openai.com/v1",
            api_key="key",
            extra={
                "payload_overrides": {"thinking": {"type": "enabled"}},
                "openai_payload_overrides": {"service_tier": "default"},
            },
        ),
        transport=openai_transport,
    ).invoke(request)
    AnthropicProvider(
        ProviderConfig(
            provider_name="anthropic",
            model="claude",
            base_url="https://api.anthropic.com",
            api_key="key",
            extra={
                "payload_overrides": {"reasoning": {"effort": "high"}},
                "anthropic_payload_overrides": {"metadata": {"provider": "anthropic"}},
            },
        ),
        transport=anthropic_transport,
    ).invoke(request)

    openai_payload = captured["openai"]
    assert openai_payload["max_output_tokens"] == 123
    assert openai_payload["temperature"] == 0.2
    assert openai_payload["top_p"] == 0.9
    assert openai_payload["tool_choice"] == "required"
    assert openai_payload["reasoning"] == {"effort": "high"}
    assert openai_payload["text"] == {"format": {"type": "json_object"}}
    assert "json object" in str(openai_payload["input"][0]["content"])
    assert openai_payload["parallel_tool_calls"] is False
    assert openai_payload["max_tool_calls"] == 3
    assert openai_payload["previous_response_id"] == "resp-prev"
    assert openai_payload["store"] is False
    assert openai_payload["truncation"] == "auto"
    assert openai_payload["service_tier"] == "flex"
    assert "thinking" not in openai_payload
    assert "stop_sequences" not in openai_payload
    assert "metadata" not in openai_payload

    anthropic_payload = captured["anthropic"]
    assert anthropic_payload["max_tokens"] == 123
    assert anthropic_payload["temperature"] == 0.2
    assert anthropic_payload["top_p"] == 0.9
    assert anthropic_payload["stop_sequences"] == ["END"]
    assert anthropic_payload["tool_choice"] == {"type": "any"}
    assert anthropic_payload["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert anthropic_payload["metadata"] == {"provider": "request-anthropic"}
    assert "reasoning" not in anthropic_payload
    assert "text" not in anthropic_payload
    assert "parallel_tool_calls" not in anthropic_payload
    assert "max_tool_calls" not in anthropic_payload
    assert "previous_response_id" not in anthropic_payload
    assert "store" not in anthropic_payload
    assert "truncation" not in anthropic_payload


def test_openai_responses_history_flattens_assistant_tool_calls() -> None:
    captured: dict[str, object] = {}

    def transport(url, payload, headers, timeout):
        captured.update(payload)
        return {"id": "resp-openai", "output": []}

    provider = OpenAIProvider(
        ProviderConfig(provider_name="openai", model="gpt", base_url="https://api.openai.com/v1", api_key="key"),
        transport=transport,
    )
    provider.invoke(
        LLMRequest(
            id="req-1",
            turn_id="turn-1",
            invocation_id="llm-1",
            messages=[
                LLMMessage(role="user", content="create candidate"),
                LLMMessage(
                    role="assistant",
                    content="",
                    tool_uses=[
                        ToolUse(
                            id="call-1",
                            name="upsert_candidate",
                            input={"name": "Ada"},
                        )
                    ],
                ),
                LLMMessage(role="tool", name="upsert_candidate", tool_use_id="call-1", content={"ok": True}),
            ],
        )
    )

    input_payload = captured["input"]
    assert input_payload[0] == {"role": "user", "content": "create candidate"}
    assert input_payload[1] == {
        "type": "function_call",
        "call_id": "call-1",
        "name": "upsert_candidate",
        "arguments": '{"name": "Ada"}',
    }
    assert input_payload[2] == {"type": "function_call_output", "call_id": "call-1", "output": '{"ok": true}'}
    assert "tool_calls" not in input_payload[1]


def _request() -> LLMRequest:
    return LLMRequest(
        id="req-1",
        turn_id="turn-1",
        invocation_id="llm-1",
        messages=[LLMMessage(role="user", content="hello")],
        tools=[
            ToolSchema(
                name="upsert_candidate",
                description="Create or update a candidate.",
                input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            )
        ],
    )
