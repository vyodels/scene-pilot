from __future__ import annotations

import threading
import time
from pathlib import Path

from agent_runtime.fixtures import LLMResponse, ToolCall
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.capabilities.tools import ToolDefinition, ToolRegistry, register_core_tools

from ._helpers import build_assistant_client


def test_assistant_cancel_state_is_not_reused_by_later_turns(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="slow-1", name="slow.wait", arguments={"seconds": 1})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="fresh reply", finish_reason="stop"),
        ],
    )
    tools = ToolRegistry()
    register_core_tools(tools)

    def _slow_wait(arguments: dict[str, object]) -> dict[str, object]:
        for _ in range(5):
            time.sleep(0.02)
        return {"done": True}

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
        background = threading.Thread(
            target=lambda: client.post(
                f"/api/assistant/conversations/{conversation_id}/turn",
                json={"message": "slow turn"},
            ),
            daemon=True,
        )
        background.start()
        deadline = time.time() + 2
        while conversation_id not in agent.active_turns and time.time() < deadline:
            time.sleep(0.02)
        client.post(f"/api/assistant/conversations/{conversation_id}/cancel")
        background.join(timeout=5)

        second = client.post(
            f"/api/assistant/conversations/{conversation_id}/turn",
            json={"message": "new turn"},
        )
        assert "event: assistant_message_completed" in second.text
        assert "event: turn_interrupted" not in second.text
        assert conversation_id not in agent.active_turns
