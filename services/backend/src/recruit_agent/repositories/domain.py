from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.base import utcnow
from recruit_agent.models import (
    AgentLearning,
    ApplicationAssessment,
    ApplicationAssignment,
    ApplicationCommunicationLog,
    ApplicationReviewDecision,
    ApplicationScorecard,
    ApplicationSession,
    ApplicationStatusTransition,
    ApplicationSyncRecord,
    ExecutionGraphProjection,
    ExecutionTrace,
    GoalSpec,
    AgentRun,
    AgentRunCheckpoint,
    AgentRuntimeEvent,
    AgentSession,
    AgentWorkItem,
    OperatorInteraction,
    ApprovalItem,
    AppSetting,
    Candidate,
    CandidateApplication,
    CandidateAssessment,
    CandidateAssignment,
    CandidatePlatformIdx,
    CandidateReviewDecision,
    CandidateScorecard,
    CandidateSession,
    CandidateStatusTransition,
    CommunicationLog,
    DecisionLog,
    EnvironmentSnapshot,
    EvolutionArtifact,
    ExecutionEpisode,
    ExecutionPlan,
    JobDescription,
    JobDescriptionPlatformIdx,
    McpServer,
    McpTool,
    RecruitAgentProfile,
    PersonResumeArtifact,
    ResumeArtifact,
    Skill,
    StrategyFragment,
    SyncBacklogEntry,
    TaskSpec,
    TaskQueueItem,
    TalentPoolSyncRecord,
    Playbook,
    PlaybookPatch,
    PlaybookVersion,
    RecruitmentStateMachineVersion,
)
from recruit_agent.schemas import AppSettingsRead, MetricsSummary

ModelT = TypeVar("ModelT")


def _apply_update(instance: Any, data: dict[str, Any]) -> Any:
    for key, value in data.items():
        setattr(instance, key, value)
    return instance


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, limit: int = 100, offset: int = 0) -> list[ModelT]:
        stmt = select(self.model).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())

    def count(self) -> int:
        stmt = select(func.count()).select_from(self.model)
        return int(self.session.scalar(stmt) or 0)

    def get(self, item_id: str) -> ModelT | None:
        return self.session.get(self.model, item_id)

    def delete(self, instance: ModelT) -> None:
        self.session.delete(instance)
        self.session.commit()

    def create(self, data: BaseModel | dict[str, Any]) -> ModelT:
        payload = data.model_dump(exclude_unset=True) if isinstance(data, BaseModel) else dict(data)
        instance = self.model(**payload)  # type: ignore[call-arg]
        self.session.add(instance)
        self.session.commit()
        self.session.refresh(instance)
        return instance

    def update(self, instance: ModelT, data: BaseModel | dict[str, Any]) -> ModelT:
        payload = data.model_dump(exclude_unset=True) if isinstance(data, BaseModel) else dict(data)
        _apply_update(instance, payload)
        self.session.commit()
        self.session.refresh(instance)
        return instance


class PlaybookRepository(BaseRepository[Playbook]):
    model = Playbook

    def active(self) -> list[Playbook]:
        stmt = select(Playbook).where(Playbook.status == "active").order_by(Playbook.updated_at.desc(), Playbook.id.asc())
        return list(self.session.scalars(stmt).all())


class CandidateRepository(BaseRepository[Candidate]):
    model = Candidate

    def get_by_business_id(self, candidate_person_id: str) -> Candidate | None:
        stmt = select(Candidate).where(Candidate.candidate_person_id == candidate_person_id)
        return self.session.scalars(stmt).first()

    def get_by_storage_id(self, storage_id: str) -> Candidate | None:
        return self.session.get(Candidate, storage_id)

    def get(self, item_id: str) -> Candidate | None:
        return self.get_by_business_id(item_id)

    def by_platform_candidate_id(self, platform: str, platform_candidate_id: str) -> Candidate | None:
        idx_repo = CandidatePlatformIdxRepository(self.session)
        idx = idx_repo.by_platform_identity(platform, platform_candidate_id)
        if idx is not None:
            candidate = self.get_by_storage_id(idx.candidate_id)
            if candidate is not None:
                return candidate
        return None

    def resolve(self, candidate_id: str) -> Candidate | None:
        return self.get(candidate_id)

    def _sync_platform_identity(self, candidate: Candidate) -> None:
        platform_candidate_id = str(candidate.platform_candidate_id or "").strip()
        if not platform_candidate_id:
            return
        idx_repo = CandidatePlatformIdxRepository(self.session)
        candidate_idx = idx_repo.by_candidate_and_platform(candidate.id, candidate.platform)
        if candidate_idx is not None:
            candidate_idx.platform_candidate_person_id = platform_candidate_id
            self.session.flush()
            return
        idx = idx_repo.by_platform_identity(candidate.platform, platform_candidate_id)
        if idx is None:
            idx_repo.create(
                {
                    "candidate_id": candidate.id,
                    "platform": candidate.platform,
                    "platform_candidate_person_id": platform_candidate_id,
                }
            )
            return
        if idx.candidate_id != candidate.id:
            idx.candidate_id = candidate.id
            self.session.flush()

    def create(self, data: BaseModel | dict[str, Any]) -> Candidate:
        payload = data.model_dump(exclude_unset=True) if isinstance(data, BaseModel) else dict(data)
        instance = self.model(**payload)  # type: ignore[call-arg]
        self.session.add(instance)
        self.session.flush()
        self._sync_platform_identity(instance)
        self.session.commit()
        self.session.refresh(instance)
        return instance

    def update(self, instance: Candidate, data: BaseModel | dict[str, Any]) -> Candidate:
        payload = data.model_dump(exclude_unset=True) if isinstance(data, BaseModel) else dict(data)
        _apply_update(instance, payload)
        self.session.flush()
        self._sync_platform_identity(instance)
        self.session.commit()
        self.session.refresh(instance)
        return instance


class CandidatePlatformIdxRepository(BaseRepository[CandidatePlatformIdx]):
    model = CandidatePlatformIdx

    def by_platform_identity(self, platform: str, platform_candidate_id: str) -> CandidatePlatformIdx | None:
        stmt = select(CandidatePlatformIdx).where(
            CandidatePlatformIdx.platform == platform,
            CandidatePlatformIdx.platform_candidate_person_id == platform_candidate_id,
        )
        return self.session.scalars(stmt).first()

    def by_candidate_and_platform(self, candidate_id: str, platform: str) -> CandidatePlatformIdx | None:
        stmt = (
            select(CandidatePlatformIdx)
            .where(
                CandidatePlatformIdx.candidate_id == candidate_id,
                CandidatePlatformIdx.platform == platform,
            )
            .order_by(CandidatePlatformIdx.updated_at.desc(), CandidatePlatformIdx.id.asc())
        )
        return self.session.scalars(stmt).first()


