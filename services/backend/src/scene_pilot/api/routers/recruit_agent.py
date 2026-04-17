from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_container, get_session
from scene_pilot.repositories import (
    AgentGlobalMemoryRepository,
    ApplicationAssessmentRepository,
    ApplicationAssignmentRepository,
    ApplicationCommunicationLogRepository,
    ApplicationReviewDecisionRepository,
    ApplicationScorecardRepository,
    ApplicationSessionRepository,
    ApplicationStatusTransitionRepository,
    ApplicationSyncRecordRepository,
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
    CandidateMemoryRepository,
    CandidateRepository,
    CandidateReviewDecisionRepository,
    CandidateScorecardRepository,
    CandidateSessionRepository,
    CandidateStatusTransitionRepository,
    CommunicationLogRepository,
    EvolutionArtifactRepository,
    JobMemoryRepository,
    RecruitAgentProfileRepository,
    PersonResumeArtifactRepository,
    ResumeArtifactRepository,
    SkillRepository,
    StrategyFragmentRepository,
    TalentPoolSyncRecordRepository,
)
from scene_pilot.schemas import (
    AgentGlobalMemoryRead,
    AgentGlobalMemoryUpdate,
    ApprovalRead,
    CandidateAssessmentCreate,
    CandidateAssessmentRead,
    CandidateAssignmentCreate,
    CandidateAssignmentRead,
    CandidateConversationEntryCreate,
    CandidateConversationEntryRead,
    CandidateMemoryRead,
    CandidateMemoryUpdate,
    CandidateRead,
    CandidateReviewDecisionCreate,
    CandidateReviewDecisionRead,
    CandidateScorecardCreate,
    CandidateScorecardRead,
    CandidateStatusTransitionRead,
    CandidateStateSnapshotRead,
    CandidateStateTransitionRequest,
    CandidateThreadRead,
    ExecutionGraphProjectionRead,
    ExecutionTraceRead,
    EvolutionArtifactCreate,
    EvolutionArtifactRead,
    EvolutionArtifactUpdate,
    GoalSpecCreate,
    GoalSpecRead,
    GoalSpecUpdate,
    JobMemoryRead,
    JobMemoryUpdate,
    MemoryCompactRequest,
    OperatorInteractionRead,
    OperatorInteractionResolveRequest,
    RecruitAgentProfileRead,
    RecruitAgentProfileUpdate,
    ResumeArtifactCreate,
    ResumeArtifactRead,
    RuntimeCheckpointRead,
    RuntimeControlledRunRead,
    RuntimeEventRead,
    RuntimeSessionRead,
    StrategyFragmentRead,
    TalentPoolSyncRecordCreate,
    TalentPoolSyncRecordRead,
)
from scene_pilot.services.container import AppContainer
from scene_pilot.services.application_subjects import application_id_for_candidate, job_description_id_for_candidate, person_id_for_candidate
from scene_pilot.services.events import EventStreamService
from scene_pilot.services.evolution import promote_skill_draft_contract, resolve_promoted_skill_snapshot
from scene_pilot.services.recruit_agent import (
    AUTO_COMPACT_THRESHOLD,
    apply_memory_compaction,
    content_length,
    default_candidate_state_snapshot,
    ensure_candidate_memory,
    ensure_global_memory,
    ensure_job_memory,
    ensure_primary_recruit_agent_profile,
    needs_compaction,
    resolve_context_policy,
    validate_evolution_artifact,
)
from scene_pilot.services.candidate_identity import relink_application_person_by_contact_info
from scene_pilot.services.state_machine import available_state_statuses, transition_candidate

