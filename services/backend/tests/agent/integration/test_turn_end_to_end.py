from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recruit_station.agents.autonomous import AutonomousAdapter
from recruit_station.core.settings import AppSettings
from recruit_station.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_station.models.domain import AgentRun, AgentSession, AgentTurnRecord, Candidate, AgentDefinition
from recruit_station.repositories.domain import TaskQueueRepository
from recruit_station.plugins.host import PluginHost
from agent_runtime.fixtures import LLMResponse
from agent_runtime.fixtures import ScriptedProvider
from recruit_station.capabilities.tools import ToolRegistry, register_core_tools


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
        assert refreshed_run.status == "idle"
        assert refreshed_run.turns_count == 1
        assert session.scalar(select(func.count()).select_from(AgentTurnRecord).where(AgentTurnRecord.run_pk == run.id)) == 1
    finally:
        session.close()


def test_transient_provider_error_requeues_runtime_run_instead_of_failing(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        definition = AgentDefinition(definition_key="jd-sync", name="JD Sync")
        session.add(definition)
        session.flush()

        agent_session = AgentSession(agent_definition_id=definition.id)
        session.add(agent_session)
        session.flush()

        run = AgentRun(
            session_id=agent_session.id,
            run_id="jd-sync-run-1",
            agent_kind="jd_sync",
            run_type="jd_sync",
            status="queued",
        )
        session.add(run)
        session.commit()

        class TransientProvider:
            provider_name = "transient"

            def invoke(self, _request):
                raise RuntimeError(
                    'HTTP 500 calling http://127.0.0.1:8317/v1/responses: {"error":{"message":"unexpected EOF","type":"server_error"}}'
                )

        agent = AutonomousAdapter(
            session_factory=session.bind and create_session_factory(session.get_bind()),
            provider=TransientProvider(),
            tool_registry=ToolRegistry(),
            plugin_host=PluginHost(),
        )

        outcome = agent.run_turn_from_envelope(
            {
                "run_pk": run.id,
                "trigger_type": "heartbeat",
                "scope_kind": "global",
                "scope_ref": "workspace",
                "world_snapshot": {},
            }
        )

        session.expire_all()
        refreshed_run = session.get(AgentRun, run.id)
        assert refreshed_run is not None
        assert outcome.metadata["provider_retry_scheduled"] is True
        assert refreshed_run.status == "queued"
        assert refreshed_run.finished_at is None
        assert "unexpected EOF" in str(refreshed_run.last_error)

        turns = session.query(AgentTurnRecord).filter(AgentTurnRecord.run_pk == run.id).all()
        assert len(turns) == 1
        assert turns[0].status == "retrying"
        assert turns[0].outcome_kind == "provider_retry"

        retry_task = TaskQueueRepository(session).get(str(refreshed_run.queue_task_id))
        assert retry_task is not None
        assert retry_task.status == "pending"
        assert retry_task.payload["metadata"]["provider_retry_count"] == 1
        assert retry_task.payload["trigger_type"] == "provider_retry"
    finally:
        session.close()
