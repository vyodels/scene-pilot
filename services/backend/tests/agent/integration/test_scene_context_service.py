from __future__ import annotations

import json
from pathlib import Path

import pytest

from recruit_station.core.settings import AppSettings
from recruit_station.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_station.models.domain import AgentGlobalState, AgentLearning, EnvironmentSnapshot, ExecutionEpisode, ExecutionPlan, TaskSpec
from recruit_station.plugins.host import PluginHost
from agent_runtime.fixtures import LLMResponse, ToolCall
from agent_runtime.fixtures import ScriptedProvider
from recruit_station.capabilities.tools import ToolDefinition, ToolRegistry
from recruit_station.agents.outcome import AgentTurnOutcome
from recruit_station.services.scene_context import (
    SceneContextService,
    _scene_tool_registry,
    _should_retry_scene_for_missing_hid,
    _should_retry_scene_for_transient_hid_error,
)


def _session_factory(tmp_path: Path):
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'scene-context.db'}",
        provider_config={},
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)


def test_scene_tool_registry_excludes_recruiting_business_tools() -> None:
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Observe browser.",
            parameters={"type": "object"},
            handler=lambda arguments: {"ok": True},
            metadata={"capabilities": ["browser"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="Execute HID action.",
            parameters={"type": "object"},
            handler=lambda arguments: {"ok": True},
            metadata={"capabilities": ["computer"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="transition_application",
            description="Move application state.",
            parameters={"type": "object"},
            handler=lambda arguments: {"ok": True},
            metadata={
                "capabilities": ["candidate", "state_transition", "recruit_write"],
                "requires_confirmation": True,
                "risk_level": "high",
            },
        )
    )
    tools.register(
        ToolDefinition(
            name="local_download_attribute",
            description="Attribute browser download.",
            parameters={"type": "object"},
            handler=lambda arguments: {"ok": True},
            metadata={"capabilities": ["scene", "download", "document"], "real_environment": True},
        )
    )

    scene_registry = _scene_tool_registry(tools, request={}, browser_semantics={})

    assert set(scene_registry.tools) == {"browser_snapshot", "hid_action", "local_download_attribute"}


def test_scene_context_creates_episode_records_without_learning_side_effects(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="tool-1", name="browser_snapshot", arguments={"capture": "jd-detail"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="已完成页面观察并提炼出业务摘要。"),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Capture current browser scene.",
            parameters={"type": "object", "properties": {"capture": {"type": "string"}}, "additionalProperties": False},
            handler=lambda arguments: {
                "source": "browser",
                "environment_key": "tab-1",
                "url": "https://example.test/jobs/1",
                "title": "JD Detail",
                "page_type": "job_detail",
                "observed_entities": [{"kind": "job_description", "external_id": "jd-1"}],
                "affordances": [{"kind": "button", "label": "立即沟通"}],
                "runtime_metadata": {"capture": arguments.get("capture")},
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "观察 JD 页面",
            "instruction": "观察当前页面并总结 JD 详情是否已经可用于后续同步。",
            "success_criteria": {"must_include": ["岗位基本信息", "页面可继续动作"]},
            "output_contract": {"status": "string", "summary": "string"},
            "preferred_capabilities": ["browser"],
            "environment_requirements": {"environment_kind": "job_detail"},
            "context": {"environment_kind": "job_detail"},
            "input": {"job_description_id": "jd-local-1"},
        }
    )

    assert result["status"] == "completed"
    assert result["summary"] == "已完成页面观察并提炼出业务摘要。"
    assert result["blockers"] == []
    assert all("url" not in artifact for artifact in result["artifacts"])

    with session_factory() as session:
        task_specs = session.query(TaskSpec).all()
        plans = session.query(ExecutionPlan).all()
        episodes = session.query(ExecutionEpisode).all()
        snapshots = session.query(EnvironmentSnapshot).all()
        learning = session.query(AgentLearning).all()

        assert len(task_specs) == 1
        assert len(plans) == 1
        assert len(episodes) == 1
        assert len(snapshots) >= 2
        assert learning == []

        episode = episodes[0]
        assert episode.id == result["episode_id"]
        assert episode.status == "completed"
        assert episode.result_summary == "已完成页面观察并提炼出业务摘要。"
        assert episode.execution_kind == "browser_scene_execution"
        assert episode.summary_scope == "business_summary_only"
        assert episode.evidence_scope == "episode_scoped"
        assert episode.memory_policy == "disabled"
        assert episode.learning_policy == "disabled"
        assert len(list(episode.observations or [])) >= 1
        assert len(list(episode.actions or [])) >= 1
        assert int((episode.metrics or {}).get("environment_snapshot_count") or 0) >= 2

        requested_snapshot = next(item for item in snapshots if item.status == "requested")
        observed_snapshot = next(item for item in snapshots if item.status == "observed")
        assert requested_snapshot.environment_kind == "job_detail"
        assert observed_snapshot.environment_kind == "job_detail"
        assert observed_snapshot.display_label == "JD Detail"
        assert observed_snapshot.resource_locator == "https://example.test/jobs/1"
        assert observed_snapshot.action_hints == [{"kind": "button", "label": "立即沟通"}]
        assert observed_snapshot.environment_descriptor["environment_kind"] == "job_detail"


def test_scene_context_with_browser_target_requires_browser_or_hid_tool_evidence(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(content="已完成活跃 JD 同步检查。"),
        ],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "同步招聘站点 JD",
            "instruction": "从招聘站点发现并同步所有活跃 JD。",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "http://127.0.0.1:50149/", "host": "127.0.0.1:50149"},
        }
    )

    assert result["status"] == "blocked"
    assert result["blockers"] == [
        {
            "kind": "missing_browser_hid_evidence",
            "message": (
                "scene context has a browser target but produced no successful browser/HID tool result; "
                "the scene cannot be marked completed without observed browser or computer execution evidence."
            ),
        }
    ]

    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        assert episode.status == "blocked"
        assert episode.metrics["blocker_count"] == 1
        assert episode.metrics["tool_result_count"] == 0


def test_scene_context_blocks_new_hid_actions_when_workspace_is_paused(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    with session_factory() as session:
        state = AgentGlobalState(id="singleton")
        state.autonomous_paused = False
        state.state_metadata = {"workspace_control": {"state": "running"}}
        session.add(state)
        session.commit()

    hid_calls: list[dict[str, object]] = []

    def _browser_list_tabs(arguments: dict[str, object]) -> dict[str, object]:
        with session_factory() as session:
            state = session.get(AgentGlobalState, "singleton")
            assert state is not None
            state.autonomous_paused = True
            state.state_metadata = {"workspace_control": {"state": "paused", "reason": "manual pause"}}
            session.commit()
        return {
            "success": True,
            "tabs": [{"tabId": 7, "url": "http://127.0.0.1:50149/jobs", "title": "职位列表"}],
        }

    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="tabs", name="browser_list_tabs", arguments={}),
                    ToolCall(
                        id="click",
                        name="hid_action",
                        arguments={
                            "target": {"host": "127.0.0.1:50149", "tabId": 7},
                            "context": {"host": "127.0.0.1:50149"},
                            "primitives": [{"type": "click", "at": {"x": 20, "y": 30}}],
                        },
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content='{"status":"blocked","summary":"workspace paused"}'),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List browser tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=_browser_list_tabs,
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="Execute HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: hid_calls.append(dict(arguments)) or {"ok": True},
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "暂停后阻止新 HID",
            "instruction": "观察页面后尝试点击。",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "http://127.0.0.1:50149/", "host": "127.0.0.1:50149"},
        }
    )

    assert result["status"] == "blocked"
    assert hid_calls == []
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        tool_results = [
            (item["payload"]["tool_name"], item["payload"]["content"])
            for item in episode.actions
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
        ]
        assert tool_results == [
            (
                "browser_list_tabs",
                {
                    "success": True,
                    "tabs": [{"tabId": 7, "url": "http://127.0.0.1:50149/jobs", "title": "职位列表"}],
                },
            ),
        ]
    assert result["result_data"]["status"] == "paused"
    assert result["result_data"]["blockers"] == [
        {
            "kind": "workspace_paused",
            "message": "workspace is paused; scene execution stopped before issuing another action.",
        }
    ]


