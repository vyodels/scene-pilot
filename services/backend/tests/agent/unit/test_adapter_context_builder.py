from __future__ import annotations

import json

from recruit_agent.agent_runtime.types import LLMMessage
from recruit_agent.product_adapters.context_builder import (
    build_agent_turn_context,
    build_assistant_turn_context,
    build_autonomous_turn_context,
    build_scene_turn_context,
)


def test_assistant_context_preserves_history_and_turn_input() -> None:
    history = [LLMMessage(role="assistant", content="previous")]

    context = build_assistant_turn_context(history_messages=history, user_message="hello")

    assert context.initial_messages[0].role == "system"
    assert context.initial_messages[1:] == history
    assert context.turn_input == "hello"
    assert context.context_payload["agent"]["kind"] == "assistant"
    assert context.context_payload["scope"] == {"kind": "conversation"}


def test_assistant_context_uses_progressive_memory_disclosure() -> None:
    context = build_assistant_turn_context(
        history_messages=[],
        user_message="hello",
        agent_definition_id="assistant-profile",
        memory_entries=[
            {
                "memory_item_id": "MEMORY.md",
                "kind": "memory_file",
                "summary": "Use concise replies",
                "content": {"path": "MEMORY.md", "preview": "Use concise replies"},
            }
        ],
    )

    assert context.context_payload["memory_layers"]["long_term"].startswith("memory entries")
    assert context.context_payload["agent"]["definition_id"] == "assistant-profile"
    assert "read full files only when needed" in str(context.initial_messages[0].content)


def test_autonomous_context_renders_payload_and_json_turn_input() -> None:
    context = build_autonomous_turn_context(
        title="Follow up",
        instruction="Handle candidate",
        scope_kind="candidate",
        scope_ref="cand-1",
        constraints={"priority": "high"},
        world_snapshot={"stage": "replied"},
        recent_events=[{"event_type": "tool_event"}],
        memory_entries=[{"summary": "Alice wants remote"}],
        available_tools=["read_memory"],
        skill_contexts=[{"skill_id": "resume-parser"}],
        available_mcps=["docs"],
        mcp_resource_contexts=[{"uri": "memo://candidate", "content": "profile"}],
    )

    payload = json.loads(context.turn_input)
    assert payload["instruction"] == "Handle candidate"
    assert "goal" not in payload
    assert payload["mcp_resource_contexts"][0]["uri"] == "memo://candidate"
    assert "skill_contexts" in str(context.initial_messages[0].content)
    assert context.context_payload["scope"] == {"kind": "candidate", "ref": "cand-1"}
    assert context.context_payload["memory_layers"]["long_term"].startswith("memory index")


def test_shared_context_builder_uses_canonical_instruction_payload() -> None:
    context = build_agent_turn_context(
        agent_kind="autonomous",
        agent_name="Autonomous",
        system_prompt="Run recruiting work.",
        turn_input="Find qualified candidates.",
        instruction="Find qualified candidates.",
        title="Candidate discovery",
        agent_definition_id="profile-1",
        scope_kind="global",
        scope_ref="workspace:shared",
        constraints={"jd_id": "jd-1"},
        world_snapshot={"active_jds": 1},
        recent_events=[{"event_type": "run_created"}],
        memory_entries=[{"memory_item_id": "global.md", "summary": "Use approved sources"}],
        available_tools=["list_candidates"],
        skill_contexts=[{"skill_id": "candidate-discovery"}],
        available_mcps=["browser"],
        mcp_resource_contexts=[{"uri": "mcp://resource", "content": "resource summary"}],
        response_policy={"prefer_structured_output": True},
    )

    assert context.turn_input == "Find qualified candidates."
    assert context.context_payload["instruction"] == "Find qualified candidates."
    assert context.context_payload["agent"] == {
        "kind": "autonomous",
        "name": "Autonomous",
        "definition_id": "profile-1",
    }
    assert context.context_payload["scope"] == {"kind": "global", "ref": "workspace:shared"}
    assert context.context_payload["mcp_resource_contexts"][0]["uri"] == "mcp://resource"
    assert "instruction_template" not in str(context.context_payload)
    assert "automationInstruction" not in str(context.context_payload)
    assert "goal" not in str(context.context_payload).lower()


def test_scene_context_renders_scene_payload_without_memory_or_skills() -> None:
    context = build_scene_turn_context(
        request={
            "instruction": "Inspect",
            "input": {"url": "https://example.test"},
            "context": {"candidate": "Alice"},
            "output_contract": {"summary": True},
            "environment_requirements": {"browser_target": {"url": "https://example.test"}},
        },
        episode_id="episode-1",
        task_spec_id="task-1",
        max_llm_invocations=4,
        recent_events=[],
        available_tools=["browser_snapshot"],
        available_mcps=["browser"],
        instruction="Inspect candidate page",
    )

    assert context.turn_input == "Inspect candidate page"
    assert "scene_request" in str(context.initial_messages[0].content)
    assert "memory_entries" not in str(context.initial_messages[0].content)
    assert "skill_contexts" not in str(context.initial_messages[0].content)
