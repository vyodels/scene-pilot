from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


JD_SYNC_STATE_MACHINE: tuple[str, ...] = (
    "init_target",
    "find_existing_zhipin_tab",
    "recover_to_job_management",
    "observe_job_list",
    "enumerate_open_jobs",
    "open_job_detail",
    "extract_detail",
    "validate_detail",
    "writeback_jd",
    "verify_coverage",
    "completed",
)

JD_SYNC_SCENE_REQUIRED_FIELDS: tuple[str, ...] = (
    "status",
    "scene_status",
    "observed_jobs",
    "pending_jobs",
    "completed_job_details",
    "inactive_or_closed_jobs",
    "action_candidates",
    "recovery",
    "terminal_blockers",
    "policy_violations",
    "evidence_refs",
    "writeback_candidates",
    "blockers",
    "limitations",
    "evidence",
)

JD_SYNC_ALLOWED_RUNTIME_TOOLS: frozenset[str] = frozenset(
    {
        "delegate_scene_context",
        "list_job_descriptions",
        "upsert_job_description",
        "get_jd_progress",
        "request_human_approval",
    }
)


def is_jd_sync_contract(contract: dict[str, Any] | None) -> bool:
    payload = _as_dict(contract)
    if str(payload.get("contract_kind") or "").strip().lower() == "jd_sync":
        return True
    required = {str(item).strip() for item in payload.get("required_fields") or [] if str(item or "").strip()}
    return {"observed_jobs", "completed_job_details", "inactive_or_closed_jobs"}.issubset(required)


def jd_sync_scene_output_contract(*, sync_mode: str = "", max_job_descriptions: int | None = None) -> dict[str, Any]:
    single_probe = sync_mode == "single_jd_probe" or max_job_descriptions == 1
    field_contract = {
        "scene_status": "Current scene state: in_progress, partial, blocked, or completed. Keep status and scene_status aligned.",
        "observed_jobs": "Open/current jobs actually observed in this scene turn from current-host list/detail evidence.",
        "pending_jobs": "Observed open jobs that still need detail entry, extraction, validation, or writeback.",
        "completed_job_details": "Only jobs whose current-host detail/edit page was opened/read and concrete responsibilities plus requirements were extracted.",
        "inactive_or_closed_jobs": "Jobs observed as inactive, closed, unavailable, draft, pending publish, review failed, or removed.",
        "action_candidates": "Safe next same-page actions derived from browser observations, such as job row/title/detail/edit entries, back/list controls, or scroll needs.",
        "recovery": "Recoverable same-site state including selected_tab, last page kind, attempted recovery actions, next_action, and retryable errors.",
        "terminal_blockers": "Hard blockers only: login, captcha, permission, required tool unavailable, target site unreachable, or no visible same-origin path.",
        "policy_violations": "JD-only or boundary violations such as candidate/chat contamination, public job-search evidence, new-tab/address-bar proposals, or destructive controls.",
        "evidence_refs": "Current-run evidence references to scene observations, URLs, tab IDs, tool results, or page facts. Historical memory/checkpoints are not evidence.",
        "writeback_candidates": "Validated current-run detail payloads that may be passed to upsert_job_description; list/card-only entries must not appear here.",
        "blockers": "Compatibility alias for terminal_blockers and current scene blockers.",
        "limitations": "Recoverable or incomplete conditions; include offscreen entries, pending detail reads, and list/detail coverage gaps.",
        "evidence": "Compatibility evidence summary; keep current-host and current-run only.",
    }
    if single_probe:
        field_contract["observed_jobs"] = (
            "Jobs actually observed or selected in this scene turn. For single_jd_probe this may contain only the visible/selected "
            "published/current JD candidate and does not need to account for every listed/open job."
        )
        field_contract["completed_job_details"] = (
            field_contract["completed_job_details"]
            + " New/draft/pending-publish/review-failed forms, including BOSS/Zhipin URLs with encryptId=0, are not completed job details."
        )
        completion_rule = (
            "For single_jd_probe, status may be completed only after one published/current recruiting JD detail has been opened/read, "
            "validated, written back, and verified by tool result or local reread. List summaries, review-failed/pending-publish pages, "
            "draft/new forms, stale-host evidence, or inferred jobs must stay partial or blocked."
        )
    else:
        completion_rule = (
            "Full JD sync status may be completed only when all observed/open jobs have completed details and writeback verification, "
            "pending_jobs is empty, terminal_blockers is empty, and policy_violations is empty. List summaries, partial details, "
            "offscreen links, stale-host evidence, candidate/chat evidence, or inferred jobs must stay partial/in_progress or blocked."
        )
    return {
        "contract_kind": "jd_sync",
        "format": "json",
        "result_data_required": True,
        "status_values": ["in_progress", "partial", "blocked", "completed"],
        "state_machine": list(JD_SYNC_STATE_MACHINE),
        "required_fields": list(JD_SYNC_SCENE_REQUIRED_FIELDS),
        "field_contract": field_contract,
        "completion_rule": completion_rule,
    }


