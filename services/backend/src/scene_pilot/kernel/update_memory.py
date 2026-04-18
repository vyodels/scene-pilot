from __future__ import annotations

from typing import Any

from scene_pilot.runtime.models import Deliberation


def update_memory(deliberation: Deliberation, memory_service: Any | None = None) -> list[dict[str, Any]]:
    if memory_service is None:
        return []
    writings: list[dict[str, Any]] = []
    for result in deliberation.tool_results:
        if result.tool_name == "record_learning" and not result.is_error:
            writings.append({"tool_name": result.tool_name, "arguments": dict(result.arguments or {})})
    return writings
