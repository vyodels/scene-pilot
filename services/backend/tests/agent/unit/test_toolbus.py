from __future__ import annotations

import asyncio
from pathlib import Path

from recruit_station.agent_runtime.types import ToolCall, TurnContext
from recruit_station.capabilities.tools import ToolDefinition, ToolRegistry, build_delegate_scene_context_tool, is_scene_context_tool, register_core_tools
from recruit_station.core.settings import AppSettings
from recruit_station.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_station.models.domain import Candidate
from recruit_station.plugins.host import PluginHost
from recruit_station.plugins.recruit.manifest import RecruitPluginManifest
from recruit_station.memory.filesystem import MemoryFileStore
from recruit_station.services.container import (
    _build_delete_memory_file_handler,
    _build_list_memory_files_handler,
    _build_read_memory_file_handler,
    _build_read_memory_handler,
    _build_record_learning_handler,
    _build_write_memory_file_handler,
)


async def _run_async(tool_registry: ToolRegistry, tool_name: str, arguments: dict[str, object]):
    return await tool_registry.execute_async(tool_name, arguments)


def test_toolbus_executes_async_and_sync_tools_and_merges_sources() -> None:
    registry = ToolRegistry()

    async def _async_handler(arguments: dict[str, object]) -> dict[str, object]:
        return {"echo": arguments}

    registry.register(
        ToolDefinition(
            name="core.echo",
            description="Echo content.",
            parameters={"type": "object"},
            handler=_async_handler,
            category="core",
            external_target=False,
            resource_target_kind="memory",
        )
    )
    register_core_tools(registry)

    plugin_registry = ToolRegistry()
    plugin_registry.register(
        ToolDefinition(
            name="plugin.note",
            description="Record note.",
            parameters={"type": "object"},
            handler=lambda arguments: {"noted": arguments.get("note")},
            category="plugin",
            external_target=False,
            resource_target_kind="candidate",
        )
    )
    registry.merge(plugin_registry)

    result = asyncio.run(_run_async(registry, "core.echo", {"value": 1}))
    plugin_result = asyncio.run(_run_async(registry, "plugin.note", {"note": "hello"}))

    assert result.is_error is False
    assert result.output == {"echo": {"value": 1}}
    assert plugin_result.output == {"noted": "hello"}
    assert registry.tools["core.echo"].category == "core"
    assert registry.tools["plugin.note"].resource_target_kind == "candidate"
    assert "read_memory" in registry.tools
    assert registry.tools["read_memory"].category == "memory"
    assert registry.tools["write_memory_file"].category == "memory"


def test_toolbus_sync_execute_works_inside_running_event_loop() -> None:
    registry = ToolRegistry()

    async def _async_handler(arguments: dict[str, object]) -> dict[str, object]:
        return {"echo": arguments}

    registry.register(
        ToolDefinition(
            name="core.echo",
            description="Echo content.",
            parameters={"type": "object"},
            handler=_async_handler,
        )
    )

    async def _scenario():
        return registry.execute("core.echo", {"value": 1})

    result = asyncio.run(_scenario())

    assert result.is_error is False
    assert result.output == {"echo": {"value": 1}}


def test_register_core_tools_do_not_expose_skill_execution_tool() -> None:
    registry = ToolRegistry()
    register_core_tools(registry)

    assert "read_memory" in registry.tools
    assert "write_memory" not in registry.tools
    assert "write_memory_file" in registry.tools
    assert registry.tools["write_memory_file"].metadata["permission_scope"] == "memory_write"
    assert all(tool.resource_target_kind != "skill" for tool in registry.tools.values())
    assert all(tool.metadata.get("resource_target_kind") != "skill" for tool in registry.to_agent_runtime_tools())


