from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


SCHEMA_MIGRATIONS_TABLE = "schema_migrations"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


MigrationFn = Callable[[Connection], None]


@dataclass(frozen=True, slots=True)
class SchemaMigration:
    version: int
    name: str
    apply: MigrationFn


def _noop(_: Connection) -> None:
    return


def _legacy_database_memory_table_names() -> tuple[str, ...]:
    memory = "memories"
    return (
        "_".join(("candidate", memory)),
        "_".join(("job", memory)),
        "_".join(("agent", "global", memory)),
        "_".join(("candidate", "person", memory)),
        "_".join(("job", "description", memory)),
    )


def _drop_legacy_database_memory_tables(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    for table_name in _legacy_database_memory_table_names():
        if table_name in tables:
            connection.execute(text(f"DROP TABLE {table_name}"))


def _create_supporting_indexes(connection: Connection) -> None:
    indexed_tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    statements_by_table = {
        "task_queue": (
            "CREATE INDEX IF NOT EXISTS ix_task_queue_status_scheduled_for ON task_queue (status, scheduled_for)",
            "CREATE INDEX IF NOT EXISTS ix_task_queue_locked_at ON task_queue (locked_at)",
        ),
        "sync_backlog": (
            "CREATE INDEX IF NOT EXISTS ix_sync_backlog_status_item_type ON sync_backlog (status, item_type)",
        ),
        "approval_items": (
            "CREATE INDEX IF NOT EXISTS ix_approval_items_status_target_type ON approval_items (status, target_type)",
        ),
    }
    for table_name, statements in statements_by_table.items():
        if table_name not in indexed_tables:
            continue
        for statement in statements:
            connection.execute(text(statement))


def _sync_backlog_protocol_columns(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "sync_backlog" not in tables:
        return

    columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(sync_backlog)")).fetchall()
    }
    statements = []
    if "protocol_version" not in columns:
        statements.append("ALTER TABLE sync_backlog ADD COLUMN protocol_version TEXT NOT NULL DEFAULT 'v1'")
    if "destination" not in columns:
        statements.append("ALTER TABLE sync_backlog ADD COLUMN destination TEXT NOT NULL DEFAULT 'intranet'")
    if "attempt_count" not in columns:
        statements.append("ALTER TABLE sync_backlog ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0")
    if "last_attempted_at" not in columns:
        statements.append("ALTER TABLE sync_backlog ADD COLUMN last_attempted_at TEXT")
    if "last_error" not in columns:
        statements.append("ALTER TABLE sync_backlog ADD COLUMN last_error TEXT")
    for statement in statements:
        connection.execute(text(statement))
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_sync_backlog_destination ON sync_backlog (destination)")
    )


def _create_general_runtime_indexes(connection: Connection) -> None:
    indexed_tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    statements_by_table = {
        "task_specs": (
            "CREATE INDEX IF NOT EXISTS ix_task_specs_status_domain ON task_specs (status, domain)",
        ),
        "playbook_versions": (
            "CREATE INDEX IF NOT EXISTS ix_playbook_versions_status_domain ON playbook_versions (status, domain)",
        ),
        "execution_plans": (
            "CREATE INDEX IF NOT EXISTS ix_execution_plans_status_mode ON execution_plans (status, mode)",
            "CREATE INDEX IF NOT EXISTS ix_execution_plans_task_spec_created_at ON execution_plans (task_spec_id, created_at)",
        ),
        "execution_episodes": (
            "CREATE INDEX IF NOT EXISTS ix_execution_episodes_status_mode ON execution_episodes (status, mode)",
            "CREATE INDEX IF NOT EXISTS ix_execution_episodes_plan_created_at ON execution_episodes (execution_plan_id, created_at)",
        ),
        "environment_snapshots": (
            "CREATE INDEX IF NOT EXISTS ix_environment_snapshots_episode_environment_kind ON environment_snapshots (execution_episode_id, environment_kind)",
        ),
        "playbook_patches": (
            "CREATE INDEX IF NOT EXISTS ix_playbook_patches_status_kind ON playbook_patches (status, patch_kind)",
            "CREATE INDEX IF NOT EXISTS ix_playbook_patches_template_created_at ON playbook_patches (template_id, created_at)",
        ),
    }
    for table_name, statements in statements_by_table.items():
        if table_name not in indexed_tables:
            continue
        for statement in statements:
            connection.execute(text(statement))


def _extend_skill_schema(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "skills" not in tables:
        return

    columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(skills)")).fetchall()
    }
    statements = []
    if "description" not in columns:
        statements.append("ALTER TABLE skills ADD COLUMN description TEXT")
    if "category" not in columns:
        statements.append("ALTER TABLE skills ADD COLUMN category TEXT NOT NULL DEFAULT 'general'")
    if "input_schema" not in columns:
        statements.append("ALTER TABLE skills ADD COLUMN input_schema TEXT NOT NULL DEFAULT '{}'")
    if "output_schema" not in columns:
        statements.append("ALTER TABLE skills ADD COLUMN output_schema TEXT NOT NULL DEFAULT '{}'")
    if "risk_level" not in columns:
        statements.append("ALTER TABLE skills ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'medium'")
    if "skill_metadata" not in columns:
        statements.append("ALTER TABLE skills ADD COLUMN skill_metadata TEXT NOT NULL DEFAULT '{}'")
    for statement in statements:
        connection.execute(text(statement))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_category_status ON skills (category, status)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_risk_level ON skills (risk_level)"))


def _extend_recruit_agent_state_schema(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "candidates" in tables:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(candidates)")).fetchall()}
        if "state_snapshot" not in columns:
            connection.execute(text("ALTER TABLE candidates ADD COLUMN state_snapshot TEXT NOT NULL DEFAULT '{}'"))

    if "communication_logs" in tables:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(communication_logs)")).fetchall()}
        if "metadata" not in columns:
            connection.execute(text("ALTER TABLE communication_logs ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'"))

    indexed_tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "candidate_stage_events" in indexed_tables:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_stage_events_candidate_occurred_at ON candidate_stage_events (candidate_id, occurred_at)")
        )
    if "candidate_assessments" in indexed_tables:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_assessments_candidate_created_at ON candidate_assessments (candidate_id, created_at)")
        )
    if "evolution_artifacts" in indexed_tables:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_evolution_artifacts_kind_status ON evolution_artifacts (artifact_kind, status)")
        )


def _extend_candidate_fact_tables(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "candidate_assignments" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_assignments (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL REFERENCES candidate_persons(id) ON DELETE CASCADE,
                    assignee TEXT NOT NULL,
                    owner_role TEXT NOT NULL DEFAULT 'operator',
                    status TEXT NOT NULL DEFAULT 'active',
                    note TEXT,
                    assignment_metadata TEXT NOT NULL DEFAULT '{}',
                    assigned_at TEXT NOT NULL,
                    released_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    if "resume_artifacts" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE resume_artifacts (
                    id TEXT PRIMARY KEY,
                    application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    source TEXT NOT NULL DEFAULT 'site',
                    artifact_type TEXT NOT NULL DEFAULT 'resume',
                    file_name TEXT,
                    file_path TEXT,
                    extracted_text TEXT,
                    contact_snapshot TEXT NOT NULL DEFAULT '{}',
                    artifact_metadata TEXT NOT NULL DEFAULT '{}',
                    captured_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    if "candidate_scorecards" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_scorecards (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL REFERENCES candidate_persons(id) ON DELETE CASCADE,
                    stage_key TEXT,
                    source TEXT NOT NULL DEFAULT 'ai',
                    rubric_version TEXT NOT NULL DEFAULT 'recruit-scorecard-v1',
                    score_total INTEGER,
                    verdict TEXT,
                    summary TEXT,
                    dimension_scores TEXT NOT NULL DEFAULT '{}',
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    scorecard_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    if "candidate_review_decisions" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_review_decisions (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL REFERENCES candidate_persons(id) ON DELETE CASCADE,
                    stage_key TEXT,
                    decision TEXT NOT NULL,
                    rationale TEXT,
                    decision_source TEXT NOT NULL DEFAULT 'manual',
                    decided_by TEXT,
                    scorecard_id TEXT REFERENCES candidate_scorecards(id) ON DELETE SET NULL,
                    review_metadata TEXT NOT NULL DEFAULT '{}',
                    decided_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    if "talent_pool_sync_records" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE talent_pool_sync_records (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL REFERENCES candidate_persons(id) ON DELETE CASCADE,
                    destination TEXT NOT NULL DEFAULT 'talent_pool',
                    status TEXT NOT NULL DEFAULT 'pending',
                    external_ref TEXT,
                    payload_snapshot TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT,
                    synced_at TEXT,
                    last_attempted_at TEXT,
                    sync_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )

    indexed_tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "candidate_assignments" in indexed_tables:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_assignments_candidate_assigned_at ON candidate_assignments (candidate_id, assigned_at)")
        )
    if "resume_artifacts" in indexed_tables:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_resume_artifacts_application_captured_at ON resume_artifacts (application_id, captured_at)")
        )
    if "candidate_scorecards" in indexed_tables:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_scorecards_candidate_created_at ON candidate_scorecards (candidate_id, created_at)")
        )
    if "candidate_review_decisions" in indexed_tables:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_review_decisions_candidate_decided_at ON candidate_review_decisions (candidate_id, decided_at)")
        )
    if "talent_pool_sync_records" in indexed_tables:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_talent_pool_sync_records_candidate_created_at ON talent_pool_sync_records (candidate_id, created_at)")
        )


