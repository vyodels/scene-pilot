from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from scene_pilot.db.base import utcnow
from scene_pilot.repositories import (
    CandidateRepository,
    CandidateStatusTransitionRepository,
    RecruitmentStateMachineVersionRepository,
)
from scene_pilot.schemas.domain import CandidateStateTransitionRequest, RecruitmentStateMachineUpdate
from scene_pilot.services.recruit_agent import default_candidate_state_snapshot


class StateMachineValidationError(ValueError):
    pass


@dataclass(slots=True)
class StateMachineTransitionResult:
    candidate_id: str
    from_status: str
    to_status: str
    deepest_milestone: str | None
    matched_transition: dict[str, Any] | None
    state_machine: dict[str, Any]
    transition_record: Any


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages/shared/src/data/defaultStateMachine.json").exists():
            return parent
    raise FileNotFoundError("Unable to locate packages/shared/src/data/defaultStateMachine.json")


def _default_state_machine_path() -> Path:
    return _repo_root() / "packages/shared/src/data/defaultStateMachine.json"


def load_default_state_machine_payload() -> dict[str, Any]:
    with _default_state_machine_path().open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return normalize_state_machine_payload(payload)


def normalize_state_machine_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": int(payload.get("version") or 1),
        "updatedAt": str(payload.get("updatedAt") or payload.get("updated_at") or ""),
        "updatedBy": str(payload.get("updatedBy") or payload.get("updated_by") or "system"),
        "changeSummary": payload.get("changeSummary") or payload.get("change_summary"),
        "nodes": list(payload.get("nodes") or []),
        "transitions": list(payload.get("transitions") or []),
        "globalTransitions": list(payload.get("globalTransitions") or payload.get("global_transitions") or []),
        "versionMetadata": dict(payload.get("versionMetadata") or payload.get("version_metadata") or {}),
    }


def _validate_state_machine_payload(payload: dict[str, Any]) -> None:
    node_ids: list[str] = []
    for node in payload["nodes"]:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            raise StateMachineValidationError("State node id is required.")
        node_ids.append(node_id)

    if len(node_ids) != len(set(node_ids)):
        raise StateMachineValidationError("State node ids must be unique.")

    known_node_ids = set(node_ids)
    for transition in [*payload["transitions"], *payload["globalTransitions"]]:
        from_state = str(transition.get("fromState") or transition.get("from_state") or "").strip()
        to_state = str(transition.get("toState") or transition.get("to_state") or "").strip()
        if not to_state:
            raise StateMachineValidationError("Transition toState is required.")
        if to_state not in known_node_ids:
            raise StateMachineValidationError(f"Transition target {to_state} does not exist.")
        if from_state not in {"*", ""} and from_state not in known_node_ids:
            raise StateMachineValidationError(f"Transition source {from_state} does not exist.")


def serialize_state_machine_version(record: Any) -> dict[str, Any]:
    return {
        "version": int(record.version),
        "updatedAt": record.updated_at.isoformat(),
        "updatedBy": str(record.updated_by),
        "changeSummary": record.change_summary,
        "nodes": list(record.nodes_json or []),
        "transitions": list(record.transitions_json or []),
        "globalTransitions": list(record.global_transitions_json or []),
        "versionMetadata": dict(record.version_metadata or {}),
        "publishedAt": record.published_at.isoformat(),
        "createdAt": record.created_at.isoformat(),
    }


def ensure_latest_state_machine(session: Session) -> dict[str, Any]:
    repo = RecruitmentStateMachineVersionRepository(session)
    latest = repo.latest()
    if latest is None:
        seed = load_default_state_machine_payload()
        latest = repo.create(
            {
                "version": int(seed["version"]),
                "updated_by": str(seed["updatedBy"]),
                "change_summary": seed.get("changeSummary"),
                "nodes_json": list(seed["nodes"]),
                "transitions_json": list(seed["transitions"]),
                "global_transitions_json": list(seed["globalTransitions"]),
                "version_metadata": dict(seed.get("versionMetadata") or {}),
            }
        )
    return serialize_state_machine_version(latest)