def test_jd_sync_scene_delegate_instruction_is_rule_only_and_structured() -> None:
    captured_arguments: dict[str, object] = {}

    registry = ToolRegistry()
    registry.register(
        build_delegate_scene_context_tool(
            lambda arguments: captured_arguments.update(arguments)
            or {
                "status": "completed",
                "summary": "自然语言摘要里可能包含 1/5 和 国际销售工程师，但父上下文不应依赖它。",
                "result_data": {"status": "partial", "completed_job_details": []},
            }
        )
    )
    runtime_tool = next(tool for tool in registry.to_agent_runtime_tools() if tool.name == "delegate_scene_context")

    result = runtime_tool.handler.handle(
        ToolCall(
            id="tool-call-1",
            turn_id="turn-1",
            llm_invocation_id="llm-1",
            tool_use_id="use-1",
            name="delegate_scene_context",
            input={
                "instruction": "继续刚才同一招聘站点 JD 同步 scene。上一轮只完整读取了 1/5 个，剩余 4 个：国际销售工程师、客户成功经理。",
                "preferred_capabilities": ["browser", "computer"],
                "output_contract": {"format": "json"},
            },
        ),
        TurnContext(
            turn_id="turn-1",
            conversation_id="jd-sync-primary",
            tools=[],
            runtime={"constraints": {"plan_kind": "jd_sync"}},
        ),
    )

    instruction = str(captured_arguments["instruction"])
    assert "output_contract" in captured_arguments
    assert "completed_job_details" in captured_arguments["output_contract"]["required_fields"]
    assert "1/5" not in instruction
    assert "剩余 4" not in instruction
    assert "国际销售工程师" not in instruction
    assert "客户成功经理" not in instruction
    assert "规则" in instruction
    assert result.content["business_result"] == {"status": "partial", "completed_job_details": []}
    assert "business_summary" not in result.content


def test_core_read_memory_tool_uses_memory_files(tmp_path: Path) -> None:
    store = MemoryFileStore(tmp_path / "memory-files")
    store.write_file(
        scope_kind="candidate",
        scope_ref="alice",
        agent_definition_id="agent-1",
        path="status.md",
        content="# Alice replied\n\nCandidate replied to outreach.",
    )

    output = _build_read_memory_handler(store)(
        {"scope_kind": "candidate", "scope_ref": "alice", "agent_definition_id": "agent-1"}
    )

    assert output["count"] == 1
    assert output["entries"][0]["memory_item_id"] == "status.md"
    assert output["entries"][0]["summary"] == "Alice replied"
    assert output["entries"][0]["content"] == {"path": "status.md", "preview": "# Alice replied\n\nCandidate replied to outreach."}


def test_memory_tools_are_scoped_to_memory_root(tmp_path: Path) -> None:
    store = MemoryFileStore(tmp_path / "memory-files")

    write_output = _build_write_memory_file_handler(store)(
        {
            "scope_kind": "global",
            "scope_ref": "workspace",
            "agent_definition_id": "agent-1",
            "path": "preferences.md",
            "content": "- Use concise status updates.\n",
        }
    )
    list_output = _build_list_memory_files_handler(store)(
        {"scope_kind": "global", "scope_ref": "workspace", "agent_definition_id": "agent-1"}
    )
    read_output = _build_read_memory_file_handler(store)(
        {
            "scope_kind": "global",
            "scope_ref": "workspace",
            "agent_definition_id": "agent-1",
            "path": "preferences.md",
        }
    )

    assert write_output["path"] == "preferences.md"
    assert list_output["count"] == 1
    assert read_output["content"] == "- Use concise status updates.\n"

    try:
        _build_delete_memory_file_handler(store)(
            {
                "scope_kind": "global",
                "scope_ref": "workspace",
                "agent_definition_id": "agent-1",
                "path": "../preferences.md",
            }
        )
    except ValueError as exc:
        assert "relative path inside the memory scope" in str(exc)
    else:
        raise AssertionError("memory tools must reject path traversal")


def test_core_record_learning_tool_queues_learning(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'learning-tool.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    output = _build_record_learning_handler(session_factory)(
        {"kind": "prompt_lesson", "payload": {"content": "Prefer verified candidate facts.", "tags": ["memory"]}}
    )

    assert output["queued"] is True
    assert output["learning_id"]


def test_scene_context_tool_detection_covers_computer_capabilities() -> None:
    browser_like = ToolDefinition(
        name="hid.semantic_action",
        description="Computer action",
        parameters={"type": "object"},
        handler=lambda arguments: arguments,
        metadata={"external_tool": True, "real_environment": True, "capabilities": ["computer", "computer_write"]},
    )

    assert is_scene_context_tool(browser_like) is True


