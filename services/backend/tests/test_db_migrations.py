from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from recruit_agent.core.settings import AppSettings
from recruit_agent.db import CURRENT_SCHEMA_VERSION, SCHEMA_MIGRATIONS_TABLE, current_schema_version
from recruit_agent.db.migrations import ensure_schema_migrations_table, run_migrations
from recruit_agent.db.session import create_engine_from_settings, initialize_database


def _build_engine(tmp_path: Path):
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'recruit-agent.db'}",
    )
    return create_engine_from_settings(settings)


def _legacy_database_memory_table_names() -> tuple[str, ...]:
    memory = "memories"
    return (
        "_".join(("candidate", memory)),
        "_".join(("job", memory)),
        "_".join(("agent", "global", memory)),
        "_".join(("candidate", "person", memory)),
        "_".join(("job", "description", memory)),
    )


def test_initialize_database_records_baseline_version(tmp_path):
    engine = _build_engine(tmp_path)

    initialize_database(engine)

    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        assert SCHEMA_MIGRATIONS_TABLE in tables
        assert "candidate_persons" in tables
        assert "candidate_applications" in tables
        assert "job_descriptions" in tables
        assert "candidate_person_platform_idx" in tables
        assert "job_description_platform_idx" in tables
        assert "candidate_application_assessments" in tables
        assert "candidate_application_scorecards" in tables
        assert "candidate_application_messages" in tables
        assert "candidate_application_transitions" in tables
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION


def test_initialize_database_is_idempotent(tmp_path):
    engine = _build_engine(tmp_path)

    initialize_database(engine)
    initialize_database(engine)

    with engine.connect() as connection:
        applied_rows = connection.execute(
            text(f"SELECT version, name FROM {SCHEMA_MIGRATIONS_TABLE} ORDER BY version ASC")
        ).fetchall()
        assert len(applied_rows) == CURRENT_SCHEMA_VERSION
        assert applied_rows[-1][0] == CURRENT_SCHEMA_VERSION


def test_run_migrations_on_existing_database_with_empty_registry(tmp_path):
    engine = _build_engine(tmp_path)

    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)

    run_migrations(engine)

    with engine.connect() as connection:
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION


def test_run_migrations_creates_supporting_indexes(tmp_path):
    engine = _build_engine(tmp_path)

    initialize_database(engine)

    with engine.connect() as connection:
        indexes = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='index'")
            ).fetchall()
        }
        assert "ix_task_queue_status_scheduled_for" in indexes
        assert "ix_task_queue_locked_at" in indexes
        assert "ix_sync_backlog_status_item_type" in indexes


