from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from recruit_agent.core.settings import load_settings
from recruit_agent.models.domain import AgentRun, AgentSession, AgentTurnRecord, AgentDefinition
from recruit_agent.server import create_app


def test_turn_routes_expose_turns(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            definition = session.query(AgentDefinition).filter_by(definition_key="recruit-agent").one()
            agent_session = AgentSession(agent_definition_id=definition.id, session_key="autonomous")
            session.add(agent_session)
            session.flush()
            run = AgentRun(session_id=agent_session.id, run_id="run-turn-route", agent_kind="autonomous")
            session.add(run)
            session.flush()
            session.add(
                AgentTurnRecord(
                    run_pk=run.id,
                    seq=1,
                    trigger_type="manual",
                    status="completed",
                    outcome_kind="complete",
                )
            )
            session.commit()

        turns = client.get("/api/agents/autonomous/runs/run-turn-route/turns")
        assert turns.status_code == 200
        assert turns.json()[0]["seq"] == 1

        ticks = client.get("/api/agents/autonomous/runs/run-turn-route/ticks")
        assert ticks.status_code == 404
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()
