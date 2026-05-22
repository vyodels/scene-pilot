from __future__ import annotations

from datetime import datetime, timedelta, timezone

from recruit_station.services.skills import SkillHealthCheckService, SkillRecord, SkillStatus


def test_skill_health_check_preflight_degrades_missing_executable_asset() -> None:
    skill = SkillRecord(
        skill_id="jd-diff",
        name="JD diff",
        platform="runtime-scene",
        status=SkillStatus.ACTIVE,
        strategy={"instruction": "Diff structured JD payloads."},
        execution_hints={"executor_mode": "python_inline"},
        body={"summary": "Missing artifacts."},
        health_check_config={
            "preflight": {
                "required_executor_mode": "python_inline",
                "required_artifacts": ["python_inline"],
            }
        },
    )

    result = SkillHealthCheckService().run(skill)

    assert result.health == "warning"
    assert result.recommended_status == SkillStatus.DEGRADED
    assert "missing_artifact:python_inline" in result.issues
    assert skill.status == SkillStatus.DEGRADED


def test_skill_health_check_postcondition_and_stale_checks() -> None:
    skill = SkillRecord(
        skill_id="jd-diff",
        name="JD diff",
        platform="runtime-scene",
        status=SkillStatus.ACTIVE,
        strategy={"instruction": "Diff structured JD payloads."},
        body={"artifacts": {"python_inline": {"entrypoint": "run"}}},
        last_health_check=datetime.now(timezone.utc) - timedelta(seconds=120),
        health_check_config={
            "stale_after_seconds": 30,
            "postconditions": {"required_output_fields": ["status", "created"]},
        },
    )

    result = SkillHealthCheckService().run(skill, observed_result={"status": "completed"})

    assert result.health == "warning"
    assert "stale_health_check" in result.issues
    assert "missing_output_field:created" in result.issues
    assert skill.status == SkillStatus.DEGRADED
