from __future__ import annotations

import json
import re
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
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
    ApplicationSessionRepository,
    CandidateApplicationRepository,
    ExecutionGraphProjectionRepository,
    ExecutionTraceRepository,
    GoalSpecRepository,
    JobDescriptionRepository,
    OperatorInteractionRepository,
    ApprovalRepository,
    CandidateRepository,
    CandidateSessionRepository,
    CommunicationLogRepository,
    DecisionLogRepository,
    EvolutionArtifactRepository,
    SkillRepository,
    ResumeArtifactRepository,
    StrategyFragmentRepository,
    TaskQueueRepository,
)
from scene_pilot.runtime.agent_loop import AgentLoop
from scene_pilot.runtime.models import AgentResult, ToolExecutionResult
from scene_pilot.runtime.result_semantics import extract_business_status
from scene_pilot.scheduler.queue import TaskEnvelope
from scene_pilot.scheduler.scheduler import ScheduledOutcome, SerialScheduler
from scene_pilot.schemas import CandidateStateTransitionRequest, TaskCompileRequest
from scene_pilot.services.context_assembler import ContextAssemblerService
from scene_pilot.services.candidate_progression_selector import (
    ApplicationProgressionTarget,
    select_next_application_progression,
)
from scene_pilot.services.candidate_identity import resolve_candidate_by_contact_info, resolve_candidate_by_platform_identity
from scene_pilot.services.candidate_waiting_retry_selector import (
    ApplicationWaitingRetryPolicy,
    ApplicationWaitingRetryTarget,
    select_waiting_application_retry_action,
)
from scene_pilot.services.events import EventStreamService
from scene_pilot.services.feature_flags import FeatureFlagService
from scene_pilot.services.adaptive_runtime import resolve_adaptive_stage
from scene_pilot.services.application_window import make_application_window
from scene_pilot.services.recruit_agent import (
    default_candidate_state_snapshot,
    ensure_primary_recruit_agent_profile,
    validate_evolution_artifact,
)
from scene_pilot.services.runtime_control import RuntimeControlService
from scene_pilot.services.state_machine import (
    StateMachineValidationError,
    ensure_latest_state_machine,
    resolve_candidate_current_status,
    transition_candidate,
)
from scene_pilot.services.skills import SkillHealthCheckService
from scene_pilot.services.sync import SyncService
from scene_pilot.services.runtime import PersistedRuntimeService


