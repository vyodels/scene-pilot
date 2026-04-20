from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from scene_pilot.repositories import (
    ApplicationAssessmentRepository,
    ApplicationAssignmentRepository,
    ApplicationCommunicationLogRepository,
    ApplicationReviewDecisionRepository,
    ApplicationScorecardRepository,
    ApplicationSessionRepository,
    ApplicationStatusTransitionRepository,
    ApplicationSyncRecordRepository,
    ApprovalRepository,
    CandidateApplicationRepository,
    CandidateRepository,
    JobDescriptionRepository,
    OperatorInteractionRepository,
    ResumeArtifactRepository,
)
from scene_pilot.schemas import (
    ApprovalRead,
    ApplicationSubjectRead,
    CandidateAssessmentCreate,
    CandidateAssessmentRead,
    CandidateAssignmentCreate,
    CandidateAssignmentRead,
    CandidateConversationEntryCreate,
    CandidateConversationEntryRead,
    CandidateReviewDecisionCreate,
    CandidateReviewDecisionRead,
    CandidateScorecardCreate,
    CandidateScorecardRead,
    CandidateStateSnapshotRead,
    CandidateStateTransitionRequest,
    CandidateStatusTransitionRead,
    CandidateThreadRead,
    OperatorInteractionRead,
    ResumeArtifactCreate,
    ResumeArtifactRead,
    TalentPoolSyncRecordCreate,
    TalentPoolSyncRecordRead,
)
from scene_pilot.services.application_subjects import application_payload_from_application
from scene_pilot.services.candidate_identity import merge_contact_info, relink_application_person_by_contact_info
from scene_pilot.services.recruit_agent import default_candidate_state_snapshot
from scene_pilot.services.state_machine import available_state_statuses, transition_candidate


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