def test_scene_context_canonicalizes_browser_hid_capability_aliases(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[LLMResponse(content="需要继续执行页面动作。")],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    service.delegate(
        {
            "instruction": "读取职位列表并进入详情。",
            "preferred_capabilities": ["browser-mcp", "VirtualHID"],
            "browser_target": {"url": "http://127.0.0.1:50149/"},
        }
    )

    with session_factory() as session:
        task_spec = session.query(TaskSpec).one()
        episode = session.query(ExecutionEpisode).one()

    assert task_spec.preferred_capabilities == ["browser", "computer"]
    assert episode.runtime_metadata["preferred_capabilities"] == ["browser", "computer"]
    assert episode.runtime_metadata["execution_contract"]["execution_kind"] == "browser_computer_scene_execution"
    assert "目标浏览器窗口置前" in task_spec.instruction
    assert "activateTarget" in task_spec.instruction
    assert "不得在未尝试 hid_action 的情况下声称当前能力仅支持只读观察" in task_spec.instruction
    assert "E_CURSOR_INTERFERENCE" in task_spec.instruction
    assert "至少完成一次重新观察后的重试" in task_spec.instruction
    assert "E_NOT_FRONTMOST" in task_spec.instruction
    assert "浏览器地址栏、直接输入 URL、粘贴 URL 和浏览器外壳导航不属于招聘网站页面内业务动作" in task_spec.instruction
    assert 'key(keyCode=37, modifiers=["cmd"])' not in task_spec.instruction


def test_scene_context_timeout_is_episode_boundary_not_same_engine_retry() -> None:
    outcome = AgentTurnOutcome(
        status="escalate",
        gate_signal="escalate",
        final_output="E_SCENE_TIMEOUT: scene_context turn exceeded timeoutSeconds=180",
        result_data={
            "status": "blocked",
            "blockers": [{"kind": "scene_context_timeout", "message": "timed out"}],
        },
    )
    events = [
        {
            "type": "tool_event",
            "payload": {
                "kind": "tool_result_ready",
                "tool_name": "browser_snapshot",
                "is_error": False,
                "content": {
                    "success": True,
                    "url": "http://127.0.0.1:50149/",
                    "affordances": [{"kind": "link", "href": "/jobs/jd-sales-001", "clickPoint": {"x": 10, "y": 10}}],
                },
            },
        }
    ]
    blockers = [{"kind": "scene_context_timeout", "message": "timed out"}]

    assert not _should_retry_scene_for_missing_hid(
        outcome=outcome,
        blockers=blockers,
        events=events,
        request={"preferred_capabilities": ["browser", "computer"]},
        available_tools=["browser_snapshot", "hid_action"],
    )
    assert not _should_retry_scene_for_transient_hid_error(
        outcome=outcome,
        blockers=blockers,
        events=events,
    )


def test_scene_context_executes_hid_without_nested_permission_boundary(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="snapshot", name="browser_snapshot", arguments={}),
                    ToolCall(
                        id="hid",
                        name="hid_action",
                        arguments={
                            "target": {"bundleId": "com.google.Chrome", "host": "127.0.0.1:50149"},
                            "geometry": {"coordSpace": "viewport", "pageScale": 1},
                            "context": {"host": "127.0.0.1:50149"},
                            "primitives": [{"type": "click", "at": {"x": 10, "y": 10}}],
                        },
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="已完成 HID 动作后的页面确认。"),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Snapshot.",
            parameters={"type": "object", "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "snapshot": {
                    "url": "http://127.0.0.1:50149/",
                    "title": "职位列表",
                    "clickables": [{"href": "/jobs/jd-sales-001", "clickPoint": {"viewport": {"x": 10, "y": 10}}}],
                },
            },
            external_target=True,
            metadata={"capabilities": ["browser"], "requires_confirmation": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="HID.",
            parameters={"type": "object", "additionalProperties": True},
            handler=lambda arguments: {"ok": True, "events": [{"type": "leftMouseDown"}, {"type": "leftMouseUp"}]},
            external_target=True,
            metadata={"capabilities": ["computer"], "requires_confirmation": True},
        )
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "instruction": "观察页面并点击职位入口。",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "http://127.0.0.1:50149/"},
        }
    )

    assert result["status"] == "completed"
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
    assert any(
        item["type"] == "tool_event"
        and item["payload"]["kind"] == "tool_result_ready"
        and item["payload"]["tool_name"] == "hid_action"
        for item in episode.actions
    )


def test_scene_context_active_tab_mismatch_is_recoverable_target_identification(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="active", name="browser_get_active_tab", arguments={}),
                    ToolCall(id="tabs", name="browser_list_tabs", arguments={}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="已找到同源页签，可继续观察。"),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_get_active_tab",
            description="Get active browser tab.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda arguments: {"success": True, "tab": {"tabId": 1, "url": "http://127.0.0.1:5174/"}},
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List browser tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda arguments: {"success": True, "tabs": [{"tabId": 2, "url": "http://127.0.0.1:50149/jobs"}]},
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "instruction": "找到目标招聘站点页签。",
            "preferred_capabilities": ["browser"],
            "browser_target": {"url": "http://127.0.0.1:50149/"},
        }
    )

    assert result["status"] == "completed"
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        active_result = next(
            item["payload"]["content"]
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "browser_get_active_tab"
        )
    assert active_result["success"] is True
    assert active_result["targetMatch"] is False
    assert "not a terminal blocker" in active_result["message"]


def test_scene_context_only_uses_round_budget_when_explicit(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(provider_name="scene-scripted", responses=[LLMResponse()])

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "显式预算测试",
            "instruction": "保持继续，直到显式预算触发。",
            "max_llm_invocations": 1,
        }
    )

    assert result["status"] == "blocked"
    assert result["blockers"][0]["kind"] == "budget_exhausted"
    assert result["metrics"]["engine_output_count"] >= 1


