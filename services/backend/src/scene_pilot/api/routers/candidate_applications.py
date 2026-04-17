from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_session
from scene_pilot.api.routers.recruit_agent import (
    build_application_thread,
    create_application_assignment,
    create_application_assessment,
    create_application_review_decision,
    create_application_scorecard,
    create_application_sync_record,
    create_application_entry,
    create_application_status_transition,
    create_application_resume_artifact,
    list_application_threads,
    list_application_assignments,
    list_application_review_decisions,
    list_application_scorecards,
    list_application_sync_records,
    list_application_resume_artifacts,
    list_application_entries,
    list_application_status_transitions,
    _get_application_with_person_or_404,
    _with_application_id,
)
from scene_pilot.repositories import ApplicationAssessmentRepository, CandidateApplicationRepository
from scene_pilot.schemas import (
    CandidateAssessmentCreate,
    CandidateAssessmentRead,
    CandidateAssignmentCreate,
    CandidateAssignmentRead,
    CandidateApplicationCreate,
    CandidateApplicationRead,
    CandidateApplicationUpdate,
    CandidateConversationEntryCreate,
    CandidateConversationEntryRead,
    CandidateReviewDecisionCreate,
    CandidateReviewDecisionRead,
    CandidateScorecardCreate,
    CandidateScorecardRead,
    CandidateStateTransitionRequest,
    CandidateStatusTransitionRead,
    CandidateThreadRead,
    ResumeArtifactCreate,
    ResumeArtifactRead,
    TalentPoolSyncRecordCreate,
    TalentPoolSyncRecordRead,
)

router = APIRouter(prefix="/api/candidate-applications", tags=["candidate-applications"])


