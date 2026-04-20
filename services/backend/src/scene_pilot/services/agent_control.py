from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.db.base import utcnow
from scene_pilot.repositories.domain import TaskQueueRepository


class AgentControlService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def enqueue_task(
        self,
        task_type: str,
        *,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        candidate_id: str | None = None,
    ) -> str:
        resolved_task_id = task_id or uuid4().hex
        envelope = _build_task_envelope(
            payload=payload,
            metadata=metadata,
            candidate_id=candidate_id,
        )
        with self.session_factory() as session:
            TaskQueueRepository(session).enqueue(
                task_id=resolved_task_id,
                task_type=task_type,
                priority=priority,
                payload=envelope,
            )
        return resolved_task_id

    def apply_approval_resolution(
        self,
        session: Session,
        approval,
        *,
        status: str,
        reviewer: str,
        notes: str | None,
    ):
        payload_snapshot = dict(approval.payload or {})
        reviewed_at = utcnow().isoformat()
        payload_snapshot["resolution"] = {
            "status": status,
            "reviewer": reviewer,
            "reason": notes,
            "reviewed_at": reviewed_at,
            "approved": status == "approved",
        }
        payload_snapshot["closed_at"] = reviewed_at

        if status == "approved":
            resume_task = _extract_resume_task(payload_snapshot)
            if resume_task is not None:
                task_id = str(resume_task.get("task_id") or approval.id or uuid4().hex)
                metadata = {
                    **dict(resume_task.get("metadata") or {}),
                    "resumed_from_approval_id": approval.id,
                    "approval_target_type": approval.target_type,
                    "approval_target_id": approval.target_id,
                }
                TaskQueueRepository(session).enqueue(
                    task_id=task_id,
                    task_type=str(resume_task["task_type"]),
                    priority=int(resume_task.get("priority", 100) or 100),
                    payload=_build_task_envelope(
                        payload=resume_task.get("payload"),
                        metadata=metadata,
                        candidate_id=resume_task.get("candidate_id"),
                    ),
                )
                payload_snapshot["resumed_task_id"] = task_id
                payload_snapshot["resume_task"] = resume_task

        approval.payload = payload_snapshot
        return approval


def _extract_resume_task(payload: dict[str, object]) -> dict[str, object] | None:
    for key in ("resume_task", "follow_up_task", "blocked_task"):
        raw = payload.get(key)
        if isinstance(raw, dict) and raw.get("task_type"):
            return dict(raw)
    return None


def _build_task_envelope(
    *,
    payload: dict[str, Any] | object | None,
    metadata: dict[str, Any] | None,
    candidate_id: str | None,
) -> dict[str, Any]:
    raw_payload = dict(payload or {}) if isinstance(payload, dict) else {}
    merged_metadata = {
        **(dict(raw_payload.get("metadata") or {}) if isinstance(raw_payload.get("metadata"), dict) else {}),
        **dict(metadata or {}),
    }
    if any(key in raw_payload for key in ("run_pk", "run_id")):
        envelope = dict(raw_payload)
        if merged_metadata:
            envelope["metadata"] = merged_metadata
        if candidate_id is not None and not envelope.get("candidate_id"):
            envelope["candidate_id"] = candidate_id
        return envelope

    return {
        "payload": raw_payload,
        "candidate_id": candidate_id,
        "metadata": merged_metadata,
    }