def jd_sync_scene_instruction(*, sync_mode: str, max_job_descriptions: int | None) -> str:
    single_probe = sync_mode == "single_jd_probe" or max_job_descriptions == 1
    scope_rule = (
        "本次运行模式是单 JD 同步试跑：最多完成 1 个招聘中 JD 的完整详情读取、校验、写回和验证；"
        "不要求全量扫描所有职位，也不要因为列表计数或 offscreen 职位继续扩张目标。"
        if single_probe
        else
        "本次是完整 JD 同步：必须枚举当前招聘中职位，逐个进入详情/安全编辑页，抽取、校验、写回，并确认 pending_jobs 为空后才能完成。"
    )
    return (
        "执行招聘站点 JD 同步 scene。规则：必须按状态机推进："
        "init_target -> find_existing_zhipin_tab -> recover_to_job_management -> observe_job_list -> "
        "enumerate_open_jobs -> open_job_detail -> extract_detail -> validate_detail -> writeback_jd -> "
        "verify_coverage -> completed。"
        f"{scope_rule}"
        "本地 JD 库为空是正常启动状态，不是 blocker；JD Sync 的职责就是从已登录页面发现并同步 JD。"
        "首次 scene 必须先查找已有 zhipin/BOSS 页签、同页恢复到职位管理、观察职位列表。"
        "从当前同源招聘网页出发，使用 browser 只读观察和 computer/HID 页面内操作；"
        "browser-mcp 不能点击、导航、打开新页、操作地址栏或执行写动作，执行只允许走 VirtualHID。"
        "不得主动聚焦浏览器地址栏、输入 URL、粘贴 URL、打开新 BOSS/zhipin 标签或窗口。"
        "DOMAIN,zhipin.com 是硬边界；同站点恢复只能使用已有 zhipin/BOSS 页签和页面内可见入口。"
        "从非 JD 页面恢复时只能点击 BOSS 主导航 职位管理；推荐牛人、搜索、沟通只能作为页面识别锚点，不能作为 JD sync 恢复入口。"
        "职位管理列表只用于发现 observed_jobs/pending_jobs，不能把列表卡、数量、指标、候选人概况或公共求职职位结果当作 completed_job_details。"
        "在职位管理列表中只允许选择职位卡、职位标题、查看详情、编辑/安全编辑等用于读取 JD 的入口；"
        "BOSS/直聘页面里 encryptId=0 或 URL/表单语义指向待发布/新建职位时，不能视为已发布 JD 详情，也不能写回。"
        "不得点击发布职位、关闭、停止招聘、下线、删除、升级、曝光刷新、新建分组、候选人/聊天/外联控件。"
        "如果目标职位入口在 browser 观察中存在但 inViewport=false，先用 HID 滚动，再重新观察并基于新的 in-viewport clickPoint 点击。"
        "每个 completed_job_details 必须来自当前 host 的详情/编辑页，包含职位名、当前详情 URL 或稳定标识、职责/描述、要求等具体文本；"
        "generic assertion、历史摘要、checkpoint、记忆、列表卡或模型推断都不是详情证据。"
        "候选人/沟通/简历内容只能记录为 policy_violations 和 blocker，不能作为 progress、observed_jobs、writeback_candidates 或 JD 写回依据。"
        "若同源页面仍可观察且存在安全 action_candidates、pending_jobs 或 recovery.next_action，status/scene_status 必须是 in_progress 或 partial，不能 blocked。"
        "只有登录、验证码、权限、必要工具缺失、目标站点不可达，或没有任何可见同源恢复路径时，才能写 terminal_blockers 并返回 blocked。"
        "最终回答必须是单个 JSON object，直接包含 output_contract.required_fields 的全部字段；partial/in_progress/blocked 也必须填齐空列表/对象。"
    )


