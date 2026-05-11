from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from recruit_agent.core.settings import load_settings
from recruit_agent.models.domain import RecruitAgentProfile
from recruit_agent.server import create_app


def test_agents_memory_routes_isolate_file_memory_by_agent_and_scope(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            autonomous = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
            assistant = session.query(RecruitAgentProfile).filter_by(agent_key="assistant").one()

        store = app.state.container.memory_file_store
        store.write_file(
            scope_kind="candidate",
            scope_ref="shared-candidate",
            agent_profile_id=autonomous.id,
            content="autonomous candidate\n",
        )
        store.write_file(
            scope_kind="candidate",
            scope_ref="shared-candidate",
            agent_profile_id=assistant.id,
            content="assistant candidate\n",
        )
        store.write_file(
            scope_kind="job",
            scope_ref="shared-job",
            agent_profile_id=autonomous.id,
            content="autonomous job\n",
        )
        store.write_file(
            scope_kind="job",
            scope_ref="shared-job",
            agent_profile_id=assistant.id,
            content="assistant job\n",
        )
        store.write_file(
            scope_kind="global",
            scope_ref="workspace",
            agent_profile_id=autonomous.id,
            content="autonomous global\n",
        )
        store.write_file(
            scope_kind="global",
            scope_ref="workspace",
            agent_profile_id=assistant.id,
            content="assistant global\n",
        )

        autonomous_candidate = client.get("/api/agents/autonomous/memory/candidate")
        assistant_candidate = client.get("/api/agents/assistant/memory/candidate")
        autonomous_job = client.get("/api/agents/autonomous/memory/job")
        assistant_job = client.get("/api/agents/assistant/memory/job")
        autonomous_global = client.get("/api/agents/autonomous/memory/global")
        assistant_global = client.get("/api/agents/assistant/memory/global")

        assert [item["summary"] for item in autonomous_candidate.json()] == ["autonomous candidate"]
        assert [item["summary"] for item in assistant_candidate.json()] == ["assistant candidate"]
        assert [item["summary"] for item in autonomous_job.json()] == ["autonomous job"]
        assert [item["summary"] for item in assistant_job.json()] == ["assistant job"]
        assert [item["summary"] for item in autonomous_global.json()] == ["autonomous global"]
        assert [item["summary"] for item in assistant_global.json()] == ["assistant global"]
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()