def test_delegate_scene_context_tool_schema_mentions_browser_computer_contracts() -> None:
    tool = build_delegate_scene_context_tool(lambda arguments: arguments)
    properties = tool.parameters["properties"]

    assert "artifact_expectations" in properties["output_contract"]["description"]
    assert "local_download_create_attempt" in properties["output_contract"]["description"]
    assert "local_download_attribute" in properties["output_contract"]["description"]
    assert "business_writeback" in properties["output_contract"]["description"]
    assert "attach_resume_artifact" in properties["output_contract"]["description"]
    assert "browser_target" in properties["environment_requirements"]["description"]
    assert "structured fields" in properties["environment_requirements"]["description"]
    assert "browser_target" in properties
    assert "artifact_expectations" in properties
    assert "candidate landing regions" in properties["context"]["description"]


def test_delegate_scene_context_tool_inherits_runtime_browser_target() -> None:
    captured: dict[str, object] = {}
    registry = ToolRegistry()

    def _handler(arguments: dict[str, object]) -> dict[str, object]:
        captured.update(arguments)
        return {"ok": True}

    registry.register(build_delegate_scene_context_tool(_handler))
    runtime_tool = registry.to_agent_runtime_tools()[0]
    context = TurnContext(
        turn_id="turn-1",
        conversation_id="conversation-1",
        tools=[],
        runtime={
            "browser_target": {
                "url": "http://127.0.0.1:50149/#detail-jd-solution-002",
                "host": "127.0.0.1:50149",
            }
        },
    )
    call = ToolCall(
        id="tool-1",
        turn_id="turn-1",
        llm_invocation_id="llm-1",
        tool_use_id="use-1",
        name="delegate_scene_context",
        input={"instruction": "读取招聘站点职位列表与详情。"},
    )

    result = runtime_tool.handler.handle(call, context)

    assert result.is_error is False
    assert captured["browser_target"] == {
        "url": "http://127.0.0.1:50149/#detail-jd-solution-002",
        "host": "127.0.0.1:50149",
    }
    assert captured["environment_requirements"] == {"browser_target": captured["browser_target"]}
    assert captured["context"] == {"browser_target": captured["browser_target"]}


def test_delegate_scene_context_tool_projects_scene_capsule_for_parent_context() -> None:
    registry = ToolRegistry()

    def _handler(arguments: dict[str, object]) -> dict[str, object]:
        return {
            "status": "blocked",
            "summary": "已读取职位列表，但详情页仍需继续打开。",
            "result_data": {"found_jobs": 5, "completed_jobs": 1},
            "environment_context": {"dom": "<button>raw detail</button>", "clickPoint": {"x": 10, "y": 20}},
            "execution_contract": {"raw_hid": [{"type": "click", "at": {"x": 10, "y": 20}}]},
            "artifacts": [{"kind": "environment_snapshot", "snapshot_id": "snap-1"}],
            "metrics": {"tool_call_count": 12},
            "blockers": [{"kind": "continuable", "message": "需要继续读取详情", "raw": {"dom": "hidden"}}],
            "episode_id": "episode-1",
        }

    registry.register(build_delegate_scene_context_tool(_handler))
    runtime_tool = registry.to_agent_runtime_tools()[0]
    context = TurnContext(turn_id="turn-1", conversation_id="conversation-1", tools=[], runtime={})
    call = ToolCall(
        id="tool-1",
        turn_id="turn-1",
        llm_invocation_id="llm-1",
        tool_use_id="use-1",
        name="delegate_scene_context",
        input={"instruction": "读取招聘站点职位列表与详情。"},
    )

    result = runtime_tool.handler.handle(call, context)

    assert result.is_error is False
    assert result.metadata["scene_result_projection"] is True
    assert result.content == {
        "status": "blocked",
        "business_result": {"found_jobs": 5, "completed_jobs": 1},
        "blockers": [{"kind": "continuable", "message": "需要继续读取详情"}],
        "evidence_refs": [
            {"kind": "execution_episode", "id": "episode-1"},
            {"kind": "environment_snapshot", "id": "snap-1"},
        ],
        "projection": {
            "kind": "scene_result_summary",
            "raw_scene_context_stored": True,
            "raw_scene_context_access": "Use evidence_refs to inspect ExecutionEpisode, EnvironmentSnapshot, and runtime events when debugging or distilling skills.",
        },
    }
    projected_text = str(result.content)
    assert "environment_context" not in projected_text
    assert "execution_contract" not in projected_text
    assert "clickPoint" not in projected_text
    assert "raw_hid" not in projected_text