def test_scene_context_rejects_browser_tab_from_different_target_origin(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="tabs", name="browser_list_tabs", arguments={"currentWindowOnly": False}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(id="select", name="browser_select_tab", arguments={"tabId": 1}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="target mismatch",
                result_data={"status": "blocked", "reason": "target mismatch"},
            ),
        ],
    )
    select_calls: list[dict[str, object]] = []
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "tabs": [
                    {
                        "id": 1,
                        "url": "http://127.0.0.1:11111/candidate-detail.html?id=old",
                        "title": "Old mock tab",
                        "active": True,
                    }
                ],
            },
            metadata={"capabilities": ["browser"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_select_tab",
            description="Select tab.",
            parameters={"type": "object", "properties": {"tabId": {"type": "integer"}}, "additionalProperties": True},
            handler=lambda arguments: select_calls.append(dict(arguments)) or {"success": True, "tabId": arguments["tabId"]},
            metadata={"capabilities": ["browser"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "目标 origin 隔离测试",
            "instruction": "只允许操作当前 scene browser_target origin。",
            "browser_target": {"url": "http://127.0.0.1:22222/jobs", "host": "127.0.0.1"},
            "preferred_capabilities": ["browser"],
        }
    )

    assert result["status"] == "blocked"
    assert select_calls == []
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        mismatch_results = [
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "browser_select_tab"
            and item["payload"]["content"].get("error") == "scene_browser_mutation_not_allowed"
        ]
        assert mismatch_results


def test_scene_context_derives_browser_target_from_instruction_url(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    open_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="open-stale",
                        name="browser_open_tab",
                        arguments={"url": "http://127.0.0.1:64872/candidate/jobs.html", "active": True},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="stale target",
                result_data={"status": "blocked", "summary": "stale target"},
            ),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_open_tab",
            description="Open tab.",
            parameters={"type": "object", "properties": {"url": {"type": "string"}}, "additionalProperties": True},
            handler=lambda arguments: open_calls.append(dict(arguments)) or {"success": True},
            metadata={"capabilities": ["browser"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "从 instruction 提取目标 URL",
            "instruction": "在 http://127.0.0.1:64932/jobs 执行模拟招聘流程。",
            "preferred_capabilities": ["browser", "computer"],
        }
    )

    assert result["status"] == "blocked"
    assert open_calls == []
    assert result["environment_context"]["browser_target"] == {
        "host": "127.0.0.1:64932",
        "url": "http://127.0.0.1:64932/jobs",
    }
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "browser_open_tab"
            and item["payload"]["content"].get("error") == "scene_browser_mutation_not_allowed"
        ]
        assert blocked_results


def test_scene_context_does_not_mark_failed_provider_result_data_as_completed(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                content="下载记录未产生可验证的本地路径。",
                result_data={
                    "status": "failed_no_verified_local_artifact",
                    "failure_reason": "download record did not produce a verified local path",
                },
            )
        ],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "验证下载 artifact",
            "instruction": "验证下载后的本地 artifact。",
            "preferred_capabilities": ["browser"],
            "artifact_expectations": {"requires_local_artifact": True, "allowed_extensions": ["pdf"]},
        }
    )

    assert result["status"] == "error"
    assert result["summary"] == "下载记录未产生可验证的本地路径。"
    assert result["result_data"]["status"] == "failed_no_verified_local_artifact"

    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        assert episode.status == "failed"


def test_scene_context_does_not_mark_completed_result_with_unrecovered_blocker_as_completed(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="hid", name="hid_action", arguments={"id": "return-to-list"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="已完成部分同步。",
                result_data={"status": "completed", "summary": "已完成部分同步。"},
            ),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="Execute HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: (_ for _ in ()).throw(RuntimeError("PERMISSION_DENIED: login required")),
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate({"instruction": "返回列表并继续读取剩余 JD。", "preferred_capabilities": ["computer"]})

    assert result["status"] == "blocked"
    assert result["result_data"]["status"] == "blocked"
    assert result["result_data"]["reported_status"] == "completed"
    assert result["blockers"][0]["kind"] == "tool_error"

    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        assert episode.status == "blocked"


def test_scene_context_retries_once_when_model_blocks_on_single_transient_hid_error(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    hid_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="snapshot-1", name="browser_snapshot", arguments={"tabId": 1}),
                    ToolCall(id="hid-1", name="hid_action", arguments={"id": "open-detail"}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="已阻塞：E_NOT_FRONTMOST: target app is not frontmost"),
            LLMResponse(
                tool_calls=[
                    ToolCall(id="snapshot-2", name="browser_snapshot", arguments={"tabId": 1}),
                    ToolCall(id="hid-2", name="hid_action", arguments={"id": "open-detail-retry"}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="已恢复并完成详情读取。"),
        ],
    )

    def _hid_handler(arguments: dict[str, object]) -> dict[str, object]:
        hid_calls.append(dict(arguments))
        if len(hid_calls) == 1:
            raise RuntimeError("E_NOT_FRONTMOST: target app is not frontmost")
        return {"ok": True, "events": [{"type": "mouseMoved"}, {"type": "leftMouseUp"}]}

    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Capture current browser scene.",
            parameters={"type": "object", "properties": {"tabId": {"type": "number"}}, "additionalProperties": False},
            handler=lambda arguments: {
                "success": True,
                "snapshot": {
                    "url": "https://recruit.example.test/jobs",
                    "title": "Jobs",
                    "clickables": [{"role": "link", "href": "https://recruit.example.test/jobs/1", "label": "国际销售工程师"}],
                },
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="Execute HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=_hid_handler,
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate({"instruction": "进入职位详情。", "preferred_capabilities": ["browser", "computer"]})

    assert result["status"] == "completed"
    assert result["summary"] == "已恢复并完成详情读取。"
    assert result["blockers"] == []
    assert len(hid_calls) == 2
    assert "不能直接作为当前 scene 的终局 blocker" in provider.captured_requests[2].messages[-1].content


def test_scene_context_does_not_parse_final_text_json_as_result_data_or_writeback(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_text = json.dumps(
        {
            "status": "completed",
            "summary": "hidden machine payload",
            "business_writeback": {
                "tool": "attach_resume_artifact",
                "arguments": {"file_path": "/tmp/from-final-text.pdf"},
            },
        },
        ensure_ascii=False,
    )
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[LLMResponse(content=final_text, finish_reason="stop")],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate({"instruction": "Return a plain final answer that happens to look like JSON."})

    assert result["status"] == "completed"
    assert result["summary"] == final_text
    assert result["result_data"] == {}
    assert [item for item in result["artifacts"] if item.get("kind") == "local_artifact"] == []


def test_scene_context_uses_final_json_as_result_data_when_contract_requires_it(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "partial",
        "completed_job_details": [{"title": "国际销售工程师", "external_id": "jd-sales-001"}],
        "blockers": [],
        "evidence": ["opened detail page"],
    }
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[LLMResponse(content=json.dumps(final_payload, ensure_ascii=False), finish_reason="stop")],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "instruction": "Return scene result JSON.",
            "output_contract": {"result_data_required": True},
        }
    )

    assert result["status"] == "incomplete"
    assert result["result_data"] == final_payload
    assert [item for item in result["artifacts"] if item.get("kind") == "local_artifact"] == []
    assert provider.captured_requests[0].text_format == {"type": "json_object"}


def test_scene_context_blocks_completed_result_missing_required_contract_fields(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "completed",
        "business_summary": {"verified_count": 5},
    }
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[LLMResponse(content=json.dumps(final_payload, ensure_ascii=False), finish_reason="stop")],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "instruction": "Return scene result JSON.",
            "output_contract": {
                "result_data_required": True,
                "required_fields": ["status", "completed_job_details", "evidence"],
            },
        }
    )

    assert result["status"] == "blocked"
    assert result["result_data"]["contract_validation"]["status"] == "failed"
    assert result["blockers"][0]["kind"] == "output_contract_incomplete"
    assert "completed_job_details" in result["blockers"][0]["missing_fields"]


