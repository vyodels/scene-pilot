from __future__ import annotations

import threading
import time
from pathlib import Path

from recruit_agent.agent_runtime.models import LLMResponse, ToolCall
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.runtime.tools import ToolDefinition, ToolRegistry, register_core_tools

from ._helpers import build_assistant_client


def test_functional_closure_assistant_cancel_interrupts_live_turn(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(tool_calls=[ToolCall(id="tool-1", name="slow.wait", arguments={})], finish_reason="tool_calls"),
        ],
    )
    tools = ToolRegistry()
    register_core_tools(tools)

    def _slow_wait(arguments: dict[str, object], *, cancel_token=None) -> dict[str, object]:
        for _ in range(100):
            if cancel_token is not None and cancel_token.cancelled:
                return {"cancelled": True}
            time.sleep(0.02)
        return {"done": True}

    tools.register(
        ToolDefinition(
            name="slow.wait",
            description="Slow wait.",
            parameters={"type": "object", "additionalProperties": True},
            handler=_slow_wait,
            category="core",
            external_target=False,
            resource_target_kind="execution",
        )
    )
    client, agent, _session_factory = build_assistant_client(tmp_path, provider=provider, tools=tools)
    with client:
        conversation_id = client.post("/api/assistant/conversations", json={"user_id": "user-1"}).json()["conversation_id"]
        body: dict[str, str] = {}

        def _run_turn() -> None:
            body["text"] = client.post(
                f"/api/assistant/conversations/{conversation_id}/turn",
                json={"message": "slow"},
            ).text

        worker = threading.Thread(target=_run_turn, daemon=True)
        worker.start()
        deadline = time.time() + 2
        while conversation_id not in agent.active_turns and time.time() < deadline:
            time.sleep(0.02)
        assert client.post(f"/api/assistant/conversations/{conversation_id}/cancel").json()["cancelled"] is True
        worker.join(timeout=5)
        assert "event: turn.cancelling" in body["text"]
        assert "event: turn.cancelled" in body["text"]
