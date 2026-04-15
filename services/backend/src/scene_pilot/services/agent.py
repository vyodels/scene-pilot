from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.base import utcnow
from scene_pilot.models import AgentLearning, ApprovalItem
from scene_pilot.repositories import (
    AgentLearningRepository,
    AgentRunCheckpointRepository,
    AgentRunRepository,
    AgentSessionRepository,
    ExecutionGraphProjectionRepository,
    ExecutionTraceRepository,
    GoalSpecRepository,
    OperatorInteractionRepository,
    ApprovalRepository,
    CandidateRepository,
    CandidateSessionRepository,
    CommunicationLogRepository,
    DecisionLogRepository,
    SkillRepository,
    StrategyFragmentRepository,
)
from scene_pilot.runtime.agent_loop import AgentLoop
from scene_pilot.runtime.models import AgentResult
from scene_pilot.runtime.result_semantics import extract_business_status
from scene_pilot.scheduler.queue import TaskEnvelope
from scene_pilot.scheduler.scheduler import ScheduledOutcome, SerialScheduler
from scene_pilot.services.context_assembler import ContextAssemblerService
from scene_pilot.services.events import EventStreamService
from scene_pilot.services.feature_flags import FeatureFlagService
from scene_pilot.services.adaptive_runtime import resolve_adaptive_stage
from scene_pilot.services.runtime_control import RuntimeControlService
from scene_pilot.services.skills import SkillHealthCheckService
from scene_pilot.services.sync import SyncService
from scene_pilot.services.runtime import PersistedRuntimeService


