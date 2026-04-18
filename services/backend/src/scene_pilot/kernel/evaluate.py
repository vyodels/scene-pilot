from __future__ import annotations

from scene_pilot.runtime.models import Deliberation, Effects, TickOutcome


def evaluate(deliberation: Deliberation, effects: Effects) -> TickOutcome:
    status = "complete" if deliberation.final_content else "continue"
    return TickOutcome(
        status=status,
        final_output=deliberation.final_content,
        effects=effects,
        metadata={"stop_reason": deliberation.stop_reason},
    )
