from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.db.base import utcnow
from recruit_agent.models import AgentLearning, ApprovalItem
from recruit_agent.repositories import (
    AgentLearningRepository,
    ApprovalRepository,
    CandidateRepository,
    CandidateSessionRepository,
    CommunicationLogRepository,
    DecisionLogRepository,
    SkillRepository,
    WorkflowRunRepository,
)
from recruit_agent.runtime.agent_loop import AgentLoop
from recruit_agent.runtime.models import AgentResult
from recruit_agent.runtime.result_semantics import extract_business_status
from recruit_agent.scheduler.queue import TaskEnvelope
from recruit_agent.scheduler.scheduler import ScheduledOutcome, SerialScheduler
from recruit_agent.platforms import PlatformAdapter
from recruit_agent.services.events import EventStreamService
from recruit_agent.services.feature_flags import FeatureFlagService
from recruit_agent.services.skills import SkillHealthCheckService
from recruit_agent.services.sync import SyncService
from recruit_agent.workflows.definitions import WorkflowDefinition, WorkflowNode
from recruit_agent.workflows.engine import WorkflowEngine


@dataclass(slots=True)
class AgentControlService:
    scheduler: SerialScheduler
    workflow_engine: WorkflowEngine
    agent_loop: AgentLoop | None = None
    events: EventStreamService = field(default_factory=EventStreamService)
    flags: FeatureFlagService = field(default_factory=FeatureFlagService)
    platform_adapter: PlatformAdapter | None = None
    sync_service: SyncService | None = None
    session_factory: sessionmaker[Session] | None = None

    def enqueue_task(
        self,
        task_type: str,
        *,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        candidate_id: str | None = None,
        workflow_id: str | None = None,
        workflow_node_id: str | None = None,
    ) -> TaskEnvelope:
        task = TaskEnvelope(
            task_id=task_id or uuid4().hex,
            task_type=task_type,
            payload=payload or {},
            priority=priority,
            candidate_id=candidate_id,
            workflow_id=workflow_id,
            workflow_node_id=workflow_node_id or task_type,
            metadata=metadata or {},
        )
        self.scheduler.submit(task)
        self.events.publish("info", "scheduler", f"Queued task {task.task_type}", task_id=task.task_id)
        return task

    def run_once(self) -> ScheduledOutcome | None:
        outcome = self.scheduler.run_once()
        if outcome is None:
            self.events.publish("info", "scheduler", "Run loop was idle.")
            return None
        level = "info" if outcome.result.success else "warning"
        self.events.publish(level, "runtime", f"Task {outcome.task.task_type} finished with {outcome.result.status}")
        return outcome

    def apply_approval_resolution(
        self,
        session: Session,
        approval: ApprovalItem,
        *,
        status: str,
        reviewer: str,
        notes: str | None,
    ) -> ApprovalItem:
        payload = dict(approval.payload or {})
        resolution = {
            "status": status,
            "reviewed_by": reviewer,
            "reason": notes,
            "resumed": False,
            "resolved_at": utcnow().isoformat(),
        }

        if approval.target_type == "blocked_task":
            resumed = False
            if status == "approved":
                snapshot = payload.get("resume_task") or payload.get("blocked_task")
                if isinstance(snapshot, dict):
                    resumed = self._enqueue_task_snapshot(snapshot)
            resolution["resumed"] = resumed
            payload["closed_at"] = utcnow().isoformat()
            self._apply_blocked_session_resolution(session, approval, status=status, notes=notes)

        payload["resolution"] = resolution
        approval.payload = payload
        return approval

    def build_runner(self):
        def _run(task: TaskEnvelope) -> AgentResult:
            workflow = self.workflow_engine.resolve_workflow(task)
            workflow_node = self.workflow_engine.resolve_node(task, workflow=workflow)
            runtime_session = self._build_runtime_session(task, workflow=workflow, workflow_node=workflow_node)
            runtime_skill = self._build_skill_context(task, workflow_node=workflow_node)
            platform_context = self._build_platform_context(task)
            workflow_run_id = self._start_workflow_run(
                task,
                workflow=workflow,
                workflow_node=workflow_node,
                session_context=runtime_session,
                skill_context=runtime_skill,
                platform_context=platform_context,
            )

            if task.task_type == "discover_candidate" and self.platform_adapter is not None:
                discovered = self.platform_adapter.discover_candidates(task.payload)
                result = AgentResult(
                    success=True,
                    status="completed",
                    content=f"Discovered {len(discovered)} candidates in the current runtime scene.",
                    data={
                        "status": "pass",
                        "discovered_count": len(discovered),
                        "candidates": [candidate.raw for candidate in discovered],
                    },
                    metadata={"platform_action": "discover_candidates"},
                )
                self._persist_task_artifacts(
                    task,
                    result,
                    workflow=workflow,
                    workflow_node=workflow_node,
                    workflow_run_id=workflow_run_id,
                    session_context=runtime_session,
                    skill_context=runtime_skill,
                )
                return result

            if task.task_type == "request_resume" and self.platform_adapter is not None and task.candidate_id:
                platform_result = self.platform_adapter.request_resume(task.candidate_id)
                self._enqueue_sync("resume_request", task.candidate_id, platform_result)
                result = AgentResult(
                    success=True,
                    status="completed",
                    content="Resume request submitted in the current runtime scene.",
                    data={"status": "pass", "platform_result": platform_result},
                    metadata={"platform_action": "request_resume"},
                )
                self._persist_task_artifacts(
                    task,
                    result,
                    workflow=workflow,
                    workflow_node=workflow_node,
                    workflow_run_id=workflow_run_id,
                    session_context=runtime_session,
                    skill_context=runtime_skill,
                )
                return result

            if (
                task.task_type == "initiate_communication"
                and self.platform_adapter is not None
                and task.candidate_id
                and self.flags.is_enabled("feature.outbound_messaging")
            ):
                platform_result = self.platform_adapter.send_message(
                    task.candidate_id,
                    str(task.payload.get("message") or "Hello, we would like to continue the recruiting process."),
                )
                self._enqueue_sync("communication", task.candidate_id, platform_result)
                result = AgentResult(
                    success=True,
                    status="completed",
                    content="Outbound communication submitted in the current runtime scene.",
                    data={"status": "pass", "platform_result": platform_result},
                    metadata={"platform_action": "send_message"},
                )
                self._persist_task_artifacts(
                    task,
                    result,
                    workflow=workflow,
                    workflow_node=workflow_node,
                    workflow_run_id=workflow_run_id,
                    session_context=runtime_session,
                    skill_context=runtime_skill,
                )
                return result

            if task.task_type == "archive_candidate" and self.platform_adapter is not None and task.candidate_id:
                platform_result = self.platform_adapter.archive_candidate(
                    task.candidate_id,
                    str(task.payload.get("reason") or "Archived by workflow."),
                )
                self._enqueue_sync("candidate_archive", task.candidate_id, platform_result)
                result = AgentResult(
                    success=True,
                    status="completed",
                    content="Candidate archived in the current runtime scene.",
                    data={"status": "pass", "platform_result": platform_result},
                    metadata={"platform_action": "archive_candidate"},
                )
                self._persist_task_artifacts(
                    task,
                    result,
                    workflow=workflow,
                    workflow_node=workflow_node,
                    workflow_run_id=workflow_run_id,
                    session_context=runtime_session,
                    skill_context=runtime_skill,
                )
                return result

            if self.agent_loop is None:
                result = AgentResult(
                    success=True,
                    status="completed",
                    content="Synthetic runtime executed without a live provider.",
                    data={
                        "status": "pass",
                        "task_id": task.task_id,
                        "candidate_id": task.candidate_id,
                    },
                    metadata={"synthetic": True},
                )
                self._persist_task_artifacts(
                    task,
                    result,
                    workflow=workflow,
                    workflow_node=workflow_node,
                    workflow_run_id=workflow_run_id,
                    session_context=runtime_session,
                    skill_context=runtime_skill,
                )
                return result

            runtime_task = SimpleNamespace(
                task_type=task.task_type,
                workflow_node_id=task.workflow_node_id,
                payload=task.payload,
                max_turns=6,
                token_budget=4096,
            )
            result = self.agent_loop.run(
                runtime_task,
                session=runtime_session or None,
                skill=runtime_skill or None,
                extra_context=platform_context or None,
            )

            if (
                task.task_type == "candidate_scoring"
                and self.platform_adapter is not None
                and task.candidate_id
                and result.success
                and result.data
            ):
                platform_result = self.platform_adapter.score_candidate(task.candidate_id, result.data)
                result.metadata["platform_result"] = platform_result
                self._enqueue_sync("candidate_score", task.candidate_id, platform_result)

            if result.status == "waiting_human":
                self._persist_blocked_task_approval(task, result)
            self._persist_task_artifacts(
                task,
                result,
                workflow=workflow,
                workflow_node=workflow_node,
                workflow_run_id=workflow_run_id,
                session_context=runtime_session,
                skill_context=runtime_skill,
            )
            self._persist_runtime_learning(task, result)
            return result

        return _run

    def _build_platform_context(self, task: TaskEnvelope) -> dict[str, Any]:
        if self.platform_adapter is None or not task.candidate_id:
            return {}

        try:
            snapshot = self.platform_adapter.inspect_candidate(task.candidate_id)
        except KeyError:
            return {}

        return {
            "platform_candidate": snapshot.raw,
            "cooldown_active": self.platform_adapter.check_cooldown(task.candidate_id),
        }

    def _build_runtime_session(
        self,
        task: TaskEnvelope,
        *,
        workflow: WorkflowDefinition,
        workflow_node: WorkflowNode | None,
    ) -> dict[str, Any]:
        if self.session_factory is None or not task.candidate_id:
            return {}

        with self.session_factory() as session:
            candidate_repo = CandidateRepository(session)
            candidate = candidate_repo.resolve(task.candidate_id)
            if candidate is None:
                return {}

            session_repo = CandidateSessionRepository(session)
            candidate_session = session_repo.get_or_create(
                candidate.id,
                defaults={
                    "status": "active",
                    "context_summary": candidate.ai_reasoning or f"{candidate.name} is currently in {candidate.status}.",
                    "facts": {},
                    "recent_messages": [],
                    "last_active_at": utcnow(),
                },
            )
            candidate_session.last_active_at = utcnow()

            facts = dict(candidate_session.facts or {})
            facts.update(
                {
                    "candidate_status": candidate.status,
                    "workflow_id": workflow.workflow_id,
                    "workflow_node_id": workflow_node.node_id if workflow_node is not None else task.workflow_node_id,
                    "task_type": task.task_type,
                    "resume_available": bool(candidate.resume_path or candidate.online_resume_text),
                }
            )
            candidate_session.facts = facts
            session.commit()

            return {
                "candidate": {
                    "id": candidate.id,
                    "platform_candidate_id": candidate.platform_candidate_id,
                    "name": candidate.name,
                    "platform": candidate.platform,
                    "status": candidate.status,
                    "current_workflow_node": candidate.current_workflow_node,
                    "jd_id": candidate.jd_id,
                    "contact_info": dict(candidate.contact_info or {}),
                    "resume_path": candidate.resume_path,
                    "online_resume_text": candidate.online_resume_text,
                    "ai_scores": dict(candidate.ai_scores or {}),
                    "ai_reasoning": candidate.ai_reasoning,
                },
                "session": {
                    "id": candidate_session.id,
                    "status": candidate_session.status,
                    "context_summary": candidate_session.context_summary,
                    "recent_messages": list(candidate_session.recent_messages or []),
                    "facts": dict(candidate_session.facts or {}),
                    "suspend_reason": candidate_session.suspend_reason,
                    "last_active_at": candidate_session.last_active_at.isoformat() if candidate_session.last_active_at else None,
                },
            }

    def _build_skill_context(self, task: TaskEnvelope, *, workflow_node: WorkflowNode | None) -> dict[str, Any] | None:
        if self.session_factory is None:
            return None

        preferred_skill_id = (
            task.payload.get("skill_id")
            or task.metadata.get("skill_id")
            or (workflow_node.metadata.get("preferred_skill_id") if workflow_node is not None else None)
            or (workflow_node.metadata.get("skill_id") if workflow_node is not None else None)
        )
        workflow_node_id = workflow_node.node_id if workflow_node is not None else task.workflow_node_id

        with self.session_factory() as session:
            repo = SkillRepository(session)
            skill = None

            if isinstance(preferred_skill_id, str) and preferred_skill_id.strip():
                skill = repo.by_skill_id(preferred_skill_id.strip()) or repo.get(preferred_skill_id.strip())

            if skill is None and workflow_node_id:
                candidates = repo.active_for_node(workflow_node_id, platform=task.platform)
                skill = candidates[0] if candidates else None

            if skill is None:
                return None

            return {
                "id": skill.id,
                "skill_id": skill.skill_id,
                "name": skill.name,
                "status": skill.status,
                "version": skill.version,
                "platform": skill.platform,
                "bound_to_workflow_node": skill.bound_to_workflow_node,
                "strategy": dict(skill.strategy or {}),
                "execution_hints": dict(skill.execution_hints or {}),
                "last_health_status": skill.last_health_status,
            }

    def _start_workflow_run(
        self,
        task: TaskEnvelope,
        *,
        workflow: WorkflowDefinition,
        workflow_node: WorkflowNode | None,
        session_context: dict[str, Any],
        skill_context: dict[str, Any] | None,
        platform_context: dict[str, Any],
    ) -> str | None:
        resolved_workflow_id = task.workflow_id
        if self.session_factory is None or not resolved_workflow_id:
            return None

        with self.session_factory() as session:
            candidate_repo = CandidateRepository(session)
            workflow_run_repo = WorkflowRunRepository(session)
            candidate = candidate_repo.resolve(task.candidate_id) if task.candidate_id else None
            if candidate is not None and workflow_node is not None:
                candidate.current_workflow_node = workflow_node.node_id

            run = workflow_run_repo.create(
                {
                    "workflow_id": resolved_workflow_id,
                    "candidate_id": candidate.id if candidate is not None else None,
                    "status": "running",
                    "current_node": workflow_node.node_id if workflow_node is not None else task.workflow_node_id,
                    "started_at": utcnow(),
                    "context": {
                        "task_id": task.task_id,
                        "task_type": task.task_type,
                        "payload": dict(task.payload or {}),
                        "metadata": dict(task.metadata or {}),
                        "session": session_context,
                        "skill": skill_context,
                        "platform": platform_context,
                    },
                }
            )
            return run.id

    def _persist_task_artifacts(
        self,
        task: TaskEnvelope,
        result: AgentResult,
        *,
        workflow: WorkflowDefinition,
        workflow_node: WorkflowNode | None,
        workflow_run_id: str | None,
        session_context: dict[str, Any],
        skill_context: dict[str, Any] | None,
    ) -> None:
        if self.session_factory is None:
            return

        try:
            with self.session_factory() as session:
                candidate_repo = CandidateRepository(session)
                session_repo = CandidateSessionRepository(session)
                decision_repo = DecisionLogRepository(session)
                communication_repo = CommunicationLogRepository(session)
                workflow_run_repo = WorkflowRunRepository(session)

                candidate = candidate_repo.resolve(task.candidate_id) if task.candidate_id else None
                candidate_session = None
                if candidate is not None:
                    candidate_session = session_repo.get_or_create(
                        candidate.id,
                        defaults={"status": "active", "facts": {}, "recent_messages": []},
                    )
                    business_status = extract_business_status(result.data) or result.status
                    candidate.current_workflow_node = workflow_node.node_id if workflow_node is not None else task.workflow_node_id
                    candidate.ai_reasoning = result.content or candidate.ai_reasoning

                    facts = dict(candidate_session.facts or {})
                    facts.update(
                        {
                            "last_task_id": task.task_id,
                            "last_task_type": task.task_type,
                            "last_result_status": business_status,
                            "last_execution_status": result.status,
                            "last_result_success": result.success,
                            "workflow_id": task.workflow_id or workflow.workflow_id,
                            "workflow_node_id": workflow_node.node_id if workflow_node is not None else task.workflow_node_id,
                        }
                    )
                    if result.data:
                        facts["last_result_data"] = dict(result.data)
                    if skill_context:
                        facts["active_skill"] = {
                            "skill_id": skill_context.get("skill_id"),
                            "name": skill_context.get("name"),
                        }
                    candidate_session.facts = facts
                    candidate_session.context_summary = result.content or candidate_session.context_summary
                    candidate_session.last_active_at = utcnow()
                    if result.status == "waiting_human":
                        candidate_session.status = "waiting_human"
                        candidate_session.suspend_reason = result.content or "Waiting for approval."
                    else:
                        candidate_session.status = "active"
                        candidate_session.suspend_reason = None

                if workflow_run_id is not None:
                    run = workflow_run_repo.get(workflow_run_id)
                    if run is not None:
                        next_tasks = self.workflow_engine.next_tasks(task, result) if result.success else []
                        if result.status == "waiting_human":
                            run.status = "blocked"
                            run.finished_at = None
                        elif result.success:
                            run.status = "completed"
                            run.finished_at = utcnow()
                        else:
                            run.status = result.status
                            run.finished_at = utcnow()
                        run.current_node = workflow_node.node_id if workflow_node is not None else task.workflow_node_id
                        run.last_error = None if result.success else result.content
                        run.context = {
                            **dict(run.context or {}),
                            "result": {
                                "success": result.success,
                                "status": result.status,
                                "business_status": extract_business_status(result.data) or result.status,
                                "content": result.content,
                                "data": dict(result.data or {}),
                                "metadata": dict(result.metadata or {}),
                            },
                            "next_tasks": [self._task_snapshot(item) for item in next_tasks],
                        }

                if candidate is not None:
                    if task.task_type == "initiate_communication":
                        communication_repo.create(
                            {
                                "candidate_id": candidate.id,
                                "direction": "outbound",
                                "content": str(result.metadata.get("platform_result", {}).get("message") or task.payload.get("message") or result.content),
                                "message_type": "text",
                                "platform": task.platform,
                                "timestamp": utcnow(),
                            }
                        )
                        session_repo.append_recent_message(
                            candidate_session,
                            direction="outbound",
                            content=str(result.metadata.get("platform_result", {}).get("message") or task.payload.get("message") or result.content),
                            metadata={"task_id": task.task_id, "task_type": task.task_type},
                        )
                    elif task.task_type == "request_resume":
                        communication_repo.create(
                            {
                                "candidate_id": candidate.id,
                                "direction": "outbound",
                                "content": "Requested resume submission.",
                                "message_type": "resume_request",
                                "platform": task.platform,
                                "timestamp": utcnow(),
                            }
                        )
                        session_repo.append_recent_message(
                            candidate_session,
                            direction="outbound",
                            content="Requested resume submission.",
                            message_type="resume_request",
                            metadata={"task_id": task.task_id, "task_type": task.task_type},
                        )

                    decision_value = str(extract_business_status(result.data) or result.status or "completed")
                    if decision_value:
                        decision_repo.create(
                            {
                                "candidate_id": candidate.id,
                                "task_id": task.task_id,
                                "decision_type": task.task_type,
                                "decision": decision_value,
                                "scores": dict(result.data or {}),
                                "reasoning": result.content,
                                "input_context_snapshot": {
                                    "payload": dict(task.payload or {}),
                                    "session": session_context,
                                    "skill": skill_context,
                                },
                                "timestamp": utcnow(),
                            }
                        )

                self._update_skill_health(session, skill_context, result, task=task)
                session.commit()
        except Exception as exc:  # pragma: no cover - defensive guard
            self.events.publish(
                "error",
                "runtime",
                "Failed to persist runtime execution artifacts.",
                task_id=task.task_id,
                error=str(exc),
            )

    def _enqueue_sync(self, item_type: str, item_id: str, payload: dict[str, Any]) -> None:
        if self.sync_service is None or not self.sync_service.intranet_enabled:
            return
        self.sync_service.enqueue(item_type, item_id, payload)

    def _update_skill_health(
        self,
        session: Session,
        skill_context: dict[str, Any] | None,
        result: AgentResult,
        *,
        task: TaskEnvelope,
    ) -> None:
        if not skill_context or not result.success or not isinstance(result.data, dict):
            return

        repo = SkillRepository(session)
        skill = None
        skill_record_id = skill_context.get("id")
        if isinstance(skill_record_id, str) and skill_record_id.strip():
            skill = repo.get(skill_record_id)
        if skill is None:
            skill_key = skill_context.get("skill_id")
            if isinstance(skill_key, str) and skill_key.strip():
                skill = repo.by_skill_id(skill_key)
        if skill is None:
            return

        checker = SkillHealthCheckService()
        health_result = checker.run(skill, observed_result=result.data)
        if health_result.health != "healthy":
            self.events.publish(
                "warning",
                "skill_health",
                "Runtime execution degraded an active skill.",
                task_id=task.task_id,
                skill_id=skill.skill_id,
                health=health_result.health,
                issues=health_result.issues,
            )

    def _persist_runtime_learning(self, task: TaskEnvelope, result: AgentResult) -> None:
        if not result.success or self.session_factory is None:
            return

        drafts = self._extract_learning_drafts(result)
        if not drafts:
            return

        try:
            with self.session_factory() as session:
                learning_repo = AgentLearningRepository(session)
                approval_repo = ApprovalRepository(session)
                learning_ids = list(result.metadata.get("learning_ids", []))
                approval_ids = list(result.metadata.get("approval_ids", []))

                for draft in drafts:
                    learning = self._upsert_learning(session, learning_repo, task, draft)
                    if learning.id not in learning_ids:
                        learning_ids.append(learning.id)

                    self.events.publish(
                        "info",
                        "learning",
                        f"Captured runtime learning for task {task.task_type}.",
                        learning_id=learning.id,
                        task_id=task.task_id,
                    )

                    if not self._requires_runtime_review(draft):
                        continue

                    approval = self._ensure_learning_approval(session, approval_repo, task, learning, draft)
                    if approval.id not in approval_ids:
                        approval_ids.append(approval.id)
                        self.events.publish(
                            "warning",
                            "approval",
                            "Runtime skill draft queued for desktop review.",
                            approval_id=approval.id,
                            learning_id=learning.id,
                            task_id=task.task_id,
                        )

                result.metadata["learning_ids"] = learning_ids
                if approval_ids:
                    result.metadata["approval_ids"] = approval_ids
        except Exception as exc:  # pragma: no cover - defensive guard
            result.metadata["learning_persist_error"] = str(exc)
            self.events.publish(
                "error",
                "learning",
                "Failed to persist runtime learning artifact.",
                task_id=task.task_id,
                error=str(exc),
            )

    def _extract_learning_drafts(self, result: AgentResult) -> list[dict[str, Any]]:
        drafts: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _append(payload: dict[str, Any] | str | None, *, kind: str, requires_review: bool = False) -> None:
            if payload is None:
                return
            if isinstance(payload, str):
                item = {"content": payload}
            else:
                item = dict(payload)
            item.setdefault("kind", kind)
            item.setdefault("requires_review", requires_review)
            marker = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            if marker in seen:
                return
            seen.add(marker)
            drafts.append(item)

        _append(result.skill_draft, kind="skill_draft", requires_review=True)

        if isinstance(result.data, dict):
            _append(result.data.get("learning"), kind="learning")
            _append(result.data.get("learning_draft"), kind="learning")
            raw_learnings = result.data.get("learnings")
            if isinstance(raw_learnings, list):
                for learning in raw_learnings:
                    _append(learning, kind="learning")

        return drafts

    def _upsert_learning(
        self,
        session: Session,
        repo: AgentLearningRepository,
        task: TaskEnvelope,
        draft: dict[str, Any],
    ) -> AgentLearning:
        content = self._build_learning_content(task, draft)
        existing = (
            session.query(AgentLearning)
            .filter(
                AgentLearning.source_task_id == task.task_id,
                AgentLearning.content == content,
            )
            .first()
        )
        if existing is not None:
            return existing

        tags = [str(tag) for tag in draft.get("tags", []) if str(tag).strip()]
        for tag in ("runtime", str(draft.get("kind") or "learning")):
            if tag not in tags:
                tags.append(tag)

        return repo.create(
            {
                "content": content,
                "tags": tags,
                "source_task_id": str(draft.get("source_task_id") or task.task_id),
                "is_active": bool(draft.get("is_active", True)),
            }
        )

    def _ensure_learning_approval(
        self,
        session: Session,
        repo: ApprovalRepository,
        task: TaskEnvelope,
        learning: AgentLearning,
        draft: dict[str, Any],
    ) -> ApprovalItem:
        target_type = str(draft.get("approval_target_type") or draft.get("kind") or "learning")
        existing = (
            session.query(ApprovalItem)
            .filter(
                ApprovalItem.target_type == target_type,
                ApprovalItem.target_id == learning.id,
            )
            .first()
        )
        if existing is not None:
            return existing

        skill_name = str(draft.get("skill_name") or draft.get("name") or task.workflow_node_id or task.task_type)
        title = str(draft.get("approval_title") or f"Review runtime skill draft: {skill_name}")
        approval_payload = {
            "summary": draft.get("summary") or self._build_learning_content(task, draft),
            "task_id": task.task_id,
            "task_type": task.task_type,
            "candidate_id": task.candidate_id,
            "workflow_id": task.workflow_id,
            "workflow_node_id": task.workflow_node_id,
            "learning_id": learning.id,
            "skill_draft": dict(draft),
        }

        return repo.create(
            {
                "target_type": target_type,
                "target_id": learning.id,
                "title": title,
                "status": "pending",
                "requested_by": str(draft.get("requested_by") or "runtime"),
                "payload": approval_payload,
                "notes": draft.get("notes"),
            }
        )

    def _persist_blocked_task_approval(self, task: TaskEnvelope, result: AgentResult) -> None:
        if self.session_factory is None:
            return

        try:
            with self.session_factory() as session:
                approval_repo = ApprovalRepository(session)
                existing = (
                    session.query(ApprovalItem)
                    .filter(
                        ApprovalItem.target_type == "blocked_task",
                        ApprovalItem.target_id == task.task_id,
                    )
                    .first()
                )
                if existing is not None:
                    return

                payload = self._build_blocked_task_payload(task, result)
                approval_repo.create(
                    {
                        "target_type": "blocked_task",
                        "target_id": task.task_id,
                        "title": self._blocked_task_title(task),
                        "status": "pending",
                        "requested_by": "runtime",
                        "payload": payload,
                        "notes": result.content or "Task paused for human review.",
                    }
                )
                self.events.publish(
                    "warning",
                    "approval",
                    "Blocked task queued for desktop approval.",
                    task_id=task.task_id,
                    task_type=task.task_type,
                )
        except Exception as exc:  # pragma: no cover - defensive guard
            self.events.publish(
                "error",
                "approval",
                "Failed to persist blocked task approval.",
                task_id=task.task_id,
                error=str(exc),
            )

    def _requires_runtime_review(self, draft: dict[str, Any]) -> bool:
        if "requires_review" in draft:
            return bool(draft["requires_review"])
        return str(draft.get("kind") or "") == "skill_draft"

    def _build_learning_content(self, task: TaskEnvelope, draft: dict[str, Any]) -> str:
        for key in ("content", "summary", "description", "insight"):
            value = draft.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        skill_name = draft.get("skill_name") or draft.get("name")
        if isinstance(skill_name, str) and skill_name.strip():
            return f"Runtime skill draft proposed for {skill_name.strip()}."

        return f"Runtime learning captured for {task.task_type}."

    def _build_blocked_task_payload(self, task: TaskEnvelope, result: AgentResult) -> dict[str, Any]:
        task_snapshot = self._task_snapshot(task)
        return {
            "kind": "blocked_task",
            "task_state": result.status,
            "resume_on_approve": True,
            "blocked_task": task_snapshot,
            "resume_task": {
                **task_snapshot,
                "status": "pending",
                "attempts": 0,
                "metadata": {
                    **task_snapshot.get("metadata", {}),
                    "resumed_from": task.task_id,
                    "resume_reason": "approval",
                },
            },
            "resolution": None,
            "summary": result.content or "Task paused for human review.",
            "reason": result.content or "Human review required.",
        }

    def _enqueue_task_snapshot(self, snapshot: dict[str, Any]) -> bool:
        try:
            self.enqueue_task(
                task_type=str(snapshot["task_type"]),
                task_id=str(snapshot.get("task_id") or uuid4().hex),
                payload=dict(snapshot.get("payload") or {}),
                metadata=dict(snapshot.get("metadata") or {}),
                priority=int(snapshot.get("priority", 100) or 100),
                candidate_id=snapshot.get("candidate_id"),
                workflow_id=snapshot.get("workflow_id"),
                workflow_node_id=snapshot.get("workflow_node_id"),
            )
            return True
        except Exception as exc:  # pragma: no cover - defensive guard
            self.events.publish(
                "error",
                "approval",
                "Failed to enqueue resumed task.",
                task_id=str(snapshot.get("task_id") or ""),
                error=str(exc),
            )
            return False

    def _apply_blocked_session_resolution(
        self,
        session: Session,
        approval: ApprovalItem,
        *,
        status: str,
        notes: str | None,
    ) -> None:
        blocked_task = dict((approval.payload or {}).get("blocked_task") or {})
        candidate_id = blocked_task.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            return

        candidate = CandidateRepository(session).resolve(candidate_id)
        if candidate is None:
            return

        session_repo = CandidateSessionRepository(session)
        candidate_session = session_repo.by_candidate_id(candidate.id)
        if candidate_session is None:
            return

        candidate_session.status = "active" if status == "approved" else "closed"
        candidate_session.suspend_reason = None if status == "approved" else (notes or "Human review rejected the blocked task.")
        candidate_session.last_active_at = utcnow()

    def _task_snapshot(self, task: TaskEnvelope) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "priority": task.priority,
            "payload": dict(task.payload or {}),
            "metadata": dict(task.metadata or {}),
            "candidate_id": task.candidate_id,
            "workflow_id": task.workflow_id,
            "workflow_node_id": task.workflow_node_id,
            "platform": task.platform,
            "attempts": task.attempts,
            "due_at": task.due_at.isoformat() if task.due_at else None,
        }

    def _blocked_task_title(self, task: TaskEnvelope) -> str:
        node = task.workflow_node_id or task.task_type
        if task.candidate_id:
            return f"Resume blocked task for {task.candidate_id}: {node}"
        return f"Resume blocked task: {node}"
