from __future__ import annotations

import json

from recruit_station.agent_runtime.types import LLMMessage
from recruit_station.agent_runtime.history import ConversationHistory
from recruit_station.product_adapters.context_builder import (
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


def test_autonomous_context_sanitizes_recent_tool_event_payloads() -> None:
    context = build_autonomous_turn_context(
        title="JD Sync",
        instruction="Continue JD sync",
        scope_kind="global",
        scope_ref="workspace:shared",
        constraints={},
        world_snapshot={},
        recent_events=[
            {
                "event_type": "tool_event",
                "source": "runtime",
                "message": "delegate_scene_context",
                "turn_id": "turn-1",
                "conversation_id": "run-1",
                "seq": 3,
                "payload": {
                    "data": {
                        "kind": "tool_result_ready",
                        "tool_name": "delegate_scene_context",
                        "content": {
                            "status": "blocked",
                            "summary": "raw scene summary",
                            "environment_context": {"dom": "<button>detail</button>", "clickPoint": {"x": 1, "y": 2}},
                            "execution_contract": {"hid": [{"type": "click"}]},
                            "evidence_refs": [{"kind": "execution_episode", "id": "episode-1"}],
                        },
                    }
                },
            }
        ],
        memory_entries=[],
        available_tools=["delegate_scene_context"],
        skill_contexts=[],
        available_mcps=["browser-mcp", "VirtualHID"],
    )

    rendered = str(context.initial_messages[0].content)
    assert "delegate_scene_context" in rendered
    assert "raw scene summary" not in rendered
    assert "environment_context" not in rendered
    assert "execution_contract" not in rendered
    assert "clickPoint" not in rendered
    event_payload = context.context_payload["recent_events"][0]["payload"]["data"]
    assert event_payload["content_summary"] == '{"evidence_ref_count": 1, "status": "blocked"}'


def test_runtime_context_preserves_product_agent_kind() -> None:
    context = build_autonomous_turn_context(
        agent_kind="jd_sync",
        title="同步招聘站点 JD",
        instruction="同步招聘站点 JD",
        scope_kind="global",
        scope_ref="workspace:shared",
        constraints={},
        world_snapshot={},
        recent_events=[],
        memory_entries=[],
        available_tools=["delegate_scene_context"],
        skill_contexts=[],
        available_mcps=["browser", "virtualhid"],
    )

    payload = json.loads(context.turn_input)
    assert payload["instruction"] == "同步招聘站点 JD"
    assert context.context_payload["agent"]["kind"] == "jd_sync"
    assert '"kind": "jd_sync"' in str(context.initial_messages[0].content)


def test_autonomous_context_treats_browser_target_url_as_entrypoint_hint() -> None:
    context = build_autonomous_turn_context(
        title="Recruiting workflow",
        instruction="当前 Chrome 活动页已经是 http://127.0.0.1:4317/jobs，请完成招聘闭环。",
        scope_kind="global",
        scope_ref="workspace:shared",
        constraints={
            "browser_target": {"url": "http://127.0.0.1:4317/jobs", "host": "127.0.0.1:4317"},
            "context_hints": {"active_tab_url": "http://127.0.0.1:4317/jobs"},
        },
        world_snapshot={},
        recent_events=[],
        memory_entries=[],
        available_tools=["delegate_scene_context"],
        skill_contexts=[],
        available_mcps=["browser"],
    )

    system_prompt = str(context.initial_messages[0].content)
    assert "browser_target.url is an entrypoint hint" in system_prompt
    assert "not an exact active-tab path requirement" in system_prompt
    assert "full origin" in system_prompt
    assert "Do not treat context_hints.active_tab_url as current browser evidence" in system_prompt
    assert "Available runtime tools: delegate_scene_context" in system_prompt
    assert "delegate_scene_context is the browser/HID execution gateway" in system_prompt
    assert "partial progress with blockers or limitations" in system_prompt
    assert "alternate same-origin affordance" in system_prompt


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
    assert context.context_payload["scene_request"]["instruction"] == "Inspect candidate page"
    assert context.initial_messages[1].metadata["kind"] == "runtime_context"
    assert context.initial_messages[1].metadata["auto_compact"] is True
    assert "scene_request" in str(context.initial_messages[1].content)
    assert "memory_entries" not in str(context.initial_messages[0].content)
    assert "skill_contexts" not in str(context.initial_messages[0].content)


def test_scene_context_prompt_lists_full_available_tools() -> None:
    context = build_scene_turn_context(
        request={
            "instruction": "Inspect",
            "input": {},
            "context": {},
            "output_contract": {},
            "environment_requirements": {},
            "anti_detection_policy": {},
            "behavior_budget": {},
        },
        episode_id="episode-1",
        task_spec_id="task-1",
        max_llm_invocations=4,
        recent_events=[],
        available_tools=[
            "browser_get_active_tab",
            "browser_list_tabs",
            "browser_query_elements",
            "browser_snapshot",
            "hid_action",
        ],
        available_mcps=["browser-mcp", "VirtualHID"],
        instruction="Inspect page and click when needed",
    )

    system_prompt = str(context.initial_messages[0].content)
    assert "Available scene tools:" in system_prompt
    assert "hid_action" in system_prompt
    assert "Available MCP capabilities: browser-mcp, VirtualHID" in system_prompt


def test_scene_context_does_not_hard_trim_payload_in_adapter() -> None:
    huge_input = "INPUT_SENTINEL_" + ("x" * 40000) + "_INPUT_TAIL"
    huge_context = "CONTEXT_SENTINEL_" + ("y" * 40000) + "_CONTEXT_TAIL"
    huge_environment_note = "ENV_SENTINEL_" + ("z" * 40000) + "_ENV_TAIL"

    context = build_scene_turn_context(
        request={
            "instruction": "Inspect",
            "input": {"resume_blob": huge_input},
            "context": {"page_snapshot": huge_context},
            "output_contract": {"summary": True},
            "environment_requirements": {
                "browser_target": {
                    "url": "https://ats.example.test/jobs/123",
                    "host": "ats.example.test",
                },
                "large_note": huge_environment_note,
            },
            "anti_detection_policy": {"mode": "humanized"},
            "behavior_budget": {"max_steps": 8},
        },
        episode_id="episode-1",
        task_spec_id="task-1",
        max_llm_invocations=4,
        recent_events=[{"event_type": "scene_started", "payload": "event " * 5000}],
        available_tools=[
            "browser_get_active_tab",
            "browser_snapshot",
            "browser_query_elements",
            "hid_action",
        ],
        available_mcps=["browser-mcp", "VirtualHID"],
        instruction="Inspect candidate page",
    )

    system_prompt = str(context.initial_messages[0].content)
    runtime_context = str(context.initial_messages[1].content)

    assert "INPUT_TAIL" not in system_prompt
    assert "CONTEXT_TAIL" not in system_prompt
    assert "ENV_TAIL" not in system_prompt
    assert "INPUT_TAIL" in runtime_context
    assert "CONTEXT_TAIL" in runtime_context
    assert "ENV_TAIL" in runtime_context
    assert "omitted by scene adapter pre-send context budget" not in runtime_context

    assert "https://ats.example.test/jobs/123" in system_prompt
    assert "browser_get_active_tab" in system_prompt
    assert "browser_snapshot" in system_prompt
    assert "browser_query_elements" in system_prompt
    assert "hid_action" in system_prompt
    assert "Available MCP capabilities: browser-mcp, VirtualHID" in system_prompt

    assert context.context_payload["scene_request"]["instruction"] == "Inspect candidate page"
    assert system_prompt.count("Inspect candidate page") == 0
    assert context.turn_input.count("Inspect candidate page") == 1


def test_runtime_auto_compacts_scene_runtime_context_without_replacing_current_user_task() -> None:
    history = ConversationHistory(
        [
            LLMMessage(role="system", content="Scene policy and hard boundary."),
            LLMMessage(
                role="system",
                content="Scene runtime context:\n" + ("large context " * 2000),
                metadata={"kind": "runtime_context", "auto_compact": True},
            ),
            LLMMessage(role="user", content="Inspect candidate page"),
        ]
    )

    compacted = history.compact_for_context_budget(max_chars=2000, summary_max_chars=600)

    assert compacted is not None
    assert history.messages[0].content == "Scene policy and hard boundary."
    assert history.messages[-1].content == "Inspect candidate page"
    assert any(message.metadata.get("kind") == "context_compaction_summary" for message in history.messages)
    assert all("large context " * 100 not in str(message.content) for message in history.messages)
