from __future__ import annotations

from functools import lru_cache
import json
from typing import Any

from scene_pilot.asset_paths import prompt_path
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
    scope_memory_entries = []
    global_memory_entries = []
    if memory_service is not None and observation.scope_kind and observation.scope_ref:
        try:
            scope_memory_entries = memory_service.read(scope_kind=observation.scope_kind, scope_ref=observation.scope_ref, limit=5)
        except Exception:
            scope_memory_entries = []
    global_scope_ref = str(goal.constraints.get("global_scope_ref") or "").strip()
    if memory_service is not None and global_scope_ref:
        try:
            global_memory_entries = memory_service.read(scope_kind="global", scope_ref=global_scope_ref, limit=5)
        except Exception:
            global_memory_entries = []

    system_parts = _system_prompt_parts(goal)
    if persona_fragments:
        system_parts.append("\n".join(persona_fragments))
    if tool_registry is not None:
        system_parts.append(f"Available tools: {', '.join(sorted(tool_registry.tools.keys()))}")

    input_envelope = observation.input
    user_payload = {
        "goal_id": goal.goal_id,
        "goal_title": goal.title,
        "goal_kind": goal.constraints.get("goal_kind"),
        "scope_kind": goal.scope_kind,
        "scope_ref": goal.scope_ref,
        "constraints": dict(goal.constraints or {}),
        "success_criteria": dict(goal.constraints.get("success_criteria") or {}),
        "context_hints": dict(goal.constraints.get("context_hints") or {}),
        "input_message": None if input_envelope is None else input_envelope.input_message,
        "world_snapshot": observation.world_snapshot,
        "recent_events": list(observation.recent_events)[-8:],
        "memory": scope_memory_entries,
        "global_memory": global_memory_entries,
    }
    messages = [Message(role="system", content="\n\n".join(part for part in system_parts if part))]
    if input_envelope is not None and input_envelope.history_messages:
        messages.extend(input_envelope.history_messages)
    messages.append(Message(role="user", content=json.dumps(user_payload, ensure_ascii=False, default=str)))
    return messages


def _system_prompt_parts(goal: GoalRef) -> list[str]:
    parts: list[str] = []
    for prompt_key in ("base/identity", "base/behavior_rules", "base/output_format"):
        prompt_text = _load_prompt(prompt_key)
        if prompt_text:
            parts.append(prompt_text)

    task_prompt = _task_prompt_for_goal(goal)
    if task_prompt:
        parts.append(task_prompt)

    goal_summary = goal.goal_text or goal.title or "Complete the assigned goal."
    if goal_summary:
        parts.append(f"# 当前目标\n\n{goal_summary}")
    return parts


def _task_prompt_for_goal(goal: GoalRef) -> str:
    goal_kind = str(goal.constraints.get("goal_kind") or "").strip().lower()
    target_entity = str(goal.constraints.get("target_entity") or "").strip().lower()
    prompt_key = _task_prompt_key(goal_kind=goal_kind, target_entity=target_entity)
    if prompt_key is None:
        return ""
    return _load_prompt(f"tasks/{prompt_key}")


def _task_prompt_key(*, goal_kind: str, target_entity: str) -> str | None:
    if goal_kind in {
        "candidate_discovery",
        "candidate_outreach",
        "candidate_probe",
        "candidate_scoring",
        "candidate_archive",
        "resume_collection",
        "cooldown",
        "strategy_distill",
        "talent_pool_upload",
    }:
        return goal_kind
    if goal_kind in {"sync_jd_initial", "sync_jd_incremental"} or target_entity == "job_description":
        return "job_description_sync"
    return None


@lru_cache(maxsize=32)
def _load_prompt(prompt_key: str) -> str:
    asset_path = prompt_path(prompt_key)
    if not asset_path.exists():
        return ""
    return asset_path.read_text(encoding="utf-8").strip()
