from __future__ import annotations

from agent_runtime.fixtures import LLMResponse, ScriptedProvider, ToolCall

from recruit_station.agent_runtime.types import LLMMessage
from recruit_station.capabilities.tools import ToolDefinition, ToolRegistry, build_delegate_scene_context_tool
from recruit_station.agents.autonomous import (
    _final_output_continuation_resolver,
    _jd_sync_recoverable_scene_retry_needed,
    _outcome_from_final_output_text,
    _structured_status_resolver,
)
from recruit_station.product_adapters.agent_runner import run_agent_turn
from recruit_station.product_adapters.context_builder import build_assistant_turn_context, build_autonomous_turn_context
from recruit_station.product_adapters.result_semantics import extract_execution_status


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


def test_runner_passes_context_budget_to_runtime_engine() -> None:
    provider = ScriptedProvider(provider_name="autonomous-scripted", responses=[LLMResponse(content="done")])
    large_context = "x" * 5000

    run_agent_turn(
        provider=provider,
        tool_registry=ToolRegistry(),
        agent_definition_id=None,
        conversation_id="autonomous-conv",
        initial_messages=[
            LLMMessage(role="system", content="Autonomous prompt."),
            LLMMessage(
                role="system",
                content=large_context,
                metadata={"kind": "runtime_context", "auto_compact": True},
            )
        ],
        turn_input="run",
        max_llm_invocations=1,
        max_context_chars=1000,
        compaction_summary_max_chars=200,
    )

    request = provider.captured_requests[0]
    assert request.system_prompt == "Autonomous prompt."
    assert len(str(request.messages[0].content)) < len(large_context)
    assert "Conversation context compacted automatically before provider request" in str(request.messages[0].content)


def test_runner_projects_normalized_tool_input_in_tool_started_event() -> None:
    provider = ScriptedProvider(
        provider_name="autonomous-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="delegate_scene_context",
                        arguments={
                            "instruction": "继续刚才同一招聘站点 JD 同步 scene。上一轮只完整读取了 1/5 个，剩余 4 个：国际销售工程师。",
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="done", result_data={"execution_status": "completed"}),
        ],
    )
    registry = ToolRegistry()
    registry.register(
        build_delegate_scene_context_tool(
            lambda arguments: {"status": "partial", "result_data": {"status": "partial"}},
        )
    )
    events = []

    run_agent_turn(
        provider=provider,
        tool_registry=registry,
        agent_definition_id=None,
        conversation_id="jd-sync-primary",
        initial_messages=[],
        turn_input="run",
        max_llm_invocations=2,
        runtime={"constraints": {"plan_kind": "jd_sync"}},
        output_sink=events.append,
    )

    started = next(
        output
        for output in events
        if output.type == "tool_event" and output.data.get("kind") == "tool_call_started"
    )
    instruction = str(started.data["input"]["instruction"])
    assert "1/5" not in instruction
    assert "剩余 4" not in instruction
    assert "国际销售工程师" not in instruction
    assert started.data["input"]["output_contract"]["result_data_required"] is True


def test_runner_can_resolve_terminal_status_from_final_output_text() -> None:
    provider = ScriptedProvider(provider_name="autonomous-scripted", responses=[LLMResponse(content="结果：已阻塞，等待恢复。")])

    result = run_agent_turn(
        provider=provider,
        tool_registry=ToolRegistry(),
        agent_definition_id=None,
        conversation_id="autonomous-conv",
        initial_messages=[],
        turn_input="run",
        max_llm_invocations=1,
        final_output_status_resolver=lambda text: ("escalate", "escalate") if "已阻塞" in text else None,
    )

    assert result.status == "escalate"
    assert result.gate_signal == "escalate"
    assert result.final_output == "结果：已阻塞，等待恢复。"


