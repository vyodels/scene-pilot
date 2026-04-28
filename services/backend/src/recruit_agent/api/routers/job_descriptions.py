from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from recruit_agent.api.deps import get_container, get_session
from recruit_agent.repositories import JobDescriptionMemoryRepository, JobDescriptionRepository
from recruit_agent.schemas import JobDescriptionCreate, JobDescriptionRead, JobDescriptionUpdate, JobMemoryRead, JobMemoryUpdate, MemoryCompactRequest
from recruit_agent.services.container import AppContainer
from recruit_agent.services.recruit_agent import (
    AUTO_COMPACT_THRESHOLD,
    apply_memory_compaction,
    content_length,
    ensure_job_description_memory,
    ensure_primary_recruit_agent_profile,
    needs_compaction,
)

router = APIRouter(prefix="/api/job-descriptions", tags=["job-descriptions"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("", response_model=list[JobDescriptionRead])
def list_job_descriptions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[JobDescriptionRead]:
    return [JobDescriptionRead.model_validate(item) for item in JobDescriptionRepository(session).list(limit=limit, offset=offset)]


@router.post("", response_model=JobDescriptionRead, status_code=201)
def create_job_description(payload: JobDescriptionCreate, session: Session = Depends(get_session)) -> JobDescriptionRead:
    item = JobDescriptionRepository(session).create(payload)
    return JobDescriptionRead.model_validate(item)


@router.get("/memories", response_model=list[JobMemoryRead])
def list_job_description_memories(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[JobMemoryRead]:
    profile = ensure_primary_recruit_agent_profile(session)
    job_repo = JobDescriptionRepository(session)
    for item in job_repo.list(limit=5000, offset=0):
        ensure_job_description_memory(session, agent_profile_id=profile.id, job_description_id=item.id)
    items = JobDescriptionMemoryRepository(session).list_for_agent(profile.id, limit=limit, offset=offset)
    return [JobMemoryRead.model_validate(item) for item in items]


@router.get("/{job_description_id}/memory", response_model=JobMemoryRead)
def get_job_description_memory(job_description_id: str, session: Session = Depends(get_session)) -> JobMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    item = JobDescriptionRepository(session).get(job_description_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Job description not found")
    memory = ensure_job_description_memory(session, agent_profile_id=profile.id, job_description_id=item.id)
    return JobMemoryRead.model_validate(memory)


@router.patch("/{job_description_id}/memory", response_model=JobMemoryRead)
def update_job_description_memory(
    job_description_id: str,
    payload: JobMemoryUpdate,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> JobMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    item = JobDescriptionRepository(session).get(job_description_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Job description not found")
    repo = JobDescriptionMemoryRepository(session)
    memory = ensure_job_description_memory(session, agent_profile_id=profile.id, job_description_id=item.id)
    update_data = payload.model_dump(exclude_unset=True)
    if "content" in update_data:
        update_data.setdefault("raw_content", update_data["content"] or {})
        update_data["token_estimate"] = content_length(update_data["content"] or {})
        update_data["disclosure"] = {
            "preview": str(update_data.get("summary") or memory.summary or "")[:180],
            "operator_summary": str(update_data.get("summary") or memory.summary or ""),
            "model_context": str(update_data["content"])[:1600],
        }
    updated = repo.update(memory, update_data)
    threshold = int((((profile.memory_policy or {}).get("job_memory") or {}).get("compact_threshold") or AUTO_COMPACT_THRESHOLD))
    auto_compact = bool((((profile.memory_policy or {}).get("job_memory") or {}).get("auto_compact") or False))
    if auto_compact and needs_compaction(dict(updated.content or {}), threshold=threshold):
        apply_memory_compaction(
            updated,
            provider=container.provider,
            scope=f"job-description:{job_description_id}",
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
    return JobMemoryRead.model_validate(updated)


@router.post("/{job_description_id}/memory/compact", response_model=JobMemoryRead)
def compact_job_description_memory(
    job_description_id: str,
    payload: MemoryCompactRequest,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> JobMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    item = JobDescriptionRepository(session).get(job_description_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Job description not found")
    repo = JobDescriptionMemoryRepository(session)
    memory = ensure_job_description_memory(session, agent_profile_id=profile.id, job_description_id=item.id)
    if not payload.force and not needs_compaction(dict(memory.content or {})):
        return JobMemoryRead.model_validate(memory)
    apply_memory_compaction(
        memory,
        provider=container.provider,
        scope=f"job-description:{job_description_id}",
        reason=payload.reason,
        compacted_at=_now(),
    )
    updated = repo.update(
        memory,
        {
            "summary": memory.summary,
            "raw_content": dict(memory.raw_content or {}),
            "content": dict(memory.content or {}),
            "disclosure": dict(memory.disclosure or {}),
            "token_estimate": memory.token_estimate,
            "compacted_at": memory.compacted_at,
            "compacted_reason": memory.compacted_reason,
            "memory_metadata": dict(memory.memory_metadata or {}),
        },
    )
    return JobMemoryRead.model_validate(updated)


@router.get("/{job_description_id}", response_model=JobDescriptionRead)
def get_job_description(job_description_id: str, session: Session = Depends(get_session)) -> JobDescriptionRead:
    item = JobDescriptionRepository(session).get(job_description_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Job description not found")
    return JobDescriptionRead.model_validate(item)


@router.patch("/{job_description_id}", response_model=JobDescriptionRead)
def update_job_description(
    job_description_id: str,
    payload: JobDescriptionUpdate,
    session: Session = Depends(get_session),
) -> JobDescriptionRead:
    repo = JobDescriptionRepository(session)
    item = repo.get(job_description_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Job description not found")
    updated = repo.update(item, payload)
    return JobDescriptionRead.model_validate(updated)


@router.delete("/{job_description_id}", status_code=204)
def delete_job_description(job_description_id: str, session: Session = Depends(get_session)) -> None:
    repo = JobDescriptionRepository(session)
    item = repo.get(job_description_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Job description not found")
    repo.delete(item)
