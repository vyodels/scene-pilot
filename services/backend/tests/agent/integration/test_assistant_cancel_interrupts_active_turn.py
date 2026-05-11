from __future__ import annotations

import threading
import time
from pathlib import Path

from agent_runtime.fixtures import LLMResponse, ToolCall
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.capabilities.tools import ToolDefinition, ToolRegistry, register_core_tools

from ._helpers import build_assistant_client


def test_assistant_cancel_interrupts_active_turn(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="slow-1", name="slow.wait", arguments={"seconds": 1})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="should not reach", finish_reason="stop"),
        ],
    )
    tools = ToolRegistry()
    register_core_tools(tools)

    def _slow_wait(arguments: dict[str, object]) -> dict[str, object]:
        for _ in range(5):
            time.sleep(0.02)
        return {"done": True, "seconds": arguments["seconds"]}

    tools.register(
        ToolDefinition(
            name="slow.wait",
            description="Wait until cancelled.",
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
        response_box: dict[str, str] = {}

        def _run_turn() -> None:
            response = client.post(
                f"/api/assistant/conversations/{conversation_id}/turn",
                json={"message": "wait"},
            )
            response_box["body"] = response.text

        worker = threading.Thread(target=_run_turn, daemon=True)
        worker.start()
        deadline = time.time() + 2
        while conversation_id not in agent.active_turns and time.time() < deadline:
            time.sleep(0.02)

        cancelled = client.post(f"/api/assistant/conversations/{conversation_id}/cancel").json()
        worker.join(timeout=5)

        assert cancelled["cancelled"] is True
        assert "event: turn_interrupted" in response_box["body"]
        assert conversation_id not in agent.active_turns
