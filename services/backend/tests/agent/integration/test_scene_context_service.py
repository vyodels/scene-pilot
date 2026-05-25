from __future__ import annotations

import json
from pathlib import Path

import pytest

from recruit_station.core.settings import AppSettings
from recruit_station.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_station.models.domain import AgentGlobalState, AgentLearning, Candidate, CandidateApplication, ConversationSession, ConversationTurn, EnvironmentSnapshot, ExecutionEpisode, ExecutionPlan, JobDescription, TaskSpec
from recruit_station.plugins.host import PluginHost
from agent_runtime.fixtures import LLMResponse, ToolCall
from agent_runtime.fixtures import ScriptedProvider
from recruit_station.capabilities.tools import ToolDefinition, ToolRegistry
from recruit_station.agents.outcome import AgentTurnOutcome
from recruit_station.services.scene_context import (
    SceneContextService,
    _jd_sync_browser_evidence_delta_from_snapshot,
    _scene_tool_registry,
    _should_retry_scene_for_missing_hid,
    _should_retry_scene_for_transient_hid_error,
)
from recruit_station.services.jd_sync_state import (
    initial_jd_sync_state,
    reduce_jd_sync_scene_result,
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


@pytest.mark.parametrize(
    ("browser_target", "tab_url", "expected_called"),
    [
        ({"url": "https://www.zhipin.com/"}, "https://zhipin.com/web/chat/index", True),
        ({"url": "https://www.zhipin.com/"}, "https://login.zhipin.com/web/user", True),
        ({"url": "https://www.zhipin.com/"}, "https://m.zhipin.com/web/geek/job", True),
        ({"url": "https://zhipin.com/web/geek/job", "domain": "zhipin.com"}, "https://www.zhipin.com/web/chat/index", True),
        ({"url": "https://login.zhipin.com/web/user", "domain": "zhipin.com"}, "https://www.zhipin.com/web/chat/index", True),
        ({"url": "https://www.zhipin.com/web/geek/job"}, "https://login.zhipin.com/web/chat/index?status=open", True),
        ({"url": "https://www.zhipin.com/"}, "http://login.zhipin.com/web/user", False),
        ({"url": "https://www.zhipin.com:8443/"}, "https://login.zhipin.com/web/user", False),
        ({"url": "https://www.zhipin.com/"}, "https://evilzhipin.com/web/chat/index", False),
        ({"url": "https://www.zhipin.com/"}, "https://zhipin.com.evil.test/web/chat/index", False),
        ({"url": "https://www.zhipin.com/"}, "https://example.com/web/chat/index", False),
        ({"url": "https://recruit.example.test/jobs"}, "https://app.recruit.example.test/jobs", False),
        ({"url": "https://recruit.example.test/jobs", "domain": "recruit.example.test"}, "https://app.recruit.example.test/jobs", True),
    ],
)
def test_scene_context_enforces_browser_target_domain_boundary(
    tmp_path: Path,
    browser_target: dict[str, str],
    tab_url: str,
    expected_called: bool,
) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(tool_calls=[ToolCall(id="tabs", name="browser_list_tabs", arguments={})], finish_reason="tool_calls"),
            LLMResponse(tool_calls=[ToolCall(id="snapshot", name="browser_snapshot", arguments={"tabId": 9})], finish_reason="tool_calls"),
            LLMResponse(
                content="zhipin boundary checked",
                result_data={
                    "status": "completed" if expected_called else "blocked",
                    "summary": "zhipin boundary checked",
                },
            ),
        ],
    )
    snapshot_calls: list[dict[str, object]] = []
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List browser tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "tabs": [{"tabId": 9, "url": tab_url, "title": "BOSS 直聘", "active": True}],
            },
            metadata={"capabilities": ["browser"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Capture browser tab.",
            parameters={"type": "object", "properties": {"tabId": {"type": "integer"}}, "additionalProperties": True},
            handler=lambda arguments: snapshot_calls.append(dict(arguments))
            or {
                "success": True,
                "url": tab_url,
                "title": "BOSS 直聘",
                "elements": [{"role": "link", "text": "岗位管理", "href": "https://www.zhipin.com/web/chat/index"}],
            },
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
            "title": "zhipin target boundary",
            "instruction": "Recover toward JD sync on the target recruiting site.",
            "preferred_capabilities": ["browser"],
            "browser_target": browser_target,
        }
    )

    assert bool(snapshot_calls) is expected_called
    if expected_called:
        assert result["status"] == "completed"
    else:
        assert result["status"] == "blocked"
        with session_factory() as session:
            episode = session.query(ExecutionEpisode).one()
            blocked_results = [
                item
                for item in episode.observations
                if item["type"] == "tool_event"
                and item["payload"]["kind"] == "tool_result_ready"
                and item["payload"]["tool_name"] == "browser_snapshot"
                and item["payload"]["content"].get("error") == "scene_browser_target_mismatch"
            ]
            assert blocked_results


def test_scene_context_prompt_requires_zhipin_same_site_recovery_before_jd_sync_blocker(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                content="needs recovery",
                result_data={"status": "blocked", "summary": "needs recovery"},
            )
        ],
    )
    service = SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=ToolRegistry(),
        plugin_host=PluginHost(),
    )

    service.delegate(
        {
            "title": "JD sync recovery contract",
            "instruction": "Start JD sync from the already open zhipin page.",
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://www.zhipin.com/", "tabId": 9},
        }
    )

    rendered_prompt = "\n".join(message.content for request in provider.captured_requests for message in request.messages)
    assert "DOMAIN,zhipin.com" in rendered_prompt
    assert "匹配只看 URL host/domain，忽略 path 与 query" in rendered_prompt
    assert "目标 host 精确等于 browser_target.domain 或属于其子域才允许视为同一目标站点" in rendered_prompt
    assert "拼接伪装域名不匹配" in rendered_prompt
    assert "需要 origin 级比较时仍要求 scheme 和显式端口匹配" in rendered_prompt
    assert "当前可见页已经在目标站点内但不是招聘管理、岗位列表或岗位详情页，这不是 JD sync 的终局 blocker" in rendered_prompt
    assert "BOSS/zhipin 恢复不得打开新标签/新窗口，不得使用地址栏输入 URL" in rendered_prompt
    assert "如果 browser-mcp/native host 不可用导致无法观察已有页签，不得新开 BOSS/zhipin 页签" in rendered_prompt
    assert "当 browser_list_tabs 同时返回多个 zhipin.com 页签时，必须优先选择已经打开的 BOSS 招聘管理工作台页签" in rendered_prompt
    assert "/web/chat/index、/web/chat/job/、/web/geek/recommend、/web/geek/search" in rendered_prompt
    assert "不得新开另一个 zhipin 页签，也不得因为公共求职首页、城市首页或职位搜索首页处于 active 状态就持续观察这些公共页" in rendered_prompt
    assert "browser_list_tabs、browser_snapshot/query" in rendered_prompt
    assert "通过 VirtualHID 执行这些同站点入口、返回、滚动或点击" in rendered_prompt
    assert "browser_list_tabs 或 browser_get_active_tab 只能证明找到了候选 BOSS 页签" in rendered_prompt
    assert "即使活动页已经是 /web/chat/job/list 或其他招聘管理 URL，也不得据此最终回答或返回 completed" in rendered_prompt
    assert "reason=jd_sync_requires_job_list_snapshot_or_detail" in rendered_prompt
    assert "如果只存在公共首页，可使用该页可见的同站点入口在同一页签内恢复到招聘管理工作台，不得打开新标签/新窗口" in rendered_prompt
    assert "公共首页上的求职职位列表、城市职位列表或搜索结果不得作为 employer JD sync 完成证据" in rendered_prompt
    assert "不得硬编码站点选择器" in rendered_prompt
    assert "不得通过浏览器地址栏、直接输入 URL 或 browser 导航工具跳转" in rendered_prompt
    assert "招聘站点页面恢复/导航点击必须使用 browser 观察到的 BOSS 主导航可见入口：职位管理、推荐牛人、搜索、沟通" in rendered_prompt
    assert "职位管理页包含标题 职位管理、页签 全部职位/开放中/待开放/审核不通过/已关闭" in rendered_prompt
    assert "JD sync 只读职位信息，不点击 发布职位、关闭、升级、曝光刷新" in rendered_prompt
    assert "推荐牛人页包含标题 推荐牛人、推荐/最新、JD 选择器示例如 产品实习生_北京 2-4K" in rendered_prompt
    assert "实际职位标题、城市、薪资和关键词以本次启用/选中 JD 为准" in rendered_prompt
    assert "不得为了匹配截图示例而跨 JD" in rendered_prompt
    assert "沟通页包含 全部/新招呼/沟通中/已约面/已获取简历/已交换电话/已交换微信/收藏/更多" in rendered_prompt


