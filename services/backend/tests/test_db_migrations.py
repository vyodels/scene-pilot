from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.core.settings import AppSettings
from scene_pilot.db import CURRENT_SCHEMA_VERSION, SCHEMA_MIGRATIONS_TABLE, current_schema_version
from scene_pilot.db.migrations import ensure_schema_migrations_table, run_migrations
from scene_pilot.db.session import create_engine_from_settings, initialize_database


def _build_engine(tmp_path: Path):
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'recruit-agent.db'}",
    )
    return create_engine_from_settings(settings)


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
        for version in range(1, CURRENT_SCHEMA_VERSION):
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
