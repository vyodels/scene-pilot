from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from recruit_agent.api.deps import get_container, get_session
from recruit_agent.services.container import AppContainer
from recruit_agent.schemas import (
    CapabilityDriverRead,
    DomainPackRead,
    EnvironmentAssessmentRead,
    EnvironmentAssessmentRequest,
    EpisodeConfirmRequest,
    EnvironmentSnapshotCreate,
    EnvironmentSnapshotRead,
    ExecutionEpisodeCreate,
    ExecutionEpisodeRead,
    ExecutionPlanReplanRead,
    ExecutionPlanReplanRequest,
    ExecutionPlanRead,
    RuntimeEpisodeReplayRead,
    RuntimeLearningOutcomeRead,
    TaskCompileRequest,
    TaskCompileResponse,
    TaskSpecCreate,
    TaskSpecRead,
    TrialRunExecuteRequest,
    TrialRunRequest,
    WorkflowPatchCreate,
    WorkflowPatchDecisionRequest,
    WorkflowPatchRead,
    WorkflowTemplateCreate,
    WorkflowTemplateRead,
    WorkflowTemplateUpdate,
)
from recruit_agent.services.runtime import CompilePlanRequest, PersistedRuntimeService

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


def get_runtime_service(
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> PersistedRuntimeService:
    return PersistedRuntimeService(session=session, providers=container.providers)


def _raise_runtime_http_error(exc: ValueError) -> None:
    detail = str(exc)
    lowered = detail.lower()
    if "not found" in lowered:
        raise HTTPException(status_code=404, detail=detail) from exc
    if "already exists" in lowered:
        raise HTTPException(status_code=409, detail=detail) from exc
    raise HTTPException(status_code=400, detail=detail) from exc


@router.get("/domain-packs", response_model=list[DomainPackRead])
def list_domain_packs(
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> list[DomainPackRead]:
    return service.list_domain_packs()


@router.get("/capability-drivers", response_model=list[CapabilityDriverRead])
@router.get("/capabilities", response_model=list[CapabilityDriverRead])
def list_capability_drivers(
    domain: str | None = Query(default=None),
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> list[CapabilityDriverRead]:
    return service.list_capability_drivers(domain=domain)


@router.get("/task-specs", response_model=list[TaskSpecRead])
@router.get("/tasks", response_model=list[TaskSpecRead])
def list_task_specs(
    domain: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> list[TaskSpecRead]:
    return service.list_task_specs(domain=domain, limit=limit, offset=offset)


@router.post("/task-specs", response_model=TaskSpecRead, status_code=201)
@router.post("/tasks", response_model=TaskSpecRead, status_code=201)
def create_task_spec(
    payload: TaskSpecCreate,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> TaskSpecRead:
    try:
        return service.create_task_spec(payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/task-specs/compile", response_model=TaskCompileResponse, status_code=201)
@router.post("/tasks/compile", response_model=TaskCompileResponse, status_code=201)
def compile_task_spec(
    payload: TaskCompileRequest,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> TaskCompileResponse:
    try:
        return service.compile_task(payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.get("/plans", response_model=list[ExecutionPlanRead])
def list_execution_plans(
    task_spec_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> list[ExecutionPlanRead]:
    return service.list_plans(task_spec_id=task_spec_id, limit=limit, offset=offset)


@router.post("/plans", response_model=ExecutionPlanRead, status_code=201)
@router.post("/plans/compile", response_model=ExecutionPlanRead, status_code=201)
def compile_execution_plan(
    payload: CompilePlanRequest,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> ExecutionPlanRead:
    try:
        return service.compile_plan(payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/plans/{plan_id}/replan", response_model=ExecutionPlanReplanRead, status_code=201)
def replan_execution_plan(
    plan_id: str,
    payload: ExecutionPlanReplanRequest,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> ExecutionPlanReplanRead:
    try:
        return service.replan_execution(plan_id, payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.get("/episodes", response_model=list[ExecutionEpisodeRead])
@router.get("/trial-runs", response_model=list[ExecutionEpisodeRead])
def list_execution_episodes(
    execution_plan_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> list[ExecutionEpisodeRead]:
    return service.list_episodes(execution_plan_id=execution_plan_id, limit=limit, offset=offset)


@router.get("/episodes/{episode_id}", response_model=ExecutionEpisodeRead)
def get_execution_episode(
    episode_id: str,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> ExecutionEpisodeRead:
    try:
        return service.get_episode(episode_id)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.get("/episodes/{episode_id}/replay", response_model=RuntimeEpisodeReplayRead)
@router.get("/trial-runs/{episode_id}/replay", response_model=RuntimeEpisodeReplayRead)
def get_execution_episode_replay(
    episode_id: str,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> RuntimeEpisodeReplayRead:
    try:
        return service.get_episode_replay(episode_id)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/episodes", response_model=ExecutionEpisodeRead, status_code=201)
def create_execution_episode(
    payload: ExecutionEpisodeCreate,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> ExecutionEpisodeRead:
    try:
        return service.create_episode(payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/trial-runs", response_model=ExecutionEpisodeRead, status_code=201)
def create_trial_run(
    payload: TrialRunRequest,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> ExecutionEpisodeRead:
    try:
        return service.create_trial_run(payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/trial-runs/{episode_id}/execute", response_model=RuntimeLearningOutcomeRead)
@router.post("/episodes/{episode_id}/execute", response_model=RuntimeLearningOutcomeRead)
def execute_trial_run(
    episode_id: str,
    payload: TrialRunExecuteRequest,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> RuntimeLearningOutcomeRead:
    try:
        return service.execute_trial_run(episode_id, payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/trial-runs/{episode_id}/learn", response_model=RuntimeLearningOutcomeRead)
@router.post("/episodes/{episode_id}/learn", response_model=RuntimeLearningOutcomeRead)
def derive_learning_from_episode(
    episode_id: str,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> RuntimeLearningOutcomeRead:
    try:
        return service.derive_learning_from_episode(episode_id)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/trial-runs/{episode_id}/confirm", response_model=RuntimeLearningOutcomeRead)
@router.post("/episodes/{episode_id}/confirm", response_model=RuntimeLearningOutcomeRead)
def confirm_episode(
    episode_id: str,
    payload: EpisodeConfirmRequest,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> RuntimeLearningOutcomeRead:
    try:
        return service.confirm_episode(episode_id, payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.get("/environment-snapshots", response_model=list[EnvironmentSnapshotRead])
@router.get("/snapshots", response_model=list[EnvironmentSnapshotRead])
def list_environment_snapshots(
    execution_episode_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> list[EnvironmentSnapshotRead]:
    return service.list_environment_snapshots(
        execution_episode_id=execution_episode_id,
        limit=limit,
        offset=offset,
    )


@router.post("/environment-snapshots", response_model=EnvironmentSnapshotRead, status_code=201)
@router.post("/snapshots", response_model=EnvironmentSnapshotRead, status_code=201)
def create_environment_snapshot(
    payload: EnvironmentSnapshotCreate,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> EnvironmentSnapshotRead:
    try:
        return service.create_environment_snapshot(payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/environment-assessments", response_model=EnvironmentAssessmentRead)
@router.post("/environment-assessment", response_model=EnvironmentAssessmentRead)
@router.post("/scene-assessment", response_model=EnvironmentAssessmentRead)
def assess_environment(
    payload: EnvironmentAssessmentRequest,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> EnvironmentAssessmentRead:
    try:
        return service.assess_environment(payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.get("/templates", response_model=list[WorkflowTemplateRead])
def list_workflow_templates(
    domain: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> list[WorkflowTemplateRead]:
    return service.list_templates(domain=domain, limit=limit, offset=offset)


@router.get("/templates/{template_id}", response_model=WorkflowTemplateRead)
def get_workflow_template(
    template_id: str,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> WorkflowTemplateRead:
    try:
        return service.get_template(template_id)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/templates", response_model=WorkflowTemplateRead, status_code=201)
def create_workflow_template(
    payload: WorkflowTemplateCreate,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> WorkflowTemplateRead:
    try:
        return service.create_template(payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.patch("/templates/{template_id}", response_model=WorkflowTemplateRead)
def update_workflow_template(
    template_id: str,
    payload: WorkflowTemplateUpdate,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> WorkflowTemplateRead:
    try:
        return service.update_template(template_id, payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.get("/workflow-patches", response_model=list[WorkflowPatchRead])
@router.get("/patches", response_model=list[WorkflowPatchRead])
def list_workflow_patches(
    status: str | None = Query(default=None),
    workflow_template_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> list[WorkflowPatchRead]:
    return service.list_workflow_patches(
        status=status,
        workflow_template_id=workflow_template_id,
        limit=limit,
        offset=offset,
    )


@router.post("/workflow-patches", response_model=WorkflowPatchRead, status_code=201)
@router.post("/patches", response_model=WorkflowPatchRead, status_code=201)
def create_workflow_patch(
    payload: WorkflowPatchCreate,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> WorkflowPatchRead:
    try:
        return service.create_workflow_patch(payload)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/workflow-patches/{patch_id}/approve", response_model=WorkflowPatchRead)
@router.post("/patches/{patch_id}/approve", response_model=WorkflowPatchRead)
def approve_workflow_patch(
    patch_id: str,
    payload: WorkflowPatchDecisionRequest,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> WorkflowPatchRead:
    try:
        return service.review_workflow_patch(patch_id, payload, approve=True)
    except ValueError as exc:
        _raise_runtime_http_error(exc)


@router.post("/workflow-patches/{patch_id}/reject", response_model=WorkflowPatchRead)
@router.post("/patches/{patch_id}/reject", response_model=WorkflowPatchRead)
def reject_workflow_patch(
    patch_id: str,
    payload: WorkflowPatchDecisionRequest,
    service: PersistedRuntimeService = Depends(get_runtime_service),
) -> WorkflowPatchRead:
    try:
        return service.review_workflow_patch(patch_id, payload, approve=False)
    except ValueError as exc:
        _raise_runtime_http_error(exc)