@pytest.mark.parametrize(
    ("label", "click_point"),
    [
        ("职位管理", {"x": 88, "y": 240}),
        ("推荐牛人", {"x": 88, "y": 300}),
        ("搜索", {"x": 88, "y": 360}),
        ("沟通", {"x": 88, "y": 420}),
    ],
)
def test_scene_context_allows_recruiting_automation_boss_main_navigation_entries(
    tmp_path: Path,
    label: str,
    click_point: dict[str, int],
) -> None:
    result, hid_calls, session_factory = _run_recruiting_site_hid_click_scene(
        tmp_path,
        plan_kind="autonomous_recruiting",
        instruction="Recruiting automation: recover from the current BOSS page.",
        page_url="https://www.zhipin.com/web/chat/index",
        page_text="沟通页面",
        elements=_boss_main_navigation_entries(),
        click_point=click_point,
        final_status="completed",
    )

    assert result["status"] == "completed"
    assert len(hid_calls) == 1
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "hid_action"
            and item["payload"]["content"].get("error") == "scene_recruiting_navigation_target_blocked"
        ]
        assert blocked_results == []


def test_scene_context_allows_jd_sync_boss_main_navigation_job_management_entry(tmp_path: Path) -> None:
    result, hid_calls, _session_factory_ref = _run_recruiting_site_hid_click_scene(
        tmp_path,
        plan_kind="jd_sync",
        instruction="JD sync: recover from the current BOSS page into job management and sync job descriptions.",
        page_url="https://www.zhipin.com/web/chat/index",
        page_text="沟通页面",
        elements=_boss_main_navigation_entries(),
        click_point={"x": 88, "y": 240},
        final_status="completed",
    )

    assert result["status"] == "completed"
    assert len(hid_calls) == 1


def test_scene_context_allows_realish_jd_sync_job_management_get_element_without_nav_metadata(tmp_path: Path) -> None:
    job_management_entry = {
        "ref": "job-management-link",
        "text": "职位管理",
        "role": "link",
        "href": "https://www.zhipin.com/web/chat/job/list",
        "bounds": {"viewport": {"x": 24, "y": 96, "width": 68, "height": 40}},
    }
    result, hid_calls, _session_factory_ref = _run_recruiting_site_hid_click_scene(
        tmp_path,
        plan_kind="jd_sync",
        instruction="JD sync: recover from the current BOSS page into job management and sync job descriptions.",
        page_url="https://www.zhipin.com/web/chat/index",
        page_text="沟通页面",
        elements=[],
        click_point={"x": 58, "y": 116},
        final_status="completed",
        selected_element=job_management_entry,
    )

    assert result["status"] == "completed"
    assert len(hid_calls) == 1


@pytest.mark.parametrize(
    ("element", "click_point", "reason"),
    [
        ({"ref": "nav-rules", "text": "招聘规范", "role": "link", "kind": "navigation", "container": "top-nav", "clickPoint": {"x": 510, "y": 72}}, {"x": 510, "y": 72}, "non_recruiting_navigation_target"),
        ({"ref": "top-chat", "text": "沟通", "role": "link", "kind": "navigation", "container": "top-nav", "clickPoint": {"x": 610, "y": 72}}, {"x": 610, "y": 72}, "requires_allowed_boss_main_navigation_entry"),
        ({"ref": "top-jobs", "text": "职位管理", "role": "link", "href": "https://www.zhipin.com/web/chat/job/list", "clickPoint": {"x": 610, "y": 72}}, {"x": 610, "y": 72}, "requires_allowed_boss_main_navigation_entry"),
        ({"ref": "page-jobs", "text": "职位管理", "role": "button", "href": "https://www.zhipin.com/web/chat/job/list", "clickPoint": {"x": 420, "y": 190}}, {"x": 420, "y": 190}, "requires_allowed_boss_main_navigation_entry"),
        ({"ref": "new-group", "text": "新建分组", "role": "button", "kind": "group_action", "clickPoint": {"x": 260, "y": 190}}, {"x": 260, "y": 190}, "non_recruiting_navigation_target"),
        ({"ref": "chat-plus", "text": "+", "role": "button", "kind": "group_action", "clickPoint": {"x": 300, "y": 190}}, {"x": 300, "y": 190}, "non_recruiting_navigation_target"),
        ({"ref": "chat-user", "text": "张三", "role": "link", "kind": "candidate", "clickPoint": {"x": 220, "y": 360}}, {"x": 220, "y": 360}, "non_recruiting_navigation_target"),
        ({"ref": "interview", "text": "面试", "role": "button", "clickPoint": {"x": 420, "y": 360}}, {"x": 420, "y": 360}, "non_recruiting_navigation_target"),
        ({"ref": "account-rights", "text": "账号权益", "role": "link", "clickPoint": {"x": 520, "y": 72}}, {"x": 520, "y": 72}, "non_recruiting_navigation_target"),
        ({"ref": "vip", "text": "升级VIP", "role": "button", "clickPoint": {"x": 620, "y": 72}}, {"x": 620, "y": 72}, "non_recruiting_navigation_target"),
        ({"ref": "greet", "text": "打招呼", "role": "button", "clickPoint": {"x": 740, "y": 360}}, {"x": 740, "y": 360}, "non_recruiting_navigation_target"),
        ({"ref": "resume", "text": "求简历", "role": "button", "clickPoint": {"x": 740, "y": 400}}, {"x": 740, "y": 400}, "non_recruiting_navigation_target"),
        ({"ref": "phone", "text": "换电话", "role": "button", "clickPoint": {"x": 740, "y": 440}}, {"x": 740, "y": 440}, "non_recruiting_navigation_target"),
        ({"ref": "wechat", "text": "换微信", "role": "button", "clickPoint": {"x": 740, "y": 480}}, {"x": 740, "y": 480}, "non_recruiting_navigation_target"),
        ({"ref": "schedule", "text": "约面试", "role": "button", "clickPoint": {"x": 740, "y": 520}}, {"x": 740, "y": 520}, "non_recruiting_navigation_target"),
        ({"ref": "reject", "text": "不合适", "role": "button", "clickPoint": {"x": 740, "y": 560}}, {"x": 740, "y": 560}, "non_recruiting_navigation_target"),
    ],
)
def test_scene_context_blocks_non_main_navigation_controls_during_recruiting_site_recovery(
    tmp_path: Path,
    element: dict[str, object],
    click_point: dict[str, int],
    reason: str,
) -> None:
    result, hid_calls, session_factory = _run_recruiting_site_hid_click_scene(
        tmp_path,
        plan_kind="autonomous_recruiting",
        instruction="Recruiting automation: recover from the current BOSS page.",
        page_url="https://www.zhipin.com/web/chat/index",
        page_text="沟通页面",
        elements=[*_boss_main_navigation_entries(), element],
        click_point=click_point,
        final_status="blocked",
    )

    assert result["status"] == "blocked"
    assert hid_calls == []
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item["payload"]["content"]
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "hid_action"
            and item["payload"]["content"].get("error") == "scene_recruiting_navigation_target_blocked"
        ]
        assert blocked_results
        assert blocked_results[0]["reason"] == reason