def list_state_machine_versions(session: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    repo = RecruitmentStateMachineVersionRepository(session)
    ensure_latest_state_machine(session)
    return [serialize_state_machine_version(record) for record in repo.list_versions(limit=limit)]


def get_state_machine_version(session: Session, version: int) -> dict[str, Any] | None:
    repo = RecruitmentStateMachineVersionRepository(session)
    record = repo.get_version(version)
    if record is None:
        return None
    return serialize_state_machine_version(record)


def save_state_machine_version(session: Session, payload: RecruitmentStateMachineUpdate) -> dict[str, Any]:
    normalized = normalize_state_machine_payload(
        {
            "updatedBy": payload.updated_by,
            "changeSummary": payload.change_summary,
            "nodes": payload.nodes,
            "transitions": payload.transitions,
            "globalTransitions": payload.global_transitions,
            "versionMetadata": payload.version_metadata,
        }
    )
    _validate_state_machine_payload(normalized)
    repo = RecruitmentStateMachineVersionRepository(session)
    latest = repo.latest()
    next_version = (latest.version if latest is not None else 0) + 1
    created = repo.create(
        {
            "version": next_version,
            "updated_by": normalized["updatedBy"],
            "change_summary": normalized.get("changeSummary"),
            "nodes_json": normalized["nodes"],
            "transitions_json": normalized["transitions"],
            "global_transitions_json": normalized["globalTransitions"],
            "version_metadata": normalized.get("versionMetadata") or {},
        }
    )
    return serialize_state_machine_version(created)


def available_state_statuses(session: Session) -> list[str]:
    machine = ensure_latest_state_machine(session)
    return [str(node.get("id")) for node in machine["nodes"] if node.get("id")]


def _node_index(state_machine: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): dict(node) for node in state_machine["nodes"]}


def resolve_candidate_current_status(candidate: Any) -> str:
    return str(getattr(candidate, "current_status", None) or "discovered")


def _resolve_actor(payload: CandidateStateTransitionRequest) -> str:
    source = str(payload.source or "").lower()
    actor = str(payload.actor or payload.actor_id or "").lower()
    is_override = bool(payload.override_reason)
    if source == "system":
        return "system"
    if is_override and "agent" in actor:
        return "agent_override"
    if is_override:
        return "recruiter_override"
    if "agent" in actor or source in {"agent", "runtime", "ai"}:
        return "agent"
    return "recruiter"


def _find_transition(
    state_machine: dict[str, Any],
    *,
    from_status: str,
    to_status: str,
) -> dict[str, Any] | None:
    for transition in state_machine["transitions"]:
        if str(transition.get("fromState") or transition.get("from_state")) == from_status and str(
            transition.get("toState") or transition.get("to_state")
        ) == to_status:
            return dict(transition)
    for transition in state_machine["globalTransitions"]:
        if str(transition.get("toState") or transition.get("to_state")) != to_status:
            continue
        from_state = str(transition.get("fromState") or transition.get("from_state") or "")
        if from_state in {"*", from_status}:
            return dict(transition)
    return None


def _milestone_order(state_machine: dict[str, Any]) -> dict[str, int]:
    order: dict[str, int] = {}
    for node in state_machine["nodes"]:
        milestone_id = node.get("milestoneId") or node.get("milestone_id")
        if milestone_id:
            order[str(milestone_id)] = int(node.get("sortOrder") or node.get("sort_order") or 0)
    return order


def _advance_milestone(
    state_machine: dict[str, Any],
    *,
    current_milestone: str | None,
    target_status: str,
) -> str | None:
    node = _node_index(state_machine).get(target_status)
    if node is None:
        return current_milestone
    target_milestone = node.get("milestoneId") or node.get("milestone_id")
    if not target_milestone:
        return current_milestone
    orders = _milestone_order(state_machine)
    current_order = orders.get(str(current_milestone), 0)
    target_order = orders.get(str(target_milestone), 0)
    if target_order > current_order:
        return str(target_milestone)
    return current_milestone


