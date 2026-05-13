from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from recruit_agent.api.deps import get_container, get_session
from recruit_agent.repositories import (
    ExecutionGraphProjectionRepository,
    ExecutionTraceRepository,
    ExecutionEpisodeRepository,
    ExecutionPlanRepository,
    EnvironmentSnapshotRepository,
    AgentRunCheckpointRepository,
    AgentRuntimeEventRepository,
    AgentSessionRepository,
    OperatorInteractionRepository,
    ApprovalRepository,
    CandidateAssessmentRepository,
    CandidateApplicationRepository,
    CandidateAssignmentRepository,
    CandidateRepository,
    CandidateReviewDecisionRepository,
    CandidateScorecardRepository,
    CandidateSessionRepository,
    CandidateStatusTransitionRepository,
    CommunicationLogRepository,
    EvolutionArtifactRepository,
    AgentDefinitionRepository,
    PersonResumeArtifactRepository,
    SkillRepository,
    StrategyFragmentRepository,
    TaskSpecRepository,
    TalentPoolSyncRecordRepository,
)
from recruit_agent.schemas import (
    ApprovalRead,
    CapabilityDriverRead,
    DomainPackRead,
    EnvironmentSnapshotRead,
    ExecutionGraphProjectionRead,
    ExecutionEpisodeCreate,
    ExecutionEpisodeRead,
    ExecutionPlanCreate,
    ExecutionPlanRead,
    ExecutionTraceRead,
    EvolutionArtifactCreate,
    EvolutionArtifactRead,
    EvolutionArtifactUpdate,
    OperatorInteractionRead,
    OperatorInteractionResolveRequest,
    AgentDefinitionRead,
    AgentDefinitionUpdate,
    RuntimeCheckpointRead,
    RuntimeControlledRunRead,
    RuntimeEventRead,
    RuntimePlanEnqueueRead,
    RuntimePlanEnqueueRequest,
    RuntimeSessionRead,
    StrategyFragmentRead,
    TaskCompileRequest,
    TaskCompileResponse,
    TaskCompilerContractRead,
    TaskSpecCreate,
    TaskSpecRead,
)
from recruit_agent.services.container import AppContainer
from recruit_agent.services.agent_control import AgentControlService
from recruit_agent.services.events import EventStreamService
from recruit_agent.services.evolution import promote_skill_draft_contract, resolve_promoted_skill_snapshot
from recruit_agent.services.recruit_agent import (
    default_candidate_state_snapshot,
    ensure_primary_agent_definition,
    normalize_prompt_config,
    resolve_context_policy,
    resolve_memory_policy,
    validate_evolution_artifact,
)
from recruit_agent.services.scene_templates import shared_scene_template_catalog

