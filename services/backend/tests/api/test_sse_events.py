from __future__ import annotations

from pathlib import Path

from scene_pilot.runtime.models import LLMResponse
from scene_pilot.runtime.providers import ScriptedProvider
from services.backend.tests.agent.integration._helpers import build_assistant_client


def test_assistant_sse_events_use_turn_terminology(tmp_path: Path) -> None:
    provider = ScriptedProvider(provider_name="scripted", responses=[LLMResponse(content="assistant reply")])
    client, _agent, _session_factory = build_assistant_client(tmp_path, provider=provider)

    with client:
        conversation_id = client.post("/api/assistant/conversations", json={"user_id": "user-1"}).json()["conversation_id"]
        response = client.post(
            f"/api/assistant/conversations/{conversation_id}/turn",
            json={"message": "Summarize candidate status"},
        )

    body = response.text
    assert response.status_code == 200
    assert "event: turn.started" in body
    assert "event: round.completed" in body
    assert "event: turn.completed" in body
    assert "event: tick.started" not in body
    assert "event: tick.completed" not in body
    assert "event: tick.waiting_human" not in body
    assert "event: tick.failed" not in body
