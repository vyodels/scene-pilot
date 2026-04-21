from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.models.domain import CandidateAutonomousLock
from recruit_agent.plugins.recruit.toolkit import _active_lock, _serialize_lock
from recruit_agent.runtime.models import Observation


def build_observation_enricher(
    session_factory: sessionmaker[Session],
) -> Callable[[Observation], Awaitable[dict[str, object]]]:
    async def _enricher(observation: Observation) -> dict[str, object]:
        if observation.scope_kind != "application" or not observation.scope_ref:
            return {"human_locked": False, "lock_meta": None, "recent_handover": None}
        with session_factory() as session:
            lock = _active_lock(session, observation.scope_ref)
            recent_handover = _recent_handover(session, observation.scope_ref)
            return {
                "human_locked": lock is not None,
                "lock_meta": None if lock is None else _serialize_lock(lock),
                "recent_handover": recent_handover,
            }

    return _enricher


def _recent_handover(session: Session, application_id: str) -> dict[str, object] | None:
    stmt = (
        select(CandidateAutonomousLock)
        .where(
            CandidateAutonomousLock.application_id == application_id,
            CandidateAutonomousLock.released_at.is_not(None),
        )
        .order_by(CandidateAutonomousLock.released_at.desc(), CandidateAutonomousLock.id.desc())
    )
    lock = session.scalars(stmt).first()
    return None if lock is None else _serialize_lock(lock)