def test_run_migrations_adds_job_description_detail_columns_for_existing_schema(tmp_path):
    engine = _build_engine(tmp_path)

    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)
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
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        for version in range(1, 19):
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, name, applied_at)
                    VALUES (:version, :name, :applied_at)
                    """
                ),
                {
                    "version": version,
                    "name": f"migration-{version}",
                    "applied_at": "2026-04-20T00:00:00+00:00",
                },
            )

    run_migrations(engine)

    with engine.connect() as connection:
        job_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(job_descriptions)")).fetchall()
        }
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        assert {
            "company_name",
            "employment_type",
            "compensation_text",
            "experience_requirement",
            "education_requirement",
            "summary",
            "benefit_tags",
            "detail_metadata",
        } <= job_columns


def test_run_migrations_aligns_candidate_lock_scope_for_existing_schema(tmp_path):
    engine = _build_engine(tmp_path)

    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)
        connection.execute(
            text(
                """
                CREATE TABLE candidate_persons (
                    id TEXT PRIMARY KEY NOT NULL,
                    candidate_person_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT 'site',
                    platform_candidate_id TEXT,
                    contact_info TEXT NOT NULL DEFAULT '{}',
                    resume_path TEXT,
                    online_resume_text TEXT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE candidate_applications (
                    id TEXT PRIMARY KEY NOT NULL,
                    candidate_application_id TEXT NOT NULL UNIQUE,
                    person_id TEXT NOT NULL,
                    job_description_id TEXT,
                    platform TEXT NOT NULL DEFAULT 'site',
                    source_platform TEXT NOT NULL DEFAULT 'site',
                    platform_application_id TEXT,
                    source_platform_candidate_person_id TEXT,
                    application_window TEXT NOT NULL,
                    current_status TEXT NOT NULL DEFAULT 'discovered',
                    current_stage_key TEXT,
                    deepest_milestone TEXT,
                    state_snapshot TEXT NOT NULL DEFAULT '{}',
                    contact_snapshot TEXT NOT NULL DEFAULT '{}',
                    resume_snapshot TEXT NOT NULL DEFAULT '{}',
                    ai_scores TEXT NOT NULL DEFAULT '{}',
                    ai_reasoning TEXT,
                    cooldown_until BIGINT,
                    last_contacted_at BIGINT,
                    active_assessment_summary TEXT NOT NULL DEFAULT '{}',
                    application_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE candidate_autonomous_locks (
                    id TEXT PRIMARY KEY NOT NULL,
                    candidate_person_id TEXT NOT NULL,
                    locked_at BIGINT NOT NULL,
                    locked_by TEXT NOT NULL,
                    reason TEXT,
                    expires_at BIGINT,
                    released_at BIGINT,
                    released_by TEXT,
                    handover_note TEXT,
                    handover_next_hint TEXT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO candidate_persons (
                    id, candidate_person_id, name, platform, platform_candidate_id, contact_info, created_at, updated_at
                ) VALUES (
                    'cand-storage-1', 'cand-biz-1', 'Alice', 'site', NULL, '{}', 1, 1
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO candidate_applications (
                    id, candidate_application_id, person_id, job_description_id, platform, source_platform,
                    application_window, current_status, state_snapshot, contact_snapshot, resume_snapshot, ai_scores,
                    active_assessment_summary, application_metadata, created_at, updated_at
                ) VALUES (
                    'app-storage-1', 'app-biz-1', 'cand-storage-1', NULL, 'site', 'site',
                    'cand-biz-1::job-1::202604', 'discovered', '{}', '{}', '{}', '{}', '{}', '{}', 1, 1
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO candidate_autonomous_locks (
                    id, candidate_person_id, locked_at, locked_by, reason, expires_at, released_at, released_by,
                    handover_note, handover_next_hint, created_at, updated_at
                ) VALUES (
                    'lock-1', 'cand-biz-1', 1, 'human-a', 'manual', NULL, NULL, NULL, NULL, NULL, 1, 1
                )
                """
            )
        )
        for version in range(1, 26):
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, name, applied_at)
                    VALUES (:version, :name, :applied_at)
                    """
                ),
                {
                    "version": version,
                    "name": f"migration-{version}",
                    "applied_at": "2026-04-20T00:00:00+00:00",
                },
            )

    run_migrations(engine)

    with engine.connect() as connection:
        lock_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(candidate_autonomous_locks)")).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
        }
        migrated_lock = connection.execute(
            text("SELECT application_id, candidate_person_id FROM candidate_autonomous_locks WHERE id = 'lock-1'")
        ).fetchone()
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        assert "application_id" in lock_columns
        assert "ix_candidate_autonomous_locks_application_id" in indexes
        assert migrated_lock == ("app-biz-1", "cand-biz-1")


def test_run_migrations_aligns_mcp_server_columns_for_existing_schema(tmp_path):
    engine = _build_engine(tmp_path)

    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)
        connection.execute(
            text(
                """
                CREATE TABLE mcp_servers (
                    id TEXT PRIMARY KEY NOT NULL,
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
                    last_health_at BIGINT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        for version in range(1, 20):
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, name, applied_at)
                    VALUES (:version, :name, :applied_at)
                    """
                ),
                {
                    "version": version,
                    "name": f"migration-{version}",
                    "applied_at": "2026-04-20T00:00:00+00:00",
                },
            )

    run_migrations(engine)

    with engine.connect() as connection:
        server_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(mcp_servers)")).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
        }
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        assert {"capabilities", "circuit_state", "circuit_until", "last_error"} <= server_columns
        assert "ix_mcp_servers_circuit_state" in indexes
        assert "ix_mcp_servers_circuit_until" in indexes


