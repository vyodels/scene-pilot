from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_session
from scene_pilot.schemas import (
    RecruitmentStateMachineRead,
    RecruitmentStateMachineUpdate,
    StateCriteriaOptimizationReportRead,
)
from scene_pilot.services.state_machine import (
    StateMachineValidationError,
    ensure_latest_state_machine,
    get_state_machine_version,
    list_state_machine_versions,
    save_state_machine_version,
)
from scene_pilot.services.state_machine_criteria import list_state_machine_criteria_suggestions

router = APIRouter(prefix="/api/state-machine", tags=["state-machine"])


@router.get("", response_model=RecruitmentStateMachineRead)
def get_state_machine(session: Session = Depends(get_session)) -> RecruitmentStateMachineRead:
    return RecruitmentStateMachineRead.model_validate(ensure_latest_state_machine(session))


@router.get("/versions", response_model=list[RecruitmentStateMachineRead])
def get_state_machine_versions(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> list[RecruitmentStateMachineRead]:
    return [RecruitmentStateMachineRead.model_validate(item) for item in list_state_machine_versions(session, limit=limit)]


@router.get("/versions/{version}", response_model=RecruitmentStateMachineRead)
def get_state_machine_version_detail(
    version: int,
    session: Session = Depends(get_session),
) -> RecruitmentStateMachineRead:
    payload = get_state_machine_version(session, version)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"State machine version {version} not found.")
    return RecruitmentStateMachineRead.model_validate(payload)


@router.get("/criteria-suggestions", response_model=list[StateCriteriaOptimizationReportRead])
def get_state_machine_criteria_suggestions(
    session: Session = Depends(get_session),
) -> list[StateCriteriaOptimizationReportRead]:
    return [StateCriteriaOptimizationReportRead.model_validate(item) for item in list_state_machine_criteria_suggestions(session)]


@router.put("", response_model=RecruitmentStateMachineRead)
def put_state_machine(
    payload: RecruitmentStateMachineUpdate,
    session: Session = Depends(get_session),
) -> RecruitmentStateMachineRead:
    try:
        stored = save_state_machine_version(session, payload)
    except StateMachineValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RecruitmentStateMachineRead.model_validate(stored)
