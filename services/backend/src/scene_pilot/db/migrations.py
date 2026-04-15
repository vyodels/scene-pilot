from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

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
        "workflow_templates": (
            "CREATE INDEX IF NOT EXISTS ix_workflow_templates_status_domain ON workflow_templates (status, domain)",
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
            "CREATE INDEX IF NOT EXISTS ix_environment_snapshots_episode_page_type ON environment_snapshots (execution_episode_id, page_type)",
        ),
        "workflow_patches": (
            "CREATE INDEX IF NOT EXISTS ix_workflow_patches_status_kind ON workflow_patches (status, patch_kind)",
            "CREATE INDEX IF NOT EXISTS ix_workflow_patches_template_created_at ON workflow_patches (template_id, created_at)",
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

    for table_name in ("candidate_memories", "job_memories", "agent_global_memories"):
        if table_name not in tables:
            continue
        columns = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()}
        if "raw_content" not in columns:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN raw_content TEXT NOT NULL DEFAULT '{{}}'"))
        if "disclosure" not in columns:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN disclosure TEXT NOT NULL DEFAULT '{{}}'"))

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
                    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
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
                    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
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
                    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
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
                    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
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
                    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
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
            text("CREATE INDEX IF NOT EXISTS ix_resume_artifacts_candidate_captured_at ON resume_artifacts (candidate_id, captured_at)")
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
                    agent_profile_id TEXT NOT NULL REFERENCES recruit_agent_profiles(id) ON DELETE CASCADE,
                    session_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    current_lane TEXT,
                    last_active_at TEXT,
                    last_run_at TEXT,
                    runtime_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CONSTRAINT uq_agent_sessions_agent_session_key UNIQUE (agent_profile_id, session_key)
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
                    candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
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
    if "agent_work_items" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE agent_work_items (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
                    queue_task_id TEXT,
                    candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
                    platform TEXT NOT NULL DEFAULT 'site',
                    lane TEXT NOT NULL DEFAULT 'agent',
                    item_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    priority INTEGER NOT NULL DEFAULT 100,
                    dedupe_key TEXT,
                    payload TEXT NOT NULL DEFAULT '{}',
                    scheduled_for TEXT,
                    claimed_at TEXT,
                    completed_at TEXT,
                    deferred_until TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CONSTRAINT uq_agent_work_items_queue_task_id UNIQUE (queue_task_id)
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
                    candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
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
                    candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
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
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_candidate_status ON agent_runs (candidate_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_execution_episode_id ON agent_runs (execution_episode_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_queue_task_id ON agent_runs (queue_task_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_platform_status ON agent_runs (platform, status)"))
    if "agent_work_items" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_work_items_run_status ON agent_work_items (run_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_work_items_candidate_status ON agent_work_items (candidate_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_work_items_dedupe_key ON agent_work_items (dedupe_key)"))
    if "agent_run_checkpoints" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_run_checkpoints_run_status ON agent_run_checkpoints (run_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_run_checkpoints_approval_id ON agent_run_checkpoints (approval_id)"))
    if "agent_runtime_events" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runtime_events_session_occurred_at ON agent_runtime_events (session_id, occurred_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runtime_events_run_occurred_at ON agent_runtime_events (run_id, occurred_at)"))


def _create_goal_runtime_tables(connection: Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }

    if "agent_sessions" in tables:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(agent_sessions)")).fetchall()}
        if "current_goal_id" not in columns:
            connection.execute(text("ALTER TABLE agent_sessions ADD COLUMN current_goal_id TEXT"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_sessions_current_goal_id ON agent_sessions (current_goal_id)"))

    if "agent_runs" in tables:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(agent_runs)")).fetchall()}
        if "goal_spec_id" not in columns:
            connection.execute(text("ALTER TABLE agent_runs ADD COLUMN goal_spec_id TEXT"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_runs_goal_spec_id ON agent_runs (goal_spec_id)"))

    if "agent_work_items" in tables:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(agent_work_items)")).fetchall()}
        if "goal_spec_id" not in columns:
            connection.execute(text("ALTER TABLE agent_work_items ADD COLUMN goal_spec_id TEXT"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_work_items_goal_spec_id ON agent_work_items (goal_spec_id)"))

    if "goal_specs" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE goal_specs (
                    id TEXT PRIMARY KEY,
                    agent_profile_id TEXT NOT NULL REFERENCES recruit_agent_profiles(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    goal_text TEXT NOT NULL,
                    goal_kind TEXT NOT NULL DEFAULT 'recruiting',
                    status TEXT NOT NULL DEFAULT 'draft',
                    source TEXT NOT NULL DEFAULT 'operator',
                    source_text TEXT,
                    requested_by TEXT,
                    constraints TEXT NOT NULL DEFAULT '{}',
                    success_criteria TEXT NOT NULL DEFAULT '{}',
                    context_hints TEXT NOT NULL DEFAULT '{}',
                    trial_budget TEXT NOT NULL DEFAULT '{}',
                    run_preferences TEXT NOT NULL DEFAULT '{}',
                    summary TEXT,
                    latest_run_id TEXT,
                    last_activity_at TEXT,
                    goal_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    if "execution_traces" not in tables:
        connection.execute(
            text(
                """
                CREATE TABLE execution_traces (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
                    goal_spec_id TEXT,
                    candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
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
                    agent_profile_id TEXT NOT NULL REFERENCES recruit_agent_profiles(id) ON DELETE CASCADE,
                    goal_spec_id TEXT,
                    run_id TEXT,
                    candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
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
                    goal_spec_id TEXT,
                    run_id TEXT,
                    candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
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
                    goal_spec_id TEXT,
                    candidate_id TEXT REFERENCES candidates(id) ON DELETE SET NULL,
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
    if "goal_specs" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_goal_specs_agent_status ON goal_specs (agent_profile_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_goal_specs_last_activity_at ON goal_specs (last_activity_at)"))
    if "execution_traces" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_traces_goal_created_at ON execution_traces (goal_spec_id, created_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_traces_run_created_at ON execution_traces (run_id, created_at)"))
    if "strategy_fragments" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_strategy_fragments_agent_status ON strategy_fragments (agent_profile_id, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_strategy_fragments_kind_scope ON strategy_fragments (fragment_kind, scope)"))
    if "execution_graph_projections" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_graph_projections_goal_created_at ON execution_graph_projections (goal_spec_id, created_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_execution_graph_projections_run_created_at ON execution_graph_projections (run_id, created_at)"))
    if "operator_interactions" in indexed_tables:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_operator_interactions_status_surfaced_at ON operator_interactions (status, surfaced_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_operator_interactions_candidate_status ON operator_interactions (candidate_id, status)"))
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
                    protocol TEXT NOT NULL DEFAULT 'json_socket_tool_call',
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
        name="create_goal_runtime_tables",
        apply=_create_goal_runtime_tables,
    ),
    SchemaMigration(
        version=10,
        name="create_mcp_registry_tables",
        apply=_create_mcp_registry_tables,
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

    from scene_pilot.core.settings import load_settings
    from scene_pilot.db.session import create_engine_from_settings

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