def apply_transition_snapshot(
    candidate: Any,
    payload: CandidateStateTransitionRequest,
    *,
    state_machine: dict[str, Any],
) -> dict[str, Any]:
    current_status = resolve_candidate_current_status(candidate)
    snapshot = dict(candidate.state_snapshot or {}) or default_candidate_state_snapshot(status=current_status)
    nodes = _node_index(state_machine)
    target_node = nodes.get(payload.to_status, {})
    transition_at = utcnow().isoformat()
    snapshot["current_stage_key"] = payload.stage_key or payload.to_status
    snapshot["current_stage_label"] = payload.stage_label or str(target_node.get("label") or snapshot["current_stage_key"]).replace("_", " ")
    snapshot["current_phase_key"] = payload.phase_key or target_node.get("phase") or snapshot.get("current_phase_key")
    snapshot["current_phase_label"] = payload.phase_label or target_node.get("phaseLabel") or snapshot.get("current_phase_label")
    if payload.contact_channels is not None:
        unique_channels = [item for item in dict.fromkeys(payload.contact_channels) if item]
        snapshot["contact_channels"] = unique_channels
        snapshot["contact_acquired"] = bool(unique_channels)
        snapshot["contact_status"] = "acquired" if unique_channels else "missing"
    if payload.to_status == "contact_acquired" and not snapshot.get("contact_channels"):
        contact_info = dict(candidate.contact_info or {})
        channels = [key for key in ("phone", "mobile", "wechat") if contact_info.get(key)]
        snapshot["contact_channels"] = channels
        snapshot["contact_acquired"] = bool(channels)
        snapshot["contact_status"] = "acquired" if channels else "missing"
    if payload.to_status == "resume_requested":
        snapshot["resume_status"] = "requested"
    elif payload.to_status == "resume_received":
        snapshot["resume_status"] = "received"
    if payload.to_status in {"ai_online_passed", "ai_online_rejected", "offline_score_passed", "offline_score_rejected"}:
        snapshot["ai_assessment_status"] = "completed"
    if payload.to_status == "pending_human_review":
        snapshot["human_assessment_status"] = "pending"
    elif payload.to_status in {"human_review_passed", "human_review_rejected"}:
        snapshot["human_assessment_status"] = "completed"
    interview_plan = dict(snapshot.get("interview_plan") or default_candidate_state_snapshot()["interview_plan"])
    rounds = list(interview_plan.get("rounds") or [])
    if payload.interview_round is not None:
        interview_plan["active_round"] = payload.interview_round
        found = False
        for round_item in rounds:
            if int(round_item.get("round") or 0) != payload.interview_round:
                continue
            found = True
            if payload.to_status == "interview_pending":
                round_item["status"] = "waiting_schedule"
            elif payload.to_status == "interview_scheduled":
                round_item["status"] = "scheduled"
            elif payload.to_status == "interview_completed":
                round_item["status"] = "completed"
            elif payload.to_status == "interview_passed":
                round_item["status"] = "passed"
            elif payload.to_status == "interview_rejected":
                round_item["status"] = "rejected"
            round_item["updated_at"] = transition_at
            if payload.note:
                round_item["summary"] = payload.note
        if not found:
            rounds.append(
                {
                    "round": payload.interview_round,
                    "label": f"第 {payload.interview_round} 轮",
                    "status": "scheduled" if payload.to_status == "interview_scheduled" else "waiting_schedule",
                    "updated_at": transition_at,
                    "summary": payload.note,
                }
            )
    interview_plan["rounds"] = rounds
    snapshot["interview_plan"] = interview_plan
    snapshot["latest_note"] = payload.note
    snapshot["latest_transition_at"] = transition_at
    snapshot["latest_transition_source"] = payload.source
    snapshot.setdefault("snapshot_metadata", {})
    snapshot["snapshot_metadata"]["status_machine_version"] = state_machine["version"]
    snapshot["snapshot_metadata"]["current_status"] = payload.to_status
    snapshot["snapshot_metadata"]["manual_override"] = bool(payload.override_reason)
    return snapshot