@router.get("", response_model=list[CandidateApplicationRead])
def list_candidate_applications(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[CandidateApplicationRead]:
    return [
        CandidateApplicationRead.model_validate(item)
        for item in CandidateApplicationRepository(session).list(limit=limit, offset=offset)
    ]


@router.get("/threads", response_model=list[CandidateThreadRead])
def list_candidate_application_threads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[CandidateThreadRead]:
    return list_application_threads(limit=limit, offset=offset, session=session)


@router.post("", response_model=CandidateApplicationRead, status_code=201)
def create_candidate_application(
    payload: CandidateApplicationCreate,
    session: Session = Depends(get_session),
) -> CandidateApplicationRead:
    try:
        item = CandidateApplicationRepository(session).create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CandidateApplicationRead.model_validate(item)


@router.get("/{application_id}", response_model=CandidateApplicationRead)
def get_candidate_application(application_id: str, session: Session = Depends(get_session)) -> CandidateApplicationRead:
    item = CandidateApplicationRepository(session).get(application_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate application not found")
    return CandidateApplicationRead.model_validate(item)


@router.patch("/{application_id}", response_model=CandidateApplicationRead)
def update_candidate_application(
    application_id: str,
    payload: CandidateApplicationUpdate,
    session: Session = Depends(get_session),
) -> CandidateApplicationRead:
    repo = CandidateApplicationRepository(session)
    item = repo.get(application_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate application not found")
    updated = repo.update(item, payload)
    return CandidateApplicationRead.model_validate(updated)


@router.get("/{applicationId}/thread", response_model=CandidateThreadRead)
def get_candidate_application_thread(applicationId: str, session: Session = Depends(get_session)) -> CandidateThreadRead:
    return build_application_thread(session, applicationId)


@router.get("/{applicationId}/entries", response_model=list[CandidateConversationEntryRead])
def get_candidate_application_entries(
    applicationId: str,
    session: Session = Depends(get_session),
) -> list[CandidateConversationEntryRead]:
    return list_application_entries(session, applicationId)


@router.post("/{applicationId}/entries", response_model=CandidateConversationEntryRead, status_code=201)
def create_candidate_application_entry(
    applicationId: str,
    payload: CandidateConversationEntryCreate,
    session: Session = Depends(get_session),
) -> CandidateConversationEntryRead:
    return create_application_entry(session, applicationId, payload)


@router.get("/{applicationId}/transitions", response_model=list[CandidateStatusTransitionRead])
def get_candidate_application_transitions(
    applicationId: str,
    session: Session = Depends(get_session),
) -> list[CandidateStatusTransitionRead]:
    return list_application_status_transitions(session, applicationId)


@router.post("/{applicationId}/transitions", response_model=CandidateThreadRead)
def create_candidate_application_transition(
    applicationId: str,
    payload: CandidateStateTransitionRequest,
    session: Session = Depends(get_session),
) -> CandidateThreadRead:
    return create_application_status_transition(session, applicationId, payload)


@router.get("/{applicationId}/assessments", response_model=list[CandidateAssessmentRead])
def list_candidate_application_assessments(
    applicationId: str,
    session: Session = Depends(get_session),
) -> list[CandidateAssessmentRead]:
    application, _person = _get_application_with_person_or_404(session, applicationId)
    items = ApplicationAssessmentRepository(session).by_application(application.id, limit=100, offset=0)
    return [_with_application_id(CandidateAssessmentRead, item, application.id, application.person_id) for item in items]


@router.post("/{applicationId}/assessments", response_model=CandidateAssessmentRead, status_code=201)
def create_candidate_application_assessment(
    applicationId: str,
    payload: CandidateAssessmentCreate,
    session: Session = Depends(get_session),
) -> CandidateAssessmentRead:
    return create_application_assessment(applicationId, payload, session)


@router.get("/{applicationId}/assignments", response_model=list[CandidateAssignmentRead])
def list_candidate_application_assignments(
    applicationId: str,
    session: Session = Depends(get_session),
) -> list[CandidateAssignmentRead]:
    return list_application_assignments(applicationId, session)


@router.post("/{applicationId}/assignments", response_model=CandidateAssignmentRead, status_code=201)
def create_candidate_application_assignment(
    applicationId: str,
    payload: CandidateAssignmentCreate,
    session: Session = Depends(get_session),
) -> CandidateAssignmentRead:
    return create_application_assignment(applicationId, payload, session)


@router.get("/{applicationId}/resume-artifacts", response_model=list[ResumeArtifactRead])
def list_candidate_application_resume_artifacts(
    applicationId: str,
    session: Session = Depends(get_session),
) -> list[ResumeArtifactRead]:
    return list_application_resume_artifacts(applicationId, session)


@router.post("/{applicationId}/resume-artifacts", response_model=ResumeArtifactRead, status_code=201)
def create_candidate_application_resume_artifact(
    applicationId: str,
    payload: ResumeArtifactCreate,
    session: Session = Depends(get_session),
) -> ResumeArtifactRead:
    return create_application_resume_artifact(applicationId, payload, session)


@router.get("/{applicationId}/scorecards", response_model=list[CandidateScorecardRead])
def list_candidate_application_scorecards(
    applicationId: str,
    session: Session = Depends(get_session),
) -> list[CandidateScorecardRead]:
    return list_application_scorecards(applicationId, session)


@router.post("/{applicationId}/scorecards", response_model=CandidateScorecardRead, status_code=201)
def create_candidate_application_scorecard(
    applicationId: str,
    payload: CandidateScorecardCreate,
    session: Session = Depends(get_session),
) -> CandidateScorecardRead:
    return create_application_scorecard(applicationId, payload, session)


@router.get("/{applicationId}/review-decisions", response_model=list[CandidateReviewDecisionRead])
def list_candidate_application_review_decisions(
    applicationId: str,
    session: Session = Depends(get_session),
) -> list[CandidateReviewDecisionRead]:
    return list_application_review_decisions(applicationId, session)


@router.post("/{applicationId}/review-decisions", response_model=CandidateReviewDecisionRead, status_code=201)
def create_candidate_application_review_decision(
    applicationId: str,
    payload: CandidateReviewDecisionCreate,
    session: Session = Depends(get_session),
) -> CandidateReviewDecisionRead:
    return create_application_review_decision(applicationId, payload, session)


@router.get("/{applicationId}/sync-records", response_model=list[TalentPoolSyncRecordRead])
def list_candidate_application_sync_records(
    applicationId: str,
    session: Session = Depends(get_session),
) -> list[TalentPoolSyncRecordRead]:
    return list_application_sync_records(applicationId, session)


@router.post("/{applicationId}/sync-records", response_model=TalentPoolSyncRecordRead, status_code=201)
def create_candidate_application_sync_record(
    applicationId: str,
    payload: TalentPoolSyncRecordCreate,
    session: Session = Depends(get_session),
) -> TalentPoolSyncRecordRead:
    return create_application_sync_record(applicationId, payload, session)