def test_runner_can_reject_final_output_and_continue_with_tool_call() -> None:
    provider = ScriptedProvider(
        provider_name="autonomous-scripted",
        responses=[
            LLMResponse(content="结果：未完成全量 JD 同步，当前阻塞。"),
            LLMResponse(
                tool_calls=[ToolCall(id="tool-1", name="test.observe", arguments={"scope": "remaining-jobs"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="JD sync completed.", result_data={"execution_status": "completed"}),
        ],
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.observe",
            description="Observe remaining jobs.",
            parameters={"type": "object", "additionalProperties": True},
            handler=lambda arguments: {"observed": arguments.get("scope")},
            category="core",
        )
    )

    result = run_agent_turn(
        provider=provider,
        tool_registry=registry,
        agent_definition_id=None,
        conversation_id="autonomous-conv",
        initial_messages=[],
        turn_input="run",
        max_llm_invocations=3,
        structured_status_resolver=lambda value: ("complete", "run_done")
        if extract_execution_status(value) == "completed"
        else None,
        final_output_status_resolver=lambda text: ("escalate", "escalate") if "阻塞" in text else None,
        final_output_continuation_resolver=lambda text, tool_calls, tool_results, attempt: "continue with tools"
        if "未完成全量" in text and not tool_calls and attempt == 0
        else None,
    )

    assert result.status == "complete"
    assert result.gate_signal == "run_done"
    assert result.final_output == "JD sync completed."
    assert any(call.get("tool_name") == "test.observe" for call in result.tool_calls)
    assert provider.captured_requests[1].messages[-1].content == "continue with tools"


def test_jd_sync_continuation_rejects_partial_final_output_after_tool_calls() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "已完成部分 JD 同步，但未完成全量详情读取，当前 partial。",
        [{"tool_name": "delegate_scene_context"}],
        [{"tool_name": "delegate_scene_context", "result": {"status": "partial"}}],
        0,
    )

    assert continuation is not None
    assert "即使本轮已经调用过 scene 或业务工具" in continuation
    assert "继续同一个 turn" in continuation


def test_jd_sync_continuation_rejects_bland_final_output_when_result_data_is_partial() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "已处理。",
        [{"tool_name": "delegate_scene_context"}],
        [{"tool_name": "delegate_scene_context", "result": {"status": "partial"}}],
        0,
        {"status": "partial", "remaining_jobs": ["jd-solution-002"]},
    )

    assert continuation is not None
    assert "继续同一个 turn" in continuation


def test_jd_sync_continuation_treats_hid_frontmost_timeout_as_recoverable_after_tool_calls() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "本轮同步阻塞，未完成全量 JD 同步。阻塞原因：E_TIMEOUT: injector action exceeded timeout；"
        "E_NOT_FRONTMOST: target app is not frontmost；VirtualHID/电脑执行链路不可用。剩余 4 个职位未完成详情读取。",
        [{"tool_name": "delegate_scene_context"}],
        [{"tool_name": "delegate_scene_context", "result": {"status": "partial"}}],
        0,
        {},
    )

    assert continuation is not None
    assert "E_TIMEOUT" in continuation
    assert "继续同一个 turn" in continuation


def test_jd_sync_continuation_treats_nested_pending_confirmation_as_recoverable() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "仍需人工恢复，当前 blocked。原因包含 human-only / pending_confirmation / E_NOT_FRONTMOST / "
        "E_DAEMON_UNREACHABLE。剩余 4 个 JD 未完成详情读取。",
        [{"tool_name": "delegate_scene_context"}],
        [{"tool_name": "delegate_scene_context", "result": {"status": "blocked", "blockers": ["pending_confirmation"]}}],
        0,
        {},
    )

    assert continuation is not None
    assert "pending_confirmation" in continuation
    assert "继续同一个 turn" in continuation


def test_jd_sync_continuation_allows_real_login_boundary_to_stop() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "本轮阻塞，未完成全量 JD 同步。目标页面要求重新登录和验证码，无法继续读取剩余详情。",
        [{"tool_name": "delegate_scene_context"}],
        [{"tool_name": "delegate_scene_context", "result": {"status": "blocked"}}],
        0,
        {},
    )

    assert continuation is None


