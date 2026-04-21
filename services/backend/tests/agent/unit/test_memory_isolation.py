from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.memory.service import MemoryService
from recruit_agent.models.domain import (
    AgentRun,
    AgentRuntimeEvent,
    AgentSession,
    Candidate,
    ConversationSession,
    JobDescription,
    RecruitAgentProfile,
)


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'agent-memory.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_memory_service_isolates_scope_indexes_and_fetches_context(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        job = JobDescription(title="Backend Engineer")
        session.add_all([profile, candidate, job])
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id)
        session.add(agent_session)
        session.flush()

        run = AgentRun(session_id=agent_session.id, run_id="run-1", agent_kind="autonomous")
        conversation = ConversationSession(
            conversation_id="conv-1",
            user_id="user-1",
            assistant_id="assistant-default",
            assistant_assembly_id="assistant-default",
            title="Test",
            jsonl_path="/tmp/conv-1.jsonl",
        )
        session.add_all([run, conversation])
        session.commit()

        service = MemoryService(session)
        service.write(
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            memory_item_id="cand-1",
            kind="candidate_fact",
            index_name="candidate-location",
            index_description="Candidate is based in Shanghai",
            summary="Candidate location",
            content={"city": "Shanghai"},
        )
        service.write(
            scope_kind="job",
            scope_ref=job.id,
            agent_profile_id=profile.id,
            memory_item_id="job-1",
            kind="job_pattern",
            index_name="must-have-python",
            index_description="Role requires strong Python skills",
            summary="Job requirement",
            content={"skill": "Python"},
        )
        service.write(
            scope_kind="global",
            scope_ref=profile.id,
            agent_profile_id=profile.id,
            memory_item_id="global-1",
            kind="global_lesson",
            index_name="reply-window",
            index_description="Follow up after three business days",
            summary="Global lesson",
            content={"days": 3},
        )
        service.set_run_context(run.id, {"goal": "follow up candidates"})
        session.add(
            AgentRuntimeEvent(
                session_id=agent_session.id,
                run_id=run.id,
                source="kernel",
                event_type="turn.completed",
                message="turn finished",
                turn_id="turn-1",
                seq=1,
            )
        )
        session.commit()

        candidate_index = service.index_for_scope("candidate", candidate.id)
        job_index = service.index_for_scope("job", job.id)
        global_index = service.index_for_scope("global", profile.id)

        assert [item["memory_item_id"] for item in candidate_index] == ["cand-1"]
        assert [item["memory_item_id"] for item in job_index] == ["job-1"]
        assert [item["memory_item_id"] for item in global_index] == ["global-1"]

        hits = service.search_semantic("Shanghai", scope_kind="candidate", scope_ref=candidate.id)
        assert [item["memory_item_id"] for item in hits] == ["cand-1"]
        assert service.fetch_run_context(run.id) == {"goal": "follow up candidates"}
        assert service.fetch_session_summary(conversation.id) is None
        recent_events = service.fetch_recent_events(run_id=run.id)
        assert [event["turn_id"] for event in recent_events] == ["turn-1"]
    finally:
        session.close()
