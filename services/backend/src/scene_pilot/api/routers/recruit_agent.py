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
    CandidateAssignmentRepository,
    CandidateMemoryRepository,
    CandidateRepository,
    CandidateReviewDecisionRepository,
    CandidateScorecardRepository,
    CandidateSessionRepository,
    CandidateStageEventRepository,
    CommunicationLogRepository,
    EvolutionArtifactRepository,
    JobMemoryRepository,
    RecruitAgentProfileRepository,
    ResumeArtifactRepository,
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
    CandidateStageEventRead,
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
from scene_pilot.services.events import EventStreamService
from scene_pilot.services.recruit_agent import (
    AUTO_COMPACT_THRESHOLD,
    apply_memory_compaction,
    content_length,
    DEFAULT_CANDIDATE_STATUSES,
    default_candidate_state_snapshot,
    ensure_candidate_memory,
    ensure_global_memory,
    ensure_job_memory,
    ensure_primary_recruit_agent_profile,
    needs_compaction,
    resolve_context_policy,
    validate_evolution_artifact,
)

router = APIRouter(prefix="/api/recruit-agent", tags=["recruit-agent"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_candidate_or_404(session: Session, candidate_id: str):
    item = CandidateRepository(session).resolve(candidate_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return item


def _runtime_approvals_for_candidate(session: Session, candidate_id: str) -> list[ApprovalRead]:
    items = []
    for approval in ApprovalRepository(session).list(limit=500, offset=0):
        payload = dict(approval.payload or {})
        if approval.target_id == candidate_id:
            items.append(approval)
            continue
        if str(payload.get("candidate_id") or "") == candidate_id:
            items.append(approval)
            continue
        blocked = payload.get("blocked_task") if isinstance(payload.get("blocked_task"), dict) else {}
        if str(blocked.get("candidate_id") or "") == candidate_id:
            items.append(approval)
    return [ApprovalRead.model_validate(item) for item in items]


def _runtime_interactions_for_candidate(session: Session, candidate_id: str) -> list[OperatorInteractionRead]:
    items = OperatorInteractionRepository(session).list_recent(candidate_id=candidate_id, limit=100, offset=0)
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
    payload = dict(candidate.state_snapshot or {})
    if not payload:
        payload = default_candidate_state_snapshot(status=candidate.status)
    if payload.get("current_stage_key") in {None, ""}:
        payload["current_stage_key"] = candidate.status
    if payload.get("current_stage_label") in {None, ""}:
        payload["current_stage_label"] = str(payload["current_stage_key"]).replace("_", " ")
    if payload.get("contact_channels") is None:
        payload["contact_channels"] = []
    if payload.get("interview_plan") is None:
        payload["interview_plan"] = default_candidate_state_snapshot(status=candidate.status)["interview_plan"]
    return CandidateStateSnapshotRead.model_validate(payload)


def _build_candidate_thread(session: Session, candidate) -> CandidateThreadRead:
    session_repo = CandidateSessionRepository(session)
    logs_repo = CommunicationLogRepository(session)
    stage_repo = CandidateStageEventRepository(session)
    assessment_repo = CandidateAssessmentRepository(session)
    assignment_repo = CandidateAssignmentRepository(session)
    resume_repo = ResumeArtifactRepository(session)
    scorecard_repo = CandidateScorecardRepository(session)
    review_repo = CandidateReviewDecisionRepository(session)
    sync_repo = TalentPoolSyncRecordRepository(session)
    candidate_session = session_repo.by_candidate_id(candidate.id)
    logs = logs_repo.by_candidate(candidate.id, limit=200, offset=0)
    stage_events = stage_repo.by_candidate(candidate.id, limit=200, offset=0)
    if not stage_events:
        stage_events = [
            CandidateStageEventRead(
                id=f"synthetic-stage-{candidate.id}",
                candidate_id=candidate.id,
                event_type="stage_snapshot",
                from_status=None,
                to_status=candidate.status,
                phase_key=_candidate_state_snapshot(candidate).current_phase_key,
                phase_label=_candidate_state_snapshot(candidate).current_phase_label,
                stage_key=candidate.current_stage_key or candidate.status,
                stage_label=_candidate_state_snapshot(candidate).current_stage_label,
                actor="agent",
                source="synthetic",
                note="首次候选人状态快照。",
                payload={},
                occurred_at=candidate.updated_at,
                created_at=candidate.updated_at,
                updated_at=candidate.updated_at,
            )
        ]
    assessments = assessment_repo.by_candidate(candidate.id, limit=50, offset=0)
    if candidate.ai_scores and not any(item.assessment_type == "ai" for item in assessments):
        assessments = [
            CandidateAssessmentRead(
                id=f"synthetic-ai-{candidate.id}",
                candidate_id=candidate.id,
                assessment_type="ai",
                stage_key=candidate.current_stage_key or candidate.status,
                status="completed",
                decision=str((candidate.ai_scores or {}).get("decision") or "pending"),
                score=int((candidate.ai_scores or {}).get("overall") or 0),
                summary=candidate.ai_reasoning or "AI 评估已生成。",
                evidence_refs=list((candidate.ai_scores or {}).get("evidence_refs") or []),
                metadata={"source": "candidate.ai_scores", "synthetic": True},
                created_by="agent",
                reviewed_by=None,
                reviewed_at=None,
                created_at=candidate.updated_at,
                updated_at=candidate.updated_at,
            )
        ] + [CandidateAssessmentRead.model_validate(item) for item in assessments]
    else:
        assessments = [CandidateAssessmentRead.model_validate(item) for item in assessments]
    assignments = [CandidateAssignmentRead.model_validate(item) for item in assignment_repo.by_candidate(candidate.id, limit=20, offset=0)]
    resume_artifacts = [ResumeArtifactRead.model_validate(item) for item in resume_repo.by_candidate(candidate.id, limit=20, offset=0)]
    scorecards = [CandidateScorecardRead.model_validate(item) for item in scorecard_repo.by_candidate(candidate.id, limit=50, offset=0)]
    review_decisions = [
        CandidateReviewDecisionRead.model_validate(item)
        for item in review_repo.by_candidate(candidate.id, limit=50, offset=0)
    ]
    sync_records = [TalentPoolSyncRecordRead.model_validate(item) for item in sync_repo.by_candidate(candidate.id, limit=20, offset=0)]
    return CandidateThreadRead(
        candidate=CandidateRead.model_validate(candidate),
        session_status=candidate_session.status if candidate_session is not None else "active",
        context_summary=candidate_session.context_summary if candidate_session is not None else None,
        facts=dict(candidate_session.facts or {}) if candidate_session is not None else {},
        recent_messages=list(candidate_session.recent_messages or []) if candidate_session is not None else [],
        communication_logs=[
            CandidateConversationEntryRead(
                id=item.id,
                direction=item.direction,
                content=item.content,
                message_type=item.message_type,
                platform=item.platform,
                metadata=dict(item.message_metadata or {}),
                timestamp=item.timestamp,
            )
            for item in logs
        ],
        state_snapshot=_candidate_state_snapshot(candidate),
        stage_events=[item if isinstance(item, CandidateStageEventRead) else CandidateStageEventRead.model_validate(item) for item in stage_events],
        assessments=assessments,
        assignments=assignments,
        resume_artifacts=resume_artifacts,
        scorecards=scorecards,
        review_decisions=review_decisions,
        sync_records=sync_records,
        available_statuses=DEFAULT_CANDIDATE_STATUSES,
        runtime_approvals=_runtime_approvals_for_candidate(session, candidate.id),
        runtime_interactions=_runtime_interactions_for_candidate(session, candidate.id),
    )


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


def _apply_transition_snapshot(
    candidate,
    payload: CandidateStateTransitionRequest,
) -> dict[str, Any]:
    snapshot = dict(candidate.state_snapshot or {}) or default_candidate_state_snapshot(status=candidate.status)
    snapshot["current_stage_key"] = payload.stage_key or payload.to_status
    snapshot["current_stage_label"] = payload.stage_label or str(snapshot["current_stage_key"]).replace("_", " ")
    if payload.phase_key is not None:
        snapshot["current_phase_key"] = payload.phase_key
    if payload.phase_label is not None:
        snapshot["current_phase_label"] = payload.phase_label
    if payload.contact_channels is not None:
        unique_channels = [item for item in dict.fromkeys(payload.contact_channels) if item]
        snapshot["contact_channels"] = unique_channels
        snapshot["contact_acquired"] = bool(unique_channels)
        snapshot["contact_status"] = "acquired" if unique_channels else "missing"
    if payload.to_status == "contact_acquired" and not snapshot.get("contact_channels"):
        contact_info = dict(candidate.contact_info or {})
        channels = [key for key in ("phone", "mobile", "wechat") if contact_info.get(key)]
        snapshot["contact_channels"] = channels
        snapshot["contact_acquired"] = bool(channels)
        snapshot["contact_status"] = "acquired" if channels else "missing"
    if payload.to_status == "resume_requested":
        snapshot["resume_status"] = "requested"
    elif payload.to_status == "resume_received":
        snapshot["resume_status"] = "received"
    if payload.to_status == "ai_assessment_completed":
        snapshot["ai_assessment_status"] = "completed"
    if payload.to_status == "human_assessment_pending":
        snapshot["human_assessment_status"] = "pending"
    elif payload.to_status == "human_assessment_completed":
        snapshot["human_assessment_status"] = "completed"
    interview_plan = dict(snapshot.get("interview_plan") or default_candidate_state_snapshot()["interview_plan"])
    rounds = list(interview_plan.get("rounds") or [])
    if payload.interview_round is not None:
        interview_plan["active_round"] = payload.interview_round
        found = False
        for round_item in rounds:
            if int(round_item.get("round") or 0) == payload.interview_round:
                found = True
                if payload.to_status.startswith("waiting_schedule_"):
                    round_item["status"] = "waiting_schedule"
                elif payload.to_status.startswith("interview_"):
                    round_item["status"] = "scheduled"
                round_item["updated_at"] = _now().isoformat()
                if payload.note:
                    round_item["summary"] = payload.note
        if not found:
            rounds.append(
                {
                    "round": payload.interview_round,
                    "label": f"第 {payload.interview_round} 轮",
                    "status": "scheduled" if payload.to_status.startswith("interview_") else "waiting_schedule",
                    "updated_at": _now().isoformat(),
                    "summary": payload.note,
                }
            )
    interview_plan["rounds"] = rounds
    snapshot["interview_plan"] = interview_plan
    snapshot["latest_note"] = payload.note
    snapshot["latest_transition_at"] = _now().isoformat()
    snapshot["latest_transition_source"] = payload.source
    snapshot["next_recommended_stages"] = _next_recommended_stages(payload.to_status)
    snapshot.setdefault("snapshot_metadata", {})
    snapshot["snapshot_metadata"]["manual_override"] = payload.source == "operator"
    return snapshot


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
    jd_ids = sorted({str(candidate.jd_id) for candidate in candidate_repo.list(limit=5000, offset=0) if candidate.jd_id})
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


@router.get("/candidate-threads", response_model=list[CandidateThreadRead])
def list_candidate_threads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[CandidateThreadRead]:
    candidates = CandidateRepository(session).list(limit=limit, offset=offset)
    return [_build_candidate_thread(session, candidate) for candidate in candidates]


@router.get("/candidate-threads/{candidate_id}", response_model=CandidateThreadRead)
def get_candidate_thread(candidate_id: str, session: Session = Depends(get_session)) -> CandidateThreadRead:
    candidate = _get_candidate_or_404(session, candidate_id)
    return _build_candidate_thread(session, candidate)


@router.post("/candidate-threads/{candidate_id}/entries", response_model=CandidateConversationEntryRead, status_code=201)
def create_candidate_thread_entry(
    candidate_id: str,
    payload: CandidateConversationEntryCreate,
    session: Session = Depends(get_session),
) -> CandidateConversationEntryRead:
    candidate = _get_candidate_or_404(session, candidate_id)
    timestamp = payload.timestamp or _now()
    entry = CommunicationLogRepository(session).create(
        {
            "candidate_id": candidate.id,
            "direction": payload.direction,
            "content": payload.content,
            "message_type": payload.message_type,
            "platform": payload.platform,
            "message_metadata": payload.metadata,
            "timestamp": timestamp,
        }
    )
    candidate_session = CandidateSessionRepository(session).get_or_create(
        candidate.id,
        defaults={"status": "active", "facts": {}, "recent_messages": []},
    )
    CandidateSessionRepository(session).append_recent_message(
        candidate_session,
        direction=payload.direction,
        content=payload.content,
        message_type=payload.message_type,
        metadata={"source": "recruit_agent_thread", **dict(payload.metadata or {})},
    )
    return CandidateConversationEntryRead(
        id=entry.id,
        direction=entry.direction,
        content=entry.content,
        message_type=entry.message_type,
        platform=entry.platform,
        metadata=dict(entry.message_metadata or {}),
        timestamp=entry.timestamp,
    )


@router.post("/candidates/{candidate_id}/transition", response_model=CandidateThreadRead)
def transition_candidate_state(
    candidate_id: str,
    payload: CandidateStateTransitionRequest,
    session: Session = Depends(get_session),
) -> CandidateThreadRead:
    candidate_repo = CandidateRepository(session)
    candidate = _get_candidate_or_404(session, candidate_id)
    previous_status = candidate.status
    next_snapshot = _apply_transition_snapshot(candidate, payload)
    contact_info = dict(candidate.contact_info or {})
    if payload.contact_channels is not None:
        if "phone" in payload.contact_channels or "mobile" in payload.contact_channels:
            contact_info.setdefault("has_phone", True)
        if "wechat" in payload.contact_channels:
            contact_info.setdefault("has_wechat", True)
        candidate.contact_info = contact_info
    candidate.current_stage_key = payload.stage_key or payload.to_status
    candidate_repo.update_state_snapshot(candidate, status=payload.to_status, snapshot=next_snapshot)
    CandidateStageEventRepository(session).create(
        {
            "candidate_id": candidate.id,
            "event_type": "stage_transition",
            "from_status": previous_status,
            "to_status": payload.to_status,
            "phase_key": payload.phase_key,
            "phase_label": payload.phase_label,
            "stage_key": payload.stage_key or payload.to_status,
            "stage_label": payload.stage_label or str(payload.stage_key or payload.to_status).replace("_", " "),
            "actor": payload.actor,
            "source": payload.source,
            "note": payload.note,
            "payload": {
                **dict(payload.metadata or {}),
                "interview_round": payload.interview_round,
                "contact_channels": payload.contact_channels,
            },
            "occurred_at": _now(),
        }
    )
    refreshed = _get_candidate_or_404(session, candidate_id)
    return _build_candidate_thread(session, refreshed)


@router.get("/candidates/{candidate_id}/events", response_model=list[CandidateStageEventRead])
def list_candidate_stage_events(candidate_id: str, session: Session = Depends(get_session)) -> list[CandidateStageEventRead]:
    candidate = _get_candidate_or_404(session, candidate_id)
    items = CandidateStageEventRepository(session).by_candidate(candidate.id, limit=500, offset=0)
    return [CandidateStageEventRead.model_validate(item) for item in items]


@router.get("/candidates/{candidate_id}/assignments", response_model=list[CandidateAssignmentRead])
def list_candidate_assignments(candidate_id: str, session: Session = Depends(get_session)) -> list[CandidateAssignmentRead]:
    candidate = _get_candidate_or_404(session, candidate_id)
    items = CandidateAssignmentRepository(session).by_candidate(candidate.id, limit=100, offset=0)
    return [CandidateAssignmentRead.model_validate(item) for item in items]


@router.post("/candidates/{candidate_id}/assignments", response_model=CandidateAssignmentRead, status_code=201)
def create_candidate_assignment(
    candidate_id: str,
    payload: CandidateAssignmentCreate,
    session: Session = Depends(get_session),
) -> CandidateAssignmentRead:
    candidate = _get_candidate_or_404(session, candidate_id)
    item = CandidateAssignmentRepository(session).create(
        {
            **payload.model_dump(exclude_unset=True),
            "candidate_id": candidate.id,
            "assigned_at": payload.assigned_at or _now(),
        }
    )
    return CandidateAssignmentRead.model_validate(item)


@router.get("/candidates/{candidate_id}/resume-artifacts", response_model=list[ResumeArtifactRead])
def list_resume_artifacts(candidate_id: str, session: Session = Depends(get_session)) -> list[ResumeArtifactRead]:
    candidate = _get_candidate_or_404(session, candidate_id)
    items = ResumeArtifactRepository(session).by_candidate(candidate.id, limit=100, offset=0)
    return [ResumeArtifactRead.model_validate(item) for item in items]


@router.post("/candidates/{candidate_id}/resume-artifacts", response_model=ResumeArtifactRead, status_code=201)
def create_resume_artifact(
    candidate_id: str,
    payload: ResumeArtifactCreate,
    session: Session = Depends(get_session),
) -> ResumeArtifactRead:
    candidate = _get_candidate_or_404(session, candidate_id)
    item = ResumeArtifactRepository(session).create(
        {
            **payload.model_dump(exclude_unset=True),
            "candidate_id": candidate.id,
            "captured_at": payload.captured_at or _now(),
        }
    )
    snapshot = dict(candidate.state_snapshot or {}) or default_candidate_state_snapshot(status=candidate.status)
    if payload.artifact_type == "resume":
        snapshot["resume_status"] = "received"
        snapshot["latest_note"] = payload.file_name or snapshot.get("latest_note")
        CandidateRepository(session).update_state_snapshot(candidate, snapshot=snapshot)
    return ResumeArtifactRead.model_validate(item)


@router.post("/candidates/{candidate_id}/assessments", response_model=CandidateAssessmentRead, status_code=201)
def create_candidate_assessment(
    candidate_id: str,
    payload: CandidateAssessmentCreate,
    session: Session = Depends(get_session),
) -> CandidateAssessmentRead:
    candidate = _get_candidate_or_404(session, candidate_id)
    assessment_payload = payload.model_dump(exclude_unset=True)
    assessment_payload.pop("candidate_id", None)
    assessment_metadata = assessment_payload.pop("metadata", {})
    item = CandidateAssessmentRepository(session).create(
        {
            **assessment_payload,
            "candidate_id": candidate.id,
            "assessment_metadata": assessment_metadata,
        }
    )
    scorecard = CandidateScorecardRepository(session).create(
        {
            "candidate_id": candidate.id,
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
        CandidateReviewDecisionRepository(session).create(
            {
                "candidate_id": candidate.id,
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
    snapshot = dict(candidate.state_snapshot or {}) or default_candidate_state_snapshot(status=candidate.status)
    if payload.assessment_type == "ai":
        snapshot["ai_assessment_status"] = payload.status
    if payload.assessment_type == "manual":
        snapshot["human_assessment_status"] = payload.status
    snapshot["latest_note"] = payload.summary or snapshot.get("latest_note")
    CandidateRepository(session).update_state_snapshot(candidate, snapshot=snapshot)
    return CandidateAssessmentRead.model_validate(item)


@router.get("/candidates/{candidate_id}/scorecards", response_model=list[CandidateScorecardRead])
def list_candidate_scorecards(candidate_id: str, session: Session = Depends(get_session)) -> list[CandidateScorecardRead]:
    candidate = _get_candidate_or_404(session, candidate_id)
    items = CandidateScorecardRepository(session).by_candidate(candidate.id, limit=100, offset=0)
    return [CandidateScorecardRead.model_validate(item) for item in items]


@router.post("/candidates/{candidate_id}/scorecards", response_model=CandidateScorecardRead, status_code=201)
def create_candidate_scorecard(
    candidate_id: str,
    payload: CandidateScorecardCreate,
    session: Session = Depends(get_session),
) -> CandidateScorecardRead:
    candidate = _get_candidate_or_404(session, candidate_id)
    item = CandidateScorecardRepository(session).create(
        {
            **payload.model_dump(exclude_unset=True),
            "candidate_id": candidate.id,
        }
    )
    return CandidateScorecardRead.model_validate(item)


@router.get("/candidates/{candidate_id}/review-decisions", response_model=list[CandidateReviewDecisionRead])
def list_candidate_review_decisions(candidate_id: str, session: Session = Depends(get_session)) -> list[CandidateReviewDecisionRead]:
    candidate = _get_candidate_or_404(session, candidate_id)
    items = CandidateReviewDecisionRepository(session).by_candidate(candidate.id, limit=100, offset=0)
    return [CandidateReviewDecisionRead.model_validate(item) for item in items]


@router.post("/candidates/{candidate_id}/review-decisions", response_model=CandidateReviewDecisionRead, status_code=201)
def create_candidate_review_decision(
    candidate_id: str,
    payload: CandidateReviewDecisionCreate,
    session: Session = Depends(get_session),
) -> CandidateReviewDecisionRead:
    candidate = _get_candidate_or_404(session, candidate_id)
    item = CandidateReviewDecisionRepository(session).create(
        {
            **payload.model_dump(exclude_unset=True),
            "candidate_id": candidate.id,
            "decided_at": payload.decided_at or _now(),
        }
    )
    return CandidateReviewDecisionRead.model_validate(item)


@router.get("/candidates/{candidate_id}/sync-records", response_model=list[TalentPoolSyncRecordRead])
def list_candidate_sync_records(candidate_id: str, session: Session = Depends(get_session)) -> list[TalentPoolSyncRecordRead]:
    candidate = _get_candidate_or_404(session, candidate_id)
    items = TalentPoolSyncRecordRepository(session).by_candidate(candidate.id, limit=100, offset=0)
    return [TalentPoolSyncRecordRead.model_validate(item) for item in items]


@router.post("/candidates/{candidate_id}/sync-records", response_model=TalentPoolSyncRecordRead, status_code=201)
def create_candidate_sync_record(
    candidate_id: str,
    payload: TalentPoolSyncRecordCreate,
    session: Session = Depends(get_session),
) -> TalentPoolSyncRecordRead:
    candidate = _get_candidate_or_404(session, candidate_id)
    item = TalentPoolSyncRecordRepository(session).create(
        {
            **payload.model_dump(exclude_unset=True),
            "candidate_id": candidate.id,
        }
    )
    return TalentPoolSyncRecordRead.model_validate(item)


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
    items = AgentRunRepository(session).list_filtered(
        session_id=session_record.id,
        status=status,
        lane=lane,
        candidate_id=candidate_id,
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
    items = ExecutionGraphProjectionRepository(session).list_recent(
        goal_spec_id=goal_id,
        candidate_id=candidate_id,
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
    items = OperatorInteractionRepository(session).list_recent(
        session_id=session_record.id,
        candidate_id=candidate_id,
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
    updated = repo.update(item, payload)
    return EvolutionArtifactRead.model_validate(updated)
