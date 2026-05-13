from __future__ import annotations

from functools import lru_cache
from typing import Any

from recruit_agent.asset_paths import scene_templates_root

SHARED_WORKSPACE_SCOPE_REF = "workspace:shared"

_META_SECTION = "__meta__"
_SUMMARY_SECTION = "summary"
_INSTRUCTION_SECTION = "instruction"
_CONSTRAINTS_SECTION = "constraints"
_SUCCESS_CRITERIA_SECTION = "success criteria"
_CONTEXT_HINTS_SECTION = "context hints"
_TRIAL_BUDGET_SECTION = "trial budget"

_SOURCE_SURFACE_MARKERS: dict[str, tuple[str, ...]] = {
    "browser_accessible_recruiting_pages": ("职位列表", "职位详情", "jd", "招聘平台", "招聘页面"),
    "browser_accessible_candidate_pages": ("候选人来源", "候选人列表", "人才库", "人才页", "推荐列表", "来源页面"),
}
_SOURCE_SURFACE_BLOCKERS: dict[str, str] = {
    "browser_accessible_recruiting_pages": (
        "当前缺少可用的招聘页面，Agent 应先复用现有页面或自行打开招聘平台页面；"
        "只有在登录、验证码、权限或浏览器能力受限时才需要 human 介入。"
    ),
    "browser_accessible_candidate_pages": (
        "当前缺少可用的候选人来源页面，Agent 应先复用现有页面或自行打开招聘平台页面；"
        "只有在登录、验证码、权限或浏览器能力受限时才需要 human 介入。"
    ),
}
_HUMAN_ONLY_BLOCKER = "当前业务动作被登录、验证码、权限或浏览器能力限制阻塞，需要 human 介入后继续。"
_CANDIDATE_DATA_GAP_BLOCKER = "当前没有可继续处理的候选人数据，需要先补充候选人来源或筛选结果。"
_GENERIC_BUSINESS_BLOCKER = "当前业务动作受阻，需要 human 补充业务上下文后继续。"


def shared_scene_template_catalog() -> dict[str, dict[str, Any]]:
    return dict(_load_shared_scene_template_catalog())


def serialize_scene_template(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": template["key"],
        "title": template["title"],
        "summary": template["summary"],
        "action_kind": template["action_kind"],
        "actionKind": template["action_kind"],
        "default_instruction": template["default_instruction"],
        "defaultInstruction": template["default_instruction"],
        "requires_jd": bool(template.get("requires_jd")),
        "requiresJd": bool(template.get("requires_jd")),
        "supports_candidate_count_target": bool(template.get("supports_candidate_count_target")),
        "supportsCandidateCountTarget": bool(template.get("supports_candidate_count_target")),
        "default_candidate_count_target": template.get("default_candidate_count_target"),
        "defaultCandidateCountTarget": template.get("default_candidate_count_target"),
        "direct_runnable": bool(template.get("direct_runnable")),
        "directRunnable": bool(template.get("direct_runnable")),
        "constraints": dict(template.get("constraints") or {}),
        "success_criteria": dict(template.get("success_criteria") or {}),
        "successCriteria": dict(template.get("success_criteria") or {}),
        "context_hints": dict(template.get("context_hints") or {}),
        "contextHints": dict(template.get("context_hints") or {}),
        "trial_budget": dict(template.get("trial_budget") or {}),
        "trialBudget": dict(template.get("trial_budget") or {}),
    }


def resolve_scene_action_definition(action_kind: str | None, *, run_title: str | None = None) -> dict[str, Any]:
    normalized_action_kind = str(action_kind or "").strip().lower()
    template = shared_scene_template_catalog().get(normalized_action_kind or "") or {}
    constraints = dict(template.get("constraints") or {})
    success_criteria = dict(template.get("success_criteria") or {})
    target_entity = str(constraints.get("target_entity") or success_criteria.get("entity") or "").strip().lower()
    source_surface = str(constraints.get("source_surface") or "").strip().lower() or None
    return {
        "action_kind": normalized_action_kind or "unknown",
        "action_label": str(run_title or template.get("title") or normalized_action_kind or "业务动作").strip() or "业务动作",
        "target_entity": target_entity,
        "source_surface": source_surface,
        "summary_mode": _resolve_summary_mode(
            action_kind=normalized_action_kind,
            constraints=constraints,
            success_criteria=success_criteria,
            target_entity=target_entity,
        ),
    }


def source_surface_markers(source_surface: str | None) -> tuple[str, ...]:
    key = str(source_surface or "").strip().lower()
    return _SOURCE_SURFACE_MARKERS.get(key, ())


def infer_source_surface(text: str) -> str | None:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return None
    for source_surface, markers in _SOURCE_SURFACE_MARKERS.items():
        if any(marker.lower() in normalized for marker in markers):
            return source_surface
    return None


def summarize_business_action(
    scene_action: dict[str, Any],
    *,
    status: str,
    created: int = 0,
    updated: int = 0,
    skipped: int = 0,
    discovered_count: int = 0,
    blocker_kind: str | None = None,
) -> dict[str, str | None]:
    action_label = str(scene_action.get("action_label") or "业务动作").strip() or "业务动作"
    blocker = _blocker_message(scene_action, blocker_kind)
    if blocker:
        return {"summary": f"{action_label}受阻：{blocker}", "blocker": blocker}

    summary_mode = str(scene_action.get("summary_mode") or "").strip().lower()
    if summary_mode == "job_description_sync":
        return {
            "summary": f"{action_label}状态：新增 {created}，更新 {updated}，跳过 {skipped}。",
            "blocker": None,
        }
    if summary_mode == "candidate_discovery":
        return {
            "summary": f"{action_label}状态：新增/确认 {discovered_count} 名候选人。",
            "blocker": None,
        }
    return {"summary": f"{action_label}状态：{status}。", "blocker": None}