router = APIRouter(prefix="/api/recruit-agent", tags=["recruit-agent"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_candidate_or_404(session: Session, candidate_id: str):
    item = CandidateRepository(session).resolve(candidate_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return item


def _get_candidate_for_application_or_404(session: Session, application_id: str):
    application = CandidateApplicationRepository(session).get(application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Candidate application not found")
    candidate = CandidateRepository(session).resolve(application.person_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate person not found")
    return application, candidate


def _with_application_id(model_cls, item, application_id: str, person_id: str | None = None):
    if hasattr(item, "model_dump"):
        payload = dict(item.model_dump(exclude_unset=True))
    elif hasattr(item, "__dict__"):
        payload = {key: value for key, value in vars(item).items() if not key.startswith("_")}
    else:
        payload = dict(item)
    payload["application_id"] = payload.get("application_id") or application_id
    payload["person_id"] = payload.get("person_id") or person_id
    return model_cls.model_validate(payload)


def _runtime_person_filter_id(session: Session, candidate_id: str | None) -> str | None:
    text = str(candidate_id or "").strip()
    if not text:
        return None
    application = CandidateApplicationRepository(session).get(text)
    if application is not None:
        return application.person_id
    return text


def _candidate_read_for_application(candidate, application) -> CandidateRead:
    return CandidateRead.model_validate(
        {
            "id": candidate.id,
            "name": candidate.name,
            "platform": application.platform or candidate.platform,
            "platform_candidate_id": candidate.platform_candidate_id,
            "current_status": application.current_status,
            "current_stage_key": application.current_stage_key,
            "deepest_milestone": application.deepest_milestone,
            "job_description_id": application.job_description_id or candidate.job_description_id,
            "contact_info": dict(candidate.contact_info or {}),
            "state_snapshot": dict(application.state_snapshot or {}),
            "resume_path": candidate.resume_path,
            "online_resume_text": candidate.online_resume_text,
            "ai_scores": dict(application.ai_scores or candidate.ai_scores or {}),
            "ai_reasoning": application.ai_reasoning or candidate.ai_reasoning,
            "cooldown_until": application.cooldown_until or candidate.cooldown_until,
            "last_contacted_at": application.last_contacted_at or candidate.last_contacted_at,
            "created_at": candidate.created_at,
            "updated_at": candidate.updated_at,
        }
    )


def _runtime_approvals_for_application(session: Session, application_id: str, person_id: str | None = None) -> list[ApprovalRead]:
    items = []
    for approval in ApprovalRepository(session).list(limit=500, offset=0):
        payload = dict(approval.payload or {})
        if approval.target_id in {application_id, person_id}:
            items.append(approval)
            continue
        if str(payload.get("application_id") or "") == application_id:
            items.append(approval)
            continue
        if str(payload.get("candidate_id") or "") in {application_id, person_id}:
            items.append(approval)
            continue
        blocked = payload.get("blocked_task") if isinstance(payload.get("blocked_task"), dict) else {}
        if str(blocked.get("application_id") or "") == application_id:
            items.append(approval)
            continue
        if str(blocked.get("candidate_id") or "") in {application_id, person_id}:
            items.append(approval)
    return [ApprovalRead.model_validate(item) for item in items]


def _runtime_interactions_for_application(session: Session, application_id: str, person_id: str | None = None) -> list[OperatorInteractionRead]:
    items = OperatorInteractionRepository(session).list_recent(candidate_id=application_id, limit=100, offset=0)
    if not items and person_id and person_id != application_id:
        items = OperatorInteractionRepository(session).list_recent(candidate_id=person_id, limit=100, offset=0)
    return [OperatorInteractionRead.model_validate(item) for item in items]


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


def _candidate_state_snapshot(candidate) -> CandidateStateSnapshotRead:
    current_status = candidate.current_status
    payload = dict(candidate.state_snapshot or {})
    if not payload:
        payload = default_candidate_state_snapshot(status=current_status)
    if payload.get("current_stage_key") in {None, ""}:
        payload["current_stage_key"] = current_status
    if payload.get("current_stage_label") in {None, ""}:
        payload["current_stage_label"] = str(payload["current_stage_key"]).replace("_", " ")
    if payload.get("contact_channels") is None:
        payload["contact_channels"] = []
    if payload.get("interview_plan") is None:
        payload["interview_plan"] = default_candidate_state_snapshot(status=current_status)["interview_plan"]
    return CandidateStateSnapshotRead.model_validate(payload)


def _build_candidate_thread(session: Session, application, candidate) -> CandidateThreadRead:
    application_id = application.id
    person_id = candidate.id
    session_repo = ApplicationSessionRepository(session)
    logs_repo = ApplicationCommunicationLogRepository(session)
    transition_repo = ApplicationStatusTransitionRepository(session)
    assessment_repo = ApplicationAssessmentRepository(session)
    assignment_repo = ApplicationAssignmentRepository(session)
    resume_repo = ResumeArtifactRepository(session)
    scorecard_repo = ApplicationScorecardRepository(session)
    review_repo = ApplicationReviewDecisionRepository(session)
    sync_repo = ApplicationSyncRecordRepository(session)
    candidate_session = session_repo.by_application_id(application.id)
    logs = logs_repo.by_application(application.id, limit=200, offset=0)
    status_transitions = [
        _with_application_id(CandidateStatusTransitionRead, item, application_id, person_id)
        for item in transition_repo.by_application(application.id, limit=200, offset=0)
    ]
    assessments = assessment_repo.by_application(application.id, limit=50, offset=0)
    if application.ai_scores and not any(item.assessment_type == "ai" for item in assessments):
        assessments = [
            CandidateAssessmentRead(
                id=f"synthetic-ai-{application.id}",
                candidate_id=person_id,
                application_id=application_id,
                assessment_type="ai",
                stage_key=application.current_stage_key or application.current_status,
                status="completed",
                decision=str((application.ai_scores or {}).get("decision") or "pending"),
                score=int((application.ai_scores or {}).get("overall") or 0),
                summary=application.ai_reasoning or "AI 评估已生成。",
                evidence_refs=list((application.ai_scores or {}).get("evidence_refs") or []),
                metadata={"source": "application.ai_scores", "synthetic": True},
                created_by="agent",
                reviewed_by=None,
                reviewed_at=None,
                created_at=application.updated_at,
                updated_at=application.updated_at,
            )
        ] + [_with_application_id(CandidateAssessmentRead, item, application_id, person_id) for item in assessments]
    else:
        assessments = [_with_application_id(CandidateAssessmentRead, item, application_id, person_id) for item in assessments]
    assignments = [
        _with_application_id(CandidateAssignmentRead, item, application_id, person_id)
        for item in assignment_repo.by_application(application.id, limit=20, offset=0)
    ]
    resume_artifacts = [
        _with_application_id(ResumeArtifactRead, item, application_id, person_id)
        for item in resume_repo.by_application(application_id, limit=20, offset=0)
    ]
    scorecards = [
        _with_application_id(CandidateScorecardRead, item, application_id, person_id)
        for item in scorecard_repo.by_application(application.id, limit=50, offset=0)
    ]
    review_decisions = [
        _with_application_id(CandidateReviewDecisionRead, item, application_id, person_id)
        for item in review_repo.by_application(application.id, limit=50, offset=0)
    ]
    sync_records = [
        _with_application_id(TalentPoolSyncRecordRead, item, application_id, person_id)
        for item in sync_repo.by_application(application.id, limit=20, offset=0)
    ]
    return CandidateThreadRead(
        application_id=application_id,
        person_id=person_id,
        job_description_id=application.job_description_id or job_description_id_for_candidate(candidate),
        candidate=_candidate_read_for_application(candidate, application),
        session_status=candidate_session.status if candidate_session is not None else "active",
        context_summary=candidate_session.context_summary if candidate_session is not None else None,
        facts=dict(candidate_session.facts or {}) if candidate_session is not None else {},
        recent_messages=list(candidate_session.recent_messages or []) if candidate_session is not None else [],
        communication_logs=[
            CandidateConversationEntryRead(
                id=item.id,
                application_id=application_id,
                direction=item.direction,
                content=item.content,
                message_type=item.message_type,
                platform=item.platform,
                metadata=dict(item.message_metadata or {}),
                timestamp=item.timestamp,
            )
            for item in logs
        ],
        state_snapshot=_candidate_state_snapshot(application),
        status_transitions=status_transitions,
        assessments=assessments,
        assignments=assignments,
        resume_artifacts=resume_artifacts,
        scorecards=scorecards,
        review_decisions=review_decisions,
        sync_records=sync_records,
        available_statuses=available_state_statuses(session),
        runtime_approvals=_runtime_approvals_for_application(session, application.id, person_id),
        runtime_interactions=_runtime_interactions_for_application(session, application.id, person_id),
    )


def build_application_thread(session: Session, application_id: str) -> CandidateThreadRead:
    application, candidate = _get_candidate_for_application_or_404(session, application_id)
    return _build_candidate_thread(session, application, candidate)


def list_application_entries(session: Session, application_id: str) -> list[CandidateConversationEntryRead]:
    application, _candidate = _get_candidate_for_application_or_404(session, application_id)
    logs = ApplicationCommunicationLogRepository(session).by_application(application.id, limit=200, offset=0)
    resolved_application_id = application.id
    return [
        CandidateConversationEntryRead(
            id=item.id,
            application_id=resolved_application_id,
            direction=item.direction,
            content=item.content,
            message_type=item.message_type,
            platform=item.platform,
            metadata=dict(item.message_metadata or {}),
            timestamp=item.timestamp,
        )
        for item in logs
    ]


def create_application_entry(
    session: Session,
    application_id: str,
    payload: CandidateConversationEntryCreate,
) -> CandidateConversationEntryRead:
    application, _candidate = _get_candidate_for_application_or_404(session, application_id)
    resolved_application_id = application.id
    timestamp = payload.timestamp or _now()
    entry = ApplicationCommunicationLogRepository(session).create(
        {
            "application_id": application.id,
            "direction": payload.direction,
            "content": payload.content,
            "message_type": payload.message_type,
            "platform": payload.platform,
            "message_metadata": payload.metadata,
            "timestamp": timestamp,
        }
    )
    candidate_session = ApplicationSessionRepository(session).get_or_create(
        application.id,
        defaults={"status": "active", "facts": {}, "recent_messages": []},
    )
    ApplicationSessionRepository(session).append_recent_message(
        candidate_session,
        direction=payload.direction,
        content=payload.content,
        message_type=payload.message_type,
        metadata={"source": "recruit_agent_thread", **dict(payload.metadata or {})},
    )
    return CandidateConversationEntryRead(
        id=entry.id,
        application_id=resolved_application_id,
        direction=entry.direction,
        content=entry.content,
        message_type=entry.message_type,
        platform=entry.platform,
        metadata=dict(entry.message_metadata or {}),
        timestamp=entry.timestamp,
    )


def list_application_status_transitions(session: Session, application_id: str) -> list[CandidateStatusTransitionRead]:
    application, _candidate = _get_candidate_for_application_or_404(session, application_id)
    resolved_application_id = application.id
    items = ApplicationStatusTransitionRepository(session).by_application(application.id, limit=500, offset=0)
    return [_with_application_id(CandidateStatusTransitionRead, item, resolved_application_id, application.person_id) for item in items]


def create_application_status_transition(
    session: Session,
    application_id: str,
    payload: CandidateStateTransitionRequest,
) -> CandidateThreadRead:
    application, candidate = _get_candidate_for_application_or_404(session, application_id)
    try:
        transition_candidate(session, candidate=candidate, application=application, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    refreshed_application, refreshed_candidate = _get_candidate_for_application_or_404(session, application.id)
    return _build_candidate_thread(session, refreshed_application, refreshed_candidate)


def _next_recommended_stages(status: str) -> list[str]:
    mapping = {
        "discovered": ["profile_reviewed"],
        "profile_reviewed": ["screening_passed", "screening_rejected"],
        "screening_passed": ["contact_required", "contact_acquired"],
        "contact_required": ["contact_acquired"],
        "contact_acquired": ["pending_communication"],
        "pending_communication": ["waiting_reply", "resume_requested"],
        "waiting_reply": ["resume_requested", "rejected"],
        "resume_requested": ["resume_received", "cooldown"],
        "resume_received": ["ai_assessment_completed"],
        "ai_assessment_completed": ["human_assessment_pending"],
        "human_assessment_pending": ["human_assessment_completed"],
        "human_assessment_completed": ["waiting_schedule_round_1", "rejected"],
        "waiting_schedule_round_1": ["interview_round_1_scheduled", "rejected"],
        "interview_round_1_scheduled": ["waiting_schedule_round_2", "offer_review", "rejected"],
        "waiting_schedule_round_2": ["interview_round_2_scheduled", "rejected"],
        "interview_round_2_scheduled": ["waiting_schedule_final", "offer_review", "rejected"],
        "waiting_schedule_final": ["interview_final_scheduled", "rejected"],
        "interview_final_scheduled": ["offer_review", "passed_to_talent_pool", "rejected"],
        "offer_review": ["passed_to_talent_pool", "rejected", "cooldown"],
        "rejected": ["waiting_schedule_round_2", "offer_review", "cooldown"],
        "cooldown": ["pending_communication"],
    }
    return mapping.get(status, [])


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
    if isinstance(patch.get("prompt_config"), dict):
        prompt_config = dict(profile.prompt_config or {})
        prompt_config.update(dict(patch["prompt_config"] or {}))
        prompt_config["context_policy"] = resolve_context_policy(prompt_config)
        patch["prompt_config"] = prompt_config
    if payload.is_primary:
        for item in repo.list(limit=500, offset=0):
            if item.id != profile.id and item.is_primary:
                repo.update(item, {"is_primary": False})
    updated = repo.update(profile, patch)
    return RecruitAgentProfileRead.model_validate(updated)


@router.get("/candidate-memories", response_model=list[CandidateMemoryRead])
def list_candidate_memories(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[CandidateMemoryRead]:
    profile = ensure_primary_recruit_agent_profile(session)
    candidate_repo = CandidateRepository(session)
    for candidate in candidate_repo.list(limit=5000, offset=0):
        ensure_candidate_memory(session, agent_profile_id=profile.id, candidate_id=candidate.id)
    items = CandidateMemoryRepository(session).list_for_agent(profile.id, limit=limit, offset=offset)
    return [CandidateMemoryRead.model_validate(item) for item in items]


@router.get("/candidate-memories/{candidate_id}", response_model=CandidateMemoryRead)
def get_candidate_memory(candidate_id: str, session: Session = Depends(get_session)) -> CandidateMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    candidate = _get_candidate_or_404(session, candidate_id)
    item = ensure_candidate_memory(session, agent_profile_id=profile.id, candidate_id=candidate.id)
    return CandidateMemoryRead.model_validate(item)


@router.patch("/candidate-memories/{candidate_id}", response_model=CandidateMemoryRead)
def update_candidate_memory(
    candidate_id: str,
    payload: CandidateMemoryUpdate,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> CandidateMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    candidate = _get_candidate_or_404(session, candidate_id)
    repo = CandidateMemoryRepository(session)
    item = ensure_candidate_memory(session, agent_profile_id=profile.id, candidate_id=candidate.id)
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
        (((profile.memory_policy or {}).get("candidate_memory") or {}).get("compact_threshold") or AUTO_COMPACT_THRESHOLD)
    )
    auto_compact = bool((((profile.memory_policy or {}).get("candidate_memory") or {}).get("auto_compact") or False))
    if auto_compact and needs_compaction(dict(updated.content or {}), threshold=threshold):
        apply_memory_compaction(
            updated,
            providers=container.providers,
            scope=f"candidate:{candidate.id}",
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
    return CandidateMemoryRead.model_validate(updated)


@router.post("/candidate-memories/{candidate_id}/compact", response_model=CandidateMemoryRead)
def compact_candidate_memory(
    candidate_id: str,
    payload: MemoryCompactRequest,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> CandidateMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    candidate = _get_candidate_or_404(session, candidate_id)
    repo = CandidateMemoryRepository(session)
    item = ensure_candidate_memory(session, agent_profile_id=profile.id, candidate_id=candidate.id)
    if not payload.force and not needs_compaction(dict(item.content or {})):
        return CandidateMemoryRead.model_validate(item)
    apply_memory_compaction(
        item,
        providers=container.providers,
        scope=f"candidate:{candidate.id}",
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
    return CandidateMemoryRead.model_validate(updated)


@router.get("/job-memories", response_model=list[JobMemoryRead])
def list_job_memories(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[JobMemoryRead]:
    profile = ensure_primary_recruit_agent_profile(session)
    candidate_repo = CandidateRepository(session)
    jd_ids = sorted(
        {
            str(candidate.job_description_id)
            for candidate in candidate_repo.list(limit=5000, offset=0)
            if candidate.job_description_id
        }
    )
    for jd_id in jd_ids:
        ensure_job_memory(session, agent_profile_id=profile.id, jd_id=jd_id)
    items = JobMemoryRepository(session).list_for_agent(profile.id, limit=limit, offset=offset)
    return [JobMemoryRead.model_validate(item) for item in items]


@router.get("/job-memories/{jd_id}", response_model=JobMemoryRead)
def get_job_memory(jd_id: str, session: Session = Depends(get_session)) -> JobMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    item = ensure_job_memory(session, agent_profile_id=profile.id, jd_id=jd_id)
    return JobMemoryRead.model_validate(item)


@router.patch("/job-memories/{jd_id}", response_model=JobMemoryRead)
def update_job_memory(
    jd_id: str,
    payload: JobMemoryUpdate,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> JobMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    repo = JobMemoryRepository(session)
    item = ensure_job_memory(session, agent_profile_id=profile.id, jd_id=jd_id)
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
    threshold = int((((profile.memory_policy or {}).get("job_memory") or {}).get("compact_threshold") or AUTO_COMPACT_THRESHOLD))
    auto_compact = bool((((profile.memory_policy or {}).get("job_memory") or {}).get("auto_compact") or False))
    if auto_compact and needs_compaction(dict(updated.content or {}), threshold=threshold):
        apply_memory_compaction(
            updated,
            providers=container.providers,
            scope=f"job:{jd_id}",
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
    return JobMemoryRead.model_validate(updated)


@router.post("/job-memories/{jd_id}/compact", response_model=JobMemoryRead)
def compact_job_memory(
    jd_id: str,
    payload: MemoryCompactRequest,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> JobMemoryRead:
    profile = ensure_primary_recruit_agent_profile(session)
    repo = JobMemoryRepository(session)
    item = ensure_job_memory(session, agent_profile_id=profile.id, jd_id=jd_id)
    if not payload.force and not needs_compaction(dict(item.content or {})):
        return JobMemoryRead.model_validate(item)
    apply_memory_compaction(
        item,
        providers=container.providers,
        scope=f"job:{jd_id}",
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
    return JobMemoryRead.model_validate(updated)


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
            providers=container.providers,
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
        providers=container.providers,
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


def list_candidate_threads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[CandidateThreadRead]:
    applications = CandidateApplicationRepository(session).list(limit=limit, offset=offset)
    threads: list[CandidateThreadRead] = []
    candidate_repo = CandidateRepository(session)
    for application in applications:
        candidate = candidate_repo.resolve(application.person_id)
        if candidate is None:
            continue
        threads.append(_build_candidate_thread(session, application, candidate))
    return threads


def get_candidate_thread(candidate_id: str, session: Session = Depends(get_session)) -> CandidateThreadRead:
    return build_application_thread(session, candidate_id)


def create_candidate_thread_entry(
    candidate_id: str,
    payload: CandidateConversationEntryCreate,
    session: Session = Depends(get_session),
) -> CandidateConversationEntryRead:
    return create_application_entry(session, candidate_id, payload)


def transition_candidate_state(
    candidate_id: str,
    payload: CandidateStateTransitionRequest,
    session: Session = Depends(get_session),
) -> CandidateThreadRead:
    return create_application_status_transition(session, candidate_id, payload)

def list_candidate_status_transitions(candidate_id: str, session: Session = Depends(get_session)) -> list[CandidateStatusTransitionRead]:
    return list_application_status_transitions(session, candidate_id)


def list_candidate_assignments(candidate_id: str, session: Session = Depends(get_session)) -> list[CandidateAssignmentRead]:
    application, _candidate = _get_candidate_for_application_or_404(session, candidate_id)
    items = ApplicationAssignmentRepository(session).by_application(application.id, limit=100, offset=0)
    return [_with_application_id(CandidateAssignmentRead, item, application.id, application.person_id) for item in items]


def create_candidate_assignment(
    candidate_id: str,
    payload: CandidateAssignmentCreate,
    session: Session = Depends(get_session),
) -> CandidateAssignmentRead:
    application, _candidate = _get_candidate_for_application_or_404(session, candidate_id)
    assignment_payload = payload.model_dump(exclude_unset=True)
    assignment_payload.pop("candidate_id", None)
    assignment_payload.pop("person_id", None)
    assignment_payload.pop("application_id", None)
    item = ApplicationAssignmentRepository(session).create(
        {
            **assignment_payload,
            "application_id": application.id,
            "assigned_at": payload.assigned_at or _now(),
        }
    )
    return _with_application_id(CandidateAssignmentRead, item, application.id, application.person_id)


def list_resume_artifacts(candidate_id: str, session: Session = Depends(get_session)) -> list[ResumeArtifactRead]:
    application, candidate = _get_candidate_for_application_or_404(session, candidate_id)
    items = ResumeArtifactRepository(session).by_application(application.id, limit=100, offset=0)
    return [_with_application_id(ResumeArtifactRead, item, application.id, candidate.id) for item in items]


def create_resume_artifact(
    candidate_id: str,
    payload: ResumeArtifactCreate,
    session: Session = Depends(get_session),
) -> ResumeArtifactRead:
    application, candidate = _get_candidate_for_application_or_404(session, candidate_id)
    linked_candidate = relink_application_person_by_contact_info(
        session,
        application=application,
        current_candidate=candidate,
        contact_info=payload.contact_snapshot,
    )
    artifact_payload = payload.model_dump(exclude_unset=True)
    artifact_payload.pop("person_id", None)
    artifact_payload.pop("application_id", None)
    item = ResumeArtifactRepository(session).create(
        {
            **artifact_payload,
            "application_id": application.id,
            "captured_at": payload.captured_at or _now(),
        }
    )
    snapshot = dict(application.state_snapshot or {}) or default_candidate_state_snapshot(status=application.current_status)
    if payload.artifact_type == "resume":
        snapshot["resume_status"] = "received"
        snapshot["latest_note"] = payload.file_name or snapshot.get("latest_note")
        CandidateApplicationRepository(session).update(
            application,
            {
                "state_snapshot": snapshot,
                "current_stage_key": application.current_stage_key or application.current_status,
            },
        )
    return _with_application_id(ResumeArtifactRead, item, application.id, linked_candidate.id)


def create_candidate_assessment(
    candidate_id: str,
    payload: CandidateAssessmentCreate,
    session: Session = Depends(get_session),
) -> CandidateAssessmentRead:
    application, _candidate = _get_candidate_for_application_or_404(session, candidate_id)
    assessment_payload = payload.model_dump(exclude_unset=True)
    assessment_payload.pop("candidate_id", None)
    assessment_payload.pop("person_id", None)
    assessment_metadata = assessment_payload.pop("metadata", {})
    item = ApplicationAssessmentRepository(session).create(
        {
            **assessment_payload,
            "application_id": application.id,
            "assessment_metadata": assessment_metadata,
        }
    )
    scorecard = ApplicationScorecardRepository(session).create(
        {
            "application_id": application.id,
            "stage_key": payload.stage_key,
            "source": payload.assessment_type,
            "rubric_version": str(assessment_metadata.get("rubric_version") or "recruit-scorecard-v1"),
            "score_total": payload.score,
            "verdict": payload.decision,
            "summary": payload.summary,
            "dimension_scores": dict(assessment_metadata.get("dimension_scores") or {}),
            "evidence_refs": list(payload.evidence_refs or []),
            "scorecard_metadata": {
                **assessment_metadata,
                "assessment_id": item.id,
            },
        }
    )
    if payload.assessment_type in {"manual", "human"} or payload.decision:
        ApplicationReviewDecisionRepository(session).create(
            {
                "application_id": application.id,
                "stage_key": payload.stage_key,
                "decision": payload.decision or "review",
                "rationale": payload.summary,
                "decision_source": payload.assessment_type,
                "decided_by": payload.created_by,
                "scorecard_id": scorecard.id,
                "review_metadata": {"assessment_id": item.id, **assessment_metadata},
                "decided_at": payload.reviewed_at or _now(),
            }
        )
    snapshot = dict(application.state_snapshot or {}) or default_candidate_state_snapshot(status=application.current_status)
    if payload.assessment_type == "ai":
        snapshot["ai_assessment_status"] = payload.status
    if payload.assessment_type == "manual":
        snapshot["human_assessment_status"] = payload.status
    snapshot["latest_note"] = payload.summary or snapshot.get("latest_note")
    CandidateApplicationRepository(session).update(application, {"state_snapshot": snapshot})
    return _with_application_id(CandidateAssessmentRead, item, application.id, application.person_id)


def list_candidate_scorecards(candidate_id: str, session: Session = Depends(get_session)) -> list[CandidateScorecardRead]:
    application, _candidate = _get_candidate_for_application_or_404(session, candidate_id)
    items = ApplicationScorecardRepository(session).by_application(application.id, limit=100, offset=0)
    return [_with_application_id(CandidateScorecardRead, item, application.id, application.person_id) for item in items]


def create_candidate_scorecard(
    candidate_id: str,
    payload: CandidateScorecardCreate,
    session: Session = Depends(get_session),
) -> CandidateScorecardRead:
    application, _candidate = _get_candidate_for_application_or_404(session, candidate_id)
    scorecard_payload = payload.model_dump(exclude_unset=True)
    scorecard_payload.pop("candidate_id", None)
    scorecard_payload.pop("person_id", None)
    scorecard_payload.pop("application_id", None)
    item = ApplicationScorecardRepository(session).create(
        {
            **scorecard_payload,
            "application_id": application.id,
        }
    )
    return _with_application_id(CandidateScorecardRead, item, application.id, application.person_id)


def list_candidate_review_decisions(candidate_id: str, session: Session = Depends(get_session)) -> list[CandidateReviewDecisionRead]:
    application, _candidate = _get_candidate_for_application_or_404(session, candidate_id)
    items = ApplicationReviewDecisionRepository(session).by_application(application.id, limit=100, offset=0)
    return [_with_application_id(CandidateReviewDecisionRead, item, application.id, application.person_id) for item in items]


def create_candidate_review_decision(
    candidate_id: str,
    payload: CandidateReviewDecisionCreate,
    session: Session = Depends(get_session),
) -> CandidateReviewDecisionRead:
    application, _candidate = _get_candidate_for_application_or_404(session, candidate_id)
    review_payload = payload.model_dump(exclude_unset=True)
    review_payload.pop("candidate_id", None)
    review_payload.pop("person_id", None)
    review_payload.pop("application_id", None)
    item = ApplicationReviewDecisionRepository(session).create(
        {
            **review_payload,
            "application_id": application.id,
            "decided_at": payload.decided_at or _now(),
        }
    )
    return _with_application_id(CandidateReviewDecisionRead, item, application.id, application.person_id)


def list_candidate_sync_records(candidate_id: str, session: Session = Depends(get_session)) -> list[TalentPoolSyncRecordRead]:
    application, _candidate = _get_candidate_for_application_or_404(session, candidate_id)
    items = ApplicationSyncRecordRepository(session).by_application(application.id, limit=100, offset=0)
    return [_with_application_id(TalentPoolSyncRecordRead, item, application.id, application.person_id) for item in items]


def create_candidate_sync_record(
    candidate_id: str,
    payload: TalentPoolSyncRecordCreate,
    session: Session = Depends(get_session),
) -> TalentPoolSyncRecordRead:
    application, _candidate = _get_candidate_for_application_or_404(session, candidate_id)
    sync_payload = payload.model_dump(exclude_unset=True)
    sync_payload.pop("candidate_id", None)
    sync_payload.pop("person_id", None)
    sync_payload.pop("application_id", None)
    item = ApplicationSyncRecordRepository(session).create(
        {
            **sync_payload,
            "application_id": application.id,
        }
    )
    return _with_application_id(TalentPoolSyncRecordRead, item, application.id, application.person_id)


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
    container.agent_control.enqueue_task(
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


@router.get("/runtime/session", response_model=RuntimeSessionRead)
def get_runtime_session(session: Session = Depends(get_session)) -> RuntimeSessionRead:
    item = _ensure_runtime_session(session)
    return RuntimeSessionRead.model_validate(item)


@router.get("/runtime/runs", response_model=list[RuntimeControlledRunRead])
def list_runtime_runs(
    status: str | None = Query(default=None),
    lane: str | None = Query(default=None),
    candidate_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[RuntimeControlledRunRead]:
    session_record = _ensure_runtime_session(session)
    resolved_candidate_id = _runtime_person_filter_id(session, candidate_id)
    items = AgentRunRepository(session).list_filtered(
        session_id=session_record.id,
        status=status,
        lane=lane,
        candidate_id=resolved_candidate_id,
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
    items = AgentRuntimeEventRepository(session).recent(
        session_id=session_record.id,
        run_id=run_id,
        limit=limit,
        offset=offset,
    )
    return [RuntimeEventRead.model_validate(item) for item in items]


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
    candidate_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExecutionGraphProjectionRead]:
    resolved_candidate_id = _runtime_person_filter_id(session, candidate_id)
    items = ExecutionGraphProjectionRepository(session).list_recent(
        goal_spec_id=goal_id,
        candidate_id=resolved_candidate_id,
        limit=limit,
        offset=offset,
    )
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
    candidate_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[OperatorInteractionRead]:
    session_record = _ensure_runtime_session(session)
    resolved_candidate_id = _runtime_person_filter_id(session, candidate_id)
    items = OperatorInteractionRepository(session).list_recent(
        session_id=session_record.id,
        candidate_id=resolved_candidate_id,
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
            updated_approval = container.agent_control.apply_approval_resolution(
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
            updated_approval = container.agent_control.apply_approval_resolution(
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
                flags=container.flags,
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