@pytest.mark.parametrize(
    ("label", "click_point"),
    [
        ("推荐牛人", {"x": 88, "y": 300}),
        ("搜索", {"x": 88, "y": 360}),
        ("沟通", {"x": 88, "y": 420}),
    ],
)
def test_scene_context_blocks_non_job_main_navigation_entries_for_jd_sync_recovery(
    tmp_path: Path,
    label: str,
    click_point: dict[str, int],
) -> None:
    result, hid_calls, session_factory = _run_recruiting_site_hid_click_scene(
        tmp_path,
        plan_kind="jd_sync",
        instruction="JD sync: recover from the current BOSS page into job management and sync job descriptions.",
        page_url="https://www.zhipin.com/web/chat/index",
        page_text="沟通页面",
        elements=_boss_main_navigation_entries(),
        click_point=click_point,
        final_status="blocked",
    )

    assert result["status"] == "blocked"
    assert hid_calls == []
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item["payload"]["content"]
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "hid_action"
            and item["payload"]["content"].get("error") == "scene_recruiting_navigation_target_blocked"
        ]
        assert blocked_results
        assert blocked_results[0]["reason"] == "jd_sync_requires_job_management_entry"


def test_scene_context_allows_jd_sync_job_page_entries_after_job_management_recovery(tmp_path: Path) -> None:
    result, hid_calls, _session_factory_ref = _run_recruiting_site_hid_click_scene(
        tmp_path,
        plan_kind="jd_sync",
        instruction="JD sync: read job list and job details.",
        page_url="https://www.zhipin.com/web/geek/job",
        page_text="职位管理 在招职位",
        elements=[
            {"ref": "job-row-1", "text": "高级后端工程师", "role": "link", "kind": "job_row", "href": "https://www.zhipin.com/web/chat/job/edit?encryptId=1", "clickPoint": {"x": 420, "y": 330}},
            {"ref": "edit-job-1", "text": "编辑", "role": "button", "kind": "job_management_action", "clickPoint": {"x": 760, "y": 330}},
        ],
        click_point={"x": 420, "y": 330},
        final_status="completed",
    )

    assert result["status"] == "completed"
    assert len(hid_calls) == 1


@pytest.mark.parametrize(
    ("entry", "click_point", "expected_at"),
    [
        (
            {"ref": "job-row-1", "text": "产品实习生 北京 2-4K", "role": "link", "kind": "job_row", "clickPoint": {"x": 360, "y": 300}, "region": {"x": 250, "y": 260, "width": 620, "height": 120}},
            {"x": 520, "y": 310},
            {"x": 360, "y": 300},
        ),
        (
            {"ref": "job-title-1", "text": "产品实习生", "role": "link", "href": "https://www.zhipin.com/web/chat/job/edit?encryptId=job-1", "clickPoint": {"x": 330, "y": 294}, "region": {"x": 285, "y": 278, "width": 120, "height": 32}},
            {"x": 330, "y": 294},
            {"x": 330, "y": 294},
        ),
        (
            {"ref": "job-edit-1", "text": "编辑", "role": "button", "kind": "job_management_action", "parentRef": "job-row-1", "clickPoint": {"x": 760, "y": 306}, "region": {"x": 735, "y": 288, "width": 56, "height": 34}},
            {"x": 760, "y": 306},
            {"x": 760, "y": 306},
        ),
        (
            {"ref": "job-detail-1", "text": "查看详情", "role": "button", "parentRef": "job-row-1", "hitTestState": "covered", "clickPoint": {"x": 830, "y": 306}, "region": {"x": 800, "y": 288, "width": 74, "height": 34}},
            {"x": 830, "y": 306},
            {"x": 360, "y": 300},
        ),
    ],
)
def test_scene_context_allows_bound_jd_sync_job_list_entries(
    tmp_path: Path,
    entry: dict[str, object],
    click_point: dict[str, int],
    expected_at: dict[str, int],
) -> None:
    job_row = {
        "ref": "job-row-1",
        "text": "产品实习生 北京 2-4K 开放中",
        "role": "link",
        "kind": "job_row",
        "clickPoint": {"x": 360, "y": 300},
        "region": {"x": 250, "y": 260, "width": 620, "height": 120},
    }
    elements = [job_row]
    if entry["ref"] != "job-row-1":
        elements.append(entry)
    result, hid_calls, _session_factory_ref = _run_recruiting_site_hid_click_scene(
        tmp_path,
        plan_kind="jd_sync",
        instruction="JD sync: enter the visible BOSS job detail/edit page for the open job.",
        page_url="https://www.zhipin.com/web/chat/job/list",
        page_text="职位管理 全部职位 开放中 产品实习生 北京 2-4K 查看详情 编辑",
        elements=elements,
        click_point=click_point,
        final_status="completed",
    )

    assert result["status"] == "completed"
    assert len(hid_calls) == 1
    primitive = hid_calls[0]["primitives"][0]
    assert primitive["at"] == expected_at
    assert primitive["targetKind"] == "boss_job_list_entry"
    assert primitive.get("boundRef") in {None, "job-row-1", "job-title-1"}


@pytest.mark.parametrize(
    ("element", "click_point"),
    [
        ({"ref": "open-jobs-tab", "text": "开放中", "role": "tab", "clickPoint": {"x": 360, "y": 180}}, {"x": 360, "y": 180}),
        ({"ref": "close-job-1", "text": "关闭职位", "role": "button", "kind": "job_management_action", "parentRef": "job-row-1", "clickPoint": {"x": 820, "y": 306}}, {"x": 820, "y": 306}),
    ],
)
def test_scene_context_blocks_jd_sync_filters_tabs_and_destructive_job_actions(
    tmp_path: Path,
    element: dict[str, object],
    click_point: dict[str, int],
) -> None:
    result, hid_calls, session_factory = _run_recruiting_site_hid_click_scene(
        tmp_path,
        plan_kind="jd_sync",
        instruction="JD sync: only enter job detail/edit pages; do not mutate job state.",
        page_url="https://www.zhipin.com/web/chat/job/list",
        page_text="职位管理 全部职位 开放中 待开放 审核不通过 已关闭 产品实习生",
        elements=[
            {"ref": "job-row-1", "text": "产品实习生 北京 2-4K 开放中", "role": "link", "kind": "job_row", "clickPoint": {"x": 360, "y": 300}, "region": {"x": 250, "y": 260, "width": 620, "height": 120}},
            element,
        ],
        click_point=click_point,
        final_status="blocked",
    )

    assert result["status"] == "blocked"
    assert hid_calls == []
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item["payload"]["content"]
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "hid_action"
            and item["payload"]["content"].get("error") == "scene_recruiting_navigation_target_blocked"
        ]
    assert blocked_results