def test_jd_sync_delegate_scene_context_defaults_to_browser_and_computer_capabilities() -> None:
    captured: dict[str, object] = {}
    registry = ToolRegistry()

    def _handler(arguments: dict[str, object]) -> dict[str, object]:
        captured.update(arguments)
        return {"ok": True}

    registry.register(build_delegate_scene_context_tool(_handler))
    runtime_tool = registry.to_agent_runtime_tools()[0]
    context = TurnContext(
        turn_id="turn-1",
        conversation_id="conversation-1",
        tools=[],
        runtime={
            "constraints": {
                "plan_kind": "jd_sync",
                "browser_target": {
                    "url": "http://127.0.0.1:50149/",
                    "host": "127.0.0.1:50149",
                },
            }
        },
    )
    call = ToolCall(
        id="tool-1",
        turn_id="turn-1",
        llm_invocation_id="llm-1",
        tool_use_id="use-1",
        name="delegate_scene_context",
        input={"instruction": "读取招聘站点职位列表与详情。"},
    )

    result = runtime_tool.handler.handle(call, context)

    assert result.is_error is False
    assert captured["preferred_capabilities"] == ["browser", "computer"]
    assert captured["browser_target"] == {
        "url": "http://127.0.0.1:50149/",
        "host": "127.0.0.1:50149",
    }


def test_recruit_plugin_tools_are_marked_as_business_tools(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'business-tools.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    host = PluginHost()

    RecruitPluginManifest(session_factory).install(host)

    expected_permission_scopes = {
        "take_over_candidate": "business_write",
        "release_candidate": "business_write",
        "list_locked_candidates": "business_read",
        "list_job_descriptions": "business_read",
        "upsert_job_description": "business_write",
        "list_candidates": "business_read",
        "upsert_candidate": "business_write",
        "delete_candidate": "business_write",
        "archive_candidate": "business_write",
        "list_candidate_threads": "business_read",
        "get_candidate_thread": "business_read",
        "score_candidate": "business_write",
        "create_candidate_scorecard": "business_write",
        "create_candidate_review_decision": "business_write",
        "record_outbound_message": "business_write",
        "record_candidate_message": "business_write",
        "list_pending_candidate_message_syncs": "business_read",
        "record_candidate_message_sync_ack": "business_write",
        "attach_resume_artifact": "business_write",
        "delete_resume_artifact": "business_write",
        "transition_application": "business_write",
        "create_candidate_sync_record": "business_write",
        "get_jd_progress": "business_read",
        "request_human_approval": "approval",
    }
    assert set(host.tool_registry.tools) == set(expected_permission_scopes)
    for tool_name, permission_scope in expected_permission_scopes.items():
        tool = host.tool_registry.tools[tool_name]
        assert tool.category == "business"
        assert tool.metadata["business_tool"] is True
        assert tool.metadata["business_domain"] == "recruit"
        assert tool.resource_target_kind
        assert tool.metadata["permission_scope"] == permission_scope
        assert tool.metadata["risk_level"] in {"low", "medium", "high"}

    read_tool = host.tool_registry.tools["list_candidates"]
    write_tool = host.tool_registry.tools["upsert_candidate"]
    destructive_tool = host.tool_registry.tools["delete_candidate"]
    transition_tool = host.tool_registry.tools["transition_application"]
    approval_tool = host.tool_registry.tools["request_human_approval"]
    assert read_tool.metadata["business_tool"] is True
    assert read_tool.metadata["business_domain"] == "recruit"
    assert read_tool.metadata["permission_scope"] == "business_read"
    assert write_tool.metadata["permission_scope"] == "business_write"
    assert write_tool.metadata["risk_level"] == "medium"
    assert destructive_tool.metadata["risk_level"] == "high"
    assert destructive_tool.metadata["requires_confirmation"] is True
    assert transition_tool.metadata["risk_level"] == "high"
    assert transition_tool.metadata["requires_confirmation"] is True
    assert approval_tool.metadata["permission_scope"] == "approval"
    assert approval_tool.metadata["requires_confirmation"] is True