@lru_cache(maxsize=1)
def _load_shared_scene_template_catalog() -> dict[str, dict[str, Any]]:
    ordered_templates: list[dict[str, Any]] = []
    for path in sorted(_scene_templates_root().glob("*.md")):
        template = _parse_scene_template_doc(path)
        ordered_templates.append(template)
    ordered_templates.sort(key=lambda item: (int(item.get("display_order", 1000)), str(item.get("key") or "")))

    catalog: dict[str, dict[str, Any]] = {}
    for template in ordered_templates:
        catalog[template["key"]] = template
    return catalog


def _parse_scene_template_doc(path) -> dict[str, Any]:
    title, sections = _parse_markdown_sections(path)
    metadata = _parse_mapping_block(path=path, block_name="Meta", lines=sections.get(_META_SECTION, []))
    constraints = _parse_mapping_block(path=path, block_name="Constraints", lines=sections.get(_CONSTRAINTS_SECTION, []))
    success_criteria = _parse_mapping_block(
        path=path,
        block_name="Success Criteria",
        lines=sections.get(_SUCCESS_CRITERIA_SECTION, []),
    )
    context_hints = _parse_mapping_block(path=path, block_name="Context Hints", lines=sections.get(_CONTEXT_HINTS_SECTION, []))
    trial_budget = _parse_mapping_block(path=path, block_name="Trial Budget", lines=sections.get(_TRIAL_BUDGET_SECTION, []))

    key = str(metadata.get("key") or path.stem).strip()
    action_kind = str(metadata.get("action_kind") or key).strip()
    template: dict[str, Any] = {
        "key": key,
        "title": title,
        "summary": _parse_text_block(path=path, block_name="Summary", lines=sections.get(_SUMMARY_SECTION, [])),
        "action_kind": action_kind,
        "default_instruction": _parse_text_block(path=path, block_name="Instruction", lines=sections.get(_INSTRUCTION_SECTION, [])),
        "requires_jd": bool(metadata.get("requires_jd", False)),
        "supports_candidate_count_target": bool(metadata.get("supports_candidate_count_target", False)),
        "direct_runnable": bool(metadata.get("direct_runnable", False)),
        "constraints": constraints,
        "success_criteria": success_criteria,
        "context_hints": context_hints,
        "trial_budget": trial_budget,
    }
    if "default_candidate_count_target" in metadata:
        template["default_candidate_count_target"] = metadata["default_candidate_count_target"]
    if "display_order" in metadata:
        template["display_order"] = metadata["display_order"]
    return template


def _resolve_summary_mode(
    *,
    action_kind: str,
    constraints: dict[str, Any],
    success_criteria: dict[str, Any],
    target_entity: str,
) -> str:
    if target_entity == "job_description" and str(constraints.get("sync_mode") or "").strip():
        return "job_description_sync"
    if str(success_criteria.get("outcome") or "").strip().lower() == "candidate_discovery":
        return "candidate_discovery"
    if action_kind.startswith("candidate_discovery"):
        return "candidate_discovery"
    return "generic"


def _blocker_message(scene_action: dict[str, Any], blocker_kind: str | None) -> str | None:
    normalized = str(blocker_kind or "").strip().lower()
    if not normalized:
        return None
    if normalized == "human_only":
        return _HUMAN_ONLY_BLOCKER
    if normalized == "missing_source_surface":
        source_surface = str(scene_action.get("source_surface") or "").strip().lower()
        return _SOURCE_SURFACE_BLOCKERS.get(source_surface, _GENERIC_BUSINESS_BLOCKER)
    if normalized == "no_candidate_data":
        return _CANDIDATE_DATA_GAP_BLOCKER
    return _GENERIC_BUSINESS_BLOCKER


def _parse_markdown_sections(path) -> tuple[str, dict[str, list[str]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    title = ""
    sections: dict[str, list[str]] = {_META_SECTION: []}
    current_section = _META_SECTION
    for line in lines:
        stripped = line.strip()
        if not stripped and current_section == _META_SECTION and not sections[_META_SECTION]:
            continue
        if stripped.startswith("# "):
            if not title:
                title = stripped[2:].strip()
                continue
        if stripped.startswith("## "):
            current_section = stripped[3:].strip().lower()
            sections.setdefault(current_section, [])
            continue
        sections.setdefault(current_section, []).append(line)
    if not title:
        raise ValueError(f"Scene template doc missing title heading: {path}")
    return title, sections


def _parse_mapping_block(*, path: Path, block_name: str, lines: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        if not stripped.startswith("- ") or ":" not in stripped[2:]:
            raise ValueError(f"Scene template doc has invalid {block_name} entry: {path}: {raw_line}")
        key, raw_value = stripped[2:].split(":", 1)
        payload[key.strip()] = _coerce_scalar(raw_value.strip())
    return payload


def _parse_text_block(*, path: Path, block_name: str, lines: list[str]) -> str:
    text = "\n".join(line.rstrip() for line in lines).strip()
    if not text:
        raise ValueError(f"Scene template doc missing {block_name}: {path}")
    return text


def _coerce_scalar(value: str) -> Any:
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if lowered.lstrip("-").isdigit():
        return int(lowered)
    return normalized


def _scene_templates_root():
    return scene_templates_root()
