from __future__ import annotations

import json
from pathlib import Path

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import AgentLearning, EnvironmentSnapshot, ExecutionEpisode, ExecutionPlan, TaskSpec
from recruit_agent.plugins.host import PluginHost
from recruit_agent.runtime.models import LLMResponse, ToolCall
from recruit_agent.runtime.providers import ScriptedProvider
from recruit_agent.runtime.tools import ToolDefinition, ToolRegistry
from recruit_agent.services.scene_context import SceneContextService


def _session_factory(tmp_path: Path):
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'scene-context.db'}",
        provider_config={},
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)


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


def test_scene_context_does_not_mark_failed_structured_final_as_completed(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    provider = ScriptedProvider(
        provider_name="scene-scripted",
        responses=[
            LLMResponse(
                content=(
                    '{"status":"failed_no_verified_local_artifact",'
                    '"failure_reason":"download record did not produce a verified local path"}'
                )
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
    assert "failed_no_verified_local_artifact" in result["summary"]

    with session_factory() as session:
        episode = session.query(ExecutionEpisode).one()
        assert episode.status == "failed"


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


def test_scene_context_promotes_structured_final_json_to_result_data_and_artifacts(tmp_path: Path) -> None:
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
                content=json.dumps(
                    {
                        "status": "blocked",
                        "browser_download": {
                            "located": True,
                            "state": "complete",
                            "filename": "candidate-resume.pdf",
                            "fileName": "candidate-resume.pdf",
                            "sourceUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
                        },
                    }
                ),
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
                content=json.dumps(
                    {
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
                    }
                ),
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
                            "geometry": {"coordSpace": "viewport", "pageScale": 1},
                            "options": {"postMode": "auto", "dryRun": True},
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
                        "scrollX": 0,
                        "scrollY": 128,
                        "screenX": 100,
                        "screenY": 80,
                        "viewportInScreen": {"x": 112, "y": 144, "width": 1440, "height": 900},
                        "visualViewport": {"scale": 1},
                    },
                },
                "tabId": arguments.get("tabId"),
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
    assert hid_arguments["context"]["host"] == "recruit.example.test"
    assert hid_arguments["context"]["url"] == "https://recruit.example.test/candidate/613"
    assert hid_arguments["primitives"] == [{"type": "click", "at": {"x": 1642, "y": 56}, "button": "left"}]
    assert "viewportInScreen" not in hid_arguments["geometry"]
    assert hid_arguments["geometry"]["scrollOffset"] == {"x": 0, "y": 128}
    assert hid_arguments["geometry"]["viewportSize"] == {"x": 0, "y": 0, "width": 1440, "height": 900}


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
