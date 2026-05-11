from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from recruit_agent.agents.autonomous import AutonomousAdapter
from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import AgentRun, AgentSession, Candidate, RecruitAgentProfile
from recruit_agent.plugins.host import PluginHost
from recruit_agent.capabilities.tools import ToolRegistry, register_core_tools

from .test_memory_backed_continuity import ContinuityProvider


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'functional-memory.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_functional_closure_memory_service_is_in_autonomous_loop(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        session.add_all([profile, candidate])
        session.flush()
        agent_session = AgentSession(agent_profile_id=profile.id)
        session.add(agent_session)
        session.flush()
        run = AgentRun(session_id=agent_session.id, run_id="run-func-memory", person_id=candidate.candidate_person_id)
        session.add(run)
        session.commit()

        tools = ToolRegistry()
        register_core_tools(tools)
        agent = AutonomousAdapter(
            session_factory=create_session_factory(session.get_bind()),
            provider=ContinuityProvider(),
            tool_registry=tools,
            plugin_host=PluginHost(),
        )
        agent.run_turn_from_envelope({"run_pk": run.id, "scope_kind": "candidate", "scope_ref": candidate.candidate_person_id})
        outcome = agent.run_turn_from_envelope({"run_pk": run.id, "scope_kind": "candidate", "scope_ref": candidate.candidate_person_id})
        assert outcome.final_output == "continued"
    finally:
        session.close()