def test_scene_context_normalizes_contract_aliases_without_marking_complete(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "completed",
        "summary": {
            "active_recruiting_jobs": [
                {
                    "title": "解决方案顾问",
                    "external_id": "jd-solution-002",
                    "status": "招聘中",
                    "description": "支持售前演示。",
                    "requirements": ["4-8 年售前经验"],
                }
            ],
            "jobs_reviewed": [{"job_title": "解决方案顾问", "status": "招聘中"}],
            "notes": ["已完成 1 个 JD 的详情核验。"],
        },
    }
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[LLMResponse(content=json.dumps(final_payload, ensure_ascii=False), finish_reason="stop")],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "instruction": "Return scene result JSON.",
            "output_contract": {
                "result_data_required": True,
                "required_fields": [
                    "status",
                    "observed_jobs",
                    "completed_job_details",
                    "inactive_or_closed_jobs",
                    "activation_entry_observed",
                    "blockers",
                    "limitations",
                    "evidence",
                ],
            },
        }
    )

    assert result["status"] == "incomplete"
    assert result["blockers"] == []
    assert result["result_data"]["status"] == "partial"
    assert result["result_data"]["reported_status"] == "completed"
    assert result["result_data"]["completed_job_details"][0]["external_id"] == "jd-solution-002"
    assert result["result_data"]["observed_jobs"][0]["job_title"] == "解决方案顾问"
    assert result["result_data"]["inactive_or_closed_jobs"] == []
    assert result["result_data"]["blockers"] == []
    assert result["result_data"]["limitations"] == []
    assert result["result_data"]["activation_entry_observed"] is False
    assert result["result_data"]["evidence"] == ["已完成 1 个 JD 的详情核验。"]


def test_scene_context_uses_blocked_final_json_for_public_status_without_writeback(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_text = json.dumps(
        {
            "status": "blocked",
            "summary": "Browser/HID sequence gate blocked the next page action.",
            "business_writeback": {
                "tool": "attach_resume_artifact",
                "arguments": {"file_path": "/tmp/from-final-text.pdf"},
            },
        },
        ensure_ascii=False,
    )
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[LLMResponse(content=final_text, finish_reason="stop")],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate({"instruction": "Return a blocked scene result as final JSON."})

    assert result["status"] == "blocked"
    assert result["summary"] == "Browser/HID sequence gate blocked the next page action."
    assert result["result_data"] == {}
    assert [item for item in result["artifacts"] if item.get("kind") == "local_artifact"] == []

    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        assert episode.status == "blocked"


def test_scene_context_returns_structured_result_and_browser_computer_contract(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="tool-1", name="browser_snapshot", arguments={"tabId": 321})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="已定位下载入口与目标区域。",
                result_data={
                    "status": "completed",
                    "summary": "已定位下载入口与目标区域。",
                    "artifact": {"path": "/tmp/resume.pdf", "format": "pdf"},
                },
                finish_reason="stop",
            ),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Capture current browser scene.",
            parameters={"type": "object", "properties": {"tabId": {"type": "number"}}, "additionalProperties": False},
            handler=lambda arguments: {
                "source": "browser",
                "environment_key": "tab-321",
                "url": "https://example.test/candidates/1",
                "title": "Candidate Detail",
                "page_type": "candidate_detail",
                "observed_entities": [{"kind": "candidate", "external_id": "cand-1"}],
                "action_hints": [{"kind": "download", "label": "下载简历"}],
                "runtime_metadata": {"tabId": arguments.get("tabId")},
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "候选人简历下载检查",
            "instruction": "确认目标 tab 中的下载入口、目标区域和本地文件要求。",
            "preferred_capabilities": ["browser", "computer"],
            "environment_requirements": {
                "environment_kind": "candidate_detail",
            },
            "browser_target": {
                "application": "Google Chrome",
                "window_title": "BOSS 直聘",
                "tabId": 321,
                "host": "example.test",
                "urlPattern": "/candidates/",
            },
            "computer_target": {
                "application": "Google Chrome",
                "window_title": "BOSS 直聘",
                "postMode": "auto",
            },
            "target_regions": [
                {
                    "name": "resume_download_region",
                    "ref": "@e1",
                    "sig": "sig-download-1",
                    "label": "下载简历",
                    "hint": "visible attachment download affordance",
                    "role": "button",
                    "href": "https://recruiting.example.test/downloads/resume-1.pdf",
                    "download": "resume-1.pdf",
                    "region": {"x": 12, "y": 24, "width": 160, "height": 36},
                }
            ],
            "action_plan": {
                "steps": [
                    "click the visible resume download affordance",
                    "locate the browser download record and local path",
                ],
                "download_source": {
                    "sourceUrl": "https://recruiting.example.test/downloads/resume-1.pdf",
                    "download": "resume-1.pdf",
                    "startedAfter": "2026-04-25T09:30:00.000Z",
                    "ref": "@e1",
                    "sig": "sig-download-1",
                },
            },
            "artifact_expectations": {
                "requires_local_artifact": True,
                "accepted_file_kinds": ["pdf"],
                "verify_path": True,
                "verify_format": True,
                "download_lookup": {
                    "sourceUrl": "https://recruiting.example.test/downloads/resume-1.pdf",
                    "fileName": "resume-1.pdf",
                    "startedAfter": "2026-04-25T09:30:00.000Z",
                },
            },
            "anti_detection_policy": {"mode": "generic_human_paced", "require_browser_hid_preflight": True},
            "behavior_budget": {
                "max_candidates_per_hour": 10,
                "max_candidates_per_day": 80,
                "candidate_gap_seconds": 120,
                "page_dwell_seconds": 25,
                "max_hid_actions_per_candidate": 30,
                "retry_backoff_seconds": [30, 120],
            },
        }
    )

    assert result["status"] == "completed"
    assert result["summary"] == "已定位下载入口与目标区域。"
    assert result["result_data"] == {
        "status": "completed",
        "summary": "已定位下载入口与目标区域。",
        "artifact": {"path": "/tmp/resume.pdf", "format": "pdf"},
    }
    assert result["execution_contract"]["execution_kind"] == "browser_computer_scene_execution"
    assert result["execution_contract"]["coordinate_policy"] == "delegate_to_hid"
    assert result["execution_contract"]["browser_target"]["tab_id"] == 321
    assert result["environment_context"]["browser_target"]["host"] == "example.test"
    assert result["environment_context"]["computer_target"]["post_mode"] == "auto"
    assert result["environment_context"]["target_regions"][0]["signature"] == "sig-download-1"
    assert result["environment_context"]["target_regions"][0]["name"] == "resume_download_region"
    assert result["environment_context"]["target_regions"][0]["hint"] == "visible attachment download affordance"
    assert result["environment_context"]["target_regions"][0]["href"] == "https://recruiting.example.test/downloads/resume-1.pdf"
    assert result["environment_context"]["artifact_expectations"]["requires_local_artifact"] is True
    assert result["environment_context"]["artifact_expectations"]["download_lookup"]["source_url"] == "https://recruiting.example.test/downloads/resume-1.pdf"
    assert result["environment_context"]["artifact_expectations"]["download_lookup"]["expected_filename"] == "resume-1.pdf"
    assert result["environment_context"]["artifact_expectations"]["download_lookup"]["started_after"] == "2026-04-25T09:30:00.000Z"
    assert result["execution_contract"]["anti_detection_policy"]["mode"] == "generic_human_paced"
    assert result["execution_contract"]["behavior_budget"]["max_hid_actions_per_candidate"] == 30

    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        runtime_metadata = dict(episode.runtime_metadata or {})
        execution_contract = dict(runtime_metadata.get("execution_contract") or {})
        environment_context = dict(runtime_metadata.get("environment_context") or {})

        assert execution_contract["coordinate_policy"] == "delegate_to_hid"
        assert execution_contract["browser_target"]["tab_id"] == 321
        assert execution_contract["action_plan"][0]["steps"][0] == "click the visible resume download affordance"
        assert execution_contract["action_plan"][0]["download_source"]["source_url"] == "https://recruiting.example.test/downloads/resume-1.pdf"
        assert execution_contract["action_plan"][0]["download_source"]["require_source_correlation"] is True
        assert execution_contract["target_regions"][0]["signature"] == "sig-download-1"
        assert environment_context["computer_target"]["post_mode"] == "auto"
        assert environment_context["artifact_expectations"]["allowed_extensions"] == ["pdf"]
        assert runtime_metadata["anti_detection_policy"]["require_browser_hid_preflight"] is True
        assert runtime_metadata["behavior_budget"]["candidate_gap_seconds"] == 120


