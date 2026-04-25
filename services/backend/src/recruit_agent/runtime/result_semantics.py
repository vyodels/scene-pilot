from __future__ import annotations

import json
import re
from typing import Any, Mapping


_GENERIC_EXECUTION_STATUSES = {"", "completed", "complete", "success", "ok", "done", "result", "default", "succeeded"}
_STATUS_ALIASES = {
    "passed": "pass",
    "failed": "fail",
}
_WAIT_HUMAN_RESULT_STATUSES = {
    "approval_required",
    "blocked_human",
    "human_required",
    "needs_human",
    "wait_human",
    "waiting_human",
}
_BLOCKED_RESULT_STATUSES = {
    "blocked",
    "blocked_environment",
    "escalate",
}
_FAILED_RESULT_STATUSES = {
    "error",
    "fail",
}
_STATUS_TEXT_PATTERN = re.compile(r'(?i)(?:^|[\s{,])["\']?status["\']?\s*[:=]\s*["\']?([a-z_][a-z0-9_-]*)')


def extract_business_status(payload: Mapping[str, Any] | None, *, fallback: str | None = None) -> str | None:
    raw_payload = dict(payload or {})
    screening_result = raw_payload.get("screening_result")
    candidates: list[str | None] = [
        _normalize_status(raw_payload.get("screening_decision")),
        _normalize_status(raw_payload.get("decision")),
        _normalize_status(screening_result.get("decision")) if isinstance(screening_result, Mapping) else None,
        _bool_decision(screening_result.get("pass")) if isinstance(screening_result, Mapping) else None,
    ]

    for key in ("data", "result"):
        nested_payload = raw_payload.get(key)
        if isinstance(nested_payload, Mapping):
            candidates.append(extract_business_status(nested_payload))

    candidates.extend(
        [
            _normalize_status(raw_payload.get("status")),
            _normalize_status(fallback),
        ]
    )

    generic: str | None = None
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.lower() not in _GENERIC_EXECUTION_STATUSES:
            return candidate
        if generic is None:
            generic = candidate
    return generic


def normalize_result_payload(payload: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    raw_payload = dict(payload or {})
    result_data: dict[str, Any] = {}

    nested_data = raw_payload.get("data")
    if isinstance(nested_data, Mapping):
        result_data.update(dict(nested_data))

    nested_result = raw_payload.get("result")
    if isinstance(nested_result, Mapping):
        result_data.update(dict(nested_result))

    for key, value in raw_payload.items():
        if key in {"data", "result", "skill_draft"}:
            continue
        result_data[key] = value

    business_status = extract_business_status(result_data)
    if business_status:
        current_status = _normalize_status(result_data.get("status"))
        if current_status and current_status != business_status:
            result_data.setdefault("execution_status", current_status)
        result_data["status"] = business_status

    skill_draft = raw_payload.get("skill_draft")
    if not isinstance(skill_draft, Mapping):
        return result_data, None
    return result_data, dict(skill_draft)


def infer_non_success_round_outcome(final_output: str | None) -> tuple[str, str] | None:
    payload = extract_structured_result_payload(final_output)
    execution_status = extract_execution_status(payload)
    normalized_status = execution_status.lower() if execution_status else None
    if normalized_status in _WAIT_HUMAN_RESULT_STATUSES:
        return "wait_human", "wait_human"
    if (
        normalized_status in _FAILED_RESULT_STATUSES
        or (normalized_status is not None and normalized_status.startswith("failed_"))
        or (normalized_status is not None and normalized_status.startswith("failure_"))
    ):
        return "error", "escalate"
    if normalized_status in _BLOCKED_RESULT_STATUSES or (normalized_status is not None and normalized_status.startswith("blocked_")):
        return "escalate", "escalate"
    return None


def extract_structured_result_payload(final_output: str | None) -> dict[str, Any] | None:
    text = str(final_output or "").strip()
    if not text:
        return None
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = _STATUS_TEXT_PATTERN.search(text)
        if match is None:
            return None
        return {"status": match.group(1)}
    return dict(payload) if isinstance(payload, Mapping) else None


def extract_execution_status(payload: Mapping[str, Any] | None) -> str | None:
    raw_payload = dict(payload or {})
    status = _normalize_status(raw_payload.get("status"))
    if status:
        return status
    for key in ("data", "result"):
        nested_payload = raw_payload.get(key)
        if not isinstance(nested_payload, Mapping):
            continue
        nested_status = extract_execution_status(nested_payload)
        if nested_status:
            return nested_status
    return None


def _normalize_status(value: Any) -> str | None:
    cleaned = _clean_string(value)
    if cleaned is None:
        return None
    return _STATUS_ALIASES.get(cleaned.lower(), cleaned)


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _bool_decision(value: Any) -> str | None:
    if isinstance(value, bool):
        return "pass" if value else "fail"
    return None
