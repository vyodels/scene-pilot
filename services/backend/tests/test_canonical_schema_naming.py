from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, initialize_database


def _build_engine(tmp_path: Path):
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'recruit-agent.db'}",
    )
    return create_engine_from_settings(settings)


def test_canonical_core_tables_exist(tmp_path):
    engine = _build_engine(tmp_path)
    initialize_database(engine)

    with engine.connect() as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }

    expected_tables = {
        "candidate_persons",
        "candidate_person_platform_idx",
        "candidate_applications",
        "job_descriptions",
        "job_description_platform_idx",
        "candidate_application_assessments",
        "candidate_application_scorecards",
        "candidate_application_messages",
        "candidate_application_transitions",
    }

    missing = expected_tables - table_names
    assert not missing, f"Missing canonical tables: {sorted(missing)}"


def test_canonical_business_ids_and_timestamp_columns_exist(tmp_path):
    engine = _build_engine(tmp_path)
    initialize_database(engine)

    with engine.connect() as connection:
        person_columns = {
            row[1]: row[2]
            for row in connection.execute(text("PRAGMA table_info(candidate_persons)")).fetchall()
        }
        application_columns = {
            row[1]: row[2]
            for row in connection.execute(text("PRAGMA table_info(candidate_applications)")).fetchall()
        }
        platform_idx_columns = {
            row[1]: row[2]
            for row in connection.execute(text("PRAGMA table_info(candidate_person_platform_idx)")).fetchall()
        }
        application_transition_columns = {
            row[1]: row[2]
            for row in connection.execute(text("PRAGMA table_info(candidate_application_transitions)")).fetchall()
        }
        message_columns = {
            row[1]: row[2]
            for row in connection.execute(text("PRAGMA table_info(candidate_application_messages)")).fetchall()
        }
        job_columns = {
            row[1]: row[2]
            for row in connection.execute(text("PRAGMA table_info(job_descriptions)")).fetchall()
        }

    assert "candidate_person_id" in person_columns
    assert "candidate_application_id" in application_columns
    assert "platform_candidate_person_id" in platform_idx_columns
    assert "source_platform_candidate_person_id" in application_columns
    assert {
        "company_name",
        "employment_type",
        "compensation_text",
        "experience_requirement",
        "education_requirement",
        "summary",
        "benefit_tags",
        "detail_metadata",
    } <= set(job_columns)

    for column_map in (person_columns, application_columns, platform_idx_columns):
        assert column_map["created_at"].upper() in {"BIGINT", "INTEGER"}
        assert column_map["updated_at"].upper() in {"BIGINT", "INTEGER"}

    assert platform_idx_columns["first_seen_at"].upper() in {"BIGINT", "INTEGER"}
    assert platform_idx_columns["last_seen_at"].upper() in {"BIGINT", "INTEGER"}
    assert application_columns["cooldown_until"].upper() in {"BIGINT", "INTEGER"}
    assert application_columns["last_contacted_at"].upper() in {"BIGINT", "INTEGER"}
    assert application_transition_columns["created_at"].upper() in {"BIGINT", "INTEGER"}
    assert message_columns["timestamp"].upper() in {"BIGINT", "INTEGER"}
