from __future__ import annotations

import json

from recruit_agent.product_adapters.limits import SceneExecutionLimits, TurnLimits
from recruit_agent.capabilities.tools import ToolExecutionResult


def test_product_limits_split_between_scene_execution_and_turn() -> None:
    scene_limits = SceneExecutionLimits()
    turn_limits = TurnLimits()

    assert scene_limits.token_budget is None
    assert scene_limits.max_llm_invocations > 0
    assert scene_limits.max_wakeup_delay_seconds >= scene_limits.min_wakeup_delay_seconds
    assert turn_limits.max_llm_invocations is None
    assert turn_limits.turn_timeout_seconds is None
    assert turn_limits.token_budget is None


def test_tool_execution_result_message_content_uses_raw_serialized_output() -> None:
    output = {
        "display_label": "JD Detail",
        "environment_kind": "job_detail",
        "resource_locator": "https://example.test/jobs/1",
        "observed_entities": [{"kind": "candidate", "name": "Alice"}],
        "action_hints": [{"kind": "button", "label": "立即沟通"}],
        "runtime_metadata": {"viewport": {"width": 1440, "height": 900}},
    }

    result = ToolExecutionResult(tool_name="browser_snapshot", output=output)

    assert result.to_message_content() == json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)