def _create_agent_runtime_control_tables(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "agent_sessions" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE agent_sessions (
                    id TEXT PRIMARY KEY,
                    agent_definition_id TEXT NOT NULL REFERENCES agent_definitions(id) ON DELETE CASCADE,
                    session_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    current_lane TEXT,
                    last_active_at TEXT,
                    last_run_at TEXT,
                    runtime_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CONSTRAINT uq_agent_sessions_definition_session_key UNIQUE (agent_definition_id, session_key)
                )
                """
            )
        )
    if "agent_runs" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE agent_runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    execution_episode_id TEXT REFERENCES execution_episodes(id) ON DELETE SET NULL,
                    person_id TEXT REFERENCES candidate_persons(candidate_person_id) ON DELETE SET NULL,
                    application_id TEXT REFERENCES candidate_applications(candidate_application_id) ON DELETE SET NULL,
                    jd_id TEXT,
                    platform TEXT NOT NULL DEFAULT 'site',
                    lane TEXT NOT NULL DEFAULT 'agent',
                    run_type TEXT NOT NULL DEFAULT 'generic',
                    status TEXT NOT NULL DEFAULT 'queued',
                    priority INTEGER NOT NULL DEFAULT 100,
                    queue_task_id TEXT,
                    checkpoint_status TEXT NOT NULL DEFAULT 'none',
                    context_manifest TEXT NOT NULL DEFAULT '{}',
                    runtime_metadata TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT,
                    finished_at TEXT,
                    blocked_reason TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    if "agent_run_checkpoints" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE agent_run_checkpoints (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                    person_id TEXT REFERENCES candidate_persons(candidate_person_id) ON DELETE SET NULL,
                    application_id TEXT REFERENCES candidate_applications(candidate_application_id) ON DELETE SET NULL,
                    approval_id TEXT REFERENCES approval_items(id) ON DELETE SET NULL,
                    checkpoint_kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    title TEXT NOT NULL,
                    summary TEXT,
                    payload TEXT NOT NULL DEFAULT '{}',
                    resolved_by TEXT,
                    resolved_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    if "agent_runtime_events" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE agent_runtime_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
                    person_id TEXT REFERENCES candidate_persons(candidate_person_id) ON DELETE SET NULL,
                    application_id TEXT REFERENCES candidate_applications(candidate_application_id) ON DELETE SET NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    occurred_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )

    indexed_tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "agent_sessions" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_sessions_status ON agent_sessions (status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_sessions_last_active_at ON agent_sessions (last_active_at)"))
    if "agent_runs" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_session_status_priority ON agent_runs (session_id, status, priority)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_person_status ON agent_runs (person_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_application_status ON agent_runs (application_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_execution_episode_id ON agent_runs (execution_episode_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_queue_task_id ON agent_runs (queue_task_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_platform_status ON agent_runs (platform, status)"))
    if "agent_run_checkpoints" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_run_checkpoints_run_status ON agent_run_checkpoints (run_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_run_checkpoints_approval_id ON agent_run_checkpoints (approval_id)"))
    if "agent_runtime_events" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runtime_events_session_occurred_at ON agent_runtime_events (session_id, occurred_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runtime_events_run_occurred_at ON agent_runtime_events (run_id, occurred_at)"))


def _create_agent_runtime_tables(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "execution_traces" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE execution_traces (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
                    candidate_id TEXT REFERENCES candidate_persons(id) ON DELETE SET NULL,
                    lane TEXT NOT NULL DEFAULT 'agent',
                    trace_kind TEXT NOT NULL DEFAULT 'adaptive_run',
                    status TEXT NOT NULL DEFAULT 'captured',
                    title TEXT NOT NULL,
                    summary TEXT,
                    raw_trace TEXT NOT NULL DEFAULT '{}',
                    distilled_trace TEXT NOT NULL DEFAULT '{}',
                    outcome TEXT NOT NULL DEFAULT '{}',
                    trace_metadata TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT,
                    finished_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    if "strategy_fragments" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE strategy_fragments (
                    id TEXT PRIMARY KEY,
                    agent_definition_id TEXT NOT NULL REFERENCES agent_definitions(id) ON DELETE CASCADE,
                    run_id TEXT,
                    candidate_id TEXT REFERENCES candidate_persons(id) ON DELETE SET NULL,
                    jd_id TEXT,
                    scope TEXT NOT NULL DEFAULT 'agent',
                    fragment_kind TEXT NOT NULL DEFAULT 'strategy',
                    title TEXT NOT NULL,
                    summary TEXT,
                    content TEXT NOT NULL DEFAULT '{}',
                    evidence TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'draft',
                    adoption_count INTEGER NOT NULL DEFAULT 0,
                    last_applied_at TEXT,
                    fragment_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    if "execution_graph_projections" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE execution_graph_projections (
                    id TEXT PRIMARY KEY,
                    run_id TEXT,
                    candidate_id TEXT REFERENCES candidate_persons(id) ON DELETE SET NULL,
                    graph_kind TEXT NOT NULL DEFAULT 'execution_projection',
                    title TEXT NOT NULL,
                    summary TEXT,
                    nodes TEXT NOT NULL DEFAULT '[]',
                    edges TEXT NOT NULL DEFAULT '[]',
                    rendered_text TEXT,
                    graph_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    if "operator_interactions" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE operator_interactions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
                    checkpoint_id TEXT,
                    approval_id TEXT REFERENCES approval_items(id) ON DELETE SET NULL,
                    person_id TEXT REFERENCES candidate_persons(candidate_person_id) ON DELETE SET NULL,
                    application_id TEXT REFERENCES candidate_applications(candidate_application_id) ON DELETE SET NULL,
                    lane TEXT NOT NULL DEFAULT 'agent',
                    interaction_type TEXT NOT NULL DEFAULT 'confirm',
                    status TEXT NOT NULL DEFAULT 'pending',
                    title TEXT NOT NULL,
                    agent_prompt TEXT NOT NULL,
                    suggested_options TEXT NOT NULL DEFAULT '[]',
                    operator_response TEXT NOT NULL DEFAULT '{}',
                    effect_summary TEXT,
                    scope TEXT NOT NULL DEFAULT 'run_only',
                    interaction_metadata TEXT NOT NULL DEFAULT '{}',
                    surfaced_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )

    indexed_tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "execution_traces" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_traces_run_created_at ON execution_traces (run_id, created_at)"))
    if "strategy_fragments" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_strategy_fragments_definition_status ON strategy_fragments (agent_definition_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_strategy_fragments_kind_scope ON strategy_fragments (fragment_kind, scope)"))
    if "execution_graph_projections" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_graph_projections_run_created_at ON execution_graph_projections (run_id, created_at)"))
    if "operator_interactions" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_operator_interactions_status_surfaced_at ON operator_interactions (status, surfaced_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_operator_interactions_person_status ON operator_interactions (person_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_operator_interactions_application_status ON operator_interactions (application_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_operator_interactions_approval_status ON operator_interactions (approval_id, status)"))


def _create_mcp_registry_tables(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "mcp_servers" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE mcp_servers (
                    id TEXT PRIMARY KEY,
                    server_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    transport_kind TEXT NOT NULL DEFAULT 'unix_socket',
                    protocol TEXT NOT NULL DEFAULT 'mcp_jsonrpc',
                    endpoint TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    preset_key TEXT,
                    auth_config TEXT NOT NULL DEFAULT '{}',
                    server_metadata TEXT NOT NULL DEFAULT '{}',
                    health_status TEXT NOT NULL DEFAULT 'unknown',
                    health_error TEXT,
                    last_health_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_servers_server_key ON mcp_servers (server_key)"))
    if "mcp_tools" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE mcp_tools (
                    id TEXT PRIMARY KEY,
                    server_id TEXT NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    parameters TEXT NOT NULL DEFAULT '{}',
                    capabilities TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    risk_level TEXT NOT NULL DEFAULT 'medium',
                    remote_name TEXT,
                    tool_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_tools_server_name ON mcp_tools (server_id, name)"))
    indexed_tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "mcp_servers" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_mcp_servers_enabled ON mcp_servers (enabled)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_mcp_servers_protocol ON mcp_servers (protocol)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_mcp_servers_health_status ON mcp_servers (health_status)"))
    if "mcp_tools" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_mcp_tools_server_enabled ON mcp_tools (server_id, enabled)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_mcp_tools_risk_level ON mcp_tools (risk_level)"))


def _align_mcp_registry_schema(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "mcp_servers" not in tables:
        return

    server_columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(mcp_servers)")).fetchall()
    }
    server_statements = []
    if "capabilities" not in server_columns:
        server_statements.append("ALTER TABLE mcp_servers ADD COLUMN capabilities JSON NOT NULL DEFAULT '{}'")
    if "circuit_state" not in server_columns:
        server_statements.append("ALTER TABLE mcp_servers ADD COLUMN circuit_state TEXT NOT NULL DEFAULT 'closed'")
    if "circuit_until" not in server_columns:
        server_statements.append("ALTER TABLE mcp_servers ADD COLUMN circuit_until BIGINT")
    if "last_error" not in server_columns:
        server_statements.append("ALTER TABLE mcp_servers ADD COLUMN last_error TEXT")
    for statement in server_statements:
        connection.execute(text(statement))

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_mcp_servers_circuit_state ON mcp_servers (circuit_state)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_mcp_servers_circuit_until ON mcp_servers (circuit_until)"))


def _align_agent_runtime_control_schema(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "agent_runs" not in tables:
        return

    run_columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(agent_runs)")).fetchall()
    }
    run_statements = []
    if "run_id" not in run_columns:
        run_statements.append("ALTER TABLE agent_runs ADD COLUMN run_id TEXT")
    if "agent_kind" not in run_columns:
        run_statements.append("ALTER TABLE agent_runs ADD COLUMN agent_kind TEXT NOT NULL DEFAULT 'autonomous'")
    if "turns_count" not in run_columns:
        run_statements.append("ALTER TABLE agent_runs ADD COLUMN turns_count INTEGER NOT NULL DEFAULT 0")
    if "prompt_tokens" not in run_columns:
        run_statements.append("ALTER TABLE agent_runs ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0")
    if "completion_tokens" not in run_columns:
        run_statements.append("ALTER TABLE agent_runs ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0")
    if "cache_hit_tokens" not in run_columns:
        run_statements.append("ALTER TABLE agent_runs ADD COLUMN cache_hit_tokens INTEGER NOT NULL DEFAULT 0")
    if "escalate_reason" not in run_columns:
        run_statements.append("ALTER TABLE agent_runs ADD COLUMN escalate_reason TEXT")
    if "lock_scope" not in run_columns:
        run_statements.append("ALTER TABLE agent_runs ADD COLUMN lock_scope JSON NOT NULL DEFAULT '{}'")
    if "idempotency_key" not in run_columns:
        run_statements.append("ALTER TABLE agent_runs ADD COLUMN idempotency_key TEXT")
    if "wakeup_state" not in run_columns:
        run_statements.append("ALTER TABLE agent_runs ADD COLUMN wakeup_state JSON NOT NULL DEFAULT '{}'")
    for statement in run_statements:
        connection.execute(text(statement))

    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_run_id ON agent_runs (run_id)"))
    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_idempotency_key ON agent_runs (idempotency_key)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_agent_kind ON agent_runs (agent_kind)"))


def _align_agent_runtime_subject_columns(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "agent_runs" in tables:
        run_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_runs)")).fetchall()
        }
        run_statements = []
        if "person_id" not in run_columns:
            run_statements.append("ALTER TABLE agent_runs ADD COLUMN person_id TEXT")
        if "application_id" not in run_columns:
            run_statements.append("ALTER TABLE agent_runs ADD COLUMN application_id TEXT")
        if "jd_id" not in run_columns:
            run_statements.append("ALTER TABLE agent_runs ADD COLUMN jd_id TEXT")
        for statement in run_statements:
            connection.execute(text(statement))

        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_person_status ON agent_runs (person_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_application_status ON agent_runs (application_id, status)"))

    if "agent_run_checkpoints" in tables:
        checkpoint_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_run_checkpoints)")).fetchall()
        }
        checkpoint_statements = []
        if "person_id" not in checkpoint_columns:
            checkpoint_statements.append("ALTER TABLE agent_run_checkpoints ADD COLUMN person_id TEXT")
        if "application_id" not in checkpoint_columns:
            checkpoint_statements.append("ALTER TABLE agent_run_checkpoints ADD COLUMN application_id TEXT")
        for statement in checkpoint_statements:
            connection.execute(text(statement))

    if "agent_runtime_events" in tables:
        event_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_runtime_events)")).fetchall()
        }
        event_statements = []
        if "person_id" not in event_columns:
            event_statements.append("ALTER TABLE agent_runtime_events ADD COLUMN person_id TEXT")
        if "application_id" not in event_columns:
            event_statements.append("ALTER TABLE agent_runtime_events ADD COLUMN application_id TEXT")
        for statement in event_statements:
            connection.execute(text(statement))


def _align_skill_schema_for_runtime_learning(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "skills" not in tables:
        return

    skill_columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(skills)")).fetchall()
    }
    skill_statements = []
    if "trigger_hint" not in skill_columns:
        skill_statements.append("ALTER TABLE skills ADD COLUMN trigger_hint TEXT")
    if "body" not in skill_columns:
        skill_statements.append("ALTER TABLE skills ADD COLUMN body JSON NOT NULL DEFAULT '{}'")
    if "trial_metrics" not in skill_columns:
        skill_statements.append("ALTER TABLE skills ADD COLUMN trial_metrics JSON NOT NULL DEFAULT '{}'")
    if "requires_human_gate" not in skill_columns:
        skill_statements.append("ALTER TABLE skills ADD COLUMN requires_human_gate INTEGER NOT NULL DEFAULT 0")
    if "human_gate_policy" not in skill_columns:
        skill_statements.append("ALTER TABLE skills ADD COLUMN human_gate_policy JSON NOT NULL DEFAULT '{}'")
    for statement in skill_statements:
        connection.execute(text(statement))

    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_requires_human_gate ON skills (requires_human_gate)"))


def _align_approval_and_event_runtime_schema(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "approval_items" in tables:
        approval_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(approval_items)")).fetchall()
        }
        approval_statements = []
        if "run_pk" not in approval_columns:
            approval_statements.append("ALTER TABLE approval_items ADD COLUMN run_pk TEXT")
        if "turn_pk" not in approval_columns:
            approval_statements.append("ALTER TABLE approval_items ADD COLUMN turn_pk TEXT")
        if "conversation_pk" not in approval_columns:
            approval_statements.append("ALTER TABLE approval_items ADD COLUMN conversation_pk TEXT")
        if "source_kind" not in approval_columns:
            approval_statements.append("ALTER TABLE approval_items ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'autonomous'")
        if "tool_name" not in approval_columns:
            approval_statements.append("ALTER TABLE approval_items ADD COLUMN tool_name TEXT")
        if "args_digest" not in approval_columns:
            approval_statements.append("ALTER TABLE approval_items ADD COLUMN args_digest TEXT")
        if "expires_at" not in approval_columns:
            approval_statements.append("ALTER TABLE approval_items ADD COLUMN expires_at BIGINT")
        if "executed_at" not in approval_columns:
            approval_statements.append("ALTER TABLE approval_items ADD COLUMN executed_at BIGINT")
        if "idempotency_key" not in approval_columns:
            approval_statements.append("ALTER TABLE approval_items ADD COLUMN idempotency_key TEXT")
        for statement in approval_statements:
            connection.execute(text(statement))

        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_approval_items_run_pk ON approval_items (run_pk)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_approval_items_turn_pk ON approval_items (turn_pk)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_approval_items_conversation_pk ON approval_items (conversation_pk)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_approval_items_source_kind ON approval_items (source_kind)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_approval_items_tool_name ON approval_items (tool_name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_approval_items_args_digest ON approval_items (args_digest)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_approval_items_expires_at ON approval_items (expires_at)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_items_idempotency_key ON approval_items (idempotency_key)"))

    if "agent_runtime_events" in tables:
        event_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_runtime_events)")).fetchall()
        }
        event_statements = []
        if "turn_id" not in event_columns:
            event_statements.append("ALTER TABLE agent_runtime_events ADD COLUMN turn_id TEXT")
        if "conversation_id" not in event_columns:
            event_statements.append("ALTER TABLE agent_runtime_events ADD COLUMN conversation_id TEXT")
        if "seq" not in event_columns:
            event_statements.append("ALTER TABLE agent_runtime_events ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")
        for statement in event_statements:
            connection.execute(text(statement))

        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runtime_events_turn_id ON agent_runtime_events (turn_id)"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_agent_runtime_events_conversation_id ON agent_runtime_events (conversation_id)")
        )


def _align_memory_item_schema(connection: Connection) -> None:
    _drop_legacy_database_memory_tables(connection)


def _rename_skill_binding_to_stage(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "skills" not in tables:
        return

    columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(skills)")).fetchall()
    }
    if "bound_to_stage" not in columns:
        connection.execute(text("ALTER TABLE skills ADD COLUMN bound_to_stage TEXT"))
    if "bound_to_workflow_node" in columns:
        connection.execute(
            text(
                """
                UPDATE skills
                SET bound_to_stage = COALESCE(NULLIF(bound_to_stage, ''), bound_to_workflow_node)
                WHERE bound_to_workflow_node IS NOT NULL
                """
            )
        )
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_skills_bound_to_stage ON skills (bound_to_stage)"))


_LEGACY_STAGE_MAP = {
    "discover_candidate": "candidate_discovery",
    "initial_screening": "candidate_probe",
    "initiate_communication": "candidate_outreach",
    "request_resume": "resume_collection",
    "runtime_execution": "scale_execution",
    "archive_candidate": "candidate_archive",
}


def _map_stage_value(value: Any) -> Any:
    if isinstance(value, str):
        return _LEGACY_STAGE_MAP.get(value, value)
    return value


def _rewrite_runtime_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [_rewrite_runtime_payload(item) for item in value]
    if not isinstance(value, dict):
        return _map_stage_value(value)

    rewritten: dict[str, Any] = {}
    for key, item in value.items():
        if key == "workflow_id":
            continue
        if key == "workflow_node_id":
            if "adaptive_stage" not in value:
                rewritten["adaptive_stage"] = _map_stage_value(item)
            continue
        if key == "bound_to_workflow_node":
            rewritten["bound_to_stage"] = _map_stage_value(item)
            continue
        if key == "current_workflow_node":
            rewritten["current_stage_key"] = _map_stage_value(item)
            continue
        rewritten[key] = _rewrite_runtime_payload(item)

    for field in (
        "task_type",
        "adaptive_stage",
        "run_type",
        "item_type",
        "decision_type",
        "current_stage_key",
        "bound_to_stage",
    ):
        if field in rewritten:
            rewritten[field] = _map_stage_value(rewritten[field])

    metadata = rewritten.get("metadata")
    if isinstance(metadata, dict) and "adaptive_stage" not in metadata:
        stage = rewritten.get("adaptive_stage")
        if isinstance(stage, str) and stage.strip():
            rewritten["metadata"] = {**metadata, "adaptive_stage": stage}
    return rewritten


def _rewrite_json_column(
    connection: Connection,
    *,
    table: str,
    id_column: str,
    json_column: str,
) -> None:
    rows = connection.execute(text(f"SELECT {id_column}, {json_column} FROM {table}")).fetchall()
    for row_id, payload in rows:
        if payload in (None, ""):
            continue
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
        else:
            data = payload
        rewritten = _rewrite_runtime_payload(data)
        if rewritten == data:
            continue
        connection.execute(
            text(f"UPDATE {table} SET {json_column} = :payload WHERE {id_column} = :row_id"),
            {"payload": json.dumps(rewritten, ensure_ascii=False), "row_id": row_id},
        )


def _rewrite_runtime_records_to_adaptive_format(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "candidates" in tables:
        candidate_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(candidates)")).fetchall()
        }
        stage_column = "current_stage_key" if "current_stage_key" in candidate_columns else "current_workflow_node"
        for legacy, adaptive in _LEGACY_STAGE_MAP.items():
            connection.execute(
                text(
                    """
                    UPDATE candidates
                    SET {stage_column} = :adaptive
                    WHERE {stage_column} = :legacy
                    """
                    .replace("{stage_column}", stage_column)
                ),
                {"legacy": legacy, "adaptive": adaptive},
            )

    if "task_queue" in tables:
        for legacy, adaptive in _LEGACY_STAGE_MAP.items():
            connection.execute(
                text("UPDATE task_queue SET task_type = :adaptive WHERE task_type = :legacy"),
                {"legacy": legacy, "adaptive": adaptive},
            )
        _rewrite_json_column(connection, table="task_queue", id_column="id", json_column="payload")

    if "agent_runs" in tables:
        for legacy, adaptive in _LEGACY_STAGE_MAP.items():
            connection.execute(
                text("UPDATE agent_runs SET run_type = :adaptive WHERE run_type = :legacy"),
                {"legacy": legacy, "adaptive": adaptive},
            )
        _rewrite_json_column(connection, table="agent_runs", id_column="id", json_column="runtime_metadata")
        _rewrite_json_column(connection, table="agent_runs", id_column="id", json_column="context_manifest")

    if "approval_items" in tables:
        _rewrite_json_column(connection, table="approval_items", id_column="id", json_column="payload")

    if "execution_traces" in tables:
        _rewrite_json_column(connection, table="execution_traces", id_column="id", json_column="raw_trace")
        _rewrite_json_column(connection, table="execution_traces", id_column="id", json_column="distilled_trace")
        _rewrite_json_column(connection, table="execution_traces", id_column="id", json_column="outcome")
        _rewrite_json_column(connection, table="execution_traces", id_column="id", json_column="trace_metadata")

    if "decision_logs" in tables:
        for legacy, adaptive in _LEGACY_STAGE_MAP.items():
            connection.execute(
                text("UPDATE decision_logs SET decision_type = :adaptive WHERE decision_type = :legacy"),
                {"legacy": legacy, "adaptive": adaptive},
            )
        _rewrite_json_column(connection, table="decision_logs", id_column="id", json_column="input_context_snapshot")

    if "skills" in tables:
        for legacy, adaptive in _LEGACY_STAGE_MAP.items():
            connection.execute(
                text("UPDATE skills SET bound_to_stage = :adaptive WHERE bound_to_stage = :legacy"),
                {"legacy": legacy, "adaptive": adaptive},
            )
        _rewrite_json_column(connection, table="skills", id_column="id", json_column="strategy")
        _rewrite_json_column(connection, table="skills", id_column="id", json_column="execution_hints")
        _rewrite_json_column(connection, table="skills", id_column="id", json_column="health_check_config")
        _rewrite_json_column(connection, table="skills", id_column="id", json_column="skill_metadata")


def _rename_candidate_stage_column(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "candidates" not in tables:
        return

    columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(candidates)")).fetchall()
    }
    if "current_stage_key" in columns:
        return
    if "current_workflow_node" in columns:
        connection.execute(text("ALTER TABLE candidates RENAME COLUMN current_workflow_node TO current_stage_key"))


def _cut_over_playbook_storage(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "agent_definitions" in tables:
        columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_definitions)")).fetchall()
        }
        if "playbook_blueprint" not in columns and "workflow_definition" in columns:
            connection.execute(
                text("ALTER TABLE agent_definitions RENAME COLUMN workflow_definition TO playbook_blueprint")
            )

    if "workflow_runs" in tables:
        connection.execute(text("DROP TABLE workflow_runs"))

    if "workflows" not in tables:
        return

    if "playbooks" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE playbooks (
                    id TEXT PRIMARY KEY NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    scope_kind TEXT NOT NULL DEFAULT 'global',
                    scope_ref TEXT,
                    blueprint TEXT NOT NULL DEFAULT '{}',
                    strategy_defaults TEXT NOT NULL DEFAULT '{}',
                    context_overrides TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'draft',
                    version INTEGER NOT NULL DEFAULT 1,
                    playbook_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbooks_name ON playbooks (name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbooks_scope_kind ON playbooks (scope_kind)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbooks_scope_ref ON playbooks (scope_ref)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbooks_status ON playbooks (status)"))

    playbook_count = connection.execute(text("SELECT COUNT(*) FROM playbooks")).scalar_one()
    if int(playbook_count or 0) == 0:
        rows = connection.execute(
            text(
                """
                SELECT id, name, jd_id, config, status, version, created_at, updated_at
                FROM workflows
                """
            )
        ).fetchall()
        for row in rows:
            config_payload = row[3]
            if isinstance(config_payload, str):
                try:
                    config = json.loads(config_payload)
                except json.JSONDecodeError:
                    config = {}
            elif isinstance(config_payload, dict):
                config = dict(config_payload)
            else:
                config = {}
            description = config.get("description")
            strategy_defaults = config.get("strategy_defaults") if isinstance(config.get("strategy_defaults"), dict) else {}
            context_overrides = config.get("context_overrides") if isinstance(config.get("context_overrides"), dict) else {}
            playbook_metadata = config.get("metadata") if isinstance(config.get("metadata"), dict) else {}
            scope_ref = row[2]
            scope_kind = "jd" if scope_ref else "global"
            connection.execute(
                text(
                    """
                    INSERT INTO playbooks (
                        id,
                        name,
                        description,
                        scope_kind,
                        scope_ref,
                        blueprint,
                        strategy_defaults,
                        context_overrides,
                        status,
                        version,
                        playbook_metadata,
                        created_at,
                        updated_at
                    ) VALUES (
                        :id,
                        :name,
                        :description,
                        :scope_kind,
                        :scope_ref,
                        :blueprint,
                        :strategy_defaults,
                        :context_overrides,
                        :status,
                        :version,
                        :playbook_metadata,
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "id": row[0],
                    "name": row[1],
                    "description": description,
                    "scope_kind": scope_kind,
                    "scope_ref": scope_ref,
                    "blueprint": json.dumps(config, ensure_ascii=False),
                    "strategy_defaults": json.dumps(strategy_defaults, ensure_ascii=False),
                    "context_overrides": json.dumps(context_overrides, ensure_ascii=False),
                    "status": row[4],
                    "version": row[5],
                    "playbook_metadata": json.dumps(playbook_metadata, ensure_ascii=False),
                    "created_at": row[6],
                    "updated_at": row[7],
                },
            )

    connection.execute(text("DROP TABLE workflows"))


