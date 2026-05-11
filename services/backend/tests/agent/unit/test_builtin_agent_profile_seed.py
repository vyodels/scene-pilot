from __future__ import annotations

from pathlib import Path

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import RecruitAgentProfile
from recruit_agent.services.container import _seed_builtin_agent_profiles


def test_seed_builtin_profiles_normalizes_autonomous_memory_policy(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'builtin-agent-seed.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        session.add(
            RecruitAgentProfile(
                agent_key="autonomous",
                name="Autonomous",
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

    _seed_builtin_agent_profiles(session_factory)

    with session_factory() as session:
        profile = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
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


def test_seed_builtin_profiles_backfills_autonomous_goal_template(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'builtin-agent-goal-template.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        session.add(
            RecruitAgentProfile(
                agent_key="autonomous",
                name="Autonomous",
                is_primary=True,
                prompt_config={},
                memory_policy={},
            )
        )
        session.commit()

    _seed_builtin_agent_profiles(session_factory)

    with session_factory() as session:
        profile = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
        goal_template = str((profile.prompt_config or {}).get("goal_template") or "")
        assert "定期同步当前仍处于活跃招聘中的 JD" in goal_template
        assert "围绕活跃 JD 主动探索多种可达的候选人发现路径" in goal_template
        assert "把 JD、投递记录事实、评分结果、沟通状态、阻塞原因和下一步动作写入系统" in goal_template