def test_run_migrations_aligns_agent_run_columns_for_existing_schema(tmp_path):
    engine = _build_engine(tmp_path)

    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)
        connection.execute(
            text(
                """
                CREATE TABLE agent_runs (
                    id TEXT PRIMARY KEY NOT NULL,
                    session_id TEXT NOT NULL,
                    execution_episode_id TEXT,
                    candidate_id TEXT,
                    jd_id TEXT,
                    platform TEXT NOT NULL DEFAULT 'site',
                    lane TEXT NOT NULL DEFAULT 'agent',
                    run_type TEXT NOT NULL DEFAULT 'generic',
                    status TEXT NOT NULL DEFAULT 'queued',
                    priority INTEGER NOT NULL DEFAULT 100,
                    queue_task_id TEXT,
                    checkpoint_status TEXT NOT NULL DEFAULT 'none',
                    context_manifest JSON NOT NULL DEFAULT '{}',
                    runtime_metadata JSON NOT NULL DEFAULT '{}',
                    started_at BIGINT,
                    finished_at BIGINT,
                    blocked_reason TEXT,
                    last_error TEXT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        for version in range(1, 21):
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, name, applied_at)
                    VALUES (:version, :name, :applied_at)
                    """
                ),
                {
                    "version": version,
                    "name": f"migration-{version}",
                    "applied_at": "2026-04-20T00:00:00+00:00",
                },
            )

    run_migrations(engine)

    with engine.connect() as connection:
        run_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_runs)")).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
        }
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        assert {
            "run_id",
            "agent_kind",
            "turns_count",
            "prompt_tokens",
            "completion_tokens",
            "cache_hit_tokens",
            "escalate_reason",
            "lock_scope",
            "idempotency_key",
            "wakeup_state",
        } <= run_columns
        assert "uq_agent_runs_run_id" in indexes
        assert "uq_agent_runs_idempotency_key" in indexes
        assert "ix_agent_runs_agent_kind" in indexes


def test_run_migrations_aligns_agent_runtime_subject_columns_after_version_27(tmp_path):
    engine = _build_engine(tmp_path)

    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)
        connection.execute(
            text(
                """
                CREATE TABLE agent_runs (
                    id TEXT PRIMARY KEY NOT NULL,
                    session_id TEXT NOT NULL,
                    candidate_id TEXT,
                    jd_id TEXT,
                    platform TEXT NOT NULL DEFAULT 'site',
                    lane TEXT NOT NULL DEFAULT 'agent',
                    run_type TEXT NOT NULL DEFAULT 'generic',
                    status TEXT NOT NULL DEFAULT 'queued',
                    priority INTEGER NOT NULL DEFAULT 100,
                    checkpoint_status TEXT NOT NULL DEFAULT 'none',
                    context_manifest JSON NOT NULL DEFAULT '{}',
                    runtime_metadata JSON NOT NULL DEFAULT '{}',
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE agent_run_checkpoints (
                    id TEXT PRIMARY KEY NOT NULL,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    candidate_id TEXT,
                    checkpoint_kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    title TEXT NOT NULL,
                    payload JSON NOT NULL DEFAULT '{}',
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE agent_runtime_events (
                    id TEXT PRIMARY KEY NOT NULL,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    candidate_id TEXT,
                    level TEXT NOT NULL DEFAULT 'info',
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload JSON NOT NULL DEFAULT '{}',
                    occurred_at BIGINT NOT NULL,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        for version in range(1, 28):
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, name, applied_at)
                    VALUES (:version, :name, :applied_at)
                    """
                ),
                {
                    "version": version,
                    "name": f"migration-{version}",
                    "applied_at": "2026-04-20T00:00:00+00:00",
                },
            )

    run_migrations(engine)

    with engine.connect() as connection:
        run_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_runs)")).fetchall()
        }
        checkpoint_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_run_checkpoints)")).fetchall()
        }
        event_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_runtime_events)")).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
        }

        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        assert {"person_id", "application_id", "jd_id"} <= run_columns
        assert {"person_id", "application_id"} <= checkpoint_columns
        assert {"person_id", "application_id"} <= event_columns
        assert "ix_agent_runs_person_status" in indexes
        assert "ix_agent_runs_application_status" in indexes


