from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_container, get_session
from scene_pilot.repositories import (
    AgentGlobalMemoryRepository,
    ExecutionGraphProjectionRepository,
    ExecutionTraceRepository,
    GoalSpecRepository,
    AgentRunCheckpointRepository,
    AgentRunRepository,
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
    RecruitAgentProfileRepository,
    PersonResumeArtifactRepository,
    SkillRepository,
    StrategyFragmentRepository,
    TalentPoolSyncRecordRepository,
)
from scene_pilot.schemas import (
    AgentGlobalMemoryRead,
    AgentGlobalMemoryUpdate,
    ApprovalRead,
    ExecutionGraphProjectionRead,
    ExecutionTraceRead,
    EvolutionArtifactCreate,
    EvolutionArtifactRead,
    EvolutionArtifactUpdate,
    GoalSpecCreate,
    GoalSpecRead,
    GoalSpecUpdate,
    MemoryCompactRequest,
    OperatorInteractionRead,
    OperatorInteractionResolveRequest,
    RecruitAgentProfileRead,
    RecruitAgentProfileUpdate,
    RuntimeCheckpointRead,
    RuntimeControlledRunRead,
    RuntimeEventRead,
    RuntimeSessionRead,
    StrategyFragmentRead,
)
from scene_pilot.services.container import AppContainer
from scene_pilot.services.agent_control import AgentControlService
from scene_pilot.services.events import EventStreamService
from scene_pilot.services.evolution import promote_skill_draft_contract, resolve_promoted_skill_snapshot
from scene_pilot.services.recruit_agent import (
    AUTO_COMPACT_THRESHOLD,
    apply_memory_compaction,
    content_length,
    default_candidate_state_snapshot,
    ensure_global_memory,
    ensure_primary_recruit_agent_profile,
    needs_compaction,
    resolve_context_policy,
    resolve_memory_policy,
    validate_evolution_artifact,
)

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
    profile = RecruitAgentProfileRepository(session).primary() or ensure_primary_recruit_agent_profile(session)
    repo = AgentSessionRepository(session)
    item = repo.by_agent_and_key(agent_profile_id=profile.id, session_key="primary")
    if item is not None:
        return item
    return repo.create(
        {
            "agent_profile_id": profile.id,
            "session_key": "primary",
            "status": "active",
            "runtime_metadata": {"agent_key": profile.agent_key},
        }
    )


@router.get("/profile", response_model=RecruitAgentProfileRead)
def get_recruit_agent_profile(session: Session = Depends(get_session)) -> RecruitAgentProfileRead:
    profile = ensure_primary_recruit_agent_profile(session)
    return RecruitAgentProfileRead.model_validate(profile)


@router.patch("/profile", response_model=RecruitAgentProfileRead)
def update_recruit_agent_profile(
    payload: RecruitAgentProfileUpdate,
    session: Session = Depends(get_session),
) -> RecruitAgentProfileRead:
    repo = RecruitAgentProfileRepository(session)
    profile = ensure_primary_recruit_agent_profile(session)
    patch = payload.model_dump(exclude_unset=True)
    if isinstance(patch.get("role_definition"), dict):
        role_definition = dict(profile.role_definition or {})
        role_definition.update(dict(patch["role_definition"] or {}))
        patch["role_definition"] = role_definition
    if isinstance(patch.get("prompt_config"), dict):
        prompt_config = dict(profile.prompt_config or {})
        prompt_config.update(dict(patch["prompt_config"] or {}))
        prompt_config["context_policy"] = resolve_context_policy(prompt_config)
        patch["prompt_config"] = prompt_config
    if isinstance(patch.get("memory_policy"), dict):
        memory_policy = dict(profile.memory_policy or {})
        memory_policy.update(dict(patch["memory_policy"] or {}))
        patch["memory_policy"] = resolve_memory_policy(memory_policy)
    if payload.is_primary:
        for item in repo.list(limit=500, offset=0):
            if item.id != profile.id and item.is_primary:
                repo.update(item, {"is_primary": False})
    updated = repo.update(profile, patch)
    return RecruitAgentProfileRead.model_validate(updated)


