from __future__ import annotations

from agent_runtime.fixtures import LLMResponse, ScriptedProvider, ToolCall

from recruit_station.agent_runtime.types import LLMMessage
from recruit_station.capabilities.tools import ToolDefinition, ToolRegistry, build_delegate_scene_context_tool
from recruit_station.agents.autonomous import (
    _final_output_continuation_resolver,
    _jd_sync_action_plan_from_state,
    _jd_sync_result_data_needs_tool_continuation,
    _jd_sync_recoverable_scene_retry_needed,
    _jd_sync_scene_result_needs_continuation,
    _outcome_from_final_output_text,
    _outcome_from_structured_result_data,
)
from recruit_station.product_adapters.agent_runner import run_agent_turn
from recruit_station.product_adapters.context_builder import build_assistant_turn_context, build_autonomous_turn_context
from recruit_station.product_adapters.result_semantics import extract_execution_status
from recruit_station.services.recruit_station import default_agent_definition


_LEGACY_JD_SELECTION_PHRASE = "生效 " + "JD 选择"
_LEGACY_CONFIG_PAGE_PHRASE = "配置页" + "选择"


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


def test_default_jd_sync_system_prompt_uses_jd_sync_completion_contract() -> None:
    prompt = str(
        ((default_agent_definition().get("product_config") or {}).get("jd_sync") or {})
        .get("prompt_config", {})
        .get("system_prompt", "")
    )

    assert "全量真实详情读取、本地 JD 写回验证且 pending_jobs 为空" in prompt
    assert _LEGACY_JD_SELECTION_PHRASE not in prompt
    assert _LEGACY_CONFIG_PAGE_PHRASE not in prompt
    assert "侧边栏" + "语义" not in prompt


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


def test_jd_sync_empty_state_first_request_requires_scene_tool_and_hides_candidate_tools() -> None:
    provider = ScriptedProvider(provider_name="jd-sync-scripted", responses=[LLMResponse(content="无法继续。")])
    registry = ToolRegistry()
    registry.register(
        build_delegate_scene_context_tool(
            lambda arguments: {
                "status": "partial",
                "result_data": {"status": "partial", "observed_jobs": [], "completed_job_details": []},
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="upsert_candidate",
            description="Must not be available to JD sync.",
            parameters={"type": "object", "additionalProperties": True},
            handler=lambda arguments: {"candidate_id": "candidate-1"},
            category="core",
        )
    )

    run_agent_turn(
        provider=provider,
        tool_registry=registry,
        agent_definition_id=None,
        conversation_id="jd-sync-primary",
        initial_messages=[],
        turn_input="同步招聘站点 JD",
        max_llm_invocations=1,
        runtime={
            "constraints": {
                "plan_kind": "jd_sync",
                "jd_sync_state": {
                    "jobs_by_key": {},
                    "pending_job_keys": [],
                    "completed_job_keys": [],
                    "inactive_job_keys": [],
                    "evidence_refs": [],
                    "recovery_attempts": [],
                    "writeback_results": [],
                },
            }
        },
    )

    request = provider.captured_requests[0]
    assert request.tool_choice == "delegate_scene_context"
    assert "delegate_scene_context" in {tool.name for tool in request.tools}
    assert "upsert_candidate" not in {tool.name for tool in request.tools}


def test_jd_sync_top_level_existing_state_does_not_force_bootstrap_scene_tool() -> None:
    provider = ScriptedProvider(provider_name="jd-sync-scripted", responses=[LLMResponse(content="继续处理已有状态。")])
    registry = ToolRegistry()
    registry.register(build_delegate_scene_context_tool(lambda arguments: {"status": "partial"}))

    run_agent_turn(
        provider=provider,
        tool_registry=registry,
        agent_definition_id=None,
        conversation_id="jd-sync-primary",
        initial_messages=[],
        turn_input="继续 JD 同步",
        max_llm_invocations=1,
        runtime={
            "constraints": {"plan_kind": "jd_sync"},
            "jd_sync_state": {
                "jobs_by_key": {"job-1": {"title": "销售工程师", "sync_state": "pending"}},
                "pending_job_keys": ["job-1"],
                "completed_job_keys": [],
                "inactive_job_keys": [],
                "evidence_refs": ["scene:turn-1"],
                "recovery_attempts": [],
                "writeback_results": [],
            },
        },
    )

    assert provider.captured_requests[0].tool_choice is None
    assert "delegate_scene_context" in {tool.name for tool in provider.captured_requests[0].tools}


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
    assert "真实详情读取、本地 JD 写回验证" in continuation
    assert "pending_jobs" in continuation
    assert _LEGACY_JD_SELECTION_PHRASE not in continuation
    assert _LEGACY_CONFIG_PAGE_PHRASE not in continuation


def test_jd_sync_continuation_with_action_candidates_requires_scene_hid_detail_entry() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "已完成部分 JD 同步。",
        [{"tool_name": "delegate_scene_context"}],
        [
            {
                "tool_name": "delegate_scene_context",
                "output": {
                    "status": "partial",
                    "result_data": {
                        "status": "partial",
                        "pending_jobs": [{"external_id": "e23", "title": "产品实习生"}],
                        "action_candidates": [
                            {
                                "kind": "open_job_detail_or_safe_edit",
                                "tool_name": "hid_action",
                                "ref": "job-title-product",
                                "label": "产品实习生",
                            }
                        ],
                    },
                },
            }
        ],
        0,
        {},
    )

    assert continuation is not None
    assert "必须调用 delegate_scene_context" in continuation
    assert "VirtualHID/HID 页面内操作进入 JD 详情" in continuation
    assert "structured_action_plan" in continuation
    assert "真实详情读取、本地 JD 写回验证" in continuation
    assert "pending_jobs" in continuation
    assert _LEGACY_JD_SELECTION_PHRASE not in continuation
    assert _LEGACY_CONFIG_PAGE_PHRASE not in continuation