def test_scene_context_uses_provider_result_data_for_artifacts_and_writeback(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "completed",
        "summary": "已定位并验证本地简历 artifact。",
        "artifact": {
            "artifact_type": "resume",
            "file_name": "candidate-resume.pdf",
            "file_path": "/tmp/candidate-resume.pdf",
            "format": "pdf",
            "verified": True,
            "source_url": "https://recruiting.example.test/downloads/candidate-resume.pdf",
            "final_url": "https://recruiting.example.test/downloads/candidate-resume.pdf",
        },
        "browser_download": {
            "located": True,
            "state": "complete",
            "exists": True,
            "sourceUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
            "finalUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
            "filename": "/tmp/candidate-resume.pdf",
        },
        "business_writeback": {
            "tool": "attach_resume_artifact",
            "arguments": {
                "application_id": "app-1",
                "source": "site",
                "artifact_type": "resume",
                "file_name": "candidate-resume.pdf",
                "file_path": "/tmp/candidate-resume.pdf",
                "metadata": {
                    "browser_download": {
                        "located": True,
                        "state": "complete",
                        "sourceUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
                        "finalUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
                    }
                },
            },
        },
    }
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                content="已定位并验证本地简历 artifact。",
                result_data=final_payload,
                finish_reason="stop",
            )
        ],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "结构化 artifact 返回",
            "instruction": "返回可供业务写入的 verified local artifact result_data。",
            "preferred_capabilities": ["browser", "computer"],
            "artifact_expectations": {"requires_local_artifact": True, "allowed_extensions": ["pdf"]},
        }
    )

    assert result["status"] == "completed"
    assert result["result_data"]["artifact"]["file_path"] == "/tmp/candidate-resume.pdf"
    assert result["result_data"]["browser_download"]["located"] is True
    assert result["result_data"]["business_writeback"]["tool"] == "attach_resume_artifact"
    local_artifacts = [item for item in result["artifacts"] if item.get("kind") == "local_artifact"]
    assert local_artifacts[0] == {
        "kind": "local_artifact",
        "source_key": "artifact",
        "file_path": "/tmp/candidate-resume.pdf",
        "file_name": "candidate-resume.pdf",
        "artifact_type": "resume",
        "format": "pdf",
        "verified": True,
        "source_url": "https://recruiting.example.test/downloads/candidate-resume.pdf",
        "final_url": "https://recruiting.example.test/downloads/candidate-resume.pdf",
    }
    assert local_artifacts[1] == {
        "kind": "local_artifact",
        "source_key": "browser_download",
        "file_path": "/tmp/candidate-resume.pdf",
        "state": "complete",
        "verified": True,
        "source_url": "https://recruiting.example.test/downloads/candidate-resume.pdf",
        "final_url": "https://recruiting.example.test/downloads/candidate-resume.pdf",
    }


def test_scene_context_does_not_treat_plain_filename_as_local_artifact(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                content="下载记录已定位，但尚未得到本地路径。",
                result_data={
                    "status": "blocked",
                    "browser_download": {
                        "located": True,
                        "state": "complete",
                        "filename": "candidate-resume.pdf",
                        "fileName": "candidate-resume.pdf",
                        "sourceUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
                    },
                },
                finish_reason="stop",
            )
        ],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate({"instruction": "Return a located record without a local path."})

    assert result["status"] == "blocked"
    assert result["result_data"]["browser_download"]["filename"] == "candidate-resume.pdf"
    assert [item for item in result["artifacts"] if item.get("kind") == "local_artifact"] == []


def test_scene_context_promotes_browser_download_path_without_duplicate_artifact(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                content="已定位浏览器下载记录和本地路径。",
                result_data={
                    "status": "completed",
                    "browser_download": {
                        "located": True,
                        "state": "complete",
                        "exists": True,
                        "filename": "/tmp/candidate-resume.pdf",
                        "fileName": "candidate-resume.pdf",
                        "sourceUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
                        "finalUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
                    },
                },
                finish_reason="stop",
            )
        ],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate({"instruction": "Return a located browser download path."})

    local_artifacts = [item for item in result["artifacts"] if item.get("kind") == "local_artifact"]
    assert local_artifacts == [
        {
            "kind": "local_artifact",
            "source_key": "browser_download",
            "file_path": "/tmp/candidate-resume.pdf",
            "file_name": "candidate-resume.pdf",
            "state": "complete",
            "verified": True,
            "source_url": "https://recruiting.example.test/downloads/candidate-resume.pdf",
            "final_url": "https://recruiting.example.test/downloads/candidate-resume.pdf",
        }
    ]


def test_scene_context_passes_browser_semantics_into_hid_action(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    captured_hid_arguments: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="tool-1", name="browser_snapshot", arguments={"tabId": 613}),
                    ToolCall(
                        id="tool-2",
                        name="hid_action",
                        arguments={
                            "id": "click-download",
                            "target": {"tabId": 613},
                            "geometry": {"coordSpace": "viewport", "pageScale": 1, "viewportSize": {"width": 1440, "height": 900}},
                            "options": {"postMode": "global", "dryRun": True, "behaviorMode": "normal", "profile": {"speed": "caller-owned"}},
                            "primitives": [{"type": "click", "at": {"x": 1642, "y": 56}, "button": "left", "profile": {"speed": "caller-owned"}}],
                            "x": 1642,
                            "y": 56,
                        },
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="已完成 HID dry-run。"),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Capture current browser scene.",
            parameters={"type": "object", "properties": {"tabId": {"type": "number"}}, "additionalProperties": False},
            handler=lambda arguments: {
                "success": True,
                "snapshot": {
                    "url": "https://recruit.example.test/candidate/613",
                    "title": "Candidate Detail",
                    "viewport": {
                        "innerWidth": 1440,
                        "innerHeight": 900,
                        "outerWidth": 1510,
                        "outerHeight": 1120,
                        "scrollX": 0,
                        "scrollY": 128,
                        "screenX": 1280,
                        "screenY": -1180,
                        "viewportInScreen": {"x": 112, "y": 144, "width": 1440, "height": 900},
                        "visualViewport": {"scale": 1},
                    },
                },
                "tabId": arguments.get("tabId"),
                "target": {"tabId": arguments.get("tabId"), "windowId": 88, "url": "https://recruit.example.test/candidate/613", "title": "Candidate Detail"},
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="Execute HID action.",
            parameters={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "target": {"type": "object"},
                    "geometry": {"type": "object"},
                    "primitives": {"type": "array"},
                    "context": {"type": "object"},
                    "options": {"type": "object"},
                },
                "additionalProperties": True,
            },
            handler=lambda arguments: captured_hid_arguments.append(dict(arguments)) or {"ok": True},
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "候选人简历下载 dry-run",
            "instruction": "先读取浏览器页面，再对下载入口做 HID dry-run。",
            "preferred_capabilities": ["browser", "computer"],
            "environment_requirements": {
                "browser_target": {
                    "tabId": 613,
                    "url": "https://recruit.example.test/candidate/613",
                }
            },
        }
    )

    assert result["status"] == "completed"
    assert captured_hid_arguments
    hid_arguments = captured_hid_arguments[0]
    assert hid_arguments["target"]["host"] == "recruit.example.test"
    assert hid_arguments["target"]["bundleId"] == "com.google.Chrome"
    assert hid_arguments["target"]["windowId"] == 88
    assert hid_arguments["target"]["windowTitle"] == "Candidate Detail"
    assert hid_arguments["target"]["browserWindowBounds"] == {"x": 1280, "y": -1180, "width": 1510, "height": 1120}
    assert hid_arguments["context"]["host"] == "recruit.example.test"
    assert hid_arguments["context"]["url"] == "https://recruit.example.test/candidate/613"
    assert hid_arguments["primitives"] == [{"type": "click", "at": {"x": 1642, "y": 56}, "button": "left"}]
    assert "behaviorMode" not in hid_arguments["options"]
    assert "profile" not in hid_arguments["options"]
    assert hid_arguments["options"]["postMode"] == "auto"
    assert "viewportInScreen" not in hid_arguments["geometry"]
    assert hid_arguments["geometry"]["scrollOffset"] == {"x": 0, "y": 128}
    assert hid_arguments["geometry"]["viewportSize"] == {"x": 0, "y": 0, "width": 1440, "height": 900}

    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        assert any(
            item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "hid_action"
            for item in episode.actions
        )