def test_jd_sync_continuation_detects_still_needs_continue_output() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    final_output = (
        "仍需继续，但当前没有新的可写回 JD 详情证据。\n"
        "- 仍未成功确认进入任一职位详情页\n"
        "- completed_job_details 仍为空\n"
        "- 还不能调用本地 JD 写回\n"
        "本轮仍出现 E_NOT_FRONTMOST 和 E_DAEMON_UNREACHABLE。"
    )

    continuation = resolver(
        final_output,
        [{"tool_name": "delegate_scene_context"}],
        [{"tool_name": "delegate_scene_context", "result": {"status": "blocked"}}],
        0,
        {},
    )

    assert continuation is not None
    assert _outcome_from_final_output_text(final_output) == ("escalate", "escalate")


def test_jd_sync_continuation_reads_recoverable_scene_tool_result_even_with_bland_summary() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "已完成。",
        [{"tool_name": "delegate_scene_context"}],
        [
            {
                "tool_name": "delegate_scene_context",
                "output": {
                    "status": "blocked",
                    "summary": "返回列表时 E_TIMEOUT，但目标站点仍可访问，仍需继续读取剩余职位详情。",
                    "remaining_work": ["resume_remaining_job_details"],
                    "completed_job_details": [],
                },
            }
        ],
        0,
        {},
    )

    assert continuation is not None
    assert "继续同一个 turn" in continuation


def test_jd_sync_recoverable_scene_retry_detects_frontmost_blocker_after_repeated_recovery() -> None:
    assert _jd_sync_recoverable_scene_retry_needed(
        final_output=(
            "已按要求继续恢复，但当前未能继续进入职位列表。"
            "真实 HID 注入仍被前台焦点条件拦截，目标同源页面仍稳定可读。"
        ),
        tool_results=[
            {
                "tool_name": "delegate_scene_context",
                "output": {
                    "status": "blocked",
                    "summary": "E_NOT_FRONTMOST，目标站点仍可访问，剩余职位未完成详情读取。",
                    "remaining_work": ["read_remaining_job_details"],
                },
            }
        ],
        result_data={},
    )


def test_jd_sync_recoverable_scene_retry_ignores_negated_hard_blocker_terms() -> None:
    assert _jd_sync_recoverable_scene_retry_needed(
        final_output=(
            "本轮已读取 1 个职位详情，但未完成全量 JD 同步。"
            "没有登录、验证码、权限或页面不可达问题；当前只是 E_NOT_FRONTMOST，剩余 4 个职位未完成详情读取。"
        ),
        tool_results=[
            {
                "tool_name": "delegate_scene_context",
                "output": {
                    "status": "blocked",
                    "summary": "没有目标站点不可达问题；HID 点击返回列表 E_TIMEOUT，仍需继续打开剩余职位详情。",
                    "observed_jobs": ["jd-sales-001", "jd-solution-002", "jd-csm-003", "jd-pm-004", "jd-backend-005"],
                    "completed_job_details": [{"title": "国际销售工程师"}],
                    "remaining_work": ["read_remaining_job_details"],
                },
            }
        ],
        result_data={},
    )


def test_jd_sync_continuation_ignores_negated_unreachable_boundary() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "未完成全量 JD 同步。没有登录、验证码、权限或页面不可达问题；只是 E_TIMEOUT，剩余职位未完成详情读取。",
        [{"tool_name": "delegate_scene_context"}],
        [
            {
                "tool_name": "delegate_scene_context",
                "output": {
                    "status": "blocked",
                    "summary": "没有页面不可达问题；当前 HID 超时，仍需继续。",
                    "remaining_work": ["read_remaining_job_details"],
                },
            }
        ],
        0,
        {},
    )

    assert continuation is not None
    assert "继续同一个 turn" in continuation