def _cut_over_playbook_version_storage(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "workflow_templates" in tables:
        if "playbook_versions" not in tables:
            connection.execute(
                text(
                    """
                    CREATE TABLE playbook_versions (
                        id TEXT PRIMARY KEY NOT NULL,
                        template_key TEXT NOT NULL,
                        name TEXT NOT NULL,
                        domain TEXT NOT NULL DEFAULT 'general',
                        status TEXT NOT NULL DEFAULT 'draft',
                        version INTEGER NOT NULL DEFAULT 1,
                        source_task_spec_id TEXT,
                        template_body TEXT NOT NULL DEFAULT '{}',
                        activation_strategy TEXT NOT NULL DEFAULT '{}',
                        validation_summary TEXT,
                        last_validated_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_playbook_versions_template_key ON playbook_versions (template_key)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbook_versions_name ON playbook_versions (name)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbook_versions_domain ON playbook_versions (domain)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbook_versions_status ON playbook_versions (status)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbook_versions_source_task_spec_id ON playbook_versions (source_task_spec_id)"))

        version_count = int(connection.execute(text("SELECT COUNT(*) FROM playbook_versions")).scalar_one() or 0)
        if version_count == 0:
            rows = connection.execute(
                text(
                    """
                    SELECT id, template_key, name, domain, status, version, source_task_spec_id,
                           template_body, activation_strategy, validation_summary, last_validated_at,
                           created_at, updated_at
                    FROM workflow_templates
                    """
                )
            ).fetchall()
            for row in rows:
                connection.execute(
                    text(
                        """
                        INSERT INTO playbook_versions (
                            id, template_key, name, domain, status, version, source_task_spec_id,
                            template_body, activation_strategy, validation_summary, last_validated_at,
                            created_at, updated_at
                        ) VALUES (
                            :id, :template_key, :name, :domain, :status, :version, :source_task_spec_id,
                            :template_body, :activation_strategy, :validation_summary, :last_validated_at,
                            :created_at, :updated_at
                        )
                        """
                    ),
                    dict(row._mapping),
                )
        connection.execute(text("DROP TABLE workflow_templates"))

    if "workflow_patches" in tables:
        if "playbook_patches" not in tables:
            connection.execute(
                text(
                    """
                    CREATE TABLE playbook_patches (
                        id TEXT PRIMARY KEY NOT NULL,
                        title TEXT NOT NULL,
                        patch_kind TEXT NOT NULL DEFAULT 'execution_divergence',
                        status TEXT NOT NULL DEFAULT 'pending_review',
                        template_id TEXT,
                        task_spec_id TEXT,
                        execution_plan_id TEXT,
                        execution_episode_id TEXT,
                        proposed_by TEXT,
                        reviewed_by TEXT,
                        reviewed_at TEXT,
                        applied_at TEXT,
                        divergence_summary TEXT,
                        rationale TEXT,
                        patch_body TEXT NOT NULL DEFAULT '{}',
                        runtime_metadata TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            )
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbook_patches_status ON playbook_patches (status)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbook_patches_patch_kind ON playbook_patches (patch_kind)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbook_patches_template_id ON playbook_patches (template_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbook_patches_task_spec_id ON playbook_patches (task_spec_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbook_patches_execution_plan_id ON playbook_patches (execution_plan_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_playbook_patches_execution_episode_id ON playbook_patches (execution_episode_id)"))

        patch_count = int(connection.execute(text("SELECT COUNT(*) FROM playbook_patches")).scalar_one() or 0)
        if patch_count == 0:
            rows = connection.execute(
                text(
                    """
                    SELECT id, title, patch_kind, status, template_id, task_spec_id, execution_plan_id,
                           execution_episode_id, proposed_by, reviewed_by, reviewed_at, applied_at,
                           divergence_summary, rationale, patch_body, runtime_metadata, created_at, updated_at
                    FROM workflow_patches
                    """
                )
            ).fetchall()
            for row in rows:
                connection.execute(
                    text(
                        """
                        INSERT INTO playbook_patches (
                            id, title, patch_kind, status, template_id, task_spec_id, execution_plan_id,
                            execution_episode_id, proposed_by, reviewed_by, reviewed_at, applied_at,
                            divergence_summary, rationale, patch_body, runtime_metadata, created_at, updated_at
                        ) VALUES (
                            :id, :title, :patch_kind, :status, :template_id, :task_spec_id, :execution_plan_id,
                            :execution_episode_id, :proposed_by, :reviewed_by, :reviewed_at, :applied_at,
                            :divergence_summary, :rationale, :patch_body, :runtime_metadata, :created_at, :updated_at
                        )
                        """
                    ),
                    dict(row._mapping),
                )
        connection.execute(text("DROP TABLE workflow_patches"))


def _create_state_machine_tables(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "candidates" in tables:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(candidates)")).fetchall()}
        if "current_status" not in columns:
            connection.execute(text("ALTER TABLE candidates ADD COLUMN current_status TEXT NOT NULL DEFAULT 'discovered'"))
        if "deepest_milestone" not in columns:
            connection.execute(text("ALTER TABLE candidates ADD COLUMN deepest_milestone TEXT"))
        if "status" in columns:
            connection.execute(text("DROP INDEX IF EXISTS ix_candidates_status"))
            connection.execute(text("ALTER TABLE candidates DROP COLUMN status"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_candidates_current_status ON candidates (current_status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_candidates_deepest_milestone ON candidates (deepest_milestone)"))

    if "recruitment_state_machine_versions" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE recruitment_state_machine_versions (
                    version INTEGER PRIMARY KEY NOT NULL,
                    updated_by TEXT NOT NULL,
                    change_summary TEXT,
                    nodes_json TEXT NOT NULL DEFAULT '[]',
                    transitions_json TEXT NOT NULL DEFAULT '[]',
                    global_transitions_json TEXT NOT NULL DEFAULT '[]',
                    published_at TEXT NOT NULL,
                    version_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_recruitment_state_machine_versions_published_at ON recruitment_state_machine_versions (published_at)")
        )

    if "candidate_status_transitions" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_status_transitions (
                    id TEXT PRIMARY KEY NOT NULL,
                    candidate_id TEXT NOT NULL REFERENCES candidate_persons(id) ON DELETE CASCADE,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    from_status_label TEXT NOT NULL,
                    to_status_label TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    actor_id TEXT,
                    trigger TEXT NOT NULL,
                    note TEXT,
                    override_reason TEXT,
                    is_override INTEGER NOT NULL DEFAULT 0,
                    milestone_updated TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_status_transitions_candidate_id ON candidate_status_transitions (candidate_id)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_status_transitions_actor ON candidate_status_transitions (actor)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_status_transitions_trigger ON candidate_status_transitions (trigger)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_status_transitions_is_override ON candidate_status_transitions (is_override)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_status_transitions_candidate_created_at ON candidate_status_transitions (candidate_id, created_at)")
        )

    if "candidate_stage_events" in tables:
        connection.execute(text("DROP TABLE candidate_stage_events"))


def _create_candidate_subject_tables(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "candidate_persons" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_persons (
                    id TEXT PRIMARY KEY NOT NULL,
                    name TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT 'site',
                    platform_candidate_id TEXT,
                    contact_info TEXT NOT NULL DEFAULT '{}',
                    resume_path TEXT,
                    online_resume_text TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_candidate_persons_name ON candidate_persons (name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_candidate_persons_platform ON candidate_persons (platform)"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_persons_platform_candidate_id ON candidate_persons (platform_candidate_id)")
        )
    else:
        person_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(candidate_persons)")).fetchall()}
        for column_name in (
            "current_status",
            "current_stage_key",
            "deepest_milestone",
            "job_description_id",
            "state_snapshot",
            "ai_scores",
            "ai_reasoning",
            "cooldown_until",
            "last_contacted_at",
        ):
            if column_name in person_columns:
                connection.execute(text(f"ALTER TABLE candidate_persons DROP COLUMN {column_name}"))

    if "candidates_platform_idx" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidates_platform_idx (
                    id TEXT PRIMARY KEY NOT NULL,
                    candidate_id TEXT NOT NULL REFERENCES candidate_persons(id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    platform_candidate_id TEXT NOT NULL,
                    profile_url TEXT,
                    raw_profile TEXT NOT NULL DEFAULT '{}',
                    first_seen_at TEXT,
                    last_seen_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CONSTRAINT uq_candidate_platform_identity UNIQUE (platform, platform_candidate_id)
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_candidates_platform_idx_candidate_id ON candidates_platform_idx (candidate_id)"))

    if "job_descriptions" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE job_descriptions (
                    id TEXT PRIMARY KEY NOT NULL,
                    title TEXT NOT NULL,
                    department TEXT,
                    location TEXT,
                    headcount INTEGER,
                    salary_min INTEGER,
                    salary_max INTEGER,
                    description TEXT,
                    requirements TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_job_descriptions_title ON job_descriptions (title)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_job_descriptions_department ON job_descriptions (department)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_job_descriptions_status ON job_descriptions (status)"))

    if "job_descriptions_platform_idx" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE job_descriptions_platform_idx (
                    id TEXT PRIMARY KEY NOT NULL,
                    job_description_id TEXT NOT NULL REFERENCES job_descriptions(id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    external_url TEXT,
                    sync_status TEXT NOT NULL DEFAULT 'pending',
                    sync_metadata TEXT NOT NULL DEFAULT '{}',
                    last_synced_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CONSTRAINT uq_job_description_platform_identity UNIQUE (platform, external_id)
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_job_descriptions_platform_idx_job_description_id ON job_descriptions_platform_idx (job_description_id)")
        )

    if "candidate_applications" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_applications (
                    id TEXT PRIMARY KEY NOT NULL,
                    person_id TEXT NOT NULL REFERENCES candidate_persons(id) ON DELETE CASCADE,
                    job_description_id TEXT REFERENCES job_descriptions(id) ON DELETE SET NULL,
                    platform TEXT NOT NULL DEFAULT 'site',
                    platform_application_id TEXT,
                    current_status TEXT NOT NULL DEFAULT 'discovered',
                    current_stage_key TEXT,
                    deepest_milestone TEXT,
                    state_snapshot TEXT NOT NULL DEFAULT '{}',
                    ai_scores TEXT NOT NULL DEFAULT '{}',
                    ai_reasoning TEXT,
                    cooldown_until TEXT,
                    last_contacted_at TEXT,
                    application_metadata TEXT NOT NULL DEFAULT '{}',
                    application_window TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CONSTRAINT uq_candidate_application_window UNIQUE (application_window)
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_candidate_applications_person_id ON candidate_applications (person_id)"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_applications_job_description_id ON candidate_applications (job_description_id)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_candidate_applications_current_status ON candidate_applications (current_status)")
        )

    if "application_sessions" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE application_sessions (
                    id TEXT PRIMARY KEY NOT NULL,
                    application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'active',
                    context_summary TEXT,
                    recent_messages TEXT NOT NULL DEFAULT '[]',
                    facts TEXT NOT NULL DEFAULT '{}',
                    suspend_reason TEXT,
                    last_active_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CONSTRAINT uq_application_sessions_application_id UNIQUE (application_id)
                )
                """
            )
        )

    if "application_communication_logs" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE application_communication_logs (
                    id TEXT PRIMARY KEY NOT NULL,
                    application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    direction TEXT NOT NULL,
                    content TEXT NOT NULL,
                    message_type TEXT NOT NULL DEFAULT 'text',
                    platform TEXT NOT NULL DEFAULT 'site',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    timestamp TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_application_communication_logs_application_id ON application_communication_logs (application_id)")
        )

    if "application_status_transitions" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE application_status_transitions (
                    id TEXT PRIMARY KEY NOT NULL,
                    application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    from_status_label TEXT NOT NULL,
                    to_status_label TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    actor_id TEXT,
                    trigger TEXT NOT NULL,
                    note TEXT,
                    override_reason TEXT,
                    is_override INTEGER NOT NULL DEFAULT 0,
                    milestone_updated TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_application_status_transitions_application_created_at ON application_status_transitions (application_id, created_at)")
        )

    if "application_assessments" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE application_assessments (
                    id TEXT PRIMARY KEY NOT NULL,
                    application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    assessment_type TEXT NOT NULL DEFAULT 'ai',
                    stage_key TEXT,
                    status TEXT NOT NULL DEFAULT 'completed',
                    decision TEXT,
                    score INTEGER,
                    summary TEXT,
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_by TEXT,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_application_assessments_application_created_at ON application_assessments (application_id, created_at)")
        )

    if "application_assignments" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE application_assignments (
                    id TEXT PRIMARY KEY NOT NULL,
                    application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    assignee TEXT NOT NULL,
                    owner_role TEXT NOT NULL DEFAULT 'operator',
                    status TEXT NOT NULL DEFAULT 'active',
                    note TEXT,
                    assignment_metadata TEXT NOT NULL DEFAULT '{}',
                    assigned_at TEXT NOT NULL,
                    released_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_application_assignments_application_assigned_at ON application_assignments (application_id, assigned_at)")
        )

    if "person_resume_artifacts" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE person_resume_artifacts (
                    id TEXT PRIMARY KEY NOT NULL,
                    person_id TEXT NOT NULL REFERENCES candidate_persons(id) ON DELETE CASCADE,
                    source TEXT NOT NULL DEFAULT 'site',
                    artifact_type TEXT NOT NULL DEFAULT 'resume',
                    file_name TEXT,
                    file_path TEXT,
                    extracted_text TEXT,
                    contact_snapshot TEXT NOT NULL DEFAULT '{}',
                    artifact_metadata TEXT NOT NULL DEFAULT '{}',
                    captured_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_person_resume_artifacts_person_captured_at ON person_resume_artifacts (person_id, captured_at)")
        )

    if "application_scorecards" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE application_scorecards (
                    id TEXT PRIMARY KEY NOT NULL,
                    application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    stage_key TEXT,
                    source TEXT NOT NULL DEFAULT 'ai',
                    rubric_version TEXT NOT NULL DEFAULT 'recruit-scorecard-v1',
                    score_total INTEGER,
                    verdict TEXT,
                    summary TEXT,
                    dimension_scores TEXT NOT NULL DEFAULT '{}',
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    scorecard_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_application_scorecards_application_created_at ON application_scorecards (application_id, created_at)")
        )

    if "application_review_decisions" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE application_review_decisions (
                    id TEXT PRIMARY KEY NOT NULL,
                    application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    stage_key TEXT,
                    decision TEXT NOT NULL,
                    rationale TEXT,
                    decision_source TEXT NOT NULL DEFAULT 'manual',
                    decided_by TEXT,
                    scorecard_id TEXT REFERENCES application_scorecards(id) ON DELETE SET NULL,
                    review_metadata TEXT NOT NULL DEFAULT '{}',
                    decided_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_application_review_decisions_application_decided_at ON application_review_decisions (application_id, decided_at)")
        )

    if "application_sync_records" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE application_sync_records (
                    id TEXT PRIMARY KEY NOT NULL,
                    application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    destination TEXT NOT NULL DEFAULT 'talent_pool',
                    status TEXT NOT NULL DEFAULT 'pending',
                    external_ref TEXT,
                    payload_snapshot TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT,
                    synced_at TEXT,
                    last_attempted_at TEXT,
                    sync_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_application_sync_records_application_created_at ON application_sync_records (application_id, created_at)")
        )


def _canonicalize_core_entity_schema(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "candidate_persons" in tables:
        person_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(candidate_persons)")).fetchall()
        }
        if "candidate_person_id" not in person_columns:
            connection.execute(
                text("ALTER TABLE candidate_persons ADD COLUMN candidate_person_id TEXT")
            )

    if "candidate_applications" in tables:
        application_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(candidate_applications)")).fetchall()
        }
        if "candidate_application_id" not in application_columns:
            connection.execute(
                text("ALTER TABLE candidate_applications ADD COLUMN candidate_application_id TEXT")
            )
        if "source_platform_candidate_person_id" not in application_columns:
            connection.execute(
                text("ALTER TABLE candidate_applications ADD COLUMN source_platform_candidate_person_id TEXT")
            )

    if "candidate_person_platform_idx" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_person_platform_idx (
                    id TEXT PRIMARY KEY NOT NULL,
                    candidate_person_platform_idx_id TEXT,
                    candidate_person_id TEXT NOT NULL REFERENCES candidate_persons(id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    platform_candidate_person_id TEXT NOT NULL,
                    profile_url TEXT,
                    raw_profile TEXT NOT NULL DEFAULT '{}',
                    first_seen_at BIGINT,
                    last_seen_at BIGINT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL,
                    CONSTRAINT uq_candidate_person_platform_identity UNIQUE (platform, platform_candidate_person_id)
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_candidate_person_platform_idx_candidate_person_id ON candidate_person_platform_idx (candidate_person_id)"
            )
        )

    if "job_description_platform_idx" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE job_description_platform_idx (
                    id TEXT PRIMARY KEY NOT NULL,
                    job_description_platform_idx_id TEXT,
                    job_description_id TEXT NOT NULL REFERENCES job_descriptions(id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    external_url TEXT,
                    sync_status TEXT NOT NULL DEFAULT 'pending',
                    sync_metadata TEXT NOT NULL DEFAULT '{}',
                    last_synced_at BIGINT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL,
                    CONSTRAINT uq_job_description_platform_identity UNIQUE (platform, external_id)
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_job_description_platform_idx_job_description_id ON job_description_platform_idx (job_description_id)"
            )
        )

    if "candidate_application_messages" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_application_messages (
                    id TEXT PRIMARY KEY NOT NULL,
                    candidate_application_message_id TEXT,
                    candidate_application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    direction TEXT NOT NULL,
                    content TEXT NOT NULL,
                    message_type TEXT NOT NULL DEFAULT 'text',
                    signal_snapshot TEXT NOT NULL DEFAULT '{}',
                    message_metadata TEXT NOT NULL DEFAULT '{}',
                    occurred_at BIGINT NOT NULL,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )

    if "candidate_application_transitions" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_application_transitions (
                    id TEXT PRIMARY KEY NOT NULL,
                    candidate_application_transition_id TEXT,
                    candidate_application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    from_status_label TEXT NOT NULL,
                    to_status_label TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    actor_id TEXT,
                    trigger TEXT NOT NULL,
                    note TEXT,
                    override_reason TEXT,
                    is_override INTEGER NOT NULL DEFAULT 0,
                    milestone_updated TEXT,
                    transition_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_candidate_application_transitions_application_created_at ON candidate_application_transitions (candidate_application_id, created_at)"
            )
        )

    if "candidate_application_assessments" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_application_assessments (
                    id TEXT PRIMARY KEY NOT NULL,
                    candidate_application_assessment_id TEXT,
                    candidate_application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    assessment_actor_type TEXT NOT NULL DEFAULT 'ai',
                    assessment_stage_key TEXT,
                    assessment_stage_label TEXT,
                    assessment_round INTEGER NOT NULL DEFAULT 1,
                    decision TEXT,
                    score INTEGER,
                    summary TEXT,
                    criteria_snapshot TEXT NOT NULL DEFAULT '{}',
                    evidence_snapshot TEXT NOT NULL DEFAULT '{}',
                    result_payload TEXT NOT NULL DEFAULT '{}',
                    assessment_metadata TEXT NOT NULL DEFAULT '{}',
                    assessed_at BIGINT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_candidate_application_assessments_application_created_at ON candidate_application_assessments (candidate_application_id, created_at)"
            )
        )

    if "candidate_application_scorecards" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE candidate_application_scorecards (
                    id TEXT PRIMARY KEY NOT NULL,
                    candidate_application_scorecard_id TEXT,
                    candidate_application_id TEXT NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
                    assessment_stage_key TEXT,
                    scorecard_source TEXT NOT NULL DEFAULT 'ai',
                    rubric_version TEXT NOT NULL DEFAULT 'recruit-scorecard-v1',
                    score_total INTEGER,
                    verdict TEXT,
                    summary TEXT,
                    dimension_scores TEXT NOT NULL DEFAULT '{}',
                    evidence_snapshot TEXT NOT NULL DEFAULT '{}',
                    scorecard_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_candidate_application_scorecards_application_created_at ON candidate_application_scorecards (candidate_application_id, created_at)"
            )
        )


def _extend_job_description_detail_schema(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "job_descriptions" not in tables:
        return

    columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(job_descriptions)")).fetchall()
    }
    statements = []
    if "company_name" not in columns:
        statements.append("ALTER TABLE job_descriptions ADD COLUMN company_name TEXT")
    if "employment_type" not in columns:
        statements.append("ALTER TABLE job_descriptions ADD COLUMN employment_type TEXT")
    if "compensation_text" not in columns:
        statements.append("ALTER TABLE job_descriptions ADD COLUMN compensation_text TEXT")
    if "experience_requirement" not in columns:
        statements.append("ALTER TABLE job_descriptions ADD COLUMN experience_requirement TEXT")
    if "education_requirement" not in columns:
        statements.append("ALTER TABLE job_descriptions ADD COLUMN education_requirement TEXT")
    if "summary" not in columns:
        statements.append("ALTER TABLE job_descriptions ADD COLUMN summary TEXT")
    if "benefit_tags" not in columns:
        statements.append("ALTER TABLE job_descriptions ADD COLUMN benefit_tags JSON NOT NULL DEFAULT '[]'")
    if "detail_metadata" not in columns:
        statements.append("ALTER TABLE job_descriptions ADD COLUMN detail_metadata JSON NOT NULL DEFAULT '{}'")

    for statement in statements:
        connection.execute(text(statement))


def _align_environment_snapshot_schema(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "environment_snapshots" not in tables:
        return

    columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(environment_snapshots)")).fetchall()
    }
    statements = []
    if "resource_locator" not in columns:
        statements.append("ALTER TABLE environment_snapshots ADD COLUMN resource_locator TEXT")
    if "display_label" not in columns:
        statements.append("ALTER TABLE environment_snapshots ADD COLUMN display_label TEXT")
    if "environment_kind" not in columns:
        statements.append("ALTER TABLE environment_snapshots ADD COLUMN environment_kind TEXT")
    if "action_hints" not in columns:
        statements.append("ALTER TABLE environment_snapshots ADD COLUMN action_hints TEXT NOT NULL DEFAULT '[]'")
    for statement in statements:
        connection.execute(text(statement))

    connection.execute(text("DROP INDEX IF EXISTS ix_environment_snapshots_episode_page_type"))
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_environment_snapshots_episode_environment_kind ON environment_snapshots (execution_episode_id, environment_kind)"
        )
    )


def _align_candidate_application_lock_scope(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "candidate_autonomous_locks" not in tables:
        return

    columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(candidate_autonomous_locks)")).fetchall()
    }
    if "application_id" not in columns:
        connection.execute(text("ALTER TABLE candidate_autonomous_locks ADD COLUMN application_id TEXT"))
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_candidate_autonomous_locks_application_id ON candidate_autonomous_locks (application_id)")
    )

    if "candidate_person_id" not in columns:
        return

    connection.execute(
        text(
            """
            UPDATE candidate_autonomous_locks
            SET application_id = (
                SELECT ca.candidate_application_id
                FROM candidate_applications AS ca
                JOIN candidate_persons AS cp ON cp.id = ca.person_id
                WHERE cp.candidate_person_id = candidate_autonomous_locks.candidate_person_id
                  AND (
                    SELECT COUNT(*)
                    FROM candidate_applications AS scoped_ca
                    JOIN candidate_persons AS scoped_cp ON scoped_cp.id = scoped_ca.person_id
                    WHERE scoped_cp.candidate_person_id = candidate_autonomous_locks.candidate_person_id
                  ) = 1
                LIMIT 1
            )
            WHERE application_id IS NULL
            """
        )
    )


MIGRATIONS: tuple[SchemaMigration, ...] = (
    SchemaMigration(
        version=1,
        name="baseline_sqlalchemy_schema",
        apply=_noop,
    ),
    SchemaMigration(
        version=2,
        name="supporting_runtime_indexes",
        apply=_create_supporting_indexes,
    ),
    SchemaMigration(
        version=3,
        name="sync_backlog_protocol_columns",
        apply=_sync_backlog_protocol_columns,
    ),
    SchemaMigration(
        version=4,
        name="general_runtime_indexes",
        apply=_create_general_runtime_indexes,
    ),
    SchemaMigration(
        version=5,
        name="extend_skill_schema",
        apply=_extend_skill_schema,
    ),
    SchemaMigration(
        version=6,
        name="extend_recruit_agent_state_schema",
        apply=_extend_recruit_agent_state_schema,
    ),
    SchemaMigration(
        version=7,
        name="extend_candidate_fact_tables",
        apply=_extend_candidate_fact_tables,
    ),
    SchemaMigration(
        version=8,
        name="create_agent_runtime_control_tables",
        apply=_create_agent_runtime_control_tables,
    ),
    SchemaMigration(
        version=9,
        name="create_agent_runtime_tables",
        apply=_create_agent_runtime_tables,
    ),
    SchemaMigration(
        version=10,
        name="create_mcp_registry_tables",
        apply=_create_mcp_registry_tables,
    ),
    SchemaMigration(
        version=11,
        name="rename_skill_binding_to_stage",
        apply=_rename_skill_binding_to_stage,
    ),
    SchemaMigration(
        version=12,
        name="rewrite_runtime_records_to_adaptive_format",
        apply=_rewrite_runtime_records_to_adaptive_format,
    ),
    SchemaMigration(
        version=13,
        name="rename_candidate_stage_column",
        apply=_rename_candidate_stage_column,
    ),
    SchemaMigration(
        version=14,
        name="cut_over_playbook_storage",
        apply=_cut_over_playbook_storage,
    ),
    SchemaMigration(
        version=15,
        name="cut_over_playbook_version_storage",
        apply=_cut_over_playbook_version_storage,
    ),
    SchemaMigration(
        version=16,
        name="create_state_machine_tables",
        apply=_create_state_machine_tables,
    ),
    SchemaMigration(
        version=17,
        name="create_candidate_subject_tables",
        apply=_create_candidate_subject_tables,
    ),
    SchemaMigration(
        version=18,
        name="canonicalize_core_entity_schema",
        apply=_canonicalize_core_entity_schema,
    ),
    SchemaMigration(
        version=19,
        name="extend_job_description_detail_schema",
        apply=_extend_job_description_detail_schema,
    ),
    SchemaMigration(
        version=20,
        name="align_mcp_registry_schema",
        apply=_align_mcp_registry_schema,
    ),
    SchemaMigration(
        version=21,
        name="align_agent_runtime_control_schema",
        apply=_align_agent_runtime_control_schema,
    ),
    SchemaMigration(
        version=22,
        name="align_skill_schema_for_runtime_learning",
        apply=_align_skill_schema_for_runtime_learning,
    ),
    SchemaMigration(
        version=23,
        name="align_approval_and_event_runtime_schema",
        apply=_align_approval_and_event_runtime_schema,
    ),
    SchemaMigration(
        version=24,
        name="align_memory_item_schema",
        apply=_align_memory_item_schema,
    ),
    SchemaMigration(
        version=25,
        name="align_environment_snapshot_schema",
        apply=_align_environment_snapshot_schema,
    ),
    SchemaMigration(
        version=26,
        name="align_candidate_application_lock_scope",
        apply=_align_candidate_application_lock_scope,
    ),
    SchemaMigration(
        version=27,
        name="drop_legacy_database_memory_tables",
        apply=_drop_legacy_database_memory_tables,
    ),
    SchemaMigration(
        version=28,
        name="align_agent_runtime_subject_columns",
        apply=_align_agent_runtime_subject_columns,
    ),
)

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version if MIGRATIONS else 0


def ensure_schema_migrations_table(connection: Connection) -> None:
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA_MIGRATIONS_TABLE} (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
    )


def list_applied_versions(connection: Connection) -> list[int]:
    ensure_schema_migrations_table(connection)
    rows = connection.execute(
        text(f"SELECT version FROM {SCHEMA_MIGRATIONS_TABLE} ORDER BY version ASC")
    ).fetchall()
    return [int(row[0]) for row in rows]


def current_schema_version(connection: Connection) -> int:
    versions = list_applied_versions(connection)
    return versions[-1] if versions else 0


def run_migrations(engine: Engine) -> int:
    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)
        applied_versions = set(list_applied_versions(connection))
        for migration in MIGRATIONS:
            if migration.version in applied_versions:
                continue
            migration.apply(connection)
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, name, applied_at)
                    VALUES (:version, :name, :applied_at)
                    """
                ),
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": _utcnow_iso(),
                },
            )
            applied_versions.add(migration.version)
    return CURRENT_SCHEMA_VERSION


def describe_migrations() -> list[dict[str, object]]:
    return [{"version": migration.version, "name": migration.name} for migration in MIGRATIONS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or apply General Automation Runtime schema migrations")
    parser.add_argument("command", choices=("current", "history", "upgrade"), nargs="?", default="upgrade")
    args = parser.parse_args()

    from recruit_agent.core.settings import load_settings
    from recruit_agent.db.session import create_engine_from_settings

    engine = create_engine_from_settings(load_settings())
    if args.command == "history":
        for migration in describe_migrations():
            print(f"{migration['version']}: {migration['name']}")
        return

    with engine.connect() as connection:
        if args.command == "current":
            print(current_schema_version(connection))
            return

    print(run_migrations(engine))


if __name__ == "__main__":
    main()
