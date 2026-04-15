from __future__ import annotations

import json
import re
import traceback
from dataclasses import asdict, dataclass, field
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
    ExecutionGraphProjectionRepository,
    ExecutionTraceRepository,
    GoalSpecRepository,
    OperatorInteractionRepository,
    ApprovalRepository,
    CandidateRepository,
    CandidateSessionRepository,
    CandidateStageEventRepository,
    CommunicationLogRepository,
    DecisionLogRepository,
    SkillRepository,
    ResumeArtifactRepository,
    StrategyFragmentRepository,
)
from scene_pilot.runtime.agent_loop import AgentLoop
from scene_pilot.runtime.models import AgentResult, ToolExecutionResult
from scene_pilot.runtime.result_semantics import extract_business_status
from scene_pilot.scheduler.queue import TaskEnvelope
from scene_pilot.scheduler.scheduler import ScheduledOutcome, SerialScheduler
from scene_pilot.schemas import TaskCompileRequest
from scene_pilot.services.context_assembler import ContextAssemblerService
from scene_pilot.services.events import EventStreamService
from scene_pilot.services.feature_flags import FeatureFlagService
from scene_pilot.services.adaptive_runtime import resolve_adaptive_stage
from scene_pilot.services.recruit_agent import default_candidate_state_snapshot, ensure_primary_recruit_agent_profile
from scene_pilot.services.runtime_control import RuntimeControlService
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

                goal_intake_result = self._run_goal_intake(task)
                if goal_intake_result is not None:
                    return _complete(goal_intake_result)

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
                        resume_request_message = self._resume_collection_outbound_message(task=task, result=result)
                        if resume_request_message:
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
        stage_repo = CandidateStageEventRepository(session)
        resume_repo = ResumeArtifactRepository(session)
        persisted_ids: list[str] = []
        goal_spec_id = str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "").strip() or None

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
                existing = candidate_repo.by_platform_candidate_id(
                    normalized["platform"],
                    normalized["platform_candidate_id"],
                )
            if existing is None and normalized.get("name"):
                for item in candidate_repo.list(limit=200, offset=0):
                    if item.platform == normalized["platform"] and item.name == normalized["name"]:
                        existing = item
                        break

            created = False
            previous_status = existing.status if existing is not None else None
            previous_stage = existing.current_stage_key if existing is not None else None
            if existing is None:
                existing = candidate_repo.create(
                    {
                        "name": normalized["name"],
                        "platform": normalized["platform"],
                        "platform_candidate_id": normalized.get("platform_candidate_id"),
                        "status": normalized["status"],
                        "current_stage_key": normalized["current_stage_key"],
                        "jd_id": normalized.get("jd_id"),
                        "contact_info": normalized["contact_info"],
                        "state_snapshot": normalized["state_snapshot"],
                        "resume_path": normalized.get("resume_path"),
                        "online_resume_text": normalized.get("online_resume_text"),
                        "ai_scores": normalized.get("ai_scores", {}),
                        "ai_reasoning": normalized.get("ai_reasoning"),
                    }
                )
                created = True
            else:
                merged_contact = dict(existing.contact_info or {})
                merged_contact.update(normalized["contact_info"])
                existing.name = normalized["name"] or existing.name
                existing.platform = normalized["platform"] or existing.platform
                existing.platform_candidate_id = normalized.get("platform_candidate_id") or existing.platform_candidate_id
                existing.status = normalized["status"] or existing.status
                existing.current_stage_key = normalized["current_stage_key"] or existing.current_stage_key
                existing.jd_id = normalized.get("jd_id") or existing.jd_id
                existing.contact_info = merged_contact
                existing.state_snapshot = normalized["state_snapshot"] or existing.state_snapshot
                existing.resume_path = normalized.get("resume_path") or existing.resume_path
                existing.online_resume_text = normalized.get("online_resume_text") or existing.online_resume_text
                existing.ai_scores = normalized.get("ai_scores") or existing.ai_scores
                existing.ai_reasoning = normalized.get("ai_reasoning") or existing.ai_reasoning
                session.flush()

            candidate_session = session_repo.get_or_create(
                existing.id,
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
                normalized=normalized,
                task=task,
                adaptive_stage=adaptive_stage,
            )

            if created or previous_status != existing.status or previous_stage != existing.current_stage_key:
                stage_repo.create(
                    {
                        "candidate_id": existing.id,
                        "event_type": "stage_transition" if not created else "candidate_discovered",
                        "from_status": previous_status,
                        "to_status": existing.status,
                        "phase_key": str((existing.state_snapshot or {}).get("current_phase_key") or "discovery_and_screening"),
                        "phase_label": str((existing.state_snapshot or {}).get("current_phase_label") or "发现与初筛"),
                        "stage_key": existing.current_stage_key or adaptive_stage,
                        "stage_label": str((existing.state_snapshot or {}).get("current_stage_label") or existing.current_stage_key or adaptive_stage),
                        "actor": "agent",
                        "source": "runtime",
                        "note": normalized.get("ai_reasoning"),
                        "payload": {
                            "task_id": task.task_id,
                            "task_type": task.task_type,
                            "goal_spec_id": goal_spec_id,
                            "source_scene": normalized["state_snapshot"].get("snapshot_metadata", {}).get("source_scene"),
                        },
                        "occurred_at": utcnow(),
                    }
                )

            if existing.id not in persisted_ids:
                persisted_ids.append(existing.id)

        session.commit()
        return persisted_ids

    def _persist_resume_artifact(
        self,
        session: Session,
        *,
        resume_repo: ResumeArtifactRepository,
        candidate,
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

        existing_artifacts = resume_repo.by_candidate(candidate.id, limit=20, offset=0)
        for existing in existing_artifacts:
            existing_path = str(existing.file_path or "").strip()
            existing_text = str(existing.extracted_text or "").strip()
            if local_resume_path and existing_path == local_resume_path:
                if not candidate.resume_path:
                    candidate.resume_path = local_resume_path
                    session.flush()
                return
            if synthesized_resume_text and existing_text == synthesized_resume_text:
                if local_resume_path and not candidate.resume_path:
                    candidate.resume_path = local_resume_path
                    session.flush()
                return

        if local_resume_path:
            candidate.resume_path = local_resume_path
        elif source_resume_path and not candidate.resume_path:
            candidate.resume_path = source_resume_path
        session.flush()

        resume_repo.create(
            {
                "candidate_id": candidate.id,
                "source": normalized.get("platform") or candidate.platform or task.platform,
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
            "jd_id": payload.get("jd_id") or task.payload.get("jd_id"),
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
                        "candidate_id": task.candidate_id,
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
        candidate_repo = CandidateRepository(session)
        resume_repo = ResumeArtifactRepository(session)
        candidate_records = [
            item
            for item in (
                candidate_repo.resolve(candidate_id)
                for candidate_id in candidate_ids
            )
            if item is not None
        ]
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

        for candidate in candidate_records:
            if str(candidate.resume_path or "").strip() or str(candidate.online_resume_text or "").strip():
                has_resume_or_profile = True
            _remember_local_path(candidate.resume_path)
            for artifact in resume_repo.by_candidate(candidate.id, limit=50, offset=0):
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
