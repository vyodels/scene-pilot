from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class ApplicationWaitingRetryPolicy:
    max_retries: int
    retry_after_hours: int
    close_after_hours: int


@dataclass(frozen=True, slots=True)
class ApplicationWaitingRetryTarget:
    application_id: str
    current_status: str
    node_id: str
    node_label: str
    retry_policy: ApplicationWaitingRetryPolicy
    current_retry_count: int = 0
    is_terminal: bool = False
    is_soft_terminal: bool = False
    is_transient: bool = False
    has_open_task: bool = False
    created_at: int | datetime | None = None
    updated_at: int | datetime | None = None
    last_contacted_at: int | datetime | None = None


@dataclass(frozen=True, slots=True)
class ApplicationWaitingRetryAction:
    application_id: str
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


def map_waiting_application_retry_task_type(target: ApplicationWaitingRetryTarget) -> str | None:
    if target.current_status in {
        "offline_resume_fetching",
        "interview_scheduled",
        "offer_sent",
    }:
        return "candidate_outreach"
    return None


def is_waiting_candidate_retry_eligible(
    target: ApplicationWaitingRetryTarget,
    *,
    now: datetime | None = None,
) -> bool:
    current_time = now or datetime.now(timezone.utc)
    if not target.application_id or not target.current_status or not target.node_id:
        return False
    if target.is_terminal or target.is_soft_terminal:
        return False
    if target.has_open_task:
        return False
    if target.retry_policy.max_retries < 0 or target.retry_policy.retry_after_hours <= 0 or target.retry_policy.close_after_hours <= 0:
        return False
    return _hours_since_contact(target, now=current_time) >= 0 and map_waiting_application_retry_task_type(target) is not None


def _hours_since_contact(target: ApplicationWaitingRetryTarget, *, now: datetime) -> float:
    reference = (
        _normalize_datetime(target.last_contacted_at, now=now)
        or _normalize_datetime(target.updated_at, now=now)
        or _normalize_datetime(target.created_at, now=now)
        or now
    )
    return max((now - reference).total_seconds() / 3600.0, 0.0)


def select_waiting_application_retry_action(
    targets: list[ApplicationWaitingRetryTarget],
    *,
    now: datetime | None = None,
) -> ApplicationWaitingRetryAction | None:
    current_time = now or datetime.now(timezone.utc)
    ranked: list[tuple[tuple[int, float, int, str], ApplicationWaitingRetryAction]] = []

    for target in targets:
        if not is_waiting_candidate_retry_eligible(target, now=current_time):
            continue

        hours_since_contact = round(_hours_since_contact(target, now=current_time), 4)
        policy = target.retry_policy
        action: ApplicationWaitingRetryAction | None = None
        if target.current_retry_count >= policy.max_retries and hours_since_contact >= float(policy.close_after_hours):
            action = ApplicationWaitingRetryAction(
                application_id=target.application_id,
                current_status=target.current_status,
                node_id=target.node_id,
                node_label=target.node_label,
                action_kind="close",
                selected_task_type=None,
                to_status="exception_closed",
                current_retry_count=target.current_retry_count,
                next_retry_count=None,
                hours_since_contact=hours_since_contact,
                reason="retry_limit_reached + close_window_elapsed",
            )
        elif target.current_retry_count < policy.max_retries and hours_since_contact >= float(policy.retry_after_hours):
            task_type = map_waiting_application_retry_task_type(target)
            if task_type is None:
                continue
            action = ApplicationWaitingRetryAction(
                application_id=target.application_id,
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
                    target.application_id,
                ),
                action,
            )
        )

    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]
