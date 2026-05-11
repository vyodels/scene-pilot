from __future__ import annotations

from pathlib import Path

from recruit_agent.agent_runtime.models import LLMResponse, ToolCall
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.runtime.tools import ToolDefinition, ToolRegistry, register_core_tools

from ._helpers import build_assistant_client


def test_functional_closure_assistant_uses_shared_kernel_and_recovery(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(tool_calls=[ToolCall(id="tool-1", name="outbound.send", arguments={"text": "hello"})], finish_reason="tool_calls"),
            LLMResponse(content="sent", finish_reason="stop"),
        ],
    )
    tools = ToolRegistry()
    register_core_tools(tools)
    tools.register(
        ToolDefinition(
            name="outbound.send",
            description="Send outbound message.",
            parameters={"type": "object", "additionalProperties": True},
            handler=lambda arguments: {"sent": arguments["text"]},
            category="plugin",
            external_target=True,
            resource_target_kind="candidate",
        )
    )
    client, agent, _session_factory = build_assistant_client(tmp_path, provider=provider, tools=tools)
    with client:
        conversation_id = client.post("/api/assistant/conversations", json={"user_id": "user-1"}).json()["conversation_id"]
        initial = client.post(f"/api/assistant/conversations/{conversation_id}/turn", json={"message": "send"}).text
        assert "event: turn.waiting_human" in initial
        confirmed = client.post(f"/api/assistant/conversations/{conversation_id}/confirm").json()
        assert confirmed["confirmed"] is True
        assert confirmed["status"] == "completed"
        assert agent.kernel is not None
        assert not hasattr(agent, "provider")
