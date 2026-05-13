from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.evolution.learning_writer import LearningWriter
from recruit_agent.models.domain import EvolutionArtifact, Skill
from recruit_agent.services.evolution import build_skill_distill_review_payload, promote_skill_draft_contract


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
        run_kind="sync_jd_incremental",
        engine_output_count=2,
        final_output='{"status":"completed","created":1}',
        tool_activity=[{"tool_name": "list_job_descriptions", "event_type": "tool_event", "kind": "tool_result_ready"}],
        event_outline=[{"event_type": "llm_invocation_completed", "message": "done"}],
    )

    assert payload["run_id"] == "run-1"
    assert payload["run_kind"] == "sync_jd_incremental"
    assert payload["engine_output_count"] == 2
    assert payload["tool_activity"][0]["tool_name"] == "list_job_descriptions"
    assert "instruction_text" not in payload
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


def test_record_skill_draft_blocks_mock_scope_auto_promotion(tmp_path: Path) -> None:
    session_factory = _make_session_factory(tmp_path)
    writer = LearningWriter(session_factory)

    recorded = writer.record_skill_draft(
        draft_contract={
            "skill_name": "mock 候选人详情点击",
            "description": "仅用于 mock 页面验证的候选人详情点击经验。",
            "category": "recruiting",
            "platform": "boss_mock",
            "strategy": {"instruction": "仅适用于 mock fixture。"},
            "body": {"summary": "mock-only 操作路径。"},
            "skill_metadata": {"environment_scope": "mock_only"},
        },
        tags=["autonomous", "skill_distill", "mock_validation_evidence"],
        trial_metrics={"runs": 5, "successes": 5},
        source_run_id="run-mock",
        source_turn_id="turn-mock",
        source_kind="autonomous",
        proposed_by="autonomous",
    )

    assert recorded["auto_promoted"] is False
    assert recorded["environment_scope"] == "mock_only"
    assert recorded["judgment"]["promotion_blocked_reason"] == "mock_environment_scope"

    with session_factory() as session:
        skill = session.scalars(select(Skill)).first()
        assert skill is not None
        assert skill.status == "trial"
        assert skill.skill_metadata["environment_scope"] == "mock_only"
        assert skill.skill_metadata["not_for_real_site"] is True
        assert skill.skill_metadata["real_site_verified"] is False

        artifact = session.scalars(select(EvolutionArtifact).where(EvolutionArtifact.artifact_kind == "skill_draft")).first()
        assert artifact is not None
        assert artifact.status == "pending_review"
        assert artifact.artifact_body["environment_scope"] == "mock_only"
        assert artifact.artifact_metadata["not_for_real_site"] is True


def test_promote_skill_draft_rejects_mock_scope_contract(tmp_path: Path) -> None:
    session_factory = _make_session_factory(tmp_path)

    with session_factory() as session:
        try:
            promote_skill_draft_contract(
                session,
                auto_activate=True,
                draft={
                    "skill_name": "mock-only skill",
                    "description": "不能晋升为真实站点 skill。",
                    "skill_metadata": {"environment_scope": "mock_only"},
                },
                reviewer="reviewer",
                reason="attempted promotion",
                fallback_title="mock-only skill",
            )
        except ValueError as exc:
            assert "mock-only" in str(exc)
        else:
            raise AssertionError("mock-only skill promotion should fail")
