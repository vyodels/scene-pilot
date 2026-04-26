from __future__ import annotations

from recruit_agent.agents.autonomous import _resolve_turn_limits
from recruit_agent.models.domain import GoalSpec
from recruit_agent.runtime.limits import TurnLimits


def test_autonomous_turn_limits_default_round_wall_clock_and_token_budgets_are_unlimited() -> None:
    limits = TurnLimits()

    assert limits.max_rounds_per_turn is None
    assert limits.turn_timeout_seconds is None
    assert limits.token_budget is None


def test_autonomous_turn_limits_accept_goal_trial_budget_override() -> None:
    goal = GoalSpec(trial_budget={"max_rounds_per_turn": 32, "turn_timeout_seconds": 240, "token_budget": 99_999})

    resolved = _resolve_turn_limits(TurnLimits(), goal)

    assert resolved.max_rounds_per_turn == 32
    assert resolved.turn_timeout_seconds == 240
    assert resolved.token_budget == 99_999


def test_autonomous_turn_limits_ignore_invalid_goal_trial_budget_values() -> None:
    goal = GoalSpec(trial_budget={"max_rounds_per_turn": "bad", "turn_timeout_seconds": -10, "token_budget": "bad"})

    resolved = _resolve_turn_limits(TurnLimits(), goal)

    assert resolved.max_rounds_per_turn is None
    assert resolved.turn_timeout_seconds is None
    assert resolved.token_budget is None


def test_autonomous_turn_limits_allow_explicit_unlimited_goal_trial_budget_values() -> None:
    defaults = TurnLimits(max_rounds_per_turn=8, turn_timeout_seconds=120, token_budget=1_000)
    goal = GoalSpec(trial_budget={"max_rounds_per_turn": 0, "turn_timeout_seconds": "unlimited", "token_budget": "none"})

    resolved = _resolve_turn_limits(defaults, goal)

    assert resolved.max_rounds_per_turn is None
    assert resolved.turn_timeout_seconds is None
    assert resolved.token_budget is None