@router.get("/global-memory", response_model=AgentGlobalMemoryRead)
def get_agent_global_memory(session: Session = Depends(get_session)) -> AgentGlobalMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    item = ensure_global_memory(session, agent_profile_id=profile.id)
    return AgentGlobalMemoryRead.model_validate(item)


@router.patch("/global-memory", response_model=AgentGlobalMemoryRead)
def update_agent_global_memory(
    payload: AgentGlobalMemoryUpdate,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> AgentGlobalMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    repo = AgentGlobalMemoryRepository(session)
    item = ensure_global_memory(session, agent_profile_id=profile.id)
    update_data = payload.model_dump(exclude_unset=True)
    if "content" in update_data:
        update_data.setdefault("raw_content", update_data["content"] or {})
        update_data["token_estimate"] = content_length(update_data["content"] or {})
        update_data["disclosure"] = {
            "preview": str(update_data.get("summary") or item.summary or "")[:180],
            "operator_summary": str(update_data.get("summary") or item.summary or ""),
            "model_context": str(update_data["content"])[:1600],
        }
    updated = repo.update(item, update_data)
    threshold = int(
        (((profile.memory_policy or {}).get("agent_global_memory") or {}).get("compact_threshold") or AUTO_COMPACT_THRESHOLD)
    )
    auto_compact = bool((((profile.memory_policy or {}).get("agent_global_memory") or {}).get("auto_compact") or False))
    if auto_compact and needs_compaction(dict(updated.content or {}), threshold=threshold):
        apply_memory_compaction(
            updated,
            provider=container.provider,
            scope="agent_global",
            reason="auto_compact_threshold_exceeded",
            compacted_at=_now(),
        )
        updated = repo.update(
            updated,
            {
                "summary": updated.summary,
                "raw_content": dict(updated.raw_content or {}),
                "content": dict(updated.content or {}),
                "disclosure": dict(updated.disclosure or {}),
                "token_estimate": updated.token_estimate,
                "compacted_at": updated.compacted_at,
                "compacted_reason": updated.compacted_reason,
                "memory_metadata": dict(updated.memory_metadata or {}),
            },
        )
    return AgentGlobalMemoryRead.model_validate(updated)


@router.post("/global-memory/compact", response_model=AgentGlobalMemoryRead)
def compact_agent_global_memory(
    payload: MemoryCompactRequest,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> AgentGlobalMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    repo = AgentGlobalMemoryRepository(session)
    item = ensure_global_memory(session, agent_profile_id=profile.id)
    if not payload.force and not needs_compaction(dict(item.content or {})):
        return AgentGlobalMemoryRead.model_validate(item)
    apply_memory_compaction(
        item,
        provider=container.provider,
        scope="agent_global",
        reason=payload.reason,
        compacted_at=_now(),
    )
    updated = repo.update(
        item,
        {
            "summary": item.summary,
            "raw_content": dict(item.raw_content or {}),
            "content": dict(item.content or {}),
            "disclosure": dict(item.disclosure or {}),
            "token_estimate": item.token_estimate,
            "compacted_at": item.compacted_at,
            "compacted_reason": item.compacted_reason,
            "memory_metadata": dict(item.memory_metadata or {}),
        },
    )
    return AgentGlobalMemoryRead.model_validate(updated)


@router.get("/goals", response_model=list[GoalSpecRead])
def list_goal_specs(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[GoalSpecRead]:
    profile = ensure_primary_recruit_agent_profile(session)
    items = GoalSpecRepository(session).list_recent(
        agent_profile_id=profile.id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [GoalSpecRead.model_validate(item) for item in items]


@router.post("/goals", response_model=GoalSpecRead, status_code=201)
def create_goal_spec(
    payload: GoalSpecCreate,
    session: Session = Depends(get_session),
    container: AppContainer = Depends(get_container),
) -> GoalSpecRead:
    profile = ensure_primary_recruit_agent_profile(session)
    agent_control = AgentControlService(container.session_factory)
    goal = GoalSpecRepository(session).create(
        {
            "agent_profile_id": profile.id,
            "title": payload.title,
            "goal_text": payload.goal_text,
            "goal_kind": payload.goal_kind,
            "status": "queued",
            "source": "operator",
            "source_text": payload.goal_text,
            "requested_by": payload.requested_by,
            "constraints": payload.constraints,
            "success_criteria": payload.success_criteria,
            "context_hints": payload.context_hints,
            "trial_budget": payload.trial_budget,
            "run_preferences": payload.run_preferences,
            "summary": payload.summary or f"围绕目标“{payload.title}”启动自适应招聘探索。",
            "last_activity_at": _now(),
            "goal_metadata": {
                "created_from": "desktop_workbench",
                "execution_mode": "adaptive_goal",
            },
        }
    )
    agent_control.enqueue_task(
        "goal_intake",
        payload={
            "goal_id": goal.id,
            "goal_text": goal.goal_text,
            "goal_kind": goal.goal_kind,
            "constraints": dict(goal.constraints or {}),
            "success_criteria": dict(goal.success_criteria or {}),
            "context_hints": dict(goal.context_hints or {}),
            "trial_budget": dict(goal.trial_budget or {}),
            "run_preferences": dict(goal.run_preferences or {}),
        },
        metadata={
            "requested_by": payload.requested_by,
            "goal_spec_id": goal.id,
            "lane": "agent",
            "mode": "adaptive_goal",
        },
        priority=payload.priority,
    )
    refreshed = GoalSpecRepository(session).get(goal.id)
    return GoalSpecRead.model_validate(refreshed or goal)


@router.patch("/goals/{goal_id}", response_model=GoalSpecRead)
def update_goal_spec(
    goal_id: str,
    payload: GoalSpecUpdate,
    session: Session = Depends(get_session),
) -> GoalSpecRead:
    repo = GoalSpecRepository(session)
    item = repo.get(goal_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    updated = repo.update(item, payload.model_dump(exclude_unset=True))
    return GoalSpecRead.model_validate(updated)


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal_spec(
    goal_id: str,
    session: Session = Depends(get_session),
) -> None:
    repo = GoalSpecRepository(session)
    item = repo.get(goal_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    session.delete(item)
    session.commit()
    return None


@router.get("/runtime/session", response_model=RuntimeSessionRead)
def get_runtime_session(session: Session = Depends(get_session)) -> RuntimeSessionRead:
    item = _ensure_runtime_session(session)
    return RuntimeSessionRead.model_validate(item)


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
        candidate_id=resolved_subject_id,
        limit=limit,
        offset=offset,
    )
    if resolved_application_id:
        items = [
            item
            for item in items
            if str((item.runtime_metadata or {}).get("application_id") or "").strip() == resolved_application_id
        ]
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
            fallback_application_id = str((run_item.runtime_metadata or {}).get("application_id") or "").strip() or None
    items = AgentRuntimeEventRepository(session).recent(
        session_id=session_record.id,
        run_id=run_id,
        limit=limit,
        offset=offset,
    )
    return [ _with_runtime_subjects(RuntimeEventRead, item, application_id=fallback_application_id) for item in items ]


@router.get("/runtime/traces", response_model=list[ExecutionTraceRead])
def list_runtime_traces(
    goal_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExecutionTraceRead]:
    session_record = _ensure_runtime_session(session)
    items = ExecutionTraceRepository(session).list_recent(
        goal_spec_id=goal_id,
        session_id=session_record.id,
        limit=limit,
        offset=offset,
    )
    return [ExecutionTraceRead.model_validate(item) for item in items]


@router.get("/runtime/graphs", response_model=list[ExecutionGraphProjectionRead])
def list_runtime_graphs(
    goal_id: str | None = Query(default=None),
    application_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExecutionGraphProjectionRead]:
    resolved_subject_id, resolved_application_id = _runtime_subject_filter_ids(session, application_id)
    items = ExecutionGraphProjectionRepository(session).list_recent(
        goal_spec_id=goal_id,
        candidate_id=resolved_subject_id,
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
    profile = ensure_primary_recruit_agent_profile(session)
    items = StrategyFragmentRepository(session).list_recent(
        agent_profile_id=profile.id,
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
        candidate_id=resolved_subject_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    if resolved_application_id:
        items = [
            item
            for item in items
            if str((item.interaction_metadata or {}).get("application_id") or "").strip() == resolved_application_id
        ]
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
    profile = ensure_primary_recruit_agent_profile(session)
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
            "agent_profile_id": payload.agent_profile_id or profile.id,
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
