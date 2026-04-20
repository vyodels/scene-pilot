from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, initialize_database


def test_schema_uses_turn_terminology(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'schema-terminology.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    inspector = inspect(engine)

    table_names = set(inspector.get_table_names())
    turn_record_tables = {name for name in table_names if name.startswith("agent_") and name.endswith("_records")}
    assert turn_record_tables == {"agent_turn_records"}

    run_columns = {column["name"] for column in inspector.get_columns("agent_runs")}
    assert "turns_count" in run_columns
    assert {name for name in run_columns if name.endswith("_count")} == {"turns_count"}
    assert {"person_id", "application_id"} <= run_columns
    assert "candidate_id" not in run_columns

    work_item_columns = {column["name"] for column in inspector.get_columns("agent_work_items")}
    assert {"person_id", "application_id"} <= work_item_columns
    assert "candidate_id" not in work_item_columns

    turn_record_columns = {column["name"] for column in inspector.get_columns("agent_turn_records")}
    assert {"turn_id", "run_pk", "seq", "turn_metadata"}.issubset(turn_record_columns)
    assert {name for name in turn_record_columns if name.endswith("_id")} == {"turn_id"}

    runtime_event_columns = {column["name"] for column in inspector.get_columns("agent_runtime_events")}
    assert "turn_id" in runtime_event_columns
    assert "candidate_id" not in runtime_event_columns
    assert {name for name in runtime_event_columns if name.endswith("_id")} == {
        "application_id",
        "conversation_id",
        "person_id",
        "run_id",
        "session_id",
        "turn_id",
    }

    operator_interaction_columns = {column["name"] for column in inspector.get_columns("operator_interactions")}
    assert {"person_id", "application_id"} <= operator_interaction_columns
    assert "candidate_id" not in operator_interaction_columns

    approval_columns = {column["name"] for column in inspector.get_columns("approval_items")}
    assert {name for name in approval_columns if name.endswith("_pk")} == {
        "conversation_pk",
        "run_pk",
        "turn_pk",
    }

    tool_invocation_columns = {column["name"] for column in inspector.get_columns("tool_invocations")}
    assert {name for name in tool_invocation_columns if name.endswith("_pk")} == {"turn_pk"}
