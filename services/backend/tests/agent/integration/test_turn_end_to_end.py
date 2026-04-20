from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scene_pilot.agents.autonomous import AutonomousAgent
from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.kernel.kernel import AgentKernel
from scene_pilot.models.domain import AgentRun, AgentSession, AgentTurnRecord, Candidate, RecruitAgentProfile
from scene_pilot.plugins.host import PluginHost
from scene_pilot.runtime.models import LLMResponse
from scene_pilot.runtime.providers import ScriptedProvider
from scene_pilot.runtime.tools import ToolRegistry, register_core_tools


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'autonomous-turn.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_autonomous_turn_persists_run_turn_records(tmp_path: Path) -> None:
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

        provider = ScriptedProvider(provider_name="scripted", responses=[LLMResponse(content="completed")])
        tools = ToolRegistry()
        register_core_tools(tools)
        kernel = AgentKernel(provider=provider, tool_registry=tools, plugin_host=PluginHost())
        agent = AutonomousAgent(session_factory=session.bind and create_session_factory(session.get_bind()), kernel=kernel)

        outcome = agent.run_turn_from_envelope(
            {
                "run_pk": run.id,
                "scope_kind": "candidate",
                "scope_ref": candidate.candidate_person_id,
                "world_snapshot": {"candidate": "ready"},
            }
        )

        session.expire_all()
        refreshed_run = session.get(AgentRun, run.id)
        assert refreshed_run is not None
        assert outcome.status == "complete"
        assert refreshed_run.status == "completed"
        assert refreshed_run.turns_count == 1
        assert session.scalar(select(func.count()).select_from(AgentTurnRecord).where(AgentTurnRecord.run_pk == run.id)) == 1
    finally:
        session.close()
