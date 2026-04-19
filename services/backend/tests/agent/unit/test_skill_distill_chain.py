from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.evolution.learning_writer import LearningWriter
from scene_pilot.models.domain import EvolutionArtifact, Skill
from scene_pilot.services.evolution import build_skill_distill_review_payload


def _make_session_factory(tmp_path: Path):
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'skill-distill-unit.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)


def test_build_skill_distill_review_payload_only_contains_run_evidence() -> None:
    payload = build_skill_distill_review_payload(
        run_id="run-1",
        run_type="sync_jd_incremental",
        goal_kind="sync_jd_incremental",
        round_count=2,
        final_output='{"status":"completed","created":1}',
        tool_activity=[{"tool_name": "list_job_descriptions", "event_type": "tool.result"}],
        event_outline=[{"event_type": "round.completed", "message": "done"}],
    )

    assert payload["run_id"] == "run-1"
    assert payload["goal_kind"] == "sync_jd_incremental"
    assert payload["round_count"] == 2
    assert payload["tool_activity"][0]["tool_name"] == "list_job_descriptions"
    assert "goal_text" not in payload
    assert "constraints" not in payload
    assert "success_criteria" not in payload
    assert "context_hints" not in payload


def test_record_skill_draft_uses_llm_contract_body_instead_of_learning_content(tmp_path: Path) -> None:
    session_factory = _make_session_factory(tmp_path)
    writer = LearningWriter(session_factory)

    recorded = writer.record_skill_draft(
        draft_contract={
            "skill_name": "活跃 JD 增量同步",
            "description": "把活跃 JD 差异同步到共享工作区。",
            "category": "recruiting",
            "platform": "runtime-scene",
            "strategy": {
                "instruction": "先读取当前可见岗位，再与本地 JD 做差异比对。",
            },
            "body": {
                "summary": "复用当前招聘页面完成活跃 JD 增量同步。",
                "checklist": ["确认岗位仍在活跃招聘"],
            },
            "execution_hints": {
                "tool_preferences": ["list_job_descriptions", "upsert_job_description"],
            },
            "health_check_config": {"expected_result_status": "completed"},
            "skill_metadata": {"llm_generated": True},
        },
        tags=["autonomous", "skill_distill", "sync_jd_incremental"],
        trial_metrics={"runs": 1, "successes": 1},
        learning_content="不要把这句 learning_content 当成 skill 正文。",
        source_run_id="run-1",
        source_turn_id="turn-1",
        source_kind="autonomous",
        proposed_by="autonomous",
    )

    assert recorded["skill_name"] == "活跃 JD 增量同步"

    with session_factory() as session:
        skill = session.scalars(select(Skill)).first()
        assert skill is not None
        assert skill.strategy["instruction"] == "先读取当前可见岗位，再与本地 JD 做差异比对。"
        assert skill.body["summary"] == "复用当前招聘页面完成活跃 JD 增量同步。"
        assert "learning_content" not in skill.body

        artifact = session.scalars(select(EvolutionArtifact).where(EvolutionArtifact.artifact_kind == "skill_draft")).first()
        assert artifact is not None
        assert artifact.artifact_body["skill_contract"]["skill_name"] == "活跃 JD 增量同步"
