from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from recruit_agent.agents.autonomous import AutonomousAgent
from recruit_agent.evolution.learning_writer import LearningWriter
from recruit_agent.kernel.kernel import AgentKernel
from recruit_agent.models.domain import AgentRun, AgentRuntimeEvent, AgentSession, EvolutionArtifact, GoalSpec, RecruitAgentProfile, Skill
from recruit_agent.plugins.host import PluginHost
from recruit_agent.runtime.models import LLMResponse, ToolCall
from recruit_agent.runtime.providers import ScriptedProvider
from recruit_agent.runtime.tools import ToolRegistry, register_core_tools

from ._helpers import make_session_factory


def _setup_run(tmp_path: Path):
    session_factory = make_session_factory(tmp_path, "autonomous-skill-distill.db")
    with session_factory() as session:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        session.add(profile)
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id)
        session.add(agent_session)
        session.flush()

        goal = GoalSpec(
            agent_profile_id=profile.id,
            title="发现候选人",
            goal_text="敏感 goal_text 不应被主程序直接复制进 skill 正文",
            goal_kind="candidate_discovery",
            status="queued",
            constraints={},
        )
        session.add(goal)
        session.flush()

        run = AgentRun(
            session_id=agent_session.id,
            goal_spec_id=goal.id,
            run_id="run-1",
            run_type="candidate_discovery",
            agent_kind="autonomous",
            status="queued",
        )
        session.add(run)
        session.commit()
        return session_factory, profile.id, run.id


def _build_kernel(provider: ScriptedProvider, session_factory):
    tools = ToolRegistry()
    register_core_tools(tools)
    return AgentKernel(
        provider=provider,
        tool_registry=tools,
        plugin_host=PluginHost(),
        learning_writer=LearningWriter(session_factory),
    )


def test_autonomous_completed_run_distills_trial_skill_from_llm_response(tmp_path: Path) -> None:
    session_factory, _, run_pk = _setup_run(tmp_path)
    skill_contract = {
        "skill_name": "候选人线索归档",
        "description": "把成功的候选人线索收集过程沉淀为可复用技能。",
        "trigger_hint": "归档候选人线索",
        "category": "recruiting",
        "bound_to_stage": "candidate_discovery",
        "platform": "runtime-scene",
        "body": {
            "summary": "先确认线索有效，再做结构化归档。",
            "checklist": ["检查候选人线索", "确认有效信息", "写入结果"],
        },
        "strategy": {
            "instruction": "从成功 run 中抽取稳定动作，而不是复述目标文本。",
            "learned_patterns": ["优先记录已验证的线索"],
            "observed_actions": ["读取线索", "确认有效性", "完成归档"],
        },
        "execution_hints": {
            "prerequisites": ["已有成功 run 回顾"],
            "observed_outcomes": ["形成可复用的线索归档路径"],
        },
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object", "properties": {}},
        "health_check_config": {"expected_result_status": "pass"},
        "skill_metadata": {"review_basis": "基于本次成功 run 的工具调用与结果回顾"},
    }
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="tool-1", name="read_memory", arguments={"scope_kind": "global", "scope_ref": "workspace:shared"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="完成候选人发现并记录结果。"),
            LLMResponse(content=json.dumps(skill_contract, ensure_ascii=False)),
        ],
    )
    kernel = _build_kernel(provider, session_factory)
    agent = AutonomousAgent(session_factory=session_factory, kernel=kernel)

    outcome = agent.run_turn_from_envelope({"run_pk": run_pk, "scope_kind": "global", "scope_ref": "workspace:shared"})

    assert outcome.status == "complete"
    with session_factory() as session:
        run = session.get(AgentRun, run_pk)
        artifact = session.scalars(select(EvolutionArtifact).where(EvolutionArtifact.artifact_kind == "skill_draft")).first()
        skill = session.scalars(select(Skill).where(Skill.name == "候选人线索归档")).first()
        events = session.scalars(
            select(AgentRuntimeEvent)
            .where(AgentRuntimeEvent.run_id == run_pk)
            .order_by(AgentRuntimeEvent.created_at.asc(), AgentRuntimeEvent.id.asc())
        ).all()

        assert run is not None
        assert run.status == "completed"
        assert artifact is not None
        assert skill is not None
        assert skill.status == "trial"
        assert skill.body["summary"] == skill_contract["body"]["summary"]
        assert skill.strategy["instruction"] == skill_contract["strategy"]["instruction"]
        assert "敏感 goal_text" not in json.dumps(skill.body, ensure_ascii=False)
        assert "敏感 goal_text" not in json.dumps(skill.strategy, ensure_ascii=False)
        assert artifact.related_skill_id == skill.id
        assert artifact.artifact_body["skill_contract"]["skill_name"] == "候选人线索归档"
        assert any(event.event_type == "skill_distill.completed" for event in events)


def test_autonomous_skill_distill_failure_does_not_fail_run(tmp_path: Path) -> None:
    session_factory, _, run_pk = _setup_run(tmp_path)
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="tool-1", name="read_memory", arguments={"scope_kind": "global", "scope_ref": "workspace:shared"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="完成候选人发现并记录结果。"),
        ],
    )
    kernel = _build_kernel(provider, session_factory)
    agent = AutonomousAgent(session_factory=session_factory, kernel=kernel)

    outcome = agent.run_turn_from_envelope({"run_pk": run_pk, "scope_kind": "global", "scope_ref": "workspace:shared"})

    assert outcome.status == "complete"
    with session_factory() as session:
        run = session.get(AgentRun, run_pk)
        artifact = session.scalars(select(EvolutionArtifact).where(EvolutionArtifact.artifact_kind == "skill_draft")).first()
        events = session.scalars(
            select(AgentRuntimeEvent)
            .where(AgentRuntimeEvent.run_id == run_pk)
            .order_by(AgentRuntimeEvent.created_at.asc(), AgentRuntimeEvent.id.asc())
        ).all()

        assert run is not None
        assert run.status == "completed"
        assert artifact is None
        assert any(event.event_type == "skill_distill.failed" for event in events)


def test_autonomous_blocked_final_payload_marks_run_blocked(tmp_path: Path) -> None:
    session_factory, _, run_pk = _setup_run(tmp_path)
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[LLMResponse(content='{"status":"blocked","next_step":"等待可继续执行条件满足。"}')],
    )
    kernel = _build_kernel(provider, session_factory)
    agent = AutonomousAgent(session_factory=session_factory, kernel=kernel)

    outcome = agent.run_turn_from_envelope({"run_pk": run_pk, "scope_kind": "global", "scope_ref": "workspace:shared"})

    assert outcome.status == "escalate"
    assert outcome.gate_signal == "escalate"
    with session_factory() as session:
        run = session.get(AgentRun, run_pk)
        assert run is not None
        assert run.status == "blocked"
        assert run.finished_at is not None
