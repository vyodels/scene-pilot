from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

GLOBAL_MEMORY_SCHEMA_NAMESPACE = "agent-global-memory-long-term"
_LONG_TERM_CONTENT_KEYS = (
    "facts",
    "decisions",
    "open_questions",
    "next_actions",
    "risk_flags",
    "evidence_refs",
    "confidence",
)
_LEGACY_RUNTIME_KEYS = {
    "business_snapshot",
    "business_action",
    "candidate_pipeline",
    "job_sync",
    "external_platforms",
    "blocked_business_actions",
}
_LEAK_MARKERS = (
    "标签页",
    "browser_list_tabs",
    "browser_snapshot",
    "active tab",
    "current tab",
    "http://",
    "https://",
    "management center",
    "dom",
    "url:",
    "招聘页面",
    "候选人来源页面",
    "职位列表",
    "职位详情",
    "请先在浏览器中打开",
    "新增 ",
    "更新 ",
    "跳过 ",
    "业务动作状态：unknown",
    "最近一次业务动作",
)
_DEFAULT_SUMMARY = "尚未沉淀长期可复用的全局业务知识。"


def _projection_contract() -> dict[str, Any]:
    return {
        "schema_namespace": GLOBAL_MEMORY_SCHEMA_NAMESPACE,
        "content_keys": list(_LONG_TERM_CONTENT_KEYS),
        "legacy_runtime_keys": sorted(_LEGACY_RUNTIME_KEYS),
        "default_summary": _DEFAULT_SUMMARY,
    }


