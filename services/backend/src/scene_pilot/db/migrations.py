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