def test_scene_context_matches_recruiting_navigation_with_document_wrapped_bounds(tmp_path: Path) -> None:
    result, hid_calls, _session_factory_ref = _run_recruiting_site_hid_click_scene(
        tmp_path,
        plan_kind="autonomous_recruiting",
        instruction="Recruiting automation: recover from the current BOSS page.",
        page_url="https://www.zhipin.com/web/chat/index",
        page_text="沟通页面",
        elements=[
            {
                "ref": "nav-search",
                "text": "搜索",
                "role": "link",
                "kind": "navigation",
                "href": "https://www.zhipin.com/web/geek/search",
                "bounds": {"document": {"x": 72, "y": 340, "width": 88, "height": 40}},
            }
        ],
        click_point={"x": 88, "y": 360},
        final_status="completed",
    )

    assert result["status"] == "completed"
    assert len(hid_calls) == 1


def _run_recruiting_site_hid_click_scene(
    tmp_path: Path,
    *,
    plan_kind: str,
    instruction: str,
    page_url: str,
    page_text: str,
    elements: list[dict[str, object]],
    click_point: dict[str, int],
    final_status: str,
    selected_element: dict[str, object] | None = None,
):
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(tool_calls=[ToolCall(id="snapshot", name="browser_snapshot", arguments={"tabId": 9})], finish_reason="tool_calls"),
            *(
                [
                    LLMResponse(
                        tool_calls=[
                            ToolCall(
                                id="element",
                                name="browser_get_element",
                                arguments={"tabId": 9, "selector": "a[href*='/web/chat/job/list']"},
                            )
                        ],
                        finish_reason="tool_calls",
                    )
                ]
                if selected_element is not None
                else []
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="hid",
                        name="hid_action",
                        arguments={
                            "target": {"tabId": 9},
                            "primitives": [{"type": "click", "at": click_point, "button": "left"}],
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="recruiting site click checked",
                result_data={"status": final_status, "summary": "recruiting site click checked"},
            ),
        ],
    )
    hid_calls: list[dict[str, object]] = []
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Snapshot page.",
            parameters={"type": "object", "properties": {"tabId": {"type": "integer"}}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "tabId": arguments.get("tabId"),
                "url": page_url,
                "title": "BOSS 直聘",
                "text": page_text,
                "elements": elements,
            },
            metadata={"capabilities": ["browser"], "external_tool": True, "real_environment": True},
        )
    )
    if selected_element is not None:
        tools.register(
            ToolDefinition(
                name="browser_get_element",
                description="Get page element.",
                parameters={"type": "object", "properties": {"tabId": {"type": "integer"}, "selector": {"type": "string"}}, "additionalProperties": True},
                handler=lambda arguments: {
                    "success": True,
                    "tabId": arguments.get("tabId"),
                    "url": page_url,
                    "title": "BOSS 直聘",
                    "element": selected_element,
                },
                metadata={"capabilities": ["browser"], "external_tool": True, "real_environment": True},
            )
        )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="Execute HID.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: hid_calls.append(dict(arguments)) or {"success": True, "ok": True},
            metadata={"capabilities": ["computer"], "external_tool": True, "real_environment": True},
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
            "title": "Recruiting site navigation gate",
            "instruction": instruction,
            "preferred_capabilities": ["browser", "computer"],
            "context": {"plan_kind": plan_kind},
            "browser_target": {"url": "https://www.zhipin.com/", "tabId": 9},
        }
    )
    return result, hid_calls, session_factory


def _boss_main_navigation_entries() -> list[dict[str, object]]:
    return [
        {"ref": "nav-jobs", "text": "职位管理", "role": "link", "kind": "navigation", "href": "https://www.zhipin.com/web/chat/job/list", "clickPoint": {"x": 88, "y": 240}},
        {"ref": "nav-recommend", "text": "推荐牛人", "role": "link", "kind": "navigation", "href": "https://www.zhipin.com/web/geek/recommend", "clickPoint": {"x": 88, "y": 300}},
        {"ref": "nav-search", "text": "搜索", "role": "link", "kind": "navigation", "href": "https://www.zhipin.com/web/geek/search", "clickPoint": {"x": 88, "y": 360}},
        {"ref": "nav-chat", "text": "沟通", "role": "link", "kind": "navigation", "href": "https://www.zhipin.com/web/chat/index", "clickPoint": {"x": 88, "y": 420}},
    ]


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


def test_scene_context_normalizes_jd_sync_partial_output_to_complete_contract(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "in_progress",
        "summary": "职位管理列表已观察，下一步进入产品实习生详情。",
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "output_contract": {
                "contract_kind": "jd_sync",
                "result_data_required": True,
                "required_fields": [
                    "status",
                    "scene_status",
                    "observed_jobs",
                    "pending_jobs",
                    "completed_job_details",
                    "inactive_or_closed_jobs",
                    "action_candidates",
                    "recovery",
                    "terminal_blockers",
                    "policy_violations",
                    "evidence_refs",
                    "writeback_candidates",
                ],
            },
        }
    )

    assert result["status"] == "incomplete"
    assert result["blockers"] == []
    assert result["result_data"]["status"] == "in_progress"
    assert result["result_data"]["scene_status"] == "in_progress"
    for field in (
        "observed_jobs",
        "pending_jobs",
        "completed_job_details",
        "inactive_or_closed_jobs",
        "action_candidates",
        "terminal_blockers",
        "policy_violations",
        "evidence_refs",
        "writeback_candidates",
    ):
        assert result["result_data"][field] == []
    assert result["result_data"]["recovery"] == {}
    assert "output_contract_incomplete" not in json.dumps(result["blockers"], ensure_ascii=False)
    with session_factory() as session:
        assert session.query(JobDescription).count() == 0
        assert session.query(Candidate).count() == 0
        assert session.query(CandidateApplication).count() == 0
        assert session.query(ConversationSession).count() == 0
        assert session.query(ConversationTurn).count() == 0