class JobDescriptionRepository(BaseRepository[JobDescription]):
    model = JobDescription

    def _filtered_query(
        self,
        *,
        status: str | None = None,
        location: str | None = None,
        department: str | None = None,
        owner: str | None = None,
        keyword: str | None = None,
        applicant_keyword: str | None = None,
    ):
        stmt = select(JobDescription)
        normalized_status = str(status or "").strip()
        if normalized_status:
            stmt = stmt.where(JobDescription.status == normalized_status)
        normalized_location = str(location or "").strip()
        if normalized_location:
            stmt = stmt.where(JobDescription.location == normalized_location)
        normalized_department = str(department or "").strip()
        if normalized_department:
            stmt = stmt.where(JobDescription.department == normalized_department)
        normalized_owner = str(owner or "").strip()
        if normalized_owner:
            stmt = stmt.where(
                or_(
                    JobDescription.detail_metadata["ownerName"].as_string() == normalized_owner,
                    JobDescription.detail_metadata["owner_name"].as_string() == normalized_owner,
                    JobDescription.detail_metadata["recruiterName"].as_string() == normalized_owner,
                    JobDescription.detail_metadata["recruiter_name"].as_string() == normalized_owner,
                )
            )
        normalized_keyword = str(keyword or "").strip()
        if normalized_keyword:
            pattern = f"%{normalized_keyword}%"
            stmt = stmt.where(
                or_(
                    JobDescription.title.ilike(pattern),
                    JobDescription.job_description_id.ilike(pattern),
                    JobDescription.company_name.ilike(pattern),
                    JobDescription.department.ilike(pattern),
                    JobDescription.location.ilike(pattern),
                )
            )
        normalized_applicant_keyword = str(applicant_keyword or "").strip()
        if normalized_applicant_keyword:
            pattern = f"%{normalized_applicant_keyword}%"
            matching_job_ids = (
                select(CandidateApplication.job_description_id)
                .join(Candidate, Candidate.id == CandidateApplication.person_id)
                .where(
                    CandidateApplication.job_description_id.is_not(None),
                    or_(
                        Candidate.name.ilike(pattern),
                        Candidate.candidate_person_id.ilike(pattern),
                        Candidate.platform_candidate_id.ilike(pattern),
                        Candidate.contact_info["phone"].as_string().ilike(pattern),
                        Candidate.contact_info["mobile"].as_string().ilike(pattern),
                        Candidate.contact_info["email"].as_string().ilike(pattern),
                        CandidateApplication.contact_snapshot["phone"].as_string().ilike(pattern),
                        CandidateApplication.contact_snapshot["mobile"].as_string().ilike(pattern),
                        CandidateApplication.contact_snapshot["email"].as_string().ilike(pattern),
                    ),
                )
            )
            stmt = stmt.where(JobDescription.id.in_(matching_job_ids))
        return stmt

    def list_page(
        self,
        *,
        status: str | None = None,
        location: str | None = None,
        department: str | None = None,
        owner: str | None = None,
        keyword: str | None = None,
        applicant_keyword: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobDescription]:
        stmt = (
            self._filtered_query(
                status=status,
                location=location,
                department=department,
                owner=owner,
                keyword=keyword,
                applicant_keyword=applicant_keyword,
            )
            .order_by(JobDescription.updated_at.desc(), JobDescription.job_description_id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def count_page(
        self,
        *,
        status: str | None = None,
        location: str | None = None,
        department: str | None = None,
        owner: str | None = None,
        keyword: str | None = None,
        applicant_keyword: str | None = None,
    ) -> int:
        filtered = self._filtered_query(
            status=status,
            location=location,
            department=department,
            owner=owner,
            keyword=keyword,
            applicant_keyword=applicant_keyword,
        ).subquery()
        stmt = select(func.count()).select_from(filtered)
        return int(self.session.scalar(stmt) or 0)

    def get_by_business_id(self, job_description_id: str) -> JobDescription | None:
        stmt = select(JobDescription).where(JobDescription.job_description_id == job_description_id)
        return self.session.scalars(stmt).first()

    def get(self, item_id: str) -> JobDescription | None:
        return self.get_by_business_id(item_id)

    def get_by_storage_id(self, storage_id: str) -> JobDescription | None:
        return self.session.get(JobDescription, storage_id)


class JobDescriptionPlatformIdxRepository(BaseRepository[JobDescriptionPlatformIdx]):
    model = JobDescriptionPlatformIdx

    def by_platform_identity(self, platform: str, external_id: str) -> JobDescriptionPlatformIdx | None:
        stmt = select(JobDescriptionPlatformIdx).where(
            JobDescriptionPlatformIdx.platform == platform,
            JobDescriptionPlatformIdx.external_id == external_id,
        )
        return self.session.scalars(stmt).first()


class CandidateApplicationRepository(BaseRepository[CandidateApplication]):
    model = CandidateApplication

    def get_by_business_id(self, candidate_application_id: str) -> CandidateApplication | None:
        stmt = select(CandidateApplication).where(CandidateApplication.candidate_application_id == candidate_application_id)
        return self.session.scalars(stmt).first()

    def get_by_storage_id(self, storage_id: str) -> CandidateApplication | None:
        return self.session.get(CandidateApplication, storage_id)

    def get(self, item_id: str) -> CandidateApplication | None:
        return self.get_by_business_id(item_id)

    def _normalize_payload(self, data: BaseModel | dict[str, Any]) -> dict[str, Any]:
        payload = data.model_dump(exclude_unset=True) if isinstance(data, BaseModel) else dict(data)
        person_business_id = str(payload.get("person_id") or "").strip()
        job_business_id = str(payload.get("job_description_id") or "").strip()
        person = CandidateRepository(self.session).get(person_business_id) if person_business_id else None
        if person is not None:
            payload["person_id"] = person.id
        job_description = JobDescriptionRepository(self.session).get(job_business_id) if job_business_id else None
        if job_description is not None:
            payload["job_description_id"] = job_description.id
        if person_business_id and job_business_id:
            from recruit_agent.services.application_window import make_application_window

            canonical_window = make_application_window(person_business_id, job_business_id)
            provided_window = str(payload.get("application_window") or "").strip()
            if provided_window and provided_window != canonical_window:
                raise ValueError("application_window must match the canonical person/job/month format")
            payload["application_window"] = canonical_window
        source_platform = str(payload.get("source_platform") or payload.get("platform") or "site").strip() or "site"
        payload.setdefault("source_platform", source_platform)
        if person is not None and not str(payload.get("source_platform_candidate_person_id") or "").strip():
            idx = CandidatePlatformIdxRepository(self.session).by_candidate_and_platform(person.id, source_platform)
            if idx is not None:
                payload["source_platform_candidate_person_id"] = idx.platform_candidate_person_id
        return payload

    def create(self, data: BaseModel | dict[str, Any]) -> CandidateApplication:
        return super().create(self._normalize_payload(data))

    def update(self, instance: CandidateApplication, data: BaseModel | dict[str, Any]) -> CandidateApplication:
        payload = self._normalize_payload(data)
        return super().update(instance, payload)

    def count(self) -> int:
        stmt = select(func.count()).select_from(CandidateApplication)
        return int(self.session.scalar(stmt) or 0)

    def count_by_status(self) -> dict[str, int]:
        stmt = select(CandidateApplication.current_status, func.count()).group_by(CandidateApplication.current_status)
        return {status: count for status, count in self.session.execute(stmt).all()}

    def count_by_current_statuses(self, statuses: list[str]) -> int:
        normalized = [str(status).strip() for status in statuses if str(status).strip()]
        if not normalized:
            return 0
        stmt = select(func.count()).select_from(CandidateApplication).where(CandidateApplication.current_status.in_(normalized))
        return int(self.session.scalar(stmt) or 0)

    def by_job_description_storage_id(
        self,
        job_description_id: str,
        *,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[CandidateApplication]:
        stmt = (
            select(CandidateApplication)
            .where(CandidateApplication.job_description_id == job_description_id)
            .order_by(CandidateApplication.updated_at.desc(), CandidateApplication.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def by_current_statuses(self, statuses: list[str], *, limit: int = 500, offset: int = 0) -> list[CandidateApplication]:
        normalized = [str(status).strip() for status in statuses if str(status).strip()]
        if not normalized:
            return []
        stmt = (
            select(CandidateApplication)
            .where(CandidateApplication.current_status.in_(normalized))
            .order_by(CandidateApplication.updated_at.desc(), CandidateApplication.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def by_person(self, person_id: str, *, limit: int = 100, offset: int = 0) -> list[CandidateApplication]:
        stmt = (
            select(CandidateApplication)
            .where(CandidateApplication.person_id == person_id)
            .order_by(CandidateApplication.updated_at.desc(), CandidateApplication.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def by_application_window(self, application_window: str) -> CandidateApplication | None:
        stmt = select(CandidateApplication).where(CandidateApplication.application_window == application_window)
        return self.session.scalars(stmt).first()


def _resolve_application_storage_id(session: Session, application_id: str) -> str:
    normalized = str(application_id or "").strip()
    if not normalized:
        return normalized
    repo = CandidateApplicationRepository(session)
    application = repo.get_by_business_id(normalized)
    if application is not None:
        return application.id
    return normalized


class ApplicationSessionRepository(BaseRepository[ApplicationSession]):
    model = ApplicationSession

    def by_application_id(self, application_id: str) -> ApplicationSession | None:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        stmt = select(ApplicationSession).where(ApplicationSession.application_id == resolved_application_id)
        return self.session.scalars(stmt).first()

    def get_or_create(self, application_id: str, *, defaults: dict[str, Any] | None = None) -> ApplicationSession:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        existing = self.by_application_id(application_id)
        if existing is not None:
            return existing
        payload = {"application_id": resolved_application_id, **dict(defaults or {})}
        return self.create(payload)

    def append_recent_message(
        self,
        application_session: ApplicationSession,
        *,
        direction: str,
        content: str,
        message_type: str = "text",
        metadata: dict[str, Any] | None = None,
    ) -> ApplicationSession:
        history = list(application_session.recent_messages or [])
        history.append(
            {
                "direction": direction,
                "content": content,
                "message_type": message_type,
                "metadata": dict(metadata or {}),
                "timestamp": utcnow().isoformat(),
            }
        )
        application_session.recent_messages = history[-20:]
        application_session.last_active_at = utcnow()
        self.session.commit()
        self.session.refresh(application_session)
        return application_session


class ApplicationCommunicationLogRepository(BaseRepository[ApplicationCommunicationLog]):
    model = ApplicationCommunicationLog

    def by_application(self, application_id: str, limit: int = 100, offset: int = 0) -> list[ApplicationCommunicationLog]:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        stmt = (
            select(ApplicationCommunicationLog)
            .where(ApplicationCommunicationLog.application_id == resolved_application_id)
            .order_by(ApplicationCommunicationLog.timestamp.asc(), ApplicationCommunicationLog.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class ApplicationStatusTransitionRepository(BaseRepository[ApplicationStatusTransition]):
    model = ApplicationStatusTransition

    def by_application(self, application_id: str, limit: int = 200, offset: int = 0) -> list[ApplicationStatusTransition]:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        stmt = (
            select(ApplicationStatusTransition)
            .where(ApplicationStatusTransition.application_id == resolved_application_id)
            .order_by(ApplicationStatusTransition.created_at.asc(), ApplicationStatusTransition.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def latest_for_application(self, application_id: str) -> ApplicationStatusTransition | None:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        stmt = (
            select(ApplicationStatusTransition)
            .where(ApplicationStatusTransition.application_id == resolved_application_id)
            .order_by(ApplicationStatusTransition.created_at.desc(), ApplicationStatusTransition.id.desc())
        )
        return self.session.scalars(stmt).first()


class ApplicationAssessmentRepository(BaseRepository[ApplicationAssessment]):
    model = ApplicationAssessment

    def by_application(self, application_id: str, limit: int = 50, offset: int = 0) -> list[ApplicationAssessment]:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        stmt = (
            select(ApplicationAssessment)
            .where(ApplicationAssessment.application_id == resolved_application_id)
            .order_by(ApplicationAssessment.created_at.desc(), ApplicationAssessment.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class ApplicationAssignmentRepository(BaseRepository[ApplicationAssignment]):
    model = ApplicationAssignment

    def by_application(self, application_id: str, limit: int = 50, offset: int = 0) -> list[ApplicationAssignment]:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        stmt = (
            select(ApplicationAssignment)
            .where(ApplicationAssignment.application_id == resolved_application_id)
            .order_by(ApplicationAssignment.assigned_at.desc(), ApplicationAssignment.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class PersonResumeArtifactRepository(BaseRepository[PersonResumeArtifact]):
    model = PersonResumeArtifact

    def by_person(self, person_id: str, limit: int = 50, offset: int = 0) -> list[PersonResumeArtifact]:
        stmt = (
            select(PersonResumeArtifact)
            .where(PersonResumeArtifact.person_id == person_id)
            .order_by(PersonResumeArtifact.captured_at.desc(), PersonResumeArtifact.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class ApplicationScorecardRepository(BaseRepository[ApplicationScorecard]):
    model = ApplicationScorecard

    def by_application(self, application_id: str, limit: int = 100, offset: int = 0) -> list[ApplicationScorecard]:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        stmt = (
            select(ApplicationScorecard)
            .where(ApplicationScorecard.application_id == resolved_application_id)
            .order_by(ApplicationScorecard.created_at.desc(), ApplicationScorecard.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class ApplicationReviewDecisionRepository(BaseRepository[ApplicationReviewDecision]):
    model = ApplicationReviewDecision

    def by_application(self, application_id: str, limit: int = 100, offset: int = 0) -> list[ApplicationReviewDecision]:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        stmt = (
            select(ApplicationReviewDecision)
            .where(ApplicationReviewDecision.application_id == resolved_application_id)
            .order_by(ApplicationReviewDecision.decided_at.desc(), ApplicationReviewDecision.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class ApplicationSyncRecordRepository(BaseRepository[ApplicationSyncRecord]):
    model = ApplicationSyncRecord

    def by_application(self, application_id: str, limit: int = 50, offset: int = 0) -> list[ApplicationSyncRecord]:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        stmt = (
            select(ApplicationSyncRecord)
            .where(ApplicationSyncRecord.application_id == resolved_application_id)
            .order_by(ApplicationSyncRecord.created_at.desc(), ApplicationSyncRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class CandidateSessionRepository(BaseRepository[CandidateSession]):
    model = CandidateSession

    def by_candidate_id(self, candidate_id: str) -> CandidateSession | None:
        stmt = select(CandidateSession).where(CandidateSession.candidate_id == candidate_id)
        return self.session.scalars(stmt).first()

    def get_or_create(self, candidate_id: str, *, defaults: dict[str, Any] | None = None) -> CandidateSession:
        existing = self.by_candidate_id(candidate_id)
        if existing is not None:
            return existing
        payload = {"candidate_id": candidate_id, **dict(defaults or {})}
        return self.create(payload)

    def append_recent_message(
        self,
        candidate_session: CandidateSession,
        *,
        direction: str,
        content: str,
        message_type: str = "text",
        metadata: dict[str, Any] | None = None,
    ) -> CandidateSession:
        history = list(candidate_session.recent_messages or [])
        history.append(
            {
                "direction": direction,
                "content": content,
                "message_type": message_type,
                "metadata": dict(metadata or {}),
                "timestamp": utcnow().isoformat(),
            }
        )
        candidate_session.recent_messages = history[-20:]
        candidate_session.last_active_at = utcnow()
        self.session.commit()
        self.session.refresh(candidate_session)
        return candidate_session


class CommunicationLogRepository(BaseRepository[CommunicationLog]):
    model = CommunicationLog

    def by_candidate(self, candidate_id: str, limit: int = 100, offset: int = 0) -> list[CommunicationLog]:
        stmt = (
            select(CommunicationLog)
            .where(CommunicationLog.candidate_id == candidate_id)
            .order_by(CommunicationLog.timestamp.asc(), CommunicationLog.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class CandidateStatusTransitionRepository(BaseRepository[CandidateStatusTransition]):
    model = CandidateStatusTransition

    def by_candidate(self, candidate_id: str, limit: int = 200, offset: int = 0) -> list[CandidateStatusTransition]:
        stmt = (
            select(CandidateStatusTransition)
            .where(CandidateStatusTransition.candidate_id == candidate_id)
            .order_by(CandidateStatusTransition.created_at.asc(), CandidateStatusTransition.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def latest_for_candidate(self, candidate_id: str) -> CandidateStatusTransition | None:
        stmt = (
            select(CandidateStatusTransition)
            .where(CandidateStatusTransition.candidate_id == candidate_id)
            .order_by(CandidateStatusTransition.created_at.desc(), CandidateStatusTransition.id.desc())
        )
        return self.session.scalars(stmt).first()


class CandidateAssessmentRepository(BaseRepository[CandidateAssessment]):
    model = CandidateAssessment

    def by_candidate(self, candidate_id: str, limit: int = 50, offset: int = 0) -> list[CandidateAssessment]:
        stmt = (
            select(CandidateAssessment)
            .where(CandidateAssessment.candidate_id == candidate_id)
            .order_by(CandidateAssessment.created_at.desc(), CandidateAssessment.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class CandidateAssignmentRepository(BaseRepository[CandidateAssignment]):
    model = CandidateAssignment

    def by_candidate(self, candidate_id: str, limit: int = 50, offset: int = 0) -> list[CandidateAssignment]:
        stmt = (
            select(CandidateAssignment)
            .where(CandidateAssignment.candidate_id == candidate_id)
            .order_by(CandidateAssignment.assigned_at.desc(), CandidateAssignment.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class ResumeArtifactRepository(BaseRepository[ResumeArtifact]):
    model = ResumeArtifact

    def by_application(self, application_id: str, limit: int = 50, offset: int = 0) -> list[ResumeArtifact]:
        resolved_application_id = _resolve_application_storage_id(self.session, application_id)
        stmt = (
            select(ResumeArtifact)
            .where(ResumeArtifact.application_id == resolved_application_id)
            .order_by(ResumeArtifact.captured_at.desc(), ResumeArtifact.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class CandidateScorecardRepository(BaseRepository[CandidateScorecard]):
    model = CandidateScorecard

    def by_candidate(self, candidate_id: str, limit: int = 100, offset: int = 0) -> list[CandidateScorecard]:
        stmt = (
            select(CandidateScorecard)
            .where(CandidateScorecard.candidate_id == candidate_id)
            .order_by(CandidateScorecard.created_at.desc(), CandidateScorecard.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class CandidateReviewDecisionRepository(BaseRepository[CandidateReviewDecision]):
    model = CandidateReviewDecision

    def by_candidate(self, candidate_id: str, limit: int = 100, offset: int = 0) -> list[CandidateReviewDecision]:
        stmt = (
            select(CandidateReviewDecision)
            .where(CandidateReviewDecision.candidate_id == candidate_id)
            .order_by(CandidateReviewDecision.decided_at.desc(), CandidateReviewDecision.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class McpServerRepository(BaseRepository[McpServer]):
    model = McpServer

    def enabled(self) -> list[McpServer]:
        stmt = select(McpServer).where(McpServer.enabled.is_(True)).order_by(McpServer.name.asc(), McpServer.id.asc())
        return list(self.session.scalars(stmt).all())

    def by_key(self, server_key: str) -> McpServer | None:
        stmt = select(McpServer).where(McpServer.server_key == server_key)
        return self.session.scalars(stmt).first()


class McpToolRepository(BaseRepository[McpTool]):
    model = McpTool

    def by_server(self, server_id: str, *, enabled_only: bool = False) -> list[McpTool]:
        stmt = select(McpTool).where(McpTool.server_id == server_id)
        if enabled_only:
            stmt = stmt.where(McpTool.enabled.is_(True))
        stmt = stmt.order_by(McpTool.name.asc(), McpTool.id.asc())
        return list(self.session.scalars(stmt).all())


class TalentPoolSyncRecordRepository(BaseRepository[TalentPoolSyncRecord]):
    model = TalentPoolSyncRecord

    def by_candidate(self, candidate_id: str, limit: int = 50, offset: int = 0) -> list[TalentPoolSyncRecord]:
        stmt = (
            select(TalentPoolSyncRecord)
            .where(TalentPoolSyncRecord.candidate_id == candidate_id)
            .order_by(TalentPoolSyncRecord.created_at.desc(), TalentPoolSyncRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class EvolutionArtifactRepository(BaseRepository[EvolutionArtifact]):
    model = EvolutionArtifact

    def list_filtered(
        self,
        *,
        artifact_kind: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EvolutionArtifact]:
        stmt = select(EvolutionArtifact)
        if artifact_kind:
            stmt = stmt.where(EvolutionArtifact.artifact_kind == artifact_kind)
        if status:
            stmt = stmt.where(EvolutionArtifact.status == status)
        stmt = stmt.order_by(EvolutionArtifact.created_at.desc(), EvolutionArtifact.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())

    def find_by_source_task_id(
        self,
        *,
        source_task_id: str,
        artifact_kind: str | None = None,
    ) -> EvolutionArtifact | None:
        stmt = select(EvolutionArtifact).order_by(EvolutionArtifact.created_at.desc(), EvolutionArtifact.id.desc())
        if artifact_kind:
            stmt = stmt.where(EvolutionArtifact.artifact_kind == artifact_kind)
        for item in self.session.scalars(stmt):
            metadata = dict(item.artifact_metadata or {})
            if str(metadata.get("source_task_id") or "").strip() == source_task_id:
                return item
        return None


class RecruitAgentProfileRepository(BaseRepository[RecruitAgentProfile]):
    model = RecruitAgentProfile

    def by_agent_key(self, agent_key: str) -> RecruitAgentProfile | None:
        stmt = select(RecruitAgentProfile).where(RecruitAgentProfile.agent_key == agent_key)
        return self.session.scalars(stmt).first()

    def primary(self) -> RecruitAgentProfile | None:
        stmt = (
            select(RecruitAgentProfile)
            .where(RecruitAgentProfile.is_primary.is_(True))
            .order_by(RecruitAgentProfile.updated_at.desc(), RecruitAgentProfile.id.asc())
        )
        return self.session.scalars(stmt).first()


class AgentSessionRepository(BaseRepository[AgentSession]):
    model = AgentSession

    def by_agent_and_key(self, *, agent_profile_id: str, session_key: str = "primary") -> AgentSession | None:
        stmt = select(AgentSession).where(
            AgentSession.agent_profile_id == agent_profile_id,
            AgentSession.session_key == session_key,
        )
        return self.session.scalars(stmt).first()


class AgentRunRepository(BaseRepository[AgentRun]):
    model = AgentRun

    def list_for_session(self, session_id: str, limit: int = 100, offset: int = 0) -> list[AgentRun]:
        stmt = (
            select(AgentRun)
            .where(AgentRun.session_id == session_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def list_filtered(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
        lane: str | None = None,
        person_id: str | None = None,
        application_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentRun]:
        stmt = select(AgentRun)
        if session_id is not None:
            stmt = stmt.where(AgentRun.session_id == session_id)
        if status is not None:
            stmt = stmt.where(AgentRun.status == status)
        if lane is not None:
            stmt = stmt.where(AgentRun.lane == lane)
        if person_id is not None:
            stmt = stmt.where(AgentRun.person_id == person_id)
        if application_id is not None:
            stmt = stmt.where(AgentRun.application_id == application_id)
        stmt = stmt.order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())

    def list_recoverable(self, *, session_id: str | None = None, limit: int = 5000) -> list[AgentRun]:
        stmt = select(AgentRun).where(AgentRun.status.in_(("running", "interrupted", "resumable")))
        if session_id is not None:
            stmt = stmt.where(AgentRun.session_id == session_id)
        stmt = stmt.order_by(AgentRun.updated_at.desc(), AgentRun.id.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())

    def by_queue_task_id(self, queue_task_id: str) -> AgentRun | None:
        stmt = select(AgentRun).where(AgentRun.queue_task_id == queue_task_id).order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        return self.session.scalars(stmt).first()

    def latest_open_for_application(
        self,
        *,
        session_id: str,
        application_id: str,
        lane: str = "candidate",
    ) -> AgentRun | None:
        stmt = (
            select(AgentRun)
            .where(
                AgentRun.session_id == session_id,
                AgentRun.application_id == application_id,
                AgentRun.lane == lane,
                AgentRun.status.in_(("queued", "running", "waiting_human", "waiting_candidate", "blocked", "resumable")),
            )
            .order_by(AgentRun.updated_at.desc(), AgentRun.id.desc())
        )
        return self.session.scalars(stmt).first()

    def running_count(self, *, session_id: str, platform: str | None = None) -> int:
        stmt = select(func.count()).select_from(AgentRun).where(
            AgentRun.session_id == session_id,
            AgentRun.status == "running",
        )
        if platform is not None:
            stmt = stmt.where(AgentRun.platform == platform)
        return int(self.session.scalar(stmt) or 0)

    def conflicting_application_run(
        self,
        *,
        session_id: str,
        application_id: str,
        exclude_run_id: str | None = None,
    ) -> AgentRun | None:
        stmt = (
            select(AgentRun)
            .where(
                AgentRun.session_id == session_id,
                AgentRun.application_id == application_id,
                AgentRun.status.in_(("running", "waiting_human", "waiting_candidate", "blocked")),
            )
            .order_by(AgentRun.updated_at.desc(), AgentRun.id.desc())
        )
        if exclude_run_id is not None:
            stmt = stmt.where(AgentRun.id != exclude_run_id)
        return self.session.scalars(stmt).first()


class AgentWorkItemRepository(BaseRepository[AgentWorkItem]):
    model = AgentWorkItem

    def by_queue_task_id(self, queue_task_id: str) -> AgentWorkItem | None:
        stmt = select(AgentWorkItem).where(AgentWorkItem.queue_task_id == queue_task_id)
        return self.session.scalars(stmt).first()

    def list_filtered(
        self,
        *,
        run_id: str | None = None,
        status: str | None = None,
        person_id: str | None = None,
        application_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentWorkItem]:
        stmt = select(AgentWorkItem)
        if run_id is not None:
            stmt = stmt.where(AgentWorkItem.run_id == run_id)
        if status is not None:
            stmt = stmt.where(AgentWorkItem.status == status)
        if person_id is not None:
            stmt = stmt.where(AgentWorkItem.person_id == person_id)
        if application_id is not None:
            stmt = stmt.where(AgentWorkItem.application_id == application_id)
        stmt = stmt.order_by(AgentWorkItem.created_at.asc(), AgentWorkItem.id.asc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())

    def list_for_run(self, run_id: str, limit: int = 100, offset: int = 0) -> list[AgentWorkItem]:
        stmt = (
            select(AgentWorkItem)
            .where(AgentWorkItem.run_id == run_id)
            .order_by(AgentWorkItem.created_at.asc(), AgentWorkItem.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class AgentRunCheckpointRepository(BaseRepository[AgentRunCheckpoint]):
    model = AgentRunCheckpoint

    def open_for_run(self, run_id: str) -> AgentRunCheckpoint | None:
        stmt = (
            select(AgentRunCheckpoint)
            .where(AgentRunCheckpoint.run_id == run_id, AgentRunCheckpoint.status == "open")
            .order_by(AgentRunCheckpoint.created_at.desc(), AgentRunCheckpoint.id.desc())
        )
        return self.session.scalars(stmt).first()

    def by_approval(self, approval_id: str) -> AgentRunCheckpoint | None:
        stmt = select(AgentRunCheckpoint).where(AgentRunCheckpoint.approval_id == approval_id)
        return self.session.scalars(stmt).first()

    def list_open(self, *, session_id: str | None = None, limit: int = 100, offset: int = 0) -> list[AgentRunCheckpoint]:
        stmt = select(AgentRunCheckpoint).where(AgentRunCheckpoint.status == "open")
        if session_id is not None:
            stmt = stmt.where(AgentRunCheckpoint.session_id == session_id)
        stmt = stmt.order_by(AgentRunCheckpoint.created_at.desc(), AgentRunCheckpoint.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())


class AgentRuntimeEventRepository(BaseRepository[AgentRuntimeEvent]):
    model = AgentRuntimeEvent

    def recent(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AgentRuntimeEvent]:
        stmt = select(AgentRuntimeEvent)
        if session_id is not None:
            stmt = stmt.where(AgentRuntimeEvent.session_id == session_id)
        if run_id is not None:
            stmt = stmt.where(AgentRuntimeEvent.run_id == run_id)
        stmt = stmt.order_by(AgentRuntimeEvent.occurred_at.desc(), AgentRuntimeEvent.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())


class GoalSpecRepository(BaseRepository[GoalSpec]):
    model = GoalSpec

    def list_recent(
        self,
        *,
        agent_profile_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GoalSpec]:
        stmt = select(GoalSpec)
        if agent_profile_id is not None:
            stmt = stmt.where(GoalSpec.agent_profile_id == agent_profile_id)
        if status is not None:
            stmt = stmt.where(GoalSpec.status == status)
        stmt = stmt.order_by(
            GoalSpec.last_activity_at.desc().nullslast(),
            GoalSpec.created_at.desc(),
            GoalSpec.id.desc(),
        ).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())


class ExecutionTraceRepository(BaseRepository[ExecutionTrace]):
    model = ExecutionTrace

    def by_run(self, run_id: str) -> ExecutionTrace | None:
        stmt = (
            select(ExecutionTrace)
            .where(ExecutionTrace.run_id == run_id)
            .order_by(ExecutionTrace.created_at.desc(), ExecutionTrace.id.desc())
        )
        return self.session.scalars(stmt).first()

    def list_recent(
        self,
        *,
        goal_spec_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExecutionTrace]:
        stmt = select(ExecutionTrace)
        if goal_spec_id is not None:
            stmt = stmt.where(ExecutionTrace.goal_spec_id == goal_spec_id)
        if session_id is not None:
            stmt = stmt.where(ExecutionTrace.session_id == session_id)
        stmt = stmt.order_by(ExecutionTrace.created_at.desc(), ExecutionTrace.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())


class StrategyFragmentRepository(BaseRepository[StrategyFragment]):
    model = StrategyFragment

    def list_recent(
        self,
        *,
        agent_profile_id: str | None = None,
        status: str | None = None,
        scope: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StrategyFragment]:
        stmt = select(StrategyFragment)
        if agent_profile_id is not None:
            stmt = stmt.where(StrategyFragment.agent_profile_id == agent_profile_id)
        if status is not None:
            stmt = stmt.where(StrategyFragment.status == status)
        if scope is not None:
            stmt = stmt.where(StrategyFragment.scope == scope)
        stmt = stmt.order_by(StrategyFragment.updated_at.desc(), StrategyFragment.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())


class ExecutionGraphProjectionRepository(BaseRepository[ExecutionGraphProjection]):
    model = ExecutionGraphProjection

    def by_run(self, run_id: str) -> ExecutionGraphProjection | None:
        stmt = (
            select(ExecutionGraphProjection)
            .where(ExecutionGraphProjection.run_id == run_id)
            .order_by(ExecutionGraphProjection.created_at.desc(), ExecutionGraphProjection.id.desc())
        )
        return self.session.scalars(stmt).first()

    def list_recent(
        self,
        *,
        goal_spec_id: str | None = None,
        candidate_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExecutionGraphProjection]:
        stmt = select(ExecutionGraphProjection)
        if goal_spec_id is not None:
            stmt = stmt.where(ExecutionGraphProjection.goal_spec_id == goal_spec_id)
        if candidate_id is not None:
            stmt = stmt.where(ExecutionGraphProjection.candidate_id == candidate_id)
        stmt = stmt.order_by(ExecutionGraphProjection.created_at.desc(), ExecutionGraphProjection.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())


class OperatorInteractionRepository(BaseRepository[OperatorInteraction]):
    model = OperatorInteraction

    def open_for_approval(self, approval_id: str) -> OperatorInteraction | None:
        stmt = (
            select(OperatorInteraction)
            .where(
                OperatorInteraction.approval_id == approval_id,
                OperatorInteraction.status == "pending",
            )
            .order_by(OperatorInteraction.created_at.desc(), OperatorInteraction.id.desc())
        )
        return self.session.scalars(stmt).first()

    def list_recent(
        self,
        *,
        session_id: str | None = None,
        person_id: str | None = None,
        application_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[OperatorInteraction]:
        stmt = select(OperatorInteraction)
        if session_id is not None:
            stmt = stmt.where(OperatorInteraction.session_id == session_id)
        if person_id is not None:
            stmt = stmt.where(OperatorInteraction.person_id == person_id)
        if application_id is not None:
            stmt = stmt.where(OperatorInteraction.application_id == application_id)
        if status is not None:
            stmt = stmt.where(OperatorInteraction.status == status)
        stmt = stmt.order_by(OperatorInteraction.surfaced_at.desc(), OperatorInteraction.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())

    def list_recent_for_application(
        self,
        *,
        application_ids: list[str] | set[str] | tuple[str, ...],
        approval_ids: list[str] | set[str] | tuple[str, ...] | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[OperatorInteraction]:
        normalized_application_ids = [str(item).strip() for item in application_ids if str(item).strip()]
        normalized_approval_ids = [str(item).strip() for item in (approval_ids or []) if str(item).strip()]
        conditions = []
        if normalized_application_ids:
            conditions.append(OperatorInteraction.application_id.in_(normalized_application_ids))
        if normalized_approval_ids:
            conditions.append(OperatorInteraction.approval_id.in_(normalized_approval_ids))
        if not conditions:
            return []
        stmt = select(OperatorInteraction).where(or_(*conditions))
        if status is not None:
            stmt = stmt.where(OperatorInteraction.status == status)
        stmt = stmt.order_by(OperatorInteraction.surfaced_at.desc(), OperatorInteraction.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())


class TaskSpecRepository(BaseRepository[TaskSpec]):
    model = TaskSpec

    def by_task_key(self, task_key: str) -> TaskSpec | None:
        normalized = task_key.strip().lower()
        for item in self.list(limit=5000, offset=0):
            compiled_payload = dict(item.compiled_payload or {})
            candidate_key = str(compiled_payload.get("task_key") or item.title).strip().lower()
            if candidate_key == normalized:
                return item
        return None

    def by_domain(self, domain: str, limit: int = 100, offset: int = 0) -> list[TaskSpec]:
        stmt = (
            select(TaskSpec)
            .where(TaskSpec.domain == domain)
            .order_by(TaskSpec.updated_at.desc(), TaskSpec.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def list_by_status(self, status: str, limit: int = 100, offset: int = 0) -> list[TaskSpec]:
        stmt = (
            select(TaskSpec)
            .where(TaskSpec.status == status)
            .order_by(TaskSpec.updated_at.desc(), TaskSpec.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class PlaybookVersionRepository(BaseRepository[PlaybookVersion]):
    model = PlaybookVersion

    def by_template_key(self, template_key: str) -> PlaybookVersion | None:
        stmt = select(PlaybookVersion).where(PlaybookVersion.template_key == template_key)
        return self.session.scalars(stmt).first()

    def active(self, limit: int = 100, offset: int = 0) -> list[PlaybookVersion]:
        stmt = (
            select(PlaybookVersion)
            .where(PlaybookVersion.status == "active")
            .order_by(PlaybookVersion.updated_at.desc(), PlaybookVersion.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class ExecutionPlanRepository(BaseRepository[ExecutionPlan]):
    model = ExecutionPlan

    def by_task_spec(self, task_spec_id: str, limit: int = 100, offset: int = 0) -> list[ExecutionPlan]:
        stmt = (
            select(ExecutionPlan)
            .where(ExecutionPlan.task_spec_id == task_spec_id)
            .order_by(ExecutionPlan.updated_at.desc(), ExecutionPlan.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def for_task_spec(self, task_spec_id: str, limit: int = 20) -> list[ExecutionPlan]:
        return self.by_task_spec(task_spec_id, limit=limit, offset=0)

    def active(self, limit: int = 100, offset: int = 0) -> list[ExecutionPlan]:
        stmt = (
            select(ExecutionPlan)
            .where(ExecutionPlan.status.in_(("planned", "running", "blocked")))
            .order_by(ExecutionPlan.updated_at.desc(), ExecutionPlan.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class ExecutionEpisodeRepository(BaseRepository[ExecutionEpisode]):
    model = ExecutionEpisode

    def by_plan(self, execution_plan_id: str, limit: int = 100, offset: int = 0) -> list[ExecutionEpisode]:
        stmt = (
            select(ExecutionEpisode)
            .where(ExecutionEpisode.execution_plan_id == execution_plan_id)
            .order_by(ExecutionEpisode.created_at.desc(), ExecutionEpisode.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def for_plan(self, execution_plan_id: str, limit: int = 50) -> list[ExecutionEpisode]:
        return self.by_plan(execution_plan_id, limit=limit, offset=0)

    def latest_for_task_spec(self, task_spec_id: str) -> ExecutionEpisode | None:
        stmt = (
            select(ExecutionEpisode)
            .where(ExecutionEpisode.task_spec_id == task_spec_id)
            .order_by(ExecutionEpisode.created_at.desc(), ExecutionEpisode.id.desc())
        )
        return self.session.scalars(stmt).first()

    def recover_running(self, *, reason: str = "Recovered after local runtime restart.") -> int:
        stmt = select(ExecutionEpisode).where(ExecutionEpisode.status == "running")
        recovered = 0
        for episode in self.session.scalars(stmt).all():
            episode.status = "interrupted"
            episode.finished_at = utcnow()
            episode.last_error = reason
            runtime_metadata = dict(episode.runtime_metadata or {})
            recovery_history = list(runtime_metadata.get("recovery_history") or [])
            recovery_history.append({"at": utcnow().isoformat(), "reason": reason, "status": "interrupted"})
            runtime_metadata["recovery_history"] = recovery_history[-10:]
            episode.runtime_metadata = runtime_metadata
            recovered += 1
        if recovered:
            self.session.commit()
        return recovered


class EnvironmentSnapshotRepository(BaseRepository[EnvironmentSnapshot]):
    model = EnvironmentSnapshot

    def for_episode(self, execution_episode_id: str, limit: int = 100, offset: int = 0) -> list[EnvironmentSnapshot]:
        stmt = (
            select(EnvironmentSnapshot)
            .where(EnvironmentSnapshot.execution_episode_id == execution_episode_id)
            .order_by(EnvironmentSnapshot.created_at.asc(), EnvironmentSnapshot.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def latest_for_episode(self, execution_episode_id: str) -> EnvironmentSnapshot | None:
        stmt = (
            select(EnvironmentSnapshot)
            .where(EnvironmentSnapshot.execution_episode_id == execution_episode_id)
            .order_by(EnvironmentSnapshot.created_at.desc(), EnvironmentSnapshot.id.desc())
        )
        return self.session.scalars(stmt).first()


class PlaybookPatchRepository(BaseRepository[PlaybookPatch]):
    model = PlaybookPatch

    def pending_review(self, limit: int = 100, offset: int = 0) -> list[PlaybookPatch]:
        stmt = (
            select(PlaybookPatch)
            .where(PlaybookPatch.status == "pending_review")
            .order_by(PlaybookPatch.created_at.asc(), PlaybookPatch.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def for_template(self, playbook_version_id: str, limit: int = 50) -> list[PlaybookPatch]:
        stmt = (
            select(PlaybookPatch)
            .where(PlaybookPatch.template_id == playbook_version_id)
            .order_by(PlaybookPatch.created_at.desc(), PlaybookPatch.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def mark_review(
        self,
        patch: PlaybookPatch,
        *,
        status: str,
        reviewer: str | None = None,
        reason: str | None = None,
        rationale: str | None = None,
        applied_at: Any | None = None,
    ) -> PlaybookPatch:
        patch.status = status
        patch.reviewed_by = reviewer
        patch.reviewed_at = utcnow()
        review_reason = rationale if rationale is not None else reason
        if review_reason is not None:
            if hasattr(patch, "reason"):
                patch.reason = review_reason
            elif hasattr(patch, "rationale"):
                patch.rationale = review_reason
        if applied_at is not None:
            patch.applied_at = applied_at
        self.session.commit()
        self.session.refresh(patch)
        return patch


class DecisionLogRepository(BaseRepository[DecisionLog]):
    model = DecisionLog


class SkillRepository(BaseRepository[Skill]):
    model = Skill

    def by_skill_id(self, skill_id: str) -> Skill | None:
        stmt = select(Skill).where(Skill.skill_id == skill_id)
        return self.session.scalars(stmt).first()

    def list_active(self, limit: int = 100, offset: int = 0) -> list[Skill]:
        stmt = (
            select(Skill)
            .where(Skill.status == "active")
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def active_for_stage(self, stage_key: str, *, platform: str | None = None) -> list[Skill]:
        stmt = select(Skill).where(
            Skill.status == "active",
            Skill.bound_to_stage == stage_key,
        )
        normalized_platform = str(platform or "").strip()
        if normalized_platform and normalized_platform.lower() != "site":
            variants = {normalized_platform, normalized_platform.lower(), normalized_platform.upper(), "site"}
            stmt = stmt.where(Skill.platform.in_(tuple(variants)))
        stmt = stmt.order_by(Skill.updated_at.desc(), Skill.id.asc())
        return list(self.session.scalars(stmt).all())


class AgentLearningRepository(BaseRepository[AgentLearning]):
    model = AgentLearning

    def list_active(self, limit: int = 100, offset: int = 0) -> list[AgentLearning]:
        stmt = (
            select(AgentLearning)
            .where(AgentLearning.is_active.is_(True))
            .order_by(AgentLearning.created_at.desc(), AgentLearning.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def set_active(self, learning: AgentLearning, is_active: bool) -> AgentLearning:
        learning.is_active = is_active
        learning.updated_at = utcnow()
        self.session.commit()
        self.session.refresh(learning)
        return learning


class ApprovalRepository(BaseRepository[ApprovalItem]):
    model = ApprovalItem

    def pending(self, limit: int = 100, offset: int = 0) -> list[ApprovalItem]:
        stmt = (
            select(ApprovalItem)
            .where(ApprovalItem.status == "pending")
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def mark_review(self, approval: ApprovalItem, status: str, reviewer: str | None = None, notes: str | None = None) -> ApprovalItem:
        approval.status = status
        approval.reviewed_by = reviewer
        approval.notes = notes
        approval.reviewed_at = utcnow()
        self.session.commit()
        self.session.refresh(approval)
        return approval


class TaskQueueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, task_id: str) -> TaskQueueItem | None:
        return self.session.get(TaskQueueItem, task_id)

    def _append_audit_event(self, record: TaskQueueItem, kind: str, **extra: Any) -> None:
        payload = dict(record.payload or {})
        audit = payload.get("queue_audit") if isinstance(payload.get("queue_audit"), dict) else {}
        history = list(audit.get("history") or [])
        event = {"kind": kind, "at": utcnow().isoformat(), **extra}
        history.append(event)
        audit.update(
            {
                "last_event": kind,
                "last_event_at": event["at"],
                "history": history[-20:],
            }
        )
        payload["queue_audit"] = audit
        record.payload = payload
        flag_modified(record, "payload")

    def enqueue(
        self,
        *,
        task_id: str,
        task_type: str,
        priority: int = 100,
        payload: dict[str, Any] | None = None,
        status: str = "pending",
        scheduled_for: Any | None = None,
        attempts: int = 0,
    ) -> TaskQueueItem:
        record = self.session.get(TaskQueueItem, task_id)
        task_payload = dict(payload or {})
        if record is None:
            record = TaskQueueItem(
                id=task_id,
                task_type=task_type,
                priority=priority,
                payload=task_payload,
                status=status,
                scheduled_for=scheduled_for,
                attempts=attempts,
            )
            self.session.add(record)
            self._append_audit_event(record, "enqueued", status=status, priority=priority)
        else:
            record.task_type = task_type
            record.priority = priority
            record.payload = task_payload
            record.status = status
            record.scheduled_for = scheduled_for
            record.attempts = attempts
            record.locked_at = None
            record.locked_by = None
            self._append_audit_event(record, "requeued", status=status, priority=priority, attempts=attempts)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_pending(self, limit: int = 100, offset: int = 0) -> list[TaskQueueItem]:
        stmt = (
            select(TaskQueueItem)
            .where(TaskQueueItem.status == "pending")
            .order_by(TaskQueueItem.priority.desc(), TaskQueueItem.created_at.asc(), TaskQueueItem.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def list(self, *, status: str | None = None, limit: int = 100, offset: int = 0) -> list[TaskQueueItem]:
        stmt = select(TaskQueueItem)
        if status is not None:
            stmt = stmt.where(TaskQueueItem.status == status)
        stmt = (
            stmt.order_by(
                TaskQueueItem.priority.desc(),
                TaskQueueItem.created_at.asc(),
                TaskQueueItem.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def pending_count(self) -> int:
        return self.session.scalar(
            select(func.count()).select_from(TaskQueueItem).where(TaskQueueItem.status == "pending")
        ) or 0

    def counts_by_status(self) -> dict[str, int]:
        stmt = select(TaskQueueItem.status, func.count()).group_by(TaskQueueItem.status)
        return {str(status): int(count or 0) for status, count in self.session.execute(stmt).all()}

    def has_open_task_types(
        self,
        task_types: list[str],
        *,
        statuses: tuple[str, ...] = ("pending", "running"),
    ) -> bool:
        normalized_types = [task_type for task_type in task_types if task_type]
        if not normalized_types:
            return False
        stmt = (
            select(TaskQueueItem.id)
            .where(
                TaskQueueItem.task_type.in_(normalized_types),
                TaskQueueItem.status.in_(statuses),
            )
            .limit(1)
        )
        return self.session.scalar(stmt) is not None

    def open_subject_ids_for_task_types(
        self,
        task_types: list[str],
        *,
        statuses: tuple[str, ...] = ("pending", "running"),
    ) -> set[str]:
        normalized_types = [task_type for task_type in task_types if task_type]
        if not normalized_types:
            return set()
        stmt = select(TaskQueueItem.payload).where(
            TaskQueueItem.task_type.in_(normalized_types),
            TaskQueueItem.status.in_(statuses),
        )
        subject_ids: set[str] = set()
        for payload in self.session.scalars(stmt).all():
            envelope = dict(payload or {})
            subject_id = str(envelope.get("application_id") or envelope.get("person_id") or "").strip()
            if subject_id:
                subject_ids.add(subject_id)
        return subject_ids

    def claim_next(self, *, locked_by: str = "scheduler") -> TaskQueueItem | None:
        now = utcnow()
        stmt = (
            select(TaskQueueItem)
            .where(
                TaskQueueItem.status == "pending",
                or_(TaskQueueItem.scheduled_for.is_(None), TaskQueueItem.scheduled_for <= now),
            )
            .order_by(TaskQueueItem.priority.desc(), TaskQueueItem.created_at.asc(), TaskQueueItem.id.asc())
        )
        record = self.session.scalars(stmt).first()
        if record is None:
            return None
        record.status = "running"
        record.locked_at = utcnow()
        record.locked_by = locked_by
        self._append_audit_event(record, "claimed", locked_by=locked_by, attempts=record.attempts)
        self.session.commit()
        self.session.refresh(record)
        return record

    def mark_pending(self, task_id: str, *, attempts: int | None = None, error: str | None = None) -> TaskQueueItem | None:
        record = self.session.get(TaskQueueItem, task_id)
        if record is None:
            return None
        record.status = "pending"
        record.locked_at = None
        record.locked_by = None
        if attempts is not None:
            record.attempts = attempts
        self._append_audit_event(record, "returned_to_queue", attempts=record.attempts, error=error)
        self.session.commit()
        self.session.refresh(record)
        return record

    def mark_complete(self, task_id: str) -> TaskQueueItem | None:
        record = self.session.get(TaskQueueItem, task_id)
        if record is None:
            return None
        record.status = "completed"
        record.locked_at = None
        record.locked_by = None
        self._append_audit_event(record, "completed", attempts=record.attempts)
        self.session.commit()
        self.session.refresh(record)
        return record

    def mark_failed(self, task_id: str, *, error: str | None = None) -> TaskQueueItem | None:
        record = self.session.get(TaskQueueItem, task_id)
        if record is None:
            return None
        record.status = "failed"
        record.locked_at = None
        record.locked_by = None
        self._append_audit_event(record, "failed", attempts=record.attempts, error=error)
        self.session.commit()
        self.session.refresh(record)
        return record

    def recover_stale_running(self, *, locked_before: Any | None = None) -> int:
        stmt = select(TaskQueueItem).where(TaskQueueItem.status == "running")
        if locked_before is not None:
            stmt = stmt.where(
                or_(
                    TaskQueueItem.locked_at.is_(None),
                    TaskQueueItem.locked_at <= locked_before,
                )
            )

        recovered = 0
        for record in self.session.scalars(stmt).all():
            record.status = "pending"
            record.locked_at = None
            record.locked_by = None
            self._append_audit_event(record, "recovered_stale", attempts=record.attempts)
            recovered += 1

        if recovered:
            self.session.commit()
        return recovered


class SettingsRepository:
    singleton_id = "singleton"

    def __init__(self, session: Session) -> None:
        self.session = session

    def load(self, defaults: AppSettings) -> AppSettingsRead:
        record = self.session.get(AppSetting, self.singleton_id)
        if record is None or not record.payload:
            return AppSettingsRead.model_validate(defaults.model_dump())

        data = defaults.model_dump()
        _deep_merge(data, record.payload)
        return AppSettingsRead.model_validate(data)

    def save(self, settings: AppSettingsRead | BaseModel | dict[str, Any]) -> AppSettingsRead:
        payload = settings.model_dump() if isinstance(settings, BaseModel) else dict(settings)
        record = self.session.get(AppSetting, self.singleton_id)
        if record is None:
            record = AppSetting(id=self.singleton_id, payload=payload)
            self.session.add(record)
        else:
            record.payload = payload
        self.session.commit()
        return AppSettingsRead.model_validate(payload)


class RecruitmentStateMachineVersionRepository(BaseRepository[RecruitmentStateMachineVersion]):
    model = RecruitmentStateMachineVersion

    def latest(self) -> RecruitmentStateMachineVersion | None:
        stmt = (
            select(RecruitmentStateMachineVersion)
            .order_by(RecruitmentStateMachineVersion.version.desc())
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def get_version(self, version: int) -> RecruitmentStateMachineVersion | None:
        return self.session.get(RecruitmentStateMachineVersion, version)

    def list_versions(self, *, limit: int = 50) -> list[RecruitmentStateMachineVersion]:
        stmt = (
            select(RecruitmentStateMachineVersion)
            .order_by(RecruitmentStateMachineVersion.version.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class SyncBacklogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, *, status: str | None = None, limit: int = 100, offset: int = 0) -> list[Any]:
        stmt = select(SyncBacklogEntry)
        if status is not None:
            stmt = stmt.where(SyncBacklogEntry.status == status)
        stmt = (
            stmt.order_by(SyncBacklogEntry.created_at.desc(), SyncBacklogEntry.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def enqueue(
        self,
        item_type: str,
        item_id: str,
        payload: dict[str, Any],
        *,
        protocol_version: str = "v1",
        destination: str = "intranet",
    ) -> Any:
        stmt = select(SyncBacklogEntry).where(
            SyncBacklogEntry.item_type == item_type,
            SyncBacklogEntry.item_id == item_id,
        )
        record = self.session.scalars(stmt).first()
        if record is None:
            record = SyncBacklogEntry(
                item_type=item_type,
                item_id=item_id,
                payload=dict(payload),
                status="pending",
                protocol_version=protocol_version,
                destination=destination,
            )
            self.session.add(record)
        else:
            record.payload = dict(payload)
            record.status = "pending"
            record.protocol_version = protocol_version
            record.destination = destination
            record.attempt_count = 0
            record.last_attempted_at = None
            record.last_error = None
            record.synced_at = None
        self.session.commit()
        self.session.refresh(record)
        return record

    def pending(self, limit: int = 100, offset: int = 0) -> list[Any]:
        stmt = (
            select(SyncBacklogEntry)
            .where(SyncBacklogEntry.status == "pending")
            .order_by(SyncBacklogEntry.created_at.asc(), SyncBacklogEntry.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def pending_count(self) -> int:
        return self.session.scalar(
            select(func.count()).select_from(SyncBacklogEntry).where(SyncBacklogEntry.status == "pending")
        ) or 0

    def counts_by_status(self) -> dict[str, int]:
        rows = self.session.execute(
            select(SyncBacklogEntry.status, func.count()).group_by(SyncBacklogEntry.status)
        ).all()
        return {str(status): int(count) for status, count in rows}

    def delivery_error_count(self) -> int:
        return self.session.scalar(
            select(func.count()).select_from(SyncBacklogEntry).where(SyncBacklogEntry.last_error.is_not(None))
        ) or 0

    def latest_delivery_error(self) -> str | None:
        stmt = (
            select(SyncBacklogEntry.last_error)
            .where(SyncBacklogEntry.last_error.is_not(None))
            .order_by(SyncBacklogEntry.updated_at.desc(), SyncBacklogEntry.id.desc())
        )
        value = self.session.execute(stmt).scalar()
        return str(value) if value is not None else None

    def mark_synced(self, item_id: str, item_type: str | None = None) -> Any | None:
        stmt = select(SyncBacklogEntry).where(SyncBacklogEntry.item_id == item_id)
        if item_type is not None:
            stmt = stmt.where(SyncBacklogEntry.item_type == item_type)
        record = self.session.scalars(stmt).first()
        if record is None:
            return None
        payload = dict(record.payload or {})
        delivery = payload.get("delivery") if isinstance(payload.get("delivery"), dict) else {}
        delivery.update(
            {
                "last_error": None,
                "next_attempt_at": None,
            }
        )
        payload["delivery"] = delivery
        record.payload = payload
        flag_modified(record, "payload")
        record.status = "synced"
        record.last_error = None
        record.synced_at = utcnow()
        self.session.commit()
        self.session.refresh(record)
        return record

    def mark_attempt(
        self,
        item_id: str,
        *,
        item_type: str | None = None,
        error: str | None = None,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any | None:
        stmt = select(SyncBacklogEntry).where(SyncBacklogEntry.item_id == item_id)
        if item_type is not None:
            stmt = stmt.where(SyncBacklogEntry.item_type == item_type)
        record = self.session.scalars(stmt).first()
        if record is None:
            return None
        record.attempt_count = int(record.attempt_count or 0) + 1
        record.last_attempted_at = utcnow()
        record.last_error = error
        record.status = status or ("failed" if error else "pending")
        if payload is not None:
            record.payload = dict(payload)
            flag_modified(record, "payload")
        self.session.commit()
        self.session.refresh(record)
        return record

    def update_payload(self, item_id: str, item_type: str, payload: dict[str, Any]) -> Any | None:
        stmt = select(SyncBacklogEntry).where(
            SyncBacklogEntry.item_id == item_id,
            SyncBacklogEntry.item_type == item_type,
        )
        record = self.session.scalars(stmt).first()
        if record is None:
            return None
        record.payload = dict(payload)
        flag_modified(record, "payload")
        self.session.commit()
        self.session.refresh(record)
        return record


class MetricsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def summary(self) -> MetricsSummary:
        candidate_count = self.session.scalar(select(func.count()).select_from(CandidateApplication)) or 0
        playbook_count = self.session.scalar(select(func.count()).select_from(Playbook)) or 0
        skill_count = self.session.scalar(select(func.count()).select_from(Skill)) or 0
        approval_count = self.session.scalar(select(func.count()).select_from(ApprovalItem)) or 0
        pending_approval_count = self.session.scalar(
            select(func.count()).select_from(ApprovalItem).where(ApprovalItem.status == "pending")
        ) or 0
        active_skill_count = self.session.scalar(
            select(func.count()).select_from(Skill).where(Skill.status == "active")
        ) or 0
        by_status = {
            status: count
            for status, count in self.session.execute(
                select(CandidateApplication.current_status, func.count()).group_by(CandidateApplication.current_status)
            ).all()
        }
        return MetricsSummary(
            candidate_count=candidate_count,
            playbook_count=playbook_count,
            skill_count=skill_count,
            approval_count=approval_count,
            pending_approval_count=pending_approval_count,
            active_skill_count=active_skill_count,
            by_status=by_status,
        )