router = APIRouter(prefix="/api/recruit-agent", tags=["recruit-agent"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    return None


def _get_candidate_or_404(session: Session, candidate_id: str):
    item = CandidateRepository(session).resolve(candidate_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return item


def _runtime_subject_filter_ids(session: Session, subject_id: str | None) -> tuple[str | None, str | None]:
    text = str(subject_id or "").strip()
    if not text:
        return None, None
    application = CandidateApplicationRepository(session).get(text)
    if application is not None:
        person = CandidateRepository(session).get_by_storage_id(application.person_id)
        return (
            str(person.candidate_person_id or "").strip() or None if person is not None else None,
            application.candidate_application_id,
        )
    person = CandidateRepository(session).resolve(text)
    if person is not None:
        return str(person.candidate_person_id or "").strip() or None, None
    return text, None


def _with_runtime_subjects(model_cls, item, *, application_id: str | None = None):
    payload = item
    if hasattr(item, "model_dump"):
        payload = dict(item.model_dump(exclude_unset=True))
    elif hasattr(item, "__dict__"):
        payload = {key: value for key, value in vars(item).items() if not key.startswith("_")}
    if isinstance(payload, dict):
        if application_id and not str(payload.get("application_id") or "").strip():
            payload["application_id"] = application_id
        return model_cls.model_validate(payload)
    return model_cls.model_validate(item)


def _ensure_runtime_session(session: Session):
    definition = AgentDefinitionRepository(session).primary() or ensure_primary_agent_definition(session)
    repo = AgentSessionRepository(session)
    item = repo.by_agent_and_key(agent_definition_id=definition.id, session_key="autonomous")
    if item is not None:
        return item
    return repo.create(
        {
            "agent_definition_id": definition.id,
            "session_key": "autonomous",
            "status": "active",
            "runtime_metadata": {"agent_definition_key": definition.definition_key, "agent_kind": "autonomous"},
        }
    )


def _scene_domain_pack() -> DomainPackRead:
    templates = shared_scene_template_catalog()
    return DomainPackRead(
        key="scene",
        name="Scene execution",
        description="Delegated scene tasks compiled from ordinary instructions.",
        runtime_only=True,
        default_capabilities=[item.key for item in _runtime_capability_drivers()],
        sample_tasks=[str(item.get("default_instruction") or item.get("summary") or item.get("title") or "") for item in list(templates.values())[:5]],
        default_constraints={"approval_policy": "product_adapter"},
        default_output_contract={"summary": "business-level result"},
        template_keys=list(templates.keys()),
        compiler_hints=["Use instruction as the task body; do not create a separate durable target object."],
        quality_gates={"requires_instruction": True},
        template_count=len(templates),
        active_template_count=len(templates),
    )


def _task_compiler_contract() -> TaskCompilerContractRead:
    return TaskCompilerContractRead(
        strategy="Create a TaskSpec from the instruction and optionally a trial ExecutionPlan.",
        fallback_strategy="If no domain hint is provided, compile into the scene domain.",
        prompt_asset="tasks/runtime_task_compiler",
        required_fields=["instruction"],
        optional_fields=["title", "description", "domain_hint", "inputs", "constraints", "success_criteria", "approval_policy", "output_contract", "preferred_capabilities"],
        invariants=[
            "TaskSpec is a compiled task artifact, not an Agent target.",
            "Autonomous run input remains AgentRun.context_manifest.instruction.",
        ],
        quality_gates=["instruction must be non-empty"],
        repair_policy={"invalid_instruction": "reject"},
        available_domains=[_scene_domain_pack()],
        available_capabilities=_runtime_capability_drivers(),
    )


def _runtime_capability_drivers() -> list[CapabilityDriverRead]:
    return [
        CapabilityDriverRead(
            key="business_tool_loop",
            description="Use governed recruiting business tools through the shared Agent tool registry.",
            risk="medium",
            supported_domains=["scene", "recruiting"],
            recommended_scene_types=["candidate_discovery", "candidate_review", "jd_sync"],
            signal_labels=["tool_result", "business_projection"],
            preferred_tools=["list_candidates", "upsert_candidate", "transition_application"],
            writes_state=True,
            requires_supervision=True,
            audit_tags=["business_tool"],
        ),
        CapabilityDriverRead(
            key="mcp_tool_loop",
            description="Use enabled MCP tools exposed as ordinary Agent tools.",
            risk="medium",
            supported_domains=["scene", "recruiting"],
            recommended_scene_types=["external_page_inspection"],
            signal_labels=["mcp_tool_result"],
            preferred_tools=["list_mcp_resources", "read_mcp_resource"],
            requires_supervision=True,
            audit_tags=["mcp"],
        ),
        CapabilityDriverRead(
            key="memory_context",
            description="Read and update Agent file memory through governed memory tools.",
            risk="low",
            supported_domains=["scene", "recruiting"],
            recommended_scene_types=["context_recall"],
            signal_labels=["memory_entry"],
            preferred_tools=["read_memory", "read_memory_file", "write_memory_file"],
            writes_state=True,
            audit_tags=["memory"],
        ),
    ]


def _task_title(instruction: str) -> str:
    normalized = " ".join(str(instruction or "").split())
    if not normalized:
        return "Runtime task"
    return normalized[:80]


def _task_key(instruction: str) -> str:
    normalized = "_".join(str(instruction or "").lower().split())
    return normalized[:80] or "runtime_task"


@router.get("/agent-definition", response_model=AgentDefinitionRead)
def get_agent_definition(session: Session = Depends(get_session)) -> AgentDefinitionRead:
    definition = ensure_primary_agent_definition(session)
    return AgentDefinitionRead.model_validate(definition)


@router.patch("/agent-definition", response_model=AgentDefinitionRead)
def update_agent_definition(
    payload: AgentDefinitionUpdate,
    session: Session = Depends(get_session),
) -> AgentDefinitionRead:
    repo = AgentDefinitionRepository(session)
    definition = ensure_primary_agent_definition(session)
    patch = payload.model_dump(exclude_unset=True)
    if isinstance(patch.get("role_definition"), dict):
        role_definition = dict(definition.role_definition or {})
        role_definition.update(dict(patch["role_definition"] or {}))
        patch["role_definition"] = role_definition
    if isinstance(patch.get("prompt_config"), dict):
        prompt_config = dict(definition.prompt_config or {})
        prompt_config.update(dict(patch["prompt_config"] or {}))
        prompt_config = normalize_prompt_config(prompt_config)
        prompt_config["context_policy"] = resolve_context_policy(prompt_config)
        patch["prompt_config"] = prompt_config
    if isinstance(patch.get("memory_policy"), dict):
        memory_policy = dict(definition.memory_policy or {})
        memory_policy.update(dict(patch["memory_policy"] or {}))
        patch["memory_policy"] = resolve_memory_policy(memory_policy)
    if payload.is_primary:
        for item in repo.list(limit=500, offset=0):
            if item.id != definition.id and item.is_primary:
                repo.update(item, {"is_primary": False})
    updated = repo.update(definition, patch)
    return AgentDefinitionRead.model_validate(updated)


@router.get("/runtime/session", response_model=RuntimeSessionRead)
def get_runtime_session(session: Session = Depends(get_session)) -> RuntimeSessionRead:
    item = _ensure_runtime_session(session)
    return RuntimeSessionRead.model_validate(item)


@router.get("/runtime/compiler-contract", response_model=TaskCompilerContractRead)
def get_task_compiler_contract() -> TaskCompilerContractRead:
    return _task_compiler_contract()


@router.get("/runtime/domain-packs", response_model=list[DomainPackRead])
def list_runtime_domain_packs() -> list[DomainPackRead]:
    return [_scene_domain_pack()]


@router.get("/runtime/capabilities", response_model=list[CapabilityDriverRead])
def list_runtime_capabilities() -> list[CapabilityDriverRead]:
    return _runtime_capability_drivers()


@router.get("/runtime/task-specs", response_model=list[TaskSpecRead])
def list_runtime_task_specs(
    status: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[TaskSpecRead]:
    repo = TaskSpecRepository(session)
    if domain:
        items = repo.by_domain(domain, limit=limit, offset=offset)
    elif status:
        items = repo.list_by_status(status, limit=limit, offset=offset)
    else:
        items = repo.list(limit=limit, offset=offset)
    return [TaskSpecRead.model_validate(item) for item in items]


@router.post("/runtime/task-specs/compile", response_model=TaskCompileResponse)
def compile_runtime_task(payload: TaskCompileRequest, session: Session = Depends(get_session)) -> TaskCompileResponse:
    instruction = str(payload.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=422, detail="instruction must not be empty")
    domain_pack = _scene_domain_pack()
    task_spec = TaskSpecRepository(session).create(
        TaskSpecCreate(
            title=payload.title or _task_title(instruction),
            description=payload.description,
            instruction=instruction,
            domain=payload.domain_hint or "scene",
            status="planned" if payload.auto_plan else "draft",
            source_kind="natural_language",
            source_text=instruction,
            inputs=dict(payload.inputs or {}),
            constraints=dict(payload.constraints or {}),
            success_criteria=dict(payload.success_criteria or {}),
            approval_policy=dict(payload.approval_policy or {}),
            output_contract=dict(payload.output_contract or {}),
            preferred_capabilities=list(payload.preferred_capabilities or []),
            preferred_domains=list(payload.preferred_domains or ["scene"]),
            compiled_payload={
                "task_key": _task_key(instruction),
                "requested_by": payload.requested_by,
            },
        )
    )
    execution_plan = None
    if payload.auto_plan:
        execution_plan = ExecutionPlanRepository(session).create(
            ExecutionPlanCreate(
                task_spec_id=task_spec.id,
                name=task_spec.title,
                mode="trial",
                status="planned",
                approval_state="approved",
                plan_body={
                    "instruction": instruction,
                    "success_criteria": dict(payload.success_criteria or {}),
                    "output_contract": dict(payload.output_contract or {}),
                },
                environment_requirements=dict(payload.constraints or {}),
                checkpoints=[],
                runtime_metadata={"compiled_from": "runtime_task_compiler"},
            )
        )
        task_spec.active_plan_id = execution_plan.id
        session.commit()
        session.refresh(task_spec)
    return TaskCompileResponse(
        domain_pack=domain_pack,
        compiler_notes=["Compiled as a runtime task spec without a separate durable target object."],
        task_spec=TaskSpecRead.model_validate(task_spec),
        execution_plan=None if execution_plan is None else ExecutionPlanRead.model_validate(execution_plan),
    )


@router.get("/runtime/execution-plans", response_model=list[ExecutionPlanRead])
def list_runtime_execution_plans(
    task_spec_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExecutionPlanRead]:
    repo = ExecutionPlanRepository(session)
    items = repo.by_task_spec(task_spec_id, limit=limit, offset=offset) if task_spec_id else repo.list(limit=limit, offset=offset)
    return [ExecutionPlanRead.model_validate(item) for item in items]


@router.post("/runtime/execution-plans", response_model=ExecutionPlanRead)
def create_runtime_execution_plan(payload: ExecutionPlanCreate, session: Session = Depends(get_session)) -> ExecutionPlanRead:
    task_spec = TaskSpecRepository(session).get(payload.task_spec_id)
    if task_spec is None:
        raise HTTPException(status_code=404, detail="task spec not found")
    item = ExecutionPlanRepository(session).create(payload)
    return ExecutionPlanRead.model_validate(item)


@router.post("/runtime/execution-plans/{plan_id}/launch", response_model=RuntimePlanEnqueueRead)
def launch_runtime_execution_plan(
    plan_id: str,
    payload: RuntimePlanEnqueueRequest,
    session: Session = Depends(get_session),
) -> RuntimePlanEnqueueRead:
    plan = ExecutionPlanRepository(session).get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="execution plan not found")
    task_spec_id = payload.task_spec_id or plan.task_spec_id
    if TaskSpecRepository(session).get(task_spec_id) is None:
        raise HTTPException(status_code=404, detail="task spec not found")
    episode = ExecutionEpisodeRepository(session).create(
        ExecutionEpisodeCreate(
            task_spec_id=task_spec_id,
            execution_plan_id=plan.id,
            mode=payload.mode,
            status="pending",
            requested_by=payload.requested_by,
            requires_confirmation=True,
            runtime_metadata=dict(payload.runtime_metadata or {}),
        )
    )
    return RuntimePlanEnqueueRead(
        task_id=episode.id,
        task_type="runtime_execution_episode",
        priority=payload.priority,
        queue_depth=0,
        task_spec_id=task_spec_id,
        execution_plan_id=plan.id,
        execution_episode=ExecutionEpisodeRead.model_validate(episode),
    )


@router.get("/runtime/execution-episodes", response_model=list[ExecutionEpisodeRead])
def list_runtime_execution_episodes(
    execution_plan_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExecutionEpisodeRead]:
    repo = ExecutionEpisodeRepository(session)
    items = repo.by_plan(execution_plan_id, limit=limit, offset=offset) if execution_plan_id else repo.list(limit=limit, offset=offset)
    return [ExecutionEpisodeRead.model_validate(item) for item in items]


@router.post("/runtime/execution-episodes", response_model=ExecutionEpisodeRead)
def create_runtime_execution_episode(payload: ExecutionEpisodeCreate, session: Session = Depends(get_session)) -> ExecutionEpisodeRead:
    if TaskSpecRepository(session).get(payload.task_spec_id) is None:
        raise HTTPException(status_code=404, detail="task spec not found")
    if ExecutionPlanRepository(session).get(payload.execution_plan_id) is None:
        raise HTTPException(status_code=404, detail="execution plan not found")
    item = ExecutionEpisodeRepository(session).create(payload)
    return ExecutionEpisodeRead.model_validate(item)


@router.get("/runtime/snapshots", response_model=list[EnvironmentSnapshotRead])
def list_runtime_snapshots(
    execution_episode_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[EnvironmentSnapshotRead]:
    repo = EnvironmentSnapshotRepository(session)
    items = repo.for_episode(execution_episode_id, limit=limit, offset=offset) if execution_episode_id else repo.list(limit=limit, offset=offset)
    return [EnvironmentSnapshotRead.model_validate(item) for item in items]


@router.get("/runtime/runs", response_model=list[RuntimeControlledRunRead])
def list_runtime_runs(
    status: str | None = Query(default=None),
    lane: str | None = Query(default=None),
    application_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[RuntimeControlledRunRead]:
    session_record = _ensure_runtime_session(session)
    resolved_subject_id, resolved_application_id = _runtime_subject_filter_ids(session, application_id)
    items = AgentRunRepository(session).list_filtered(
        session_id=session_record.id,
        status=status,
        lane=lane,
        person_id=resolved_subject_id,
        application_id=resolved_application_id,
        limit=limit,
        offset=offset,
    )
    return [RuntimeControlledRunRead.model_validate(item) for item in items]


@router.get("/runtime/checkpoints", response_model=list[RuntimeCheckpointRead])
def list_runtime_checkpoints(
    open_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[RuntimeCheckpointRead]:
    session_record = _ensure_runtime_session(session)
    repo = AgentRunCheckpointRepository(session)
    if open_only:
        items = repo.list_open(session_id=session_record.id, limit=limit, offset=offset)
    else:
        items = [
            item
            for item in repo.list(limit=max(limit + offset, limit), offset=0)
            if item.session_id == session_record.id
        ][offset : offset + limit]
    return [RuntimeCheckpointRead.model_validate(item) for item in items]


@router.get("/runtime/events", response_model=list[RuntimeEventRead])
def list_runtime_events(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[RuntimeEventRead]:
    session_record = _ensure_runtime_session(session)
    fallback_application_id = None
    if run_id:
        run_item = AgentRunRepository(session).get(run_id)
        if run_item is not None:
            fallback_application_id = str(run_item.application_id or (run_item.runtime_metadata or {}).get("application_id") or "").strip() or None
    items = AgentRuntimeEventRepository(session).recent(
        session_id=session_record.id,
        run_id=run_id,
        limit=limit,
        offset=offset,
    )
    return [ _with_runtime_subjects(RuntimeEventRead, item, application_id=fallback_application_id) for item in items ]


@router.get("/runtime/traces", response_model=list[ExecutionTraceRead])
def list_runtime_traces(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExecutionTraceRead]:
    session_record = _ensure_runtime_session(session)
    items = ExecutionTraceRepository(session).list_recent(
        session_id=session_record.id,
        run_id=run_id,
        limit=limit,
        offset=offset,
    )
    return [ExecutionTraceRead.model_validate(item) for item in items]


@router.get("/runtime/graphs", response_model=list[ExecutionGraphProjectionRead])
def list_runtime_graphs(
    run_id: str | None = Query(default=None),
    application_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExecutionGraphProjectionRead]:
    resolved_subject_id, resolved_application_id = _runtime_subject_filter_ids(session, application_id)
    items = ExecutionGraphProjectionRepository(session).list_recent(
        candidate_id=resolved_subject_id,
        run_id=run_id,
        limit=limit,
        offset=offset,
    )
    if resolved_application_id:
        items = [
            item
            for item in items
            if str((item.graph_metadata or {}).get("application_id") or "").strip() == resolved_application_id
        ]
    return [ExecutionGraphProjectionRead.model_validate(item) for item in items]


@router.get("/runtime/strategy-fragments", response_model=list[StrategyFragmentRead])
def list_strategy_fragments(
    status: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[StrategyFragmentRead]:
    definition = ensure_primary_agent_definition(session)
    items = StrategyFragmentRepository(session).list_recent(
        agent_definition_id=definition.id,
        status=status,
        scope=scope,
        limit=limit,
        offset=offset,
    )
    return [StrategyFragmentRead.model_validate(item) for item in items]


@router.get("/runtime/operator-interactions", response_model=list[OperatorInteractionRead])
def list_operator_interactions(
    status: str | None = Query(default=None),
    application_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[OperatorInteractionRead]:
    session_record = _ensure_runtime_session(session)
    resolved_subject_id, resolved_application_id = _runtime_subject_filter_ids(session, application_id)
    items = OperatorInteractionRepository(session).list_recent(
        session_id=session_record.id,
        person_id=resolved_subject_id,
        application_id=resolved_application_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [OperatorInteractionRead.model_validate(item) for item in items]


@router.post("/runtime/operator-interactions/{interaction_id}/resolve", response_model=OperatorInteractionRead)
def resolve_operator_interaction(
    interaction_id: str,
    payload: OperatorInteractionResolveRequest,
    session: Session = Depends(get_session),
    container: AppContainer = Depends(get_container),
) -> OperatorInteractionRead:
    repo = OperatorInteractionRepository(session)
    agent_control = AgentControlService(container.session_factory)
    item = repo.get(interaction_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Operator interaction not found")
    if item.status != "pending":
        return OperatorInteractionRead.model_validate(item)

    action = payload.action.strip().lower()
    approval = ApprovalRepository(session).get(item.approval_id) if item.approval_id else None
    effect_summary = None
    if approval is not None:
        if action in {"confirm", "approve", "retry", "correct", "teach"}:
            updated_approval = agent_control.apply_approval_resolution(
                session,
                approval,
                status="approved",
                reviewer=payload.operator,
                notes=payload.comment,
            )
            ApprovalRepository(session).mark_review(
                updated_approval,
                "approved",
                reviewer=payload.operator,
                notes=payload.comment,
            )
            effect_summary = "已按操作员确认恢复运行。"
        elif action in {"reject", "stop", "handoff"}:
            updated_approval = agent_control.apply_approval_resolution(
                session,
                approval,
                status="rejected",
                reviewer=payload.operator,
                notes=payload.comment,
            )
            ApprovalRepository(session).mark_review(
                updated_approval,
                "rejected",
                reviewer=payload.operator,
                notes=payload.comment,
            )
            effect_summary = "已停止当前路径，等待人工后续处理。"
        else:
            raise HTTPException(status_code=400, detail="Unsupported operator action")
    else:
        effect_summary = "已记录操作员输入，供后续运行参考。"

    updated = repo.update(
        item,
        {
            "status": "resolved",
            "operator_response": {
                "action": action,
                "comment": payload.comment,
                "scope": payload.scope or item.scope,
            },
            "effect_summary": effect_summary,
            "resolved_at": _now(),
            "resolved_by": payload.operator,
        },
    )
    return OperatorInteractionRead.model_validate(updated)


@router.get("/evolution-artifacts", response_model=list[EvolutionArtifactRead])
def list_evolution_artifacts(
    artifact_kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[EvolutionArtifactRead]:
    items = EvolutionArtifactRepository(session).list_filtered(
        artifact_kind=artifact_kind,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [EvolutionArtifactRead.model_validate(item) for item in items]


@router.post("/evolution-artifacts", response_model=EvolutionArtifactRead, status_code=201)
def create_evolution_artifact(
    payload: EvolutionArtifactCreate,
    session: Session = Depends(get_session),
) -> EvolutionArtifactRead:
    definition = ensure_primary_agent_definition(session)
    try:
        validate_evolution_artifact(
            artifact_kind=payload.artifact_kind,
            status=payload.status,
            artifact_body=dict(payload.artifact_body or {}),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    item = EvolutionArtifactRepository(session).create(
        {
            **payload.model_dump(exclude_unset=True),
            "agent_definition_id": payload.agent_definition_id or definition.id,
        }
    )
    return EvolutionArtifactRead.model_validate(item)


@router.patch("/evolution-artifacts/{artifact_id}", response_model=EvolutionArtifactRead)
def update_evolution_artifact(
    artifact_id: str,
    payload: EvolutionArtifactUpdate,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> EvolutionArtifactRead:
    repo = EvolutionArtifactRepository(session)
    item = repo.get(artifact_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evolution artifact not found")
    next_status = payload.status or item.status
    next_body = payload.artifact_body if payload.artifact_body is not None else dict(item.artifact_body or {})
    try:
        validate_evolution_artifact(
            artifact_kind=item.artifact_kind,
            status=next_status,
            artifact_body=dict(next_body or {}),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    update_payload = payload.model_dump(exclude_unset=True)

    if item.artifact_kind == "skill_draft" and next_status in {"approved", "applied"}:
        artifact_metadata = {
            **dict(item.artifact_metadata or {}),
            **dict(payload.artifact_metadata or {}),
        }
        promoted_skill = resolve_promoted_skill_snapshot(artifact_metadata)
        if promoted_skill is None and item.related_skill_id:
            skill = SkillRepository(session).get(item.related_skill_id)
            if skill is not None:
                promoted_skill = {
                    "id": skill.id,
                    "skill_id": skill.skill_id,
                    "name": skill.name,
                    "status": skill.status,
                    "version": skill.version,
                }
        if promoted_skill is None:
            promoted_skill = promote_skill_draft_contract(
                session,
                auto_activate=bool(container.settings.provider_config.get("skills_auto_activate", False)),
                draft=dict(next_body or {}),
                reviewer=payload.reviewed_by,
                reason=str(artifact_metadata.get("review_reason") or "").strip() or None,
                fallback_title=item.title,
                fallback_platform=str(artifact_metadata.get("promotion_fallback_platform") or "").strip() or "runtime-scene",
                fallback_stage=str(
                    artifact_metadata.get("promotion_fallback_stage")
                    or artifact_metadata.get("bound_to_stage")
                    or artifact_metadata.get("task_type")
                    or ""
                ).strip()
                or None,
                learning_id=str(artifact_metadata.get("learning_id") or "").strip() or None,
                promotion_source="evolution_artifact",
                source_kind="evolution_artifact",
                source_id=item.id,
            )
        merged_metadata = {
            **artifact_metadata,
            "promoted_skill": promoted_skill,
        }
        update_payload.update(
            {
                "status": "applied",
                "reviewed_at": payload.reviewed_at or _now(),
                "applied_at": payload.applied_at or _now(),
                "related_skill_id": promoted_skill["id"],
                "artifact_metadata": merged_metadata,
            }
        )
    updated = repo.update(item, update_payload)
    return EvolutionArtifactRead.model_validate(updated)