def test_run_migrations_aligns_skill_columns_for_runtime_learning(tmp_path):
    engine = _build_engine(tmp_path)

    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)
        connection.execute(
            text(
                """
                CREATE TABLE skills (
                    id TEXT PRIMARY KEY NOT NULL,
                    skill_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT NOT NULL DEFAULT 'general',
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'draft',
                    bound_to_stage TEXT,
                    platform TEXT NOT NULL DEFAULT 'site',
                    input_schema JSON NOT NULL DEFAULT '{}',
                    output_schema JSON NOT NULL DEFAULT '{}',
                    strategy JSON NOT NULL DEFAULT '{}',
                    execution_hints JSON NOT NULL DEFAULT '{}',
                    risk_level TEXT NOT NULL DEFAULT 'medium',
                    health_check_config JSON NOT NULL DEFAULT '{}',
                    skill_metadata JSON NOT NULL DEFAULT '{}',
                    last_health_check BIGINT,
                    last_health_status TEXT,
                    confirmed_by TEXT,
                    confirmed_at BIGINT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        for version in range(1, 22):
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, name, applied_at)
                    VALUES (:version, :name, :applied_at)
                    """
                ),
                {
                    "version": version,
                    "name": f"migration-{version}",
                    "applied_at": "2026-04-20T00:00:00+00:00",
                },
            )

    run_migrations(engine)

    with engine.connect() as connection:
        skill_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(skills)")).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
        }
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        assert {
            "trigger_hint",
            "body",
            "trial_metrics",
            "requires_human_gate",
            "human_gate_policy",
        } <= skill_columns
        assert "ix_skills_requires_human_gate" in indexes


def test_run_migrations_aligns_approval_and_runtime_event_columns(tmp_path):
    engine = _build_engine(tmp_path)

    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)
        connection.execute(
            text(
                """
                CREATE TABLE approval_items (
                    id TEXT PRIMARY KEY NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    requested_by TEXT,
                    reviewed_by TEXT,
                    reviewed_at BIGINT,
                    payload JSON NOT NULL DEFAULT '{}',
                    notes TEXT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE agent_runtime_events (
                    id TEXT PRIMARY KEY NOT NULL,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    candidate_id TEXT,
                    level TEXT NOT NULL DEFAULT 'info',
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload JSON NOT NULL DEFAULT '{}',
                    occurred_at BIGINT NOT NULL,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )
        )
        for version in range(1, 23):
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, name, applied_at)
                    VALUES (:version, :name, :applied_at)
                    """
                ),
                {
                    "version": version,
                    "name": f"migration-{version}",
                    "applied_at": "2026-04-20T00:00:00+00:00",
                },
            )

    run_migrations(engine)

    with engine.connect() as connection:
        approval_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(approval_items)")).fetchall()
        }
        event_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_runtime_events)")).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
        }
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        assert {
            "run_pk",
            "turn_pk",
            "conversation_pk",
            "source_kind",
            "tool_name",
            "args_digest",
            "expires_at",
            "executed_at",
            "idempotency_key",
        } <= approval_columns
        assert {"turn_id", "conversation_id", "seq"} <= event_columns
        assert "uq_approval_items_idempotency_key" in indexes
        assert "ix_agent_runtime_events_turn_id" in indexes
        assert "ix_agent_runtime_events_conversation_id" in indexes


def test_run_migrations_drops_legacy_database_memory_tables(tmp_path):
    engine = _build_engine(tmp_path)

    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)
        for table_name in _legacy_database_memory_table_names():
            connection.execute(
                text(
                    f"""
                    CREATE TABLE {table_name} (
                        id TEXT PRIMARY KEY NOT NULL
                    )
                    """
                )
            )
        for version in range(1, 27):
            connection.execute(
                text(
                    f"""
                    INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, name, applied_at)
                    VALUES (:version, :name, :applied_at)
                    """
                ),
                {
                    "version": version,
                    "name": f"migration-{version}",
                    "applied_at": "2026-04-20T00:00:00+00:00",
                },
            )

    run_migrations(engine)

    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        }
        assert current_schema_version(connection) == CURRENT_SCHEMA_VERSION
        assert not (set(_legacy_database_memory_table_names()) & tables)
