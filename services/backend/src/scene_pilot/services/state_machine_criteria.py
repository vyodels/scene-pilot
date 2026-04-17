from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from scene_pilot.models import CandidateStatusTransition
from scene_pilot.repositories import SkillRepository
from scene_pilot.services.state_machine import ensure_latest_state_machine

_MIN_SAMPLE_SIZE = 3
_THRESHOLD_DELTA = 5
_OVERRIDE_RATE_FOR_THRESHOLD = 0.25
_OVERRIDE_RATE_FOR_SKILL_SWAP = 0.35
_HEALTHY_SKILL_STATUSES = {"", "healthy", "approved", "active"}
_SKILL_SWAP_HEALTH_PRIORITY = {
    "healthy": 0,
    "approved": 1,
    "active": 2,
    "": 3,
    "unknown": 3,
    "warning": 4,
    "degraded": 5,
    "critical": 6,
}


def list_state_machine_criteria_suggestions(session: Session) -> list[dict[str, Any]]:
    state_machine = ensure_latest_state_machine(session)
    nodes = [dict(node) for node in list(state_machine.get("nodes") or []) if isinstance(node, dict)]
    if not nodes:
        return []

    relevant_nodes = [
        node
        for node in nodes
        if str(((node.get("executionConfig") or {}).get("mode") or "")).strip() == "ai_auto"
        and isinstance((node.get("executionConfig") or {}).get("criteriaRef"), dict)
    ]
    if not relevant_nodes:
        return []

    status_ids = [str(node.get("id") or "").strip() for node in relevant_nodes if str(node.get("id") or "").strip()]
    if not status_ids:
        return []

    stmt = (
        select(CandidateStatusTransition)
        .where(
            CandidateStatusTransition.from_status.in_(tuple(status_ids)),
            CandidateStatusTransition.actor.in_(("agent", "agent_override", "recruiter_override")),
        )
        .order_by(CandidateStatusTransition.created_at.desc(), CandidateStatusTransition.id.desc())
    )
    transitions = list(session.scalars(stmt).all())
    transitions_by_status: dict[str, list[CandidateStatusTransition]] = defaultdict(list)
    for item in transitions:
        transitions_by_status[str(item.from_status)].append(item)

    node_order = {
        str(node.get("id") or ""): int(node.get("sortOrder") or node.get("sort_order") or 0)
        for node in nodes
    }
    node_index = {
        str(node.get("id") or ""): node
        for node in nodes
    }
    node_labels = {
        str(node.get("id") or ""): str(node.get("label") or node.get("id") or "")
        for node in nodes
    }
    skill_repo = SkillRepository(session)

    reports: list[dict[str, Any]] = []
    for node in relevant_nodes:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        criteria_ref = dict((node.get("executionConfig") or {}).get("criteriaRef") or {})
        status_transitions = transitions_by_status.get(node_id, [])
        if not status_transitions:
            continue

        ai_decision_count = sum(1 for item in status_transitions if str(item.actor) in {"agent", "agent_override"})
        recruiter_overrides = [item for item in status_transitions if str(item.actor) == "recruiter_override"]
        recruiter_override_count = len(recruiter_overrides)
        sample_size = ai_decision_count + recruiter_override_count
        if sample_size <= 0:
            continue

        current_order = node_order.get(node_id, 0)
        deeper_override_count = 0
        shallower_override_count = 0
        for item in recruiter_overrides:
            target_node = dict(node_index.get(str(item.to_status)) or {})
            target_order = node_order.get(str(item.to_status), current_order)
            if bool(target_node.get("isTerminal")) and not bool(target_node.get("isSuccess")):
                shallower_override_count += 1
            elif bool(target_node.get("isSuccess")) or target_order > current_order:
                deeper_override_count += 1
            else:
                shallower_override_count += 1

        accuracy_rate = round((sample_size - recruiter_override_count) / sample_size, 4)
        override_rate = round(recruiter_override_count / sample_size, 4)

        current_skill_id = str(criteria_ref.get("skillId") or "").strip() or None
        current_skill = skill_repo.by_skill_id(current_skill_id) if current_skill_id else None
        current_skill_name = current_skill.name if current_skill is not None else None

        suggestions: list[dict[str, Any]] = []
        threshold_suggestion = _build_threshold_suggestion(
            criteria_ref=criteria_ref,
            override_rate=override_rate,
            sample_size=sample_size,
            deeper_override_count=deeper_override_count,
            shallower_override_count=shallower_override_count,
        )
        if threshold_suggestion is not None:
            suggestions.append(threshold_suggestion)

        skill_suggestion = _build_skill_swap_suggestion(
            skill_repo=skill_repo,
            current_skill=current_skill,
            current_skill_id=current_skill_id,
            override_rate=override_rate,
        )
        if skill_suggestion is not None:
            suggestions.append(skill_suggestion)

        reports.append(
            {
                "node_id": node_id,
                "node_label": str(node.get("label") or node_id),
                "current_criteria_ref": criteria_ref,
                "current_skill_id": current_skill_id,
                "current_skill_name": current_skill_name,
                "metrics": {
                    "sample_size": sample_size,
                    "ai_decision_count": ai_decision_count,
                    "recruiter_override_count": recruiter_override_count,
                    "accuracy_rate": accuracy_rate,
                    "override_rate": override_rate,
                    "deeper_override_count": deeper_override_count,
                    "shallower_override_count": shallower_override_count,
                },
                "suggestions": suggestions,
                "summary": _build_report_summary(
                    node_label=str(node.get("label") or node_id),
                    sample_size=sample_size,
                    override_rate=override_rate,
                    recruiter_override_count=recruiter_override_count,
                    current_skill_name=current_skill_name,
                    node_labels=node_labels,
                    recruiter_overrides=recruiter_overrides,
                ),
            }
        )

    return sorted(
        reports,
        key=lambda item: (
            -len(list(item.get("suggestions") or [])),
            -float((dict(item.get("metrics") or {})).get("override_rate") or 0),
            str(item.get("node_label") or ""),
        ),
    )


