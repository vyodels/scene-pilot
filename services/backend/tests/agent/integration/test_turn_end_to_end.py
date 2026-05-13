from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recruit_agent.agents.autonomous import AutonomousAdapter
from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import AgentRun, AgentSession, AgentTurnRecord, Candidate, AgentDefinition
from recruit_agent.plugins.host import PluginHost
from agent_runtime.fixtures import LLMResponse
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.capabilities.tools import ToolRegistry, register_core_tools


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
        definition = AgentDefinition(definition_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        session.add_all([definition, candidate])
        session.flush()

        agent_session = AgentSession(agent_definition_id=definition.id)
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
        agent = AutonomousAdapter(
            session_factory=session.bind and create_session_factory(session.get_bind()),
            provider=provider,
            tool_registry=tools,
            plugin_host=PluginHost(),
        )

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
