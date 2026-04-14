from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock
import unittest
from urllib.error import URLError


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from recruit_agent.core.settings import AppSettings, load_settings
from recruit_agent.runtime.models import LLMResponse, Message
from recruit_agent.runtime.providers import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderRegistry,
    ProviderError,
    ScriptedProvider,
)


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class ProviderTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in [
            "RECRUIT_AGENT_PROVIDER_CONFIG__OPENAI_MODEL",
            "RECRUIT_AGENT_PROVIDER_CONFIG__OPENAI_BASE_URL",
            "RECRUIT_AGENT_PROVIDER_CONFIG__OPENAI_API_KEY",
            "RECRUIT_AGENT_PROVIDER_CONFIG__OPENAI_TIMEOUT_SECONDS",
            "RECRUIT_AGENT_PROVIDER_CONFIG__ANTHROPIC_MODEL",
            "RECRUIT_AGENT_PROVIDER_CONFIG__ANTHROPIC_BASE_URL",
            "RECRUIT_AGENT_PROVIDER_CONFIG__ANTHROPIC_API_KEY",
            "RECRUIT_AGENT_PROVIDER_CONFIG__ANTHROPIC_TIMEOUT_SECONDS",
            "RECRUIT_AGENT_PROVIDER_CONFIG__BOSS_ACCOUNT",
            "RECRUIT_AGENT_PROVIDER_CONFIG__COOLDOWN_DAYS",
        ]:
            os.environ.pop(key, None)
        load_settings.cache_clear()

    def test_parse_openai_payload(self) -> None:
        payload = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "done",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "echo",
                                    "arguments": "{\"value\": \"hello\"}",
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
        response = LLMResponse.from_payload(payload)
        self.assertEqual(response.content, "done")
        self.assertEqual(response.tool_calls[0].name, "echo")
        self.assertEqual(response.tool_calls[0].arguments["value"], "hello")
        self.assertEqual(response.usage.total_tokens, 12)

    def test_parse_anthropic_payload(self) -> None:
        payload = {
            "stop_reason": "end_turn",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "tool_use", "id": "t1", "name": "echo", "input": {"value": "world"}},
            ],
        }
        response = LLMResponse.from_payload(payload)
        self.assertEqual(response.content, "hello")
        self.assertEqual(response.tool_calls[0].name, "echo")
        self.assertEqual(response.tool_calls[0].arguments["value"], "world")

    def test_settings_parse_provider_config_from_env(self) -> None:
        os.environ["RECRUIT_AGENT_PROVIDER_CONFIG__OPENAI_MODEL"] = "gpt-4.1-mini"
        os.environ["RECRUIT_AGENT_PROVIDER_CONFIG__OPENAI_BASE_URL"] = "https://example.com/openai"
        os.environ["RECRUIT_AGENT_PROVIDER_CONFIG__OPENAI_API_KEY"] = "test-openai-key"
        os.environ["RECRUIT_AGENT_PROVIDER_CONFIG__OPENAI_TIMEOUT_SECONDS"] = "11"
        os.environ["RECRUIT_AGENT_PROVIDER_CONFIG__ANTHROPIC_MODEL"] = "claude-3.7"
        os.environ["RECRUIT_AGENT_PROVIDER_CONFIG__ANTHROPIC_BASE_URL"] = "https://example.com/anthropic"
        os.environ["RECRUIT_AGENT_PROVIDER_CONFIG__ANTHROPIC_API_KEY"] = "test-anthropic-key"
        os.environ["RECRUIT_AGENT_PROVIDER_CONFIG__ANTHROPIC_TIMEOUT_SECONDS"] = "17"
        os.environ["RECRUIT_AGENT_PROVIDER_CONFIG__BOSS_ACCOUNT"] = "boss-02"
        os.environ["RECRUIT_AGENT_PROVIDER_CONFIG__COOLDOWN_DAYS"] = "21"

        settings = AppSettings()
        runtime_settings = settings.provider_runtime_settings()

        self.assertEqual(runtime_settings.openai_model, "gpt-4.1-mini")
        self.assertEqual(runtime_settings.openai_base_url, "https://example.com/openai")
        self.assertEqual(runtime_settings.openai_api_key, "test-openai-key")
        self.assertEqual(runtime_settings.openai_timeout_seconds, 11)
        self.assertEqual(runtime_settings.anthropic_model, "claude-3.7")
        self.assertEqual(runtime_settings.anthropic_base_url, "https://example.com/anthropic")
        self.assertEqual(runtime_settings.anthropic_api_key, "test-anthropic-key")
        self.assertEqual(runtime_settings.anthropic_timeout_seconds, 17)
        self.assertEqual(runtime_settings.site_account, "boss-02")
        self.assertEqual(runtime_settings.cooldown_days, 21)

    def test_openai_default_transport_posts_expected_payload(self) -> None:
        provider = OpenAICompatibleProvider(
            ProviderConfig(
                provider_name="openai_compatible",
                model="gpt-4.1-mini",
                base_url="https://api.openai.com/v1",
                api_key="test-openai-key",
                timeout_seconds=13,
            )
        )
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeHTTPResponse(
                {
                    "choices": [{"finish_reason": "stop", "message": {"content": "done"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                }
            )

        with mock.patch("recruit_agent.runtime.providers.urlopen", side_effect=fake_urlopen):
            response = provider.generate(
                [Message(role="system", content="follow policy"), Message(role="user", content="hello")],
                max_tokens=256,
                temperature=0.3,
            )

        request = captured["request"]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(captured["timeout"], 13)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-openai-key")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "gpt-4.1-mini")
        self.assertEqual(payload["messages"][1]["content"], "hello")
        self.assertEqual(payload["max_tokens"], 256)
        self.assertEqual(payload["temperature"], 0.3)
        self.assertEqual(response.content, "done")
        self.assertEqual(response.usage.total_tokens, 12)

    def test_anthropic_default_transport_posts_expected_payload(self) -> None:
        provider = AnthropicProvider(
            ProviderConfig(
                provider_name="anthropic",
                model="claude-sonnet-4",
                base_url="https://api.anthropic.com",
                api_key="test-anthropic-key",
                timeout_seconds=19,
                extra={"anthropic_version": "2024-02-29"},
            )
        )
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeHTTPResponse(
                {
                    "content": [{"type": "text", "text": "approved"}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
                }
            )

        with mock.patch("recruit_agent.runtime.providers.urlopen", side_effect=fake_urlopen):
            response = provider.generate(
                [
                    Message(role="system", content="follow policy"),
                    Message(role="user", content="screen candidate"),
                    Message(role="assistant", content="ack"),
                ],
                temperature=0.2,
            )

        request = captured["request"]
        self.assertEqual(request.full_url, "https://api.anthropic.com/messages")
        self.assertEqual(captured["timeout"], 19)
        self.assertEqual(request.get_header("X-api-key"), "test-anthropic-key")
        self.assertEqual(request.get_header("Anthropic-version"), "2024-02-29")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "claude-sonnet-4")
        self.assertEqual(payload["system"], "follow policy")
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(payload["messages"][0]["content"], "screen candidate")
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["max_tokens"], 1024)
        self.assertEqual(response.content, "approved")
        self.assertEqual(response.usage.total_tokens, 9)

    def test_registry_fallback(self) -> None:
        registry = ProviderRegistry()
        registry.register(ScriptedProvider("openai", []))
        registry.register(ScriptedProvider("anthropic", [LLMResponse(content="ok")]))

        response = registry.generate([Message(role="user", content="hi")], preferred_provider="openai")
        self.assertEqual(response.content, "ok")

    def test_transport_absence_raises(self) -> None:
        provider = OpenAICompatibleProvider(ProviderConfig(provider_name="openai", model="gpt"))
        with self.assertRaises(ProviderError):
            provider.generate([Message(role="user", content="hi")])

    def test_transport_network_failure_is_wrapped(self) -> None:
        provider = OpenAICompatibleProvider(
            ProviderConfig(
                provider_name="openai_compatible",
                model="gpt-4.1-mini",
                base_url="https://api.openai.com/v1",
                api_key="test-openai-key",
            )
        )

        with mock.patch("recruit_agent.runtime.providers.urlopen", side_effect=URLError("down")):
            with self.assertRaisesRegex(ProviderError, "Transport error calling"):
                provider.generate([Message(role="user", content="hi")])


if __name__ == "__main__":
    unittest.main()