@dataclass(slots=True)
class AgentControlService:
    scheduler: SerialScheduler
    settings: AppSettings
    agent_loop: AgentLoop | None = None
    events: EventStreamService = field(default_factory=EventStreamService)
    flags: FeatureFlagService = field(default_factory=FeatureFlagService)
    sync_service: SyncService | None = None
    session_factory: sessionmaker[Session] | None = None
    runtime_service_factory: Callable[[Session], PersistedRuntimeService] | None = None

    def enqueue_task(
        self,
        task_type: str,
        *,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        candidate_id: str | None = None,
    ) -> TaskEnvelope:
        adaptive_stage = resolve_adaptive_stage(
            task_type=task_type,
            explicit_stage=str((metadata or {}).get("adaptive_stage") or (payload or {}).get("adaptive_stage") or "").strip() or None,
        )
        task = TaskEnvelope(
            task_id=task_id or uuid4().hex,
            task_type=adaptive_stage,
            payload=payload or {},
            priority=priority,
            candidate_id=candidate_id,
            metadata={**(metadata or {}), "adaptive_stage": adaptive_stage},
        )
        if self.session_factory is not None:
            with self.session_factory() as session:
                RuntimeControlService(
                    session,
                    settings=self.settings,
                    live_events=self.events,
                ).ensure_run_for_task(task)
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

    def build_follow_up_factory(self):
        def _follow_up(task: TaskEnvelope, result: AgentResult):
            if not result.success:
                return []
            follow_ups = self._next_tasks_for_result(task, result)
            if self.session_factory is not None:
                with self.session_factory() as session:
                    runtime_control = RuntimeControlService(
                        session,
                        settings=self.settings,
                        live_events=self.events,
                    )
                    for follow_up in follow_ups:
                        runtime_control.ensure_run_for_task(follow_up)
            return follow_ups

        return _follow_up

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
            RuntimeControlService(
                session,
                settings=self.settings,
                live_events=self.events,
            ).resolve_checkpoint_for_approval(
                approval_id=approval.id,
                status=status,
                reviewer=reviewer,
                notes=notes,
            )

        payload["resolution"] = resolution
        approval.payload = payload
        return approval

    def build_runner(self):
        def _run(task: TaskEnvelope) -> AgentResult:
            adaptive_stage = self._adaptive_stage_for_task(task)
            runtime_session = self._build_runtime_session(task)
            runtime_skill = self._build_skill_context(task)
            platform_context = self._build_platform_context(task)
            runtime_state: dict[str, Any] | None = None
            context_manifest: dict[str, Any] | None = None

            def _finalize_runtime_state(result: AgentResult) -> None:
                if self.session_factory is None or runtime_state is None:
                    return
                with self.session_factory() as session:
                    RuntimeControlService(
                        session,
                        settings=self.settings,
                        live_events=self.events,
                    ).finalize_run(
                        task=task,
                        status=result.status,
                        success=result.success,
                        blocked_reason=result.content if result.status in {"waiting_human", "waiting_candidate", "blocked"} else None,
                        last_error=None if result.success or result.status in {"waiting_human", "waiting_candidate"} else result.content,
                        runtime_metadata_patch={
                            "last_result_status": result.status,
                            "last_result_success": result.success,
                            "last_result_task_type": task.task_type,
                            "context_fragment_count": int((context_manifest or {}).get("fragment_count") or 0),
                            "selected_token_estimate": int((context_manifest or {}).get("selected_token_estimate") or 0),
                        },
                    )

            def _finalize_runtime_error(exc: Exception) -> None:
                if self.session_factory is None or runtime_state is None:
                    return
                self._persist_goal_runtime_error(task, error=str(exc), context_manifest=context_manifest or {})
                with self.session_factory() as session:
                    RuntimeControlService(
                        session,
                        settings=self.settings,
                        live_events=self.events,
                    ).finalize_run(
                        task=task,
                        status="failed",
                        success=False,
                        last_error=str(exc),
                    )

            def _complete(
                result: AgentResult,
                *,
                persist_learning: bool = False,
                session_context_override: dict[str, Any] | None = None,
            ) -> AgentResult:
                if result.status == "waiting_human":
                    self._persist_blocked_task_approval(task, result)
                    self._persist_operator_interaction(task, result)
                self._persist_task_artifacts(
                    task,
                    result,
                    session_context=session_context_override if session_context_override is not None else runtime_session,
                    skill_context=runtime_skill,
                )
                self._persist_goal_runtime_assets(
                    task,
                    result,
                    context_manifest=context_manifest or {},
                    session_context=session_context_override if session_context_override is not None else runtime_session,
                )
                if persist_learning:
                    self._persist_runtime_learning(task, result)
                _finalize_runtime_state(result)
                return result

            try:
                if self.session_factory is not None:
                    with self.session_factory() as session:
                        runtime_control = RuntimeControlService(
                            session,
                            settings=self.settings,
                            live_events=self.events,
                        )
                        runtime_state = runtime_control.begin_run(task)
                        context_manifest = ContextAssemblerService(
                            session,
                            provider=self.agent_loop.provider if self.agent_loop is not None else None,
                        ).build(
                            task,
                            lane=str(runtime_state.get("lane") or "agent"),
                            session_context=runtime_session,
                            skill_context=runtime_skill,
                            platform_context=platform_context,
                        )
                        runtime_control.attach_context_manifest(
                            run_id=str(runtime_state["run_id"]),
                            context_manifest=context_manifest,
                        )

                    runtime_session = {
                        **runtime_session,
                        "runtime": {
                            **runtime_state,
                            "context_manifest": context_manifest,
                        },
                    }
                    platform_context = {
                        **platform_context,
                        "runtime_control": runtime_state,
                        "context_manifest": context_manifest,
                    }
                    task.metadata["context_manifest"] = context_manifest

                managed_execution = self._prepare_managed_execution(task)

                if managed_execution is not None:
                    result = self._run_managed_execution(
                        task,
                        managed_execution=managed_execution,
                        session_context=runtime_session,
                        skill_context=runtime_skill,
                        platform_context=platform_context,
                    )
                    return _complete(
                        result,
                        persist_learning=True,
                        session_context_override={
                            **runtime_session,
                            "managed_execution": {
                                "task_spec_id": managed_execution.task_spec.id,
                                "execution_plan_id": managed_execution.execution_plan.id,
                                "execution_episode_id": managed_execution.execution_episode.id,
                                "scene_type": managed_execution.assessment.scene_type,
                            },
                        },
                    )

                if self.agent_loop is None:
                    result = AgentResult(
                        success=False,
                        status="blocked",
                        content="未配置可用模型 provider，无法执行真实运行。",
                        metadata={"blocked_reason": "provider_unavailable", "requires_real_environment": True},
                    )
                    return _complete(result)

                missing_capabilities = self._missing_external_capabilities(task)
                if missing_capabilities:
                    result = AgentResult(
                        success=False,
                        status="blocked",
                        content=f"缺少真实外部能力：{', '.join(missing_capabilities)}。",
                        metadata={
                            "blocked_reason": "missing_external_capabilities",
                            "missing_capabilities": list(missing_capabilities),
                            "requires_real_environment": True,
                        },
                    )
                    return _complete(result)

                runtime_task = SimpleNamespace(
                    task_type=task.task_type,
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

                return _complete(result, persist_learning=True)
            except Exception as exc:
                _finalize_runtime_error(exc)
                raise

        return _run

    def _prepare_managed_execution(self, task: TaskEnvelope):
        task_spec_id = str(task.metadata.get("task_spec_id") or task.payload.get("task_spec_id") or "").strip()
        execution_plan_id = str(task.metadata.get("execution_plan_id") or task.payload.get("execution_plan_id") or "").strip()
        execution_episode_id = str(task.metadata.get("execution_episode_id") or task.payload.get("execution_episode_id") or "").strip()
        if not task_spec_id or not execution_plan_id:
            return None
        if self.session_factory is None or self.runtime_service_factory is None:
            raise RuntimeError("Managed runtime execution requires a runtime service factory")

        with self.session_factory() as session:
            runtime_service = self.runtime_service_factory(session)
            return runtime_service.start_managed_execution(
                task_spec_id=task_spec_id,
                execution_plan_id=execution_plan_id,
                execution_episode_id=execution_episode_id or None,
                requested_by=str(task.metadata.get("requested_by") or "runtime"),
                mode=str(task.metadata.get("mode") or "production"),
                task_id=task.task_id,
                task_payload=dict(task.payload or {}),
                runtime_metadata=dict(task.metadata or {}),
            )

    def _run_managed_execution(
        self,
        task: TaskEnvelope,
        *,
        managed_execution,
        session_context: dict[str, Any],
        skill_context: dict[str, Any] | None,
        platform_context: dict[str, Any],
    ) -> AgentResult:
        preflight_block = self._managed_preflight_block_result(task, managed_execution=managed_execution)
        if preflight_block is not None:
            result = preflight_block
        elif self.agent_loop is None:
            result = AgentResult(
                success=False,
                status="blocked",
                content="未配置可用模型 provider，无法执行真实受管运行。",
                data={
                    "status": "blocked",
                    "task_id": task.task_id,
                    "execution_plan_id": managed_execution.execution_plan.id,
                },
                metadata={"blocked_reason": "provider_unavailable", "requires_real_environment": True},
            )
        else:
            runtime_task = SimpleNamespace(
                task_type="scale_execution",
                payload={
                    **dict(task.payload or {}),
                    "goal": managed_execution.task_spec.goal,
                    "domain": managed_execution.task_spec.domain,
                    "plan_name": managed_execution.execution_plan.name,
                },
                max_turns=8,
                token_budget=6_144,
            )
            result = self.agent_loop.run(
                runtime_task,
                session=session_context or None,
                skill=skill_context or None,
                extra_context={
                    **platform_context,
                    "scene_assessment": managed_execution.assessment.model_dump(),
                    "capability_drivers": [driver.model_dump() for driver in managed_execution.capability_drivers],
                    "execution_episode": managed_execution.execution_episode.model_dump(),
                    "execution_contract": managed_execution.execution_contract,
                },
            )

        if self.session_factory is None or self.runtime_service_factory is None:
            return result

        with self.session_factory() as session:
            runtime_service = self.runtime_service_factory(session)
            outcome = runtime_service.finalize_managed_execution(
                execution_episode_id=managed_execution.execution_episode.id,
                result=result,
                task_payload=dict(task.payload or {}),
                runtime_metadata={
                    "task_id": task.task_id,
                    "candidate_id": task.candidate_id,
                    "goal_spec_id": str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "") or None,
                    "adaptive_stage": self._adaptive_stage_for_task(task),
                },
            )
            result.metadata.update(
                {
                    "execution_episode_id": outcome.episode.id,
                    "execution_plan_id": managed_execution.execution_plan.id,
                    "task_spec_id": managed_execution.task_spec.id,
                    "derived_template_id": outcome.template.id if outcome.template is not None else None,
                    "derived_patch_id": outcome.patch.id if outcome.patch is not None else None,
                    "derived_learning_id": outcome.learning_draft.id if outcome.learning_draft is not None else None,
                    "template_approval_id": outcome.template_approval.id if outcome.template_approval is not None else None,
                    "approval_id": outcome.approval.id if outcome.approval is not None else None,
                    "skill_health": outcome.skill_health,
                }
            )
            if result.status == "replan_requested":
                self._handle_managed_replan(
                    task,
                    runtime_service=runtime_service,
                    managed_execution=managed_execution,
                    episode_id=outcome.episode.id,
                    result=result,
                )
        return result

    def _managed_preflight_block_result(self, task: TaskEnvelope, *, managed_execution) -> AgentResult | None:
        assessment = managed_execution.assessment
        guidance = assessment.planner_guidance
        blockers = list(assessment.blockers or [])
        is_blocked = str(assessment.plan_fit) == "blocked"
        requires_human_review = bool(guidance.requires_human_review)
        hard_blockers = {"missing_browser_snapshot", "authentication_required", "verification_required"}

        if not is_blocked or not requires_human_review or not any(blocker in hard_blockers for blocker in blockers):
            return None

        blocker_labels = {
            "missing_browser_snapshot": "当前运行缺少实时浏览器场景快照。",
            "scene_needs_reassessment": "当前场景需要重新评估后才能继续执行。",
            "missing_required_capability": "当前运行缺少继续执行所需的能力。",
        }
        preferred_next_actions = [str(item) for item in list(guidance.preferred_next_actions or []) if str(item).strip()]
        rationale = [str(item) for item in list(guidance.rationale or []) if str(item).strip()]
        blocker_notes = [blocker_labels.get(blocker, blocker.replace("_", " ")) for blocker in blockers]
        review_notes = blocker_notes + rationale
        if not review_notes:
            review_notes.append("当前运行在进入执行器前被运行时预检拦截。")

        summary = "受管执行在预检阶段已暂停，等待人工补充场景信息后继续。"
        if blocker_notes:
            summary = f"{summary} {' '.join(blocker_notes)}"

        executor_trace: dict[str, Any] = {
            "preflight_gate": {
                "kind": "waiting_human",
                "summary": summary,
                "task_id": task.task_id,
                "plan_fit": assessment.plan_fit,
                "scene_type": assessment.scene_type,
                "scene_key": assessment.scene_key,
                "blockers": blockers,
                "preferred_next_actions": preferred_next_actions,
                "requires_scene_assessment": bool(guidance.requires_scene_assessment),
                "requires_human_review": requires_human_review,
                "rationale": review_notes,
            }
        }
        if assessment.snapshot is not None:
            executor_trace["scene_updates"] = [assessment.snapshot.model_dump()]

        return AgentResult(
            success=False,
            status="waiting_human",
            content=summary,
            data={
                "status": "waiting_human",
                "summary": summary,
                "task_id": task.task_id,
                "execution_plan_id": managed_execution.execution_plan.id,
                "scene_type": assessment.scene_type,
                "scene_key": assessment.scene_key,
                "plan_fit": assessment.plan_fit,
                "blockers": blockers,
                "preferred_next_actions": preferred_next_actions,
                "requires_scene_assessment": bool(guidance.requires_scene_assessment),
                "requires_human_review": requires_human_review,
                "review_notes": review_notes,
            },
            metadata={
                "managed_execution_preflight_blocked": True,
                "executor_trace": executor_trace,
            },
        )

    def _handle_managed_replan(
        self,
        task: TaskEnvelope,
        *,
        runtime_service: PersistedRuntimeService,
        managed_execution,
        episode_id: str,
        result: AgentResult,
    ) -> None:
        replay = runtime_service.get_episode_replay(episode_id)
        latest_snapshot_id = replay.snapshots[-1].id if replay.snapshots else None
        trace = dict(result.metadata.get("executor_trace") or {})
        latest_request = (trace.get("replan_requests") or [{}])[-1] if trace.get("replan_requests") else {}
        compiler_payload = {
            "compiler_notes": [
                str(latest_request.get("reason") or result.content or "运行时请求修订当前计划。"),
                "系统已根据受管执行过程自动生成重规划建议。",
            ],
            "preferred_capabilities": list(latest_request.get("preferred_capabilities") or []),
            "step_outline": list(latest_request.get("suggested_steps") or []),
            "environment_requirements": {"scene_assessment_required": True},
            "checkpoints": [{"kind": "planner", "label": "重试前先审查自动重规划结果"}],
        }
        replanned = runtime_service.replan_execution(
            managed_execution.execution_plan.id,
            payload=SimpleNamespace(
                name=None,
                reason=str(latest_request.get("reason") or result.content or "Managed execution replan"),
                requested_by=str(task.metadata.get("requested_by") or "runtime"),
                execution_episode_id=episode_id,
                environment_snapshot_id=latest_snapshot_id,
                snapshot=None,
                compiler_payload=compiler_payload,
                plan_context={"task_payload": dict(task.payload or {}), "runtime_task_id": task.task_id},
                runtime_metadata={"generated_by": "managed_executor", "source_task_id": task.task_id},
                checkpoints=[],
                preserve_active_plan=True,
            ),
        )
        follow_up = self.enqueue_task(
            "scale_execution",
            payload={
                **dict(task.payload or {}),
                "task_spec_id": managed_execution.task_spec.id,
                "execution_plan_id": replanned.execution_plan.id,
                "execution_episode_id": episode_id,
            },
            metadata={
                **dict(task.metadata or {}),
                "task_spec_id": managed_execution.task_spec.id,
                "execution_plan_id": replanned.execution_plan.id,
                "execution_episode_id": episode_id,
                "requested_by": str(task.metadata.get("requested_by") or "runtime"),
                "mode": str(task.metadata.get("mode") or "production"),
                "replanned_from_task_id": task.task_id,
                "replanned_from_episode_id": episode_id,
            },
            priority=max(task.priority - 1, 1),
            candidate_id=task.candidate_id,
        )
        result.metadata["replanned_execution_plan_id"] = replanned.execution_plan.id
        result.metadata["replanned_task_id"] = follow_up.task_id

    def _build_platform_context(self, task: TaskEnvelope) -> dict[str, Any]:
        return {
            "platform": task.platform,
            "candidate_id": task.candidate_id,
            "requires_real_environment": True,
        }

    def _build_runtime_session(self, task: TaskEnvelope) -> dict[str, Any]:
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
            adaptive_stage = self._adaptive_stage_for_task(task)
            facts.update(
                {
                    "candidate_status": candidate.status,
                    "goal_spec_id": str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "") or None,
                    "task_type": task.task_type,
                    "resume_available": bool(candidate.resume_path or candidate.online_resume_text),
                }
            )
            if adaptive_stage == "strategy_distill":
                facts["last_learning_stage"] = adaptive_stage
            else:
                facts["adaptive_stage"] = adaptive_stage
            candidate_session.facts = facts
            session.commit()

            return {
                "candidate": {
                    "id": candidate.id,
                    "platform_candidate_id": candidate.platform_candidate_id,
                    "name": candidate.name,
                    "platform": candidate.platform,
                    "status": candidate.status,
                    "current_stage_key": candidate.current_stage_key,
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

    def _build_skill_context(self, task: TaskEnvelope) -> dict[str, Any] | None:
        if self.session_factory is None:
            return None

        preferred_skill_id = (
            task.payload.get("skill_id")
            or task.metadata.get("skill_id")
        )
        adaptive_stage = str(task.metadata.get("adaptive_stage") or "").strip() or self._adaptive_stage_for_task(task)

        with self.session_factory() as session:
            repo = SkillRepository(session)
            skill = None

            if isinstance(preferred_skill_id, str) and preferred_skill_id.strip():
                skill = repo.by_skill_id(preferred_skill_id.strip()) or repo.get(preferred_skill_id.strip())

            if skill is None and adaptive_stage:
                candidates = repo.active_for_stage(adaptive_stage, platform=task.platform)
                skill = candidates[0] if candidates else None

            if skill is None and task.task_type:
                candidates = repo.active_for_stage(task.task_type, platform=task.platform)
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
                "bound_to_stage": adaptive_stage,
                "strategy": dict(skill.strategy or {}),
                "execution_hints": dict(skill.execution_hints or {}),
                "last_health_status": skill.last_health_status,
            }

    def _persist_task_artifacts(
        self,
        task: TaskEnvelope,
        result: AgentResult,
        *,
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

                candidate = candidate_repo.resolve(task.candidate_id) if task.candidate_id else None
                candidate_session = None
                adaptive_stage = self._adaptive_stage_for_task(task)
                learning_stage = adaptive_stage == "strategy_distill"
                if candidate is not None:
                    candidate_session = session_repo.get_or_create(
                        candidate.id,
                        defaults={"status": "active", "facts": {}, "recent_messages": []},
                    )
                    business_status = extract_business_status(result.data) or result.status
                    if not learning_stage:
                        candidate.current_stage_key = adaptive_stage
                        candidate.ai_reasoning = result.content or candidate.ai_reasoning

                    facts = dict(candidate_session.facts or {})
                    if learning_stage:
                        facts.update(
                            {
                                "last_learning_task_id": task.task_id,
                                "last_learning_task_type": task.task_type,
                                "last_learning_status": result.status,
                                "last_learning_success": result.success,
                            }
                        )
                    else:
                        facts.update(
                            {
                                "last_task_id": task.task_id,
                                "last_task_type": task.task_type,
                                "last_result_status": business_status,
                                "last_execution_status": result.status,
                                "last_result_success": result.success,
                                "goal_spec_id": str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "") or None,
                                "adaptive_stage": adaptive_stage,
                            }
                        )
                    if result.data:
                        key = "last_learning_result_data" if learning_stage else "last_result_data"
                        facts[key] = dict(result.data)
                    if skill_context:
                        facts["active_skill"] = {
                            "skill_id": skill_context.get("skill_id"),
                            "name": skill_context.get("name"),
                        }
                    candidate_session.facts = facts
                    if not learning_stage:
                        candidate_session.context_summary = result.content or candidate_session.context_summary
                    candidate_session.last_active_at = utcnow()
                    if result.status == "waiting_human" and not learning_stage:
                        candidate_session.status = "waiting_human"
                        candidate_session.suspend_reason = result.content or "等待审批。"
                    else:
                        candidate_session.status = "active"
                        candidate_session.suspend_reason = None

                if candidate is not None:
                    if task.task_type == "candidate_scoring" and isinstance(result.data, dict) and result.success:
                        candidate.ai_scores = dict(result.data)
                    if task.task_type == "candidate_outreach":
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
                    elif task.task_type == "resume_collection":
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
                    if decision_value and not learning_stage:
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

    def _missing_external_capabilities(self, task: TaskEnvelope) -> list[str]:
        if self.agent_loop is None:
            return ["llm"]
        required: set[str] = set()
        adaptive_stage = self._adaptive_stage_for_task(task)
        if adaptive_stage in {
            "candidate_discovery",
            "candidate_probe",
            "candidate_outreach",
            "resume_collection",
            "candidate_archive",
        }:
            required.add("browser")
        if adaptive_stage in {"candidate_outreach", "resume_collection", "candidate_archive"}:
            required.add("approval")
        missing = [
            capability
            for capability in sorted(required)
            if not self.agent_loop.tools.capability_tool_names(capability)
        ]
        return missing

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

        skill_name = str(draft.get("skill_name") or draft.get("name") or self._adaptive_stage_for_task(task) or task.task_type)
        title = str(draft.get("approval_title") or f"Review runtime skill draft: {skill_name}")
        approval_payload = {
            "summary": draft.get("summary") or self._build_learning_content(task, draft),
            "task_id": task.task_id,
            "task_type": task.task_type,
            "candidate_id": task.candidate_id,
            "goal_spec_id": str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "") or None,
            "adaptive_stage": self._adaptive_stage_for_task(task),
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
                approval = approval_repo.create(
                    {
                        "target_type": "blocked_task",
                        "target_id": task.task_id,
                        "title": self._blocked_task_title(task),
                        "status": "pending",
                        "requested_by": "runtime",
                        "payload": payload,
                        "notes": result.content or "任务已暂停，等待人工审查。",
                    }
                )
                RuntimeControlService(
                    session,
                    settings=self.settings,
                    live_events=self.events,
                ).create_checkpoint(
                    task=task,
                    checkpoint_kind="approval",
                    title=approval.title,
                    summary=result.content or "任务已暂停，等待人工审查。",
                    payload={
                        "approval_id": approval.id,
                        "task_id": task.task_id,
                        "task_type": task.task_type,
                        "candidate_id": task.candidate_id,
                        "blocked_task": payload.get("blocked_task"),
                    },
                    approval_id=approval.id,
                )
                self.events.publish(
                    "warning",
                    "approval",
                    "阻塞任务已进入桌面审批队列。",
                    task_id=task.task_id,
                    task_type=task.task_type,
                )
        except Exception as exc:  # pragma: no cover - defensive guard
            self.events.publish(
                "error",
                "approval",
                "保存阻塞任务审批失败。",
                task_id=task.task_id,
                error=str(exc),
            )

    def _persist_operator_interaction(self, task: TaskEnvelope, result: AgentResult) -> None:
        if self.session_factory is None:
            return

        try:
            with self.session_factory() as session:
                approval = (
                    session.query(ApprovalItem)
                    .filter(
                        ApprovalItem.target_type == "blocked_task",
                        ApprovalItem.target_id == task.task_id,
                    )
                    .first()
                )
                if approval is None:
                    return
                repo = OperatorInteractionRepository(session)
                existing = repo.open_for_approval(approval.id)
                prompt = self._build_operator_prompt(task, result)
                options = self._build_operator_options(task, result)
                if existing is not None:
                    repo.update(
                        existing,
                        {
                            "title": approval.title,
                            "agent_prompt": prompt,
                            "suggested_options": options,
                            "interaction_metadata": {
                                **dict(existing.interaction_metadata or {}),
                                "task_type": task.task_type,
                                "candidate_id": task.candidate_id,
                            },
                        },
                    )
                    return

                checkpoint = AgentRunCheckpointRepository(session).by_approval(approval.id)
                repo.create(
                    {
                        "session_id": str(task.metadata.get("agent_session_id") or ""),
                        "run_id": str(task.metadata.get("agent_run_id") or "") or None,
                        "checkpoint_id": checkpoint.id if checkpoint is not None else None,
                        "approval_id": approval.id,
                        "goal_spec_id": str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "") or None,
                        "candidate_id": task.candidate_id,
                        "lane": str(task.metadata.get("lane") or ("candidate" if task.candidate_id else "agent")),
                        "interaction_type": "confirm",
                        "status": "pending",
                        "title": approval.title,
                        "agent_prompt": prompt,
                        "suggested_options": options,
                        "scope": "run_only",
                        "interaction_metadata": {
                            "task_id": task.task_id,
                            "task_type": task.task_type,
                            "approval_id": approval.id,
                            "candidate_id": task.candidate_id,
                        },
                    }
                )
        except Exception as exc:  # pragma: no cover - defensive guard
            self.events.publish(
                "error",
                "operator_interaction",
                "保存运行时人工介入项失败。",
                task_id=task.task_id,
                error=str(exc),
            )

    def _persist_goal_runtime_assets(
        self,
        task: TaskEnvelope,
        result: AgentResult,
        *,
        context_manifest: dict[str, Any],
        session_context: dict[str, Any] | None,
    ) -> None:
        if self.session_factory is None:
            return

        try:
            with self.session_factory() as session:
                run_id = str(task.metadata.get("agent_run_id") or "").strip()
                session_id = str(task.metadata.get("agent_session_id") or "").strip()
                goal_spec_id = str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "").strip() or None
                run = AgentRunRepository(session).get(run_id) if run_id else None
                goal = GoalSpecRepository(session).get(goal_spec_id) if goal_spec_id else None

                title = goal.title if goal is not None else self._humanize_task_label(self._adaptive_stage_for_task(task))
                summary = result.content or f"{title} 当前状态为 {result.status}。"
                raw_trace = {
                    "task_snapshot": self._task_snapshot(task),
                    "result": {
                        "status": result.status,
                        "success": result.success,
                        "content": result.content,
                        "metadata": dict(result.metadata or {}),
                        "tool_outputs": [asdict(item) for item in list(result.tool_outputs or [])],
                    },
                    "context_manifest": context_manifest,
                    "session_context": {
                        "candidate": dict((session_context or {}).get("candidate") or {}),
                        "runtime": dict((session_context or {}).get("runtime") or {}),
                    },
                }
                distilled_trace = {
                    "goal": goal.goal_text if goal is not None else str(task.payload.get("goal_text") or self._adaptive_stage_for_task(task)),
                    "attempt": {
                        "task_type": task.task_type,
                        "lane": str(run.lane if run is not None else task.metadata.get("lane") or "agent"),
                        "candidate_id": task.candidate_id,
                    },
                    "signals": list((context_manifest or {}).get("selected_fragments") or []),
                    "blocked": result.status in {"waiting_human", "waiting_candidate", "blocked"},
                    "next_step_hint": self._next_step_hint(result.status),
                }
                outcome = {
                    "status": result.status,
                    "success": result.success,
                    "blocked_reason": result.content if result.status in {"waiting_human", "blocked"} else None,
                    "selected_token_estimate": int((context_manifest or {}).get("selected_token_estimate") or 0),
                }

                trace_repo = ExecutionTraceRepository(session)
                existing_trace = trace_repo.by_run(run_id) if run_id else None
                trace_payload = {
                    "session_id": session_id or (run.session_id if run is not None else ""),
                    "run_id": run_id or None,
                    "goal_spec_id": goal_spec_id,
                    "candidate_id": task.candidate_id,
                    "lane": str(run.lane if run is not None else task.metadata.get("lane") or "agent"),
                    "trace_kind": "adaptive_run",
                    "status": "blocked" if result.status in {"waiting_human", "blocked"} else ("completed" if result.success else result.status),
                    "title": title,
                    "summary": summary,
                    "raw_trace": raw_trace,
                    "distilled_trace": distilled_trace,
                    "outcome": outcome,
                    "trace_metadata": {
                        "task_id": task.task_id,
                        "task_type": task.task_type,
                    },
                    "started_at": run.started_at if run is not None else None,
                    "finished_at": run.finished_at if run is not None else None,
                }
                if existing_trace is not None:
                    trace_repo.update(existing_trace, trace_payload)
                else:
                    trace_repo.create(trace_payload)

                graph_repo = ExecutionGraphProjectionRepository(session)
                existing_graph = graph_repo.by_run(run_id) if run_id else None
                graph_payload = self._build_graph_projection_payload(task=task, goal=goal, result=result)
                if existing_graph is not None:
                    graph_repo.update(existing_graph, graph_payload)
                else:
                    graph_repo.create(graph_payload)

                session_record = AgentSessionRepository(session).get(session_id) if session_id else None
                agent_profile_id = (
                    goal.agent_profile_id
                    if goal is not None
                    else session_record.agent_profile_id
                    if session_record is not None
                    else ensure_primary_recruit_agent_profile(session).id
                )
                fragment_repo = StrategyFragmentRepository(session)
                fragment_repo.create(
                    {
                        "agent_profile_id": agent_profile_id,
                        "goal_spec_id": goal_spec_id,
                        "run_id": run_id or None,
                        "candidate_id": task.candidate_id,
                        "jd_id": getattr(run, "jd_id", None),
                        "scope": "candidate" if task.candidate_id else "agent",
                        "fragment_kind": "adaptive_strategy",
                        "title": f"{title} · {self._humanize_task_label(task.task_type)}",
                        "summary": self._strategy_fragment_summary(task=task, result=result),
                        "content": {
                            "suggested_path": self._next_step_hint(result.status),
                            "task_type": task.task_type,
                            "result_status": result.status,
                            "candidate_id": task.candidate_id,
                        },
                        "evidence": {
                            "run_id": run_id or None,
                            "goal_spec_id": goal_spec_id,
                            "result_status": result.status,
                        },
                        "status": "draft" if not result.success else "active",
                        "fragment_metadata": {
                            "generated_by": "adaptive_runtime",
                        },
                    }
                )

                if goal is not None:
                    GoalSpecRepository(session).update(
                        goal,
                        {
                            "status": self._goal_status_from_result(result),
                            "summary": summary,
                            "latest_run_id": run_id or goal.latest_run_id,
                            "last_activity_at": utcnow(),
                            "goal_metadata": {
                                **dict(goal.goal_metadata or {}),
                                "last_result_status": result.status,
                            },
                        },
                    )
        except Exception as exc:  # pragma: no cover - defensive guard
            self.events.publish(
                "error",
                "adaptive_runtime",
                "保存目标驱动运行资产失败。",
                task_id=task.task_id,
                error=str(exc),
            )

    def _persist_goal_runtime_error(
        self,
        task: TaskEnvelope,
        *,
        error: str,
        context_manifest: dict[str, Any],
    ) -> None:
        if self.session_factory is None:
            return
        try:
            with self.session_factory() as session:
                run_id = str(task.metadata.get("agent_run_id") or "").strip()
                session_id = str(task.metadata.get("agent_session_id") or "").strip()
                goal_spec_id = str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "").strip() or None
                trace_repo = ExecutionTraceRepository(session)
                existing = trace_repo.by_run(run_id) if run_id else None
                payload = {
                    "session_id": session_id,
                    "run_id": run_id or None,
                    "goal_spec_id": goal_spec_id,
                    "candidate_id": task.candidate_id,
                    "lane": str(task.metadata.get("lane") or ("candidate" if task.candidate_id else "agent")),
                    "trace_kind": "adaptive_run",
                    "status": "failed",
                    "title": self._humanize_task_label(self._adaptive_stage_for_task(task)),
                    "summary": error,
                    "raw_trace": {
                        "task_snapshot": self._task_snapshot(task),
                        "error": error,
                        "context_manifest": context_manifest,
                    },
                    "distilled_trace": {
                        "goal": str(task.payload.get("goal_text") or self._adaptive_stage_for_task(task)),
                        "failure": error,
                    },
                    "outcome": {"status": "failed", "success": False},
                    "trace_metadata": {"task_id": task.task_id, "task_type": task.task_type},
                }
                if existing is not None:
                    trace_repo.update(existing, payload)
                else:
                    trace_repo.create(payload)
                goal = GoalSpecRepository(session).get(goal_spec_id) if goal_spec_id else None
                if goal is not None:
                    GoalSpecRepository(session).update(
                        goal,
                        {
                            "status": "failed",
                            "summary": error,
                            "last_activity_at": utcnow(),
                        },
                    )
        except Exception:
            return

    def _build_operator_prompt(self, task: TaskEnvelope, result: AgentResult) -> str:
        task_label = self._humanize_task_label(task.task_type)
        if task.candidate_id:
            return f"{task_label} 在候选人上下文中暂停了。当前问题：{result.content or '需要你确认下一步处理方式。'}"
        return f"{task_label} 暂时无法继续。当前问题：{result.content or '需要你确认下一步处理方式。'}"

    def _build_operator_options(self, task: TaskEnvelope, result: AgentResult) -> list[dict[str, Any]]:
        options = [
            {
                "id": "confirm",
                "label": "继续执行",
                "action": "confirm",
                "description": "保留当前路径，恢复这个 run。",
            },
            {
                "id": "retry",
                "label": "重试一次",
                "action": "retry",
                "description": "按当前目标再试一次，并保留新的人工说明。",
            },
            {
                "id": "correct",
                "label": "给出纠偏意见",
                "action": "correct",
                "description": "输入新的方向，由模型据此继续执行。",
            },
            {
                "id": "teach",
                "label": "教给 Agent",
                "action": "teach",
                "description": "把这次经验记录为后续策略输入。",
            },
        ]
        if task.candidate_id:
            options.append(
                {
                    "id": "handoff",
                    "label": "我来接管候选人",
                    "action": "handoff",
                    "description": "停止当前自动路径，改由你手动处理这个候选人。",
                }
            )
        else:
            options.append(
                {
                    "id": "stop",
                    "label": "停止这条路径",
                    "action": "stop",
                    "description": "结束当前尝试，避免继续重复失败。",
                }
            )
        return options

    def _build_graph_projection_payload(self, *, task: TaskEnvelope, goal, result: AgentResult) -> dict[str, Any]:
        title = goal.title if goal is not None else self._humanize_task_label(task.task_type)
        blocked = result.status in {"waiting_human", "blocked"}
        stage_label = self._humanize_task_label(self._adaptive_stage_for_task(task))
        nodes = [
            {"id": "goal", "label": title, "kind": "goal", "state": "active"},
            {"id": "explore", "label": "探索执行路径", "kind": "phase", "state": "completed"},
            {"id": "execute", "label": stage_label, "kind": "phase", "state": "blocked" if blocked else ("completed" if result.success else "failed")},
        ]
        edges = [
            {"from": "goal", "to": "explore", "label": "意图拆解"},
            {"from": "explore", "to": "execute", "label": "实操尝试"},
        ]
        if blocked:
            nodes.append({"id": "operator", "label": "等待人工介入", "kind": "operator", "state": "pending"})
            edges.append({"from": "execute", "to": "operator", "label": "触发确认"})
        elif result.success:
            nodes.append({"id": "distill", "label": "沉淀策略与记忆", "kind": "learning", "state": "completed"})
            edges.append({"from": "execute", "to": "distill", "label": "提炼结果"})
        rendered = "\n".join(
            [
                "graph TD",
                '  goal["目标"] --> explore["探索路径"]',
                f'  explore --> execute["{stage_label}"]',
                '  execute --> operator["人工介入"]' if blocked else '  execute --> distill["策略沉淀"]',
            ]
        )
        return {
            "goal_spec_id": goal.id if goal is not None else str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "") or None,
            "run_id": str(task.metadata.get("agent_run_id") or "") or None,
            "candidate_id": task.candidate_id,
            "graph_kind": "execution_projection",
            "title": title,
            "summary": result.content or f"{title} 当前状态为 {result.status}。",
            "nodes": nodes,
            "edges": edges,
            "rendered_text": rendered,
            "graph_metadata": {
                "result_status": result.status,
                "task_type": task.task_type,
            },
        }

    def _goal_status_from_result(self, result: AgentResult) -> str:
        if result.status in {"waiting_human", "waiting_candidate", "blocked"}:
            return "blocked"
        if result.success:
            return "active"
        if result.status in {"failed", "rejected", "cancelled"}:
            return "failed"
        return result.status or "active"

    def _strategy_fragment_summary(self, *, task: TaskEnvelope, result: AgentResult) -> str:
        base = result.content or self._next_step_hint(result.status)
        return f"{self._humanize_task_label(self._adaptive_stage_for_task(task))}：{base}"

    def _next_step_hint(self, status: str) -> str:
        if status == "waiting_human":
            return "等待人工确认后继续。"
        if status == "waiting_candidate":
            return "等待候选人响应后继续。"
        if status == "completed":
            return "已完成当前尝试，可继续扩展执行范围。"
        if status == "failed":
            return "需要换一条路径或补充新的操作线索。"
        return "继续观察结果并决定下一步。"

    def _humanize_task_label(self, task_type: str) -> str:
        return str(task_type or "task").replace("_", " ").strip().title()

    def _task_snapshot(self, task: TaskEnvelope) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "adaptive_stage": self._adaptive_stage_for_task(task),
            "priority": task.priority,
            "payload": dict(task.payload or {}),
            "metadata": dict(task.metadata or {}),
            "candidate_id": task.candidate_id,
            "platform": task.platform,
            "attempts": task.attempts,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "created_at": task.created_at.isoformat(),
        }

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
            return f"已为 {skill_name.strip()} 生成运行时 skill 草案。"

        return f"已为 {task.task_type} 捕获运行时学习结果。"

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
            "summary": result.content or "任务已暂停，等待人工审查。",
            "reason": result.content or "需要人工审查。",
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

    def _next_tasks_for_result(self, task: TaskEnvelope, result: AgentResult) -> list[TaskEnvelope]:
        if result.status in {"waiting_human", "waiting_candidate", "blocked"}:
            return []
        follow_up_stage = self._next_adaptive_stage(task, result)
        if not follow_up_stage:
            return []
        payload = {
            **dict(task.payload or {}),
            "source_task_id": task.task_id,
            "source_task_type": task.task_type,
            "previous_result_status": result.status,
            "previous_result_success": result.success,
        }
        metadata = {
            **dict(task.metadata or {}),
            "adaptive_stage": follow_up_stage,
            "requested_by": task.metadata.get("requested_by") or "runtime",
            "spawn_new_run": True,
        }
        for transient_key in (
            "agent_run_id",
            "agent_work_item_id",
            "context_manifest",
            "checkpoint_id",
            "approval_id",
        ):
            metadata.pop(transient_key, None)
        if follow_up_stage == "strategy_distill":
            payload["strategy_distill"] = {
                "from_task_type": task.task_type,
                "from_stage": self._adaptive_stage_for_task(task),
                "result_status": result.status,
                "result_summary": result.content,
            }
        return [
            TaskEnvelope(
                task_id=f"{task.task_id}:{follow_up_stage}",
                task_type=follow_up_stage,
                candidate_id=task.candidate_id,
                priority=max(task.priority - 1, 1),
                payload=payload,
                metadata=metadata,
                platform=task.platform,
            )
        ]

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

    def _blocked_task_title(self, task: TaskEnvelope) -> str:
        node = self._adaptive_stage_for_task(task) or task.task_type
        if task.candidate_id:
            return f"Resume blocked task for {task.candidate_id}: {node}"
        return f"Resume blocked task: {node}"

    def _adaptive_stage_for_task(self, task: TaskEnvelope) -> str:
        explicit = str(task.metadata.get("adaptive_stage") or task.payload.get("adaptive_stage") or "").strip()
        if explicit:
            return explicit
        return resolve_adaptive_stage(task_type=task.task_type, explicit_stage=explicit or None)

    def _next_adaptive_stage(self, task: TaskEnvelope, result: AgentResult) -> str | None:
        current = self._adaptive_stage_for_task(task)
        if current == "goal_intake":
            run_preferences = dict(task.payload.get("run_preferences") or {})
            context_hints = dict(task.payload.get("context_hints") or {})
            preferred = str(
                run_preferences.get("initial_stage")
                or context_hints.get("adaptive_stage")
                or "exploration_trial"
            ).strip()
            return preferred or "exploration_trial"
        if current in {
            "exploration_trial",
            "candidate_discovery",
            "candidate_probe",
            "candidate_outreach",
            "resume_collection",
            "candidate_scoring",
            "candidate_archive",
            "scale_execution",
        }:
            return "strategy_distill"
        return None
