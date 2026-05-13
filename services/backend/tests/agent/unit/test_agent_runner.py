from __future__ import annotations

from agent_runtime.fixtures import LLMResponse, ScriptedProvider

from recruit_agent.capabilities.tools import ToolRegistry
from recruit_agent.product_adapters.agent_runner import run_agent_turn
from recruit_agent.product_adapters.context_builder import build_assistant_turn_context, build_autonomous_turn_context
from recruit_agent.product_adapters.result_semantics import extract_execution_status


def test_runner_places_adapter_system_prompt_outside_messages_for_both_agent_kinds() -> None:
    assistant_provider = ScriptedProvider(provider_name="assistant-scripted", responses=[LLMResponse(content="assistant done")])
    autonomous_provider = ScriptedProvider(provider_name="autonomous-scripted", responses=[LLMResponse(content="autonomous done")])
    assistant_context = build_assistant_turn_context(
        history_messages=[],
        user_message="hello",
        system_prompt="Assistant shared prompt.",
    )
    autonomous_context = build_autonomous_turn_context(
        title="Run",
        instruction="Do work",
        system_prompt="Autonomous shared prompt.",
        scope_kind="global",
        scope_ref="workspace",
        constraints={},
        world_snapshot={},
        recent_events=[],
        memory_entries=[],
        available_tools=[],
        skill_contexts=[],
        available_mcps=[],
    )

    run_agent_turn(
        provider=assistant_provider,
        tool_registry=ToolRegistry(),
        agent_definition_id=None,
        conversation_id="assistant-conv",
        initial_messages=assistant_context.initial_messages,
        turn_input=assistant_context.turn_input,
        max_llm_invocations=1,
    )
    run_agent_turn(
        provider=autonomous_provider,
        tool_registry=ToolRegistry(),
        agent_definition_id=None,
        conversation_id="autonomous-conv",
        initial_messages=autonomous_context.initial_messages,
        turn_input=autonomous_context.turn_input,
        max_llm_invocations=1,
    )

    assistant_request = assistant_provider.captured_requests[0]
    autonomous_request = autonomous_provider.captured_requests[0]
    assert assistant_request.system_prompt == str(assistant_context.initial_messages[0].content)
    assert autonomous_request.system_prompt == str(autonomous_context.initial_messages[0].content)
    assert all(message.role != "system" for message in assistant_request.messages)
    assert all(message.role != "system" for message in autonomous_request.messages)


def test_extract_execution_status_prefers_execution_status_over_business_status() -> None:
    assert extract_execution_status({"status": "pass", "execution_status": "completed"}) == "completed"
