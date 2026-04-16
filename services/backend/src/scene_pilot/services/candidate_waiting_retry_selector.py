from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class CandidateWaitingRetryPolicy:
    max_retries: int
    retry_after_hours: int
    close_after_hours: int


@dataclass(frozen=True, slots=True)
class CandidateWaitingRetryTarget:
    candidate_id: str
    current_status: str
    node_id: str
    node_label: str
    retry_policy: CandidateWaitingRetryPolicy
    current_retry_count: int = 0
    is_terminal: bool = False
    is_soft_terminal: bool = False
    is_transient: bool = False
    has_open_task: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_contacted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CandidateWaitingRetryAction:
    candidate_id: str
    current_status: str
    node_id: str
    node_label: str
    action_kind: str
    selected_task_type: str | None
    to_status: str | None
    current_retry_count: int
    next_retry_count: int | None
    hours_since_contact: float
    reason: str


def _normalize_datetime(value: datetime | None, *, now: datetime) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=now.tzinfo or timezone.utc)
    return value


def map_waiting_candidate_retry_task_type(target: CandidateWaitingRetryTarget) -> str | None:
    if target.current_status in {
        "outreach_sent",
        "resume_requested",
        "contact_requested",
        "interview_scheduled",
        "offer_sent",
    }:
        return "candidate_outreach"
    return None


def is_waiting_candidate_retry_eligible(
    target: CandidateWaitingRetryTarget,
    *,
    now: datetime | None = None,
) -> bool:
    current_time = now or datetime.now(timezone.utc)
    if not target.candidate_id or not target.current_status or not target.node_id:
        return False
    if target.is_terminal or target.is_soft_terminal or target.is_transient:
        return False
    if target.has_open_task:
        return False
    if target.retry_policy.max_retries < 0 or target.retry_policy.retry_after_hours <= 0 or target.retry_policy.close_after_hours <= 0:
        return False
    return _hours_since_contact(target, now=current_time) >= 0 and map_waiting_candidate_retry_task_type(target) is not None


def _hours_since_contact(target: CandidateWaitingRetryTarget, *, now: datetime) -> float:
    reference = (
        _normalize_datetime(target.last_contacted_at, now=now)
        or _normalize_datetime(target.updated_at, now=now)
        or _normalize_datetime(target.created_at, now=now)
        or now
    )
    return max((now - reference).total_seconds() / 3600.0, 0.0)


def select_waiting_candidate_retry_action(
    targets: list[CandidateWaitingRetryTarget],
    *,
    now: datetime | None = None,
) -> CandidateWaitingRetryAction | None:
    current_time = now or datetime.now(timezone.utc)
    ranked: list[tuple[tuple[int, float, int, str], CandidateWaitingRetryAction]] = []

    for target in targets:
        if not is_waiting_candidate_retry_eligible(target, now=current_time):
            continue

        hours_since_contact = round(_hours_since_contact(target, now=current_time), 4)
        policy = target.retry_policy
        action: CandidateWaitingRetryAction | None = None
        if target.current_retry_count >= policy.max_retries and hours_since_contact >= float(policy.close_after_hours):
            action = CandidateWaitingRetryAction(
                candidate_id=target.candidate_id,
                current_status=target.current_status,
                node_id=target.node_id,
                node_label=target.node_label,
                action_kind="close",
                selected_task_type=None,
                to_status="no_response",
                current_retry_count=target.current_retry_count,
                next_retry_count=None,
                hours_since_contact=hours_since_contact,
                reason="retry_limit_reached + close_window_elapsed",
            )
        elif target.current_retry_count < policy.max_retries and hours_since_contact >= float(policy.retry_after_hours):
            task_type = map_waiting_candidate_retry_task_type(target)
            if task_type is None:
                continue
            action = CandidateWaitingRetryAction(
                candidate_id=target.candidate_id,
                current_status=target.current_status,
                node_id=target.node_id,
                node_label=target.node_label,
                action_kind="retry",
                selected_task_type=task_type,
                to_status=None,
                current_retry_count=target.current_retry_count,
                next_retry_count=target.current_retry_count + 1,
                hours_since_contact=hours_since_contact,
                reason="retry_window_elapsed",
            )

        if action is None:
            continue

        ranked.append(
            (
                (
                    1 if action.action_kind == "close" else 0,
                    action.hours_since_contact,
                    action.current_retry_count,
                    target.candidate_id,
                ),
                action,
            )
        )

    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]
