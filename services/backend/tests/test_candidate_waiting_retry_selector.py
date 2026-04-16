from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scene_pilot.services.candidate_waiting_retry_selector import (
    CandidateWaitingRetryAction,
    CandidateWaitingRetryPolicy,
    CandidateWaitingRetryTarget,
    is_waiting_candidate_retry_eligible,
    map_waiting_candidate_retry_task_type,
    select_waiting_candidate_retry_action,
)


def _target(
    candidate_id: str,
    current_status: str,
    *,
    node_id: str | None = None,
    node_label: str | None = None,
    max_retries: int = 2,
    retry_after_hours: int = 48,
    close_after_hours: int = 120,
    current_retry_count: int = 0,
    is_terminal: bool = False,
    is_soft_terminal: bool = False,
    is_transient: bool = False,
    has_open_task: bool = False,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    last_contacted_at: datetime | None = None,
) -> CandidateWaitingRetryTarget:
    return CandidateWaitingRetryTarget(
        candidate_id=candidate_id,
        current_status=current_status,
        node_id=node_id or current_status,
        node_label=node_label or current_status,
        retry_policy=CandidateWaitingRetryPolicy(
            max_retries=max_retries,
            retry_after_hours=retry_after_hours,
            close_after_hours=close_after_hours,
        ),
        current_retry_count=current_retry_count,
        is_terminal=is_terminal,
        is_soft_terminal=is_soft_terminal,
        is_transient=is_transient,
        has_open_task=has_open_task,
        created_at=created_at,
        updated_at=updated_at,
        last_contacted_at=last_contacted_at,
    )


def _assert_action(action: CandidateWaitingRetryAction | None, *, kind: str, candidate_id: str) -> CandidateWaitingRetryAction:
    assert action is not None
    assert action.action_kind == kind
    assert action.candidate_id == candidate_id
    return action


def test_selector_returns_retry_action_when_wait_window_elapsed() -> None:
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    action = select_waiting_candidate_retry_action(
        [
            _target(
                "candidate-outreach-retry",
                "outreach_sent",
                retry_after_hours=72,
                last_contacted_at=now - timedelta(hours=96),
            )
        ],
        now=now,
    )

    resolved = _assert_action(action, kind="retry", candidate_id="candidate-outreach-retry")
    assert resolved.selected_task_type == "candidate_outreach"
    assert resolved.next_retry_count == 1
    assert resolved.reason == "retry_window_elapsed"


def test_selector_prioritizes_close_when_retry_limit_is_exhausted() -> None:
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    action = select_waiting_candidate_retry_action(
        [
            _target(
                "candidate-close",
                "resume_requested",
                current_retry_count=2,
                max_retries=2,
                retry_after_hours=48,
                close_after_hours=96,
                last_contacted_at=now - timedelta(hours=120),
            ),
            _target(
                "candidate-still-retry",
                "outreach_sent",
                current_retry_count=1,
                max_retries=2,
                retry_after_hours=48,
                close_after_hours=120,
                last_contacted_at=now - timedelta(hours=60),
            ),
        ],
        now=now,
    )

    resolved = _assert_action(action, kind="close", candidate_id="candidate-close")
    assert resolved.to_status == "no_response"
    assert resolved.selected_task_type is None
    assert resolved.reason == "retry_limit_reached + close_window_elapsed"


def test_selector_skips_soft_terminal_or_open_task_targets() -> None:
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    no_response_target = _target(
        "candidate-no-response",
        "no_response",
        is_soft_terminal=True,
        last_contacted_at=now - timedelta(hours=240),
    )
    open_task_target = _target(
        "candidate-blocked",
        "contact_requested",
        has_open_task=True,
        last_contacted_at=now - timedelta(hours=72),
    )

    assert is_waiting_candidate_retry_eligible(no_response_target, now=now) is False
    assert is_waiting_candidate_retry_eligible(open_task_target, now=now) is False
    assert select_waiting_candidate_retry_action([no_response_target, open_task_target], now=now) is None


def test_waiting_retry_task_mapping_stays_generic_outbound_follow_up() -> None:
    assert map_waiting_candidate_retry_task_type(_target("candidate-a", "resume_requested")) == "candidate_outreach"
    assert map_waiting_candidate_retry_task_type(_target("candidate-b", "contact_requested")) == "candidate_outreach"
