from __future__ import annotations

from recruit_agent.services.evolution import build_skill_distill_review_payload


def test_skill_distill_review_payload_uses_run_fields() -> None:
    payload = build_skill_distill_review_payload(
        run_id="run-1",
        run_type="candidate_discovery",
        run_kind="candidate_discovery",
        engine_output_count=2,
        final_output="completed",
        tool_activity=[],
        event_outline=[],
    )

    assert payload["run_id"] == "run-1"
    assert payload["run_kind"] == "candidate_discovery"
