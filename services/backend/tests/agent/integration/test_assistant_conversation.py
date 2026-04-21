from __future__ import annotations

from pathlib import Path

from recruit_agent.runtime.models import LLMResponse
from recruit_agent.runtime.providers import ScriptedProvider

from ._helpers import build_assistant_client


def test_assistant_conversation_flow_and_cancel_endpoint(tmp_path: Path) -> None:
    provider = ScriptedProvider(provider_name="scripted", responses=[LLMResponse(content="assistant reply")])
    client, agent, _session_factory = build_assistant_client(tmp_path, provider=provider)
    with client:
        created = client.post("/api/assistant/conversations", json={"user_id": "user-1", "title": "Hiring"}).json()
        conversation_id = created["conversation_id"]

        stream_response = client.post(
            f"/api/assistant/conversations/{conversation_id}/turn",
            json={"message": "Summarize candidate status"},
        )
        body = stream_response.text
        assert stream_response.status_code == 200
        assert "event: turn.started" in body
        assert "event: llm_delta" in body
        assert "event: llm_final" in body
        assert "event: round.completed" in body
        assert "event: turn.completed" in body

        listed = client.get("/api/assistant/conversations", params={"user_id": "user-1"}).json()
        assert listed[0]["conversation_id"] == conversation_id

        cancelled = client.post(f"/api/assistant/conversations/{conversation_id}/cancel").json()
        assert cancelled["cancelled"] is False
        assert conversation_id not in agent.active_turns