def _build_threshold_suggestion(
    *,
    criteria_ref: dict[str, Any],
    override_rate: float,
    sample_size: int,
    deeper_override_count: int,
    shallower_override_count: int,
) -> dict[str, Any] | None:
    if str(criteria_ref.get("type") or "") != "skill":
        return None
    threshold = criteria_ref.get("passThreshold")
    if not isinstance(threshold, (int, float)):
        return None
    if sample_size < _MIN_SAMPLE_SIZE or override_rate < _OVERRIDE_RATE_FOR_THRESHOLD:
        return None
    if deeper_override_count == shallower_override_count:
        return None

    direction = "lower" if deeper_override_count > shallower_override_count else "raise"
    next_threshold = int(round(float(threshold))) - _THRESHOLD_DELTA if direction == "lower" else int(round(float(threshold))) + _THRESHOLD_DELTA
    next_threshold = max(0, min(100, next_threshold))
    if next_threshold == int(round(float(threshold))):
        return None

    summary = "人工多次把 AI 判定纠正为继续推进，建议适度下调通过阈值。"
    rationale = f"最近 {sample_size} 次决策中有 {round(override_rate * 100)}% 被人工覆盖，且更多覆盖指向更深节点。"
    if direction == "raise":
        summary = "人工多次把 AI 判定纠正为更保守结果，建议适度上调通过阈值。"
        rationale = f"最近 {sample_size} 次决策中有 {round(override_rate * 100)}% 被人工覆盖，且更多覆盖指向更早或拒绝节点。"

    proposed = dict(criteria_ref)
    proposed["passThreshold"] = next_threshold
    return {
        "kind": "adjust_threshold",
        "summary": summary,
        "rationale": rationale,
        "confidence": "high" if sample_size >= 8 else "medium",
        "proposed_criteria_ref": proposed,
    }


