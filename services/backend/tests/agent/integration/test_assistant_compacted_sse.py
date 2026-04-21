from __future__ import annotations

from pathlib import Path

from recruit_agent.runtime.models import LLMResponse
from recruit_agent.runtime.providers import ScriptedProvider
from recruit_agent.runtime.tools import ToolRegistry, register_core_tools

from ._helpers import build_assistant_client


def test_assistant_stream_emits_compacted_event_when_history_is_compacted(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(content="reply one", finish_reason="stop"),
            LLMResponse(content="reply two", finish_reason="stop"),
            LLMResponse(content="reply three", finish_reason="stop"),
        ],
    )
    tools = ToolRegistry()
    register_core_tools(tools)
    client, _agent, _session_factory = build_assistant_client(tmp_path, provider=provider, tools=tools)

    with client:
        conversation_id = client.post("/api/assistant/conversations", json={"user_id": "user-1"}).json()["conversation_id"]
        client.post(f"/api/assistant/conversations/{conversation_id}/turn", json={"message": "hello one"})
        client.post(f"/api/assistant/conversations/{conversation_id}/turn", json={"message": "hello two"})
        third = client.post(f"/api/assistant/conversations/{conversation_id}/turn", json={"message": "hello three"})

    assert "event: compacted" in third.text
    assert "event: turn.completed" in third.text
