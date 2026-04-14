from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_session
from scene_pilot.repositories import CandidateRepository
from scene_pilot.schemas import CandidateCreate, CandidateRead, CandidateUpdate

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


@router.get("", response_model=list[CandidateRead])
def list_candidates(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[CandidateRead]:
    return [CandidateRead.model_validate(item) for item in CandidateRepository(session).list(limit=limit, offset=offset)]


@router.post("", response_model=CandidateRead, status_code=201)
def create_candidate(payload: CandidateCreate, session: Session = Depends(get_session)) -> CandidateRead:
    item = CandidateRepository(session).create(payload)
    return CandidateRead.model_validate(item)


@router.get("/{candidate_id}", response_model=CandidateRead)
def get_candidate(candidate_id: str, session: Session = Depends(get_session)) -> CandidateRead:
    item = CandidateRepository(session).get(candidate_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return CandidateRead.model_validate(item)


@router.patch("/{candidate_id}", response_model=CandidateRead)
def update_candidate(
    candidate_id: str,
    payload: CandidateUpdate,
    session: Session = Depends(get_session),
) -> CandidateRead:
    repo = CandidateRepository(session)
    item = repo.get(candidate_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    updated = repo.update(item, payload)
    return CandidateRead.model_validate(updated)


@router.delete("/{candidate_id}", status_code=204)
def delete_candidate(candidate_id: str, session: Session = Depends(get_session)) -> None:
    repo = CandidateRepository(session)
    item = repo.get(candidate_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    repo.delete(item)