def normalize_jd_sync_scene_result(result_data: dict[str, Any], contract: dict[str, Any] | None) -> dict[str, Any]:
    if not is_jd_sync_contract(contract):
        return result_data
    normalized = dict(result_data or {})
    status = _normalize_status(
        normalized.get("scene_status")
        or normalized.get("status")
        or normalized.get("execution_status")
        or normalized.get("result_status")
    )
    normalized["status"] = status
    normalized["scene_status"] = status

    list_fields = (
        "observed_jobs",
        "pending_jobs",
        "completed_job_details",
        "inactive_or_closed_jobs",
        "action_candidates",
        "terminal_blockers",
        "policy_violations",
        "evidence_refs",
        "writeback_candidates",
        "blockers",
        "limitations",
        "evidence",
    )
    for field in list_fields:
        normalized[field] = _list_value(normalized.get(field))
    normalized["recovery"] = _as_dict(normalized.get("recovery"))
    _filter_non_jd_sync_items(normalized)

    if not normalized["pending_jobs"]:
        normalized["pending_jobs"] = _derive_pending_jobs(normalized)
    if not normalized["terminal_blockers"] and normalized["blockers"]:
        normalized["terminal_blockers"] = list(normalized["blockers"])
    if not normalized["blockers"] and normalized["terminal_blockers"]:
        normalized["blockers"] = list(normalized["terminal_blockers"])
    if not normalized["evidence_refs"] and normalized["evidence"]:
        normalized["evidence_refs"] = list(normalized["evidence"])

    has_recoverable_next = bool(
        normalized["pending_jobs"]
        or normalized["action_candidates"]
        or _as_dict(normalized.get("recovery")).get("next_action")
    )
    if status == "blocked" and has_recoverable_next and not normalized["terminal_blockers"]:
        normalized["reported_status"] = normalized.get("reported_status") or normalized.get("status")
        normalized["status"] = "in_progress"
        normalized["scene_status"] = "in_progress"
        normalized["contract_normalization"] = {
            **_as_dict(normalized.get("contract_normalization")),
            "recoverable_blocked_status_downgraded": True,
        }

    if normalized["pending_jobs"] and status in {"completed", "complete", "success", "succeeded"}:
        normalized["reported_status"] = normalized.get("reported_status") or normalized.get("status")
        normalized["status"] = "partial"
        normalized["scene_status"] = "partial"
        normalized["contract_normalization"] = {
            **_as_dict(normalized.get("contract_normalization")),
            "pending_jobs_prevented_completion": True,
        }
    return normalized


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in {"completed", "complete", "success", "succeeded"}:
        return "completed"
    if status in {"blocked", "wait_human", "waiting_human", "paused"} or status.startswith("blocked_"):
        return "blocked"
    if status in {"partial", "incomplete", "in_progress", "continuable", "continue", "pending", "needs_continuation"}:
        return "in_progress" if status in {"in_progress", "continue", "pending", "needs_continuation"} else "partial"
    return status or "in_progress"


