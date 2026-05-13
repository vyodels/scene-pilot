from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class ApplicationProgressionTarget:
    application_id: str
    current_status: str
    node_id: str
    node_label: str
    phase: str
    default_waiting_party: str
    sort_order: int
    ai_scores: dict[str, Any]
    is_terminal: bool = False
    is_soft_terminal: bool = False
    is_transient: bool = False
    effective_execution_mode: str = "none"
    locked: bool = False
    created_at: int | datetime | None = None
    updated_at: int | datetime | None = None
    last_contacted_at: int | datetime | None = None
    cooldown_until: int | datetime | None = None
    has_open_task: bool = False


@dataclass(frozen=True, slots=True)
class ApplicationProgressionScoreBreakdown:
    ai_score: float
    stage_depth: float
    waiting_hours: float
    total: float
    ai_factor: float
    stage_factor: float
    waiting_factor: float


@dataclass(frozen=True, slots=True)
class ApplicationProgressionSelection:
    application_id: str
    current_status: str
    node_id: str
    node_label: str
    selected_task_type: str
    score_breakdown: ApplicationProgressionScoreBreakdown
    reason: str


def _normalize_datetime(value: int | float | str | datetime | None, *, now: datetime) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=now.tzinfo or timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=now.tzinfo or timezone.utc)
        return parsed
    if value.tzinfo is None:
        return value.replace(tzinfo=now.tzinfo or timezone.utc)
    return value


def extract_candidate_ai_score(ai_scores: dict[str, Any] | None) -> float:
    payload = dict(ai_scores or {})
    for key in ("overall", "score_total", "score", "total"):
        raw_value = payload.get(key)
        if isinstance(raw_value, (int, float)):
            return max(min(float(raw_value), 100.0), 0.0)
        text_value = str(raw_value or "").strip()
        if not text_value:
            continue
        try:
            return max(min(float(text_value), 100.0), 0.0)
        except ValueError:
            continue

    decision = str(payload.get("decision") or payload.get("status") or "").strip().lower()
    if decision in {"pass", "strong_pass", "advance"}:
        return 80.0
    if decision in {"reject", "fail", "no_pass"}:
        return 20.0
    return 50.0


def map_application_progression_task_type(target: ApplicationProgressionTarget) -> str | None:
    if not target.current_status or not target.node_id:
        return None
    if target.is_terminal or target.is_soft_terminal:
        return None
    if target.locked:
        return None
    if target.effective_execution_mode == "human_required":
        return None
    waiting_party = str(target.default_waiting_party or "").strip().upper()
    if waiting_party in {"CANDIDATE", "HUMAN"} and target.effective_execution_mode != "ai_auto":
        return None

    explicit_map = {
        "discovered": "candidate_probe",
        "online_resume_fetching": "candidate_probe",
        "online_resume_acquired": "candidate_probe",
        "online_resume_passed": "resume_collection",
        "offline_resume_fetching": "resume_collection",
        "offline_resume_acquired": "candidate_scoring",
        "offline_resume_passed": "candidate_scoring",
        "human_screening_passed": "candidate_outreach",
        "profile_ready": "candidate_outreach",
        "interview_passed": "candidate_outreach",
    }
    mapped = explicit_map.get(target.current_status)
    if mapped:
        return mapped

    phase = str(target.phase or "").strip().upper()
    if phase == "A":
        return "candidate_probe"
    if phase in {"E", "F", "G", "H"}:
        return "candidate_outreach"
    if phase == "B":
        return "candidate_probe"
    if phase == "D":
        return "resume_collection"
    if phase == "I":
        return "candidate_archive"
    return None


def is_application_progression_eligible(
    target: ApplicationProgressionTarget,
    *,
    now: datetime | None = None,
) -> bool:
    current_time = now or datetime.now(timezone.utc)
    if not target.application_id or not target.current_status or not target.node_id:
        return False
    if target.has_open_task:
        return False
    if target.is_terminal or target.is_soft_terminal:
        return False
    if target.locked:
        return False
    if target.effective_execution_mode == "human_required":
        return False
    waiting_party = str(target.default_waiting_party or "").strip().upper()
    if waiting_party in {"CANDIDATE", "HUMAN"} and target.effective_execution_mode != "ai_auto":
        return False

    cooldown_until = _normalize_datetime(target.cooldown_until, now=current_time)
    if cooldown_until is not None and cooldown_until > current_time:
        return False

    return map_application_progression_task_type(target) is not None


