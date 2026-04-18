from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from scene_pilot.api.deps import get_container
from scene_pilot.repositories.domain import TaskQueueRepository
from scene_pilot.schemas.domain import (
    AgentQueueItemRead,
    AgentQueueRecoveryRead,
    AgentRunRead,
    AgentStatusRead,
    AgentTaskCreate,
    AgentTaskEnqueueRead,
    ApprovalRead,
)
from scene_pilot.services.container import AppContainer
from scene_pilot.services.system_commands import SystemCommandApprovalError, SystemCommandDisabledError, SystemCommandPolicyError

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _timestamp(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.isdigit():
            return int(raw)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    return None


class SystemCommandRequest(BaseModel):
    command: list[str] = Field(min_length=1)
    rationale: str | None = None
    requested_by: str = "desktop-user"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SystemCommandExecuteRequest(BaseModel):
    requested_by: str = "desktop-user"


@router.get("", response_model=AgentStatusRead)
def get_agent_status(container: AppContainer = Depends(get_container)) -> AgentStatusRead:
    return container.dashboard.build_agent_status(queue_depth=container.scheduler.queue.size())


@router.post("/tasks", response_model=AgentTaskEnqueueRead)
def enqueue_task(
    payload: AgentTaskCreate,
    container: AppContainer = Depends(get_container),
) -> AgentTaskEnqueueRead:
    resolved_application_id = str(payload.application_id or "").strip() or None
    try:
        task = container.agent_control.enqueue_task(
            payload.task_type,
            payload=payload.payload,
            metadata={
                "task_spec_id": payload.task_spec_id,
                "execution_plan_id": payload.execution_plan_id,
                "execution_episode_id": payload.execution_episode_id,
                "requested_by": payload.requested_by,
                "mode": payload.mode,
            },
            priority=payload.priority,
            application_id=resolved_application_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AgentTaskEnqueueRead(
        task_id=task.task_id,
        task_type=task.task_type,
        priority=task.priority,
        queue_depth=container.scheduler.queue.size(),
    )


@router.post("/run-once", response_model=AgentRunRead)
def run_once(container: AppContainer = Depends(get_container)) -> AgentRunRead:
    outcome = container.agent_control.run_once()
    if outcome is None:
        return AgentRunRead(processed=False, status="idle")
    return AgentRunRead(
        processed=True,
        status=outcome.result.status,
        task_id=outcome.task.task_id,
        enqueued_follow_ups=outcome.enqueued_follow_ups,
        error=outcome.error,
    )


@router.get("/queue", response_model=list[AgentQueueItemRead])
def list_agent_queue(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    container: AppContainer = Depends(get_container),
) -> list[AgentQueueItemRead]:
    with container.session_factory() as session:
        items = TaskQueueRepository(session).list(status=status, limit=limit, offset=offset)
        return [
            _build_queue_item_read(item)
            for item in items
        ]


@router.post("/queue/recover", response_model=AgentQueueRecoveryRead)
def recover_agent_queue(container: AppContainer = Depends(get_container)) -> AgentQueueRecoveryRead:
    recover_stale = getattr(container.scheduler.queue, "recover_stale", None)
    recovered = int(recover_stale()) if callable(recover_stale) else 0
    with container.session_factory() as session:
        counts = TaskQueueRepository(session).counts_by_status()
    return AgentQueueRecoveryRead(recovered_count=recovered, by_status=counts)


@router.get("/system-commands/policy")
def get_system_command_policy(container: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return container.system_commands.policy_snapshot()


@router.post("/system-commands/request", response_model=ApprovalRead, status_code=201)
def request_system_command(
    payload: SystemCommandRequest,
    container: AppContainer = Depends(get_container),
) -> ApprovalRead:
    try:
        approval = container.system_commands.request_command(
            command=payload.command,
            rationale=payload.rationale,
            requested_by=payload.requested_by,
            metadata=payload.metadata,
        )
    except SystemCommandDisabledError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SystemCommandPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApprovalRead.model_validate(approval)


@router.post("/system-commands/{approval_id}/execute", response_model=ApprovalRead)
def execute_system_command(
    approval_id: str,
    payload: SystemCommandExecuteRequest,
    container: AppContainer = Depends(get_container),
) -> ApprovalRead:
    try:
        approval = container.system_commands.execute_approval(approval_id, requested_by=payload.requested_by)
    except SystemCommandDisabledError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SystemCommandPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SystemCommandApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApprovalRead.model_validate(approval)


def _payload_value(payload: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if value is None:
        return None
    return str(value)


def _build_queue_item_read(item) -> AgentQueueItemRead:
    serialized_payload = dict(item.payload or {})
    task_payload = dict(serialized_payload.get("payload") or {})
    task_metadata = dict(serialized_payload.get("metadata") or {})
    display_payload = {
        **task_payload,
        **{
            key: value
            for key, value in task_metadata.items()
            if key in {"task_spec_id", "execution_plan_id", "execution_episode_id", "requested_by", "mode"}
            and value is not None
            and key not in task_payload
        },
    }
    if task_metadata:
        display_payload["_metadata"] = task_metadata

    return AgentQueueItemRead(
        task_id=item.id,
        task_type=item.task_type,
        adaptive_stage=_payload_value(serialized_payload.get("metadata"), "adaptive_stage") or item.task_type,
        priority=int(item.priority or 0),
        status=item.status,
        attempts=int(item.attempts or 0),
        scheduled_for=item.scheduled_for,
        locked_at=item.locked_at,
        locked_by=item.locked_by,
        application_id=_payload_value(serialized_payload, "application_id") or _payload_value(serialized_payload, "candidate_id"),
        payload=display_payload,
        queue_audit=[
            {
                "kind": str(event.get("kind") or "unknown"),
                "at": _timestamp(event.get("at")),
                "status": str(event.get("status")) if event.get("status") is not None else None,
                "priority": int(event["priority"]) if event.get("priority") is not None else None,
                "attempts": int(event["attempts"]) if event.get("attempts") is not None else None,
                "locked_by": str(event.get("locked_by")) if event.get("locked_by") is not None else None,
                "error": str(event.get("error")) if event.get("error") is not None else None,
            }
            for event in list(serialized_payload.get("queue_audit", {}).get("history") or [])
            if isinstance(event, dict)
        ],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
