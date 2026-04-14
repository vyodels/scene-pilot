from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from recruit_agent.api.deps import get_session
from recruit_agent.repositories import AgentLearningRepository, SkillRepository
from recruit_agent.schemas import (
    ApprovalDecisionRequest,
    LearningDraftCreate,
    LearningDraftRead,
    SkillCreate,
    SkillHealthCheckRead,
    SkillHealthCheckRequest,
    SkillHealthSweepItemRead,
    SkillHealthSweepRead,
    SkillHealthSweepRequest,
    SkillRead,
    SkillUpdate,
)
from recruit_agent.services.skills import SkillHealthCheckService, SkillHealthSweepService, SkillLifecycleService

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _get_skill_or_404(repo: SkillRepository, skill_id: str):
    item = repo.get(skill_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return item


def _get_learning_or_404(repo: AgentLearningRepository, learning_id: str):
    item = repo.get(learning_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Learning draft not found")
    return item


@router.get("", response_model=list[SkillRead])
def list_skills(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[SkillRead]:
    return [SkillRead.model_validate(item) for item in SkillRepository(session).list(limit=limit, offset=offset)]


@router.post("", response_model=SkillRead, status_code=201)
def create_skill(payload: SkillCreate, session: Session = Depends(get_session)) -> SkillRead:
    item = SkillRepository(session).create(payload)
    return SkillRead.model_validate(item)


@router.get("/learnings", response_model=list[LearningDraftRead])
def list_learning_drafts(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    active_only: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[LearningDraftRead]:
    repo = AgentLearningRepository(session)
    items = repo.list_active(limit=limit, offset=offset) if active_only else repo.list(limit=limit, offset=offset)
    return [LearningDraftRead.model_validate(item) for item in items]


@router.post("/learnings", response_model=LearningDraftRead, status_code=201)
def create_learning_draft(
    payload: LearningDraftCreate,
    session: Session = Depends(get_session),
) -> LearningDraftRead:
    item = AgentLearningRepository(session).create(payload)
    return LearningDraftRead.model_validate(item)


@router.post("/learnings/{learning_id}/activate", response_model=LearningDraftRead)
def activate_learning_draft(learning_id: str, session: Session = Depends(get_session)) -> LearningDraftRead:
    repo = AgentLearningRepository(session)
    item = _get_learning_or_404(repo, learning_id)
    updated = repo.set_active(item, True)
    return LearningDraftRead.model_validate(updated)


@router.post("/learnings/{learning_id}/deactivate", response_model=LearningDraftRead)
def deactivate_learning_draft(learning_id: str, session: Session = Depends(get_session)) -> LearningDraftRead:
    repo = AgentLearningRepository(session)
    item = _get_learning_or_404(repo, learning_id)
    updated = repo.set_active(item, False)
    return LearningDraftRead.model_validate(updated)


@router.get("/{skill_id}", response_model=SkillRead)
def get_skill(skill_id: str, session: Session = Depends(get_session)) -> SkillRead:
    item = _get_skill_or_404(SkillRepository(session), skill_id)
    return SkillRead.model_validate(item)


@router.patch("/{skill_id}", response_model=SkillRead)
def update_skill(skill_id: str, payload: SkillUpdate, session: Session = Depends(get_session)) -> SkillRead:
    repo = SkillRepository(session)
    item = _get_skill_or_404(repo, skill_id)
    updated = repo.update(item, payload)
    return SkillRead.model_validate(updated)


@router.post("/{skill_id}/submit-review", response_model=SkillRead)
def submit_skill_for_review(skill_id: str, session: Session = Depends(get_session)) -> SkillRead:
    repo = SkillRepository(session)
    item = _get_skill_or_404(repo, skill_id)
    lifecycle = SkillLifecycleService()
    lifecycle.submit_for_review(item)
    updated = repo.update(
        item,
        {
            "status": str(item.status),
            "updated_at": item.updated_at,
        },
    )
    return SkillRead.model_validate(updated)


@router.post("/{skill_id}/approve", response_model=SkillRead)
def approve_skill(
    skill_id: str,
    payload: ApprovalDecisionRequest,
    session: Session = Depends(get_session),
) -> SkillRead:
    repo = SkillRepository(session)
    item = _get_skill_or_404(repo, skill_id)
    lifecycle = SkillLifecycleService()
    lifecycle.approve(item, reviewer=payload.reviewer)
    updated = repo.update(
        item,
        {
            "status": str(item.status),
            "confirmed_by": item.confirmed_by,
            "confirmed_at": item.confirmed_at,
            "updated_at": item.updated_at,
            "last_health_status": payload.reason or item.last_health_status,
        },
    )
    return SkillRead.model_validate(updated)


@router.post("/{skill_id}/activate", response_model=SkillRead)
def activate_skill(
    skill_id: str,
    payload: ApprovalDecisionRequest,
    session: Session = Depends(get_session),
) -> SkillRead:
    repo = SkillRepository(session)
    item = _get_skill_or_404(repo, skill_id)
    lifecycle = SkillLifecycleService()
    try:
        lifecycle.activate(item, manual=True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated = repo.update(
        item,
        {
            "status": str(item.status),
            "confirmed_by": item.confirmed_by or payload.reviewer,
            "confirmed_at": item.confirmed_at,
            "updated_at": item.updated_at,
        },
    )
    return SkillRead.model_validate(updated)


@router.post("/{skill_id}/health-check", response_model=SkillHealthCheckRead)
def run_skill_health_check(
    skill_id: str,
    payload: SkillHealthCheckRequest,
    session: Session = Depends(get_session),
) -> SkillHealthCheckRead:
    repo = SkillRepository(session)
    item = _get_skill_or_404(repo, skill_id)
    checker = SkillHealthCheckService()
    result = checker.run(item, observed_result=payload.observed_result)
    updated = repo.update(
        item,
        {
            "status": str(item.status),
            "last_health_check": item.last_health_check,
            "last_health_status": item.last_health_status,
            "updated_at": item.updated_at,
        },
    )
    return SkillHealthCheckRead(
        skill_id=updated.id,
        status=updated.status,
        health=updated.last_health_status or result.health,
        checked_at=updated.last_health_check or result.checked_at,
        issues=result.issues,
    )


@router.post("/health-checks/sweep", response_model=SkillHealthSweepRead)
def run_skill_health_check_sweep(
    payload: SkillHealthSweepRequest,
    session: Session = Depends(get_session),
) -> SkillHealthSweepRead:
    repo = SkillRepository(session)
    sweep = SkillHealthSweepService()
    statuses = payload.statuses or ["active", "approved"]

    all_skills = repo.list(limit=5000, offset=0)
    selected_skills = sweep.filter_skills(
        all_skills,
        skill_ids=payload.skill_ids,
        statuses=statuses,
        platform=payload.platform,
    )
    sweep_result = sweep.run(
        selected_skills,
        observed_results_by_skill=payload.observed_results_by_skill,
    )

    items: list[SkillHealthSweepItemRead] = []
    for skill, result in sweep_result.results:
        updated = repo.update(
            skill,
            {
                "status": str(skill.status),
                "last_health_check": skill.last_health_check,
                "last_health_status": skill.last_health_status,
                "updated_at": skill.updated_at,
            },
        )
        items.append(
            SkillHealthSweepItemRead(
                skill_id=updated.id,
                status=updated.status,
                health=updated.last_health_status or result.health,
                checked_at=updated.last_health_check or result.checked_at,
                issues=result.issues,
                degraded=updated.status == "degraded",
            )
        )

    return SkillHealthSweepRead(
        checked_count=sweep_result.checked_count,
        degraded_count=sweep_result.degraded_count,
        statuses=statuses,
        platform=payload.platform,
        results=items,
    )
