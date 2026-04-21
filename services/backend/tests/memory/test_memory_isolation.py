from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from recruit_agent.core.settings import load_settings
from recruit_agent.models.domain import AgentGlobalMemory, Candidate, CandidatePersonMemory, JobDescription, JobDescriptionMemory, RecruitAgentProfile
from recruit_agent.server import create_app


def test_agents_memory_routes_isolate_candidate_job_and_global_by_agent(tmp_path: Path) -> None:
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

            candidate = Candidate(name="Shared Candidate")
            job = JobDescription(title="Shared Job")
            session.add_all([candidate, job])
            session.flush()

            session.add_all(
                [
                    CandidatePersonMemory(
                        agent_profile_id=autonomous.id,
                        person_id=candidate.id,
                        summary="autonomous candidate",
                        content={"owner": "autonomous"},
                        raw_content={"owner": "autonomous"},
                    ),
                    CandidatePersonMemory(
                        agent_profile_id=assistant.id,
                        person_id=candidate.id,
                        summary="assistant candidate",
                        content={"owner": "assistant"},
                        raw_content={"owner": "assistant"},
                    ),
                    JobDescriptionMemory(
                        agent_profile_id=autonomous.id,
                        job_description_id=job.id,
                        summary="autonomous job",
                        content={"owner": "autonomous"},
                        raw_content={"owner": "autonomous"},
                    ),
                    JobDescriptionMemory(
                        agent_profile_id=assistant.id,
                        job_description_id=job.id,
                        summary="assistant job",
                        content={"owner": "assistant"},
                        raw_content={"owner": "assistant"},
                    ),
                    AgentGlobalMemory(
                        agent_profile_id=autonomous.id,
                        summary="autonomous global",
                        content={"owner": "autonomous"},
                        raw_content={"owner": "autonomous"},
                    ),
                    AgentGlobalMemory(
                        agent_profile_id=assistant.id,
                        summary="assistant global",
                        content={"owner": "assistant"},
                        raw_content={"owner": "assistant"},
                    ),
                ]
            )
            session.commit()

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
