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


def build_agent_turn_context(
    *,
    agent_kind: str,
    agent_name: str,
    system_prompt: str,
    turn_input: str,
    history_messages: list[LLMMessage] | None = None,
    instruction: str | None = None,
    title: str | None = None,
    agent_definition_id: str | None = None,
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    constraints: dict[str, Any] | None = None,
    world_snapshot: dict[str, Any] | None = None,
    recent_events: list[dict[str, Any]] | None = None,
    memory_entries: list[dict[str, Any]] | None = None,
    memory_layers: dict[str, Any] | None = None,
    available_tools: list[str] | None = None,
    skill_contexts: list[dict[str, Any]] | None = None,
    available_mcps: list[str] | None = None,
    mcp_resource_contexts: list[dict[str, Any]] | None = None,
    response_policy: dict[str, Any] | None = None,
) -> RenderedAdapterInput:
    payload = _without_empty(
        {
            "agent": {
                "kind": agent_kind,
                "name": agent_name,
                "definition_id": agent_definition_id,
            },
            "title": title,
            "instruction": instruction,
            "scope": (
                {"kind": scope_kind, "ref": scope_ref}
                if scope_kind is not None or scope_ref is not None
                else None
            ),
            "constraints": constraints,
            "world_snapshot": world_snapshot,
            "recent_events": recent_events,
            "memory_layers": memory_layers,
            "memory_entries": memory_entries,
            "available_tools": available_tools,
            "skill_contexts": skill_contexts,
            "available_mcps": available_mcps,
            "mcp_resource_contexts": list(mcp_resource_contexts or []),
            "response_policy": response_policy,
        }
    )
    prompt = _agent_system_prompt(
        system_prompt=system_prompt,
        agent_kind=agent_kind,
        agent_name=agent_name,
        instruction=instruction,
        context_payload=payload,
    )
    return RenderedAdapterInput(
        initial_messages=[LLMMessage(role="system", content=prompt), *list(history_messages or [])],
        turn_input=turn_input,
        context_payload=payload,
    )


def build_assistant_turn_context(
    *,
    history_messages: list[LLMMessage],
    user_message: str,
    agent_name: str = "Assistant",
    system_prompt: str = "",
    agent_definition_id: str | None = None,
    memory_entries: list[dict[str, Any]] | None = None,
    available_tools: list[str] | None = None,
    skill_contexts: list[dict[str, Any]] | None = None,
    available_mcps: list[str] | None = None,
    mcp_resource_contexts: list[dict[str, Any]] | None = None,
    response_policy: dict[str, Any] | None = None,
) -> RenderedAdapterInput:
    return build_agent_turn_context(
        agent_kind="assistant",
        agent_name=agent_name,
        system_prompt=system_prompt,
        history_messages=history_messages,
        turn_input=user_message,
        agent_definition_id=agent_definition_id,
        scope_kind="conversation",
        memory_entries=list(memory_entries or []),
        memory_layers={
            "short_term": "recent conversation transcript is provided as history messages",
            "medium_term": "conversation summaries are provided by the assistant session store when compaction runs",
            "long_term": "memory entries are stored as markdown files; read full files only when needed",
        },
        available_tools=available_tools,
        skill_contexts=skill_contexts,
        available_mcps=available_mcps,
        mcp_resource_contexts=mcp_resource_contexts,
        response_policy=response_policy,
    )


def build_autonomous_turn_context(
    *,
    title: str | None,
    instruction: str,
    agent_name: str = "Autonomous",
    system_prompt: str = "",
    agent_definition_id: str | None = None,
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
    turn_input_payload = {
        "instruction": instruction,
        "scope": {"kind": scope_kind, "ref": scope_ref},
        "world_snapshot": world_snapshot,
        "memory_entries": memory_entries,
        "constraints": constraints,
        "mcp_resource_contexts": list(mcp_resource_contexts or []),
    }
    return build_agent_turn_context(
        agent_kind="autonomous",
        agent_name=agent_name,
        system_prompt=system_prompt,
        title=title,
        instruction=instruction,
        agent_definition_id=agent_definition_id,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        constraints=constraints,
        world_snapshot=world_snapshot,
        recent_events=recent_events,
        memory_entries=memory_entries,
        memory_layers={
            "short_term": "recent run events and current turn transcript",
            "medium_term": "run context, checkpoints, and compacted summaries",
            "long_term": "memory index with previews; use read_memory_file for full markdown content",
        },
        available_tools=available_tools,
        skill_contexts=skill_contexts,
        available_mcps=available_mcps,
        mcp_resource_contexts=mcp_resource_contexts,
        turn_input=json.dumps(turn_input_payload, ensure_ascii=False, default=str),
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
    instruction: str,
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
        turn_input=instruction,
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


def _agent_system_prompt(
    *,
    system_prompt: str,
    agent_kind: str,
    agent_name: str,
    instruction: str | None,
    context_payload: dict[str, Any],
) -> str:
    base_prompt = str(system_prompt or "").strip() or f"You are {agent_name}, a {agent_kind} type of Recruit Agent."
    lines = [
        base_prompt,
        "You run through the shared Recruit Agent product adapter. Use the available tools, skills, MCP resources, memory context, and product context without treating the agent type as a separate capability set.",
        "Memory is file-based. If the user explicitly asks you to remember or forget something, use the memory tools for the relevant scope. Do not encode memory updates in final text.",
    ]
    if instruction:
        lines.append(f"Instruction: {instruction}")
    if context_payload:
        lines.append(f"Context: {json.dumps(context_payload, ensure_ascii=False, default=str)}")
    return "\n".join(lines)


def _without_empty(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if value == [] or value == {}:
            continue
        if isinstance(value, dict):
            nested = {nested_key: nested_value for nested_key, nested_value in value.items() if nested_value is not None}
            if not nested:
                continue
            compact[key] = nested
            continue
        compact[key] = value
    return compact