def _stage_depth_score(target: ApplicationProgressionTarget, *, max_sort_order: int) -> float:
    current_order = max(int(target.sort_order or 0), 0)
    baseline = max(max_sort_order, 1)
    normalized = max(min(current_order / baseline, 1.0), 0.0)
    return round(normalized * 100.0, 4)


def _waiting_hours(target: ApplicationProgressionTarget, *, now: datetime) -> float:
    timestamps = [
        _normalize_datetime(target.created_at, now=now),
        _normalize_datetime(target.updated_at, now=now),
        _normalize_datetime(target.last_contacted_at, now=now),
    ]
    reference_time = max([value for value in timestamps if value is not None] or [now])
    elapsed_seconds = max((now - reference_time).total_seconds(), 0.0)
    return round(elapsed_seconds / 3600.0, 4)


def _score_breakdown(
    target: ApplicationProgressionTarget,
    *,
    max_sort_order: int,
    now: datetime,
) -> ApplicationProgressionScoreBreakdown:
    ai_score = extract_candidate_ai_score(target.ai_scores)
    stage_depth = _stage_depth_score(target, max_sort_order=max_sort_order)
    waiting_hours = _waiting_hours(target, now=now)
    ai_factor = 0.5 + (ai_score / 100.0)
    stage_factor = 0.5 + (stage_depth / 100.0)
    waiting_factor = 1.0 + min(waiting_hours / 24.0, 1.0)
    total = round(ai_factor * stage_factor * waiting_factor, 4)
    return ApplicationProgressionScoreBreakdown(
        ai_score=round(ai_score, 4),
        stage_depth=round(stage_depth, 4),
        waiting_hours=waiting_hours,
        total=total,
        ai_factor=round(ai_factor, 4),
        stage_factor=round(stage_factor, 4),
        waiting_factor=round(waiting_factor, 4),
    )


def _selection_reason(*, score_breakdown: ApplicationProgressionScoreBreakdown, current_status: str) -> str:
    reason_parts: list[str] = []
    if score_breakdown.ai_score >= 85:
        reason_parts.append("high_ai_score")
    elif score_breakdown.ai_score >= 70:
        reason_parts.append("solid_ai_score")
    else:
        reason_parts.append("fallback_ai_signal")

    if score_breakdown.stage_depth >= 70:
        reason_parts.append("late_stage")
    elif score_breakdown.stage_depth >= 35:
        reason_parts.append("mid_stage")
    else:
        reason_parts.append("early_stage")

    if score_breakdown.waiting_hours >= 24:
        reason_parts.append("long_wait")
    elif score_breakdown.waiting_hours >= 4:
        reason_parts.append("stale_wait")
    else:
        reason_parts.append("fresh_signal")

    return " + ".join(reason_parts)


def select_next_application_progression(
    targets: list[ApplicationProgressionTarget],
    *,
    now: datetime | None = None,
) -> ApplicationProgressionSelection | None:
    current_time = now or datetime.now(timezone.utc)
    eligible_targets = [target for target in targets if is_application_progression_eligible(target, now=current_time)]
    if not eligible_targets:
        return None

    max_sort_order = max(
        [
            int(target.sort_order or 0)
            for target in eligible_targets
        ]
        or [1]
    )

    ranked: list[tuple[tuple[float, float, float, float, str], ApplicationProgressionSelection]] = []
    for target in eligible_targets:
        task_type = map_application_progression_task_type(target)
        if task_type is None:
            continue
        score_breakdown = _score_breakdown(target, max_sort_order=max_sort_order, now=current_time)
        updated_at = _normalize_datetime(target.updated_at, now=current_time) or current_time
        selection = ApplicationProgressionSelection(
            application_id=target.application_id,
            current_status=target.current_status,
            node_id=target.node_id,
            node_label=target.node_label,
            selected_task_type=task_type,
            score_breakdown=score_breakdown,
            reason=_selection_reason(score_breakdown=score_breakdown, current_status=target.current_status),
        )
        ranked.append(
            (
                (
                    score_breakdown.total,
                    score_breakdown.stage_depth,
                    score_breakdown.waiting_hours,
                    -updated_at.timestamp(),
                    target.application_id,
                ),
                selection,
            )
        )

    if not ranked:
        return None

    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]
