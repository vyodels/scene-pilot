from __future__ import annotations

from scene_pilot.runtime.models import Deliberation, Effects, WakeupRequest


def act(deliberation: Deliberation) -> Effects:
    effects = Effects()
    for result in deliberation.tool_results:
        if result.tool_name == "enqueue_follow_up" and not result.is_error:
            effects.follow_ups.append(dict(result.arguments or {}))
        if result.tool_name == "schedule_self_wakeup" and not result.is_error:
            delay_seconds = int(result.arguments.get("delay_seconds") or 0)
            reason = str(result.arguments.get("reason") or "tool_request")
            effects.wakeup_request = WakeupRequest(delay_seconds=delay_seconds, reason=reason)
    return effects
