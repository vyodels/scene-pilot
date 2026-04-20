from __future__ import annotations

from scene_pilot.runtime.limits import RoundLimits
from scene_pilot.runtime.models import Deliberation, Effects, RoundOutcome
from scene_pilot.runtime.result_semantics import infer_non_success_round_outcome


def evaluate(deliberation: Deliberation, effects: Effects, *, limits: RoundLimits | None = None) -> RoundOutcome:
    active_limits = limits or RoundLimits()
    metadata = {"stop_reason": deliberation.stop_reason}
    if deliberation.metadata.get("cancelled"):
        return RoundOutcome(
            status="cancelled",
            gate_signal="paused",
            final_output=deliberation.final_content or None,
            tool_calls=list(deliberation.tool_calls),
            tool_results=list(deliberation.tool_results),
            effects=effects,
            metadata=metadata,
        )
    if deliberation.metadata.get("pending_tool_calls") or deliberation.stop_reason == "wait_human":
        return RoundOutcome(
            status="wait_human",
            gate_signal="wait_human",
            final_output=deliberation.final_content or None,
            tool_calls=list(deliberation.tool_calls),
            tool_results=list(deliberation.tool_results),
            effects=effects,
            metadata=metadata,
        )
    if deliberation.usage.total_tokens > active_limits.token_budget:
        return RoundOutcome(
            status="continue",
            gate_signal="budget_exhausted",
            final_output=deliberation.final_content or None,
            tool_calls=list(deliberation.tool_calls),
            tool_results=list(deliberation.tool_results),
            effects=effects,
            metadata=metadata,
        )
    if deliberation.tool_calls:
        return RoundOutcome(
            status="continue",
            gate_signal="continue",
            final_output=deliberation.final_content or None,
            tool_calls=list(deliberation.tool_calls),
            tool_results=list(deliberation.tool_results),
            effects=effects,
            metadata=metadata,
        )
    inferred_non_success = infer_non_success_round_outcome(deliberation.final_content)
    if inferred_non_success is not None:
        status, gate_signal = inferred_non_success
        return RoundOutcome(
            status=status,
            gate_signal=gate_signal,
            final_output=deliberation.final_content or None,
            tool_calls=list(deliberation.tool_calls),
            tool_results=list(deliberation.tool_results),
            effects=effects,
            metadata=metadata,
        )
    return RoundOutcome(
        status="complete" if deliberation.final_content else "continue",
        gate_signal="goal_done" if deliberation.final_content else "continue",
        final_output=deliberation.final_content or None,
        tool_calls=list(deliberation.tool_calls),
        tool_results=list(deliberation.tool_results),
        effects=effects,
        metadata=metadata,
    )