def test_scene_context_blocks_jd_sync_candidate_chat_result_without_job_evidence(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "completed",
        "current_view": {
            "url": "https://www.zhipin.com/web/chat/index",
            "page": "沟通",
            "chat_detail_panel": {
                "candidate_name": "梁雪凌",
                "profile": "5 年产品经验，当前正在沟通",
            },
        },
        "business_summary": {
            "candidate_name": "梁雪凌",
            "resume_facts": ["本科", "B 端产品"],
            "conversation": "候选人已发送简历附件。",
        },
        "evidence": ["当前页为沟通会话详情，展示候选人梁雪凌和简历信息。"],
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "output_contract": {
                "contract_kind": "jd_sync",
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

    assert result["status"] == "blocked"
    assert result["summary"] == "JD sync observed candidate/chat context instead of job description evidence"
    assert "梁雪凌" not in result["summary"]
    assert result["result_data"]["status"] == "blocked"
    assert result["result_data"]["reported_status"] == "completed"
    assert result["result_data"]["completed_job_details"] == []
    assert result["result_data"]["observed_jobs"] == []
    assert result["result_data"]["pending_jobs"] == []
    assert result["result_data"]["jd_sync_boundary_guard"]["reason"] == "jd_sync_wrong_page_candidate_context"
    assert result["result_data"]["policy_violations"][0]["kind"] == "jd_sync_candidate_chat_contamination"
    assert result["blockers"][0]["kind"] == "jd_sync_wrong_page_candidate_context"
    with session_factory() as session:
        assert session.query(JobDescription).count() == 0
        assert session.query(Candidate).count() == 0
        assert session.query(CandidateApplication).count() == 0
        assert session.query(ConversationSession).count() == 0
        assert session.query(ConversationTurn).count() == 0


def test_scene_context_recovers_jd_sync_from_chat_page_visible_job_management_nav(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "completed",
        "current_view": {
            "url": "https://www.zhipin.com/web/chat/index",
            "page": "沟通",
            "chat_detail_panel": {
                "candidate_name": "梁雪凌",
                "profile": "5 年产品经验，当前正在沟通",
            },
        },
        "business_summary": {
            "candidate_name": "梁雪凌",
            "resume_facts": ["本科", "B 端产品"],
            "conversation": "候选人已发送简历附件。",
        },
        "evidence": ["当前页为沟通会话详情，展示候选人梁雪凌和简历信息。"],
    }
    hid_calls: list[dict[str, object]] = []
    snapshot_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(tool_calls=[ToolCall(id="snapshot-chat", name="browser_snapshot", arguments={"tabId": 9})], finish_reason="tool_calls"),
            LLMResponse(content=json.dumps(final_payload, ensure_ascii=False), finish_reason="stop"),
        ],
    )
    tools = ToolRegistry()

    def browser_snapshot(arguments: dict[str, object]) -> dict[str, object]:
        snapshot_calls.append(dict(arguments))
        if len(snapshot_calls) == 1:
            return {
                "success": True,
                "tabId": arguments.get("tabId"),
                "url": "https://www.zhipin.com/web/chat/index",
                "title": "沟通",
                "text": "沟通 全部 新招呼 沟通中 候选人梁雪凌 简历附件",
                "elements": [
                    *_boss_main_navigation_entries(),
                    {"ref": "chat-user", "text": "梁雪凌", "role": "link", "kind": "candidate", "clickPoint": {"x": 230, "y": 360}},
                    {"ref": "greet", "text": "打招呼", "role": "button", "clickPoint": {"x": 740, "y": 360}},
                ],
            }
        return {
            "success": True,
            "tabId": arguments.get("tabId"),
            "url": "https://www.zhipin.com/web/chat/job/list",
            "title": "职位管理",
            "text": "职位管理 全部职位 开放中 待开放 审核不通过 已关闭",
            "elements": [
                {"ref": "all-jobs", "text": "全部职位", "role": "tab", "clickPoint": {"x": 280, "y": 180}},
                {"ref": "open-jobs", "text": "开放中", "role": "tab", "clickPoint": {"x": 360, "y": 180}},
            ],
        }

    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Observe browser page.",
            parameters={"type": "object", "properties": {"tabId": {"type": "integer"}}, "additionalProperties": True},
            handler=browser_snapshot,
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="hid_action",
            description="Execute HID.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: hid_calls.append(dict(arguments)) or {"success": True, "ok": True},
            metadata={"capabilities": ["computer"], "external_tool": True, "real_environment": True},
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "preferred_capabilities": ["browser", "computer"],
            "browser_target": {"url": "https://www.zhipin.com/web/chat/index", "tabId": 9},
            "output_contract": {
                "contract_kind": "jd_sync",
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

    assert result["status"] == "blocked"
    assert len(hid_calls) == 1
    assert [call.get("url") for call in snapshot_calls] == [None, None]
    assert [call.get("tabId") for call in snapshot_calls] == [9, 9]
    hid_call = hid_calls[0]
    assert hid_call["primitives"] == [
        {"type": "click", "at": {"x": 88, "y": 240}, "button": "left", "label": "职位管理", "ref": "nav-jobs"}
    ]
    assert hid_call["target"]["tabId"] == 9
    assert hid_call["target"]["host"] == "www.zhipin.com"
    assert "pasteText" not in json.dumps(hid_call, ensure_ascii=False)
    assert "browser_open_tab" not in json.dumps(result, ensure_ascii=False)
    assert result["result_data"]["observed_jobs"] == []
    assert result["result_data"]["completed_job_details"] == []
    assert result["result_data"]["activation_entry_observed"] is True
    assert result["result_data"]["jd_sync_recovery_guard"]["reason"] == "jd_sync_recovered_to_job_management_needs_detail_read"
    assert result["result_data"]["remaining_work"] == ["read_job_list_or_detail_after_job_management_recovery"]
    assert "jd_sync_boundary_guard" not in result["result_data"]
    assert "梁雪凌" not in json.dumps(result["result_data"], ensure_ascii=False)
    assert [blocker["kind"] for blocker in result["blockers"]] == ["jd_sync_recovered_to_job_management_needs_detail_read"]
    with session_factory() as session:
        assert session.query(Candidate).count() == 0


def test_scene_context_forces_jd_sync_snapshot_after_only_job_tab_identification(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "blocked",
        "summary": "Active tab is already the BOSS job list page.",
        "observed_jobs": [],
        "completed_job_details": [],
        "inactive_or_closed_jobs": [],
        "activation_entry_observed": False,
        "blockers": [],
        "limitations": [],
        "evidence": [],
    }
    snapshot_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(id="tabs", name="browser_list_tabs", arguments={}),
                    ToolCall(id="active", name="browser_get_active_tab", arguments={}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content=json.dumps(final_payload, ensure_ascii=False), finish_reason="stop"),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List browser tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "tabs": [
                    {
                        "tabId": 9,
                        "url": "https://www.zhipin.com/web/chat/job/list",
                        "title": "职位管理",
                        "active": True,
                    }
                ],
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_get_active_tab",
            description="Get active browser tab.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "tab": {
                    "tabId": 9,
                    "url": "https://www.zhipin.com/web/chat/job/list",
                    "title": "职位管理",
                },
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Observe browser page.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: snapshot_calls.append(dict(arguments)) or {
                "success": True,
                "tabId": arguments.get("tabId"),
                "url": "https://www.zhipin.com/web/chat/job/list",
                "title": "职位管理",
                "text": "职位管理 全部职位 开放中 待开放 审核不通过 已关闭",
                "elements": [{"role": "tab", "text": "全部职位"}],
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "preferred_capabilities": ["browser"],
            "browser_target": {"url": "https://www.zhipin.com/", "tabId": 9},
            "output_contract": {
                "contract_kind": "jd_sync",
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

    assert result["status"] == "blocked"
    assert result["result_data"]["status"] == "blocked"
    assert result["result_data"]["observed_jobs"] == []
    assert result["result_data"]["completed_job_details"] == []
    assert result["result_data"]["inactive_or_closed_jobs"] == []
    assert result["result_data"]["activation_entry_observed"] is False
    assert result["result_data"]["limitations"] == []
    assert result["result_data"]["evidence"] == []
    assert snapshot_calls == [
        {
            "tabId": 9,
            "expectedHost": "www.zhipin.com",
            "expectedOrigin": "https://www.zhipin.com",
            "targetPolicy": "same-origin",
            "includeText": True,
            "clickableLimit": 120,
        }
    ]
    assert result["result_data"]["jd_sync_observation_repair"]["status"] == "completed"
    assert result["result_data"]["jd_sync_observation_repair"]["tool_name"] == "browser_snapshot"
    assert "jd_sync_observation_guard" not in result["result_data"]
    assert [blocker["kind"] for blocker in result["blockers"]] == []
    assert "output_contract_incomplete" not in json.dumps(result["blockers"], ensure_ascii=False)


def test_scene_context_extracts_jd_sync_job_list_evidence_from_forced_snapshot(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "in_progress",
        "summary": "Need to enter the visible job detail.",
        "observed_jobs": [],
        "pending_jobs": [],
        "completed_job_details": [],
        "inactive_or_closed_jobs": [],
        "blockers": [],
        "limitations": [],
        "evidence": [],
    }
    snapshot_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(tool_calls=[ToolCall(id="tabs", name="browser_list_tabs", arguments={})], finish_reason="tool_calls"),
            LLMResponse(content=json.dumps(final_payload, ensure_ascii=False), finish_reason="stop"),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List browser tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "tabs": [
                    {
                        "tabId": 1136767565,
                        "url": "https://www.zhipin.com/web/chat/job/list",
                        "title": "职位管理",
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
            description="Observe browser page.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: snapshot_calls.append(dict(arguments)) or {
                "success": True,
                "tabId": arguments.get("tabId"),
                "url": "https://www.zhipin.com/web/chat/job/list",
                "title": "职位管理",
                "text": "职位管理 全部职位 开放中 产品实习生 北京 | 经验不限 | 本科 | 2-4K | 全职 开放中 编辑 查看详情",
                "elements": [
                    {
                        "ref": "job-row-product-intern",
                        "text": "产品实习生 北京 经验不限 本科 2-4K 全职 开放中",
                        "role": "link",
                        "kind": "job_row",
                        "href": "https://www.zhipin.com/web/chat/job/edit?encryptId=product-intern",
                        "clickPoint": {"x": 360, "y": 300},
                        "region": {"x": 250, "y": 260, "width": 620, "height": 120},
                    },
                    {
                        "ref": "job-edit-product-intern",
                        "text": "编辑",
                        "role": "button",
                        "kind": "job_management_action",
                        "parentRef": "job-row-product-intern",
                        "clickPoint": {"x": 760, "y": 306},
                    },
                    {
                        "ref": "job-close-product-intern",
                        "text": "关闭职位",
                        "role": "button",
                        "kind": "job_management_action",
                        "parentRef": "job-row-product-intern",
                        "clickPoint": {"x": 820, "y": 306},
                    },
                ],
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "preferred_capabilities": ["browser"],
            "browser_target": {"url": "https://www.zhipin.com/", "tabId": 1136767565},
            "output_contract": {"contract_kind": "jd_sync", "result_data_required": True},
        }
    )

    assert snapshot_calls == [
        {
            "tabId": 1136767565,
            "expectedHost": "www.zhipin.com",
            "expectedOrigin": "https://www.zhipin.com",
            "targetPolicy": "same-origin",
            "includeText": True,
            "clickableLimit": 120,
        }
    ]
    assert result["status"] == "incomplete"
    assert result["result_data"]["observed_jobs"][0]["title"] == "产品实习生"
    assert result["result_data"]["pending_jobs"][0]["title"] == "产品实习生"
    assert result["result_data"]["completed_job_details"] == []
    assert result["result_data"]["writeback_candidates"] == []
    assert result["result_data"]["action_candidates"][0]["tool_name"] == "hid_action"
    assert result["result_data"]["action_candidates"][0]["kind"] == "open_job_detail_or_safe_edit"
    assert "关闭职位" not in json.dumps(result["result_data"]["action_candidates"], ensure_ascii=False)
    state = reduce_jd_sync_scene_result(initial_jd_sync_state(), result)
    assert list(state["jobs_by_key"]) == ["https://www.zhipin.com/web/chat/job/edit?encryptid=product-intern"]
    assert state["pending_job_keys"] == ["https://www.zhipin.com/web/chat/job/edit?encryptid=product-intern"]
    assert state["completed_job_keys"] == []


def test_jd_sync_snapshot_ignores_boss_main_navigation_job_management_entry() -> None:
    delta = _jd_sync_browser_evidence_delta_from_snapshot(
        {
            "success": True,
            "tabId": 9,
            "url": "https://www.zhipin.com/web/chat/job/list?ka=menu-manager-job",
            "title": "职位管理",
            "text": "职位管理 推荐牛人 搜索 沟通 招聘规范 我的客服",
            "elements": [
                {
                    "ref": "e14",
                    "text": "职位管理",
                    "role": "link",
                    "href": "https://www.zhipin.com/web/chat/job/list?ka=menu-manager-job",
                    "clickPoint": {"x": 88, "y": 220},
                    "region": {"x": 24, "y": 192, "width": 128, "height": 42},
                },
                {
                    "ref": "top-rule",
                    "text": "招聘规范",
                    "role": "link",
                    "clickPoint": {"x": 1040, "y": 38},
                },
                {
                    "ref": "top-service",
                    "text": "我的客服",
                    "role": "link",
                    "clickPoint": {"x": 1130, "y": 38},
                },
            ],
        }
    )

    assert delta.get("observed_jobs") in (None, [])
    assert delta.get("pending_jobs") in (None, [])
    assert delta.get("action_candidates") in (None, [])


def test_jd_sync_snapshot_keeps_real_boss_job_card_and_safe_detail_action() -> None:
    delta = _jd_sync_browser_evidence_delta_from_snapshot(
        {
            "success": True,
            "tabId": 9,
            "url": "https://www.zhipin.com/web/chat/job/list",
            "title": "职位管理",
            "text": "职位管理 全部职位 开放中 产品实习生 北京 经验不限 本科 2-4K 全职 开放中 编辑 查看详情",
            "elements": [
                {
                    "ref": "main-job-management",
                    "text": "职位管理",
                    "role": "link",
                    "href": "https://www.zhipin.com/web/chat/job/list?ka=menu-manager-job",
                    "clickPoint": {"x": 88, "y": 220},
                    "region": {"x": 24, "y": 192, "width": 128, "height": 42},
                },
                {
                    "ref": "job-row-product-intern",
                    "text": "产品实习生 北京 经验不限 本科 2-4K 全职 开放中",
                    "role": "link",
                    "kind": "job_row",
                    "href": "https://www.zhipin.com/web/chat/job/edit?encryptId=product-intern",
                    "clickPoint": {"x": 360, "y": 300},
                    "region": {"x": 250, "y": 260, "width": 620, "height": 120},
                },
                {
                    "ref": "job-detail-product-intern",
                    "text": "查看详情",
                    "role": "button",
                    "kind": "job_management_action",
                    "parentRef": "job-row-product-intern",
                    "clickPoint": {"x": 820, "y": 306},
                },
            ],
        }
    )

    assert [item["title"] for item in delta["observed_jobs"]] == ["产品实习生"]
    assert [item["title"] for item in delta["pending_jobs"]] == ["产品实习生"]
    assert any(item["label"] == "查看详情" for item in delta["action_candidates"])
    assert "main-job-management" not in json.dumps(delta["action_candidates"], ensure_ascii=False)


def test_jd_sync_snapshot_extracts_live_boss_title_link_and_bound_edit_from_clickables() -> None:
    delta = _jd_sync_browser_evidence_delta_from_snapshot(
        {
            "success": True,
            "tabId": 1136767565,
            "snapshot": {
                "url": "https://www.zhipin.com/web/chat/job/list",
                "title": "职位管理",
                "text": "职位管理 全部职位 开放中 待开放 审核不通过 已关闭",
                "clickables": [
                    {
                        "ref": "main-job-management",
                        "tag": "a",
                        "role": "link",
                        "text": "职位管理",
                        "href": "https://www.zhipin.com/web/chat/job/list?ka=menu-manager-job",
                        "viewport": {"top": 203, "left": 64, "width": 64, "height": 22},
                        "inViewport": True,
                        "detectedBy": "selector",
                    },
                    {
                        "ref": "@e23",
                        "tag": "a",
                        "role": "link",
                        "text": "产品实习生",
                        "href": "javascript:;",
                        "viewport": {"top": 187, "left": 287, "width": 88, "height": 22},
                        "inViewport": True,
                        "detectedBy": "selector",
                    },
                    {
                        "ref": "@e27",
                        "tag": "a",
                        "role": "link",
                        "text": "编辑",
                        "href": "javascript:;",
                        "viewport": {"top": 201, "left": 1283.21875, "width": 28, "height": 20},
                        "inViewport": True,
                        "detectedBy": "selector",
                    },
                    {
                        "ref": "@e28",
                        "tag": "button",
                        "role": "button",
                        "text": "关闭",
                        "viewport": {"top": 201, "left": 1320, "width": 28, "height": 20},
                        "inViewport": True,
                        "detectedBy": "selector",
                    },
                ],
            },
        }
    )

    assert [item["title"] for item in delta["observed_jobs"]] == ["产品实习生"]
    assert [item["title"] for item in delta["pending_jobs"]] == ["产品实习生"]
    assert delta["observed_jobs"][0]["job_key"] == "@e23"
    assert any(
        item["label"] == "编辑" and item.get("bound_ref") == "@e23"
        for item in delta["action_candidates"]
    )
    action_dump = json.dumps(delta["action_candidates"], ensure_ascii=False)
    assert "关闭" not in action_dump
    assert "main-job-management" not in action_dump


def test_scene_context_jd_sync_evidence_uses_raw_snapshot_before_clickables_compaction(
    tmp_path: Path,
) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(tool_calls=[ToolCall(id="snapshot", name="browser_snapshot", arguments={})], finish_reason="tool_calls"),
            LLMResponse(content="job list observed", result_data={"status": "completed", "summary": "job list observed"}),
        ],
    )
    topbar_clickables = [
        {"ref": "@e1", "tag": "a", "role": "link", "text": "招聘规范", "viewport": {"top": 28, "left": 1010, "width": 64, "height": 20}},
        {"ref": "@e2", "tag": "a", "role": "link", "text": "我的客服", "viewport": {"top": 28, "left": 1090, "width": 64, "height": 20}},
        {"ref": "@e3", "tag": "a", "role": "link", "text": "面试", "viewport": {"top": 28, "left": 1170, "width": 32, "height": 20}},
        {"ref": "@e4", "tag": "a", "role": "link", "text": "招聘数据 1", "viewport": {"top": 28, "left": 1230, "width": 80, "height": 20}},
    ]
    filler_clickables = [
        {
            "ref": f"@filler-{index}",
            "tag": "span",
            "role": "text",
            "text": f"占位 {index}",
            "viewport": {"top": 80 + index, "left": 220, "width": 40, "height": 18},
        }
        for index in range(20)
    ]
    raw_clickables = [
        *topbar_clickables,
        *filler_clickables,
        {
            "ref": "@e23",
            "tag": "a",
            "role": "link",
            "text": "产品实习生",
            "href": "javascript:;",
            "viewport": {"top": 187, "left": 287, "width": 88, "height": 22},
            "inViewport": True,
        },
        {
            "ref": "@e27",
            "tag": "a",
            "role": "link",
            "text": "编辑",
            "href": "javascript:;",
            "parentRef": "@e23",
            "viewport": {"top": 201, "left": 1283, "width": 28, "height": 20},
            "inViewport": True,
        },
        {
            "ref": "@e28",
            "tag": "button",
            "role": "button",
            "text": "关闭",
            "parentRef": "@e23",
            "viewport": {"top": 201, "left": 1320, "width": 28, "height": 20},
            "inViewport": True,
        },
    ]
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Observe browser page.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "tabId": 1136767565,
                "snapshot": {
                    "url": "https://www.zhipin.com/web/chat/job/list",
                    "title": "职位管理",
                    "text": "招聘规范 我的客服 面试 招聘数据 1",
                    "clickables": raw_clickables,
                },
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "preferred_capabilities": ["browser"],
            "browser_target": {"url": "https://www.zhipin.com/", "tabId": 1136767565},
            "output_contract": {"contract_kind": "jd_sync", "result_data_required": True},
        }
    )

    assert result["status"] == "incomplete"
    assert result["result_data"]["observed_jobs"][0]["title"] == "产品实习生"
    assert result["result_data"]["pending_jobs"][0]["title"] == "产品实习生"
    assert any(
        item["label"] == "编辑" and item.get("bound_ref") == "@e23"
        for item in result["result_data"]["action_candidates"]
    )
    assert "关闭" not in json.dumps(result["result_data"]["action_candidates"], ensure_ascii=False)
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        snapshot_payload = next(
            item["payload"]
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "browser_snapshot"
        )
        stored_clickables = snapshot_payload["content"]["snapshot"]["clickables"]
    assert stored_clickables == [*topbar_clickables, "... 23 more items omitted"]
    assert "产品实习生" not in json.dumps(snapshot_payload["content"], ensure_ascii=False)
    assert snapshot_payload["jd_sync_browser_evidence_delta"]["observed_jobs"][0]["title"] == "产品实习生"


