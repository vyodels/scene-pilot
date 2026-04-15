from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.base import utcnow
from scene_pilot.models import (
    AgentLearning,
    AgentGlobalMemory,
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
    CandidateAssessment,
    CandidateAssignment,
    CandidateMemory,
    CandidateReviewDecision,
    CandidateScorecard,
    CandidateSession,
    CandidateStageEvent,
    CommunicationLog,
    DecisionLog,
    EnvironmentSnapshot,
    EvolutionArtifact,
    ExecutionEpisode,
    ExecutionPlan,
    JobMemory,
    McpServer,
    McpTool,
    RecruitAgentProfile,
    ResumeArtifact,
    Skill,
    StrategyFragment,
    SyncBacklogEntry,
    TaskSpec,
    TaskQueueItem,
    TalentPoolSyncRecord,
    Workflow,
    WorkflowPatch,
    WorkflowTemplate,
    WorkflowRun,
)
from scene_pilot.schemas import AppSettingsRead, MetricsSummary

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


class WorkflowRepository(BaseRepository[Workflow]):
    model = Workflow

    def active(self) -> list[Workflow]:
        stmt = select(Workflow).where(Workflow.status == "active").order_by(Workflow.updated_at.desc(), Workflow.id.asc())
        return list(self.session.scalars(stmt).all())


class CandidateRepository(BaseRepository[Candidate]):
    model = Candidate

    def by_platform_candidate_id(self, platform: str, platform_candidate_id: str) -> Candidate | None:
        stmt = select(Candidate).where(
            Candidate.platform == platform,
            Candidate.platform_candidate_id == platform_candidate_id,
        )
        return self.session.scalars(stmt).first()

    def count_by_status(self) -> dict[str, int]:
        stmt = select(Candidate.status, func.count()).group_by(Candidate.status)
        return {status: count for status, count in self.session.execute(stmt).all()}

    def resolve(self, candidate_id: str) -> Candidate | None:
        candidate = self.get(candidate_id)
        if candidate is not None:
            return candidate
        stmt = select(Candidate).where(Candidate.platform_candidate_id == candidate_id)
        return self.session.scalars(stmt).first()

    def update_state_snapshot(self, candidate: Candidate, *, status: str | None = None, snapshot: dict[str, Any] | None = None) -> Candidate:
        if status is not None:
            candidate.status = status
        if snapshot is not None:
            candidate.state_snapshot = snapshot
        candidate.updated_at = utcnow()
        self.session.commit()
        self.session.refresh(candidate)
        return candidate


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


