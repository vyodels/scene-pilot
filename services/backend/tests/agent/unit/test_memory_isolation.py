from __future__ import annotations

from pathlib import Path

from recruit_agent.memory.filesystem import MemoryFileStore
from recruit_agent.memory.writeback import (
    MemoryWritebackPolicy,
    should_start_memory_writeback_job,
    write_stable_memory_facts_to_files,
)


def test_memory_files_isolate_agent_profiles_and_scopes(tmp_path: Path) -> None:
    store = MemoryFileStore(tmp_path / "memory-files")

    store.write_file(
        scope_kind="conversation",
        scope_ref="session-1",
        agent_profile_id="assistant-profile",
        path="MEMORY.md",
        content="- Assistant-specific preference\n",
    )
    store.write_file(
        scope_kind="conversation",
        scope_ref="session-1",
        agent_profile_id="autonomous-profile",
        path="MEMORY.md",
        content="- Autonomous-specific preference\n",
    )
    store.write_file(
        scope_kind="candidate",
        scope_ref="candidate-1",
        agent_profile_id="assistant-profile",
        path="MEMORY.md",
        content="- Candidate-scoped fact\n",
    )

    assistant_memory = store.read_file(
        scope_kind="conversation",
        scope_ref="session-1",
        agent_profile_id="assistant-profile",
        path="MEMORY.md",
    )
    autonomous_memory = store.read_file(
        scope_kind="conversation",
        scope_ref="session-1",
        agent_profile_id="autonomous-profile",
        path="MEMORY.md",
    )
    candidate_file = store.read_file(
        scope_kind="candidate",
        scope_ref="candidate-1",
        agent_profile_id="assistant-profile",
        path="MEMORY.md",
    )

    assert assistant_memory["content"] == "- Assistant-specific preference\n"
    assert autonomous_memory["content"] == "- Autonomous-specific preference\n"
    assert candidate_file["content"] == "- Candidate-scoped fact\n"


def test_memory_file_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = MemoryFileStore(tmp_path / "memory-files")

    try:
        store.write_file(
            scope_kind="global",
            scope_ref="workspace",
            agent_profile_id="assistant-profile",
            path="../MEMORY.md",
            content="escape",
        )
    except ValueError as exc:
        assert "relative path inside the memory scope" in str(exc)
    else:
        raise AssertionError("memory file store must reject path traversal")


def test_file_memory_writeback_accepts_explicit_stable_facts(tmp_path: Path) -> None:
    store = MemoryFileStore(tmp_path / "memory-files")

    result = write_stable_memory_facts_to_files(
        store,
        scope_kind="candidate",
        scope_ref="candidate-1",
        agent_profile_id="autonomous-profile",
        facts=[{"summary": "Alice prefers remote roles.", "content": {"preference": "remote"}, "confidence": 0.8}],
        run_id="run-memory-patch",
        run_pk="run-pk",
        turn_id="turn-memory-patch",
        policy=MemoryWritebackPolicy(),
    )

    memory = store.read_file(
        scope_kind="candidate",
        scope_ref="candidate-1",
        agent_profile_id="autonomous-profile",
        path="stable_facts.md",
    )
    assert result.stable_facts_written == 1
    assert "Alice prefers remote roles." in memory["content"]
    assert "run-pk" in memory["content"]


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


def test_file_memory_writeback_filters_low_confidence_and_duplicates(tmp_path: Path) -> None:
    store = MemoryFileStore(tmp_path / "memory-files")
    policy = MemoryWritebackPolicy(min_confidence=0.7)

    first = write_stable_memory_facts_to_files(
        store,
        scope_kind="candidate",
        scope_ref="candidate-1",
        agent_profile_id="autonomous-profile",
        facts=[
            {"summary": "Alice is open to remote roles.", "confidence": 2.5},
            {"summary": "Alice can start in June.", "confidence": 0.4},
        ],
        policy=policy,
    )
    second = write_stable_memory_facts_to_files(
        store,
        scope_kind="candidate",
        scope_ref="candidate-1",
        agent_profile_id="autonomous-profile",
        facts=[{"summary": "Alice is open to remote roles.", "confidence": 0.9}],
        policy=policy,
    )

    memory = store.read_file(
        scope_kind="candidate",
        scope_ref="candidate-1",
        agent_profile_id="autonomous-profile",
        path="stable_facts.md",
    )
    assert first.stable_facts_written == 1
    assert second.stable_facts_written == 0
    assert "Alice is open to remote roles." in memory["content"]
    assert "Alice can start in June." not in memory["content"]
    assert second.skipped[0]["reason"] == "duplicate_summary"
