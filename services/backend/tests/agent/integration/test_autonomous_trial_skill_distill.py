from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from recruit_agent.agents.autonomous import AutonomousAdapter
from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.evolution.learning_writer import LearningWriter
from recruit_agent.models.domain import AgentRun, AgentSession, EvolutionArtifact, GoalSpec, RecruitAgentProfile, Skill
from recruit_agent.plugins.host import PluginHost
from agent_runtime.fixtures import LLMResponse, ToolCall
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.capabilities.tools import ToolRegistry, register_core_tools


def _make_session_factory(tmp_path: Path):
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'autonomous-trial-skill.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)


def _seed_run(session_factory, *, goal_text: str = "把当前招聘页中的活跃 JD 增量同步到共享工作区。") -> str:
    with session_factory() as session:
        profile = RecruitAgentProfile(agent_key="autonomous", name="Autonomous", is_primary=True)
        session.add(profile)
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id, session_key="primary")
        session.add(agent_session)
        session.flush()

        goal = GoalSpec(
            agent_profile_id=profile.id,
            title="同步 JD（增量）",
            goal_text=goal_text,
            goal_kind="sync_jd_incremental",
            status="queued",
            source="operator",
            source_text=goal_text,
            requested_by="test-user",
            constraints={
                "scope_kind": "global",
                "memory_scope_kind": "global",
                "memory_scope_ref": profile.id,
                "global_scope_ref": profile.id,
            },
        )
        session.add(goal)
        session.flush()

        run = AgentRun(
            session_id=agent_session.id,
            goal_spec_id=goal.id,
            run_id="run-skill-distill-1",
            run_type="sync_jd_incremental",
            agent_kind="autonomous",
            status="queued",
            checkpoint_status="none",
            context_manifest={"goal": goal.goal_text, "title": goal.title},
            runtime_metadata={"goal_title": goal.title, "conversation_id": goal.id},
        )
        session.add(run)
        session.commit()
        return run.id


def test_autonomous_completed_run_creates_trial_skill_from_llm_distill(tmp_path: Path) -> None:
    session_factory = _make_session_factory(tmp_path)
    run_pk = _seed_run(session_factory)

    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="record_learning",
                        arguments={
                            "kind": "observation",
                            "payload": {"content": "观察到一个活跃 JD 卡片", "tags": ["sync_jd_incremental"]},
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content='{"status":"completed","created":1,"updated":0,"skipped":0,"blocked":0}',
                finish_reason="stop",
            ),
            LLMResponse(
                content="""{
  "skill_contract": {
    "skill_name": "活跃 JD 增量同步",
    "description": "在招聘页面里识别活跃岗位并把差异同步到共享工作区。",
    "category": "recruiting",
    "platform": "runtime-scene",
    "strategy": {
      "instruction": "优先复用已打开的招聘页面，只同步仍在活跃中的岗位。",
      "learned_patterns": ["先读取当前页面可见岗位，再与本地 JD 做差异比对。"],
      "observed_actions": ["读取当前页面", "写入本地 JD 库"]
    },
    "body": {
      "summary": "复用当前招聘页做活跃 JD 增量同步。",
      "checklist": ["确认岗位仍在活跃招聘", "写入前先比对本地记录"],
      "anti_patterns": ["不要把状态不明确的岗位当作活跃 JD 写入"],
      "artifacts": {
        "python_inline": {
          "entrypoint": "run",
          "code": "def run(payload, context):\\n    remote = list(payload.get('remote_jobs') or [])\\n    local_ids = set(payload.get('local_job_ids') or [])\\n    created = [item for item in remote if str(item.get('job_id') or '') not in local_ids]\\n    return {'created_count': len(created), 'skill': context['skill_id']}"
        }
      }
    },
    "execution_hints": {
      "executor_mode": "python_inline",
      "preconditions": ["存在可访问的招聘页面"],
      "tool_preferences": ["list_job_descriptions", "upsert_job_description"],
      "observed_outcomes": ["created=1", "updated=0", "skipped=0"]
    },
    "risk_level": "low",
    "health_check_config": {
      "expected_result_status": "completed"
    },
    "skill_metadata": {
      "source_kind": "autonomous",
      "goal_kind": "sync_jd_incremental",
      "llm_generated": true
    }
  }
}""",
                finish_reason="stop",
            ),
        ],
    )
    tools = ToolRegistry()
    register_core_tools(tools)
    agent = AutonomousAdapter(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
        learning_writer=LearningWriter(session_factory),
    )

    outcome = agent.run_turn_from_envelope(
        {
            "run_pk": run_pk,
            "run_id": "run-skill-distill-1",
            "trigger_type": "manual",
            "scope_kind": "global",
            "scope_ref": "shared-workspace",
            "world_snapshot": {"scene": "jobs"},
        }
    )

    assert outcome.status == "complete"
    assert outcome.gate_signal == "goal_done"

    with session_factory() as session:
        run = session.get(AgentRun, run_pk)
        assert run is not None
        assert run.status == "completed"

        skill = session.scalars(select(Skill).order_by(Skill.created_at.desc(), Skill.id.desc())).first()
        assert skill is not None
        assert skill.name == "活跃 JD 增量同步"
        assert skill.status == "trial"
        assert skill.strategy["instruction"] == "优先复用已打开的招聘页面，只同步仍在活跃中的岗位。"
        assert skill.strategy["instruction"] != "把当前招聘页中的活跃 JD 增量同步到共享工作区。"
        assert skill.execution_hints["executor_mode"] == "python_inline"
        assert skill.body["artifacts"]["python_inline"]["entrypoint"] == "run"

        artifact = session.scalars(
            select(EvolutionArtifact).where(EvolutionArtifact.artifact_kind == "skill_draft")
        ).first()
        assert artifact is not None
        assert artifact.status == "pending_review"
        assert artifact.related_skill_id == skill.id
        assert artifact.artifact_body["skill_contract"]["skill_name"] == "活跃 JD 增量同步"


def test_autonomous_run_stays_completed_when_skill_distill_response_is_invalid(tmp_path: Path) -> None:
    session_factory = _make_session_factory(tmp_path)
    run_pk = _seed_run(session_factory, goal_text="同步当前活跃 JD。")

    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="record_learning",
                        arguments={"kind": "observation", "payload": {"content": "观察到一个活跃 JD", "tags": ["sync_jd_incremental"]}},
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content='{"status":"completed","created":1}', finish_reason="stop"),
            LLMResponse(content="这不是 JSON", finish_reason="stop"),
        ],
    )
    tools = ToolRegistry()
    register_core_tools(tools)
    agent = AutonomousAdapter(
        session_factory=session_factory,
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
        learning_writer=LearningWriter(session_factory),
    )

    outcome = agent.run_turn_from_envelope(
        {
            "run_pk": run_pk,
            "run_id": "run-skill-distill-1",
            "trigger_type": "manual",
            "scope_kind": "global",
            "scope_ref": "shared-workspace",
            "world_snapshot": {"scene": "jobs"},
        }
    )

    assert outcome.status == "complete"
    with session_factory() as session:
        run = session.get(AgentRun, run_pk)
        assert run is not None
        assert run.status == "completed"
        assert session.scalars(select(Skill)).first() is None
        assert session.scalars(select(EvolutionArtifact).where(EvolutionArtifact.artifact_kind == "skill_draft")).first() is None