class CandidateStageEventRepository(BaseRepository[CandidateStageEvent]):
    model = CandidateStageEvent

    def by_candidate(self, candidate_id: str, limit: int = 200, offset: int = 0) -> list[CandidateStageEvent]:
        stmt = (
            select(CandidateStageEvent)
            .where(CandidateStageEvent.candidate_id == candidate_id)
            .order_by(CandidateStageEvent.occurred_at.asc(), CandidateStageEvent.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def latest_for_candidate(self, candidate_id: str) -> CandidateStageEvent | None:
        stmt = (
            select(CandidateStageEvent)
            .where(CandidateStageEvent.candidate_id == candidate_id)
            .order_by(CandidateStageEvent.occurred_at.desc(), CandidateStageEvent.id.desc())
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

    def by_candidate(self, candidate_id: str, limit: int = 50, offset: int = 0) -> list[ResumeArtifact]:
        stmt = (
            select(ResumeArtifact)
            .where(ResumeArtifact.candidate_id == candidate_id)
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


class WorkflowRunRepository(BaseRepository[WorkflowRun]):
    model = WorkflowRun

    def active_for_candidate(self, workflow_id: str, candidate_id: str | None) -> WorkflowRun | None:
        stmt = (
            select(WorkflowRun)
            .where(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.candidate_id == candidate_id,
                WorkflowRun.status.in_(("running", "blocked")),
            )
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
        )
        return self.session.scalars(stmt).first()


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


class CandidateMemoryRepository(BaseRepository[CandidateMemory]):
    model = CandidateMemory

    def by_agent_and_candidate(self, *, agent_profile_id: str, candidate_id: str) -> CandidateMemory | None:
        stmt = select(CandidateMemory).where(
            CandidateMemory.agent_profile_id == agent_profile_id,
            CandidateMemory.candidate_id == candidate_id,
        )
        return self.session.scalars(stmt).first()

    def list_for_agent(self, agent_profile_id: str, limit: int = 100, offset: int = 0) -> list[CandidateMemory]:
        stmt = (
            select(CandidateMemory)
            .where(CandidateMemory.agent_profile_id == agent_profile_id)
            .order_by(CandidateMemory.updated_at.desc(), CandidateMemory.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class JobMemoryRepository(BaseRepository[JobMemory]):
    model = JobMemory

    def by_agent_and_jd(self, *, agent_profile_id: str, jd_id: str) -> JobMemory | None:
        stmt = select(JobMemory).where(
            JobMemory.agent_profile_id == agent_profile_id,
            JobMemory.jd_id == jd_id,
        )
        return self.session.scalars(stmt).first()

    def list_for_agent(self, agent_profile_id: str, limit: int = 100, offset: int = 0) -> list[JobMemory]:
        stmt = (
            select(JobMemory)
            .where(JobMemory.agent_profile_id == agent_profile_id)
            .order_by(JobMemory.updated_at.desc(), JobMemory.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class AgentGlobalMemoryRepository(BaseRepository[AgentGlobalMemory]):
    model = AgentGlobalMemory

    def by_agent(self, agent_profile_id: str) -> AgentGlobalMemory | None:
        stmt = select(AgentGlobalMemory).where(AgentGlobalMemory.agent_profile_id == agent_profile_id)
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
        candidate_id: str | None = None,
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
        if candidate_id is not None:
            stmt = stmt.where(AgentRun.candidate_id == candidate_id)
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

    def latest_open_for_candidate(
        self,
        *,
        session_id: str,
        candidate_id: str,
        lane: str = "candidate",
    ) -> AgentRun | None:
        stmt = (
            select(AgentRun)
            .where(
                AgentRun.session_id == session_id,
                AgentRun.candidate_id == candidate_id,
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

    def conflicting_candidate_run(
        self,
        *,
        session_id: str,
        candidate_id: str,
        exclude_run_id: str | None = None,
    ) -> AgentRun | None:
        stmt = (
            select(AgentRun)
            .where(
                AgentRun.session_id == session_id,
                AgentRun.candidate_id == candidate_id,
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
        candidate_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentWorkItem]:
        stmt = select(AgentWorkItem)
        if run_id is not None:
            stmt = stmt.where(AgentWorkItem.run_id == run_id)
        if status is not None:
            stmt = stmt.where(AgentWorkItem.status == status)
        if candidate_id is not None:
            stmt = stmt.where(AgentWorkItem.candidate_id == candidate_id)
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
        candidate_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[OperatorInteraction]:
        stmt = select(OperatorInteraction)
        if session_id is not None:
            stmt = stmt.where(OperatorInteraction.session_id == session_id)
        if candidate_id is not None:
            stmt = stmt.where(OperatorInteraction.candidate_id == candidate_id)
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


class WorkflowTemplateRepository(BaseRepository[WorkflowTemplate]):
    model = WorkflowTemplate

    def by_template_key(self, template_key: str) -> WorkflowTemplate | None:
        stmt = select(WorkflowTemplate).where(WorkflowTemplate.template_key == template_key)
        return self.session.scalars(stmt).first()

    def active(self, limit: int = 100, offset: int = 0) -> list[WorkflowTemplate]:
        stmt = (
            select(WorkflowTemplate)
            .where(WorkflowTemplate.status == "active")
            .order_by(WorkflowTemplate.updated_at.desc(), WorkflowTemplate.id.asc())
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


class WorkflowPatchRepository(BaseRepository[WorkflowPatch]):
    model = WorkflowPatch

    def pending_review(self, limit: int = 100, offset: int = 0) -> list[WorkflowPatch]:
        stmt = (
            select(WorkflowPatch)
            .where(WorkflowPatch.status == "pending_review")
            .order_by(WorkflowPatch.created_at.asc(), WorkflowPatch.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def for_template(self, workflow_template_id: str, limit: int = 50) -> list[WorkflowPatch]:
        stmt = (
            select(WorkflowPatch)
            .where(WorkflowPatch.template_id == workflow_template_id)
            .order_by(WorkflowPatch.created_at.desc(), WorkflowPatch.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def mark_review(
        self,
        patch: WorkflowPatch,
        *,
        status: str,
        reviewer: str | None = None,
        reason: str | None = None,
        rationale: str | None = None,
        applied_at: Any | None = None,
    ) -> WorkflowPatch:
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
        candidate_count = self.session.scalar(select(func.count()).select_from(Candidate)) or 0
        workflow_count = self.session.scalar(select(func.count()).select_from(Workflow)) or 0
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
                select(Candidate.status, func.count()).group_by(Candidate.status)
            ).all()
        }
        return MetricsSummary(
            candidate_count=candidate_count,
            workflow_count=workflow_count,
            skill_count=skill_count,
            approval_count=approval_count,
            pending_approval_count=pending_approval_count,
            active_skill_count=active_skill_count,
            by_status=by_status,
        )
