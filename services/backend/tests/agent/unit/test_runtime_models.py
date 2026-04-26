from __future__ import annotations

from dataclasses import asdict
import json

from recruit_agent.runtime.limits import RoundLimits, TurnLimits
from recruit_agent.runtime.models import CancellationToken, FairnessState, InputEnvelope, Observation, ToolExecutionResult


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
        input=InputEnvelope(input_message="hello"),
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
        "input": {"history_messages": [], "input_message": "hello", "seed_tool_calls": []},
    }


def test_fairness_state_uses_scope_not_business_specific_fields() -> None:
    fairness = FairnessState(last_scope_ref="scope-1", same_scope_turns=2, soft_limit=3, hard_limit=5)

    payload = asdict(fairness)
    assert payload["last_scope_ref"] == "scope-1"
    assert payload["same_scope_turns"] == 2
    assert "last_jd_id" not in payload
    assert "same_jd_turns" not in payload


def test_cancellation_token_records_reason() -> None:
    token = CancellationToken()

    assert token.cancelled is False
    token.cancel("operator_requested")

    assert token.cancelled is True
    assert token.reason == "operator_requested"


def test_runtime_limits_split_between_round_and_turn() -> None:
    round_limits = RoundLimits()
    turn_limits = TurnLimits()

    assert round_limits.token_budget is None
    assert round_limits.max_tool_roundtrips > 0
    assert round_limits.max_wakeup_delay_seconds >= round_limits.min_wakeup_delay_seconds
    assert turn_limits.max_rounds_per_turn is None
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