@pytest.mark.parametrize("url,title", [
    ("https://www.zhipin.com/web/geek/recommend", "推荐牛人"),
    ("https://www.zhipin.com/web/geek/search", "搜索"),
])
def test_jd_sync_snapshot_does_not_treat_candidate_search_or_recommend_clickables_as_jobs(url: str, title: str) -> None:
    delta = _jd_sync_browser_evidence_delta_from_snapshot(
        {
            "success": True,
            "tabId": 1136767565,
            "snapshot": {
                "url": url,
                "title": title,
                "text": f"{title} 产品实习生_北京 2-4K 候选人 沟通",
                "clickables": [
                    {
                        "ref": "@candidate-title",
                        "tag": "a",
                        "role": "link",
                        "text": "产品实习生",
                        "href": "javascript:;",
                        "viewport": {"top": 187, "left": 287, "width": 88, "height": 22},
                        "inViewport": True,
                    },
                    {
                        "ref": "@candidate-card",
                        "tag": "a",
                        "role": "link",
                        "text": "候选人 王同学 产品实习生",
                        "href": "javascript:;",
                        "viewport": {"top": 226, "left": 287, "width": 180, "height": 28},
                        "inViewport": True,
                    },
                ],
            },
        }
    )

    assert delta.get("observed_jobs") in (None, [])
    assert delta.get("pending_jobs") in (None, [])
    assert delta.get("action_candidates") in (None, [])