def _json_default(value: Any) -> Any:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def _json_ready(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


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
    _state_machine_cache: dict[str, Any] | None = None
    _autonomy_sourcing_backoff_until: float = field(default=0.0, init=False, repr=False)
    _autonomy_candidate_backoff_until: float = field(default=0.0, init=False, repr=False)

    def enqueue_task(
        self,
        task_type: str,
        *,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        application_id: str | None = None,
        candidate_id: str | None = None,
    ) -> TaskEnvelope:
        resolved_application_id = str(
            application_id
            or (payload or {}).get("application_id")
            or (payload or {}).get("applicationId")
            or (metadata or {}).get("application_id")
            or (metadata or {}).get("applicationId")
            or ""
        ).strip() or None
        resolved_candidate_id = str(candidate_id or "").strip() or None
        if resolved_application_id and resolved_candidate_id == resolved_application_id:
            resolved_candidate_id = None
        adaptive_stage = resolve_adaptive_stage(
            task_type=task_type,
            explicit_stage=str((metadata or {}).get("adaptive_stage") or (payload or {}).get("adaptive_stage") or "").strip() or None,
        )
        task = TaskEnvelope(
            task_id=task_id or uuid4().hex,
            task_type=adaptive_stage,
            payload=payload or {},
            priority=priority,
            application_id=resolved_application_id,
            candidate_id=resolved_candidate_id,
            metadata={**(metadata or {}), "adaptive_stage": adaptive_stage, "application_id": resolved_application_id},
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

    def _autonomy_min_funnel_candidates(self) -> int:
        raw_value = dict(self.settings.provider_config or {}).get("autonomy_min_funnel_candidates", 0)
        try:
            return max(int(raw_value or 0), 0)
        except (TypeError, ValueError):
            return 0

    def _autonomy_sourcing_cooldown_seconds(self) -> float:
        raw_value = dict(self.settings.provider_config or {}).get("autonomy_sourcing_cooldown_seconds", 60)
        try:
            return max(float(raw_value or 60), 1.0)
        except (TypeError, ValueError):
            return 60.0

    def _autonomy_candidate_cooldown_seconds(self) -> float:
        raw_value = dict(self.settings.provider_config or {}).get("autonomy_candidate_progress_cooldown_seconds", 10)
        try:
            return max(float(raw_value or 10), 1.0)
        except (TypeError, ValueError):
            return 10.0

    def _autonomy_funnel_status_ids(self, state_machine: dict[str, Any] | None) -> list[str]:
        if not state_machine:
            return []
        status_ids: list[str] = []
        for node in list(state_machine.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue
            ui_config = dict(node.get("uiConfig") or node.get("ui_config") or {})
            if not bool(ui_config.get("showInFunnel")):
                continue
            if bool(node.get("isTerminal")) or bool(node.get("isSoftTerminal")) or bool(node.get("isTransient")):
                continue
            status_ids.append(node_id)
        return status_ids

    def _autonomy_candidate_progression_task_types(self) -> list[str]:
        return [
            "candidate_probe",
            "candidate_outreach",
            "resume_collection",
            "candidate_scoring",
            "candidate_archive",
        ]

    def maybe_enqueue_autonomous_sourcing(self) -> TaskEnvelope | None:
        minimum_candidates = self._autonomy_min_funnel_candidates()
        if minimum_candidates <= 0 or self.session_factory is None:
            return None

        now = time.monotonic()
        if now < self._autonomy_sourcing_backoff_until:
            return None

        candidate_count = 0
        with self.session_factory() as session:
            state_machine = ensure_latest_state_machine(session)
            funnel_status_ids = self._autonomy_funnel_status_ids(state_machine)
            if not funnel_status_ids:
                return None
            candidate_count = CandidateApplicationRepository(session).count_by_current_statuses(funnel_status_ids)
            if candidate_count >= minimum_candidates:
                return None
            if TaskQueueRepository(session).has_open_task_types(["candidate_discovery"]):
                return None

        discovery_task = TaskEnvelope(
            task_id=uuid4().hex,
            task_type="candidate_discovery",
            priority=180,
            payload={
                "autonomy_source": "low_funnel_supply",
                "minimum_candidates": minimum_candidates,
                "observed_funnel_candidates": candidate_count,
            },
            metadata={
                "adaptive_stage": "candidate_discovery",
                "autonomy_trigger": "low_funnel_supply",
                "minimum_candidates": minimum_candidates,
                "observed_funnel_candidates": candidate_count,
            },
        )
        missing_capabilities = self._missing_external_capabilities(discovery_task)
        if missing_capabilities:
            self._autonomy_sourcing_backoff_until = now + self._autonomy_sourcing_cooldown_seconds()
            self.events.publish(
                "warning",
                "autonomy",
                "Autonomous sourcing skipped because required capabilities are unavailable.",
                missing_capabilities=missing_capabilities,
                minimum_candidates=minimum_candidates,
                observed_funnel_candidates=candidate_count,
            )
            return None

        queued_task = self.enqueue_task(
            "candidate_discovery",
            payload=dict(discovery_task.payload),
            metadata=dict(discovery_task.metadata),
            priority=discovery_task.priority,
        )
        self._autonomy_sourcing_backoff_until = now + self._autonomy_sourcing_cooldown_seconds()
        self.events.publish(
            "info",
            "autonomy",
            "Autonomous sourcing queued because funnel supply is below threshold.",
            minimum_candidates=minimum_candidates,
            observed_funnel_candidates=candidate_count,
            task_id=queued_task.task_id,
        )
        return queued_task

    def maybe_enqueue_priority_candidate_progression(self) -> TaskEnvelope | None:
        if self.session_factory is None:
            return None

        now = time.monotonic()
        if now < self._autonomy_candidate_backoff_until:
            return None

        selection = None
        selected_application_id = ""
        selected_status = ""
        application_name = ""
        with self.session_factory() as session:
            queue_repo = TaskQueueRepository(session)
            state_machine = ensure_latest_state_machine(session)
            nodes = list(state_machine.get("nodes") or [])
            node_by_id = {
                str(node.get("id") or "").strip(): dict(node)
                for node in nodes
                if str(node.get("id") or "").strip()
            }
            open_application_ids = queue_repo.open_candidate_ids_for_task_types(self._autonomy_candidate_progression_task_types())
            targets: list[ApplicationProgressionTarget] = []
            application_names: dict[str, str] = {}
            application_repo = CandidateApplicationRepository(session)
            candidate_repo = CandidateRepository(session)
            for application in application_repo.list(limit=500):
                current_status = str(application.current_status or "").strip()
                node = node_by_id.get(current_status)
                if node is None:
                    continue
                application_business_id = str(
                    getattr(application, "candidate_application_id", None) or getattr(application, "id", "") or ""
                ).strip()
                if not application_business_id:
                    continue
                execution_config = dict(node.get("executionConfig") or {})
                person = candidate_repo.resolve(application.person_id)
                application_names[application_business_id] = str(getattr(person, "name", "") or "")
                targets.append(
                    ApplicationProgressionTarget(
                        application_id=application_business_id,
                        current_status=current_status,
                        node_id=str(node.get("id") or current_status),
                        node_label=str(node.get("label") or current_status),
                        phase=str(node.get("phase") or ""),
                        default_waiting_party=str(node.get("defaultWaitingParty") or ""),
                        sort_order=int(node.get("sortOrder") or node.get("sort_order") or 0),
                        ai_scores=dict(getattr(application, "ai_scores", None) or {}),
                        is_terminal=bool(node.get("isTerminal")),
                        is_soft_terminal=bool(node.get("isSoftTerminal")),
                        is_transient=bool(node.get("isTransient")),
                        effective_execution_mode=str(execution_config.get("mode") or "none").strip() or "none",
                        locked=bool(execution_config.get("locked")),
                        created_at=getattr(application, "created_at", None),
                        updated_at=getattr(application, "updated_at", None),
                        last_contacted_at=getattr(application, "last_contacted_at", None),
                        cooldown_until=getattr(application, "cooldown_until", None),
                        has_open_task=(
                            application_business_id in open_application_ids
                            or str(getattr(application, "id", "") or "") in open_application_ids
                        ),
                    )
                )
            selection = select_next_application_progression(targets)
            if selection is None:
                return None
            selected_application_id = selection.application_id
            selected_status = selection.current_status
            application_name = application_names.get(selection.application_id, "")

        if selection is None:
            return None

        task_type = selection.selected_task_type
        priority = 140 + int(round(float(selection.score_breakdown.total) * 100))
        score_breakdown = asdict(selection.score_breakdown)
        task = TaskEnvelope(
            task_id=uuid4().hex,
            task_type=task_type,
            application_id=selected_application_id,
            priority=priority,
            payload={
                "autonomy_source": "candidate_priority_queue",
                "current_status": selected_status,
                "selection": {
                    "applicationId": selection.application_id,
                    "selectedTaskType": selection.selected_task_type,
                    "scoreBreakdown": score_breakdown,
                    "reason": selection.reason,
                },
            },
            metadata={
                "adaptive_stage": task_type,
                "autonomy_trigger": "candidate_priority_queue",
                "candidate_priority_score": round(float(selection.score_breakdown.total), 4),
                "candidate_priority_components": score_breakdown,
                "candidate_priority_reason": selection.reason,
                "state_machine_current_status": selected_status,
                "state_machine_node_label": selection.node_label,
                "state_machine_node_id": selection.node_id,
            },
        )
        missing_capabilities = self._missing_external_capabilities(task)
        if missing_capabilities:
            self._autonomy_candidate_backoff_until = now + self._autonomy_candidate_cooldown_seconds()
            self.events.publish(
                "warning",
                "autonomy",
                "Candidate priority scheduling skipped because required capabilities are unavailable.",
                missing_capabilities=missing_capabilities,
                application_id=selected_application_id,
                task_type=task_type,
                reason=selection.reason,
            )
            return None

        queued_task = self.enqueue_task(
            task_type,
            application_id=selected_application_id,
            payload=dict(task.payload),
            metadata=dict(task.metadata),
            priority=priority,
        )
        self._autonomy_candidate_backoff_until = now + self._autonomy_candidate_cooldown_seconds()
        self.events.publish(
            "info",
            "autonomy",
            "Queued priority candidate progression task.",
            application_id=selected_application_id,
            candidate_name=application_name,
            task_type=task_type,
            priority=priority,
            candidate_priority_score=round(float(selection.score_breakdown.total), 4),
            candidate_priority_reason=selection.reason,
            score_breakdown=score_breakdown,
        )
        return queued_task

    def maybe_process_waiting_candidate_retry(self) -> TaskEnvelope | dict[str, Any] | None:
        if self.session_factory is None:
            return None

        now = time.monotonic()
        if now < self._autonomy_candidate_backoff_until:
            return None

        selected_action = None
        selected_person_name = ""
        selected_policy: dict[str, int] | None = None
        with self.session_factory() as session:
            queue_repo = TaskQueueRepository(session)
            application_repo = CandidateApplicationRepository(session)
            candidate_repo = CandidateRepository(session)
            state_machine = ensure_latest_state_machine(session)
            nodes = list(state_machine.get("nodes") or [])
            node_by_id = {
                str(node.get("id") or "").strip(): dict(node)
                for node in nodes
                if str(node.get("id") or "").strip()
            }
            waiting_status_ids = [
                node_id
                for node_id, node in node_by_id.items()
                if str(node.get("defaultWaitingParty") or "").strip() == "CANDIDATE"
                and not bool(node.get("isTerminal"))
                and not bool(node.get("isSoftTerminal"))
                and not bool(node.get("isTransient"))
                and self._state_machine_retry_policy(node) is not None
            ]
            if not waiting_status_ids:
                return None

            open_application_ids = queue_repo.open_candidate_ids_for_task_types(self._autonomy_candidate_progression_task_types())
            targets: list[ApplicationWaitingRetryTarget] = []
            person_names: dict[str, str] = {}
            for application in application_repo.by_current_statuses(waiting_status_ids, limit=500):
                current_status = str(application.current_status or "").strip()
                node = node_by_id.get(current_status)
                retry_policy = self._state_machine_retry_policy(node)
                if node is None or retry_policy is None:
                    continue
                application_business_id = str(
                    getattr(application, "candidate_application_id", None) or getattr(application, "id", "") or ""
                ).strip()
                if not application_business_id:
                    continue
                person = candidate_repo.resolve(application.person_id)
                person_names[application_business_id] = str(getattr(person, "name", "") or "")
                retry_state = self._candidate_retry_state(application, current_status=current_status)
                try:
                    retry_count = max(int(retry_state.get("retry_count") or 0), 0)
                except (TypeError, ValueError):
                    retry_count = 0
                targets.append(
                    ApplicationWaitingRetryTarget(
                        application_id=application_business_id,
                        current_status=current_status,
                        node_id=str(node.get("id") or current_status),
                        node_label=str(node.get("label") or current_status),
                        retry_policy=ApplicationWaitingRetryPolicy(
                            max_retries=int(retry_policy["maxRetries"]),
                            retry_after_hours=int(retry_policy["retryAfterHours"]),
                            close_after_hours=int(retry_policy["closeAfterHours"]),
                        ),
                        current_retry_count=retry_count,
                        is_terminal=bool(node.get("isTerminal")),
                        is_soft_terminal=bool(node.get("isSoftTerminal")),
                        is_transient=bool(node.get("isTransient")),
                        has_open_task=(
                            application_business_id in open_application_ids
                            or str(getattr(application, "id", "") or "") in open_application_ids
                        ),
                        created_at=getattr(application, "created_at", None),
                        updated_at=getattr(application, "updated_at", None),
                        last_contacted_at=getattr(application, "last_contacted_at", None),
                    )
                )

            selected_action = select_waiting_application_retry_action(targets)
            if selected_action is None:
                return None

            selected_person_name = person_names.get(selected_action.application_id, "")
            selected_policy = self._state_machine_retry_policy(node_by_id.get(selected_action.current_status))
            if selected_action.action_kind == "close":
                application = application_repo.get(selected_action.application_id)
                if application is None:
                    return None
                candidate = candidate_repo.resolve(application.person_id)
                if candidate is None:
                    return None
                transition_result = transition_candidate(
                    session,
                    candidate=candidate,
                    application=application,
                    payload=CandidateStateTransitionRequest(
                        to_status="no_response",
                        note="超过重试上限且在配置时限内仍未收到回复，自动关闭为无回复。",
                        source="agent",
                        actor="agent",
                        actor_id="runtime",
                        trigger="retry_policy_timeout",
                        metadata={
                            "retry_policy": dict(selected_policy or {}),
                            "retry_state": {
                                "current_retry_count": selected_action.current_retry_count,
                                "hours_since_contact": selected_action.hours_since_contact,
                            },
                        },
                    ),
                )
                candidate = candidate_repo.resolve(transition_result.candidate_id) or candidate
                application = application_repo.get(selected_action.application_id) or application
                self._set_candidate_retry_state(
                    application,
                    status="no_response",
                    retry_count=selected_action.current_retry_count,
                    last_outbound_at=getattr(application, "last_contacted_at", None),
                    policy=selected_policy,
                    closed_at=utcnow(),
                    close_reason="retry_policy_timeout",
                )
                session.commit()
                session.refresh(application)

        if selected_action is None:
            return None

        if selected_action.action_kind == "close":
            self._autonomy_candidate_backoff_until = now + self._autonomy_candidate_cooldown_seconds()
            self.events.publish(
                "info",
                "autonomy",
                "Closed waiting candidate into no_response after retry policy exhaustion.",
                application_id=selected_action.application_id,
                candidate_name=selected_person_name,
                current_status=selected_action.current_status,
                reason=selected_action.reason,
                current_retry_count=selected_action.current_retry_count,
                hours_since_contact=selected_action.hours_since_contact,
            )
            return {
                "action": "close_to_no_response",
                "application_id": selected_action.application_id,
                "current_status": selected_action.current_status,
                "reason": selected_action.reason,
            }

        task_type = str(selected_action.selected_task_type or "").strip()
        if not task_type:
            return None
        priority = 220 + int(selected_action.next_retry_count or 0) * 10
        retry_payload = {
            "autonomy_source": "waiting_candidate_retry",
            "current_status": selected_action.current_status,
            "retryContext": {
                "sourceStatus": selected_action.current_status,
                "retryCount": int(selected_action.next_retry_count or 0),
                "maxRetries": int((selected_policy or {}).get("maxRetries") or 0),
                "retryAfterHours": int((selected_policy or {}).get("retryAfterHours") or 0),
                "closeAfterHours": int((selected_policy or {}).get("closeAfterHours") or 0),
                "reason": selected_action.reason,
            },
        }
        retry_metadata = {
            "adaptive_stage": task_type,
            "autonomy_trigger": "waiting_candidate_retry",
            "state_machine_current_status": selected_action.current_status,
            "state_machine_node_label": selected_action.node_label,
            "state_machine_node_id": selected_action.node_id,
            "retry_policy_reason": selected_action.reason,
            "retry_policy_retry_count": int(selected_action.next_retry_count or 0),
        }
        queued_task = self.enqueue_task(
            task_type,
            application_id=selected_action.application_id,
            payload=retry_payload,
            metadata=retry_metadata,
            priority=priority,
        )
        self._autonomy_candidate_backoff_until = now + self._autonomy_candidate_cooldown_seconds()
        self.events.publish(
            "info",
            "autonomy",
            "Queued waiting candidate retry task.",
            application_id=selected_action.application_id,
            candidate_name=selected_person_name,
            task_type=task_type,
            current_status=selected_action.current_status,
            reason=selected_action.reason,
            retry_count=int(selected_action.next_retry_count or 0),
            hours_since_contact=selected_action.hours_since_contact,
        )
        return queued_task

    def _load_state_machine_snapshot(self) -> dict[str, Any] | None:
        cached_snapshot = dict((self._state_machine_cache or {}).get("payload") or {})
        if self.session_factory is None:
            return cached_snapshot or None
        with self.session_factory() as session:
            snapshot = ensure_latest_state_machine(session)
        normalized = _json_ready(snapshot)
        version = int(normalized.get("version") or 0)
        cached_version = int((self._state_machine_cache or {}).get("version") or 0)
        if self._state_machine_cache is None or cached_version != version:
            self._state_machine_cache = {
                "version": version,
                "payload": normalized,
            }
        return dict((self._state_machine_cache or {}).get("payload") or {})

    def _state_machine_node(self, state_machine: dict[str, Any] | None, status: str | None) -> dict[str, Any] | None:
        if not state_machine or not status:
            return None
        for node in list(state_machine.get("nodes") or []):
            if str(node.get("id") or "").strip() == str(status).strip():
                return dict(node)
        return None

    def _state_machine_criteria_ref(self, session_context: dict[str, Any] | None) -> dict[str, Any] | None:
        state_machine = dict((session_context or {}).get("state_machine") or {})
        criteria_ref = dict(state_machine.get("criteria_ref") or {})
        return criteria_ref or None

    def _state_machine_execution_mode(self, session_context: dict[str, Any] | None) -> str | None:
        state_machine = dict((session_context or {}).get("state_machine") or {})
        execution_mode = str(state_machine.get("execution_mode") or "").strip()
        return execution_mode or None

    def _state_machine_human_actions(self, session_context: dict[str, Any] | None) -> list[dict[str, Any]]:
        state_machine = dict((session_context or {}).get("state_machine") or {})
        actions = []
        for action in list(state_machine.get("human_actions") or []):
            if not isinstance(action, dict):
                continue
            actions.append(dict(action))
        return actions

    def _sync_task_state_machine_metadata(
        self,
        task: TaskEnvelope,
        *,
        session_context: dict[str, Any] | None,
    ) -> None:
        state_machine = dict((session_context or {}).get("state_machine") or {})
        if not state_machine:
            return
        task.metadata["state_machine_version"] = state_machine.get("version")
        task.metadata["state_machine_current_status"] = state_machine.get("current_status")
        current_node = dict(state_machine.get("current_node") or {})
        if current_node.get("label"):
            task.metadata["state_machine_node_label"] = current_node.get("label")
        if state_machine.get("execution_mode"):
            task.metadata["state_machine_execution_mode"] = state_machine.get("execution_mode")
        task.metadata["state_machine_locked"] = bool(current_node.get("executionConfig", {}).get("locked"))
        if state_machine.get("criteria_ref"):
            task.metadata["state_machine_criteria_ref"] = dict(state_machine.get("criteria_ref") or {})
        task.metadata["state_machine_human_actions"] = list(state_machine.get("human_actions") or [])

    def _state_machine_milestone_for_status(self, state_machine: dict[str, Any] | None, status: str | None) -> str | None:
        node = self._state_machine_node(state_machine, status)
        if node is None:
            return None
        milestone_id = str(node.get("milestoneId") or node.get("milestone_id") or "").strip()
        return milestone_id or None

    def _agent_transition_candidate(
        self,
        session: Session,
        *,
        task: TaskEnvelope,
        candidate: Any,
        application: Any | None = None,
        to_status: str,
        stage_key: str | None = None,
        stage_label: str | None = None,
        note: str | None = None,
        trigger: str | None = None,
        override_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
        contact_channels: list[str] | None = None,
        interview_round: int | None = None,
    ):
        if application is None:
            application_id = str(task.application_id or task.metadata.get("application_id") or task.candidate_id or "").strip()
            if application_id:
                application = CandidateApplicationRepository(session).get(application_id)
        criteria_ref = dict(task.metadata.get("state_machine_criteria_ref") or {})
        trigger_fallback = str(task.task_type or self._adaptive_stage_for_task(task) or "").strip() or "agent_transition"
        transition_metadata = {
            **dict(metadata or {}),
            "task_id": task.task_id,
            "task_type": task.task_type,
            "adaptive_stage": self._adaptive_stage_for_task(task),
            "state_machine_version": task.metadata.get("state_machine_version"),
        }
        if criteria_ref:
            transition_metadata["criteria_ref"] = criteria_ref
        payload = CandidateStateTransitionRequest(
            to_status=to_status,
            stage_key=stage_key,
            stage_label=stage_label,
            note=note,
            source="agent",
            actor="agent_override" if override_reason else "agent",
            actor_id="runtime",
            trigger=trigger,
            override_reason=override_reason,
            metadata=transition_metadata,
            interview_round=interview_round,
            contact_channels=contact_channels,
        )
        transition_result = transition_candidate(session, candidate=candidate, application=application, payload=payload)
        matched_transition = dict(transition_result.matched_transition or {})
        transition_record = transition_result.transition_record
        transition_record.trigger = str(
            trigger
            or matched_transition.get("label")
            or matched_transition.get("condition")
            or trigger_fallback
        )
        transition_record.transition_metadata = {
            **{
                key: value
                for key, value in dict(transition_record.transition_metadata or {}).items()
                if value is not None
            },
            **({"criteria_ref": criteria_ref} if criteria_ref else {}),
        }
        session.commit()
        session.refresh(transition_record)
        return transition_result

    def _candidate_waiting_result(self, task: TaskEnvelope, *, session_context: dict[str, Any] | None) -> AgentResult | None:
        state_machine = dict((session_context or {}).get("state_machine") or {})
        execution_mode = str(state_machine.get("execution_mode") or "").strip()
        if execution_mode != "human_required":
            return None
        current_node = dict(state_machine.get("current_node") or {})
        label = str(current_node.get("label") or state_machine.get("current_status") or task.task_type)
        description = str(current_node.get("description") or "").strip()
        waiting_message = f"{label} 节点要求人工处理。"
        if description:
            waiting_message = f"{waiting_message} {description}"
        if current_node.get("executionConfig", {}).get("locked"):
            waiting_message = f"{waiting_message} 当前节点已锁定，Agent 不会直接执行。"
        return AgentResult(
            success=False,
            status="waiting_human",
            content=waiting_message,
            data={
                "status": str(state_machine.get("current_status") or ""),
                "state_machine_version": state_machine.get("version"),
                "execution_mode": execution_mode,
            },
            metadata={
                "state_machine_gate": {
                    "current_status": state_machine.get("current_status"),
                    "node_label": current_node.get("label"),
                    "execution_mode": execution_mode,
                    "locked": bool(current_node.get("executionConfig", {}).get("locked")),
                    "description": description or None,
                },
                "state_machine_human_actions": self._state_machine_human_actions(session_context),
            },
        )

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
            state_machine_snapshot = self._load_state_machine_snapshot()
            runtime_session = self._build_runtime_session(task, state_machine=state_machine_snapshot)
            self._sync_task_state_machine_metadata(task, session_context=runtime_session)
            runtime_skill = self._build_skill_context(task, session_context=runtime_session)
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
                self._persist_candidate_progression_evolution_artifact(
                    task,
                    result,
                    session_context=session_context_override if session_context_override is not None else runtime_session,
                    skill_context=runtime_skill,
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

                goal_intake_result = self._run_goal_intake(task)
                if goal_intake_result is not None:
                    return _complete(goal_intake_result)

                waiting_result = self._candidate_waiting_result(task, session_context=runtime_session)
                if waiting_result is not None:
                    return _complete(waiting_result)

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
                    token_budget=1_000_000,
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

    def _run_goal_intake(self, task: TaskEnvelope) -> AgentResult | None:
        if self._adaptive_stage_for_task(task) != "goal_intake":
            return None
        if self.session_factory is None or self.runtime_service_factory is None:
            return AgentResult(
                success=False,
                status="blocked",
                content="Goal intake requires a configured runtime service.",
                metadata={"blocked_reason": "runtime_service_unavailable"},
            )

        follow_up_stage = self._goal_intake_follow_up_stage(task)
        scene_snapshot, scene_metadata, tool_outputs = self._capture_goal_scene(task)

        try:
            with self.session_factory() as session:
                runtime_service = self.runtime_service_factory(session)
                compile_request = TaskCompileRequest(
                    instruction=str(task.payload.get("goal_text") or "").strip(),
                    title=str(task.payload.get("goal_title") or task.payload.get("title") or "").strip() or None,
                    description=f"Adaptive goal intake for stage {follow_up_stage}.",
                    domain_hint=str(task.payload.get("goal_kind") or "recruiting"),
                    inputs={
                        "goal_id": str(task.payload.get("goal_id") or "").strip() or None,
                        "context_hints": dict(task.payload.get("context_hints") or {}),
                        "run_preferences": dict(task.payload.get("run_preferences") or {}),
                        "trial_budget": dict(task.payload.get("trial_budget") or {}),
                    },
                    constraints=self._goal_intake_constraints(task, follow_up_stage=follow_up_stage),
                    success_criteria=self._goal_intake_success_criteria(task, follow_up_stage=follow_up_stage),
                    approval_policy={
                        "mode": "desktop_review",
                        "trial_required": True,
                        "requires_confirmation_before_production": True,
                        "requires_environment_snapshot": True,
                        "approval_actions": [],
                    },
                    output_contract=self._goal_intake_output_contract(follow_up_stage=follow_up_stage),
                    preferred_capabilities=self._goal_intake_capabilities(follow_up_stage=follow_up_stage),
                    preferred_domains=["recruiting", "general"],
                    auto_plan=False,
                    requested_by=str(task.metadata.get("requested_by") or "runtime"),
                )
                compiled = self._compile_goal_intake_task(
                    runtime_service,
                    compile_request=compile_request,
                )
                plan = runtime_service.compile_plan(
                    SimpleNamespace(
                        task_spec_id=compiled.task_spec.id,
                        playbook_version_id=None,
                        name=f"{compiled.task_spec.title} 试跑计划",
                        mode="trial",
                        status="planned",
                        compiled_from_instruction=compile_request.instruction,
                        environment_requirements={},
                        checkpoints=[],
                        runtime_metadata={
                            "compiler": getattr(compiled, "compiler_name", None) or "goal_intake",
                            "requested_by": compile_request.requested_by,
                            "follow_up_stage": follow_up_stage,
                            "goal_spec_id": str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "").strip() or None,
                            "scene_capture": scene_metadata,
                        },
                        steps=[],
                    )
                )
        except Exception as exc:
            return AgentResult(
                success=False,
                status="failed",
                content=f"Goal intake failed to compile an executable plan: {exc}",
                tool_outputs=tool_outputs,
                metadata={
                    "blocked_reason": "goal_compile_failed",
                    "follow_up_stage": follow_up_stage,
                    "scene_capture": scene_metadata,
                },
            )

        summary_bits = [f"已将目标编译为 {follow_up_stage} 的受管执行计划。"]
        if scene_metadata.get("url"):
            summary_bits.append(f"场景来自 {scene_metadata['url']}。")

        return AgentResult(
            success=True,
            status="completed",
            content=" ".join(summary_bits),
            data={
                "status": "managed_execution_ready",
                "follow_up_stage": follow_up_stage,
                "task_spec_id": compiled.task_spec.id,
                "execution_plan_id": plan.id,
                "scene_snapshot": scene_snapshot,
                "compiler_notes": list(compiled.compiler_notes or []),
            },
            tool_outputs=tool_outputs,
            metadata={
                "task_spec_id": compiled.task_spec.id,
                "execution_plan_id": plan.id,
                "follow_up_stage": follow_up_stage,
                "scene_capture": scene_metadata,
                "executor_trace": {
                    "plan_id": plan.id,
                    "task_spec_id": compiled.task_spec.id,
                    "turn_count": 0,
                    "goal_intake": {
                        "follow_up_stage": follow_up_stage,
                        "scene_capture": scene_metadata,
                        "compiler_notes": list(compiled.compiler_notes or []),
                    },
                },
            },
        )

    def _compile_goal_intake_task(
        self,
        runtime_service: PersistedRuntimeService,
        *,
        compile_request: TaskCompileRequest,
    ):
        compiled = runtime_service.compile_task(compile_request)
        return SimpleNamespace(
            task_spec=compiled.task_spec,
            compiler_notes=list(compiled.compiler_notes or []),
            compiler_name=str((compiled.task_spec.compiled_payload or {}).get("compiler") or "").strip() or "unknown",
        )

    def _goal_intake_follow_up_stage(self, task: TaskEnvelope) -> str:
        run_preferences = dict(task.payload.get("run_preferences") or {})
        context_hints = dict(task.payload.get("context_hints") or {})
        preferred = str(
            run_preferences.get("initial_stage")
            or context_hints.get("adaptive_stage")
            or "exploration_trial"
        ).strip()
        return preferred or "exploration_trial"

    def _goal_intake_capabilities(self, *, follow_up_stage: str) -> list[str]:
        stage_to_capabilities = {
            "exploration_trial": ["browser", "search", "document"],
            "candidate_discovery": ["browser", "document"],
            "candidate_probe": ["browser", "llm", "document"],
            "candidate_outreach": ["browser", "approval", "document"],
            "resume_collection": ["browser", "document"],
            "candidate_scoring": ["llm", "document"],
            "candidate_archive": ["browser", "approval", "document"],
            "scale_execution": ["browser", "document"],
        }
        return list(stage_to_capabilities.get(follow_up_stage, ["browser", "document"]))

    def _goal_intake_constraints(self, task: TaskEnvelope, *, follow_up_stage: str) -> dict[str, Any]:
        return {
            **dict(task.payload.get("constraints") or {}),
            "follow_up_stage": follow_up_stage,
            "read_only_browser": True,
            "do_not_send_messages": True,
            "do_not_mutate_source_site": True,
            "respect_registered_mcp_only": True,
        }

    def _goal_intake_success_criteria(self, task: TaskEnvelope, *, follow_up_stage: str) -> dict[str, Any]:
        criteria = {
            **dict(task.payload.get("success_criteria") or {}),
            "requires_resume_or_profile": True,
            "requires_score": False,
            "minimum_candidates": 1,
        }
        if follow_up_stage not in {"candidate_discovery", "exploration_trial"}:
            criteria.setdefault("task_completed", True)
        return criteria

    def _goal_intake_output_contract(self, *, follow_up_stage: str) -> dict[str, Any]:
        if follow_up_stage in {"candidate_discovery", "exploration_trial"}:
            return {
                "kind": "candidate_discovery",
                "fields": ["candidates", "summary", "evidence"],
                "minimum_candidates": 1,
            }
        return {"kind": "summary", "fields": ["summary", "evidence"]}

    def _capture_goal_scene(
        self,
        task: TaskEnvelope,
    ) -> tuple[dict[str, Any] | None, dict[str, Any], list[ToolExecutionResult]]:
        if self.agent_loop is None:
            return None, {}, []

        tool_outputs: list[ToolExecutionResult] = []
        active_tab = None
        if self.agent_loop.tools.has("browser_get_active_tab"):
            result = self.agent_loop.tools.execute("browser_get_active_tab", {})
            tool_outputs.append(result)
            if not result.is_error:
                active_tab = self._extract_browser_tab(result.output)

        if active_tab is None and self.agent_loop.tools.has("browser_list_tabs"):
            result = self.agent_loop.tools.execute("browser_list_tabs", {})
            tool_outputs.append(result)
            if not result.is_error:
                active_tab = self._select_browser_tab(self._extract_browser_tabs(result.output))

        if active_tab is None:
            return None, {"capture_status": "no_browser_tab"}, tool_outputs

        tab_id = active_tab.get("id")
        snapshot_payload: dict[str, Any] | None = None
        if self.agent_loop.tools.has("browser_snapshot") and isinstance(tab_id, int):
            result = self.agent_loop.tools.execute(
                "browser_snapshot",
                {
                    "tabId": tab_id,
                    "maxTextLength": 12000,
                    "interactiveLimit": 40,
                },
            )
            tool_outputs.append(result)
            if not result.is_error:
                snapshot_payload = self._extract_browser_snapshot(result.output)

        scene_snapshot = self._build_scene_snapshot(active_tab, snapshot_payload)
        return (
            scene_snapshot,
            {
                "capture_status": "captured" if scene_snapshot is not None else "no_snapshot",
                "tab_id": active_tab.get("id"),
                "title": active_tab.get("title"),
                "url": active_tab.get("url"),
            },
            tool_outputs,
        )

    def _extract_browser_tab(self, payload: Any) -> dict[str, Any] | None:
        raw = payload.get("tab") if isinstance(payload, dict) and isinstance(payload.get("tab"), dict) else payload
        if not isinstance(raw, dict):
            return None
        tab_id = raw.get("id", raw.get("tabId"))
        try:
            normalized_id = int(tab_id)
        except (TypeError, ValueError):
            normalized_id = None
        url = str(raw.get("url") or "").strip()
        title = str(raw.get("title") or "").strip()
        if normalized_id is None and not url and not title:
            return None
        return {
            "id": normalized_id,
            "title": title,
            "url": url,
            "active": bool(raw.get("active", True)),
        }

    def _extract_browser_tabs(self, payload: Any) -> list[dict[str, Any]]:
        raw_tabs = payload.get("tabs") if isinstance(payload, dict) else payload
        if not isinstance(raw_tabs, list):
            return []
        tabs: list[dict[str, Any]] = []
        for item in raw_tabs:
            tab = self._extract_browser_tab(item)
            if tab is not None:
                tabs.append(tab)
        return tabs

    def _select_browser_tab(self, tabs: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not tabs:
            return None

        def _sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
            url = str(item.get("url") or "")
            return (
                0 if item.get("active") else 1,
                0 if url.startswith(("http://", "https://")) else 1,
                0 if url else 1,
                str(item.get("title") or ""),
            )

        return sorted(tabs, key=_sort_key)[0]

    def _extract_browser_snapshot(self, payload: Any) -> dict[str, Any] | None:
        raw = payload.get("snapshot") if isinstance(payload, dict) and isinstance(payload.get("snapshot"), dict) else payload
        return dict(raw) if isinstance(raw, dict) else None

    def _build_scene_snapshot(
        self,
        tab: dict[str, Any],
        snapshot_payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not tab and not snapshot_payload:
            return None

        snapshot = dict(snapshot_payload or {})
        runtime_metadata = dict(snapshot.get("runtime_metadata") or {})
        if tab:
            runtime_metadata["active_tab"] = dict(tab)
        page_text = str(snapshot.get("text") or snapshot.get("page_text") or "").strip()
        if page_text:
            runtime_metadata["page_text_excerpt"] = page_text[:4000]
            runtime_metadata["page_text_length"] = len(page_text)

        observed_entities = list(snapshot.get("observed_entities") or [])
        if not observed_entities:
            observed_entities = self._infer_snapshot_observed_entities(tab=tab, snapshot=snapshot, page_text=page_text)
        affordances = list(snapshot.get("affordances") or [])
        if not affordances:
            affordances = self._snapshot_affordances_from_interactive_elements(snapshot)
        if affordances:
            runtime_metadata["interactive_element_count"] = len(affordances)
        url = str(snapshot.get("url") or tab.get("url") or "").strip()
        page_type = str(snapshot.get("page_type") or "").strip() or ("web_scene" if url else "browser_scene")
        environment_key = str(snapshot.get("environment_key") or "").strip() or f"browser:{page_type}"

        return {
            "source": "browser",
            "environment_key": environment_key,
            "status": str(snapshot.get("status") or "captured"),
            "url": url or None,
            "title": str(snapshot.get("title") or tab.get("title") or "").strip() or None,
            "page_type": page_type,
            "capability_hints": list(snapshot.get("capability_hints") or ["browser", "document"]),
            "observed_entities": observed_entities,
            "affordances": affordances,
            "runtime_metadata": runtime_metadata,
        }

    def _snapshot_affordances_from_interactive_elements(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        affordances: list[dict[str, Any]] = []
        for raw in list(snapshot.get("interactiveElements") or []):
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("text") or raw.get("label") or raw.get("name") or "").strip()
            href = str(raw.get("href") or raw.get("target") or "").strip()
            ref = str(raw.get("ref") or "").strip()
            if not label and not href and not ref:
                continue
            action = "navigate" if href.startswith(("http://", "https://")) else "click"
            affordances.append(
                {
                    "kind": str(raw.get("tag") or raw.get("type") or "element"),
                    "label": label or href or ref,
                    "action": action,
                    "target": href or None,
                    "requires_confirmation": self._snapshot_affordance_requires_confirmation(label),
                    "signals": ["browser_snapshot"],
                    "locator": {"ref": ref} if ref else {},
                    "rect": dict(raw.get("rect") or {}) if isinstance(raw.get("rect"), dict) else {},
                }
            )
        return affordances

    def _snapshot_affordance_requires_confirmation(self, label: str) -> bool:
        normalized = label.strip().lower()
        if not normalized:
            return False
        return any(
            token in normalized
            for token in (
                "发送",
                "投递",
                "约面试",
                "交换",
                "简历请求",
                "求简历",
                "换电话",
                "查看微信",
                "send",
                "submit",
                "upload",
                "request",
            )
        )

    def _infer_snapshot_observed_entities(
        self,
        *,
        tab: dict[str, Any],
        snapshot: dict[str, Any],
        page_text: str,
    ) -> list[dict[str, Any]]:
        title = str(snapshot.get("title") or tab.get("title") or "").strip()
        if not title:
            return []
        return [{"kind": "detail_panel", "label": title, "signals": []}]

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
                token_budget=1_000_000,
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
            "application_id": task.application_id,
            "candidate_id": task.candidate_id,
            "requires_real_environment": True,
        }

    def _build_runtime_session(
        self,
        task: TaskEnvelope,
        *,
        state_machine: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        application_id = str(task.application_id or task.payload.get("application_id") or task.metadata.get("application_id") or "").strip()
        if self.session_factory is None or (not application_id and not task.candidate_id):
            return {}

        with self.session_factory() as session:
            application = CandidateApplicationRepository(session).get(application_id) if application_id else None
            candidate_repo = CandidateRepository(session)
            candidate = candidate_repo.resolve(task.candidate_id) if task.candidate_id else None
            if candidate is None and application is not None:
                candidate = candidate_repo.resolve(application.person_id)
            if candidate is None:
                return {}
            job_description = (
                JobDescriptionRepository(session).get_by_internal_id(application.job_description_id)
                if application is not None and application.job_description_id
                else None
            )
            person_id = candidate.candidate_person_id
            application_business_id = (
                application.candidate_application_id
                if application is not None
                else application_id or person_id
            )
            job_description_id = job_description.job_description_id if job_description is not None else None

            state_machine_snapshot = dict(state_machine or self._load_state_machine_snapshot() or {})
            current_status = str(application.current_status if application is not None else resolve_candidate_current_status(candidate))
            current_node = self._state_machine_node(state_machine_snapshot, current_status)
            execution_config = dict((current_node or {}).get("executionConfig") or {})
            execution_mode = str(execution_config.get("mode") or "").strip() or None
            criteria_ref = dict(execution_config.get("criteriaRef") or {})
            raw_human_actions = (current_node or {}).get("humanActions") or execution_config.get("humanActions") or []
            human_actions = [
                dict(action)
                for action in list(raw_human_actions)
                if isinstance(action, dict)
            ]

            candidate_session = (
                ApplicationSessionRepository(session).get_or_create(
                    application.id,
                    defaults={
                        "status": "active",
                        "context_summary": (application.ai_reasoning if application is not None else None)
                        or f"{candidate.name} is currently in {current_status}.",
                        "facts": {},
                        "recent_messages": [],
                        "last_active_at": utcnow(),
                    },
                )
                if application is not None
                else CandidateSessionRepository(session).get_or_create(
                    person_id,
                    defaults={
                        "status": "active",
                        "context_summary": f"{candidate.name} is currently in {current_status}.",
                        "facts": {},
                        "recent_messages": [],
                        "last_active_at": utcnow(),
                    },
                )
            )
            candidate_session.last_active_at = utcnow()

            facts = dict(candidate_session.facts or {})
            adaptive_stage = self._adaptive_stage_for_task(task)
            facts.update(
                {
                    "application_id": application_business_id,
                    "candidate_status": current_status,
                    "current_status": current_status,
                    "goal_spec_id": str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "") or None,
                    "task_type": task.task_type,
                    "resume_available": bool(
                        application is not None
                        and (
                            bool((application.application_metadata or {}).get("resume_available"))
                            or bool((application.state_snapshot or {}).get("resume_available"))
                            or str((application.application_metadata or {}).get("resume_status") or "").strip().lower()
                            in {"received", "available", "ready", "present"}
                        )
                    ),
                    "state_machine_version": state_machine_snapshot.get("version"),
                    "execution_mode": execution_mode,
                }
            )
            if criteria_ref:
                facts["criteria_ref"] = criteria_ref
            if adaptive_stage == "strategy_distill":
                facts["last_learning_stage"] = adaptive_stage
            else:
                facts["adaptive_stage"] = adaptive_stage
            candidate_session.facts = facts
            session.commit()

            application_metadata = dict(application.application_metadata or {}) if application is not None else {}
            application_state = dict(application.state_snapshot or {}) if application is not None else {}
            resume_summary = (
                str(application_metadata.get("resume_summary") or "").strip()
                or str(application_state.get("latest_note") or "").strip()
                or str(application.ai_reasoning or "").strip()
                if application is not None
                else None
            )
            return {
                "candidate": {
                    "id": person_id,
                    "application_id": application_business_id,
                    "person_id": person_id,
                    "name": candidate.name,
                    "platform": (
                        application.source_platform
                        if application is not None and str(application.source_platform or "").strip()
                        else candidate.platform
                    ),
                    "source_platform_candidate_person_id": (
                        str(application.source_platform_candidate_person_id or "").strip()
                        if application is not None
                        else None
                    )
                    or None,
                    "current_status": current_status,
                    "current_stage_key": application.current_stage_key if application is not None else None,
                    "deepest_milestone": application.deepest_milestone if application is not None else None,
                    "job_description_id": job_description_id,
                    "contact_info": dict(candidate.contact_info or {}),
                    "resume_available": bool(facts.get("resume_available")),
                    "resume_summary": resume_summary,
                    "ai_scores": dict(application.ai_scores or {}) if application is not None else {},
                    "ai_reasoning": application.ai_reasoning if application is not None else None,
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
                "state_machine": {
                    "version": state_machine_snapshot.get("version"),
                    "current_status": current_status,
                    "current_node": current_node or {},
                    "execution_mode": execution_mode,
                    "criteria_ref": criteria_ref or None,
                    "human_actions": human_actions,
                },
            }

    def _build_skill_context(self, task: TaskEnvelope, *, session_context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if self.session_factory is None:
            return None

        preferred_skill_id = (
            task.payload.get("skill_id")
            or task.metadata.get("skill_id")
        )
        criteria_ref = self._state_machine_criteria_ref(session_context) or {}
        criteria_skill_id = (
            str(criteria_ref.get("skillId") or "").strip()
            if str(criteria_ref.get("type") or "").strip() == "skill"
            else ""
        )
        adaptive_stage = str(task.metadata.get("adaptive_stage") or "").strip() or self._adaptive_stage_for_task(task)

        with self.session_factory() as session:
            repo = SkillRepository(session)
            skill = None

            if isinstance(preferred_skill_id, str) and preferred_skill_id.strip():
                skill = repo.by_skill_id(preferred_skill_id.strip()) or repo.get(preferred_skill_id.strip())

            if skill is None and criteria_skill_id:
                skill = repo.by_skill_id(criteria_skill_id) or repo.get(criteria_skill_id)

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
                application_id = str(
                    task.application_id
                    or task.payload.get("application_id")
                    or task.metadata.get("application_id")
                    or task.candidate_id
                    or ""
                ).strip()
                application = CandidateApplicationRepository(session).get(application_id) if application_id else None
                candidate_repo = CandidateRepository(session)
                session_repo = CandidateSessionRepository(session)
                decision_repo = DecisionLogRepository(session)
                communication_repo = CommunicationLogRepository(session)

                candidate = candidate_repo.resolve(task.candidate_id) if task.candidate_id else None
                if candidate is None and application is not None:
                    candidate = candidate_repo.resolve(application.person_id)
                candidate_session = None
                adaptive_stage = self._adaptive_stage_for_task(task)
                learning_stage = adaptive_stage == "strategy_distill"
                persisted_candidate_ids = self._upsert_discovered_candidates(
                    session,
                    task=task,
                    result=result,
                    adaptive_stage=adaptive_stage,
                )
                if persisted_candidate_ids:
                    result.metadata["persisted_candidate_ids"] = list(persisted_candidate_ids)
                    if isinstance(result.data, dict):
                        result.data.setdefault("persisted_candidate_ids", list(persisted_candidate_ids))
                if candidate is not None:
                    candidate_session = session_repo.get_or_create(
                        candidate.candidate_person_id,
                        defaults={"status": "active", "facts": {}, "recent_messages": []},
                    )
                    business_status = extract_business_status(result.data) or result.status
                    if not learning_stage:
                        if application is not None:
                            application.current_stage_key = adaptive_stage
                            application.ai_reasoning = result.content or application.ai_reasoning

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
                    candidate = self._maybe_apply_candidate_rollback_signal(
                        session,
                        task=task,
                        result=result,
                        candidate=candidate,
                    )
                    if task.task_type == "candidate_scoring" and isinstance(result.data, dict) and result.success:
                        if application is not None:
                            application.ai_scores = dict(result.data)
                            application.ai_reasoning = result.content or application.ai_reasoning
                        self._append_progression_action(
                            result,
                            {
                                "kind": "score_update",
                                "task_type": task.task_type,
                                "candidate_id": candidate.candidate_person_id,
                                "score": result.data.get("overall") or result.data.get("score"),
                                "decision": result.data.get("decision") or result.data.get("status"),
                            },
                        )
                    if task.task_type == "candidate_outreach":
                        outbound_message = self._candidate_outreach_outbound_message(task=task, result=result)
                        if outbound_message:
                            candidate = self._record_waiting_candidate_outbound(
                                session,
                                task=task,
                                result=result,
                                candidate=candidate,
                                outbound_message=outbound_message,
                            )
                            communication_repo.create(
                                {
                                    "candidate_id": candidate.id,
                                    "direction": "outbound",
                                    "content": outbound_message,
                                    "message_type": "text",
                                    "platform": task.platform,
                                    "timestamp": utcnow(),
                                }
                            )
                            session_repo.append_recent_message(
                                candidate_session,
                                direction="outbound",
                                content=outbound_message,
                                metadata={"task_id": task.task_id, "task_type": task.task_type},
                            )
                            self._append_progression_action(
                                result,
                                {
                                    "kind": "outbound_message",
                                    "task_type": task.task_type,
                                    "candidate_id": candidate.candidate_person_id,
                                    "message_type": "text",
                                    "message": outbound_message,
                                },
                            )
                    elif task.task_type == "resume_collection":
                        resume_request_message = self._resume_collection_outbound_message(task=task, result=result)
                        if resume_request_message:
                            candidate = self._record_waiting_candidate_outbound(
                                session,
                                task=task,
                                result=result,
                                candidate=candidate,
                                outbound_message=resume_request_message,
                            )
                            communication_repo.create(
                                {
                                    "candidate_id": candidate.id,
                                    "direction": "outbound",
                                    "content": resume_request_message,
                                    "message_type": "resume_request",
                                    "platform": task.platform,
                                    "timestamp": utcnow(),
                                }
                            )
                            session_repo.append_recent_message(
                                candidate_session,
                                direction="outbound",
                                content=resume_request_message,
                                message_type="resume_request",
                                metadata={"task_id": task.task_id, "task_type": task.task_type},
                            )
                            self._append_progression_action(
                                result,
                                {
                                    "kind": "outbound_message",
                                    "task_type": task.task_type,
                                    "candidate_id": candidate.candidate_person_id,
                                    "message_type": "resume_request",
                                    "message": resume_request_message,
                                },
                            )

                    decision_value = str(extract_business_status(result.data) or result.status or "completed")
                    if decision_value and not learning_stage:
                        decision_repo.create(
                            {
                                "candidate_id": candidate.candidate_person_id,
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
            result.metadata["artifact_persist_error"] = str(exc)
            self.events.publish(
                "error",
                "runtime",
                "Failed to persist runtime execution artifacts.",
                task_id=task.task_id,
                error=str(exc),
                traceback=traceback.format_exc(),
            )

    def _enqueue_sync(self, item_type: str, item_id: str, payload: dict[str, Any]) -> None:
        if self.sync_service is None or not self.sync_service.intranet_enabled:
            return
        self.sync_service.enqueue(item_type, item_id, payload)

    def _upsert_discovered_candidates(
        self,
        session: Session,
        *,
        task: TaskEnvelope,
        result: AgentResult,
        adaptive_stage: str,
    ) -> list[str]:
        if not result.success or not isinstance(result.data, dict):
            return []

        payloads = self._candidate_payloads_from_result(result.data)
        if not payloads:
            return []

        candidate_repo = CandidateRepository(session)
        session_repo = CandidateSessionRepository(session)
        application_repo = CandidateApplicationRepository(session)
        resume_repo = ResumeArtifactRepository(session)
        persisted_ids: list[str] = []
        goal_spec_id = str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "").strip() or None
        state_machine_snapshot = self._load_state_machine_snapshot()

        for payload in payloads:
            normalized = self._normalize_discovered_candidate_payload(
                payload,
                default_platform=task.platform,
                adaptive_stage=adaptive_stage,
                task=task,
            )
            existing = None
            candidate_ref = normalized.get("candidate_id")
            if isinstance(candidate_ref, str) and candidate_ref.strip():
                existing = candidate_repo.resolve(candidate_ref.strip())
            if existing is None and normalized.get("platform_candidate_id"):
                existing = resolve_candidate_by_platform_identity(
                    session,
                    platform=normalized["platform"],
                    platform_candidate_id=normalized["platform_candidate_id"],
                )
            if existing is None:
                existing = resolve_candidate_by_contact_info(
                    session,
                    contact_info=normalized.get("contact_info"),
                )
            if existing is None and normalized.get("name"):
                for item in candidate_repo.list(limit=200, offset=0):
                    if item.platform == normalized["platform"] and item.name == normalized["name"]:
                        existing = item
                        break

            created = False
            target_status = str(normalized["status"] or "discovered").strip() or "discovered"
            initial_milestone = self._state_machine_milestone_for_status(state_machine_snapshot, "discovered")
            if existing is None:
                existing = candidate_repo.create(
                    {
                        "name": normalized["name"],
                        "platform": normalized["platform"],
                        "platform_candidate_id": normalized.get("platform_candidate_id"),
                        "contact_info": normalized["contact_info"],
                    }
                )
                created = True
            else:
                merged_contact = dict(existing.contact_info or {})
                merged_contact.update(normalized["contact_info"])
                existing.name = normalized["name"] or existing.name
                existing.platform = normalized["platform"] or existing.platform
                existing.platform_candidate_id = normalized.get("platform_candidate_id") or existing.platform_candidate_id
                existing.contact_info = merged_contact
                session.flush()

            resolved_job_description_id = (
                normalized.get("job_description_id")
                or normalized.get("jd_id")
            )
            application = None
            explicit_application_id = str(task.application_id or task.metadata.get("application_id") or "").strip() or None
            if explicit_application_id is not None:
                application = application_repo.get(explicit_application_id)
            if application is None and resolved_job_description_id:
                application_window = make_application_window(existing.candidate_person_id, resolved_job_description_id)
                application = application_repo.by_application_window(application_window)
            if application is None and resolved_job_description_id:
                application = application_repo.create(
                    {
                        "person_id": existing.candidate_person_id,
                        "job_description_id": resolved_job_description_id,
                        "platform": normalized["platform"],
                        "platform_application_id": normalized.get("platform_application_id"),
                        "current_status": "discovered",
                        "current_stage_key": "discovered",
                        "deepest_milestone": initial_milestone,
                        "state_snapshot": default_candidate_state_snapshot(status="discovered"),
                        "ai_scores": normalized.get("ai_scores", {}),
                        "ai_reasoning": normalized.get("ai_reasoning"),
                        "application_metadata": {
                            "created_from": "discovery",
                            "source_task_id": task.task_id,
                            "source_task_type": task.task_type,
                        },
                    }
                )
            elif application is not None:
                application.person_id = existing.id
                application.platform = normalized["platform"] or application.platform
                if resolved_job_description_id:
                    application.job_description_id = resolved_job_description_id
                application.platform_application_id = (
                    normalized.get("platform_application_id")
                    or application.platform_application_id
                )
                application.ai_scores = normalized.get("ai_scores", {}) or application.ai_scores
                application.ai_reasoning = normalized.get("ai_reasoning") or application.ai_reasoning
                session.flush()

            candidate_session = session_repo.get_or_create(
                existing.candidate_person_id,
                defaults={
                    "status": "active",
                    "context_summary": normalized.get("ai_reasoning"),
                    "facts": {},
                    "recent_messages": [],
                    "last_active_at": utcnow(),
                },
            )
            candidate_session.context_summary = normalized.get("ai_reasoning") or candidate_session.context_summary
            candidate_session.status = "active"
            candidate_session.suspend_reason = None
            candidate_session.last_active_at = utcnow()
            candidate_session.facts = {
                **dict(candidate_session.facts or {}),
                "last_task_id": task.task_id,
                "last_task_type": task.task_type,
                "last_result_status": result.status,
                "last_result_success": result.success,
                "goal_spec_id": goal_spec_id,
                "adaptive_stage": adaptive_stage,
                "source_platform": normalized["platform"],
            }
            self._persist_resume_artifact(
                session,
                resume_repo=resume_repo,
                candidate=existing,
                application=application,
                normalized=normalized,
                task=task,
                adaptive_stage=adaptive_stage,
            )

            status_subject = application if application is not None else existing
            current_status = resolve_candidate_current_status(status_subject)
            if target_status != current_status:
                transition_result = self._agent_transition_candidate(
                    session,
                    task=task,
                    candidate=existing,
                    application=application,
                    to_status=target_status,
                    stage_key=normalized["current_stage_key"],
                    stage_label=str((normalized["state_snapshot"] or {}).get("current_stage_label") or ""),
                    note=normalized.get("ai_reasoning"),
                    metadata={
                        "goal_spec_id": goal_spec_id,
                        "source_scene": normalized["state_snapshot"].get("snapshot_metadata", {}).get("source_scene"),
                        "raw_scene_locator": normalized["state_snapshot"].get("snapshot_metadata", {}).get("raw_scene_locator"),
                        "platform_candidate_id": normalized.get("platform_candidate_id"),
                        "trigger_fallback": task.task_type or adaptive_stage,
                    },
                )
                existing = candidate_repo.resolve(transition_result.candidate_id) or existing
                if application is not None:
                    application = application_repo.get(application.id) or application
                merged_snapshot = dict((application.state_snapshot if application is not None else {}) or {})
                merged_snapshot["latest_note"] = normalized.get("ai_reasoning") or merged_snapshot.get("latest_note")
                merged_metadata = dict(merged_snapshot.get("snapshot_metadata") or {})
                merged_metadata.update(
                    {
                        key: value
                        for key, value in dict((normalized["state_snapshot"] or {}).get("snapshot_metadata") or {}).items()
                        if value not in (None, "", [], {})
                    }
                )
                merged_snapshot["snapshot_metadata"] = merged_metadata
                if application is not None:
                    application.state_snapshot = merged_snapshot
                session.flush()
            else:
                target_entity = application if application is not None else existing
                if application is not None:
                    target_entity.current_status = target_status or target_entity.current_status
                    target_entity.current_stage_key = normalized["current_stage_key"] or target_entity.current_stage_key
                    target_entity.state_snapshot = normalized["state_snapshot"] or target_entity.state_snapshot
                    if created and not target_entity.deepest_milestone:
                        target_entity.deepest_milestone = self._state_machine_milestone_for_status(state_machine_snapshot, target_status)
                session.flush()

            persisted_subject_id = (
                application.candidate_application_id
                if application is not None
                else existing.candidate_person_id
            )
            if persisted_subject_id not in persisted_ids:
                persisted_ids.append(persisted_subject_id)

        session.commit()
        return persisted_ids

    def _persist_resume_artifact(
        self,
        session: Session,
        *,
        resume_repo: ResumeArtifactRepository,
        candidate,
        application,
        normalized: dict[str, Any],
        task: TaskEnvelope,
        adaptive_stage: str,
    ) -> None:
        resume_text = str(normalized.get("online_resume_text") or "").strip()
        source_resume_path = str(normalized.get("resume_path") or "").strip()
        evidence = dict(normalized.get("profile_or_resume_evidence") or {})
        evidence_excerpt = str(evidence.get("text_excerpt") or evidence.get("summary") or "").strip()
        attachment_name = str(evidence.get("attachment_name") or "").strip() or None
        synthesized_resume_text = resume_text
        if not synthesized_resume_text and evidence_excerpt:
            summary = str((normalized.get("contact_info") or {}).get("summary") or normalized.get("ai_reasoning") or "").strip()
            synthesized_resume_text = "\n\n".join(part for part in [summary, evidence_excerpt] if part).strip()
        if not synthesized_resume_text and not source_resume_path:
            return

        local_resume_path: str | None = None
        file_name: str | None = None
        if synthesized_resume_text:
            artifacts_dir = self.settings.resolved_data_dir() / "resume_artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            file_name = attachment_name or f"{candidate.id}_{self._resume_file_stem(candidate.name)}_resume.txt"
            if not file_name.lower().endswith(".txt"):
                file_name = f"{Path(file_name).stem or self._resume_file_stem(candidate.name)}.txt"
            artifact_path = artifacts_dir / file_name
            artifact_path.write_text(
                self._render_resume_artifact_text(candidate_name=candidate.name, normalized=normalized),
                encoding="utf-8",
            )
            local_resume_path = str(artifact_path.resolve())
        elif source_resume_path:
            file_name = Path(source_resume_path).name or None
            local_resume_path = source_resume_path

        application_id = str(getattr(application, "id", None) or task.application_id or task.metadata.get("application_id") or "").strip() or None
        if application_id is None:
            return
        existing_artifacts = resume_repo.by_application(application_id, limit=20, offset=0)
        for existing in existing_artifacts:
            existing_path = str(existing.file_path or "").strip()
            existing_text = str(existing.extracted_text or "").strip()
            if local_resume_path and existing_path == local_resume_path:
                return
            if synthesized_resume_text and existing_text == synthesized_resume_text:
                return

        resume_repo.create(
            {
                "application_id": application_id,
                "source": normalized.get("platform") or task.platform,
                "artifact_type": "resume",
                "file_name": file_name,
                "file_path": local_resume_path or source_resume_path or None,
                "extracted_text": synthesized_resume_text or None,
                "contact_snapshot": dict(normalized.get("contact_info") or {}),
                "artifact_metadata": {
                    "created_by": "agent_runtime",
                    "source_task_id": task.task_id,
                    "source_task_type": task.task_type,
                    "adaptive_stage": adaptive_stage,
                    "platform_candidate_id": normalized.get("platform_candidate_id"),
                    "source_resume_path": source_resume_path or None,
                    "attachment_name": attachment_name,
                },
                "captured_at": utcnow(),
            }
        )

    def _resume_file_stem(self, candidate_name: str) -> str:
        base = re.sub(r"[^0-9A-Za-z]+", "_", candidate_name.strip()).strip("_")
        return base or "candidate"

    def _render_resume_artifact_text(self, *, candidate_name: str, normalized: dict[str, Any]) -> str:
        lines = [
            f"Candidate: {candidate_name}",
            f"Platform: {normalized.get('platform') or 'site'}",
        ]
        platform_candidate_id = str(normalized.get("platform_candidate_id") or "").strip()
        if platform_candidate_id:
            lines.append(f"PlatformCandidateId: {platform_candidate_id}")
        title = str((normalized.get("contact_info") or {}).get("title") or "").strip()
        if title:
            lines.append(f"TargetRole: {title}")
        location = str((normalized.get("contact_info") or {}).get("location") or "").strip()
        if location:
            lines.append(f"Location: {location}")
        summary = str((normalized.get("contact_info") or {}).get("summary") or "").strip()
        if summary:
            lines.extend(["", "Summary", summary])
        evidence = dict(normalized.get("profile_or_resume_evidence") or {})
        attachment_name = str(evidence.get("attachment_name") or "").strip()
        if attachment_name:
            lines.append(f"AttachmentName: {attachment_name}")
        resume_text = str(normalized.get("online_resume_text") or "").strip()
        if resume_text:
            lines.extend(["", "ResumeText", resume_text])
        evidence_excerpt = str(evidence.get("text_excerpt") or evidence.get("summary") or "").strip()
        if evidence_excerpt:
            lines.extend(["", "VisibleResumeEvidence", evidence_excerpt])
        return "\n".join(lines).strip() + "\n"

    def _candidate_payloads_from_result(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        top_level_summary = str(payload.get("summary") or "").strip()
        top_level_evidence = payload.get("evidence")

        def _append(item: Any) -> None:
            if not isinstance(item, dict):
                return
            candidate_payload = dict(item)
            if (
                top_level_summary
                and not str(candidate_payload.get("summary") or "").strip()
                and not self._candidate_has_structured_details(candidate_payload)
            ):
                candidate_payload["summary"] = top_level_summary
            if not candidate_payload.get("profile_or_resume_evidence"):
                evidence_source: Any = top_level_evidence
                if isinstance(candidate_payload.get("resume"), dict):
                    evidence_source = {
                        **(dict(top_level_evidence) if isinstance(top_level_evidence, dict) else {}),
                        "resume": dict(candidate_payload.get("resume") or {}),
                    }
                merged_evidence = self._coerce_profile_or_resume_evidence(evidence_source)
                if merged_evidence:
                    candidate_payload["profile_or_resume_evidence"] = merged_evidence
            if not candidate_payload.get("source_scene") and isinstance(top_level_evidence, dict):
                page = top_level_evidence.get("page")
                if isinstance(page, dict):
                    candidate_payload["source_scene"] = dict(page)
            if not self._looks_like_candidate_payload(candidate_payload):
                return
            marker = json.dumps(candidate_payload, ensure_ascii=False, sort_keys=True, default=str)
            if marker in seen:
                return
            seen.add(marker)
            candidates.append(candidate_payload)

        for key in ("candidates", "candidate_cards", "profiles", "results"):
            raw_items = payload.get(key)
            if isinstance(raw_items, list):
                for item in raw_items:
                    _append(item)

        for key in ("candidate", "profile"):
            _append(payload.get(key))

        has_direct_candidate_fields = any(
            self._candidate_signal_present(payload.get(key))
            for key in ("candidate_id", "platform_candidate_id", "name", "contact_info", "raw_scene_locator")
        )
        if not candidates or has_direct_candidate_fields:
            _append(payload)
        return candidates

    def _looks_like_candidate_payload(self, payload: dict[str, Any]) -> bool:
        candidate_signals = (
            payload.get("name"),
            payload.get("platform_candidate_id"),
            payload.get("profile_or_resume_evidence"),
            payload.get("contact_info"),
            payload.get("raw_scene_locator"),
        )
        return any(self._candidate_signal_present(signal) for signal in candidate_signals)

    def _candidate_signal_present(self, signal: Any) -> bool:
        if signal is None:
            return False
        if isinstance(signal, str):
            return bool(signal.strip())
        if isinstance(signal, (list, tuple, set, dict)):
            return bool(signal)
        return True

    def _candidate_has_structured_details(self, payload: dict[str, Any]) -> bool:
        detail_keys = (
            "age",
            "experience",
            "education",
            "current_company",
            "current_title",
            "previous_company",
            "previous_title",
            "education_history",
            "education_detail",
            "job_search_reason",
            "preferred_direction",
            "interview_availability",
            "location",
            "target_position",
            "target_role",
            "communication_role",
            "recent_interest",
            "resume",
        )
        return any(self._candidate_signal_present(payload.get(key)) for key in detail_keys)

    def _coerce_profile_or_resume_evidence(self, evidence: Any) -> dict[str, Any]:
        if isinstance(evidence, dict):
            page = dict(evidence.get("page") or {}) if isinstance(evidence.get("page"), dict) else {}
            resume = dict(evidence.get("resume") or {}) if isinstance(evidence.get("resume"), dict) else dict(evidence)
            visible_strings = [
                str(item).strip()
                for item in (
                    list(resume.get("visible_strings") or [])
                    + list(resume.get("visible_text") or [])
                    + list(evidence.get("visible_profile_sections") or [])
                    + list(evidence.get("verbatim_markers") or [])
                )
                if str(item).strip()
            ]
            attachment_name = str(
                resume.get("attachment_name")
                or resume.get("file_name")
                or resume.get("attachment")
                or evidence.get("visible_resume_artifact")
                or ""
            ).strip()
            source_url = str(
                page.get("url")
                or evidence.get("source_url")
                or evidence.get("page")
                or ""
            ).strip()
            summary_parts: list[str] = []
            if attachment_name:
                summary_parts.append(f"附件简历：{attachment_name}")
            if visible_strings:
                summary_parts.append("；".join(visible_strings[:8]))
            if source_url:
                summary_parts.append(f"页面：{source_url}")
            note = str(evidence.get("note") or "").strip()
            if note:
                summary_parts.append(note)
            merged = {
                "kind": "resume_visibility",
                "summary": " | ".join(part for part in summary_parts if part).strip() or None,
                "text_excerpt": "\n".join(visible_strings[:20]).strip() or None,
                "attachment_name": attachment_name or None,
                "page": page or ({"url": source_url} if source_url else None),
            }
            return {
                key: value
                for key, value in merged.items()
                if value is not None and value != "" and value != [] and value != {}
            }

        if isinstance(evidence, list):
            text_parts: list[str] = []
            attachment_name: str | None = None
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                visible_text = [str(value).strip() for value in list(item.get("visible_text") or []) if str(value).strip()]
                if visible_text:
                    text_parts.extend(visible_text[:10])
                if attachment_name is None:
                    candidate_attachment = str(item.get("attachment_name") or "").strip()
                    if candidate_attachment:
                        attachment_name = candidate_attachment
            if not text_parts and not attachment_name:
                return {}
            merged = {
                "kind": "resume_visibility",
                "summary": f"附件简历：{attachment_name}" if attachment_name else "可见简历证据",
                "text_excerpt": "\n".join(text_parts[:20]).strip() or None,
                "attachment_name": attachment_name,
            }
            return {
                key: value
                for key, value in merged.items()
                if value is not None and value != "" and value != [] and value != {}
            }

        return {}

    def _normalize_discovered_candidate_payload(
        self,
        payload: dict[str, Any],
        *,
        default_platform: str,
        adaptive_stage: str,
        task: TaskEnvelope,
    ) -> dict[str, Any]:
        contact_info = dict(payload.get("contact_info") or {})
        evidence = dict(payload.get("profile_or_resume_evidence") or {})
        source_scene = dict(payload.get("source_scene") or {})
        raw_locator = dict(payload.get("raw_scene_locator") or {})
        platform = str(payload.get("platform") or default_platform or "site").strip() or "site"
        platform_candidate_id = (
            str(
                payload.get("platform_candidate_id")
                or raw_locator.get("candidate_id")
                or raw_locator.get("id")
                or source_scene.get("candidate_id")
                or ""
            ).strip()
            or None
        )
        name = str(payload.get("name") or contact_info.get("name") or raw_locator.get("name") or "未命名候选人").strip()
        title = str(
            payload.get("title")
            or payload.get("target_position")
            or payload.get("target_role")
            or payload.get("communication_role")
            or payload.get("job_title")
            or payload.get("current_title")
            or contact_info.get("title")
            or raw_locator.get("title")
            or ""
        ).strip()
        location = str(
            payload.get("location")
            or contact_info.get("location")
            or raw_locator.get("location")
            or self._infer_candidate_location(payload)
            or ""
        ).strip()
        summary = str(
            payload.get("summary")
            or contact_info.get("summary")
            or self._compose_candidate_summary(payload)
            or evidence.get("summary")
            or evidence.get("text_excerpt")
            or ""
        ).strip()
        online_resume_text = str(payload.get("online_resume_text") or evidence.get("text_excerpt") or "").strip() or None
        status = str(extract_business_status(payload, fallback="discovered") or "discovered")
        if status in {"completed", "default", "success", "ok", "done"}:
            status = "discovered"
        current_stage_key = str(payload.get("current_stage_key") or adaptive_stage or status).strip() or status
        current_stage_label = str(payload.get("current_stage_label") or current_stage_key.replace("_", " ")).strip()
        state_snapshot = default_candidate_state_snapshot(
            status=status,
            stage_key=current_stage_key,
            stage_label=current_stage_label,
        )
        state_snapshot["latest_note"] = summary or None
        state_snapshot["latest_transition_at"] = utcnow().isoformat()
        state_snapshot["latest_transition_source"] = "runtime"
        snapshot_metadata = dict(state_snapshot.get("snapshot_metadata") or {})
        snapshot_metadata.update(
            {
                "source_task_id": task.task_id,
                "source_task_type": task.task_type,
                "source_goal_id": str(task.payload.get("goal_id") or task.metadata.get("goal_spec_id") or "").strip() or None,
                "source_scene": source_scene,
                "raw_scene_locator": raw_locator,
            }
        )
        state_snapshot["snapshot_metadata"] = snapshot_metadata

        normalized_contact = {
            **contact_info,
            **({"title": title} if title else {}),
            **({"location": location} if location else {}),
            **({"summary": summary} if summary else {}),
        }

        return {
            "candidate_id": payload.get("candidate_id"),
            "name": name,
            "platform": platform,
            "platform_candidate_id": platform_candidate_id,
            "status": status,
            "current_stage_key": current_stage_key,
            "job_description_id": (
                payload.get("job_description_id")
                or payload.get("jd_id")
                or task.payload.get("job_description_id")
                or task.payload.get("jd_id")
            ),
            "contact_info": normalized_contact,
            "state_snapshot": state_snapshot,
            "resume_path": payload.get("resume_path"),
            "online_resume_text": online_resume_text,
            "ai_scores": dict(payload.get("ai_scores") or {}),
            "ai_reasoning": summary or online_resume_text,
            "profile_or_resume_evidence": evidence,
        }

    def _infer_candidate_location(self, payload: dict[str, Any]) -> str | None:
        for value in (
            payload.get("recent_interest"),
            payload.get("recent_activity"),
            payload.get("current_location"),
        ):
            text = str(value or "").strip()
            if not text:
                continue
            if "·" in text:
                candidate = text.split("·", 1)[0].strip()
                if candidate:
                    return candidate
        return None

    def _compose_candidate_summary(self, payload: dict[str, Any]) -> str | None:
        parts: list[str] = []
        age = str(payload.get("age") or "").strip()
        experience = str(payload.get("experience") or "").strip()
        education = str(payload.get("education") or "").strip()
        headline = "，".join(part for part in (age, education, experience) if part)
        if headline:
            parts.append(headline)

        for company_key, title_key in (
            ("current_company", "current_title"),
            ("previous_company", "previous_title"),
        ):
            company = str(payload.get(company_key) or "").strip()
            title = str(payload.get(title_key) or "").strip()
            if company or title:
                parts.append(" / ".join(part for part in (company, title) if part))

        for entry in list(payload.get("current_or_recent_companies") or []):
            if not isinstance(entry, dict):
                continue
            company = str(entry.get("company") or "").strip()
            title = str(entry.get("title") or "").strip()
            period = str(entry.get("period") or "").strip()
            text = " / ".join(part for part in (company, title, period) if part)
            if text:
                parts.append(text)

        for key in (
            "employment_status",
            "current_status",
            "job_search_reason",
            "motivation",
            "preferred_direction",
            "interview_availability",
        ):
            value = str(payload.get(key) or "").strip()
            if value:
                parts.append(value)

        summary = "；".join(part for part in parts if part).strip()
        return summary or None

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
        skip_skill_draft = bool(result.metadata.get("skip_runtime_skill_draft_learning"))

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

        if not skip_skill_draft:
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
                application_id, person_id, _application = self._task_subject_ids(session, task)
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
                        "candidate_id": person_id,
                        "application_id": application_id,
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

        execution_mode = str(
            task.metadata.get("state_machine_execution_mode")
            or (result.metadata.get("state_machine_gate") or {}).get("execution_mode")
            or ""
        ).strip()
        if execution_mode == "ai_auto":
            self.events.publish(
                "warning",
                "operator_interaction",
                "AI 自动节点意外进入 waiting_human，已跳过 OperatorInteraction 创建。",
                task_id=task.task_id,
                task_type=task.task_type,
                candidate_id=task.candidate_id,
                current_status=task.metadata.get("state_machine_current_status"),
            )
            return

        try:
            with self.session_factory() as session:
                application_id, person_id, _application = self._task_subject_ids(session, task)
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
                                "candidate_id": person_id,
                                "application_id": application_id,
                                "execution_mode": execution_mode or None,
                                "current_status": task.metadata.get("state_machine_current_status"),
                                "state_machine_version": task.metadata.get("state_machine_version"),
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
                        "candidate_id": person_id,
                        "lane": str(task.metadata.get("lane") or ("candidate" if person_id or application_id else "agent")),
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
                            "candidate_id": person_id,
                            "application_id": application_id,
                            "execution_mode": execution_mode or None,
                            "current_status": task.metadata.get("state_machine_current_status"),
                            "state_machine_version": task.metadata.get("state_machine_version"),
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
                application_id, person_id, _application = self._task_subject_ids(session, task, run=run)
                goal = GoalSpecRepository(session).get(goal_spec_id) if goal_spec_id else None

                title = goal.title if goal is not None else self._humanize_task_label(self._adaptive_stage_for_task(task))
                goal_evaluation = None
                if goal is not None and self._adaptive_stage_for_task(task) != "goal_intake":
                    goal_evaluation = self._evaluate_goal_success_criteria(session, task=task, goal=goal, result=result)
                summary = self._goal_summary_from_result(
                    title=title,
                    result=result,
                    goal_evaluation=goal_evaluation,
                )
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
                raw_trace = _json_ready(raw_trace)
                distilled_trace = {
                    "goal": goal.goal_text if goal is not None else str(task.payload.get("goal_text") or self._adaptive_stage_for_task(task)),
                    "attempt": {
                        "task_type": task.task_type,
                        "lane": str(run.lane if run is not None else task.metadata.get("lane") or "agent"),
                        "candidate_id": person_id,
                        "application_id": application_id,
                    },
                    "signals": list((context_manifest or {}).get("selected_fragments") or []),
                    "blocked": result.status in {"waiting_human", "waiting_candidate", "blocked"},
                    "next_step_hint": self._next_step_hint(result.status),
                }
                distilled_trace = _json_ready(distilled_trace)
                outcome = {
                    "status": result.status,
                    "success": result.success,
                    "blocked_reason": result.content if result.status in {"waiting_human", "blocked"} else None,
                    "selected_token_estimate": int((context_manifest or {}).get("selected_token_estimate") or 0),
                }
                outcome = _json_ready(outcome)

                trace_repo = ExecutionTraceRepository(session)
                existing_trace = trace_repo.by_run(run_id) if run_id else None
                trace_payload = {
                    "session_id": session_id or (run.session_id if run is not None else ""),
                    "run_id": run_id or None,
                    "goal_spec_id": goal_spec_id,
                    "candidate_id": person_id,
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
                        "application_id": application_id,
                        "person_id": person_id,
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
                graph_payload = self._build_graph_projection_payload(
                    task=task,
                    goal=goal,
                    result=result,
                    person_id=person_id,
                    application_id=application_id,
                )
                graph_payload = _json_ready(graph_payload)
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
                        "candidate_id": person_id,
                        "job_description_id": getattr(run, "job_description_id", None),
                        "scope": "candidate" if person_id or application_id else "agent",
                        "fragment_kind": "adaptive_strategy",
                        "title": f"{title} · {self._humanize_task_label(task.task_type)}",
                        "summary": self._strategy_fragment_summary(task=task, result=result),
                        "content": {
                            "suggested_path": self._next_step_hint(result.status),
                            "task_type": task.task_type,
                            "result_status": result.status,
                            "candidate_id": person_id,
                            "application_id": application_id,
                        },
                        "evidence": {
                            "run_id": run_id or None,
                            "goal_spec_id": goal_spec_id,
                            "result_status": result.status,
                            "application_id": application_id,
                            "person_id": person_id,
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
                                "last_success_criteria_satisfied": None
                                if goal_evaluation is None
                                else bool(goal_evaluation.get("satisfied")),
                                "last_missing_success_criteria": []
                                if goal_evaluation is None
                                else list(goal_evaluation.get("missing") or []),
                                "last_verified_local_resume_paths": []
                                if goal_evaluation is None
                                else list(goal_evaluation.get("matching_resume_paths") or []),
                                "last_required_resume_extensions": []
                                if goal_evaluation is None
                                else list(goal_evaluation.get("required_resume_extensions") or []),
                            },
                        },
                    )
                session.commit()
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
                application_id, person_id, _application = self._task_subject_ids(session, task)
                trace_repo = ExecutionTraceRepository(session)
                existing = trace_repo.by_run(run_id) if run_id else None
                payload = {
                    "session_id": session_id,
                    "run_id": run_id or None,
                    "goal_spec_id": goal_spec_id,
                    "candidate_id": person_id,
                    "lane": str(task.metadata.get("lane") or ("candidate" if person_id or application_id else "agent")),
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
                        "application_id": application_id,
                        "candidate_id": person_id,
                    },
                    "outcome": {"status": "failed", "success": False},
                    "trace_metadata": {
                        "task_id": task.task_id,
                        "task_type": task.task_type,
                        "application_id": application_id,
                        "person_id": person_id,
                    },
                }
                payload = _json_ready(payload)
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
                session.commit()
        except Exception:
            return

    def _build_operator_prompt(self, task: TaskEnvelope, result: AgentResult) -> str:
        task_label = self._humanize_task_label(task.task_type)
        if task.application_id or task.candidate_id:
            return f"{task_label} 在候选人上下文中暂停了。当前问题：{result.content or '需要你确认下一步处理方式。'}"
        return f"{task_label} 暂时无法继续。当前问题：{result.content or '需要你确认下一步处理方式。'}"

    def _build_operator_options(self, task: TaskEnvelope, result: AgentResult) -> list[dict[str, Any]]:
        configured_actions = result.metadata.get("state_machine_human_actions") or task.metadata.get("state_machine_human_actions") or []
        if isinstance(configured_actions, list) and configured_actions:
            options: list[dict[str, Any]] = []
            for index, raw_action in enumerate(configured_actions, start=1):
                if not isinstance(raw_action, dict):
                    continue
                label = str(raw_action.get("label") or "").strip()
                to_status = str(raw_action.get("toStatus") or raw_action.get("to_status") or "").strip()
                style = str(raw_action.get("style") or "default").strip() or "default"
                requires_note = bool(raw_action.get("requiresNote") or raw_action.get("requires_note"))
                option_id = str(raw_action.get("id") or to_status or f"human-action-{index}").strip() or f"human-action-{index}"
                description = str(raw_action.get("description") or "").strip()
                if not description:
                    description = f"按状态机配置流转到 {to_status}。" if to_status else "按状态机配置执行人工处理。"
                options.append(
                    {
                        "id": option_id,
                        "label": label or to_status or f"选项 {index}",
                        "action": "transition",
                        "description": description,
                        "to_status": to_status or None,
                        "style": style,
                        "requires_note": requires_note,
                    }
                )
            if options:
                return options

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
        if task.application_id or task.candidate_id:
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

    def _task_subject_ids(
        self,
        session: Session | None,
        task: TaskEnvelope,
        *,
        run: Any | None = None,
    ) -> tuple[str | None, str | None, Any | None]:
        application_id = str(
            task.application_id
            or task.metadata.get("application_id")
            or task.payload.get("application_id")
            or task.payload.get("applicationId")
            or ""
        ).strip() or None
        raw_person_id = str(
            task.metadata.get("person_id")
            or getattr(run, "candidate_id", None)
            or (
                task.candidate_id
                if str(task.candidate_id or "").strip() and str(task.candidate_id or "").strip() != str(application_id or "")
                else ""
            )
            or ""
        ).strip() or None
        application = CandidateApplicationRepository(session).get(application_id) if session is not None and application_id else None
        person_id = raw_person_id
        if session is not None:
            candidate_repo = CandidateRepository(session)
            candidate = candidate_repo.resolve(raw_person_id) if raw_person_id else None
            if candidate is None and application is not None:
                candidate = candidate_repo.resolve(application.person_id)
            if candidate is not None:
                person_id = str(candidate.candidate_person_id or "").strip() or None
        return application_id, person_id, application

    def _build_graph_projection_payload(
        self,
        *,
        task: TaskEnvelope,
        goal,
        result: AgentResult,
        person_id: str | None,
        application_id: str | None,
    ) -> dict[str, Any]:
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
            "candidate_id": person_id,
            "graph_kind": "execution_projection",
            "title": title,
            "summary": result.content or f"{title} 当前状态为 {result.status}。",
            "nodes": nodes,
            "edges": edges,
            "rendered_text": rendered,
            "graph_metadata": {
                "result_status": result.status,
                "task_type": task.task_type,
                "application_id": application_id,
                "person_id": person_id,
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

    def _goal_summary_from_result(
        self,
        *,
        title: str,
        result: AgentResult,
        goal_evaluation: dict[str, Any] | None,
    ) -> str:
        if goal_evaluation is not None and result.success and not bool(goal_evaluation.get("satisfied")):
            missing = "、".join(
                self._goal_requirement_label(
                    key,
                    required_resume_extensions=list(goal_evaluation.get("required_resume_extensions") or []),
                )
                for key in list(goal_evaluation.get("missing") or [])
            )
            detail = f"未满足 success criteria：{missing}。" if missing else "未满足 success criteria。"
            return f"{title} 本轮执行已完成，但{detail}"
        return result.content or f"{title} 当前状态为 {result.status}。"

    def _goal_requirement_label(
        self,
        key: str,
        *,
        required_resume_extensions: list[str],
    ) -> str:
        if key == "minimum_candidates":
            return "候选人数不足"
        if key == "resume_or_profile":
            return "缺少简历或资料证据"
        if key == "local_resume_file":
            return "缺少本地简历文件"
        if key == "resume_extension":
            if required_resume_extensions:
                return f"缺少符合格式的本地简历文件（{', '.join(required_resume_extensions)}）"
            return "本地简历文件格式不匹配"
        return key

    def _evaluate_goal_success_criteria(
        self,
        session: Session,
        *,
        task: TaskEnvelope,
        goal,
        result: AgentResult,
    ) -> dict[str, Any]:
        criteria = dict(goal.success_criteria or task.payload.get("success_criteria") or {})
        required_resume_extensions = sorted(
            {
                f".{text.lstrip('.')}" if not text.startswith(".") else text
                for text in (
                    str(item).strip().lower()
                    for item in list(criteria.get("required_resume_extensions") or [])
                )
                if text
            }
        )
        candidate_ids = self._goal_candidate_ids_for_evaluation(task=task, result=result)
        application_repo = CandidateApplicationRepository(session)
        candidate_repo = CandidateRepository(session)
        resume_repo = ResumeArtifactRepository(session)
        application_records = [
            item
            for item in (
                application_repo.get(candidate_id)
                for candidate_id in candidate_ids
            )
            if item is not None
        ]
        candidate_records = []
        for application in application_records:
            candidate = candidate_repo.resolve(application.person_id)
            if candidate is not None:
                candidate_records.append((application, candidate))
        for candidate_id in candidate_ids:
            if any(application.id == candidate_id for application, _candidate in candidate_records):
                continue
            candidate = candidate_repo.resolve(candidate_id)
            if candidate is not None:
                candidate_records.append((None, candidate))
        local_resume_paths: list[str] = []
        matching_resume_paths: list[str] = []
        has_resume_or_profile = False

        def _remember_local_path(raw_path: str | None) -> None:
            text = str(raw_path or "").strip()
            if not text:
                return
            if not Path(text).expanduser().exists():
                return
            if text not in local_resume_paths:
                local_resume_paths.append(text)
            suffix = Path(text).suffix.lower()
            if required_resume_extensions and suffix in required_resume_extensions and text not in matching_resume_paths:
                matching_resume_paths.append(text)

        for application, candidate in candidate_records:
            application_metadata = dict(application.application_metadata or {}) if application is not None else {}
            application_state = dict(application.state_snapshot or {}) if application is not None else {}
            if bool(application_metadata.get("resume_available")) or bool(application_state.get("resume_available")):
                has_resume_or_profile = True
            artifacts = (
                resume_repo.by_application(application.id, limit=50, offset=0)
                if application is not None
                else []
            )
            for artifact in artifacts:
                if str(artifact.file_path or "").strip() or str(artifact.extracted_text or "").strip():
                    has_resume_or_profile = True
                _remember_local_path(artifact.file_path)

        if not has_resume_or_profile and isinstance(result.data, dict):
            payload_candidates = self._candidate_payloads_from_result(result.data)
            has_resume_or_profile = any(
                bool(str(dict(item.get("profile_or_resume_evidence") or {}).get("text_excerpt") or "").strip())
                or bool(str(item.get("online_resume_text") or "").strip())
                or bool(str(item.get("resume_path") or "").strip())
                for item in payload_candidates
                if isinstance(item, dict)
            )

        observed_candidate_count = max(
            len(candidate_records),
            len(self._candidate_payloads_from_result(result.data)) if isinstance(result.data, dict) else 0,
        )
        missing: list[str] = []
        minimum_candidates = int(criteria.get("minimum_candidates") or 0)
        if minimum_candidates and observed_candidate_count < minimum_candidates:
            missing.append("minimum_candidates")
        if bool(criteria.get("requires_resume_or_profile")) and not has_resume_or_profile:
            missing.append("resume_or_profile")
        if bool(criteria.get("requires_local_resume_file")) and not local_resume_paths:
            missing.append("local_resume_file")
        if required_resume_extensions and not matching_resume_paths:
            missing.append("resume_extension")

        return {
            "satisfied": not missing,
            "missing": missing,
            "candidate_ids": candidate_ids,
            "observed_candidate_count": observed_candidate_count,
            "local_resume_paths": local_resume_paths,
            "matching_resume_paths": matching_resume_paths,
            "required_resume_extensions": required_resume_extensions,
        }

    def _goal_candidate_ids_for_evaluation(self, *, task: TaskEnvelope, result: AgentResult) -> list[str]:
        candidate_ids: list[str] = []
        for value in list(result.metadata.get("persisted_candidate_ids") or []):
            text = str(value or "").strip()
            if text and text not in candidate_ids:
                candidate_ids.append(text)
        task_candidate_id = str(task.candidate_id or "").strip()
        if task_candidate_id and task_candidate_id not in candidate_ids:
            candidate_ids.append(task_candidate_id)
        return candidate_ids

    def _resume_collection_outbound_message(self, *, task: TaskEnvelope, result: AgentResult) -> str | None:
        if bool(result.metadata.get("rollback_signal_applied")):
            return None
        platform_result = dict(result.metadata.get("platform_result") or {})
        result_data = dict(result.data or {}) if isinstance(result.data, dict) else {}
        action_tokens = {
            str(platform_result.get("action") or "").strip().lower(),
            str(result_data.get("action") or "").strip().lower(),
            str(result_data.get("resume_action") or "").strip().lower(),
            str(result_data.get("collection_mode") or "").strip().lower(),
        }
        resume_request_explicit = bool(result_data.get("resume_request_sent")) or any(
            token in {"resume_request", "request_resume", "resume_requested"}
            for token in action_tokens
            if token
        )
        if not resume_request_explicit:
            return None
        return (
            str(platform_result.get("message") or result_data.get("message") or task.payload.get("message") or "").strip()
            or "Requested resume submission."
        )

    def _candidate_outreach_outbound_message(self, *, task: TaskEnvelope, result: AgentResult) -> str | None:
        if bool(result.metadata.get("rollback_signal_applied")):
            return None
        platform_result = dict(result.metadata.get("platform_result") or {})
        result_data = dict(result.data or {}) if isinstance(result.data, dict) else {}
        action_tokens = {
            str(platform_result.get("action") or "").strip().lower(),
            str(result_data.get("action") or "").strip().lower(),
            str(result_data.get("outreach_action") or "").strip().lower(),
        }
        message = str(
            platform_result.get("message")
            or result_data.get("message")
            or task.payload.get("message")
            or ""
        ).strip()
        message_sent = bool(result_data.get("message_sent")) or bool(result_data.get("outreach_sent")) or any(
            token in {"message_sent", "outreach_sent", "send_message", "send_outreach", "outreach"}
            for token in action_tokens
            if token
        )
        if not message:
            return None
        if message_sent or str(task.payload.get("message") or "").strip():
            return message
        return None

    def _configured_cooldown_days(self) -> int:
        try:
            return max(int(self.settings.provider_runtime_settings().cooldown_days or 30), 1)
        except (TypeError, ValueError):
            return 30

    def _state_machine_retry_policy(self, node: dict[str, Any] | None) -> dict[str, int] | None:
        raw_policy = dict((node or {}).get("retryPolicy") or (node or {}).get("retry_policy") or {})
        if not raw_policy:
            return None
        try:
            max_retries = max(int(raw_policy.get("maxRetries", raw_policy.get("max_retries", 0)) or 0), 0)
            retry_after_hours = max(int(raw_policy.get("retryAfterHours", raw_policy.get("retry_after_hours", 0)) or 0), 0)
            close_after_hours = max(int(raw_policy.get("closeAfterHours", raw_policy.get("close_after_hours", 0)) or 0), 0)
        except (TypeError, ValueError):
            return None
        if retry_after_hours <= 0 or close_after_hours <= 0:
            return None
        return {
            "maxRetries": max_retries,
            "retryAfterHours": retry_after_hours,
            "closeAfterHours": close_after_hours,
        }

    def _candidate_retry_state(self, subject: Any, *, current_status: str) -> dict[str, Any]:
        snapshot_metadata = dict(dict(getattr(subject, "state_snapshot", {}) or {}).get("snapshot_metadata") or {})
        retry_state = dict(snapshot_metadata.get("waiting_retry") or {})
        if str(retry_state.get("status") or "").strip() != current_status:
            return {}
        return retry_state

    def _set_candidate_retry_state(
        self,
        subject: Any,
        *,
        status: str,
        retry_count: int,
        last_outbound_at: Any,
        policy: dict[str, int] | None,
        closed_at: Any = None,
        close_reason: str | None = None,
    ) -> None:
        snapshot = dict(getattr(subject, "state_snapshot", {}) or {}) or default_candidate_state_snapshot(status=status)
        snapshot_metadata = dict(snapshot.get("snapshot_metadata") or {})
        state = {
            "status": status,
            "retry_count": max(int(retry_count or 0), 0),
            "last_outbound_at": getattr(last_outbound_at, "isoformat", lambda: str(last_outbound_at))() if last_outbound_at else None,
        }
        if policy:
            state.update(
                {
                    "max_retries": int(policy.get("maxRetries") or 0),
                    "retry_after_hours": int(policy.get("retryAfterHours") or 0),
                    "close_after_hours": int(policy.get("closeAfterHours") or 0),
                }
            )
        if retry_count > 0 and last_outbound_at is not None:
            state["last_retry_at"] = getattr(last_outbound_at, "isoformat", lambda: str(last_outbound_at))()
        if closed_at is not None:
            state["closed_at"] = getattr(closed_at, "isoformat", lambda: str(closed_at))()
        if close_reason:
            state["close_reason"] = close_reason
        snapshot_metadata["waiting_retry"] = {key: value for key, value in state.items() if value is not None}
        snapshot["snapshot_metadata"] = snapshot_metadata
        subject.state_snapshot = snapshot

    def _clear_candidate_retry_state(self, subject: Any) -> None:
        snapshot = dict(getattr(subject, "state_snapshot", {}) or {})
        if not snapshot:
            return
        snapshot_metadata = dict(snapshot.get("snapshot_metadata") or {})
        if "waiting_retry" not in snapshot_metadata:
            return
        snapshot_metadata.pop("waiting_retry", None)
        snapshot["snapshot_metadata"] = snapshot_metadata
        subject.state_snapshot = snapshot

    def _extract_candidate_rollback_signal(self, result: AgentResult) -> dict[str, Any] | None:
        if not isinstance(result.data, dict):
            return None
        raw_signal = result.data.get("rollback_signal") or result.data.get("rollbackSignal")
        if not isinstance(raw_signal, dict):
            return None

        to_status = str(raw_signal.get("to_status") or raw_signal.get("toStatus") or "").strip()
        if to_status not in {"candidate_withdrew", "cooldown"}:
            return None

        reason = str(
            raw_signal.get("reason")
            or raw_signal.get("override_reason")
            or raw_signal.get("overrideReason")
            or raw_signal.get("summary")
            or result.content
            or ""
        ).strip()
        if not reason:
            return None

        evidence_excerpt = str(
            raw_signal.get("evidence_excerpt")
            or raw_signal.get("evidenceExcerpt")
            or raw_signal.get("evidence")
            or ""
        ).strip()
        summary = str(raw_signal.get("summary") or result.data.get("summary") or result.content or reason).strip() or reason
        signal_kind = str(
            raw_signal.get("signal_kind")
            or raw_signal.get("signalKind")
            or raw_signal.get("kind")
            or "conversation_signal"
        ).strip() or "conversation_signal"

        cooldown_days: int | None = None
        if to_status == "cooldown":
            raw_days = raw_signal.get("cooldown_days", raw_signal.get("cooldownDays"))
            try:
                parsed_days = int(raw_days)
            except (TypeError, ValueError):
                parsed_days = 0
            cooldown_days = parsed_days if parsed_days > 0 else self._configured_cooldown_days()

        note_parts = [summary]
        if evidence_excerpt and evidence_excerpt not in summary:
            note_parts.append(f"证据：{evidence_excerpt}")

        return {
            "to_status": to_status,
            "reason": reason,
            "summary": summary,
            "signal_kind": signal_kind,
            "evidence_excerpt": evidence_excerpt or None,
            "cooldown_days": cooldown_days,
            "note": "\n".join(part for part in note_parts if part).strip(),
            "raw_signal": dict(raw_signal),
        }

    def _maybe_apply_candidate_rollback_signal(
        self,
        session: Session,
        *,
        task: TaskEnvelope,
        result: AgentResult,
        candidate: Any,
    ):
        signal = self._extract_candidate_rollback_signal(result)
        if signal is None:
            return candidate

        current_status = resolve_candidate_current_status(candidate)
        target_status = str(signal["to_status"]).strip()
        candidate_repo = CandidateRepository(session)
        application_id, _person_id, application = self._task_subject_ids(session, task)
        status_subject = application or candidate
        if application is not None:
            current_status = resolve_candidate_current_status(application)
        try:
            if current_status != target_status:
                transition_result = self._agent_transition_candidate(
                    session,
                    task=task,
                    candidate=candidate,
                    application=application,
                    to_status=target_status,
                    note=str(signal["note"] or "").strip() or None,
                    trigger="conversation_signal",
                    override_reason=str(signal["reason"] or "").strip(),
                    metadata={
                        "signal_kind": signal["signal_kind"],
                        "conversation_signal": {
                            "to_status": target_status,
                            "reason": signal["reason"],
                            "summary": signal["summary"],
                            "evidence_excerpt": signal["evidence_excerpt"],
                            "cooldown_days": signal["cooldown_days"],
                            "raw_signal": signal["raw_signal"],
                        },
                    },
                )
                candidate = candidate_repo.resolve(transition_result.candidate_id) or candidate
                if application_id:
                    application = CandidateApplicationRepository(session).get(application_id) or application
                    status_subject = application or candidate
                transition_record = transition_result.transition_record
                result.metadata["candidate_transition"] = {
                    "kind": "rollback_signal",
                    "candidate_id": candidate.id,
                    "from_status": transition_result.from_status,
                    "to_status": transition_result.to_status,
                    "actor": transition_record.actor,
                    "trigger": transition_record.trigger,
                    "override_reason": transition_record.override_reason,
                    "note": transition_record.note,
                }
            if target_status == "cooldown":
                if application is not None:
                    application.cooldown_until = utcnow() + timedelta(days=int(signal["cooldown_days"] or self._configured_cooldown_days()))
                else:
                    candidate.cooldown_until = utcnow() + timedelta(days=int(signal["cooldown_days"] or self._configured_cooldown_days()))
            else:
                if application is not None:
                    application.cooldown_until = None
                else:
                    candidate.cooldown_until = None
            session.commit()
            session.refresh(candidate)
            if application is not None:
                session.refresh(application)
        except StateMachineValidationError as exc:
            self.events.publish(
                "warning",
                "runtime",
                "Ignored runtime rollback signal because the target transition was invalid.",
                task_id=task.task_id,
                candidate_id=getattr(candidate, "id", None),
                to_status=target_status,
                error=str(exc),
            )
            return candidate

        result.metadata["rollback_signal_applied"] = True
        self._clear_candidate_retry_state(status_subject)
        self._append_progression_action(
            result,
            {
                "kind": "rollback_signal",
                "task_type": task.task_type,
                "candidate_id": candidate.id,
                "to_status": target_status,
                "reason": signal["reason"],
                "signal_kind": signal["signal_kind"],
            },
        )
        return candidate

    def _waiting_status_for_outbound_task(self, *, task: TaskEnvelope, current_status: str) -> str | None:
        if task.task_type == "candidate_outreach":
            if current_status in {"outreach_pending", "outreach_sent", "no_response"}:
                return "outreach_sent"
            if current_status in {"resume_requested", "contact_requested", "interview_scheduled", "offer_sent"}:
                return current_status
            return None
        if task.task_type == "resume_collection":
            if current_status in {"in_conversation", "resume_requested"}:
                return "resume_requested"
        return None

    def _record_waiting_candidate_outbound(
        self,
        session: Session,
        *,
        task: TaskEnvelope,
        result: AgentResult,
        candidate: Any,
        outbound_message: str,
    ):
        application_id, _person_id, application = self._task_subject_ids(session, task)
        subject = application or candidate
        current_status = resolve_candidate_current_status(subject)
        waiting_status = self._waiting_status_for_outbound_task(task=task, current_status=current_status)
        if waiting_status is None:
            return candidate

        retry_context = dict(task.payload.get("retryContext") or task.payload.get("retry_context") or {})
        state_machine = self._load_state_machine_snapshot() or ensure_latest_state_machine(session)
        retry_policy = self._state_machine_retry_policy(self._state_machine_node(state_machine, waiting_status))
        retry_count = 0
        raw_retry_count = retry_context.get("retryCount", retry_context.get("retry_count"))
        try:
            retry_count = max(int(raw_retry_count or 0), 0)
        except (TypeError, ValueError):
            retry_count = 0
        if retry_count == 0:
            retry_state = self._candidate_retry_state(subject, current_status=waiting_status)
            try:
                retry_count = max(int(retry_state.get("retry_count") or 0), 0)
            except (TypeError, ValueError):
                retry_count = 0

        if current_status != waiting_status:
            try:
                transition_result = self._agent_transition_candidate(
                    session,
                    task=task,
                    candidate=candidate,
                    application=application,
                    to_status=waiting_status,
                    note=outbound_message,
                    trigger="retry_policy_retry" if retry_count > 0 else None,
                    metadata={
                        "retry_context": retry_context,
                        "outbound_message": outbound_message,
                    },
                )
                candidate = CandidateRepository(session).resolve(transition_result.candidate_id) or candidate
                if application_id:
                    application = CandidateApplicationRepository(session).get(application_id) or application
                    subject = application or candidate
            except StateMachineValidationError:
                return candidate

        contacted_at = utcnow()
        if application is not None:
            application.last_contacted_at = contacted_at
        self._set_candidate_retry_state(
            subject,
            status=waiting_status,
            retry_count=retry_count,
            last_outbound_at=contacted_at,
            policy=retry_policy,
        )
        session.flush()
        return candidate

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
            "application_id": task.application_id,
            "candidate_id": task.candidate_id,
            "platform": task.platform,
            "attempts": task.attempts,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "created_at": task.created_at.isoformat(),
        }

    def _append_progression_action(self, result: AgentResult, action: dict[str, Any]) -> None:
        normalized = _json_ready(action)
        actions = list(result.metadata.get("progression_actions") or [])
        marker = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
        markers = {
            json.dumps(_json_ready(item), ensure_ascii=False, sort_keys=True, default=str)
            for item in actions
            if isinstance(item, dict)
        }
        if marker in markers:
            return
        actions.append(normalized)
        result.metadata["progression_actions"] = actions[-10:]

    def _candidate_progression_action_snapshots(self, result: AgentResult) -> list[dict[str, Any]]:
        actions = [dict(item) for item in list(result.metadata.get("progression_actions") or []) if isinstance(item, dict)]
        transition = result.metadata.get("candidate_transition")
        if isinstance(transition, dict):
            actions.append(dict(transition))
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in actions:
            marker = json.dumps(_json_ready(item), ensure_ascii=False, sort_keys=True, default=str)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(item)
        return deduped

    def _should_persist_candidate_progression_evolution_artifact(self, task: TaskEnvelope, result: AgentResult) -> bool:
        if self.session_factory is None or not (task.application_id or task.candidate_id):
            return False
        if not result.success:
            return False
        if task.task_type not in self._autonomy_candidate_progression_task_types():
            return False
        if result.metadata.get("candidate_progression_artifact_id"):
            return False
        if result.status in {"waiting_human", "waiting_candidate", "blocked", "failed"}:
            return False
        return bool(self._candidate_progression_action_snapshots(result))

    def _build_candidate_progression_feature_snapshot(
        self,
        task: TaskEnvelope,
        *,
        session_context: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = dict((session_context or {}).get("candidate") or {})
        application = dict(candidate.get("application") or {})
        application_state = dict(application.get("state_snapshot") or {})
        application_metadata = dict(application.get("application_metadata") or {})
        ai_scores = dict(candidate.get("ai_scores") or {})
        selection = dict(task.payload.get("selection") or {})
        resume_status = str(
            application_metadata.get("resume_status")
            or application_state.get("resume_status")
            or ""
        ).strip().lower()
        return {
            "applicationId": candidate.get("application_id") or task.application_id or task.candidate_id,
            "candidateId": candidate.get("id") or task.metadata.get("person_id") or task.candidate_id,
            "currentStatus": candidate.get("current_status"),
            "deepestMilestone": candidate.get("deepest_milestone"),
            "jobDescriptionId": candidate.get("job_description_id") or candidate.get("jd_id"),
            "hasResume": bool(
                application.get("resume_available")
                or application_metadata.get("resume_available")
                or application_state.get("resume_available")
                or resume_status in {"received", "available", "ready", "present"}
            ),
            "hasContactInfo": bool(
                dict(candidate.get("contact_info") or {})
                or dict((candidate.get("person") or {}).get("contact_info") or {})
            ),
            "aiScore": ai_scores.get("overall") or ai_scores.get("score"),
            "aiDecision": ai_scores.get("decision") or ai_scores.get("status"),
            "selectionReason": selection.get("reason"),
            "selectionScoreBreakdown": dict(selection.get("scoreBreakdown") or {}),
        }

    def _build_candidate_progression_instruction(
        self,
        task: TaskEnvelope,
        *,
        session_context: dict[str, Any],
        actions: list[dict[str, Any]],
        result: AgentResult,
    ) -> str:
        candidate = dict((session_context or {}).get("candidate") or {})
        candidate_name = str(candidate.get("name") or "candidate").strip()
        stage_label = self._humanize_task_label(self._adaptive_stage_for_task(task) or task.task_type)
        action_labels = [str(item.get("kind") or item.get("message_type") or item.get("task_type") or "action") for item in actions[:3]]
        outcome = str(extract_business_status(result.data, fallback=result.status) or result.status or "completed").strip()
        summary = str(result.data.get("summary") or result.content or "").strip()
        action_phrase = "、".join(action_labels) if action_labels else stage_label
        instruction = f"在 {stage_label} 阶段，依据候选人信号选择 {action_phrase} 并记录结果为 {outcome}。"
        if candidate_name:
            instruction = f"针对 {candidate_name}，{instruction}"
        if summary:
            instruction = f"{instruction} 关键信息：{summary[:240]}"
        return instruction

    def _merge_generated_skill_contract(
        self,
        base_contract: dict[str, Any],
        draft: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(draft, dict):
            return base_contract

        merged = _json_ready(base_contract)
        draft_contract = dict(draft.get("skill_contract") or {}) if isinstance(draft.get("skill_contract"), dict) else {}

        candidate_name = str(draft.get("skill_name") or draft_contract.get("name") or "").strip()
        if candidate_name:
            merged["name"] = candidate_name
        description = str(draft_contract.get("description") or draft.get("summary") or draft.get("description") or "").strip()
        if description:
            merged["description"] = description

        for field_name in ("category", "platform", "bound_to_stage", "risk_level"):
            value = draft_contract.get(field_name)
            if value not in (None, "", [], {}):
                merged[field_name] = value

        for field_name in ("input_schema", "output_schema", "strategy", "execution_hints", "health_check_config", "skill_metadata"):
            existing = dict(merged.get(field_name) or {})
            incoming = dict(draft_contract.get(field_name) or {})
            if field_name == "strategy":
                content = str(draft.get("content") or "").strip()
                if content:
                    incoming.setdefault("instruction", content)
            if field_name == "skill_metadata":
                summary = str(draft.get("summary") or "").strip()
                if summary:
                    incoming.setdefault("model_summary", summary)
            merged[field_name] = {
                **existing,
                **incoming,
            }

        return merged

    def _build_candidate_progression_skill_contract(
        self,
        task: TaskEnvelope,
        *,
        session_context: dict[str, Any],
        skill_context: dict[str, Any] | None,
        actions: list[dict[str, Any]],
        result: AgentResult,
    ) -> dict[str, Any]:
        adaptive_stage = self._adaptive_stage_for_task(task) or task.task_type
        skill_key = str((skill_context or {}).get("skill_id") or f"{adaptive_stage}_progression").strip()
        platform = str((skill_context or {}).get("platform") or task.platform or "runtime-scene").strip() or "runtime-scene"
        criteria_ref = dict(task.metadata.get("state_machine_criteria_ref") or {})
        features = self._build_candidate_progression_feature_snapshot(task, session_context=session_context)
        outcome_status = str(extract_business_status(result.data, fallback=result.status) or result.status or "completed").strip()
        contract = {
            "skill_id": skill_key,
            "name": str((skill_context or {}).get("name") or f"{self._humanize_task_label(adaptive_stage)} Runtime Skill").strip(),
            "description": f"自动沉淀的 {adaptive_stage} 候选人推进策略。",
            "category": "candidate_progression",
            "platform": platform,
            "bound_to_stage": str((skill_context or {}).get("bound_to_stage") or adaptive_stage).strip() or adaptive_stage,
            "input_schema": {"candidateId": "string", "currentStatus": "string", "taskType": "string"},
            "output_schema": {"status": "string", "summary": "string"},
            "strategy": {
                "instruction": self._build_candidate_progression_instruction(
                    task,
                    session_context=session_context,
                    actions=actions,
                    result=result,
                ),
                "learned_patterns": [features],
                "observed_actions": actions,
            },
            "execution_hints": {
                "domain": task.platform,
                "observed_outcomes": [
                    {
                        "status": outcome_status,
                        "summary": str(result.data.get("summary") or result.content or "").strip() or None,
                        "success": result.success,
                    }
                ],
                "criteria_ref": criteria_ref or None,
            },
            "risk_level": "medium",
            "health_check_config": {"expected_result_status": outcome_status or "completed"},
            "skill_metadata": {
                "artifact_origin": "candidate_progression",
                "source_task_id": task.task_id,
                "source_task_type": task.task_type,
                "application_id": task.application_id,
                "candidate_id": task.metadata.get("person_id") or task.candidate_id,
                "state_machine_version": task.metadata.get("state_machine_version"),
                "criteria_ref": criteria_ref or None,
            },
        }
        return self._merge_generated_skill_contract(contract, result.skill_draft)

    def _persist_candidate_progression_evolution_artifact(
        self,
        task: TaskEnvelope,
        result: AgentResult,
        *,
        session_context: dict[str, Any],
        skill_context: dict[str, Any] | None,
    ) -> None:
        if not self._should_persist_candidate_progression_evolution_artifact(task, result):
            return

        try:
            with self.session_factory() as session:
                repo = EvolutionArtifactRepository(session)
                existing = repo.find_by_source_task_id(source_task_id=task.task_id, artifact_kind="skill_draft")
                if existing is not None:
                    result.metadata["candidate_progression_artifact_id"] = existing.id
                    result.metadata["skip_runtime_skill_draft_learning"] = True
                    return

                profile = ensure_primary_recruit_agent_profile(session)
                adaptive_stage = self._adaptive_stage_for_task(task) or task.task_type
                actions = self._candidate_progression_action_snapshots(result)
                features = self._build_candidate_progression_feature_snapshot(task, session_context=session_context)
                skill_contract = self._build_candidate_progression_skill_contract(
                    task,
                    session_context=session_context,
                    skill_context=skill_context,
                    actions=actions,
                    result=result,
                )
                artifact_body = {
                    "skill_contract": skill_contract,
                    "decision_trace": {
                        "candidate_features": features,
                        "action": actions,
                        "result": {
                            "status": str(extract_business_status(result.data, fallback=result.status) or result.status or "completed"),
                            "success": result.success,
                            "summary": str(result.data.get("summary") or result.content or "").strip() or None,
                            "data": _json_ready(result.data or {}),
                        },
                    },
                }
                if isinstance(result.skill_draft, dict) and result.skill_draft:
                    artifact_body["model_skill_draft"] = _json_ready(result.skill_draft)

                validate_evolution_artifact(
                    artifact_kind="skill_draft",
                    status="pending_review",
                    artifact_body=artifact_body,
                )

                candidate = dict((session_context or {}).get("candidate") or {})
                person_id = str(
                    candidate.get("person_id")
                    or candidate.get("id")
                    or task.metadata.get("person_id")
                    or task.candidate_id
                    or ""
                ).strip() or None
                application_id = str(candidate.get("application_id") or task.application_id or "").strip() or None
                candidate_name = str(candidate.get("name") or task.candidate_id or "candidate").strip()
                title = f"{candidate_name} · {self._humanize_task_label(adaptive_stage)} 技能草案"
                summary = str(result.data.get("summary") or result.content or "").strip() or "自动沉淀了一次候选人推进策略。"
                metadata = {
                    "source_task_id": task.task_id,
                    "task_type": task.task_type,
                    "adaptive_stage": adaptive_stage,
                    "application_id": application_id,
                    "candidate_id": person_id,
                    "goal_spec_id": str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "").strip() or None,
                    "state_machine_version": task.metadata.get("state_machine_version"),
                    "promotion_fallback_platform": str((skill_context or {}).get("platform") or task.platform or "runtime-scene"),
                    "promotion_fallback_stage": str((skill_context or {}).get("bound_to_stage") or adaptive_stage),
                    "selection": _json_ready(task.payload.get("selection") or {}),
                }
                item = repo.create(
                    {
                        "agent_profile_id": profile.id,
                        "artifact_kind": "skill_draft",
                        "title": title,
                        "summary": summary,
                        "status": "pending_review",
                        "related_candidate_id": person_id,
                        "related_skill_id": (skill_context or {}).get("id"),
                        "proposed_by": "runtime",
                        "artifact_body": artifact_body,
                        "artifact_metadata": metadata,
                    }
                )
                result.metadata["candidate_progression_artifact_id"] = item.id
                result.metadata["skip_runtime_skill_draft_learning"] = True
                self.events.publish(
                    "info",
                    "evolution",
                    "Captured candidate progression skill draft for review.",
                    artifact_id=item.id,
                    task_id=task.task_id,
                    candidate_id=person_id,
                )
        except Exception as exc:  # pragma: no cover - defensive guard
            result.metadata["candidate_progression_artifact_error"] = str(exc)
            self.events.publish(
                "error",
                "evolution",
                "Failed to persist candidate progression skill draft artifact.",
                task_id=task.task_id,
                candidate_id=task.metadata.get("person_id") or task.candidate_id,
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
                application_id=snapshot.get("application_id"),
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
        follow_up_stage = str((result.data or {}).get("follow_up_stage") or "").strip() or self._next_adaptive_stage(task, result)
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
        if self._adaptive_stage_for_task(task) == "goal_intake":
            task_spec_id = str((result.data or {}).get("task_spec_id") or result.metadata.get("task_spec_id") or "").strip()
            execution_plan_id = str((result.data or {}).get("execution_plan_id") or result.metadata.get("execution_plan_id") or "").strip()
            execution_episode_id = str((result.data or {}).get("execution_episode_id") or result.metadata.get("execution_episode_id") or "").strip()
            scene_snapshot = (result.data or {}).get("scene_snapshot")
            if task_spec_id and execution_plan_id:
                payload["task_spec_id"] = task_spec_id
                payload["execution_plan_id"] = execution_plan_id
                metadata["task_spec_id"] = task_spec_id
                metadata["execution_plan_id"] = execution_plan_id
            if execution_episode_id:
                payload["execution_episode_id"] = execution_episode_id
                metadata["execution_episode_id"] = execution_episode_id
            if isinstance(scene_snapshot, dict):
                payload["scene_snapshot"] = dict(scene_snapshot)
                metadata["scene_snapshot"] = dict(scene_snapshot)
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
                application_id=task.application_id or task.candidate_id,
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
        candidate_session = session_repo.by_candidate_id(candidate.candidate_person_id)
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
