from __future__ import annotations

import json
from typing import Any

from scene_pilot.plugins.host import PluginHost
from scene_pilot.runtime.models import GoalRef, Message, Observation
from scene_pilot.runtime.tools import ToolRegistry


def assemble_messages(
    goal: GoalRef,
    observation: Observation,
    *,
    plugin_host: PluginHost | None = None,
    memory_service: Any | None = None,
    tool_registry: ToolRegistry | None = None,
) -> list[Message]:
    persona_fragments = plugin_host.collect_persona_fragments() if plugin_host is not None else []
    memory_entries = []
    if memory_service is not None and observation.scope_kind and observation.scope_ref:
        memory_entries = memory_service.read(scope_kind=observation.scope_kind, scope_ref=observation.scope_ref, limit=5)

    system_parts = [goal.goal_text or goal.title or "Complete the assigned goal."]
    if persona_fragments:
        system_parts.append("\n".join(persona_fragments))
    if tool_registry is not None:
        system_parts.append(f"Available tools: {', '.join(sorted(tool_registry.tools.keys()))}")

    user_payload = {
        "goal_id": goal.goal_id,
        "scope_kind": goal.scope_kind,
        "scope_ref": goal.scope_ref,
        "world_snapshot": observation.world_snapshot,
        "recent_events": observation.recent_events,
        "memory": memory_entries,
    }
    return [
        Message(role="system", content="\n\n".join(part for part in system_parts if part)),
        Message(role="user", content=json.dumps(user_payload, ensure_ascii=False, default=str)),
    ]
