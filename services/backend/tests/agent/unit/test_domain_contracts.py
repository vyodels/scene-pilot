from __future__ import annotations

from scene_pilot.models.domain import (
    AgentGlobalMemory,
    AgentRun,
    AgentRuntimeEvent,
    ApprovalItem,
    CandidateAutonomousLock,
    CandidatePersonMemory,
    CompactionEvent,
    ConversationSession,
    ConversationTurn,
    JobAssembly,
    JobDescriptionMemory,
    McpServer,
    PromptOverlayRevision,
    Skill,
    ToolInvocation,
)


def _column_names(model: type) -> set[str]:
    return {column.name for column in model.__table__.columns}


def test_agent_run_contains_runtime_columns() -> None:
    columns = _column_names(AgentRun)
    assert {
        "run_id",
        "agent_kind",
        "turns_count",
        "ticks_count",
        "prompt_tokens",
        "completion_tokens",
        "cache_hit_tokens",
        "escalate_reason",
        "lock_scope",
        "idempotency_key",
        "wakeup_state",
        "runtime_metadata",
    } <= columns


def test_approval_item_contains_recovery_columns() -> None:
    columns = _column_names(ApprovalItem)
    assert {
        "run_pk",
        "tick_pk",
        "conversation_pk",
        "source_kind",
        "tool_name",
        "args_digest",
        "expires_at",
        "executed_at",
        "idempotency_key",
    } <= columns


def test_agent_runtime_event_contains_tick_turn_and_conversation_ids() -> None:
    columns = _column_names(AgentRuntimeEvent)
    assert {"tick_id", "turn_id", "conversation_id", "seq"} <= columns


def test_memory_tables_have_item_row_columns() -> None:
    required = {
        "memory_item_id",
        "kind",
        "index_name",
        "index_description",
        "confidence",
        "evidence_refs",
        "trust_level",
        "version",
        "supersedes_id",
        "expires_at",
        "item_metadata",
    }
    assert required <= _column_names(CandidatePersonMemory)
    assert required <= _column_names(JobDescriptionMemory)
    assert required <= _column_names(AgentGlobalMemory)


def test_skill_contains_trial_and_human_gate_columns() -> None:
    columns = _column_names(Skill)
    assert {"trigger_hint", "body", "trial_metrics", "requires_human_gate", "human_gate_policy"} <= columns


def test_mcp_server_contains_health_and_circuit_columns() -> None:
    columns = _column_names(McpServer)
    assert {"capabilities", "circuit_state", "circuit_until", "last_health_at", "last_error"} <= columns


def test_new_runtime_tables_are_declared() -> None:
    assert JobAssembly.__tablename__ == "job_assemblies"
    assert PromptOverlayRevision.__tablename__ == "prompt_overlay_revisions"
    assert ToolInvocation.__tablename__ == "tool_invocations"
    assert ConversationSession.__tablename__ == "conversation_sessions"
    assert ConversationTurn.__tablename__ == "conversation_turns"
    assert CompactionEvent.__tablename__ == "compaction_events"
    assert CandidateAutonomousLock.__tablename__ == "candidate_autonomous_locks"
