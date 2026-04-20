from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.models.domain import RecruitAgentProfile
from scene_pilot.services.recruit_agent import ensure_primary_recruit_agent_profile


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'recruit-agent-profile.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_ensure_primary_profile_normalizes_legacy_global_memory_schema(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        session.add(
            RecruitAgentProfile(
                agent_key="recruit-agent",
                name="Recruit Agent",
                is_primary=True,
                prompt_config={},
                memory_policy={
                    "candidate_memory": {
                        "isolation": "strict_by_candidate",
                        "auto_compact": True,
                        "compact_threshold": 123,
                        "schema": ["identity_summary"],
                        "disclosure": ["preview"],
                    },
                    "job_memory": {
                        "isolation": "strict_by_jd",
                        "auto_compact": True,
                        "compact_threshold": 456,
                        "schema": ["screening_preferences"],
                        "disclosure": ["preview"],
                    },
                    "agent_global_memory": {
                        "scope": "agent_global",
                        "auto_compact": True,
                        "compact_threshold": 789,
                        "schema": ["global_strategies", "common_failures", "effective_patterns"],
                        "disclosure": ["preview"],
                    },
                },
            )
        )
        session.commit()

        profile = ensure_primary_recruit_agent_profile(session)

        assert profile.memory_policy["agent_global_memory"]["scope"] == "agent_global"
        assert profile.memory_policy["agent_global_memory"]["compact_threshold"] == 789
        assert profile.memory_policy["agent_global_memory"]["schema"] == [
            "facts",
            "decisions",
            "open_questions",
            "next_actions",
            "risk_flags",
            "evidence_refs",
            "confidence",
        ]
    finally:
        session.close()