def transition_candidate(
    session: Session,
    *,
    candidate: Any,
    payload: CandidateStateTransitionRequest,
) -> StateMachineTransitionResult:
    state_machine = ensure_latest_state_machine(session)
    nodes = _node_index(state_machine)
    current_status = resolve_candidate_current_status(candidate)
    if current_status not in nodes:
        current_status = "discovered"
    if payload.to_status not in nodes:
        raise StateMachineValidationError(f"Unknown target status: {payload.to_status}")

    matched_transition = _find_transition(state_machine, from_status=current_status, to_status=payload.to_status)
    if matched_transition is None and not payload.override_reason:
        raise StateMachineValidationError(f"Illegal transition: {current_status} -> {payload.to_status}")

    next_deepest_milestone = _advance_milestone(
        state_machine,
        current_milestone=getattr(candidate, "deepest_milestone", None),
        target_status=payload.to_status,
    )
    milestone_updated = next_deepest_milestone if next_deepest_milestone != getattr(candidate, "deepest_milestone", None) else None
    snapshot = apply_transition_snapshot(candidate, payload, state_machine=state_machine)
    candidate_repo = CandidateRepository(session)
    history_repo = CandidateStatusTransitionRepository(session)
    contact_info = dict(candidate.contact_info or {})
    if payload.contact_channels is not None:
        if "phone" in payload.contact_channels or "mobile" in payload.contact_channels:
            contact_info.setdefault("has_phone", True)
        if "wechat" in payload.contact_channels:
            contact_info.setdefault("has_wechat", True)
        candidate.contact_info = contact_info
    updated_candidate = candidate_repo.update_state_snapshot(
        candidate,
        current_status=payload.to_status,
        deepest_milestone=next_deepest_milestone,
        snapshot=snapshot,
    )
    updated_candidate.current_stage_key = payload.stage_key or payload.to_status
    session.commit()
    session.refresh(updated_candidate)

    actor = _resolve_actor(payload)
    trigger = payload.trigger or str(
        (matched_transition or {}).get("label")
        or (matched_transition or {}).get("condition")
        or (matched_transition or {}).get("trigger")
        or payload.source
    )
    from_node = nodes[current_status]
    to_node = nodes[payload.to_status]

    transition_record = history_repo.create(
        {
            "candidate_id": updated_candidate.id,
            "from_status": current_status,
            "to_status": payload.to_status,
            "from_status_label": str(from_node.get("label") or current_status),
            "to_status_label": str(to_node.get("label") or payload.to_status),
            "actor": actor,
            "actor_id": payload.actor_id or payload.actor,
            "trigger": trigger,
            "note": payload.note,
            "override_reason": payload.override_reason,
            "is_override": bool(payload.override_reason),
            "milestone_updated": milestone_updated,
            "transition_metadata": {
                **dict(payload.metadata or {}),
                "matched_transition_id": (matched_transition or {}).get("id"),
                "matched_trigger": (matched_transition or {}).get("trigger"),
                "phase": str(to_node.get("phase") or ""),
                "phase_label": str(to_node.get("phaseLabel") or ""),
                "interview_round": payload.interview_round,
                "contact_channels": payload.contact_channels,
            },
        }
    )
    return StateMachineTransitionResult(
        candidate_id=updated_candidate.id,
        from_status=current_status,
        to_status=payload.to_status,
        deepest_milestone=next_deepest_milestone,
        matched_transition=matched_transition,
        state_machine=state_machine,
        transition_record=transition_record,
    )
