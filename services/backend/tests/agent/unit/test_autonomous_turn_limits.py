from __future__ import annotations

from recruit_agent.agents.autonomous import _resolve_turn_limits
from recruit_agent.product_adapters.limits import TurnLimits


def test_autonomous_turn_limits_default_invocation_wall_clock_and_token_budgets_are_unlimited() -> None:
    limits = TurnLimits()

    assert limits.max_llm_invocations is None
    assert limits.turn_timeout_seconds is None
    assert limits.token_budget is None


def test_autonomous_turn_limits_accept_run_trial_budget_override() -> None:
    trial_budget = {"max_llm_invocations": 32, "turn_timeout_seconds": 240, "token_budget": 99_999}

    resolved = _resolve_turn_limits(TurnLimits(), trial_budget)

    assert resolved.max_llm_invocations == 32
    assert resolved.turn_timeout_seconds == 240
    assert resolved.token_budget == 99_999


def test_autonomous_turn_limits_ignore_invalid_run_trial_budget_values() -> None:
    trial_budget = {"max_llm_invocations": "bad", "turn_timeout_seconds": -10, "token_budget": "bad"}

    resolved = _resolve_turn_limits(TurnLimits(), trial_budget)

    assert resolved.max_llm_invocations is None
    assert resolved.turn_timeout_seconds is None
    assert resolved.token_budget is None


def test_autonomous_turn_limits_allow_explicit_unlimited_run_trial_budget_values() -> None:
    defaults = TurnLimits(max_llm_invocations=8, turn_timeout_seconds=120, token_budget=1_000)
    trial_budget = {"max_llm_invocations": 0, "turn_timeout_seconds": "unlimited", "token_budget": "none"}

    resolved = _resolve_turn_limits(defaults, trial_budget)

    assert resolved.max_llm_invocations is None
    assert resolved.turn_timeout_seconds is None
    assert resolved.token_budget is None
