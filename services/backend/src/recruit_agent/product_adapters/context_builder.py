from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from recruit_agent.agent_runtime.types import LLMMessage


@dataclass(frozen=True, slots=True)
class RenderedAdapterInput:
    initial_messages: list[LLMMessage]
    turn_input: str
    context_payload: dict[str, Any]


def build_assistant_turn_context(
    *,
    history_messages: list[LLMMessage],
    user_message: str,
    agent_profile_id: str | None = None,
    memory_entries: list[dict[str, Any]] | None = None,
    mcp_resource_contexts: list[dict[str, Any]] | None = None,
) -> RenderedAdapterInput:
    payload: dict[str, Any] = {}
    initial_messages = list(history_messages)
    if memory_entries:
        payload["memory_layers"] = {
            "short_term": "recent conversation transcript is provided as history messages",
            "medium_term": "conversation summaries are provided by the assistant session store when compaction runs",
            "long_term": "memory entries are stored as markdown files; read full files only when needed",
        }
        payload["memory_scope"] = {
            "agent_profile_id": agent_profile_id,
            "scope_kind": "conversation",
        }
        payload["memory_entries"] = list(memory_entries)
    if mcp_resource_contexts:
        payload["mcp_resource_contexts"] = list(mcp_resource_contexts)
    if payload:
        initial_messages.insert(
            0,
            LLMMessage(
                role="system",
                content="Assistant product context: "
                + json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
    return RenderedAdapterInput(
        initial_messages=initial_messages,
        turn_input=user_message,
        context_payload=payload,
    )


def build_autonomous_turn_context(
    *,
    title: str | None,
    goal_text: str,
    scope_kind: str,
    scope_ref: str,
    constraints: dict[str, Any],
    world_snapshot: dict[str, Any],
    recent_events: list[dict[str, Any]],
    memory_entries: list[dict[str, Any]],
    available_tools: list[str],
    skill_contexts: list[dict[str, Any]],
    available_mcps: list[str],
    mcp_resource_contexts: list[dict[str, Any]] | None = None,
) -> RenderedAdapterInput:
    payload = {
        "title": title,
        "scope": {"kind": scope_kind, "ref": scope_ref},
        "constraints": constraints,
        "world_snapshot": world_snapshot,
        "recent_events": recent_events,
        "memory_entries": memory_entries,
        "memory_layers": {
            "short_term": "recent run events and current turn transcript",
            "medium_term": "run context, checkpoints, and compacted summaries",
            "long_term": "memory index with previews; use read_memory_file for full markdown content",
        },
        "available_tools": available_tools,
        "skill_contexts": skill_contexts,
        "available_mcps": available_mcps,
        "mcp_resource_contexts": list(mcp_resource_contexts or []),
    }
    system_prompt = "\n".join(
        [
            "You are the Autonomous agent for Recruit Agent.",
            "Use the available tools to advance the goal. Keep externally visible history business-level.",
            "Memory is file-based. If the user explicitly asks you to remember or forget something, use the memory tools for the relevant scope. Do not encode memory updates in final text.",
            f"Goal: {goal_text}",
            f"Context: {json.dumps(payload, ensure_ascii=False, default=str)}",
        ]
    )
    turn_input_payload = {
        "goal": goal_text,
        "scope": {"kind": scope_kind, "ref": scope_ref},
        "world_snapshot": world_snapshot,
        "memory_entries": memory_entries,
        "constraints": constraints,
        "mcp_resource_contexts": list(mcp_resource_contexts or []),
    }
    return RenderedAdapterInput(
        initial_messages=[LLMMessage(role="system", content=system_prompt)],
        turn_input=json.dumps(turn_input_payload, ensure_ascii=False, default=str),
        context_payload=payload,
    )


def build_scene_turn_context(
    *,
    request: dict[str, Any],
    episode_id: str,
    task_spec_id: str,
    max_llm_invocations: int,
    recent_events: list[dict[str, Any]],
    available_tools: list[str],
    available_mcps: list[str],
    goal_text: str,
) -> RenderedAdapterInput:
    payload = {
        "scene_request": {
            "instruction": request["instruction"],
            "input": _compact_value(request["input"]),
            "context": _compact_value(request["context"]),
            "output_contract": _compact_value(request["output_contract"]),
            "environment_requirements": _compact_value(request["environment_requirements"]),
        },
        "scene_execution": {
            "episode_id": episode_id,
            "task_spec_id": task_spec_id,
            "max_llm_invocations": max_llm_invocations,
            "recent_events": recent_events,
            "available_tools": available_tools,
            "available_mcps": available_mcps,
        },
    }
    system_prompt = "\n".join(
        [
            "You are executing an isolated scene context for Recruit Agent.",
            "Use only scene tools and return a business-level summary. Avoid DOM, tab, click path, or raw environment details unless they are required blocker evidence.",
            f"Context: {_compact_value(payload)}",
        ]
    )
    return RenderedAdapterInput(
        initial_messages=[LLMMessage(role="system", content=system_prompt)],
        turn_input=goal_text,
        context_payload=payload,
    )


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return str(value)[:500]
    if isinstance(value, list):
        items = [_compact_value(item, depth=depth + 1) for item in value[:4]]
        if len(value) > 4:
            items.append({"_truncated": len(value) - 4})
        return items
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key in list(value.keys())[:12]:
            compact[str(key)] = _compact_value(value[key], depth=depth + 1)
        if len(value) > 12:
            compact["_truncated_keys"] = len(value) - 12
        return compact
    if isinstance(value, str):
        return value[:2000]
    return value
