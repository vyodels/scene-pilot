from __future__ import annotations

from dataclasses import asdict

from scene_pilot.runtime.limits import RuntimeLimits
from scene_pilot.runtime.models import CancellationToken, FairnessState, Observation


def test_observation_stays_generic() -> None:
    observation = Observation(
        world_snapshot={"summary": "coarse state"},
        scope_ref="candidate-123",
        scope_kind="candidate",
        recent_events=[{"event_type": "candidate.updated"}],
        available_tools=["read_memory"],
        available_skills=["site_navigation"],
        available_mcps=["browser"],
        hash="obs-1",
    )

    assert asdict(observation) == {
        "world_snapshot": {"summary": "coarse state"},
        "scope_ref": "candidate-123",
        "scope_kind": "candidate",
        "recent_events": [{"event_type": "candidate.updated"}],
        "available_tools": ["read_memory"],
        "available_skills": ["site_navigation"],
        "available_mcps": ["browser"],
        "hash": "obs-1",
    }


def test_fairness_state_uses_scope_not_business_specific_fields() -> None:
    fairness = FairnessState(last_scope_ref="scope-1", same_scope_ticks=2, soft_limit=3, hard_limit=5)

    payload = asdict(fairness)
    assert payload["last_scope_ref"] == "scope-1"
    assert payload["same_scope_ticks"] == 2
    assert "last_jd_id" not in payload
    assert "same_jd_ticks" not in payload


def test_cancellation_token_records_reason() -> None:
    token = CancellationToken()

    assert token.cancelled is False
    token.cancel("operator_requested")

    assert token.cancelled is True
    assert token.reason == "operator_requested"


def test_runtime_limits_provide_default_guardrails() -> None:
    limits = RuntimeLimits()

    assert limits.max_turns > 0
    assert limits.token_budget > 0
    assert limits.max_tool_roundtrips > 0
    assert limits.max_wakeup_delay_seconds >= limits.min_wakeup_delay_seconds
