from __future__ import annotations

from copy import deepcopy
from typing import Any

from recruit_station.services.jd_sync_contract import normalize_jd_sync_scene_result


JD_SYNC_STATE_KEY = "jd_sync_state"


def initial_jd_sync_state(*, target: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "version": 1,
        "selected_tab": {},
        "target": dict(target or {}),
        "jobs_by_key": {},
        "pending_job_keys": [],
        "completed_job_keys": [],
        "inactive_job_keys": [],
        "policy_violations": [],
        "recovery_attempts": [],
        "writeback_results": [],
        "evidence_refs": [],
    }


def ensure_jd_sync_state(metadata: dict[str, Any], *, target: dict[str, Any] | None = None) -> dict[str, Any]:
    state = _as_dict(metadata.get(JD_SYNC_STATE_KEY))
    if not state:
        state = initial_jd_sync_state(target=target)
    else:
        state = _normalize_state_shape(state)
        if target and not state.get("target"):
            state["target"] = dict(target)
    metadata[JD_SYNC_STATE_KEY] = state
    return metadata


def reduce_jd_sync_scene_result(state: dict[str, Any] | None, scene_result: dict[str, Any]) -> dict[str, Any]:
    next_state = _normalize_state_shape(state or {})
    result_data = _scene_business_result(scene_result)
    normalized = normalize_jd_sync_scene_result(result_data, {"contract_kind": "jd_sync"})
    _merge_selected_tab(next_state, normalized)
    for item in normalized.get("observed_jobs") or []:
        _upsert_job(next_state, item, status="observed")
    for item in normalized.get("pending_jobs") or []:
        key = _upsert_job(next_state, item, status="pending")
        _append_unique(next_state["pending_job_keys"], key)
    for item in normalized.get("completed_job_details") or []:
        key = _upsert_job(next_state, item, status="completed")
        _append_unique(next_state["completed_job_keys"], key)
        _remove_value(next_state["pending_job_keys"], key)
    for item in normalized.get("inactive_or_closed_jobs") or []:
        key = _upsert_job(next_state, item, status="inactive")
        _append_unique(next_state["inactive_job_keys"], key)
        _remove_value(next_state["pending_job_keys"], key)
    for field, target in (
        ("policy_violations", "policy_violations"),
        ("evidence_refs", "evidence_refs"),
    ):
        for item in normalized.get(field) or []:
            _append_unique(next_state[target], item)
    recovery = _as_dict(normalized.get("recovery"))
    if recovery:
        _append_unique(next_state["recovery_attempts"], recovery)
    for item in normalized.get("writeback_results") or []:
        _append_unique(next_state["writeback_results"], item)
    for item in normalized.get("writeback_candidates") or []:
        _append_unique(next_state["writeback_results"], {"status": "candidate", "candidate": item})
    _recompute_pending(next_state)
    return next_state


def reduce_jd_sync_tool_results(state: dict[str, Any] | None, tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    next_state = _normalize_state_shape(state or {})
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or item.get("name") or "").strip()
        output = item.get("output") if "output" in item else item.get("result")
        if tool_name == "delegate_scene_context" and isinstance(output, dict):
            next_state = reduce_jd_sync_scene_result(next_state, output)
        elif tool_name == "upsert_job_description":
            _append_unique(
                next_state["writeback_results"],
                {"status": "error" if item.get("is_error") else "completed", "output": output},
            )
    return next_state


def reduce_agent_run_jd_sync_state(run: Any, *, tool_results: list[dict[str, Any]], final_result_data: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = dict(getattr(run, "runtime_metadata", None) or {})
    state = _normalize_state_shape(metadata.get(JD_SYNC_STATE_KEY) or {})
    state = reduce_jd_sync_tool_results(state, tool_results)
    if final_result_data:
        state = reduce_jd_sync_scene_result(state, {"result_data": dict(final_result_data)})
    metadata[JD_SYNC_STATE_KEY] = state
    run.runtime_metadata = metadata
    return state


def _scene_business_result(output: dict[str, Any]) -> dict[str, Any]:
    result_data = _as_dict(output.get("result_data"))
    if result_data:
        return result_data
    business_result = _as_dict(output.get("business_result"))
    if business_result:
        return business_result
    return dict(output)


def _normalize_state_shape(value: dict[str, Any]) -> dict[str, Any]:
    state = initial_jd_sync_state()
    for key, default in state.items():
        existing = value.get(key)
        if isinstance(default, dict):
            state[key] = dict(existing) if isinstance(existing, dict) else {}
        elif isinstance(default, list):
            state[key] = list(existing) if isinstance(existing, list) else []
        else:
            state[key] = existing if existing is not None else default
    return state


def _merge_selected_tab(state: dict[str, Any], result_data: dict[str, Any]) -> None:
    recovery = _as_dict(result_data.get("recovery"))
    selected_tab = _as_dict(recovery.get("selected_tab") or result_data.get("selected_tab"))
    if selected_tab:
        state["selected_tab"] = {**dict(state.get("selected_tab") or {}), **selected_tab}


def _upsert_job(state: dict[str, Any], item: Any, *, status: str) -> str:
    payload = _as_dict(item)
    key = _job_key(payload or item)
    if not key:
        key = f"job-{len(state['jobs_by_key']) + 1}"
    existing = dict(state["jobs_by_key"].get(key) or {})
    existing.update(payload if payload else {"label": str(item)})
    existing["sync_state"] = status
    state["jobs_by_key"][key] = existing
    return key


def _recompute_pending(state: dict[str, Any]) -> None:
    completed = set(state["completed_job_keys"])
    inactive = set(state["inactive_job_keys"])
    pending = [key for key in state["pending_job_keys"] if key not in completed and key not in inactive]
    for key, item in state["jobs_by_key"].items():
        if key in completed or key in inactive:
            continue
        if str(_as_dict(item).get("sync_state") or "") in {"observed", "pending"}:
            _append_unique(pending, key)
    state["pending_job_keys"] = pending


def _job_key(value: Any) -> str:
    item = _as_dict(value)
    for key in ("job_key", "key", "external_id", "external_url", "detail_url", "title", "job_title", "name"):
        text = str(item.get(key) or "").strip().lower()
        if text:
            return text
    text = str(value or "").strip().lower()
    return text


def _append_unique(items: list[Any], item: Any) -> None:
    comparable = _stable(item)
    if any(_stable(existing) == comparable for existing in items):
        return
    items.append(deepcopy(item))


def _remove_value(items: list[Any], value: Any) -> None:
    comparable = _stable(value)
    items[:] = [item for item in items if _stable(item) != comparable]


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((key, _stable(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(_stable(item) for item in value)
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
