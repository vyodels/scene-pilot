from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.plugins.recruit.toolkit import list_locked_candidates, release_candidate, take_over_candidate


class LockCandidateRequest(BaseModel):
    locked_by: str
    reason: str | None = None
    expires_in_seconds: int | None = None


class ReleaseCandidateRequest(BaseModel):
    released_by: str
    handover_note: str | None = None
    handover_next_hint: str | None = None


def build_router(session_factory: sessionmaker[Session]) -> APIRouter:
    router = APIRouter(prefix="/api/recruit", tags=["recruit"])

    @router.post("/candidates/{candidate_person_id}/lock")
    def lock_candidate(candidate_person_id: str, payload: LockCandidateRequest) -> dict[str, Any]:
        expires_at = None
        if payload.expires_in_seconds is not None:
            expires_at = datetime.now(UTC) + timedelta(seconds=payload.expires_in_seconds)
        return take_over_candidate(
            session_factory,
            candidate_person_id=candidate_person_id,
            locked_by=payload.locked_by,
            reason=payload.reason,
            expires_at=expires_at,
        )

    @router.post("/candidates/{candidate_person_id}/release")
    def release_locked_candidate(candidate_person_id: str, payload: ReleaseCandidateRequest) -> dict[str, Any]:
        return release_candidate(
            session_factory,
            candidate_person_id=candidate_person_id,
            released_by=payload.released_by,
            handover_note=payload.handover_note,
            handover_next_hint=payload.handover_next_hint,
        )

    @router.get("/candidates/locks")
    def list_candidate_locks() -> list[dict[str, Any]]:
        return list_locked_candidates(session_factory)

    return router
