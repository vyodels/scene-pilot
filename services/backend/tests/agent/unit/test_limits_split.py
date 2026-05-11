from __future__ import annotations

from dataclasses import fields

from recruit_agent.product_adapters.limits import SceneExecutionLimits, TurnLimits


def test_scene_execution_and_turn_limits_do_not_leak_each_others_fields() -> None:
    scene_fields = {field.name for field in fields(SceneExecutionLimits)}
    turn_fields = {field.name for field in fields(TurnLimits)}

    assert "max_llm_invocations" in scene_fields
    assert "turn_timeout_seconds" not in scene_fields

    assert "min_wakeup_delay_seconds" not in turn_fields
    assert "max_llm_invocations" in turn_fields
