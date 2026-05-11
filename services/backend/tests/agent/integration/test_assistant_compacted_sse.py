from __future__ import annotations

from pathlib import Path

from agent_runtime.fixtures import LLMResponse
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.capabilities.tools import ToolRegistry, register_core_tools

from ._helpers import build_assistant_client


def test_assistant_stream_uses_runtime_output_events_when_history_is_compacted(tmp_path: Path) -> None:
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

    assert "event: compacted" not in third.text
    assert "event: turn_completed" in third.text


def test_assistant_compacts_model_visible_history(tmp_path: Path) -> None:
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
    client, agent, _session_factory = build_assistant_client(tmp_path, provider=provider, tools=tools)
    agent.max_history_messages = 4

    with client:
        conversation_id = client.post("/api/assistant/conversations", json={"user_id": "user-1"}).json()["conversation_id"]
        client.post(f"/api/assistant/conversations/{conversation_id}/turn", json={"message": "hello one"})
        client.post(f"/api/assistant/conversations/{conversation_id}/turn", json={"message": "hello two"})
        client.post(f"/api/assistant/conversations/{conversation_id}/turn", json={"message": "hello three"})

    third_request = provider.captured_requests[2]
    assert len(third_request.messages) == 4
    assert third_request.messages[0].role == "system"
    assert third_request.messages[0].metadata["kind"] == "context_compaction_summary"
    assert "hello one" in str(third_request.messages[0].content)
    assert third_request.messages[-1].content == "hello three"
