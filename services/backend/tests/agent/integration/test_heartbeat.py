from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from recruit_agent.agents.autonomous import AutonomousAdapter
from recruit_agent.agents.heartbeat import Heartbeat
from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import AgentGlobalState, AgentRun, AgentSession, Candidate, RecruitAgentProfile
from recruit_agent.plugins.host import PluginHost
from recruit_agent.repositories.domain import TaskQueueRepository
from agent_runtime.fixtures import LLMResponse
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.capabilities.tools import ToolRegistry, register_core_tools


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'heartbeat.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_heartbeat_claims_task_and_runs_autonomous_turn(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        session.add_all([profile, candidate])
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id)
        session.add(agent_session)
        session.flush()

        run = AgentRun(
            session_id=agent_session.id,
            run_id="run-1",
            agent_kind="autonomous",
            status="queued",
            person_id=candidate.candidate_person_id,
        )
        session.add(run)
        session.commit()

        TaskQueueRepository(session).enqueue(
            task_id="task-1",
            task_type="autonomous_turn",
            payload={
                "run_pk": run.id,
                "trigger_type": "heartbeat",
                "scope_kind": "candidate",
                "scope_ref": candidate.candidate_person_id,
                "world_snapshot": {"candidate": "ready"},
            },
        )

        provider = ScriptedProvider(provider_name="scripted", responses=[LLMResponse(content="completed")])
        tools = ToolRegistry()
        register_core_tools(tools)
        agent = AutonomousAdapter(
            session_factory=create_session_factory(session.get_bind()),
            provider=provider,
            tool_registry=tools,
            plugin_host=PluginHost(),
        )
        heartbeat = Heartbeat(session_factory=create_session_factory(session.get_bind()), autonomous_adapter=agent)

        result = heartbeat.run_once()

        session.expire_all()
        assert result["status"] == "processed"
        assert TaskQueueRepository(session).get("task-1").status == "completed"
        assert session.get(AgentRun, run.id).status == "completed"
    finally:
        session.close()


def test_heartbeat_honors_global_pause(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        session.add(AgentGlobalState(id="singleton", autonomous_paused=True, pause_reason="human"))
        session.commit()

        provider = ScriptedProvider(provider_name="scripted", responses=[LLMResponse(content="completed")])
        tools = ToolRegistry()
        register_core_tools(tools)
        agent = AutonomousAdapter(
            session_factory=create_session_factory(session.get_bind()),
            provider=provider,
            tool_registry=tools,
            plugin_host=PluginHost(),
        )
        heartbeat = Heartbeat(session_factory=create_session_factory(session.get_bind()), autonomous_adapter=agent)

        result = heartbeat.run_once()

        assert result["status"] == "paused"
        assert result["reason"] == "human"
    finally:
        session.close()
