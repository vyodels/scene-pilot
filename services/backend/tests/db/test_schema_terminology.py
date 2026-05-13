from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, initialize_database


def test_schema_uses_turn_terminology(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'schema-terminology.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    inspector = inspect(engine)

    table_names = set(inspector.get_table_names())
    assert "agent_definitions" in table_names
    assert "recruit_agent_profiles" not in table_names
    assert "goal_specs" not in table_names
    turn_record_tables = {name for name in table_names if name.startswith("agent_") and name.endswith("_records")}
    assert turn_record_tables == {"agent_turn_records"}

    definition_columns = {column["name"] for column in inspector.get_columns("agent_definitions")}
    assert "definition_key" in definition_columns
    assert "agent_key" not in definition_columns

    run_columns = {column["name"] for column in inspector.get_columns("agent_runs")}
    assert "turns_count" in run_columns
    assert {name for name in run_columns if name.endswith("_count")} == {"turns_count"}
    assert {"person_id", "application_id"} <= run_columns
    assert "candidate_id" not in run_columns

    assert "agent_work_items" not in table_names
    assert not {name for name in table_names if "work_item" in name}

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

    for table_name in table_names:
        column_names = {column["name"] for column in inspector.get_columns(table_name)}
        assert "agent_profile_id" not in column_names
        assert "goal_spec_id" not in column_names
