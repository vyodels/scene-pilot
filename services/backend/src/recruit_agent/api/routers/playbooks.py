from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from recruit_agent.api.deps import get_session
from recruit_agent.repositories import PlaybookRepository
from recruit_agent.schemas import PlaybookCreate, PlaybookRead, PlaybookUpdate

router = APIRouter(prefix="/api/recruit-agent/playbooks", tags=["recruit-agent-playbooks"])


@router.get("", response_model=list[PlaybookRead])
def list_playbooks(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[PlaybookRead]:
    return [PlaybookRead.model_validate(item) for item in PlaybookRepository(session).list(limit=limit, offset=offset)]


@router.post("", response_model=PlaybookRead, status_code=201)
def create_playbook(payload: PlaybookCreate, session: Session = Depends(get_session)) -> PlaybookRead:
    item = PlaybookRepository(session).create(payload)
    return PlaybookRead.model_validate(item)


@router.get("/{playbook_id}", response_model=PlaybookRead)
def get_playbook(playbook_id: str, session: Session = Depends(get_session)) -> PlaybookRead:
    item = PlaybookRepository(session).get(playbook_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return PlaybookRead.model_validate(item)


@router.patch("/{playbook_id}", response_model=PlaybookRead)
def update_playbook(
    playbook_id: str,
    payload: PlaybookUpdate,
    session: Session = Depends(get_session),
) -> PlaybookRead:
    repo = PlaybookRepository(session)
    item = repo.get(playbook_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Playbook not found")
    updated = repo.update(item, payload)
    return PlaybookRead.model_validate(updated)


@router.delete("/{playbook_id}", status_code=204)
def delete_playbook(playbook_id: str, session: Session = Depends(get_session)) -> None:
    repo = PlaybookRepository(session)
    item = repo.get(playbook_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Playbook not found")
    repo.delete(item)
