from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_session
from scene_pilot.repositories import WorkflowRepository
from scene_pilot.schemas import WorkflowCreate, WorkflowRead, WorkflowUpdate

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("", response_model=list[WorkflowRead])
def list_workflows(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[WorkflowRead]:
    return [WorkflowRead.model_validate(item) for item in WorkflowRepository(session).list(limit=limit, offset=offset)]


@router.post("", response_model=WorkflowRead, status_code=201)
def create_workflow(payload: WorkflowCreate, session: Session = Depends(get_session)) -> WorkflowRead:
    item = WorkflowRepository(session).create(payload)
    return WorkflowRead.model_validate(item)


@router.get("/{workflow_id}", response_model=WorkflowRead)
def get_workflow(workflow_id: str, session: Session = Depends(get_session)) -> WorkflowRead:
    item = WorkflowRepository(session).get(workflow_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowRead.model_validate(item)


@router.patch("/{workflow_id}", response_model=WorkflowRead)
def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    session: Session = Depends(get_session),
) -> WorkflowRead:
    repo = WorkflowRepository(session)
    item = repo.get(workflow_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    updated = repo.update(item, payload)
    return WorkflowRead.model_validate(updated)


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: str, session: Session = Depends(get_session)) -> None:
    repo = WorkflowRepository(session)
    item = repo.get(workflow_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    repo.delete(item)
