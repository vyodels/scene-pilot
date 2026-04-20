from __future__ import annotations

from scene_pilot.agents.autonomous import _resolve_turn_limits
from scene_pilot.models.domain import GoalSpec
from scene_pilot.runtime.limits import TurnLimits


def test_autonomous_turn_limits_default_round_budget_is_expanded() -> None:
    limits = TurnLimits()

    assert limits.max_rounds_per_turn == 800


def test_autonomous_turn_limits_accept_goal_trial_budget_override() -> None:
    goal = GoalSpec(trial_budget={"max_rounds_per_turn": 32, "turn_timeout_seconds": 240})

    resolved = _resolve_turn_limits(TurnLimits(), goal)

    assert resolved.max_rounds_per_turn == 32
    assert resolved.turn_timeout_seconds == 240


def test_autonomous_turn_limits_ignore_invalid_goal_trial_budget_values() -> None:
    goal = GoalSpec(trial_budget={"max_rounds_per_turn": "bad", "turn_timeout_seconds": -10})

    resolved = _resolve_turn_limits(TurnLimits(), goal)

    assert resolved.max_rounds_per_turn == 800
    assert resolved.turn_timeout_seconds == 120
