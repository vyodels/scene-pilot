from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_container, get_session
from scene_pilot.repositories import CandidatePersonMemoryRepository, CandidateRepository
from scene_pilot.schemas import (
    CandidateMemoryRead,
    CandidateMemoryUpdate,
    CandidatePersonCreate,
    CandidatePersonRead,
    CandidatePersonUpdate,
    MemoryCompactRequest,
)
from scene_pilot.services.container import AppContainer
from scene_pilot.services.recruit_agent import (
    AUTO_COMPACT_THRESHOLD,
    apply_memory_compaction,
    content_length,
    ensure_candidate_person_memory,
    ensure_primary_recruit_agent_profile,
    needs_compaction,
)

router = APIRouter(prefix="/api/candidate-persons", tags=["candidate-persons"])


def _now() -> datetime:
    return datetime.now(timezone.utc)

def _as_candidate_person_read(candidate) -> CandidatePersonRead:
    return CandidatePersonRead.model_validate(
        {
            "person_id": candidate.candidate_person_id,
            "name": candidate.name,
            "platform": candidate.platform,
            "platform_candidate_id": candidate.platform_candidate_id,
            "contact_info": dict(candidate.contact_info or {}),
            "resume_path": candidate.resume_path,
            "online_resume_text": candidate.online_resume_text,
            "created_at": candidate.created_at,
            "updated_at": candidate.updated_at,
        }
    )


@router.get("", response_model=list[CandidatePersonRead])
def list_candidate_persons(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[CandidatePersonRead]:
    return [_as_candidate_person_read(item) for item in CandidateRepository(session).list(limit=limit, offset=offset)]


@router.post("", response_model=CandidatePersonRead, status_code=201)
def create_candidate_person(payload: CandidatePersonCreate, session: Session = Depends(get_session)) -> CandidatePersonRead:
    item = CandidateRepository(session).create(payload)
    return _as_candidate_person_read(item)


@router.get("/memories", response_model=list[CandidateMemoryRead])
def list_candidate_person_memories(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[CandidateMemoryRead]:
    profile = ensure_primary_recruit_agent_profile(session)
    person_repo = CandidateRepository(session)
    for person in person_repo.list(limit=5000, offset=0):
        ensure_candidate_person_memory(session, agent_profile_id=profile.id, person_id=person.id)
    items = CandidatePersonMemoryRepository(session).list_for_agent(profile.id, limit=limit, offset=offset)
    return [CandidateMemoryRead.model_validate(item) for item in items]


@router.get("/{person_id}/memory", response_model=CandidateMemoryRead)
def get_candidate_person_memory(person_id: str, session: Session = Depends(get_session)) -> CandidateMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    person = CandidateRepository(session).get(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Candidate person not found")
    item = ensure_candidate_person_memory(session, agent_profile_id=profile.id, person_id=person.id)
    return CandidateMemoryRead.model_validate(item)


@router.patch("/{person_id}/memory", response_model=CandidateMemoryRead)
def update_candidate_person_memory(
    person_id: str,
    payload: CandidateMemoryUpdate,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> CandidateMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    person = CandidateRepository(session).get(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Candidate person not found")
    repo = CandidatePersonMemoryRepository(session)
    item = ensure_candidate_person_memory(session, agent_profile_id=profile.id, person_id=person.id)
    update_data = payload.model_dump(exclude_unset=True)
    if "content" in update_data:
        update_data.setdefault("raw_content", update_data["content"] or {})
        update_data["token_estimate"] = content_length(update_data["content"] or {})
        update_data["disclosure"] = {
            "preview": str(update_data.get("summary") or item.summary or "")[:180],
            "operator_summary": str(update_data.get("summary") or item.summary or ""),
            "model_context": str(update_data["content"])[:1600],
        }
    updated = repo.update(item, update_data)
    threshold = int(
        (((profile.memory_policy or {}).get("candidate_memory") or {}).get("compact_threshold") or AUTO_COMPACT_THRESHOLD)
    )
    auto_compact = bool((((profile.memory_policy or {}).get("candidate_memory") or {}).get("auto_compact") or False))
    if auto_compact and needs_compaction(dict(updated.content or {}), threshold=threshold):
        apply_memory_compaction(
            updated,
            providers=container.providers,
            scope=f"candidate-person:{person.id}",
            reason="auto_compact_threshold_exceeded",
            compacted_at=_now(),
        )
        updated = repo.update(
            updated,
            {
                "summary": updated.summary,
                "raw_content": dict(updated.raw_content or {}),
                "content": dict(updated.content or {}),
                "disclosure": dict(updated.disclosure or {}),
                "token_estimate": updated.token_estimate,
                "compacted_at": updated.compacted_at,
                "compacted_reason": updated.compacted_reason,
                "memory_metadata": dict(updated.memory_metadata or {}),
            },
        )
    return CandidateMemoryRead.model_validate(updated)


@router.post("/{person_id}/memory/compact", response_model=CandidateMemoryRead)
def compact_candidate_person_memory(
    person_id: str,
    payload: MemoryCompactRequest,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> CandidateMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    person = CandidateRepository(session).get(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Candidate person not found")
    repo = CandidatePersonMemoryRepository(session)
    item = ensure_candidate_person_memory(session, agent_profile_id=profile.id, person_id=person.id)
    if not payload.force and not needs_compaction(dict(item.content or {})):
        return CandidateMemoryRead.model_validate(item)
    apply_memory_compaction(
        item,
        providers=container.providers,
        scope=f"candidate-person:{person.id}",
        reason=payload.reason,
        compacted_at=_now(),
    )
    updated = repo.update(
        item,
        {
            "summary": item.summary,
            "raw_content": dict(item.raw_content or {}),
            "content": dict(item.content or {}),
            "disclosure": dict(item.disclosure or {}),
            "token_estimate": item.token_estimate,
            "compacted_at": item.compacted_at,
            "compacted_reason": item.compacted_reason,
            "memory_metadata": dict(item.memory_metadata or {}),
        },
    )
    return CandidateMemoryRead.model_validate(updated)


@router.get("/{person_id}", response_model=CandidatePersonRead)
def get_candidate_person(person_id: str, session: Session = Depends(get_session)) -> CandidatePersonRead:
    item = CandidateRepository(session).get(person_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate person not found")
    return _as_candidate_person_read(item)


@router.patch("/{person_id}", response_model=CandidatePersonRead)
def update_candidate_person(
    person_id: str,
    payload: CandidatePersonUpdate,
    session: Session = Depends(get_session),
) -> CandidatePersonRead:
    repo = CandidateRepository(session)
    item = repo.get(person_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate person not found")
    updated = repo.update(item, payload)
    return _as_candidate_person_read(updated)


@router.delete("/{person_id}", status_code=204)
def delete_candidate_person(person_id: str, session: Session = Depends(get_session)) -> None:
    repo = CandidateRepository(session)
    item = repo.get(person_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate person not found")
    repo.delete(item)
