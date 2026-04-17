from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_session
from scene_pilot.repositories import CandidateRepository
from scene_pilot.schemas import CandidatePersonCreate, CandidatePersonRead, CandidatePersonUpdate

router = APIRouter(prefix="/api/candidate-persons", tags=["candidate-persons"])

def _as_candidate_person_read(candidate) -> CandidatePersonRead:
    return CandidatePersonRead.model_validate(candidate)


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
