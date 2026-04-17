from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_session
from scene_pilot.repositories import JobDescriptionRepository
from scene_pilot.schemas import JobDescriptionCreate, JobDescriptionRead, JobDescriptionUpdate

router = APIRouter(prefix="/api/job-descriptions", tags=["job-descriptions"])


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
