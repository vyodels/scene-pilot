from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scene_pilot.services.candidate_progression_selector import (
    CandidateProgressionTarget,
    is_candidate_progression_eligible,
    map_candidate_progression_task_type,
    select_next_candidate_progression,
)


def _target(
    candidate_id: str,
    current_status: str,
    *,
    node_id: str | None = None,
    node_label: str | None = None,
    phase: str = "A",
    waiting_party: str = "AI",
    sort_order: int = 10,
    effective_execution_mode: str = "none",
    locked: bool = False,
    ai_scores: dict[str, object] | None = None,
    is_terminal: bool = False,
    is_soft_terminal: bool = False,
    is_transient: bool = False,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    last_contacted_at: datetime | None = None,
    cooldown_until: datetime | None = None,
    has_open_task: bool = False,
) -> CandidateProgressionTarget:
    return CandidateProgressionTarget(
        candidate_id=candidate_id,
        current_status=current_status,
        node_id=node_id or current_status,
        node_label=node_label or current_status,
        phase=phase,
        default_waiting_party=waiting_party,
        sort_order=sort_order,
        ai_scores=dict(ai_scores or {"overall": 80}),
        is_terminal=is_terminal,
        is_soft_terminal=is_soft_terminal,
        is_transient=is_transient,
        effective_execution_mode=effective_execution_mode,
        locked=locked,
        created_at=created_at,
        updated_at=updated_at,
        last_contacted_at=last_contacted_at,
        cooldown_until=cooldown_until,
        has_open_task=has_open_task,
    )


def test_selector_prefers_highest_composite_candidate() -> None:
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    selected = select_next_candidate_progression(
        [
            _target(
                "candidate-high-wait",
                "outreach_pending",
                phase="B",
                waiting_party="AI",
                sort_order=50,
                effective_execution_mode="ai_auto",
                ai_scores={"overall": 92},
                created_at=now - timedelta(days=3),
                updated_at=now - timedelta(hours=36),
            ),
            _target(
                "candidate-late-stage",
                "offline_scoring",
                phase="D",
                waiting_party="AI",
                sort_order=110,
                effective_execution_mode="ai_auto",
                ai_scores={"overall": 98},
                created_at=now - timedelta(days=2),
                updated_at=now - timedelta(hours=1),
            ),
        ],
        now=now,
    )

    assert selected is not None
    assert selected.candidate_id == "candidate-high-wait"
    assert selected.selected_task_type == "candidate_outreach"
    assert selected.score_breakdown.total > 0
    assert selected.reason == "high_ai_score + mid_stage + long_wait"


def test_interview_pending_ai_auto_can_enter_autonomous_pool() -> None:
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    target = _target(
        "candidate-interview-pending",
        "interview_pending",
        phase="G",
        waiting_party="HUMAN",
        sort_order=190,
        effective_execution_mode="ai_auto",
        ai_scores={"overall": 88},
        updated_at=now - timedelta(hours=12),
    )

    assert is_candidate_progression_eligible(target, now=now) is True
    assert map_candidate_progression_task_type(target) == "candidate_outreach"


def test_offline_scoring_human_required_cannot_enter_autonomous_pool() -> None:
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    target = _target(
        "candidate-offline-scoring",
        "offline_scoring",
        phase="D",
        waiting_party="AI",
        sort_order=110,
        effective_execution_mode="human_required",
        ai_scores={"overall": 95},
        updated_at=now - timedelta(hours=18),
    )

    assert is_candidate_progression_eligible(target, now=now) is False
    assert map_candidate_progression_task_type(target) is None


def test_offer_pending_locked_cannot_enter_autonomous_pool() -> None:
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    target = _target(
        "candidate-offer-pending",
        "offer_pending",
        phase="H",
        waiting_party="HUMAN",
        sort_order=240,
        effective_execution_mode="human_required",
        locked=True,
        ai_scores={"overall": 97},
        updated_at=now - timedelta(hours=24),
    )

    assert is_candidate_progression_eligible(target, now=now) is False
    assert map_candidate_progression_task_type(target) is None


def test_selector_returns_none_when_all_targets_are_ineligible() -> None:
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    selected = select_next_candidate_progression(
        [
            _target(
                "candidate-terminal",
                "archived",
                phase="Z",
                sort_order=280,
                is_terminal=True,
                updated_at=now - timedelta(hours=6),
            ),
            _target(
                "candidate-waiting",
                "resume_requested",
                phase="C",
                waiting_party="CANDIDATE",
                sort_order=90,
                updated_at=now - timedelta(hours=18),
            ),
        ],
        now=now,
    )

    assert selected is None


def test_soft_terminal_cooldown_candidate_is_not_eligible_for_autonomous_progression() -> None:
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    target = _target(
        "candidate-cooldown",
        "cooldown",
        phase="Z",
        waiting_party="AI",
        sort_order=280,
        effective_execution_mode="ai_auto",
        is_soft_terminal=True,
        updated_at=now - timedelta(days=30),
    )

    assert is_candidate_progression_eligible(target, now=now) is False
    assert map_candidate_progression_task_type(target) is None


def test_selector_skips_open_task_and_prefers_next_candidate() -> None:
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    selected = select_next_candidate_progression(
        [
            _target(
                "candidate-open-task",
                "discovered",
                sort_order=10,
                ai_scores={"overall": 95},
                updated_at=now - timedelta(hours=10),
                has_open_task=True,
            ),
            _target(
                "candidate-fallback",
                "discovered",
                sort_order=10,
                ai_scores={"overall": 78},
                updated_at=now - timedelta(hours=12),
            ),
        ],
        now=now,
    )

    assert selected is not None
    assert selected.candidate_id == "candidate-fallback"
