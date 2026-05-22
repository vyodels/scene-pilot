from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from recruit_station.agent_runtime.types import LLMMessage

_SCENE_RUNTIME_CONTEXT_KIND = "runtime_context"


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
            "recent_events": _sanitize_recent_events(recent_events),
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
    agent_kind: str = "autonomous",
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
        agent_kind=agent_kind,
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
    browser_target = _find_key_recursive(request.get("environment_requirements"), {"browser_target", "browserTarget"})
    raw_payload = {
        "scene_request": {
            "instruction": instruction,
            "input": request["input"],
            "context": request["context"],
            "output_contract": request["output_contract"],
            "environment_requirements": request["environment_requirements"],
        },
        "scene_execution": {
            "episode_id": episode_id,
            "task_spec_id": task_spec_id,
            "max_llm_invocations": max_llm_invocations,
            "recent_events": recent_events,
            "available_tools": available_tools,
            "available_mcps": available_mcps,
            "anti_detection_policy": request.get("anti_detection_policy"),
            "behavior_budget": request.get("behavior_budget"),
        },
    }
    system_prompt = "\n".join(
        [
            "You are executing an isolated scene context for RecruitStation.",
            "Use only scene tools and return a business-level summary. Avoid DOM, tab, click path, or raw environment details unless they are required blocker evidence.",
            f"Available scene tools: {', '.join(available_tools) if available_tools else '(none)'}",
            f"Available MCP capabilities: {', '.join(available_mcps) if available_mcps else '(none)'}",
            "Browser target boundary: "
            + (json.dumps(browser_target, ensure_ascii=False, default=str) if browser_target is not None else "(not provided)"),
        ]
    )
    return RenderedAdapterInput(
        initial_messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="system",
                content="Scene runtime context:\n" + json.dumps(raw_payload, ensure_ascii=False, default=str),
                metadata={"kind": _SCENE_RUNTIME_CONTEXT_KIND, "auto_compact": True},
            ),
        ],
        turn_input=instruction,
        context_payload=raw_payload,
    )


def _json_len(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _find_key_recursive(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in keys:
                return item
        for item in value.values():
            found = _find_key_recursive(item, keys)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_key_recursive(item, keys)
            if found is not None:
                return found
    return None


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
    base_prompt = str(system_prompt or "").strip() or f"You are {agent_name}, a {agent_kind} type of RecruitStation."
    lines = [
        base_prompt,
        "You run through the shared RecruitStation product adapter. Use the available tools, skills, MCP resources, memory context, and product context without treating the agent type as a separate capability set.",
        "Memory is file-based. If the user explicitly asks you to remember or forget something, use the memory tools for the relevant scope. Do not encode memory updates in final text.",
    ]
    if instruction:
        lines.append(f"Instruction: {instruction}")
    available_tools = context_payload.get("available_tools")
    if isinstance(available_tools, list):
        lines.append(
            "Available runtime tools: "
            + (", ".join(str(item) for item in available_tools if str(item).strip()) or "(none)")
        )
    available_mcps = context_payload.get("available_mcps")
    if isinstance(available_mcps, list):
        lines.append(
            "Available MCP capabilities: "
            + (", ".join(str(item) for item in available_mcps if str(item).strip()) or "(none)")
        )
    browser_target_policy = _browser_target_policy(context_payload)
    if browser_target_policy:
        lines.append(browser_target_policy)
    if context_payload:
        lines.append(f"Context: {json.dumps(context_payload, ensure_ascii=False, default=str)}")
    return "\n".join(lines)


def _browser_target_policy(context_payload: dict[str, Any]) -> str | None:
    if not _has_browser_target(context_payload):
        return None
    return (
        "Browser target policy: browser_target.url is an entrypoint hint, not an exact active-tab path requirement. "
        "The hard boundary is the full origin derived from browser_target.url or browser_target.host, including port. "
        "Do not treat context_hints.active_tab_url as current browser evidence unless a browser tool confirms it in this turn. "
        "Browser availability must be checked with browser tools such as browser_get_active_tab, browser_list_tabs, or browser_snapshot; "
        "do not use MCP resource tools like list_mcp_resources for browser capability probing. "
        "If direct browser/HID tools are not exposed in this parent turn but delegate_scene_context is available, "
        "delegate_scene_context is the browser/HID execution gateway; call it with the browser_target and preferred_capabilities ['browser', 'computer'] instead of reporting missing direct browser/HID tools. "
        "Same-origin paths may change during the workflow; navigate or select a same-origin target when available. "
        "If a scene returns partial progress with blockers or limitations, do not treat that as a successful terminal result; continue with a recovery plan or return a clear blocked state. "
        "Recoverable browser/HID failures should be handled by re-observing, waiting for stability, releasing stuck modifier state, choosing an alternate same-origin affordance, or using HID to open an observed same-origin link. "
        "If the active tab is a different origin and no available tool can move to the target origin, report an origin blocker."
    )


def _has_browser_target(value: Any) -> bool:
    if isinstance(value, dict):
        if "browser_target" in value or "browserTarget" in value:
            return True
        return any(_has_browser_target(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_browser_target(item) for item in value)
    return False


def _sanitize_recent_events(events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        item = {
            key: event.get(key)
            for key in ("event_type", "source", "message", "turn_id", "conversation_id", "seq")
            if event.get(key) not in (None, "", [], {})
        }
        payload = event.get("payload")
        if isinstance(payload, dict):
            projected_payload = _project_recent_event_payload(payload)
            if projected_payload:
                item["payload"] = projected_payload
        sanitized.append(item)
    return sanitized


def _project_recent_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    kind = str(data.get("kind") or "").strip()
    tool_name = str(data.get("tool_name") or data.get("name") or "").strip()
    projected_data = {
        key: value
        for key, value in {
            "kind": kind or None,
            "tool_name": tool_name or None,
            "is_error": data.get("is_error") if "is_error" in data else None,
            "tool_call_id": data.get("tool_call_id"),
            "tool_use_id": data.get("tool_use_id"),
        }.items()
        if value not in (None, "", [], {})
    }
    content = data.get("content")
    if isinstance(content, dict) and str(content.get("projection", {}).get("kind") if isinstance(content.get("projection"), dict) else "") == "scene_result_summary":
        projected_data["content"] = content
    elif tool_name == "delegate_scene_context" or kind == "tool_result_ready":
        projected_data["content_summary"] = _compact_recent_event_content(content)
    return {"data": projected_data} if projected_data else {}


def _compact_recent_event_content(value: Any, *, max_chars: int = 400) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, dict):
        safe = {
            key: value.get(key)
            for key in ("status", "business_result")
            if value.get(key) not in (None, "", [], {})
        }
        refs = value.get("evidence_refs")
        if isinstance(refs, list):
            safe["evidence_ref_count"] = len(refs)
        if safe:
            return json.dumps(safe, ensure_ascii=False, sort_keys=True, default=str)[:max_chars]
    text = str(value).strip()
    return text[:max_chars] if text else None


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