def test_jd_sync_continuation_treats_empty_local_jd_library_as_scene_bootstrap_not_blocker() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    continuation = resolver(
        "当前无法继续执行 JD 同步：本地工作区中没有可用的 JD 记录可供推进，"
        "且我这边未获得可用于观察/操作 zhipin 浏览器会话的有效页面证据。",
        [],
        [],
        0,
        {},
    )

    assert continuation is not None
    assert "本轮没有调用任何 scene 或业务工具" in continuation
    assert "必须调用 delegate_scene_context" in continuation
    assert "真实详情读取、本地 JD 写回验证" in continuation
    assert "pending_jobs" in continuation
    assert _LEGACY_JD_SELECTION_PHRASE not in continuation
    assert _LEGACY_CONFIG_PAGE_PHRASE not in continuation


def test_jd_sync_continuation_respects_explicit_attempt_limit() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync", max_attempts=2)
    assert resolver is not None

    continuation = resolver(
        "已完成部分 JD 同步，但未完成全量详情读取，当前 partial。",
        [{"tool_name": "delegate_scene_context"}],
        [{"tool_name": "delegate_scene_context", "result": {"status": "partial"}}],
        2,
    )

    assert continuation is None


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


def test_jd_sync_action_plan_from_state_projects_pending_safe_actions() -> None:
    plan = _jd_sync_action_plan_from_state(
        {
            "jobs_by_key": {"e23": {"title": "产品实习生", "sync_state": "pending"}},
            "pending_job_keys": ["e23"],
            "pending_actions_by_job_key": {
                "e23": [
                    {
                        "kind": "open_job_detail_or_safe_edit",
                        "tool_name": "hid_action",
                        "bound_ref": "e23",
                        "label": "产品实习生",
                    }
                ]
            },
            "last_recovery_next_action": {"tool_name": "hid_action", "bound_ref": "e23"},
        }
    )

    assert plan == [
        {
            "job_key": "e23",
            "job": {"title": "产品实习生", "sync_state": "pending"},
            "safe_action_candidates": [
                {
                    "kind": "open_job_detail_or_safe_edit",
                    "tool_name": "hid_action",
                    "bound_ref": "e23",
                    "label": "产品实习生",
                }
            ],
            "recovery_next_action": {"tool_name": "hid_action", "bound_ref": "e23"},
        }
    ]


def test_jd_sync_continuation_treats_in_progress_scene_result_as_recoverable() -> None:
    result_data = {
        "status": "in_progress",
        "completed_job_details": [
            {
                "title": "产品实习生",
                "description": "岗位职责、任职要求、地点、部门等完整职位详情已在 scene 证据中确认可见。",
                "requirements": "完整任职要求已在职位详情页中确认可见。",
            }
        ],
        "remaining_work": ["read concrete responsibilities and requirements before writeback"],
    }

    assert _outcome_from_structured_result_data(result_data) == ("continue", "continue")
    assert _jd_sync_result_data_needs_tool_continuation(result_data)
    assert _jd_sync_scene_result_needs_continuation({"status": "in_progress", "result_data": result_data})


def test_jd_sync_continuation_retries_after_boss_main_navigation_recovery() -> None:
    resolver = _final_output_continuation_resolver(agent_kind="jd_sync")
    assert resolver is not None

    scene_output = {
        "status": "blocked",
        "summary": "已通过 BOSS 主导航 职位管理 可见入口恢复并观察到职位管理页面；仍需读取职位列表或职位详情。",
        "result_data": {
            "status": "blocked",
            "observed_jobs": [],
            "completed_job_details": [],
            "blockers": [
                {
                    "kind": "jd_sync_recovered_to_job_management_needs_detail_read",
                    "recoverable": True,
                }
            ],
            "remaining_work": ["read_job_list_or_detail_after_job_management_recovery"],
        },
    }

    continuation = resolver(
        "已阻塞。",
        [{"tool_name": "delegate_scene_context"}],
        [{"tool_name": "delegate_scene_context", "output": scene_output}],
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
