from __future__ import annotations

from dataclasses import fields

from recruit_agent.runtime.limits import RoundLimits, TurnLimits


def test_round_and_turn_limits_do_not_leak_each_others_fields() -> None:
    round_fields = {field.name for field in fields(RoundLimits)}
    turn_fields = {field.name for field in fields(TurnLimits)}

    assert "max_rounds_per_turn" not in round_fields
    assert "turn_timeout_seconds" not in round_fields
    assert "max_tool_roundtrips" in round_fields

    assert "max_tool_roundtrips" not in turn_fields
    assert "min_wakeup_delay_seconds" not in turn_fields
    assert "max_rounds_per_turn" in turn_fields