def test_scene_context_adds_viewport_geometry_to_keyboard_hid_action(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    captured_hid_arguments: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="snapshot", name="browser_snapshot", arguments={"tabId": 613}),
                    ToolCall(
                        id="open-detail",
                        name="hid_action",
                        arguments={
                            "id": "open-jd-detail",
                            "target": {"tabId": 613, "windowId": 88, "windowTitle": "职位列表 · Recruiting Workspace"},
                            "primitives": [
                                {"type": "key", "keyCode": 48},
                                {"type": "key", "keyCode": 36},
                            ],
                        },
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="已完成键盘导航。"),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Capture current browser scene.",
            parameters={"type": "object", "properties": {"tabId": {"type": "number"}}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "snapshot": {
                    "url": "https://recruit.example.test/jobs",
                    "title": "职位列表 · Recruiting Workspace",
                    "viewport": {
                        "innerWidth": 1526,
                        "innerHeight": 1039,
                        "scrollX": 0,
                        "scrollY": 0,
                        "visualViewport": {"scale": 1},
                    },
                },
                "tabId": arguments.get("tabId"),
                "target": {
                    "tabId": arguments.get("tabId"),
                    "windowId": 88,
                    "url": "https://recruit.example.test/jobs",
                    "title": "职位列表 · Recruiting Workspace",
                },
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="Execute HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: captured_hid_arguments.append(dict(arguments)) or {"ok": True},
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "键盘进入 JD 详情",
            "instruction": "通过页面内键盘焦点进入同源 JD 详情。",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://recruit.example.test/jobs", "tabId": 613},
        }
    )

    assert result["status"] == "completed"
    assert captured_hid_arguments
    hid_arguments = captured_hid_arguments[0]
    assert hid_arguments["target"]["bundleId"] == "com.google.Chrome"
    assert hid_arguments["target"]["host"] == "recruit.example.test"
    assert hid_arguments["geometry"]["viewportSize"] == {"x": 0, "y": 0, "width": 1526, "height": 1039}
    assert hid_arguments["geometry"]["scrollOffset"] == {"x": 0, "y": 0}


def test_scene_context_coerces_hid_host_to_full_scene_origin_when_port_is_missing(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    captured_hid_arguments: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="tabs", name="browser_list_tabs", arguments={}),
                    ToolCall(id="observe", name="browser_snapshot", arguments={"tabId": 99}),
                    ToolCall(
                        id="click",
                        name="hid_action",
                        arguments={
                            "target": {"host": "127.0.0.1", "tabId": 99, "windowTitle": "职位列表 · Recruiting Workspace"},
                            "context": {"host": "127.0.0.1"},
                            "geometry": {"coordSpace": "viewport", "pageScale": 1},
                            "primitives": [{"type": "click", "at": {"x": 420, "y": 360}, "button": "left"}],
                        },
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="已进入详情。"),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "tabs": [
                    {
                        "id": 99,
                        "tabId": 99,
                        "windowId": 1136766964,
                        "url": "http://127.0.0.1:50149/jobs",
                        "title": "职位列表 · Recruiting Workspace",
                        "active": True,
                    }
                ],
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Snapshot.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "snapshot": {"url": "http://127.0.0.1:50149/jobs", "title": "职位列表 · Recruiting Workspace"},
                "tabId": arguments.get("tabId"),
                "target": {
                    "tabId": arguments.get("tabId"),
                    "windowId": 1136766964,
                    "url": "http://127.0.0.1:50149/jobs",
                    "title": "职位列表 · Recruiting Workspace",
                },
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: captured_hid_arguments.append(dict(arguments)) or {"success": True},
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "进入 JD 详情",
            "instruction": "进入首个职位详情。",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "http://127.0.0.1:50149/", "host": "127.0.0.1:50149"},
        }
    )

    assert result["status"] == "completed"
    assert captured_hid_arguments
    hid_arguments = captured_hid_arguments[0]
    assert hid_arguments["target"]["host"] == "127.0.0.1:50149"
    assert hid_arguments["context"]["host"] == "127.0.0.1:50149"
    assert hid_arguments["target"]["windowId"] == 1136766964


def test_scene_context_retries_blocked_browser_only_turn_with_hid_action(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    captured_hid_arguments: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="tabs", name="browser_list_tabs", arguments={}),
                    ToolCall(id="snapshot", name="browser_snapshot", arguments={"tabId": 1}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content='{"status":"blocked","summary":"需要进入详情，但当前只看到列表。"}'),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="hid",
                        name="hid_action",
                        arguments={
                            "id": "click-detail",
                            "target": {"tabId": 1},
                            "geometry": {"coordSpace": "viewport"},
                            "primitives": [{"type": "click", "at": {"x": 420, "y": 260}, "button": "left"}],
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content='{"status":"completed","summary":"已尝试 HID 并完成后续观察。"}'),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List browser tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda arguments: {
                "success": True,
                "tabs": [{"tabId": 1, "windowId": 88, "url": "https://recruit.example.test/jobs", "title": "Jobs", "active": True}],
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Capture current browser scene.",
            parameters={"type": "object", "properties": {"tabId": {"type": "number"}}, "additionalProperties": False},
            handler=lambda arguments: {
                "success": True,
                "snapshot": {
                    "url": "https://recruit.example.test/jobs",
                    "title": "Jobs",
                    "viewport": {"scrollX": 0, "scrollY": 0, "innerWidth": 1200, "innerHeight": 800},
                    "clickables": [
                        {
                            "ref": "@detail",
                            "tag": "a",
                            "role": "link",
                            "text": "查看职位详情",
                            "href": "https://recruit.example.test/jobs/1",
                            "disabled": False,
                            "inViewport": True,
                            "clickPoint": {"viewport": {"x": 420, "y": 260}},
                        }
                    ],
                },
                "tabId": arguments.get("tabId"),
                "target": {"tabId": arguments.get("tabId"), "windowId": 88, "url": "https://recruit.example.test/jobs", "title": "Jobs"},
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="Execute HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: captured_hid_arguments.append(dict(arguments)) or {"ok": True},
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "进入详情",
            "instruction": "进入职位详情并读取内容。",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://recruit.example.test/jobs"},
        }
    )

    assert result["status"] == "completed"
    assert captured_hid_arguments
    assert captured_hid_arguments[0]["target"]["host"] == "recruit.example.test"


