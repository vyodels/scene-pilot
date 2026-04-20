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
        application_id: str | None = None,
        person_id: str | None = None,
        candidate_id: str | None = None,
    ) -> str:
        resolved_task_id = task_id or uuid4().hex
        envelope = _build_task_envelope(
            payload=payload,
            metadata=metadata,
            application_id=application_id,
            person_id=person_id,
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
                        application_id=resume_task.get("application_id"),
                        person_id=resume_task.get("person_id"),
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
    application_id: str | None,
    person_id: str | None,
    candidate_id: str | None,
) -> dict[str, Any]:
    raw_payload = dict(payload or {}) if isinstance(payload, dict) else {}
    merged_metadata = {
        **(dict(raw_payload.get("metadata") or {}) if isinstance(raw_payload.get("metadata"), dict) else {}),
        **dict(metadata or {}),
    }
    resolved_application_id = _resolve_subject_id(application_id or raw_payload.get("application_id") or raw_payload.get("applicationId"))
    resolved_person_id = _resolve_subject_id(
        person_id
        or raw_payload.get("person_id")
        or raw_payload.get("personId")
        or candidate_id
        or raw_payload.get("candidate_id")
        or raw_payload.get("candidateId")
    )
    if any(key in raw_payload for key in ("run_pk", "run_id")):
        envelope = dict(raw_payload)
        if merged_metadata:
            envelope["metadata"] = merged_metadata
        if resolved_application_id is not None and not envelope.get("application_id"):
            envelope["application_id"] = resolved_application_id
        if resolved_person_id is not None and not envelope.get("person_id"):
            envelope["person_id"] = resolved_person_id
        return envelope

    return {
        "payload": raw_payload,
        "application_id": resolved_application_id,
        "person_id": resolved_person_id,
        "metadata": merged_metadata,
    }


def _resolve_subject_id(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None
