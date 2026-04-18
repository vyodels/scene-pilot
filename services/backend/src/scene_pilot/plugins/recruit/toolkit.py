from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.db.base import utcnow
from scene_pilot.models.domain import CandidateAutonomousLock


def take_over_candidate(
    session_factory: sessionmaker[Session],
    *,
    candidate_person_id: str,
    locked_by: str,
    reason: str | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    with session_factory() as session:
        lock = _active_lock(session, candidate_person_id)
        if lock is None:
            lock = CandidateAutonomousLock(
                candidate_person_id=candidate_person_id,
                locked_by=locked_by,
                reason=reason,
                expires_at=expires_at,
            )
            session.add(lock)
        else:
            lock.locked_by = locked_by
            lock.reason = reason
            lock.expires_at = expires_at
            lock.released_at = None
            lock.released_by = None
        session.commit()
        session.refresh(lock)
        return _serialize_lock(lock)


def release_candidate(
    session_factory: sessionmaker[Session],
    *,
    candidate_person_id: str,
    released_by: str,
    handover_note: str | None = None,
    handover_next_hint: str | None = None,
) -> dict[str, Any]:
    with session_factory() as session:
        lock = _active_lock(session, candidate_person_id)
        if lock is None:
            raise KeyError(f"candidate {candidate_person_id} is not locked")
        lock.released_at = utcnow()
        lock.released_by = released_by
        if handover_note is not None:
            lock.handover_note = handover_note
        if handover_next_hint is not None:
            lock.handover_next_hint = handover_next_hint
        session.commit()
        session.refresh(lock)
        return _serialize_lock(lock)


def list_locked_candidates(session_factory: sessionmaker[Session]) -> list[dict[str, Any]]:
    with session_factory() as session:
        stmt = select(CandidateAutonomousLock).where(CandidateAutonomousLock.released_at.is_(None))
        return [_serialize_lock(lock) for lock in session.scalars(stmt).all() if _not_expired(lock)]


def _active_lock(session: Session, candidate_person_id: str) -> CandidateAutonomousLock | None:
    stmt = (
        select(CandidateAutonomousLock)
        .where(
            CandidateAutonomousLock.candidate_person_id == candidate_person_id,
            CandidateAutonomousLock.released_at.is_(None),
        )
        .order_by(CandidateAutonomousLock.locked_at.desc(), CandidateAutonomousLock.id.desc())
    )
    for lock in session.scalars(stmt).all():
        if _not_expired(lock):
            return lock
    return None


def _not_expired(lock: CandidateAutonomousLock) -> bool:
    return lock.expires_at is None or lock.expires_at >= datetime.now(UTC)


def _serialize_lock(lock: CandidateAutonomousLock) -> dict[str, Any]:
    return {
        "id": lock.id,
        "candidate_person_id": lock.candidate_person_id,
        "locked_at": lock.locked_at,
        "locked_by": lock.locked_by,
        "reason": lock.reason,
        "expires_at": lock.expires_at,
        "released_at": lock.released_at,
        "released_by": lock.released_by,
        "handover_note": lock.handover_note,
        "handover_next_hint": lock.handover_next_hint,
    }
