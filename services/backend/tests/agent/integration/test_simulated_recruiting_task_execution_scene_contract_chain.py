from __future__ import annotations

import json
from pathlib import Path

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import ExecutionEpisode
from recruit_agent.plugins.host import PluginHost
from recruit_agent.plugins.recruit.toolkit import attach_resume_artifact, upsert_candidate, upsert_job_description
from agent_runtime.fixtures import LLMResponse, ToolCall
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.capabilities.tools import ToolDefinition, ToolRegistry
from recruit_agent.services.scene_context import SceneContextService
from recruit_agent.services.scene_templates import shared_scene_template_catalog


_FIXTURE_PATH = Path(__file__).with_name("simulated_recruiting_task_execution_contracts.json")


def _session_factory(tmp_path: Path):
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'simulated-agent-task-execution.db'}",
        provider_config={},
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)


def _load_fixture() -> dict[str, object]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _build_service(session_factory, stage: dict[str, object]) -> SceneContextService:
    tool_call = dict(stage["tool_call"])
    provider_final = dict(stage["provider_final"])
    snapshot_output = dict(stage["snapshot_output"])
    provider = ScriptedProvider(
        provider_name=f"scene-scripted-{stage['stage_key']}",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=f"{stage['stage_key']}-snapshot",
                        name=str(tool_call["name"]),
                        arguments=dict(tool_call["arguments"]),
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content=str(provider_final["content"]),
                result_data=dict(provider_final["result_data"]),
                finish_reason="stop",
            ),
        ],
    )
    tools = ToolRegistry()
    expected_arguments = dict(tool_call["arguments"])

    def _browser_snapshot(arguments: dict[str, object]) -> dict[str, object]:
        assert arguments == expected_arguments
        runtime_metadata = dict(snapshot_output.get("runtime_metadata") or {})
        runtime_metadata["requested_arguments"] = dict(arguments)
        return {
            **snapshot_output,
            "runtime_metadata": runtime_metadata,
        }

    tools.register(
        ToolDefinition(
            name=str(tool_call["name"]),
            description="Capture current browser scene for the simulated autonomous recruiting task execution.",
            parameters={"type": "object", "additionalProperties": True},
            handler=_browser_snapshot,
            metadata={"capabilities": ["browser", "document"], "external_tool": True, "real_environment": True},
        )
    )
    return SceneContextService(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
    )


def test_autonomous_recruiting_task_execution_scene_contract_chain_proves_artifact_completion_and_upload(tmp_path: Path) -> None:
    fixture = _load_fixture()
    session_factory = _session_factory(tmp_path)
    results: dict[str, dict[str, object]] = {}
    created_job_id = ""
    created_application_id = ""

    for stage in list(fixture["stages"]):
        service = _build_service(session_factory, stage)
        result = service.delegate(dict(stage["delegate_request"]))
        stage_key = str(stage["stage_key"])
        results[stage_key] = result

        assert result["status"] == "completed"
        assert "tabId" not in str(result["summary"])
        assert "sig-resume-download" not in str(result["summary"])
        assert result["execution_contract"]["browser_target"]["tab_id"] == stage["delegate_request"]["environment_requirements"]["browser_target"]["tabId"]

        if stage_key == "sync_jd_incremental":
            assert result["execution_contract"]["execution_kind"] == "browser_scene_execution"
            for job_payload in list(stage["workspace_write"]["jobs"]):
                stored = upsert_job_description(session_factory, **job_payload)
                created_job_id = str(stored["job_description"]["job_description_id"])
            assert created_job_id

        if stage_key == "candidate_discovery":
            assert result["execution_contract"]["execution_kind"] == "browser_scene_execution"
            for candidate_payload in list(stage["workspace_write"]["candidates"]):
                stored = upsert_candidate(
                    session_factory,
                    **candidate_payload,
                    job_description_id=created_job_id,
                )
                created_application_id = str(stored["application"]["application_id"])
            assert created_application_id
            assert result["result_data"]["discovered_count"] == 1

        if stage_key == "resume_collection":
            assert result["execution_contract"]["execution_kind"] == "browser_computer_scene_execution"
            assert result["execution_contract"]["coordinate_policy"] == "delegate_to_hid"
            assert result["environment_context"]["computer_target"]["post_mode"] == "auto"
            assert result["environment_context"]["target_regions"][0]["signature"] == "sig-resume-download"
            assert result["environment_context"]["target_regions"][0]["href"] == "https://recruiting.example.test/downloads/li-qing-resume.pdf"
            assert result["execution_contract"]["action_plan"][0]["download_source"]["source_url"] == "https://recruiting.example.test/downloads/li-qing-resume.pdf"
            assert result["execution_contract"]["action_plan"][0]["download_source"]["expected_filename"] == "li-qing-resume.pdf"
            assert result["environment_context"]["artifact_expectations"]["requires_local_artifact"] is True
            assert result["environment_context"]["artifact_expectations"]["verify_path"] is True
            assert result["environment_context"]["artifact_expectations"]["verify_format"] is True
            assert result["environment_context"]["artifact_expectations"]["download_lookup"]["source_url"] == "https://recruiting.example.test/downloads/li-qing-resume.pdf"
            assert result["environment_context"]["artifact_expectations"]["download_lookup"]["started_after"] == "2026-04-25T09:00:00.000Z"
            assert result["result_data"]["artifact"]["path"] == "/tmp/li-qing-resume.pdf"
            assert result["result_data"]["artifact"]["format"] == "pdf"
            uploaded = attach_resume_artifact(
                session_factory,
                application_id=created_application_id,
                artifact_type=str(stage["workspace_write"]["artifact_type"]),
                source=str(stage["workspace_write"]["source"]),
                file_name=str(result["result_data"]["artifact"]["file_name"]),
                file_path=str(result["result_data"]["artifact"]["path"]),
                extracted_text=str(result["result_data"]["extracted_text"]),
                contact_snapshot=dict(result["result_data"]["contact_snapshot"]),
                metadata={
                    "origin": "simulated_scene_contract",
                    "scene_stage": stage_key,
                },
            )
            assert uploaded["artifact"]["filePath"] == "/tmp/li-qing-resume.pdf"
            assert uploaded["thread"]["application"]["resumeAvailable"] is True
            assert uploaded["thread"]["stateSnapshot"]["resume_status"] == "received"

    with session_factory() as session:
        episodes = session.query(ExecutionEpisode).order_by(ExecutionEpisode.created_at.asc(), ExecutionEpisode.id.asc()).all()
        assert len(episodes) == 3
        assert [episode.execution_kind for episode in episodes] == [
            "browser_scene_execution",
            "browser_scene_execution",
            "browser_computer_scene_execution",
        ]
        for episode in episodes:
            assert "tabId" not in str(episode.result_summary or "")
            assert "sig-resume-download" not in str(episode.result_summary or "")
            assert "clickPoint" not in str(episode.result_summary or "")


def test_resume_collection_scene_template_is_listed_for_simulated_recruiting_task_execution(tmp_path: Path) -> None:
    template = shared_scene_template_catalog()["resume_collection"]

    assert template["action_kind"] == "resume_collection"
    assert template["requires_jd"] is True
    assert template["direct_runnable"] is False
    assert "本地 artifact 路径定位与业务格式验证" in template["summary"]
    assert "共享工作区" in template["default_instruction"]
    assert "zhipin.com" not in template["summary"]
