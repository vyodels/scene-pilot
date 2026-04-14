from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_session
from scene_pilot.db.base import utcnow
from scene_pilot.repositories import AgentLearningRepository, ApprovalRepository, SkillRepository
from scene_pilot.schemas import ApprovalCreate, ApprovalDecisionRequest, ApprovalRead, ApprovalUpdate
from scene_pilot.services.container import AppContainer
from scene_pilot.api.deps import get_container

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalRead])
def list_approvals(
    pending_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ApprovalRead]:
    repo = ApprovalRepository(session)
    items = repo.pending(limit=limit, offset=offset) if pending_only else repo.list(limit=limit, offset=offset)
    return [ApprovalRead.model_validate(item) for item in items]


@router.post("", response_model=ApprovalRead, status_code=201)
def create_approval(payload: ApprovalCreate, session: Session = Depends(get_session)) -> ApprovalRead:
    item = ApprovalRepository(session).create(payload)
    return ApprovalRead.model_validate(item)


@router.patch("/{approval_id}", response_model=ApprovalRead)
def update_approval(
    approval_id: str,
    payload: ApprovalUpdate,
    session: Session = Depends(get_session),
) -> ApprovalRead:
    repo = ApprovalRepository(session)
    item = repo.get(approval_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    updated = repo.update(item, payload)
    return ApprovalRead.model_validate(updated)


@router.post("/{approval_id}/approve", response_model=ApprovalRead)
def approve_approval(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> ApprovalRead:
    repo = ApprovalRepository(session)
    item = repo.get(approval_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if item.target_type == "blocked_task":
        item = container.agent_control.apply_approval_resolution(
            session,
            item,
            status="approved",
            reviewer=payload.reviewer,
            notes=payload.reason,
        )
    else:
        payload_snapshot = dict(item.payload or {})
        resumed_task = _extract_resume_task(payload_snapshot)
        resolution = _build_resolution_snapshot(
            status="approved",
            reviewer=payload.reviewer,
            reason=payload.reason,
            resumed_task=resumed_task,
        )
        if item.target_type == "skill_draft":
            promoted_skill = _promote_skill_draft(session, container, item, reviewer=payload.reviewer, reason=payload.reason)
            if promoted_skill is not None:
                payload_snapshot["promoted_skill"] = promoted_skill
                resolution["promoted_skill_id"] = promoted_skill["id"]
                resolution["promoted_skill_status"] = promoted_skill["status"]
        elif item.target_type == "system_command":
            item = container.system_commands.apply_resolution(
                item,
                status="approved",
                reviewer=payload.reviewer,
                notes=payload.reason,
            )
            payload_snapshot = dict(item.payload or {})
            payload_snapshot.setdefault("command_resolution", _build_system_command_resolution(container, payload_snapshot))
            resolution = dict(payload_snapshot.get("resolution") or resolution)

        payload_snapshot["resolution"] = resolution
        if resumed_task is not None:
            payload_snapshot["resumed_task_id"] = resumed_task.get("task_id")
            payload_snapshot["resumed_at"] = resolution["reviewed_at"]
            container.agent_control.enqueue_task(
                str(resumed_task["task_type"]),
                task_id=str(resumed_task.get("task_id") or approval_id),
                payload=dict(resumed_task.get("payload") or {}),
                metadata={
                    **dict(resumed_task.get("metadata") or {}),
                    "resumed_from_approval_id": item.id,
                    "approval_target_type": item.target_type,
                    "approval_target_id": item.target_id,
                    "resume_reason": payload.reason,
                },
                priority=int(resumed_task.get("priority", 100) or 100),
                candidate_id=resumed_task.get("candidate_id"),
                workflow_id=resumed_task.get("workflow_id"),
                workflow_node_id=resumed_task.get("workflow_node_id"),
            )
            payload_snapshot["resume_task"] = resumed_task
        item.payload = payload_snapshot
    updated = repo.mark_review(item, "approved", reviewer=payload.reviewer, notes=payload.reason)
    return ApprovalRead.model_validate(updated)


@router.post("/{approval_id}/reject", response_model=ApprovalRead)
def reject_approval(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> ApprovalRead:
    repo = ApprovalRepository(session)
    item = repo.get(approval_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if item.target_type == "blocked_task":
        item = container.agent_control.apply_approval_resolution(
            session,
            item,
            status="rejected",
            reviewer=payload.reviewer,
            notes=payload.reason,
        )
    else:
        payload_snapshot = dict(item.payload or {})
        payload_snapshot["resolution"] = _build_resolution_snapshot(
            status="rejected",
            reviewer=payload.reviewer,
            reason=payload.reason,
            resumed_task=None,
        )
        payload_snapshot["closed_at"] = payload_snapshot["resolution"]["reviewed_at"]
        if item.target_type == "skill_draft":
            _deactivate_learning_draft(session, payload_snapshot)
        elif item.target_type == "system_command":
            item = container.system_commands.apply_resolution(
                item,
                status="rejected",
                reviewer=payload.reviewer,
                notes=payload.reason,
            )
            payload_snapshot = dict(item.payload or {})
            payload_snapshot.setdefault(
                "command_resolution",
                {
                    **_build_system_command_resolution(container, payload_snapshot),
                    "execution_status": "rejected",
                },
            )
            payload_snapshot.setdefault("closed_at", utcnow().isoformat())
        item.payload = payload_snapshot
    updated = repo.mark_review(item, "rejected", reviewer=payload.reviewer, notes=payload.reason)
    return ApprovalRead.model_validate(updated)


def _extract_resume_task(payload: dict[str, object]) -> dict[str, object] | None:
    resume_task = payload.get("resume_task")
    if isinstance(resume_task, dict) and resume_task.get("task_type"):
        return dict(resume_task)

    follow_up = payload.get("follow_up_task")
    if isinstance(follow_up, dict) and follow_up.get("task_type"):
        return dict(follow_up)

    blocked_task = payload.get("blocked_task")
    if isinstance(blocked_task, dict) and blocked_task.get("task_type") and payload.get("resume_on_approve", True):
        return dict(blocked_task)

    return None


def _build_resolution_snapshot(
    *,
    status: str,
    reviewer: str,
    reason: str | None,
    resumed_task: dict[str, object] | None,
) -> dict[str, object]:
    reviewed_at = utcnow().isoformat()
    resolution: dict[str, object] = {
        "status": status,
        "reviewer": reviewer,
        "reason": reason,
        "reviewed_at": reviewed_at,
        "resumed": resumed_task is not None and status == "approved",
    }
    if resumed_task is not None and status == "approved":
        resolution["resumed_task_id"] = resumed_task.get("task_id")
        resolution["resumed_task_type"] = resumed_task.get("task_type")
    return resolution


def _promote_skill_draft(
    session: Session,
    container: AppContainer,
    approval,
    *,
    reviewer: str,
    reason: str | None,
) -> dict[str, object] | None:
    payload = dict(approval.payload or {})
    draft = payload.get("skill_draft")
    if not isinstance(draft, dict):
        return None

    repo = SkillRepository(session)
    learning_repo = AgentLearningRepository(session)
    learning_id = payload.get("learning_id")
    learning = learning_repo.get(str(learning_id)) if isinstance(learning_id, str) and learning_id else None

    skill_name = str(draft.get("skill_name") or draft.get("name") or approval.title).strip()
    skill_key = str(draft.get("skill_id") or _slugify(skill_name)).strip("_")
    if learning is not None and not draft.get("skill_id"):
        skill_key = f"{skill_key}_{learning.id[:8]}"
    skill_key = skill_key or f"runtime_skill_{approval.id[:8]}"

    strategy = draft.get("strategy")
    if not isinstance(strategy, dict):
        strategy = {}
    if not strategy:
        seed_instruction = draft.get("content") or draft.get("summary")
        if isinstance(seed_instruction, str) and seed_instruction.strip():
            strategy = {"instruction": seed_instruction.strip()}

    execution_hints = draft.get("execution_hints")
    if not isinstance(execution_hints, dict):
        execution_hints = {}

    version_governance = draft.get("version_governance")
    if not isinstance(version_governance, dict):
        version_governance = {}

    health_check_config = draft.get("health_check_config")
    if not isinstance(health_check_config, dict):
        health_check_config = {}
    if not health_check_config:
        health_check_config = {"expected_result_status": "pass"}

    status = "active" if container.flags.is_enabled("skills.auto_activate") else "approved"
    platform = (
        str(draft.get("platform") or "").strip()
        or str(payload.get("task_domain") or "").strip()
        or str(execution_hints.get("domain") or "").strip()
        or "runtime-scene"
    )
    existing = repo.by_skill_id(skill_key)
    next_version = int(existing.version) + 1 if existing is not None else 1
    defaults = {
        "skill_id": skill_key,
        "name": skill_name,
        "version": next_version,
        "status": status,
        "platform": platform,
        "bound_to_workflow_node": draft.get("bound_to_workflow_node") or payload.get("workflow_node_id"),
        "strategy": {
            **strategy,
            "version_governance": {
                **dict(strategy.get("version_governance") or {}),
                **version_governance,
                "approved_by": reviewer,
                "approved_reason": reason,
                "approved_at": utcnow().isoformat(),
            },
        },
        "execution_hints": {
            **execution_hints,
            "version_governance": {
                **dict(execution_hints.get("version_governance") or {}),
                **version_governance,
                "skill_version": next_version,
            },
        },
        "health_check_config": {
            **health_check_config,
            "version_governance": {
                **dict(health_check_config.get("version_governance") or {}),
                **version_governance,
                "skill_version": next_version,
            },
        },
        "confirmed_by": reviewer,
        "confirmed_at": utcnow(),
        "last_health_status": reason or ("healthy" if status == "active" else "approved"),
    }

    skill = repo.update(existing, defaults) if existing is not None else repo.create(defaults)
    if learning is not None:
        learning.consolidated_at = utcnow()
        session.commit()

    return {
        "id": skill.id,
        "skill_id": skill.skill_id,
        "name": skill.name,
        "status": skill.status,
    }


def _build_system_command_resolution(container: AppContainer, payload: dict[str, object]) -> dict[str, object]:
    command = payload.get("command")
    normalized = list(command) if isinstance(command, list) else []
    policy = container.system_commands.policy_snapshot()
    return {
        "command": normalized,
        "execution_status": "approved_not_executed" if not policy["executionEnabled"] else "approved_ready",
        "execution_enabled": bool(policy["executionEnabled"]),
        "approved_at": utcnow().isoformat(),
    }


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return normalized.strip("_")


def _deactivate_learning_draft(session: Session, payload: dict[str, object]) -> None:
    learning_id = payload.get("learning_id")
    if not isinstance(learning_id, str) or not learning_id.strip():
        return
    repo = AgentLearningRepository(session)
    item = repo.get(learning_id)
    if item is None:
        return
    repo.set_active(item, False)