def _derive_projection_signature() -> str:
    contract = json.dumps(_projection_contract(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(contract.encode("utf-8")).hexdigest()[:12]


GLOBAL_MEMORY_PROJECTION_SIGNATURE = _derive_projection_signature()
GLOBAL_MEMORY_SCHEMA_VERSION = f"{GLOBAL_MEMORY_SCHEMA_NAMESPACE}-{GLOBAL_MEMORY_PROJECTION_SIGNATURE}"


def empty_agent_global_memory_payload() -> dict[str, Any]:
    content = {
        "facts": [],
        "decisions": [],
        "open_questions": [],
        "next_actions": [],
        "risk_flags": [],
        "evidence_refs": [],
        "confidence": "unknown",
    }
    return {
        "memory_schema_version": GLOBAL_MEMORY_SCHEMA_VERSION,
        "summary": _DEFAULT_SUMMARY,
        "content": content,
        "raw_content": copy.deepcopy(content),
        "memory_metadata": {
            "scope": "agent_global",
            "projection_kind": "long_term_memory",
            "abstraction_level": "long_term_business",
            "schema_namespace": GLOBAL_MEMORY_SCHEMA_NAMESPACE,
            "projection_signature": GLOBAL_MEMORY_PROJECTION_SIGNATURE,
        },
    }


def empty_agent_global_memory_business_payload() -> dict[str, Any]:
    return empty_agent_global_memory_payload()


def needs_agent_global_memory_projection(
    *,
    memory_schema_version: str | None,
    summary: str | None,
    content: dict[str, Any] | None,
    raw_content: dict[str, Any] | None,
    memory_metadata: dict[str, Any] | None = None,
) -> bool:
    if str(memory_schema_version or "") != GLOBAL_MEMORY_SCHEMA_VERSION:
        return True
    if _contains_legacy_runtime_fields(content) or _contains_legacy_runtime_fields(raw_content):
        return True
    if _looks_like_degraded_long_term_memory(summary=summary, content=content, memory_metadata=memory_metadata):
        return True
    combined = " ".join(_collect_text_fragments(summary, content, raw_content)).lower()
    if not combined:
        return False
    return any(marker in combined for marker in _LEAK_MARKERS)


def project_agent_global_memory(
    *,
    summary: str | None = None,
    content: dict[str, Any] | None = None,
    raw_content: dict[str, Any] | None = None,
    final_content: str | None = None,
    goal_kind: str | None = None,
    goal_title: str | None = None,
    round_status: str | None = None,
    source_kind: str | None = None,
    run_pk: str | None = None,
    conversation_pk: str | None = None,
) -> dict[str, Any]:
    del final_content, goal_kind, goal_title, round_status, source_kind, run_pk, conversation_pk
    seed = empty_agent_global_memory_payload()
    projected_content = _normalize_long_term_content(content=content, raw_content=raw_content)
    summary_text = _normalize_summary(summary, projected_content)
    if summary_text:
        seed["summary"] = summary_text
    elif _has_long_term_content(projected_content):
        seed["summary"] = _summarize_long_term_content(projected_content)
    seed["content"] = projected_content
    seed["raw_content"] = copy.deepcopy(projected_content)
    return seed


def _contains_legacy_runtime_fields(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(key in payload for key in _LEGACY_RUNTIME_KEYS)


def _looks_like_degraded_long_term_memory(
    *,
    summary: str | None,
    content: dict[str, Any] | None,
    memory_metadata: dict[str, Any] | None,
) -> bool:
    summary_text = str(summary or "").strip()
    lowered_summary = summary_text.lower()
    if lowered_summary in {"业务动作状态：unknown。", "全局业务状态尚未整理。"}:
        return True

    metadata = dict(memory_metadata or {})
    normalized_from = str(metadata.get("normalized_from") or "").strip().lower()
    if normalized_from.startswith("agent-global-memory-business-"):
        return True
    if any(str(metadata.get(key) or "").strip() for key in ("last_business_action", "last_business_status")):
        return True

    payload = dict(content or {})
    facts = payload.get("facts")
    if isinstance(facts, list) and any("最近一次业务动作" in str(item) for item in facts):
        return True
    return False


def _normalize_long_term_content(
    *,
    content: dict[str, Any] | None,
    raw_content: dict[str, Any] | None,
) -> dict[str, Any]:
    source = dict(content or {})
    fallback = dict(raw_content or {})
    normalized = {
        "facts": _sanitize_string_list(source.get("facts"), fallback.get("facts")),
        "decisions": _sanitize_string_list(source.get("decisions"), fallback.get("decisions")),
        "open_questions": _sanitize_string_list(source.get("open_questions"), fallback.get("open_questions")),
        "next_actions": _sanitize_string_list(source.get("next_actions"), fallback.get("next_actions")),
        "risk_flags": _sanitize_string_list(source.get("risk_flags"), fallback.get("risk_flags")),
        "evidence_refs": _sanitize_reference_list(source.get("evidence_refs"), fallback.get("evidence_refs")),
        "confidence": _normalize_confidence(source.get("confidence") or fallback.get("confidence")),
    }
    if not _has_long_term_content(normalized):
        return empty_agent_global_memory_payload()["content"]
    return normalized


def _sanitize_string_list(*values: Any) -> list[str]:
    items: list[str] = []
    for value in values:
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if not text:
                continue
            lowered = text.lower()
            if any(marker in lowered for marker in _LEAK_MARKERS):
                continue
            if text not in items:
                items.append(text)
    return items


def _sanitize_reference_list(*values: Any) -> list[Any]:
    items: list[Any] = []
    for value in values:
        if not isinstance(value, list):
            continue
        for candidate in value:
            if candidate in items:
                continue
            items.append(candidate)
    return items


def _normalize_confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"low", "medium", "high"}:
        return text
    return "unknown"


def _normalize_summary(summary: str | None, content: dict[str, Any]) -> str:
    text = str(summary or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if any(marker in lowered for marker in _LEAK_MARKERS):
        return ""
    if not _has_long_term_content(content):
        return ""
    return text


def _has_long_term_content(content: dict[str, Any]) -> bool:
    for key in ("facts", "decisions", "open_questions", "next_actions", "risk_flags", "evidence_refs"):
        value = content.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def _summarize_long_term_content(content: dict[str, Any]) -> str:
    item_count = 0
    for key in ("facts", "decisions", "open_questions", "next_actions", "risk_flags"):
        value = content.get(key)
        if isinstance(value, list):
            item_count += len(value)
    if item_count <= 0:
        return _DEFAULT_SUMMARY
    return f"已沉淀 {item_count} 条长期可复用的全局业务知识。"


def _collect_text_fragments(summary: str | None, *payloads: dict[str, Any] | None) -> list[str]:
    fragments: list[str] = []
    if summary:
        fragments.append(str(summary))
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for value in payload.values():
            if isinstance(value, str):
                fragments.append(value)
            elif isinstance(value, list):
                fragments.extend(str(item) for item in value)
            elif isinstance(value, dict):
                fragments.extend(_collect_text_fragments(None, value))
    return fragments
