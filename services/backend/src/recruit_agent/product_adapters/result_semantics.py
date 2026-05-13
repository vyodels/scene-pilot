from __future__ import annotations

from typing import Any, Mapping


_GENERIC_EXECUTION_STATUSES = {"", "completed", "complete", "success", "ok", "done", "result", "default", "succeeded"}
_STATUS_ALIASES = {
    "passed": "pass",
    "failed": "fail",
}

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


def extract_execution_status(payload: Mapping[str, Any] | None) -> str | None:
    raw_payload = dict(payload or {})
    execution_status = _normalize_status(raw_payload.get("execution_status"))
    if execution_status:
        return execution_status
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
