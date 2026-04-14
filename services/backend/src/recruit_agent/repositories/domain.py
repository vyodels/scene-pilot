from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.base import utcnow
from recruit_agent.models import (
    AgentLearning,
    ApprovalItem,
    AppSetting,
    Candidate,
    CandidateSession,
    CommunicationLog,
    DecisionLog,
    EnvironmentSnapshot,
    ExecutionEpisode,
    ExecutionPlan,
    Skill,
    SyncBacklogEntry,
    TaskSpec,
    TaskQueueItem,
    Workflow,
    WorkflowPatch,
    WorkflowTemplate,
    WorkflowRun,
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

    def active_for_node(self, workflow_node_id: str, *, platform: str | None = None) -> list[Skill]:
        stmt = select(Skill).where(
            Skill.status == "active",
            Skill.bound_to_workflow_node == workflow_node_id,
        )
        if platform:
            stmt = stmt.where(Skill.platform.in_((platform, platform.lower(), platform.upper(), "boss", "Boss直聘")))
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
        else:
            record.task_type = task_type
            record.priority = priority
            record.payload = task_payload
            record.status = status
            record.scheduled_for = scheduled_for
            record.attempts = attempts
            record.locked_at = None
            record.locked_by = None
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

    def pending_count(self) -> int:
        return self.session.scalar(
            select(func.count()).select_from(TaskQueueItem).where(TaskQueueItem.status == "pending")
        ) or 0

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
        self.session.commit()
        self.session.refresh(record)
        return record

    def mark_pending(self, task_id: str, *, attempts: int | None = None) -> TaskQueueItem | None:
        record = self.session.get(TaskQueueItem, task_id)
        if record is None:
            return None
        record.status = "pending"
        record.locked_at = None
        record.locked_by = None
        if attempts is not None:
            record.attempts = attempts
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
        self.session.commit()
        self.session.refresh(record)
        return record

    def mark_failed(self, task_id: str) -> TaskQueueItem | None:
        record = self.session.get(TaskQueueItem, task_id)
        if record is None:
            return None
        record.status = "failed"
        record.locked_at = None
        record.locked_by = None
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

    def mark_synced(self, item_id: str, item_type: str | None = None) -> Any | None:
        stmt = select(SyncBacklogEntry).where(SyncBacklogEntry.item_id == item_id)
        if item_type is not None:
            stmt = stmt.where(SyncBacklogEntry.item_type == item_type)
        record = self.session.scalars(stmt).first()
        if record is None:
            return None
        record.status = "synced"
        record.synced_at = utcnow()
        self.session.commit()
        self.session.refresh(record)
        return record

    def mark_attempt(self, item_id: str, *, item_type: str | None = None, error: str | None = None) -> Any | None:
        stmt = select(SyncBacklogEntry).where(SyncBacklogEntry.item_id == item_id)
        if item_type is not None:
            stmt = stmt.where(SyncBacklogEntry.item_type == item_type)
        record = self.session.scalars(stmt).first()
        if record is None:
            return None
        record.attempt_count = int(record.attempt_count or 0) + 1
        record.last_attempted_at = utcnow()
        record.last_error = error
        record.status = "failed" if error else "pending"
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