def _derive_pending_jobs(result_data: dict[str, Any]) -> list[Any]:
    observed = _list_value(result_data.get("observed_jobs"))
    if not observed:
        return []
    completed_keys = {_job_key(item) for item in _list_value(result_data.get("completed_job_details"))}
    inactive_keys = {_job_key(item) for item in _list_value(result_data.get("inactive_or_closed_jobs"))}
    pending: list[Any] = []
    for item in observed:
        key = _job_key(item)
        if key and key in completed_keys | inactive_keys:
            continue
        pending.append(item)
    return pending


def _filter_non_jd_sync_items(result_data: dict[str, Any]) -> None:
    removed: dict[str, int] = {}
    for field in ("observed_jobs", "pending_jobs", "action_candidates", "writeback_candidates"):
        items = _list_value(result_data.get(field))
        kept = [item for item in items if not _is_non_jd_sync_item(item, field=field)]
        if len(kept) != len(items):
            removed[field] = len(items) - len(kept)
        result_data[field] = kept
    if removed:
        result_data["contract_normalization"] = {
            **_as_dict(result_data.get("contract_normalization")),
            "filtered_non_jd_items": removed,
        }


def _is_non_jd_sync_item(value: Any, *, field: str) -> bool:
    item = _as_dict(value)
    if not item:
        return False
    labels = {
        _normalized_text(item.get(key))
        for key in ("title", "job_title", "name", "label", "raw_text", "text")
        if _normalized_text(item.get(key))
    }
    nav_labels = {"职位管理", "推荐牛人", "搜索", "沟通", "招聘规范", "我的客服"}
    if labels and labels <= nav_labels:
        return True
    if field == "action_candidates" and labels & nav_labels:
        return True
    joined = _normalized_text(
        " ".join(
            str(item.get(key) or "")
            for key in (
                "title",
                "job_title",
                "name",
                "label",
                "raw_text",
                "text",
                "kind",
                "type",
            )
        )
    )
    if _contains_forbidden_jd_sync_candidate_text(joined):
        return True
    for key in ("job_key", "key", "external_id", "external_url", "detail_url", "url", "href"):
        text = str(item.get(key) or "").strip()
        if _is_boss_job_list_menu_url(text):
            return True
    return False


def _is_boss_job_list_menu_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    path = parsed.path.rstrip("/")
    if path != "/web/chat/job/list":
        return False
    query = parsed.query.lower()
    return not query or "menu-manager-job" in query


def _contains_forbidden_jd_sync_candidate_text(value: str) -> bool:
    text = _normalized_text(value).lower()
    if not text:
        return False
    forbidden_markers = (
        "招聘规范",
        "我的客服",
        "面试",
        "招聘数据",
        "账号权益",
        "升级vip",
        "新建分组",
        "candidate",
        "applicant",
        "resume",
        "chat",
        "conversation",
        "候选人",
        "求职者",
        "牛人",
        "简历",
        "聊天",
        "会话",
        "打招呼",
        "求简历",
        "换电话",
        "换微信",
        "约面试",
        "不合适",
        "关闭职位",
        "停止招聘",
        "下线职位",
        "删除职位",
        "发布职位",
        "刷新职位",
        "曝光刷新",
    )
    if any(marker in text for marker in forbidden_markers):
        return True
    if "+" in text and any(marker in text for marker in ("group", "chat", "conversation", "分组", "沟通", "会话")):
        return True
    destructive_exact = {"关闭", "删除", "发布", "刷新", "升级", "更多", "+"}
    return text in destructive_exact


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _job_key(value: Any) -> str:
    item = _as_dict(value)
    for key in ("job_key", "key", "external_id", "external_url", "detail_url", "title", "job_title", "name"):
        text = str(item.get(key) or "").strip().lower()
        if text:
            return text
    text = str(value or "").strip().lower()
    return text


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple | set):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