def test_jd_sync_continuation_treats_authenticated_browser_channel_blocker_as_recoverable() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "当前任务仍处于阻塞状态：我无法直接观察或操作已登录的 zhipin.com 浏览器会话来继续同步 JD。"
        "需要先恢复浏览器观察/执行通道，或提供可用的同源页面证据后，我才能继续进入职位管理并读取职位详情。",
        [{"tool_name": "list_memory_files"}, {"tool_name": "get_jd_progress"}],
        [{"tool_name": "list_memory_files"}, {"tool_name": "get_jd_progress"}],
        0,
        {},
    )

    assert continuation is not None
    assert "delegate_scene_context" in continuation


def test_jd_sync_continuation_allows_terminal_login_scene_boundary() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "已阻塞，目标站点要求重新登录和验证码，无法继续读取职位详情。",
        [{"tool_name": "delegate_scene_context"}],
        [
            {
                "tool_name": "delegate_scene_context",
                "output": {
                    "status": "blocked",
                    "summary": "目标站点要求重新登录和验证码，无法继续读取职位详情。",
                    "blockers": [{"kind": "auth_required", "message": "需要登录和验证码"}],
                },
            }
        ],
        0,
        {},
    )

    assert continuation is None


def test_candidate_discovery_continuation_rejects_no_candidate_next_step_output() -> None:
    resolver = _final_output_continuation_resolver(
        agent_kind="autonomous",
        run_constraints={"run_kind": "candidate_discovery", "candidate_count_target": 1},
    )
    assert resolver is not None

    continuation = resolver(
        "我还没有读取候选人卡片，下一步可以继续读取候选人资料。",
        [{"tool_name": "delegate_scene_context"}],
        [
            {
                "tool_name": "delegate_scene_context",
                "output": {
                    "status": "completed",
                    "result_data": {
                        "status": "completed",
                        "candidate_records": [],
                        "blockers": [],
                        "evidence": ["search page observed"],
                        "actions_attempted": ["observed search results"],
                    },
                },
            }
        ],
        0,
        {"execution_status": "completed", "candidate_records": []},
    )

    assert continuation is not None
    assert "candidate_records 为空" in continuation


def test_multi_jd_recruiting_continues_after_entry_check_without_business_facts() -> None:
    resolver = _final_output_continuation_resolver(
        agent_kind="autonomous",
        run_constraints={"context_hints": {"launch_plan": {"plan_kind": "multi_jd_recruiting"}}},
    )
    assert resolver is not None

    continuation = resolver(
        "已完成入口核验。页面证据不足，暂未写入候选人、评分或消息记录。建议下一步继续进入沟通或推荐牛人。",
        [{"tool_name": "delegate_scene_context"}],
        [{"tool_name": "delegate_scene_context", "output": {"status": "completed", "result_data": {}}}],
        0,
        {},
    )

    assert continuation is not None
    assert "不能作为多 JD 自动化招聘终局" in continuation
    assert "不要把打开或核对 BOSS JD 详情页作为前置条件" in continuation


def test_multi_jd_recruiting_jd_writeback_is_not_candidate_progress() -> None:
    resolver = _final_output_continuation_resolver(
        agent_kind="autonomous",
        run_constraints={"context_hints": {"launch_plan": {"plan_kind": "multi_jd_recruiting"}}},
    )
    assert resolver is not None

    continuation = resolver(
        "已完成入口核验。暂未写入候选人、沟通、简历、评分或人工筛选事实。建议下一步继续进入推荐牛人。",
        [{"tool_name": "upsert_job_description"}],
        [{"tool_name": "upsert_job_description", "output": {"job_description_id": "jd-1"}}],
        0,
        {},
    )

    assert continuation is not None
    assert "职位管理、推荐牛人、搜索、沟通" in continuation
    assert "不得点击互动、看过我、对我感兴趣、沟通过" in continuation


