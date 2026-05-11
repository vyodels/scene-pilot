from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.memory.service import MemoryService
from recruit_agent.memory.writeback import MemoryWritebackPolicy, apply_stable_memory_facts, should_start_memory_writeback_job
from recruit_agent.models.domain import (
    AgentTurnRecord,
    AgentRun,
    AgentRuntimeEvent,
    AgentSession,
    ApprovalItem,
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
                source="agent_runtime",
                event_type="turn_completed",
                message="turn_completed",
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


def test_memory_service_rejects_memory_item_id_cross_scope_updates(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        alice = Candidate(name="Alice")
        bob = Candidate(name="Bob")
        session.add_all([profile, alice, bob])
        session.commit()

        service = MemoryService(session)
        service.write(
            scope_kind="candidate",
            scope_ref=alice.id,
            agent_profile_id=profile.id,
            memory_item_id="candidate-status",
            kind="candidate_fact",
            index_name="status",
            index_description="Alice status",
            summary="Alice replied",
            content={"status": "replied"},
        )

        try:
            service.write(
                scope_kind="candidate",
                scope_ref=bob.id,
                agent_profile_id=profile.id,
                memory_item_id="candidate-status",
                kind="candidate_fact",
                index_name="status",
                index_description="Bob status",
                summary="Bob replied",
                content={"status": "replied"},
            )
        except ValueError as exc:
            assert "another scope" in str(exc)
        else:
            raise AssertionError("cross-scope memory_item_id update should be rejected")

        alice_index = service.index_for_scope("candidate", alice.id)
        bob_index = service.index_for_scope("candidate", bob.id)
        assert [item["summary"] for item in alice_index] == ["Alice replied"]
        assert bob_index == []
    finally:
        session.close()


def test_memory_service_rejects_global_memory_scope_mismatch(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        session.add(profile)
        session.commit()

        service = MemoryService(session)
        try:
            service.write(
                scope_kind="global",
                scope_ref="workspace",
                agent_profile_id=profile.id,
                memory_item_id="global-mismatch",
                kind="global_lesson",
                index_name="lesson",
                index_description="Lesson",
                summary="Lesson",
                content={"lesson": "value"},
            )
        except ValueError as exc:
            assert "global memory scope_ref" in str(exc)
        else:
            raise AssertionError("global memory scope mismatch should be rejected")
    finally:
        session.close()


def test_autonomous_turn_memory_writeback_accepts_explicit_stable_facts(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        session.add_all([profile, candidate])
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id)
        session.add(agent_session)
        session.flush()

        run = AgentRun(session_id=agent_session.id, run_id="run-memory-patch", agent_kind="autonomous")
        session.add(run)
        session.flush()
        turn = AgentTurnRecord(run_pk=run.id, seq=1, turn_id="turn-memory-patch")
        session.add(turn)
        session.commit()

        apply_stable_memory_facts(
            MemoryService(session),
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            facts=[{"summary": "Alice prefers remote roles.", "content": {"preference": "remote"}, "confidence": 0.8}],
            run_id=str(run.run_id),
            run_pk=run.id,
            turn_id=turn.turn_id,
            policy=MemoryWritebackPolicy(),
        )

        entries = MemoryService(session).read(
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            limit=10,
        )

        summaries = {item["summary"] for item in entries}
        assert "Alice prefers remote roles." in summaries
        assert not any(item["kind"] == "turn_summary" for item in entries)
    finally:
        session.close()


def test_memory_writeback_job_gate_does_not_call_llm_every_completed_turn() -> None:
    policy = MemoryWritebackPolicy(
        min_completed_turns_between_jobs=3,
        min_evidence_chars_between_jobs=1500,
    )

    assert not should_start_memory_writeback_job(
        policy,
        completed_turns_since_last_job=1,
        evidence_text="short completed turn",
    )
    assert should_start_memory_writeback_job(
        policy,
        completed_turns_since_last_job=3,
        evidence_text="short completed turn",
    )
    assert should_start_memory_writeback_job(
        policy,
        completed_turns_since_last_job=1,
        evidence_text="x" * 1500,
    )
    assert should_start_memory_writeback_job(
        policy,
        completed_turns_since_last_job=0,
        evidence_text="",
        force=True,
    )


def test_autonomous_turn_memory_writeback_clamps_patch_confidence(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        session.add_all([profile, candidate])
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id)
        session.add(agent_session)
        session.flush()

        run = AgentRun(session_id=agent_session.id, run_id="run-memory-confidence", agent_kind="autonomous")
        session.add(run)
        session.flush()
        turn = AgentTurnRecord(run_pk=run.id, seq=1, turn_id="turn-memory-confidence")
        session.add(turn)
        session.commit()

        apply_stable_memory_facts(
            MemoryService(session),
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            facts=[
                {"summary": "Alice is open to remote roles.", "confidence": 2.5},
                {"summary": "Alice can start in June.", "confidence": "high"},
            ],
            run_id=str(run.run_id),
            run_pk=run.id,
            turn_id=turn.turn_id,
            policy=MemoryWritebackPolicy(),
        )

        entries = MemoryService(session).read(
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            limit=10,
        )

        by_summary = {item["summary"]: item for item in entries}
        assert by_summary["Alice is open to remote roles."]["confidence"] == 1.0
        assert by_summary["Alice can start in June."]["confidence"] == 0.6
        assert session.query(ApprovalItem).filter_by(target_type="memory_writeback").count() == 0
    finally:
        session.close()


def test_memory_writeback_review_is_optional(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        session.add_all([profile, candidate])
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id)
        session.add(agent_session)
        session.flush()

        run = AgentRun(session_id=agent_session.id, run_id="run-memory-review", agent_kind="autonomous")
        session.add(run)
        session.flush()
        turn = AgentTurnRecord(run_pk=run.id, seq=1, turn_id="turn-memory-review")
        session.add(turn)
        session.commit()

        apply_stable_memory_facts(
            MemoryService(session),
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            facts=[{"summary": "Alice may prefer remote roles.", "confidence": 0.5}],
            run_id=str(run.run_id),
            run_pk=run.id,
            turn_id=turn.turn_id,
            policy=MemoryWritebackPolicy(review_enabled=True),
        )

        entries = MemoryService(session).read(
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            limit=10,
        )

        assert entries == []
        approval = session.query(ApprovalItem).filter_by(target_type="memory_writeback").one()
        assert approval.status == "pending"
        assert approval.payload["summary"] == "Alice may prefer remote roles."
    finally:
        session.close()


def test_autonomous_turn_memory_writeback_ignores_plain_final_output(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        session.add_all([profile, candidate])
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id)
        session.add(agent_session)
        session.flush()

        run = AgentRun(session_id=agent_session.id, run_id="run-memory-plain", agent_kind="autonomous")
        session.add(run)
        session.flush()
        turn = AgentTurnRecord(run_pk=run.id, seq=1, turn_id="turn-memory-plain")
        session.add(turn)
        session.commit()

        apply_stable_memory_facts(
            MemoryService(session),
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            facts=[],
            run_id=str(run.run_id),
            run_pk=run.id,
            turn_id=turn.turn_id,
            policy=MemoryWritebackPolicy(),
        )

        entries = MemoryService(session).read(
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            limit=10,
        )

        assert entries == []
    finally:
        session.close()
