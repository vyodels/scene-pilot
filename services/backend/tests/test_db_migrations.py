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
        database_url=f"sqlite:///{tmp_path / 'scene-pilot.db'}",
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
        assert "candidates" in tables
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