def test_multi_jd_recruiting_continues_after_site_visibility_only_summary() -> None:
    resolver = _final_output_continuation_resolver(
        agent_kind="autonomous",
        run_constraints={"plan_kind": "multi_jd_recruiting"},
    )
    assert resolver is not None

    continuation = resolver(
        "已启动并完成站点可见性核对。本轮仅完成了站点定位与入口确认，尚未写入候选人、消息或评分记录。下一步继续围绕 JD 推进。",
        [{"tool_name": "delegate_scene_context"}],
        [{"tool_name": "delegate_scene_context", "output": {"status": "completed"}}],
        0,
        {},
    )

    assert continuation is not None
    assert "不能作为多 JD 自动化招聘终局" in continuation


def test_multi_jd_recruiting_continuation_allows_business_tool_progress() -> None:
    resolver = _final_output_continuation_resolver(
        agent_kind="autonomous",
        run_constraints={"plan_kind": "multi_jd_recruiting"},
    )
    assert resolver is not None

    continuation = resolver(
        "候选人发现完成。",
        [{"tool_name": "upsert_candidate"}],
        [{"tool_name": "upsert_candidate", "output": {"candidate_person_id": "cand-1"}}],
        0,
        {"status": "completed"},
    )

    assert continuation is None


def test_candidate_discovery_structured_status_blocks_empty_completed_result() -> None:
    resolver = _structured_status_resolver(
        agent_kind="autonomous",
        run_constraints={"run_kind": "candidate_discovery", "candidate_count_target": 1},
    )

    assert resolver({"execution_status": "completed", "candidate_records": []}) == ("escalate", "escalate")


def test_candidate_discovery_structured_status_uses_preferred_flow_without_count_target() -> None:
    resolver = _structured_status_resolver(
        agent_kind="automation_recruiting",
        run_constraints={"preferred_flow": "candidate_discovery"},
    )

    assert resolver({"execution_status": "completed", "candidate_records": []}) == ("escalate", "escalate")


def test_candidate_discovery_structured_status_allows_hard_blocker_escalation() -> None:
    resolver = _structured_status_resolver(
        agent_kind="autonomous",
        run_constraints={"run_kind": "candidate_discovery", "candidate_count_target": 1},
    )

    result = resolver(
        {
            "status": "blocked",
            "candidate_records": [],
            "blockers": [{"kind": "captcha", "message": "captcha required"}],
            "evidence": ["captcha prompt"],
            "actions_attempted": ["opened allowed candidate discovery flow"],
        }
    )

    assert result == ("escalate", "escalate")


def test_candidate_discovery_run_turn_does_not_run_done_without_candidates() -> None:
    provider = ScriptedProvider(
        provider_name="autonomous-scripted",
        responses=[
            LLMResponse(
                content="我还没有读取候选人卡片，下一步可以继续读取候选人资料。",
                result_data={"execution_status": "completed", "candidate_records": []},
            ),
            LLMResponse(
                content="候选人发现阻塞：仍未读取候选人卡片。",
                result_data={"status": "blocked", "candidate_records": [], "blockers": []},
            ),
        ],
    )

    result = run_agent_turn(
        provider=provider,
        tool_registry=ToolRegistry(),
        agent_definition_id=None,
        conversation_id="autonomous-conv",
        initial_messages=[],
        turn_input="run",
        max_llm_invocations=2,
        structured_status_resolver=_structured_status_resolver(
            agent_kind="autonomous",
            run_constraints={"run_kind": "candidate_discovery", "candidate_count_target": 1},
        ),
        final_output_continuation_resolver=_final_output_continuation_resolver(
            agent_kind="autonomous",
            run_constraints={"run_kind": "candidate_discovery", "candidate_count_target": 1},
        ),
    )

    assert result.status == "escalate"
    assert result.gate_signal == "escalate"
    assert result.continuation_attempts == 1