def _get_application_with_person_or_404(session: Session, application_id: str):
    application = CandidateApplicationRepository(session).get(application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Candidate application not found")
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Candidate person not found")
    return application, person


def _with_application_id(model_cls, item, application_id: str, person_id: str | None = None):
    if hasattr(item, "model_dump"):
        payload = dict(item.model_dump(exclude_unset=True))
    elif hasattr(item, "__dict__"):
        payload = {key: value for key, value in vars(item).items() if not key.startswith("_")}
    else:
        payload = dict(item)
    payload["application_id"] = application_id
    if person_id is not None:
        payload["person_id"] = person_id
    return model_cls.model_validate(payload)


def _application_subject_read_for_application(person, application, job_description=None) -> ApplicationSubjectRead:
    return ApplicationSubjectRead.model_validate(
        application_payload_from_application(
            application,
            person=person,
            job_description=job_description,
        )
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
        blocked_value = payload.get("blocked_task")
        blocked: dict[str, Any] = blocked_value if isinstance(blocked_value, dict) else {}
        if str(blocked.get("application_id") or "") == application_id:
            items.append(approval)
            continue
        if str(blocked.get("candidate_id") or "") in {application_id, person_id}:
            items.append(approval)
    return [ApprovalRead.model_validate(item) for item in items]


def _runtime_interactions_for_application(
    session: Session,
    application_id: str,
    person_id: str | None = None,
) -> list[OperatorInteractionRead]:
    items = OperatorInteractionRepository(session).list_recent(candidate_id=application_id, limit=100, offset=0)
    if not items and person_id and person_id != application_id:
        items = OperatorInteractionRepository(session).list_recent(candidate_id=person_id, limit=100, offset=0)
    return [OperatorInteractionRead.model_validate(item) for item in items]


def _application_state_snapshot(application) -> CandidateStateSnapshotRead:
    current_status = application.current_status
    payload = dict(application.state_snapshot or {})
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
    payload["latest_transition_at"] = _timestamp(payload.get("latest_transition_at"))
    return CandidateStateSnapshotRead.model_validate(payload)


def _build_application_thread(session: Session, application, person) -> CandidateThreadRead:
    application_id = application.candidate_application_id
    person_id = person.candidate_person_id
    job_description = (
        JobDescriptionRepository(session).get_by_storage_id(application.job_description_id)
        if getattr(application, "job_description_id", None)
        else None
    )
    application_session = ApplicationSessionRepository(session).by_application_id(application_id)
    logs = ApplicationCommunicationLogRepository(session).by_application(application_id, limit=200, offset=0)
    status_transitions = [
        _with_application_id(CandidateStatusTransitionRead, item, application_id, person_id)
        for item in ApplicationStatusTransitionRepository(session).by_application(application_id, limit=200, offset=0)
    ]
    assessment_items = ApplicationAssessmentRepository(session).by_application(application_id, limit=50, offset=0)
    assessments: list[CandidateAssessmentRead]
    if application.ai_scores and not any(item.assessment_type == "ai" for item in assessment_items):
        assessments = [
            CandidateAssessmentRead(
                id=f"synthetic-ai-{application.id}",
                person_id=person_id,
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
        ] + [_with_application_id(CandidateAssessmentRead, item, application_id, person_id) for item in assessment_items]
    else:
        assessments = [_with_application_id(CandidateAssessmentRead, item, application_id, person_id) for item in assessment_items]
    assignments = [
        _with_application_id(CandidateAssignmentRead, item, application_id, person_id)
        for item in ApplicationAssignmentRepository(session).by_application(application_id, limit=20, offset=0)
    ]
    resume_artifacts = [
        _with_application_id(ResumeArtifactRead, item, application_id, person_id)
        for item in ResumeArtifactRepository(session).by_application(application_id, limit=20, offset=0)
    ]
    scorecards = [
        _with_application_id(CandidateScorecardRead, item, application_id, person_id)
        for item in ApplicationScorecardRepository(session).by_application(application_id, limit=50, offset=0)
    ]
    review_decisions = [
        _with_application_id(CandidateReviewDecisionRead, item, application_id, person_id)
        for item in ApplicationReviewDecisionRepository(session).by_application(application_id, limit=50, offset=0)
    ]
    sync_records = [
        _with_application_id(TalentPoolSyncRecordRead, item, application_id, person_id)
        for item in ApplicationSyncRecordRepository(session).by_application(application_id, limit=20, offset=0)
    ]
    return CandidateThreadRead(
        application_id=application_id,
        person_id=person_id,
        job_description_id=job_description.job_description_id if job_description is not None else None,
        application=_application_subject_read_for_application(person, application, job_description),
        session_status=application_session.status if application_session is not None else "active",
        context_summary=application_session.context_summary if application_session is not None else None,
        facts=dict(application_session.facts or {}) if application_session is not None else {},
        recent_messages=list(application_session.recent_messages or []) if application_session is not None else [],
        communication_logs=[
            CandidateConversationEntryRead(
                id=item.id,
                application_id=application_id,
                direction=item.direction,
                content=item.content,
                message_type=item.message_type,
                platform=item.platform,
                metadata=dict(item.message_metadata or {}),
                timestamp=_timestamp(item.timestamp),
            )
            for item in logs
        ],
        state_snapshot=_application_state_snapshot(application),
        status_transitions=status_transitions,
        assessments=assessments,
        assignments=assignments,
        resume_artifacts=resume_artifacts,
        scorecards=scorecards,
        review_decisions=review_decisions,
        sync_records=sync_records,
        available_statuses=available_state_statuses(session),
        runtime_approvals=_runtime_approvals_for_application(session, application.id, person.id),
        runtime_interactions=_runtime_interactions_for_application(session, application.id, person.id),
    )


def build_application_thread(session: Session, application_id: str) -> CandidateThreadRead:
    application, person = _get_application_with_person_or_404(session, application_id)
    return _build_application_thread(session, application, person)


def list_application_entries(session: Session, application_id: str) -> list[CandidateConversationEntryRead]:
    application, _person = _get_application_with_person_or_404(session, application_id)
    logs = ApplicationCommunicationLogRepository(session).by_application(application.candidate_application_id, limit=200, offset=0)
    return [
        CandidateConversationEntryRead(
            id=item.id,
            application_id=application.candidate_application_id,
            direction=item.direction,
            content=item.content,
            message_type=item.message_type,
            platform=item.platform,
            metadata=dict(item.message_metadata or {}),
            timestamp=_timestamp(item.timestamp),
        )
        for item in logs
    ]


def create_application_entry(
    session: Session,
    application_id: str,
    payload: CandidateConversationEntryCreate,
) -> CandidateConversationEntryRead:
    application, _person = _get_application_with_person_or_404(session, application_id)
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
    application_session = ApplicationSessionRepository(session).get_or_create(
        application.candidate_application_id,
        defaults={"status": "active", "facts": {}, "recent_messages": []},
    )
    ApplicationSessionRepository(session).append_recent_message(
        application_session,
        direction=payload.direction,
        content=payload.content,
        message_type=payload.message_type,
        metadata={"source": "recruit_agent_thread", **dict(payload.metadata or {})},
    )
    return CandidateConversationEntryRead(
        id=entry.id,
        application_id=application.candidate_application_id,
        direction=entry.direction,
        content=entry.content,
        message_type=entry.message_type,
        platform=entry.platform,
        metadata=dict(entry.message_metadata or {}),
        timestamp=_timestamp(entry.timestamp),
    )


def list_application_status_transitions(session: Session, application_id: str) -> list[CandidateStatusTransitionRead]:
    application, _person = _get_application_with_person_or_404(session, application_id)
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    person_id = person.candidate_person_id if person is not None else application.person_id
    items = ApplicationStatusTransitionRepository(session).by_application(application.candidate_application_id, limit=500, offset=0)
    return [_with_application_id(CandidateStatusTransitionRead, item, application.candidate_application_id, person_id) for item in items]


def create_application_status_transition(
    session: Session,
    application_id: str,
    payload: CandidateStateTransitionRequest,
) -> CandidateThreadRead:
    application, person = _get_application_with_person_or_404(session, application_id)
    try:
        transition_candidate(session, candidate=person, application=application, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    refreshed_application, refreshed_person = _get_application_with_person_or_404(session, application.candidate_application_id)
    return _build_application_thread(session, refreshed_application, refreshed_person)


def list_application_threads(
    limit: int,
    offset: int,
    session: Session,
) -> list[CandidateThreadRead]:
    applications = CandidateApplicationRepository(session).list(limit=limit, offset=offset)
    threads: list[CandidateThreadRead] = []
    candidate_repo = CandidateRepository(session)
    for application in applications:
        candidate = candidate_repo.get_by_storage_id(application.person_id)
        if candidate is None:
            continue
        threads.append(_build_application_thread(session, application, candidate))
    return threads


def list_application_assignments(application_id: str, session: Session) -> list[CandidateAssignmentRead]:
    application, person = _get_application_with_person_or_404(session, application_id)
    items = ApplicationAssignmentRepository(session).by_application(application.candidate_application_id, limit=100, offset=0)
    return [_with_application_id(CandidateAssignmentRead, item, application.candidate_application_id, person.candidate_person_id) for item in items]


def create_application_assignment(
    application_id: str,
    payload: CandidateAssignmentCreate,
    session: Session,
) -> CandidateAssignmentRead:
    application, _person = _get_application_with_person_or_404(session, application_id)
    assignment_payload = payload.model_dump(exclude_unset=True)
    assignment_payload.pop("person_id", None)
    assignment_payload.pop("application_id", None)
    item = ApplicationAssignmentRepository(session).create(
        {
            **assignment_payload,
            "application_id": application.id,
            "assigned_at": payload.assigned_at or _now(),
        }
    )
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    return _with_application_id(
        CandidateAssignmentRead,
        item,
        application.candidate_application_id,
        person.candidate_person_id if person is not None else application.person_id,
    )


def list_application_resume_artifacts(application_id: str, session: Session) -> list[ResumeArtifactRead]:
    application, person = _get_application_with_person_or_404(session, application_id)
    items = ResumeArtifactRepository(session).by_application(application.candidate_application_id, limit=100, offset=0)
    return [_with_application_id(ResumeArtifactRead, item, application.candidate_application_id, person.candidate_person_id) for item in items]


def create_application_resume_artifact(
    application_id: str,
    payload: ResumeArtifactCreate,
    session: Session,
) -> ResumeArtifactRead:
    application, person = _get_application_with_person_or_404(session, application_id)
    linked_person = relink_application_person_by_contact_info(
        session,
        application=application,
        current_candidate=person,
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
    application_metadata = dict(application.application_metadata or {})
    if payload.artifact_type == "resume":
        snapshot["resume_status"] = "received"
        snapshot["latest_note"] = payload.file_name or snapshot.get("latest_note")
        resume_snapshot = {
            **dict(application.resume_snapshot or {}),
            "available": True,
            "status": "received",
            "file_name": payload.file_name,
            "file_path": payload.file_path,
            "artifact_type": payload.artifact_type,
            "captured_at": _timestamp(payload.captured_at or item.captured_at),
            "source": payload.source,
        }
        application_metadata["resume_available"] = True
        application_metadata["resume_snapshot"] = resume_snapshot
        application_metadata["resume_status"] = "received"
        CandidateApplicationRepository(session).update(
            application,
            {
                "state_snapshot": snapshot,
                "current_stage_key": application.current_stage_key or application.current_status,
                "resume_snapshot": resume_snapshot,
                "contact_snapshot": dict(payload.contact_snapshot or application.contact_snapshot or {}),
                "application_metadata": application_metadata,
            },
        )
        CandidateRepository(session).update(
            linked_person,
            {
                "resume_path": payload.file_path or linked_person.resume_path,
                "online_resume_text": payload.extracted_text or linked_person.online_resume_text,
                "contact_info": merge_contact_info(
                    dict(linked_person.contact_info or {}),
                    dict(payload.contact_snapshot or {}),
                ),
            },
        )
    return _with_application_id(
        ResumeArtifactRead,
        item,
        application.candidate_application_id,
        linked_person.candidate_person_id,
    )


def create_application_assessment(
    application_id: str,
    payload: CandidateAssessmentCreate,
    session: Session,
) -> CandidateAssessmentRead:
    application, _person = _get_application_with_person_or_404(session, application_id)
    assessment_payload = payload.model_dump(exclude_unset=True)
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
            "scorecard_metadata": {**assessment_metadata, "assessment_id": item.id},
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
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    return _with_application_id(
        CandidateAssessmentRead,
        item,
        application.candidate_application_id,
        person.candidate_person_id if person is not None else application.person_id,
    )


def list_application_scorecards(application_id: str, session: Session) -> list[CandidateScorecardRead]:
    application, _person = _get_application_with_person_or_404(session, application_id)
    items = ApplicationScorecardRepository(session).by_application(application.candidate_application_id, limit=100, offset=0)
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    person_id = person.candidate_person_id if person is not None else application.person_id
    return [_with_application_id(CandidateScorecardRead, item, application.candidate_application_id, person_id) for item in items]


def create_application_scorecard(
    application_id: str,
    payload: CandidateScorecardCreate,
    session: Session,
) -> CandidateScorecardRead:
    application, _person = _get_application_with_person_or_404(session, application_id)
    scorecard_payload = payload.model_dump(exclude_unset=True)
    scorecard_payload.pop("person_id", None)
    scorecard_payload.pop("application_id", None)
    item = ApplicationScorecardRepository(session).create({**scorecard_payload, "application_id": application.id})
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    return _with_application_id(
        CandidateScorecardRead,
        item,
        application.candidate_application_id,
        person.candidate_person_id if person is not None else application.person_id,
    )


def list_application_review_decisions(application_id: str, session: Session) -> list[CandidateReviewDecisionRead]:
    application, _person = _get_application_with_person_or_404(session, application_id)
    items = ApplicationReviewDecisionRepository(session).by_application(application.candidate_application_id, limit=100, offset=0)
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    person_id = person.candidate_person_id if person is not None else application.person_id
    return [_with_application_id(CandidateReviewDecisionRead, item, application.candidate_application_id, person_id) for item in items]


def create_application_review_decision(
    application_id: str,
    payload: CandidateReviewDecisionCreate,
    session: Session,
) -> CandidateReviewDecisionRead:
    application, _person = _get_application_with_person_or_404(session, application_id)
    review_payload = payload.model_dump(exclude_unset=True)
    review_payload.pop("person_id", None)
    review_payload.pop("application_id", None)
    item = ApplicationReviewDecisionRepository(session).create(
        {
            **review_payload,
            "application_id": application.id,
            "decided_at": payload.decided_at or _now(),
        }
    )
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    return _with_application_id(
        CandidateReviewDecisionRead,
        item,
        application.candidate_application_id,
        person.candidate_person_id if person is not None else application.person_id,
    )


def list_application_sync_records(application_id: str, session: Session) -> list[TalentPoolSyncRecordRead]:
    application, _person = _get_application_with_person_or_404(session, application_id)
    items = ApplicationSyncRecordRepository(session).by_application(application.candidate_application_id, limit=100, offset=0)
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    person_id = person.candidate_person_id if person is not None else application.person_id
    return [_with_application_id(TalentPoolSyncRecordRead, item, application.candidate_application_id, person_id) for item in items]


def create_application_sync_record(
    application_id: str,
    payload: TalentPoolSyncRecordCreate,
    session: Session,
) -> TalentPoolSyncRecordRead:
    application, _person = _get_application_with_person_or_404(session, application_id)
    sync_payload = payload.model_dump(exclude_unset=True)
    sync_payload.pop("person_id", None)
    sync_payload.pop("application_id", None)
    item = ApplicationSyncRecordRepository(session).create({**sync_payload, "application_id": application.id})
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    return _with_application_id(
        TalentPoolSyncRecordRead,
        item,
        application.candidate_application_id,
        person.candidate_person_id if person is not None else application.person_id,
    )


__all__ = [
    "_get_application_with_person_or_404",
    "_with_application_id",
    "build_application_thread",
    "create_application_assignment",
    "create_application_assessment",
    "create_application_entry",
    "create_application_resume_artifact",
    "create_application_review_decision",
    "create_application_scorecard",
    "create_application_status_transition",
    "create_application_sync_record",
    "list_application_assignments",
    "list_application_entries",
    "list_application_resume_artifacts",
    "list_application_review_decisions",
    "list_application_scorecards",
    "list_application_status_transitions",
    "list_application_sync_records",
    "list_application_threads",
]
