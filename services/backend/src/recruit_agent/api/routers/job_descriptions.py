from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from recruit_agent.api.deps import get_session
from recruit_agent.repositories import JobDescriptionRepository
from recruit_agent.schemas import (
    JobDescriptionCreate,
    JobDescriptionFunnelStatsRead,
    JobDescriptionPageRead,
    JobDescriptionRead,
    JobDescriptionUpdate,
)
from recruit_agent.services.job_description_stats import build_job_description_funnel_stats

router = APIRouter(prefix="/api/job-descriptions", tags=["job-descriptions"])


@router.get("", response_model=JobDescriptionPageRead)
def list_job_descriptions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    location: str | None = Query(default=None),
    department: str | None = Query(default=None),
    owner: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    applicant_keyword: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> JobDescriptionPageRead:
    repo = JobDescriptionRepository(session)
    items = [
        JobDescriptionRead.model_validate(item)
        for item in repo.list_page(
            status=status,
            location=location,
            department=department,
            owner=owner,
            keyword=keyword,
            applicant_keyword=applicant_keyword,
            limit=limit,
            offset=offset,
        )
    ]
    total = repo.count_page(
        status=status,
        location=location,
        department=department,
        owner=owner,
        keyword=keyword,
        applicant_keyword=applicant_keyword,
    )
    return JobDescriptionPageRead(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_next=offset + len(items) < total,
    )


@router.post("", response_model=JobDescriptionRead, status_code=201)
def create_job_description(payload: JobDescriptionCreate, session: Session = Depends(get_session)) -> JobDescriptionRead:
    item = JobDescriptionRepository(session).create(payload)
    return JobDescriptionRead.model_validate(item)


@router.get("/{job_description_id}/funnel-stats", response_model=JobDescriptionFunnelStatsRead)
def get_job_description_funnel_stats(job_description_id: str, session: Session = Depends(get_session)) -> JobDescriptionFunnelStatsRead:
    stats = build_job_description_funnel_stats(session, job_description_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Job description not found")
    return JobDescriptionFunnelStatsRead.model_validate(stats)


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
