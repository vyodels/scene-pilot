from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from recruit_agent.agent_runtime.types import LLMInvocationResult, LLMMessage, LLMRequest, LLMResponse

from ._helpers import build_assistant_client


@dataclass(slots=True)
class FixtureLLMProvider:
    responses: list[LLMResponse]
    provider_name: str = "test"
    captured_requests: list[LLMRequest] = field(default_factory=list)

    def invoke(self, request: LLMRequest) -> LLMInvocationResult:
        self.captured_requests.append(request)
        return LLMInvocationResult(events=[], response=self.responses.pop(0))


def test_assistant_conversation_flow_and_cancel_endpoint(tmp_path: Path) -> None:
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
