from __future__ import annotations

from pathlib import Path

from recruit_agent.runtime.models import LLMResponse, ToolCall
from recruit_agent.runtime.providers import ScriptedProvider
from recruit_agent.runtime.tools import ToolDefinition, ToolRegistry, register_core_tools

from ._helpers import build_assistant_client


def test_assistant_confirm_creates_recovery_turn(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="tool-1", name="outbound.send", arguments={"text": "hello"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="sent", finish_reason="stop"),
        ],
    )
    tools = ToolRegistry()
    register_core_tools(tools)
    tools.register(
        ToolDefinition(
            name="outbound.send",
            description="Send an outbound message.",
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
        initial = client.post(
            f"/api/assistant/conversations/{conversation_id}/turn",
            json={"message": "Send a greeting"},
        )
        assert initial.status_code == 200
        assert "event: turn.waiting_human" in initial.text

        confirmed = client.post(f"/api/assistant/conversations/{conversation_id}/confirm").json()
        assert confirmed["confirmed"] is True
        assert confirmed["status"] == "completed"
        assert confirmed["recovery_turn_id"]

        turns = agent.session_store.list_turns(conversation_id)
        assert [turn.role for turn in turns] == ["user", "assistant", "assistant"]
        assert turns[1].status == "waiting_human"
        assert turns[2].turn_id == confirmed["recovery_turn_id"]
        assert turns[2].status == "completed"
        assert turns[2].turn_metadata["recovery_of_turn_id"] == turns[1].turn_id
