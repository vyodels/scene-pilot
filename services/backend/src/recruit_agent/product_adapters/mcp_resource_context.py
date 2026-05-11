from __future__ import annotations

import json
from typing import Any


def extract_mcp_resource_context_policy(*sources: dict[str, Any]) -> dict[str, Any]:
    for source in sources:
        policy = _find_policy(source)
        if policy:
            return {
                "resources": _resource_specs(policy.get("resources")),
                "max_resources": _bounded_int(policy.get("max_resources"), default=4, minimum=1, maximum=8),
                "max_chars_per_resource": _bounded_int(
                    policy.get("max_chars_per_resource"),
                    default=4000,
                    minimum=200,
                    maximum=12000,
                ),
            }
    return {"resources": [], "max_resources": 4, "max_chars_per_resource": 4000}


def build_mcp_resource_context(mcp_registry: Any, policy: dict[str, Any]) -> list[dict[str, Any]]:
    resources = _resource_specs(policy.get("resources"))[: _bounded_int(policy.get("max_resources"), default=4, minimum=1, maximum=8)]
    max_chars = _bounded_int(policy.get("max_chars_per_resource"), default=4000, minimum=200, maximum=12000)
    contexts: list[dict[str, Any]] = []
    for spec in resources:
        uri = str(spec.get("uri") or "").strip()
        if not uri:
            continue
        try:
            payload = mcp_registry.read_mcp_resource(
                uri=uri,
                server_key=str(spec.get("server_key") or "").strip(),
                server_id=str(spec.get("server_id") or "").strip(),
            )
        except Exception as exc:
            contexts.append({"uri": uri, "error": str(exc), "status": "unavailable"})
            continue
        contexts.append(_context_item(payload, max_chars=max_chars))
    return contexts


def render_mcp_resource_context_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"mcp_resource_contexts": list(items or [])}


def _find_policy(source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    for key in ("mcp_resource_context", "mcp_resources", "resource_context"):
        value = source.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return {"resources": value}
    for key in ("context_hints", "metadata", "constraints"):
        nested = source.get(key)
        if isinstance(nested, dict):
            found = _find_policy(nested)
            if found:
                return found
    return {}


def _resource_specs(value: Any) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            item = {"uri": item}
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "").strip()
        if not uri:
            continue
        spec = {
            "uri": uri,
            "server_key": str(item.get("server_key") or "").strip(),
            "server_id": str(item.get("server_id") or "").strip(),
        }
        if spec not in specs:
            specs.append(spec)
    return specs


def _context_item(payload: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    resource = payload.get("resource")
    content = _resource_text(resource)
    item = {
        "server_id": payload.get("server_id"),
        "server_key": payload.get("server_key"),
        "name": payload.get("name"),
        "uri": payload.get("uri"),
        "content": content[:max_chars],
    }
    if len(content) > max_chars:
        item["truncated"] = True
        item["original_chars"] = len(content)
    return item


def _resource_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "contents", "data"):
            raw = value.get(key)
            if isinstance(raw, str):
                return raw
            if isinstance(raw, list):
                parts = [_resource_text(item) for item in raw]
                text = "\n".join(part for part in parts if part)
                if text:
                    return text
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, list):
        return "\n".join(_resource_text(item) for item in value)
    return "" if value is None else str(value)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))
