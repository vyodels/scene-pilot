from __future__ import annotations

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
        assert episode.execution_kind == "generic_environment_execution"
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
