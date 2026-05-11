from __future__ import annotations

from pathlib import Path

from dataclasses import dataclass, field

from recruit_agent.agent_runtime.types import LLMInvocationResult, LLMMessage, LLMRequest, LLMResponse
from agent.integration._helpers import build_assistant_client


@dataclass(slots=True)
class FixtureLLMProvider:
    responses: list[LLMResponse]
    provider_name: str = "test"
    captured_requests: list[LLMRequest] = field(default_factory=list)

    def invoke(self, request: LLMRequest) -> LLMInvocationResult:
        self.captured_requests.append(request)
        return LLMInvocationResult(events=[], response=self.responses.pop(0))


def test_assistant_sse_events_use_turn_terminology(tmp_path: Path) -> None:
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="assistant reply"),
            )
        ]
    )
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