def test_scene_context_recovers_jd_sync_snapshot_from_existing_zhipin_tab_when_active_tab_is_local(
    tmp_path: Path,
) -> None:
    session_factory = _session_factory(tmp_path)
    snapshot_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(tool_calls=[ToolCall(id="tabs", name="browser_list_tabs", arguments={})], finish_reason="tool_calls"),
            LLMResponse(tool_calls=[ToolCall(id="snapshot", name="browser_snapshot", arguments={})], finish_reason="tool_calls"),
            LLMResponse(content="job tab observed", result_data={"status": "completed", "summary": "job tab observed"}),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List browser tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "tabs": [
                    {"tabId": 1, "url": "http://127.0.0.1:5174/", "title": "RecruitStation", "active": True},
                    {"tabId": 9, "url": "https://www.zhipin.com/web/chat/job/list", "title": "职位管理", "active": False},
                    {"tabId": 10, "url": "https://www.zhipin.com/web/chat/index", "title": "沟通", "active": False},
                ],
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Observe browser page.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: snapshot_calls.append(dict(arguments))
            or (
                {
                    "success": True,
                    "tabId": 9,
                    "url": "https://www.zhipin.com/web/chat/job/list",
                    "title": "职位管理",
                    "text": "职位管理 全部职位 开放中 待开放 审核不通过 已关闭 产品实习生",
                    "elements": [{"ref": "job-row-1", "text": "产品实习生", "role": "link", "kind": "job_row"}],
                }
                if arguments.get("tabId") == 9
                else {"success": True, "tabId": 1, "url": "http://127.0.0.1:5174/", "title": "RecruitStation"}
            ),
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "preferred_capabilities": ["browser"],
            "browser_target": {"url": "https://www.zhipin.com/"},
            "output_contract": {"contract_kind": "jd_sync"},
        }
    )

    assert result["status"] == "incomplete"
    assert result["result_data"]["observed_jobs"][0]["title"] == "产品实习生"
    assert result["result_data"]["pending_jobs"][0]["title"] == "产品实习生"
    assert result["result_data"]["completed_job_details"] == []
    assert snapshot_calls == [
        {},
        {
            "tabId": 9,
            "expectedHost": "www.zhipin.com",
            "expectedOrigin": "https://www.zhipin.com",
            "targetPolicy": "same-origin",
        },
    ]
    assert all("url" not in call for call in snapshot_calls)
    assert "browser_open_tab" not in json.dumps(result, ensure_ascii=False)
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        mismatch_results = [
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "browser_snapshot"
            and item["payload"]["content"].get("error") == "scene_browser_target_mismatch"
        ]
        assert mismatch_results == []


