from __future__ import annotations

from pathlib import Path

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import RecruitAgentProfile
from recruit_agent.services.container import _seed_builtin_agent_profiles


def test_seed_builtin_profiles_normalizes_autonomous_memory_writeback_policy(tmp_path: Path) -> None:
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
                    "legacy_candidate_context": {"schema": ["legacy_business_context"]},
                    "legacy_job_context": {"schema": ["legacy_business_context"]},
                    "legacy_global_context": {"schema": ["legacy_business_context"]},
                    "writeback": {"auto_write_min_confidence": 0.9, "max_stable_facts": 3},
                },
            )
        )
        session.commit()

    _seed_builtin_agent_profiles(session_factory)

    with session_factory() as session:
        profile = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
        assert set(profile.memory_policy) == {"writeback"}
        assert profile.memory_policy["writeback"]["auto_write_min_confidence"] == 0.9
        assert profile.memory_policy["writeback"]["max_stable_facts"] == 3


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
