from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from recruit_station.core.settings import AppSettings
from recruit_station.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_station.evolution.learning_writer import LearningWriter
from recruit_station.models.domain import EvolutionArtifact, Skill
from recruit_station.services.evolution import build_skill_distill_review_payload, promote_skill_draft_contract


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


def test_record_skill_draft_preserves_valid_python_inline_asset(tmp_path: Path) -> None:
    session_factory = _make_session_factory(tmp_path)
    writer = LearningWriter(session_factory)

    recorded = writer.record_skill_draft(
        draft_contract={
            "skill_name": "JD 差异比对",
            "description": "基于结构化输入比对远端和本地 JD。",
            "category": "recruiting",
            "body": {
                "summary": "比对 JD 差异。",
                "artifacts": {
                    "python_inline": {
                        "entrypoint": "run",
                        "code": "def run(payload, context):\n    return {'status': 'completed', 'count': len(payload.get('remote', []))}\n",
                        "input_contract": {"type": "object"},
                        "output_contract": {"type": "object"},
                    }
                },
            },
            "health_check_config": {
                "preflight": {"required_artifacts": ["python_inline"], "required_executor_mode": "python_inline"},
                "postconditions": {"required_output_fields": ["status"]},
            },
        },
        tags=["autonomous", "skill_distill", "sync_jd_incremental"],
        trial_metrics={"runs": 1, "successes": 1},
    )

    assert recorded["skill_name"] == "JD 差异比对"
    with session_factory() as session:
        skill = session.scalars(select(Skill)).first()
        assert skill is not None
        assert skill.execution_hints["executor_mode"] == "python_inline"
        assert skill.body["artifacts"]["python_inline"]["entrypoint"] == "run"
        assert skill.health_check_config["preflight"]["required_artifacts"] == ["python_inline"]


def test_record_skill_draft_rejects_side_effect_python_inline_asset(tmp_path: Path) -> None:
    session_factory = _make_session_factory(tmp_path)
    writer = LearningWriter(session_factory)

    try:
        writer.record_skill_draft(
            draft_contract={
                "skill_name": "unsafe asset",
                "body": {
                    "artifacts": {
                        "python_inline": {
                            "entrypoint": "run",
                            "code": "import subprocess\n\ndef run(payload, context):\n    return subprocess.run(['echo', 'x'])\n",
                        }
                    }
                },
            },
            tags=["autonomous", "skill_distill"],
            trial_metrics={"runs": 1, "successes": 1},
        )
    except ValueError as exc:
        assert "blocked module" in str(exc)
    else:
        raise AssertionError("unsafe python_inline asset should be rejected")


def test_record_skill_draft_marks_mock_scope_as_test_skill_when_promoted(tmp_path: Path) -> None:
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

    assert recorded["auto_promoted"] is True
    assert recorded["environment_scope"] == "mock_only"
    assert recorded["judgment"]["environment_scope"] == "mock_only"

    with session_factory() as session:
        skill = session.scalars(select(Skill)).first()
        assert skill is not None
        assert skill.status == "active"
        assert skill.skill_metadata["environment_scope"] == "mock_only"
        assert skill.skill_metadata["not_for_real_site"] is True
        assert skill.skill_metadata["real_site_verified"] is False
        assert skill.skill_metadata["test_skill"] is True

        artifact = session.scalars(select(EvolutionArtifact).where(EvolutionArtifact.artifact_kind == "skill_draft")).first()
        assert artifact is not None
        assert artifact.status == "auto_promoted"
        assert artifact.artifact_body["environment_scope"] == "mock_only"
        assert artifact.artifact_metadata["not_for_real_site"] is True
        assert artifact.artifact_metadata["test_skill"] is True


def test_record_skill_draft_marks_unspecified_scope_as_test_skill_when_promoted(tmp_path: Path) -> None:
    session_factory = _make_session_factory(tmp_path)
    writer = LearningWriter(session_factory)

    recorded = writer.record_skill_draft(
        draft_contract={
            "skill_name": "JD 详情补齐",
            "description": "补齐已发现 JD 的详情字段。",
            "category": "recruiting",
            "platform": "runtime-scene",
            "strategy": {"instruction": "基于已观察到的详情补齐字段。"},
            "body": {"summary": "补齐 JD 详情。"},
        },
        tags=["autonomous", "skill_distill"],
        trial_metrics={"runs": 5, "successes": 5},
        source_run_id="run-unspecified",
        source_turn_id="turn-unspecified",
        source_kind="autonomous",
        proposed_by="autonomous",
    )

    assert recorded["auto_promoted"] is True
    assert recorded["environment_scope"] == "unspecified"
    assert recorded["judgment"]["environment_scope"] == "unspecified"

    with session_factory() as session:
        skill = session.scalars(select(Skill)).first()
        assert skill is not None
        assert skill.status == "active"
        assert skill.trial_metrics["auto_promote"] is True
        assert skill.skill_metadata["environment_scope"] == "unspecified"
        assert skill.skill_metadata["real_site_verified"] is False
        assert skill.skill_metadata["test_skill"] is True


def test_promote_skill_draft_allows_mock_scope_contract_with_test_skill_marker(tmp_path: Path) -> None:
    session_factory = _make_session_factory(tmp_path)

    with session_factory() as session:
        promoted = promote_skill_draft_contract(
            session,
            auto_activate=True,
            draft={
                "skill_name": "mock-only skill",
                "description": "可以晋升，但必须标记为测试 skill。",
                "skill_metadata": {"environment_scope": "mock_only"},
            },
            reviewer="reviewer",
            reason="attempted promotion",
            fallback_title="mock-only skill",
        )

    assert promoted["status"] == "active"
    with session_factory() as session:
        skill = session.scalars(select(Skill)).first()
        assert skill is not None
        assert skill.skill_metadata["environment_scope"] == "mock_only"
        assert skill.skill_metadata["not_for_real_site"] is True
        assert skill.skill_metadata["test_skill"] is True