def test_scene_context_retries_when_transient_hid_error_is_recovered(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    hid_calls: list[dict[str, object]] = []

    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="tabs", name="browser_list_tabs", arguments={}),
                    ToolCall(id="initial-snapshot", name="browser_snapshot", arguments={"tabId": 1}),
                    ToolCall(
                        id="hid-timeout",
                        name="hid_action",
                        arguments={
                            "id": "open-detail",
                            "target": {"host": "recruit.example.test", "tabId": 1, "windowId": 88},
                            "geometry": {"coordSpace": "viewport"},
                            "primitives": [{"type": "click", "at": {"x": 420, "y": 260}, "button": "left"}],
                            "options": {"timeoutMs": 10_000},
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="hid-retry",
                        name="hid_action",
                        arguments={
                            "id": "open-detail-retry",
                            "target": {"host": "recruit.example.test", "tabId": 1, "windowId": 88},
                            "geometry": {"coordSpace": "viewport"},
                            "primitives": [{"type": "click", "at": {"x": 420, "y": 260}, "button": "left"}],
                            "options": {"timeoutMs": 20_000},
                        },
                    ),
                    ToolCall(id="snapshot", name="browser_snapshot", arguments={"tabId": 1}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="已阻塞：E_TIMEOUT: injector action exceeded timeoutMs=10000"),
            LLMResponse(content="已根据恢复后的详情页观察继续完成。"),
        ],
    )

    def _hid_handler(arguments: dict[str, object]) -> dict[str, object]:
        hid_calls.append(dict(arguments))
        if len(hid_calls) == 1:
            raise RuntimeError("E_TIMEOUT: injector action exceeded timeoutMs=10000")
        return {"ok": True, "events": [{"type": "mouseMoved"}, {"type": "leftMouseUp"}]}

    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List browser tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda arguments: {
                "success": True,
                "tabs": [
                    {
                        "tabId": 1,
                        "windowId": 88,
                        "url": "https://recruit.example.test/jobs",
                        "title": "Jobs",
                        "active": True,
                    }
                ],
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="Execute HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=_hid_handler,
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Capture current browser scene.",
            parameters={"type": "object", "properties": {"tabId": {"type": "number"}}, "additionalProperties": False},
            handler=lambda arguments: {
                "success": True,
                "snapshot": {
                    "url": "https://recruit.example.test/jobs/1",
                    "title": "JD Detail",
                    "viewport": {"scrollX": 0, "scrollY": 0, "innerWidth": 1200, "innerHeight": 800},
                    "text": "职位详情\\n国际销售工程师\\n岗位说明完整",
                    "clickables": [],
                },
                "tabId": arguments.get("tabId"),
                "target": {"tabId": arguments.get("tabId"), "windowId": 88, "url": "https://recruit.example.test/jobs/1", "title": "JD Detail"},
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "进入详情",
            "instruction": "进入职位详情并读取内容。",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://recruit.example.test/jobs"},
        }
    )

    assert result["status"] == "completed"
    assert result["summary"] == "已根据恢复后的详情页观察继续完成。"
    assert result["blockers"] == []
    assert len(hid_calls) == 2

    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        assert episode.status == "completed"
        assert episode.last_error is None


def test_scene_context_does_not_inherit_window_title_from_different_host(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    captured_hid_arguments: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="tabs", name="browser_list_tabs", arguments={}),
                    ToolCall(id="snapshot", name="browser_snapshot", arguments={"tabId": 99}),
                    ToolCall(
                        id="hid",
                        name="hid_action",
                        arguments={
                            "id": "click-mock",
                            "target": {"host": "127.0.0.1:50149", "tabId": 99},
                            "context": {"host": "127.0.0.1:50149"},
                            "geometry": {"coordSpace": "viewport"},
                            "primitives": [{"type": "click", "at": {"x": 40, "y": 50}}],
                        },
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="done"),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "tabs": [
                    {
                        "tabId": 1,
                        "url": "http://127.0.0.1:5174/",
                        "title": "RecruitStation",
                        "active": True,
                    }
                ]
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Snapshot target.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "snapshot": {"url": "http://127.0.0.1:50149/jobs"},
                "tabId": arguments.get("tabId"),
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: captured_hid_arguments.append(dict(arguments)) or {"success": True},
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "mock site click",
            "instruction": "observe mock site and click.",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "http://127.0.0.1:50149/", "tabId": 99},
        }
    )

    assert result["status"] == "completed"
    assert captured_hid_arguments
    assert captured_hid_arguments[0]["target"]["host"] == "127.0.0.1:50149"
    assert "windowTitle" not in captured_hid_arguments[0]["target"]


def test_scene_context_blocks_hid_before_observe_and_second_hid_before_observe(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    hid_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="hid-before-observe",
                        name="hid_action",
                        arguments={
                            "target": {"host": "recruit.example.test", "tabId": 9},
                            "context": {"host": "recruit.example.test"},
                            "primitives": [{"type": "click", "at": {"x": 20, "y": 30}}],
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[ToolCall(id="observe", name="browser_snapshot", arguments={"tabId": 9})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="first-hid",
                        name="hid_action",
                        arguments={
                            "target": {"host": "recruit.example.test", "tabId": 9},
                            "context": {"host": "recruit.example.test"},
                            "primitives": [{"type": "click", "at": {"x": 22, "y": 32}}],
                        },
                    ),
                    ToolCall(
                        id="second-hid",
                        name="hid_action",
                        arguments={
                            "target": {"host": "recruit.example.test", "tabId": 9},
                            "context": {"host": "recruit.example.test"},
                            "primitives": [{"type": "click", "at": {"x": 24, "y": 34}}],
                        },
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="sequence blocked", result_data={"status": "blocked", "summary": "sequence blocked"}),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Snapshot.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {"success": True, "snapshot": {"url": "https://recruit.example.test/jobs"}, "tabId": arguments.get("tabId")},
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: hid_calls.append(dict(arguments)) or {"success": True},
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "scene sequence gate",
            "instruction": "validate observe/hid/observe ordering.",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://recruit.example.test/jobs", "tabId": 9},
        }
    )

    assert result["status"] == "blocked"
    assert len(hid_calls) == 1
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item["payload"]["content"]
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "hid_action"
            and item["payload"]["content"].get("error") == "scene_browser_hid_sequence_blocked"
        ]
        assert [item["sequence_audit"]["reason"] for item in blocked_results] == [
            "missing_prior_browser_observation",
            "pending_browser_observation_after_hid",
        ]


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("browser_query_elements", {"tabId": 9, "selector": "a"}),
        ("browser_get_element", {"tabId": 9, "selector": "a"}),
        ("browser_debug_dom", {"tabId": 9}),
        ("browser_wait_for_text", {"tabId": 9, "text": "Ready"}),
    ],
)
def test_scene_context_blocks_wrong_tab_page_observation_tools(
    tmp_path: Path,
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    session_factory = _session_factory(tmp_path)
    called_tools: list[str] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(tool_calls=[ToolCall(id="tabs", name="browser_list_tabs", arguments={})], finish_reason="tool_calls"),
            LLMResponse(tool_calls=[ToolCall(id="observe", name=tool_name, arguments=arguments)], finish_reason="tool_calls"),
            LLMResponse(content="wrong tab blocked", result_data={"status": "blocked", "summary": "wrong tab blocked"}),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List browser tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda arguments: {
                "tabs": [
                    {"tabId": 9, "url": "https://other.example.test/jobs", "title": "Other", "active": True},
                ]
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name=tool_name,
            description="Page observation.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: called_tools.append(tool_name) or {"success": True},
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "wrong tab blocker",
            "instruction": "Do not observe the wrong tab.",
            "preferred_capabilities": ["browser"],
            "browser_target": {"url": "https://recruit.example.test/jobs", "tabId": 1},
        }
    )

    assert result["status"] == "blocked"
    assert called_tools == []
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == tool_name
            and item["payload"]["content"].get("error") == "scene_browser_target_mismatch"
        ]
        assert blocked_results