def _build_skill_swap_suggestion(
    *,
    skill_repo: SkillRepository,
    current_skill,
    current_skill_id: str | None,
    override_rate: float,
) -> dict[str, Any] | None:
    if current_skill is None or not current_skill_id:
        return None
    stage_key = str(current_skill.bound_to_stage or "").strip()
    alternatives = [
        skill
        for skill in skill_repo.active_for_stage(stage_key, platform=current_skill.platform)
        if skill.skill_id != current_skill_id
    ] if stage_key else []
    if not alternatives:
        return None

    health_status = str(current_skill.last_health_status or "").strip().lower()
    should_swap = health_status not in _HEALTHY_SKILL_STATUSES or override_rate >= _OVERRIDE_RATE_FOR_SKILL_SWAP
    if not should_swap:
        return None

    candidate = sorted(alternatives, key=_skill_swap_sort_key)[0]
    proposed = {"type": "skill", "skillId": candidate.skill_id}
    if isinstance(current_skill.skill_metadata, dict):
        pass_threshold = ((current_skill.skill_metadata or {}).get("passThreshold"))
        if isinstance(pass_threshold, (int, float)):
            proposed["passThreshold"] = int(round(float(pass_threshold)))

    candidate_health = str(candidate.last_health_status or "unknown")
    summary = f"当前 Skill「{current_skill.name}」健康度偏低或覆盖率偏高，建议切换到「{candidate.name}」。"
    rationale = (
        f"当前 Skill 状态为 {current_skill.last_health_status or 'unknown'}，"
        f"最近人工覆盖率约 {round(override_rate * 100)}%，"
        f"候选 Skill 中优先选择健康度更高、版本更稳的「{candidate.name}」（health={candidate_health}，v{candidate.version}）。"
    )
    return {
        "kind": "switch_skill",
        "summary": summary,
        "rationale": rationale,
        "confidence": "medium",
        "proposed_criteria_ref": proposed,
        "suggested_skill_id": candidate.skill_id,
        "suggested_skill_name": candidate.name,
    }


def _skill_swap_sort_key(skill) -> tuple[int, int, int, float, str]:
    health_status = str(skill.last_health_status or "").strip().lower()
    health_priority = _SKILL_SWAP_HEALTH_PRIORITY.get(health_status, _SKILL_SWAP_HEALTH_PRIORITY["unknown"])
    observed_outcomes = (skill.execution_hints or {}).get("observed_outcomes") if isinstance(skill.execution_hints, dict) else []
    observed_count = len(observed_outcomes) if isinstance(observed_outcomes, list) else 0
    version = int(skill.version or 0)
    raw_updated_at = getattr(skill, "updated_at", None)
    if raw_updated_at is None:
        updated_at = 0.0
    elif isinstance(raw_updated_at, int):
        updated_at = float(raw_updated_at)
    else:
        updated_at = raw_updated_at.timestamp()
    return (
        health_priority,
        -observed_count,
        -version,
        -updated_at,
        str(skill.name or skill.skill_id or ""),
    )


def _build_report_summary(
    *,
    node_label: str,
    sample_size: int,
    override_rate: float,
    recruiter_override_count: int,
    current_skill_name: str | None,
    node_labels: dict[str, str],
    recruiter_overrides: list[CandidateStatusTransition],
) -> str:
    latest_target = None
    if recruiter_overrides:
        latest_target = node_labels.get(str(recruiter_overrides[0].to_status)) or str(recruiter_overrides[0].to_status)
    base = f"{node_label} 最近累计 {sample_size} 次可分析决策，其中 {recruiter_override_count} 次为人工覆盖。"
    if current_skill_name:
        base = f"{base} 当前 Skill 为 {current_skill_name}。"
    if latest_target:
        base = f"{base} 最近一次人工纠偏流向 {latest_target}。"
    return f"{base} 覆盖率约为 {round(override_rate * 100)}%。"
