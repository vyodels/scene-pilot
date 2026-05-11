from __future__ import annotations

from recruit_agent.agent_runtime.providers import AnthropicProvider, OpenAIProvider, ProviderConfig
from recruit_agent.agent_runtime.types import LLMMessage, LLMRequest
from recruit_agent.agent_runtime.providers import ProviderRegistry, UnavailableProvider


def test_runtime_provider_registry_uses_new_invoke_contract() -> None:
    registry = ProviderRegistry()
    provider = OpenAIProvider(
        ProviderConfig(provider_name="openai", model="gpt", base_url="https://api.openai.com/v1", api_key="key"),
        transport=lambda _url, _payload, _headers, _timeout: [{"type": "response.completed", "response": {"id": "resp", "output": []}}],
    )
    registry.register(provider)

    assert registry.get("openai") is provider


def test_unavailable_provider_raises_on_invoke() -> None:
    provider = UnavailableProvider(reason="missing key")
    request = LLMRequest(id="req", turn_id="turn", invocation_id="llm", messages=[LLMMessage(role="user", content="hi")])

    try:
        provider.invoke(request)
    except Exception as exc:
        assert "missing key" in str(exc)
    else:
        raise AssertionError("UnavailableProvider should fail")


def test_provider_names_are_neutral() -> None:
    openai = OpenAIProvider(ProviderConfig(provider_name="openai", model="gpt", base_url="https://api.openai.com/v1", api_key="key"))
    anthropic = AnthropicProvider(ProviderConfig(provider_name="anthropic", model="claude", base_url="https://api.anthropic.com", api_key="key"))

    assert openai.provider_name == "openai"
    assert anthropic.provider_name == "anthropic"