def test_scene_context_keeps_jd_sync_target_mismatch_blocked_when_no_existing_zhipin_tab(
    tmp_path: Path,
) -> None:
    session_factory = _session_factory(tmp_path)
    snapshot_calls: list[dict[str, object]] = []
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(tool_calls=[ToolCall(id="tabs", name="browser_list_tabs", arguments={})], finish_reason="tool_calls"),
            LLMResponse(tool_calls=[ToolCall(id="snapshot", name="browser_snapshot", arguments={})], finish_reason="tool_calls"),
            LLMResponse(content="target mismatch", result_data={"status": "blocked", "summary": "target mismatch"}),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_list_tabs",
            description="List browser tabs.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: {
                "success": True,
                "tabs": [{"tabId": 1, "url": "http://127.0.0.1:5174/", "title": "RecruitStation", "active": True}],
            },
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Observe browser page.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: snapshot_calls.append(dict(arguments))
            or {"success": True, "tabId": 1, "url": "http://127.0.0.1:5174/", "title": "RecruitStation"},
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "preferred_capabilities": ["browser"],
            "browser_target": {"url": "https://www.zhipin.com/"},
            "output_contract": {"contract_kind": "jd_sync"},
        }
    )

    assert result["status"] == "blocked"
    assert snapshot_calls == [{}]
    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        blocked_results = [
            item
            for item in episode.observations
            if item["type"] == "tool_event"
            and item["payload"]["kind"] == "tool_result_ready"
            and item["payload"]["tool_name"] == "browser_snapshot"
            and item["payload"]["content"].get("error") == "scene_browser_target_mismatch"
        ]
        assert blocked_results


def test_scene_context_allows_jd_sync_completed_job_detail_result(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "completed",
        "observed_jobs": [{"title": "国际销售工程师", "external_id": "boss-jd-1", "status": "招聘中"}],
        "completed_job_details": [
            {
                "title": "国际销售工程师",
                "location": "上海",
                "status": "招聘中",
                "external_id": "boss-jd-1",
                "external_url": "https://www.zhipin.com/job_detail/boss-jd-1.html",
                "description": "负责海外客户拓展。",
                "requirements": ["3 年以上销售经验"],
            }
        ],
        "inactive_or_closed_jobs": [],
        "activation_entry_observed": True,
        "blockers": [],
        "limitations": [],
        "evidence": ["职位管理详情页展示岗位职责和任职要求。"],
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "output_contract": {
                "contract_kind": "jd_sync",
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

    assert result["status"] == "completed"
    assert result["blockers"] == []
    assert result["result_data"]["completed_job_details"][0]["external_id"] == "boss-jd-1"
    assert "jd_sync_boundary_guard" not in result["result_data"]


def test_scene_context_blocks_jd_sync_list_only_completed_details(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "completed",
        "observed_jobs": [{"title": "产品实习生", "status": "开放中", "external_id": "boss-product-intern-1"}],
        "completed_job_details": [
            {
                "title": "产品实习生",
                "status": "开放中",
                "external_id": "boss-product-intern-1",
                "external_url": "https://www.zhipin.com/web/chat/job/list",
                "detail_evidence": "not full JD detail; only the job management list card was visible",
            }
        ],
        "inactive_or_closed_jobs": [],
        "activation_entry_observed": True,
        "blockers": [],
        "limitations": ["未进入职位详情/编辑页"],
        "evidence": ["职位管理列表卡片显示 产品实习生。"],
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "output_contract": {
                "contract_kind": "jd_sync",
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

    assert result["status"] == "blocked"
    assert result["result_data"]["status"] == "blocked"
    assert result["result_data"]["reported_status"] == "completed"
    assert result["result_data"]["contract_validation"]["status"] == "failed"
    assert result["blockers"][0]["kind"] == "jd_sync_completed_details_require_detail_evidence"


def test_scene_context_blocks_jd_sync_completion_when_pending_jobs_remain(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    final_payload = {
        "status": "completed",
        "observed_jobs": [{"title": "产品实习生", "external_id": "boss-product-intern-1"}, {"title": "销售工程师", "external_id": "boss-sales-1"}],
        "pending_jobs": [{"title": "销售工程师", "external_id": "boss-sales-1"}],
        "completed_job_details": [
            {
                "title": "产品实习生",
                "external_id": "boss-product-intern-1",
                "external_url": "https://www.zhipin.com/web/chat/job/edit?encryptId=product",
                "description": "负责产品需求分析、原型设计和跨团队协作。",
                "requirements": "要求本科以上，具备产品实习经验和沟通能力。",
            }
        ],
        "inactive_or_closed_jobs": [],
        "activation_entry_observed": False,
        "blockers": [],
        "limitations": [],
        "evidence": ["产品实习生详情页展示岗位职责和任职要求。"],
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
            "instruction": "Return JD sync scene result JSON.",
            "context": {"plan_kind": "jd_sync"},
            "output_contract": {
                "contract_kind": "jd_sync",
                "result_data_required": True,
                "required_fields": [
                    "status",
                    "scene_status",
                    "observed_jobs",
                    "pending_jobs",
                    "completed_job_details",
                    "inactive_or_closed_jobs",
                    "action_candidates",
                    "recovery",
                    "terminal_blockers",
                    "policy_violations",
                    "evidence_refs",
                    "writeback_candidates",
                    "blockers",
                    "limitations",
                    "evidence",
                ],
            },
        }
    )

    assert result["status"] == "incomplete"
    assert result["result_data"]["status"] == "partial"
    assert result["result_data"]["scene_status"] == "partial"
    assert result["result_data"]["reported_status"] == "completed"
    assert result["result_data"]["pending_jobs"] == [{"title": "销售工程师", "external_id": "boss-sales-1"}]
    assert "jd_sync_pending_jobs_not_complete" not in json.dumps(result["blockers"], ensure_ascii=False)
    with session_factory() as session:
        assert session.query(JobDescription).count() == 0


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
                            "context": {"episode_id": "scene-episode", "task_spec_id": "scene-task", "account": "operator"},
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
    assert "episode_id" not in hid_arguments["context"]
    assert "task_spec_id" not in hid_arguments["context"]
    assert "account" not in hid_arguments["context"]
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
