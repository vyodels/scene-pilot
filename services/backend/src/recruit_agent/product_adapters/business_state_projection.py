from __future__ import annotations

from typing import Any

_BLOCKED_STATUSES = {"blocked", "waiting_human", "escalate", "error"}
_ACTIVE_STATUSES = {"queued", "running", "active", "pending"}
_COMPLETED_STATUSES = {"completed", "approved", "resolved"}
_FAILED_STATUSES = {"failed", "cancelled", "rejected", "interrupted", "error"}
_HUMAN_ONLY_BLOCKER_MARKERS = ("登录", "captcha", "验证码", "权限", "授权", "扫码", "浏览器能力", "设备绑定")


def project_runtime_business_state(
    *,
    content: dict[str, Any] | None = None,
    run_kind: str | None = None,
    run_title: str | None = None,
    run_status: str | None = None,
) -> dict[str, Any]:
    structured = dict(content or {})
    action_kind = _normalize_action_key(run_kind or structured.get("run_kind") or structured.get("run_type") or "")
    action_label = _resolve_action_label(structured=structured, run_title=run_title, action_kind=action_kind)
    status = _normalize_status(structured.get("status") or run_status or "unknown")
    created = _coerce_int(structured.get("created"))
    updated = _coerce_int(structured.get("updated"))
    skipped = _coerce_int(structured.get("skipped"))
    discovered_count = _derive_discovered_count(structured)
    blocker_kind = _derive_business_blocker_kind(structured, status=status)
    summary, blocker = _build_business_summary(
        action_label=action_label,
        status=status,
        created=created,
        updated=updated,
        skipped=skipped,
        discovered_count=discovered_count,
        blocker_kind=blocker_kind,
    )
    return {
        "action_kind": action_kind or "unknown",
        "action_label": action_label,
        "status": status,
        "summary": summary,
        "blocker": blocker,
    }

def _normalize_action_key(value: str) -> str:
    return str(value or "").strip().lower()


def _resolve_action_label(*, structured: dict[str, Any], run_title: str | None, action_kind: str) -> str:
    for candidate in (
        run_title,
        structured.get("run_title"),
        structured.get("title"),
        structured.get("label"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    if action_kind:
        return _humanize_identifier(action_kind)
    return "当前任务"


def _humanize_identifier(value: str) -> str:
    text = " ".join(part for part in str(value or "").replace("-", "_").split("_") if part).strip()
    if not text:
        return "当前任务"
    words = [part.upper() if part.lower() == "jd" else part.capitalize() for part in text.split()]
    return " ".join(words)


def _normalize_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text or "unknown"


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _derive_discovered_count(structured: dict[str, Any]) -> int:
    for key in ("discovered_count", "discovered", "confirmed"):
        count = _coerce_int(structured.get(key))
        if count:
            return count
    return 0


def _flatten_text(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text:
            values.append(text)
        return values
    if isinstance(value, list):
        for item in value:
            values.extend(_flatten_text(item))
        return values
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_flatten_text(item))
        return values
    return values


def _derive_business_blocker_kind(
    structured: dict[str, Any],
    *,
    status: str,
) -> str | None:
    if status not in _BLOCKED_STATUSES:
        return None
    text = " ".join(
        _flatten_text(structured.get("blocked_business_actions"))
        + _flatten_text(structured.get("external_platforms"))
        + _flatten_text(structured.get("next_actions"))
        + _flatten_text(structured.get("next_step"))
        + _flatten_text(structured.get("open_questions"))
        + _flatten_text(structured.get("evidence"))
        + _flatten_text(structured.get("text"))
    ).lower()
    if any(marker.lower() in text for marker in _HUMAN_ONLY_BLOCKER_MARKERS):
        return "human_only"
    return "generic"


def _build_business_summary(
    *,
    action_label: str,
    status: str,
    created: int,
    updated: int,
    skipped: int,
    discovered_count: int,
    blocker_kind: str | None,
) -> tuple[str, str | None]:
    if created or updated or skipped:
        return f"{action_label}：新增 {created}，更新 {updated}，跳过 {skipped}。", None
    if discovered_count:
        return f"{action_label}：新增/确认 {discovered_count} 条结果。", None
    if status == "waiting_human" or blocker_kind == "human_only":
        return f"{action_label}：等待人工处理后继续。", "waiting_human"
    if status == "blocked":
        return f"{action_label}：当前受阻，等待继续执行条件满足。", "blocked"
    if status in _ACTIVE_STATUSES:
        return f"{action_label}：正在执行。", None
    if status in _COMPLETED_STATUSES:
        return f"{action_label}：已完成。", None
    if status in _FAILED_STATUSES:
        if status in {"cancelled", "interrupted", "rejected"}:
            return f"{action_label}：已停止。", "stopped"
        return f"{action_label}：执行失败。", "failed"
    if status == "draft":
        return f"{action_label}：待启动。", None
    return f"{action_label}：状态待确认。", None
