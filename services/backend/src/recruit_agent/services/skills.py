from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .feature_flags import FeatureFlagService


class SkillStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    ACTIVE = "active"
    DEGRADED = "degraded"
    DISABLED = "disabled"


@dataclass(slots=True)
class SkillRecord:
    skill_id: str
    name: str
    platform: str
    version: str = "1.0.0"
    status: SkillStatus = SkillStatus.DRAFT
    strategy: dict[str, Any] = field(default_factory=dict)
    execution_hints: dict[str, Any] = field(default_factory=dict)
    health_check_config: dict[str, Any] = field(default_factory=dict)
    last_health_check: datetime | None = None
    last_health_status: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SkillLifecycleService:
    flags: FeatureFlagService = field(default_factory=FeatureFlagService)

    def submit_for_review(self, skill: SkillRecord) -> SkillRecord:
        skill.status = SkillStatus.PENDING_REVIEW
        skill.updated_at = datetime.now(timezone.utc)
        return skill

    def approve(self, skill: SkillRecord, reviewer: str) -> SkillRecord:
        skill.status = SkillStatus.APPROVED
        skill.confirmed_by = reviewer
        skill.confirmed_at = datetime.now(timezone.utc)
        skill.updated_at = skill.confirmed_at
        return skill

    def activate(self, skill: SkillRecord, *, manual: bool = False) -> SkillRecord:
        if not manual:
            self.flags.require_enabled("skills.auto_activate")
        if skill.status not in {SkillStatus.APPROVED, SkillStatus.DEGRADED}:
            raise ValueError("Skill must be approved before activation")
        skill.status = SkillStatus.ACTIVE
        skill.updated_at = datetime.now(timezone.utc)
        return skill

    def degrade(self, skill: SkillRecord, reason: str) -> SkillRecord:
        skill.status = SkillStatus.DEGRADED
        skill.last_health_status = reason
        skill.updated_at = datetime.now(timezone.utc)
        return skill

    def disable(self, skill: SkillRecord, reason: str | None = None) -> SkillRecord:
        skill.status = SkillStatus.DISABLED
        skill.last_health_status = reason or "disabled"
        skill.updated_at = datetime.now(timezone.utc)
        return skill


@dataclass(slots=True)
class SkillSafetyService:
    flags: FeatureFlagService = field(default_factory=FeatureFlagService)

    def can_auto_activate(self, skill: SkillRecord) -> bool:
        return (
            self.flags.is_enabled("skills.auto_activate")
            and skill.status == SkillStatus.APPROVED
            and skill.last_health_status in {None, "healthy"}
        )

    def can_apply_system_command(self) -> bool:
        return self.flags.is_enabled("skills.system_command")

    def requires_human_review(self, skill: SkillRecord) -> bool:
        return skill.status in {SkillStatus.DRAFT, SkillStatus.PENDING_REVIEW, SkillStatus.DEGRADED}


@dataclass(slots=True)
class SkillHealthCheckResult:
    checked_at: datetime
    health: str
    issues: list[str] = field(default_factory=list)
    recommended_status: SkillStatus | None = None


@dataclass(slots=True)
class SkillHealthSweepResult:
    checked_count: int
    degraded_count: int
    results: list[tuple[SkillRecord, SkillHealthCheckResult]] = field(default_factory=list)


@dataclass(slots=True)
class SkillHealthCheckService:
    def run(
        self,
        skill: SkillRecord,
        *,
        observed_result: dict[str, Any] | None = None,
    ) -> SkillHealthCheckResult:
        checked_at = datetime.now(timezone.utc)
        issues: list[str] = []
        config = skill.health_check_config or {}
        strategy = skill.strategy or {}

        required_strategy_keys = config.get("required_strategy_keys") or []
        for key in required_strategy_keys:
            if key not in strategy:
                issues.append(f"missing_strategy_key:{key}")

        if not strategy:
            issues.append("missing_strategy")

        expected_status = config.get("expected_result_status")
        observed_status = observed_result.get("status") if observed_result else None
        if expected_status and observed_status and observed_status != expected_status:
            issues.append(f"unexpected_result_status:{observed_status}")

        score_threshold = config.get("minimum_overall_score")
        if score_threshold is not None and observed_result:
            score = observed_result.get("overall") or observed_result.get("score")
            if isinstance(score, (int, float)) and float(score) < float(score_threshold):
                issues.append(f"score_below_threshold:{score}")

        if skill.status == SkillStatus.DISABLED:
            health = "disabled"
            recommended_status = SkillStatus.DISABLED
        elif issues:
            severity = str(config.get("failure_severity") or "warning")
            health = "critical" if severity == "critical" else "warning"
            recommended_status = SkillStatus.DEGRADED if skill.status in {SkillStatus.APPROVED, SkillStatus.ACTIVE, SkillStatus.DEGRADED} else skill.status
        else:
            health = "healthy"
            recommended_status = skill.status

        skill.last_health_check = checked_at
        skill.last_health_status = health
        if recommended_status is not None:
            skill.status = recommended_status
        skill.updated_at = checked_at

        return SkillHealthCheckResult(
            checked_at=checked_at,
            health=health,
            issues=issues,
            recommended_status=recommended_status,
        )


@dataclass(slots=True)
class SkillHealthSweepService:
    checker: SkillHealthCheckService = field(default_factory=SkillHealthCheckService)

    def filter_skills(
        self,
        skills: list[SkillRecord],
        *,
        skill_ids: list[str] | None = None,
        statuses: list[str] | None = None,
        platform: str | None = None,
    ) -> list[SkillRecord]:
        normalized_ids = {item for item in (skill_ids or []) if item}
        normalized_statuses = {item.strip().lower() for item in (statuses or []) if item and item.strip()}
        normalized_platform = platform.strip().lower() if platform and platform.strip() else None

        filtered: list[SkillRecord] = []
        for skill in skills:
            if normalized_ids and skill.skill_id not in normalized_ids and getattr(skill, "id", None) not in normalized_ids:
                continue
            if normalized_statuses and str(skill.status).lower() not in normalized_statuses:
                continue
            if normalized_platform and skill.platform.strip().lower() != normalized_platform:
                continue
            filtered.append(skill)
        return filtered

    def run(
        self,
        skills: list[SkillRecord],
        *,
        observed_results_by_skill: dict[str, dict[str, Any]] | None = None,
    ) -> SkillHealthSweepResult:
        observed_results_by_skill = observed_results_by_skill or {}
        results: list[tuple[SkillRecord, SkillHealthCheckResult]] = []
        degraded_count = 0

        for skill in skills:
            observed_result = (
                observed_results_by_skill.get(skill.skill_id)
                or observed_results_by_skill.get(getattr(skill, "id", ""))
                or {}
            )
            result = self.checker.run(skill, observed_result=observed_result)
            if skill.status == SkillStatus.DEGRADED:
                degraded_count += 1
            results.append((skill, result))

        return SkillHealthSweepResult(
            checked_count=len(results),
            degraded_count=degraded_count,
            results=results,
        )