def test_scene_context_treats_virtual_hid_capability_as_computer_execution(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[LLMResponse(content="已完成 browser + HID 场景。")],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "HID capability alias check",
            "instruction": "执行需要浏览器观察和 HID 动作的通用场景。",
            "preferred_capabilities": ["browser_mcp", "virtual_hid"],
            "browser_target": {
                "tabId": 613,
                "url": "https://recruit.example.test/candidate/613",
            },
        }
    )

    assert result["execution_contract"]["execution_kind"] == "browser_computer_scene_execution"
    assert result["execution_contract"]["coordinate_policy"] == "delegate_to_hid"

    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        assert episode.execution_kind == "browser_computer_scene_execution"
        assert episode.execution_contract["coordinate_policy"] == "delegate_to_hid"


def test_scene_context_preserves_autonomous_artifact_expectation_aliases(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[LLMResponse(content="已记录 artifact 合同。")],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "Artifact expectation alias check",
            "instruction": "验证通用 artifact expectation 别名能保留到 scene 合同。",
            "preferred_capabilities": ["browser_mcp", "virtual_hid"],
            "artifact_expectations": {
                "resume_artifact_type": "resume",
                "required_format": "pdf",
                "require_verified_local_artifact_path": True,
                "require_download_source_correlation": True,
            },
        }
    )

    expectations = result["environment_context"]["artifact_expectations"]
    assert expectations["requires_local_artifact"] is True
    assert expectations["verify_path"] is True
    assert expectations["verify_format"] is True
    assert expectations["expected_kind"] == "resume"
    assert expectations["allowed_extensions"] == ["pdf"]
    assert expectations["download_lookup"]["require_source_correlation"] is True

    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        stored = episode.execution_contract["artifact_expectations"]
        assert stored["download_lookup"]["require_source_correlation"] is True


def test_scene_context_blocks_browser_open_tab_for_in_site_navigation(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    open_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="observe", name="browser_snapshot", arguments={"tabId": 1})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="browser_open_tab",
                        arguments={
                            "tabId": 613,
                            "url": "https://recruit.example.test/candidates?job=1",
                            "active": True,
                            "newWindow": False,
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="browser navigation requires HID",
                result_data={"status": "blocked", "summary": "browser navigation requires HID"},
            ),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Snapshot.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {"success": True, "snapshot": {"url": "https://recruit.example.test/jobs"}, "tabId": arguments.get("tabId")},
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_open_tab",
            description="Open or detach tab.",
            parameters={"type": "object", "properties": {"tabId": {"type": "number"}, "url": {"type": "string"}}, "additionalProperties": True},
            handler=lambda arguments: open_calls.append(dict(arguments)) or {"success": True},
            metadata={"capabilities": ["browser"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "站内导航必须走 HID",
            "instruction": "不要用 browser_open_tab 进行站内阶段推进。",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://recruit.example.test/jobs", "tabId": 1},
        }
    )

    assert result["status"] == "blocked"
    assert open_calls == []
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "browser_open_tab"
            and item["payload"]["content"].get("error") == "scene_browser_mutation_not_allowed"
        ]
        assert blocked_results


def test_scene_context_blocks_browser_reload_extension(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    reload_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="browser_reload_extension",
                        arguments={},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="browser reload is maintenance only",
                result_data={"status": "blocked", "summary": "browser reload is maintenance only"},
            ),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_reload_extension",
            description="Reload browser extension.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda arguments: reload_calls.append(dict(arguments)) or {"success": True},
            metadata={"capabilities": ["browser"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "scene 内禁止 reload browser extension",
            "instruction": "不要在 autonomous scene 内重载 browser extension。",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://recruit.example.test/jobs", "tabId": 1},
        }
    )

    assert result["status"] == "blocked"
    assert reload_calls == []
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "browser_reload_extension"
            and item["payload"]["content"].get("error") == "scene_browser_mutation_not_allowed"
        ]
        assert blocked_results


def test_scene_context_blocks_non_allowlist_hid_host(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    hid_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="observe", name="browser_snapshot", arguments={"tabId": 1})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="hid_action",
                        arguments={
                            "target": {"host": "evil.example.test", "tabId": 1},
                            "context": {"host": "evil.example.test"},
                            "primitives": [{"type": "click", "at": {"x": 20, "y": 30}}],
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="non-allowlist host blocked",
                result_data={"status": "blocked", "summary": "non-allowlist host blocked"},
            ),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Snapshot.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {"success": True, "snapshot": {"url": "https://recruit.example.test/jobs"}, "tabId": arguments.get("tabId")},
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: hid_calls.append(dict(arguments)) or {"success": True},
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "单 host allowlist",
            "instruction": "只允许操作招聘目标 host。",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://recruit.example.test/jobs", "tabId": 1},
        }
    )

    assert result["status"] == "blocked"
    assert hid_calls == []
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "hid_action"
            and item["payload"]["content"].get("error") == "scene_browser_host_not_allowed"
        ]
        assert blocked_results


def test_scene_context_surfaces_hid_overlay_blocker(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="observe", name="browser_snapshot", arguments={"tabId": 1})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="hid_action",
                        arguments={
                            "target": {"host": "recruit.example.test", "tabId": 1},
                            "context": {"host": "recruit.example.test"},
                            "primitives": [{"type": "click", "at": {"x": 20, "y": 30}}],
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="overlay blocked",
                result_data={"status": "blocked", "summary": "overlay blocked"},
            ),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Snapshot.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {"success": True, "snapshot": {"url": "https://recruit.example.test/jobs"}, "tabId": arguments.get("tabId")},
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "preflight": {
                    "browserChromeOverlayPolicy": {"status": "blocked"},
                    "browserChromeOverlay": {"status": "blocked"},
                },
            },
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )

    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "overlay blocker",
            "instruction": "overlay blocked should stop the action.",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://recruit.example.test/jobs", "tabId": 1},
        }
    )

    assert result["status"] == "blocked"
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "hid_action"
            and item["payload"]["content"].get("error") == "scene_hid_overlay_blocked"
        ]
        assert blocked_results
        assert blocked_results[0]["payload"]["content"]["evidence"]["browserChromeOverlay"]["status"] == "blocked"


def test_scene_context_surfaces_nested_hid_overlay_blocker_evidence(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="observe", name="browser_snapshot", arguments={"tabId": 1})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="hid_action",
                        arguments={
                            "target": {"host": "recruit.example.test", "tabId": 1},
                            "context": {"host": "recruit.example.test"},
                            "primitives": [{"type": "click", "at": {"x": 20, "y": 30}}],
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="overlay unknown",
                result_data={"status": "blocked", "summary": "overlay unknown"},
            ),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Snapshot.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {"success": True, "snapshot": {"url": "https://recruit.example.test/jobs"}, "tabId": arguments.get("tabId")},
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="HID action.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "isError": True,
                "result": {
                    "preflight": {
                        "browserChromeOverlay": {
                            "status": "unknown",
                            "reason": "chrome toolbar overlap could not be ruled out",
                        }
                    }
                },
            },
            metadata={"capabilities": ["scene", "computer", "computer_write"], "external_tool": True, "real_environment": True},
        )
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )

    result = service.delegate(
        {
            "title": "nested overlay blocker",
            "instruction": "overlay evidence should be retained.",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://recruit.example.test/jobs", "tabId": 1},
        }
    )

    assert result["status"] == "blocked"
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_result = next(
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "hid_action"
        )
        content = blocked_result["payload"]["content"]
        assert content["error"] == "scene_hid_overlay_blocked"
        assert content["evidence"]["browserChromeOverlay"]["status"] == "unknown"
        assert content["result"]["preflight"]["browserChromeOverlay"]["reason"] == "chrome toolbar overlap could not be ruled out"
