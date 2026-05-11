from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.agent_runtime.engine import InteractionEngine, InteractionEngineConfig
from recruit_agent.agent_runtime.types import InteractionOutput, LLMProvider
from recruit_agent.db.base import utcnow
from recruit_agent.evolution.learning_writer import LearningWriter
from recruit_agent.memory.filesystem import MemoryFileStore
from recruit_agent.memory.service import MemoryService
from recruit_agent.memory.writeback import (
    MemoryWritebackPolicy,
    apply_stable_memory_facts,
    memory_writeback_policy_from_config,
    select_stable_memory_facts_with_llm,
    should_start_memory_writeback_job,
)
from recruit_agent.models.domain import (
    AgentRun,
    AgentRunCheckpoint,
    AgentRuntimeEvent,
    AgentSession,
    AgentTurnRecord,
    ApprovalItem,
    Candidate,
    CandidateApplication,
    GoalSpec,
    McpServer,
    OperatorInteraction,
    RecruitAgentProfile,
    Skill,
)
from recruit_agent.product_adapters.limits import TurnLimits
from recruit_agent.agents.outcome import AgentTurnOutcome
from recruit_agent.plugins.host import PluginHost
from recruit_agent.product_adapters.context_builder import build_autonomous_turn_context
from recruit_agent.product_adapters.mcp_resource_context import build_mcp_resource_context, extract_mcp_resource_context_policy
from recruit_agent.product_adapters.result_semantics import extract_execution_status
from recruit_agent.product_adapters.target_contracts import derive_browser_target
from recruit_agent.capabilities.tools import ToolRegistry
from recruit_agent.skills.context import build_skill_context_injections

AUTONOMOUS_OPEN_RUN_STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "active",
    "waiting_human",
    "waiting_candidate",
    "blocked",
    "paused",
    "resumable",
)


@dataclass(slots=True)
class AutonomousAdapter:
    session_factory: sessionmaker[Session]
    provider: LLMProvider
    tool_registry: ToolRegistry
    plugin_host: PluginHost
    learning_writer: LearningWriter | None = None
    mcp_registry: Any | None = None
    memory_file_store: MemoryFileStore | None = None
    turn_limits: TurnLimits = field(default_factory=TurnLimits)
    pending_permission_engines: dict[str, InteractionEngine] = field(default_factory=dict)

    def run_turn_from_envelope(self, envelope: dict[str, Any]) -> AgentTurnOutcome:
        with self.session_factory() as session:
            run = self._resolve_run(session, envelope)
            run.status = "running"
            if run.started_at is None:
                run.started_at = utcnow()
            next_seq = self._next_turn_seq(session, run.id)
            memory_service = MemoryService(session)
            agent_session = session.get(AgentSession, run.session_id)
            agent_profile_id = None if agent_session is None else agent_session.agent_profile_id
            goal_spec = session.get(GoalSpec, run.goal_spec_id) if run.goal_spec_id else None
            resolved_application_id = _resolve_application_subject(run=run, envelope=envelope, goal=goal_spec)
            resolved_person_id = _resolve_person_subject(
                session,
                run=run,
                envelope=envelope,
                goal=goal_spec,
                application_id=resolved_application_id,
            )
            if resolved_application_id and str((run.runtime_metadata or {}).get("application_id") or "").strip() != resolved_application_id:
                runtime_metadata = dict(run.runtime_metadata or {})
                runtime_metadata["application_id"] = resolved_application_id
                run.runtime_metadata = runtime_metadata
            if resolved_application_id and str(run.application_id or "").strip() != resolved_application_id:
                run.application_id = resolved_application_id
            if resolved_person_id and str(run.person_id or "").strip() != resolved_person_id:
                run.person_id = resolved_person_id
            if goal_spec is not None:
                goal_spec.status = "running"
                goal_spec.latest_run_id = run.run_id
                goal_spec.last_activity_at = utcnow()
            turn = AgentTurnRecord(
                run_pk=run.id,
                seq=next_seq,
                trigger_type=str(envelope.get("trigger_type") or "manual"),
                status="started",
                phase="sense",
            )
            session.add(turn)
            session.flush()
            _append_runtime_event(
                session,
                run=run,
                goal=goal_spec,
                turn_id=turn.turn_id,
                seq=next_seq,
                event_type="adapter_turn_started",
                message="adapter_turn_started",
                payload={"trigger_type": turn.trigger_type},
            )
            session.commit()

            goal_constraints = dict(getattr(goal_spec, "constraints", {}) or {})
            goal_constraints["run_pk"] = run.id
            goal_constraints["agent_profile_id"] = agent_profile_id
            goal_constraints["goal_kind"] = str(getattr(goal_spec, "goal_kind", None) or run.run_type or "").strip()
            goal_constraints["success_criteria"] = dict(getattr(goal_spec, "success_criteria", {}) or {})
            goal_constraints["context_hints"] = dict(getattr(goal_spec, "context_hints", {}) or {})
            goal_constraints["trial_budget"] = dict(getattr(goal_spec, "trial_budget", {}) or {})
            goal_constraints["global_scope_ref"] = (
                str(goal_constraints.get("global_scope_ref") or "") or agent_profile_id
            )
            goal_constraints["source_kind"] = "autonomous"
            if resolved_application_id:
                goal_constraints["application_id"] = resolved_application_id
            browser_target = derive_browser_target(
                existing=goal_constraints.get("browser_target") or goal_constraints["context_hints"].get("browser_target"),
                structured_sources=(
                    goal_constraints,
                    goal_constraints["context_hints"],
                    run.context_manifest,
                    run.runtime_metadata,
                    envelope.get("world_snapshot"),
                    envelope.get("metadata"),
                ),
                text_sources=(
                    (run.context_manifest or {}).get("goal"),
                    getattr(goal_spec, "goal_text", None),
                    getattr(goal_spec, "title", None),
                ),
            )
            if browser_target:
                goal_constraints["browser_target"] = browser_target
                goal_constraints["context_hints"]["browser_target"] = browser_target

            scope_kind = str(envelope.get("scope_kind") or ("application" if resolved_application_id else run.lane or "global"))
            if scope_kind == "application":
                scope_ref = str(envelope.get("scope_ref") or resolved_application_id or run.id)
            else:
                scope_ref = str(envelope.get("scope_ref") or resolved_person_id or run.person_id or run.job_description_id or run.id)

            memory_scope_kind = str(goal_constraints.get("memory_scope_kind") or scope_kind or "global").strip() or "global"
            memory_scope_ref = str(goal_constraints.get("memory_scope_ref") or scope_ref or agent_profile_id or run.id)
            if memory_scope_kind == "global" and agent_profile_id:
                memory_scope_ref = str(goal_constraints.get("memory_scope_ref") or goal_constraints.get("global_scope_ref") or agent_profile_id)
            memory_entries = _read_memory_entries(
                memory_service,
                scope_kind=memory_scope_kind,
                scope_ref=memory_scope_ref,
                agent_profile_id=agent_profile_id,
            )
            if self.memory_file_store is not None:
                memory_entries.extend(
                    _read_memory_file_entries(
                        self.memory_file_store,
                        scope_kind=memory_scope_kind,
                        scope_ref=memory_scope_ref,
                        agent_profile_id=agent_profile_id,
                    )
                )
            agent_profile = session.get(RecruitAgentProfile, agent_profile_id) if agent_profile_id else None
            memory_writeback_policy = _memory_writeback_policy(agent_profile)
            goal_text = str(
                (run.context_manifest or {}).get("goal")
                or getattr(goal_spec, "goal_text", None)
                or run.run_type
                or "Autonomous execution"
            )
            goal_title = str(getattr(goal_spec, "title", None) or run.run_type or "Autonomous execution").strip() or None
            active_turn_limits = _resolve_turn_limits(self.turn_limits, goal_spec)

            last_outcome = AgentTurnOutcome(status="continue", gate_signal="continue")
            runtime_event_seq = 0
            engine_output_count = 0
            try:
                world_snapshot = dict(envelope.get("world_snapshot") or {})
                mcp_resource_contexts = _mcp_resource_contexts(
                    self.mcp_registry,
                    goal_constraints,
                    dict(goal_constraints.get("context_hints") or {}),
                    world_snapshot,
                    dict(envelope.get("metadata") or {}) if isinstance(envelope.get("metadata"), dict) else {},
                    envelope,
                )
                adapter_context = build_autonomous_turn_context(
                    title=goal_title,
                    goal_text=goal_text,
                    scope_kind=scope_kind,
                    scope_ref=scope_ref,
                    constraints=goal_constraints,
                    world_snapshot=world_snapshot,
                    recent_events=memory_service.fetch_recent_events(run_id=run.id, limit=8),
                    memory_entries=memory_entries,
                    available_tools=sorted(self.tool_registry.tools.keys()),
                    skill_contexts=self._skill_contexts(
                        session,
                        query=goal_text,
                        task_text=json.dumps(
                            {
                                "goal": goal_text,
                                "constraints": goal_constraints,
                                "world_snapshot": world_snapshot,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                        category=str(getattr(goal_spec, "goal_kind", None) or run.run_type or ""),
                        explicit_skill_ids=_explicit_skill_refs(goal_constraints, envelope),
                        token_budget=_skill_context_token_budget(goal_constraints, active_turn_limits),
                    ),
                    available_mcps=self._available_mcp_names(session),
                    mcp_resource_contexts=mcp_resource_contexts,
                )
                approved_tool_calls = _approved_tool_calls_from_envelope(envelope, run=run)
                if approved_tool_calls:
                    engine = self.pending_permission_engines.pop(run.id, None)
                    if engine is None:
                        raise RuntimeError("Pending runtime permission state is not available for this run")
                    output_iter = engine.resolvePermission(approved=True)
                else:
                    engine = InteractionEngine(
                        InteractionEngineConfig(
                            conversation_id=run.session_id or run.id,
                            provider=self.provider,
                            tools=self.tool_registry.to_agent_runtime_tools(),
                            initial_messages=adapter_context.initial_messages,
                            max_llm_invocations=active_turn_limits.max_llm_invocations or 12,
                            initial_seq=runtime_event_seq + 1,
                        )
                    )
                    output_iter = engine.submitMessage(adapter_context.turn_input)
                tool_calls: list[dict[str, Any]] = []
                tool_results: list[dict[str, Any]] = []
                final_output = ""
                gate_signal = "goal_done"
                status = "complete"
                for output in output_iter:
                    runtime_event_seq = max(runtime_event_seq, int(output.seq or runtime_event_seq))
                    engine_output_count += 1
                    _record_engine_output(session, run=run, goal=goal_spec, turn_id=turn.turn_id, output=output)
                    if output.type == "assistant_message_completed":
                        final_output = str(output.data.get("message") or "")
                    elif output.type == "llm_invocation_completed":
                        structured_status = _outcome_from_structured_result_data(output.data.get("result_data"))
                        if structured_status is not None:
                            status, gate_signal = structured_status
                    elif output.type == "tool_event":
                        data = dict(output.data)
                        if data.get("kind") in {"tool_call_started", "tool_use_completed"}:
                            tool_calls.append(data)
                        elif data.get("kind") == "tool_result_ready":
                            tool_results.append(
                                {
                                    "tool_name": data.get("tool_name"),
                                    "is_error": data.get("is_error", False),
                                    "output": data.get("content"),
                                }
                            )
                    elif output.type == "permission_requested":
                        gate_signal = "wait_human"
                        status = "wait_human"
                        tool_calls = [_permission_payload(dict(output.data))]
                        self.pending_permission_engines[run.id] = engine
                    elif output.type == "turn_failed":
                        gate_signal = "escalate"
                        status = "error"
                    elif output.type == "turn_interrupted":
                        gate_signal = "paused"
                        status = "cancelled"
                last_outcome = AgentTurnOutcome(
                    status=status,  # type: ignore[arg-type]
                    gate_signal=gate_signal,  # type: ignore[arg-type]
                    final_output=final_output,
                    tool_calls=[],
                    tool_results=[],
                    metadata={
                        "tool_calls": tool_calls,
                        "pending_tool_calls": tool_calls if status == "wait_human" else [],
                        "tool_results": tool_results,
                        "interaction_engine": True,
                    },
                )
                if status != "wait_human":
                    self.pending_permission_engines.pop(run.id, None)
            except Exception as exc:
                self.pending_permission_engines.pop(run.id, None)
                turn.status = "failed"
                turn.phase = "evaluate"
                turn.outcome_kind = "error"
                turn.turn_metadata = {"error": str(exc), "engine_output_count": engine_output_count}
                run.turns_count = int(run.turns_count or 0) + 1
                run.status = "failed"
                run.finished_at = utcnow()
                run.last_error = str(exc)
                if goal_spec is not None:
                    goal_spec.status = "failed"
                    goal_spec.latest_run_id = run.run_id
                    goal_spec.last_activity_at = utcnow()
                _resolve_wait_human_records(session, run=run)
                _append_runtime_event(
                    session,
                    run=run,
                    goal=goal_spec,
                    turn_id=turn.turn_id,
                    seq=next_seq,
                    event_type="adapter_failed",
                    message=str(exc),
                    payload={"status": "error", "error": str(exc)},
                )
                session.commit()
                raise

            turn.status = _turn_status_from_outcome(last_outcome)
            turn.phase = "evaluate"
            turn.outcome_kind = last_outcome.status
            turn.turn_metadata = {
                "final_output": last_outcome.final_output,
                "gate_signal": last_outcome.gate_signal,
                "engine_output_count": engine_output_count,
            }
            run.turns_count = int(run.turns_count or 0) + 1
            run.status = _run_status_from_outcome(last_outcome)
            if run.status in {"completed", "waiting_human", "blocked", "failed", "cancelled"}:
                run.finished_at = utcnow()
            run.last_error = None
            if goal_spec is not None:
                goal_spec.status = run.status
                goal_spec.latest_run_id = run.run_id
                goal_spec.last_activity_at = utcnow()
            if _is_waiting_human(last_outcome):
                _materialize_wait_human_records(
                    session,
                    run=run,
                    turn=turn,
                    envelope=envelope,
                    outcome=last_outcome,
                )
            else:
                _resolve_wait_human_records(session, run=run)
            session.commit()
            session.refresh(run)
            self._maybe_record_trial_skill(
                session,
                run=run,
                goal=goal_spec,
                turn=turn,
                outcome=last_outcome,
                engine_output_count=engine_output_count,
                agent_profile_id=agent_profile_id,
            )
            if run.status == "completed":
                _maybe_write_turn_memory(
                    session,
                    memory_service,
                    provider=self.provider,
                    scope_kind=memory_scope_kind,
                    scope_ref=memory_scope_ref,
                    agent_profile_id=agent_profile_id,
                    run=run,
                    turn=turn,
                    goal_text=goal_text,
                    memory_entries=memory_entries,
                    policy=memory_writeback_policy,
                    force=_memory_writeback_force_requested(envelope, goal_constraints),
                    memory_file_store=self.memory_file_store,
                )
                session.commit()
            return last_outcome

    def recover_stale(self) -> int:
        with self.session_factory() as session:
            stmt = select(AgentRun).where(AgentRun.status == "running").order_by(AgentRun.updated_at.desc(), AgentRun.id.desc())
            recovered = 0
            for run in session.scalars(stmt).all():
                _interrupt_open_run(
                    session,
                    run=run,
                    reason="Recovered stale autonomous run during startup.",
                )
                recovered += 1

            latest_open_run_by_session: dict[str, str] = {}
            open_stmt = (
                select(AgentRun)
                .where(
                    AgentRun.agent_kind == "autonomous",
                    AgentRun.status.in_(AUTONOMOUS_OPEN_RUN_STATUSES),
                )
                .order_by(
                    AgentRun.session_id.asc(),
                    AgentRun.updated_at.desc(),
                    AgentRun.created_at.desc(),
                    AgentRun.id.desc(),
                )
            )
            for run in session.scalars(open_stmt).all():
                latest_open_run_id = latest_open_run_by_session.get(run.session_id)
                if latest_open_run_id is None:
                    latest_open_run_by_session[run.session_id] = run.id
                    continue
                if run.id == latest_open_run_id:
                    continue
                _interrupt_open_run(
                    session,
                    run=run,
                    reason="Superseded during startup recovery because a newer open run already exists.",
                )
                recovered += 1
            if recovered:
                session.commit()
            return recovered

    def _resolve_run(self, session: Session, envelope: dict[str, Any]) -> AgentRun:
        run_pk = str(envelope.get("run_pk") or "").strip()
        if run_pk:
            run = session.get(AgentRun, run_pk)
            if run is None:
                raise KeyError(f"unknown run: {run_pk}")
            return run
        run_id = str(envelope.get("run_id") or "").strip()
        if run_id:
            stmt = select(AgentRun).where(AgentRun.run_id == run_id)
            run = session.scalars(stmt).first()
            if run is not None:
                return run
        raise KeyError("run envelope must include run_pk or run_id")

    def _next_turn_seq(self, session: Session, run_pk: str) -> int:
        stmt = select(func.max(AgentTurnRecord.seq)).where(AgentTurnRecord.run_pk == run_pk)
        return int(session.scalar(stmt) or 0) + 1

    def _skill_contexts(
        self,
        session: Session,
        *,
        query: str | None = None,
        task_text: str | None = None,
        category: str | None = None,
        explicit_skill_ids: list[str] | None = None,
        token_budget: int | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(Skill).where(Skill.status.in_(("trial", "active"))).order_by(Skill.name.asc(), Skill.skill_id.asc())
        skills = list(session.scalars(stmt).all())
        return [
            item.to_prompt_payload()
            for item in build_skill_context_injections(
                skills,
                query=query,
                task_text=task_text,
                category=category,
                explicit_skill_ids=explicit_skill_ids,
                token_budget=token_budget,
            )
        ]

    def _available_mcp_names(self, session: Session) -> list[str]:
        stmt = select(McpServer.name).order_by(McpServer.name.asc())
        return [str(name) for name in session.scalars(stmt).all()]

    def _maybe_record_trial_skill(
        self,
        session: Session,
        *,
        run: AgentRun,
        goal: GoalSpec | None,
        turn: AgentTurnRecord,
        outcome: AgentTurnOutcome,
        engine_output_count: int,
        agent_profile_id: str | None,
    ) -> None:
        if run.status != "completed":
            return
        if self.learning_writer is None:
            return

        from recruit_agent.services.evolution import build_skill_distill_review_payload, distill_skill_contract_from_run

        turn_events = self._turn_events(session, run_id=run.id, turn_id=turn.turn_id)
        tool_activity = _summarize_turn_tool_activity(turn_events)
        if not tool_activity:
            return

        review_payload = build_skill_distill_review_payload(
            run_id=str(run.run_id or run.id),
            run_type=run.run_type,
            goal_kind=None if goal is None else goal.goal_kind,
            engine_output_count=engine_output_count,
            final_output=outcome.final_output,
            tool_activity=tool_activity,
            event_outline=_summarize_turn_events(turn_events),
        )
        seq = max(int(engine_output_count or 0), 1) + 1
        _append_runtime_event(
            session,
            run=run,
            goal=goal,
            turn_id=turn.turn_id,
            seq=seq,
            event_type="skill_distill.started",
            message="distilling trial skill from successful run",
            payload={"run_id": run.run_id, "goal_kind": None if goal is None else goal.goal_kind},
        )
        session.commit()
        try:
            draft_contract = distill_skill_contract_from_run(
                provider=self.provider,
                review_payload=review_payload,
            )
            recorded = self.learning_writer.record_skill_draft(
                draft_contract=draft_contract,
                tags=_skill_distill_tags(run=run, goal=goal),
                trial_metrics={"runs": 1, "successes": 1},
                learning_content=_skill_learning_audit_log(review_payload, draft_contract),
                source_run_id=run.id,
                source_turn_id=turn.turn_id,
                source_kind="autonomous",
                agent_profile_id=agent_profile_id,
                proposed_by="autonomous",
                environment_scope=_skill_environment_scope(run=run, goal=goal),
            )
        except Exception as exc:
            session.rollback()
            _append_runtime_event(
                session,
                run=run,
                goal=goal,
                turn_id=turn.turn_id,
                seq=seq,
                event_type="skill_distill.failed",
                message=str(exc),
                payload={"error": str(exc)},
            )
            session.commit()
            return

        _append_runtime_event(
            session,
            run=run,
            goal=goal,
            turn_id=turn.turn_id,
            seq=seq,
            event_type="skill_distill.completed",
            message=str(recorded.get("skill_name") or "trial skill recorded"),
            payload={
                "artifact_id": recorded.get("artifact_id"),
                "skill_id": recorded.get("skill_id"),
                "auto_promoted": recorded.get("auto_promoted"),
                "queued": recorded.get("queued"),
            },
        )
        session.commit()

    def _turn_events(self, session: Session, *, run_id: str, turn_id: str) -> list[AgentRuntimeEvent]:
        stmt = (
            select(AgentRuntimeEvent)
            .where(AgentRuntimeEvent.run_id == run_id, AgentRuntimeEvent.turn_id == turn_id)
            .order_by(AgentRuntimeEvent.seq.asc(), AgentRuntimeEvent.created_at.asc(), AgentRuntimeEvent.id.asc())
        )
        return list(session.scalars(stmt).all())


def _run_status_from_outcome(outcome: AgentTurnOutcome) -> str:
    if outcome.status == "complete" or outcome.gate_signal == "goal_done":
        return "completed"
    if outcome.status == "wait_human" or outcome.gate_signal == "wait_human":
        return "waiting_human"
    if outcome.status == "cancelled" or outcome.gate_signal == "paused":
        return "cancelled"
    if outcome.status == "error":
        return "failed"
    if outcome.status == "escalate" or outcome.gate_signal == "escalate":
        return "blocked"
    if outcome.gate_signal == "budget_exhausted":
        return "blocked"
    return "running"


def _turn_status_from_outcome(outcome: AgentTurnOutcome) -> str:
    if outcome.status == "complete" or outcome.gate_signal == "goal_done":
        return "completed"
    if outcome.status == "wait_human" or outcome.gate_signal == "wait_human":
        return "waiting_human"
    if outcome.status == "cancelled" or outcome.gate_signal == "paused":
        return "cancelled"
    if outcome.status == "error":
        return "failed"
    if outcome.status == "escalate" or outcome.gate_signal == "escalate":
        return "failed"
    if outcome.gate_signal == "budget_exhausted":
        return "failed"
    return "running"


def _is_waiting_human(outcome: AgentTurnOutcome) -> bool:
    return outcome.status == "wait_human" or outcome.gate_signal == "wait_human"


def _outcome_from_structured_result_data(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    execution_status = extract_execution_status(value)
    if execution_status in {"wait_human", "waiting_human", "approval_required"}:
        return "wait_human", "wait_human"
    if execution_status in {"failed", "fail", "error"}:
        return "error", "escalate"
    if execution_status in {"blocked", "blocked_environment", "escalate"}:
        return "escalate", "escalate"
    if execution_status in {"completed", "complete", "success", "done"}:
        return "complete", "goal_done"
    return None


def _resolve_turn_limits(defaults: TurnLimits, goal_spec: GoalSpec | None) -> TurnLimits:
    if goal_spec is None:
        return defaults

    overrides = dict(getattr(goal_spec, "trial_budget", {}) or {})
    if not overrides:
        return defaults

    resolved: dict[str, int | None] = {}
    field_aliases = {
        "max_llm_invocations": ("max_llm_invocations",),
        "turn_timeout_seconds": ("turn_timeout_seconds",),
        "token_budget": ("token_budget",),
        "cooldown_seconds": ("cooldown_seconds",),
    }
    unlimited_fields = {"max_llm_invocations", "turn_timeout_seconds", "token_budget"}
    for field_name, aliases in field_aliases.items():
        raw_value = next((overrides.get(alias) for alias in aliases if overrides.get(alias) is not None), None)
        if raw_value is None:
            continue
        if isinstance(raw_value, str) and raw_value.strip().lower() in {"", "none", "null", "unlimited", "disabled"}:
            if field_name in unlimited_fields:
                resolved[field_name] = None
            continue
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            continue
        if parsed <= 0:
            if field_name in unlimited_fields:
                resolved[field_name] = None
            continue
        resolved[field_name] = parsed

    if not resolved:
        return defaults
    return replace(defaults, **resolved)


def _read_memory_entries(
    memory_service: MemoryService,
    *,
    scope_kind: str,
    scope_ref: str,
    agent_profile_id: str | None,
) -> list[dict[str, Any]]:
    try:
        return memory_service.read(
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            agent_profile_id=agent_profile_id,
            limit=12,
        )
    except Exception:
        return []


def _read_memory_file_entries(
    memory_file_store: MemoryFileStore,
    *,
    scope_kind: str,
    scope_ref: str,
    agent_profile_id: str | None,
) -> list[dict[str, Any]]:
    try:
        entries: list[dict[str, Any]] = []
        for item in memory_file_store.list_files(scope_kind=scope_kind, scope_ref=scope_ref, agent_profile_id=agent_profile_id)[:12]:
            content = memory_file_store.read_file(
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                agent_profile_id=agent_profile_id,
                path=str(item["path"]),
            ).get("content", "")
            entries.append(
                {
                    "memory_item_id": item["path"],
                    "kind": "memory_file",
                    "summary": _first_non_empty_memory_line(str(content or "")) or item["path"],
                    "content": {"path": item["path"], "text": content},
                    "updated_at": item.get("updated_at"),
                }
            )
        return entries
    except Exception:
        return []


def _first_non_empty_memory_line(text: str) -> str | None:
    for line in str(text or "").splitlines():
        stripped = line.strip(" #-\t")
        if stripped:
            return stripped[:240]
    return None


def _maybe_write_turn_memory(
    session: Session,
    memory_service: MemoryService,
    *,
    provider: LLMProvider,
    scope_kind: str,
    scope_ref: str,
    agent_profile_id: str | None,
    run: AgentRun,
    turn: AgentTurnRecord,
    goal_text: str,
    memory_entries: list[dict[str, Any]],
    policy: MemoryWritebackPolicy,
    force: bool = False,
    memory_file_store: MemoryFileStore | None = None,
) -> None:
    state = _memory_writeback_state(run)
    last_turn_seq = _bounded_int(state.get("last_turn_seq"), default=0, minimum=0, maximum=1_000_000)
    evidence_text, completed_turns_since_last_job = _memory_writeback_evidence_since_last_job(
        session,
        run=run,
        last_turn_seq=last_turn_seq,
        goal_text=goal_text,
    )
    if not should_start_memory_writeback_job(
        policy,
        completed_turns_since_last_job=completed_turns_since_last_job,
        evidence_text=evidence_text,
        force=force,
    ):
        return
    attempted = _write_turn_memory(
        memory_service,
        provider=provider,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        agent_profile_id=agent_profile_id,
        run=run,
        turn=turn,
        goal_text=goal_text,
        evidence_text=evidence_text,
        memory_entries=memory_entries,
        policy=policy,
        memory_file_store=memory_file_store,
    )
    if attempted:
        _record_memory_writeback_job(run, turn=turn, evidence_text=evidence_text)


def _write_turn_memory(
    memory_service: MemoryService,
    *,
    provider: LLMProvider,
    scope_kind: str,
    scope_ref: str,
    agent_profile_id: str | None,
    run: AgentRun,
    turn: AgentTurnRecord,
    goal_text: str,
    evidence_text: str,
    memory_entries: list[dict[str, Any]],
    policy: MemoryWritebackPolicy,
    memory_file_store: MemoryFileStore | None = None,
) -> bool:
    try:
        facts = select_stable_memory_facts_with_llm(
            provider,
            goal_text=goal_text,
            final_output=evidence_text,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            memory_entries=memory_entries,
            max_stable_facts=policy.max_stable_facts,
        )
        apply_stable_memory_facts(
            memory_service,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            agent_profile_id=agent_profile_id,
            facts=facts,
            run_id=str(run.run_id or run.id),
            run_pk=run.id,
            turn_id=turn.turn_id,
            source="memory_writeback_pipeline",
            policy=policy,
        )
        if memory_file_store is not None:
            _append_stable_memory_facts_to_file(
                memory_file_store,
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                agent_profile_id=agent_profile_id,
                facts=facts,
                run=run,
                turn=turn,
            )
        return True
    except Exception:
        return False


def _memory_writeback_policy(profile: RecruitAgentProfile | None) -> MemoryWritebackPolicy:
    config = dict((profile.memory_policy if profile is not None else {}) or {}).get("writeback")
    return memory_writeback_policy_from_config(dict(config or {}))


def _append_stable_memory_facts_to_file(
    memory_file_store: MemoryFileStore,
    *,
    scope_kind: str,
    scope_ref: str,
    agent_profile_id: str | None,
    facts: list[dict[str, Any]],
    run: AgentRun,
    turn: AgentTurnRecord,
) -> None:
    lines: list[str] = []
    for fact in facts:
        summary = _first_non_empty_memory_line(str(fact.get("summary") or fact.get("fact") or ""))
        if not summary:
            continue
        lines.append(f"- {summary} (run={run.run_id or run.id}, turn={turn.turn_id})")
    if not lines:
        return
    memory_file_store.write_file(
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        agent_profile_id=agent_profile_id,
        path="stable_facts.md",
        content="\n".join(lines) + "\n",
        mode="append",
    )


def _memory_writeback_state(run: AgentRun) -> dict[str, Any]:
    runtime_metadata = dict(run.runtime_metadata or {})
    state = runtime_metadata.get("memory_writeback")
    return dict(state) if isinstance(state, dict) else {}


def _memory_writeback_evidence_since_last_job(
    session: Session,
    *,
    run: AgentRun,
    last_turn_seq: int,
    goal_text: str,
) -> tuple[str, int]:
    stmt = (
        select(AgentTurnRecord)
        .where(
            AgentTurnRecord.run_pk == run.id,
            AgentTurnRecord.seq > last_turn_seq,
            AgentTurnRecord.status == "completed",
        )
        .order_by(AgentTurnRecord.seq.asc(), AgentTurnRecord.id.asc())
    )
    rows = list(session.scalars(stmt).all())
    parts: list[str] = [f"Goal: {goal_text}"]
    for item in rows:
        metadata = dict(item.turn_metadata or {})
        final_output = str(metadata.get("final_output") or "").strip()
        if final_output:
            parts.append(f"Turn {item.seq}: {final_output}")
    return "\n\n".join(parts).strip(), len(rows)


def _record_memory_writeback_job(run: AgentRun, *, turn: AgentTurnRecord, evidence_text: str) -> None:
    runtime_metadata = dict(run.runtime_metadata or {})
    runtime_metadata["memory_writeback"] = {
        "last_turn_seq": turn.seq,
        "last_turn_id": turn.turn_id,
        "last_completed_at": utcnow().isoformat(),
        "last_evidence_chars": len(str(evidence_text or "")),
    }
    run.runtime_metadata = runtime_metadata


def _memory_writeback_force_requested(envelope: dict[str, Any], goal_constraints: dict[str, Any]) -> bool:
    for source in (envelope.get("memory_writeback"), goal_constraints.get("memory_writeback")):
        if isinstance(source, dict) and source.get("force") is True:
            return True
        if str(source or "").strip().lower() == "force":
            return True
    return False


def _mcp_resource_contexts(mcp_registry: Any | None, *sources: dict[str, Any]) -> list[dict[str, Any]]:
    if mcp_registry is None:
        return []
    policy = extract_mcp_resource_context_policy(*sources)
    if not policy.get("resources"):
        return []
    return build_mcp_resource_context(mcp_registry, policy)


def _permission_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": str(data.get("tool_name") or ""),
        "tool_use_id": str(data.get("tool_use_id") or ""),
        "tool_call_id": str(data.get("tool_call_id") or ""),
        "input": dict(data.get("input") or {}),
        "reason": str(data.get("reason") or "pending_confirmation"),
    }


def _approved_tool_calls_from_envelope(envelope: dict[str, Any], *, run: AgentRun) -> list[dict[str, Any]]:
    candidates = envelope.get("approved_tool_calls")
    if not isinstance(candidates, list):
        candidates = (run.wakeup_state or {}).get("approved_tool_calls")
    if not isinstance(candidates, list):
        candidates = (run.wakeup_state or {}).get("pending_tool_calls")
    return [dict(item) for item in candidates or [] if isinstance(item, dict)]


def _skill_distill_tags(*, run: AgentRun, goal: GoalSpec | None) -> list[str]:
    tags = ["autonomous", "skill_distill"]
    goal_kind = str((goal.goal_kind if goal is not None else run.run_type) or "").strip()
    if goal_kind:
        tags.append(goal_kind)
    environment_scope = _skill_environment_scope(run=run, goal=goal)
    if environment_scope in {"mock_only", "simulated"}:
        tags.append(environment_scope)
    return tags


def _explicit_skill_refs(*sources: Any) -> list[str]:
    refs: list[str] = []
    for source in sources:
        _collect_explicit_skill_refs(source, refs)
    return refs


def _collect_explicit_skill_refs(source: Any, refs: list[str]) -> None:
    if isinstance(source, dict):
        for key, value in source.items():
            if key in {"explicit_skill_ids", "skill_ids", "skills", "explicit_skills"}:
                for item in value if isinstance(value, list) else [value]:
                    if isinstance(item, dict):
                        item = item.get("skill_id") or item.get("id") or item.get("name")
                    _append_ref(refs, item)
            elif isinstance(value, dict):
                _collect_explicit_skill_refs(value, refs)
            elif key in {"goal_text", "instruction", "query", "message"}:
                _collect_skill_markers(str(value or ""), refs)
        return
    if isinstance(source, list):
        for item in source:
            _collect_explicit_skill_refs(item, refs)
        return
    if isinstance(source, str):
        _collect_skill_markers(source, refs)


def _collect_skill_markers(text: str, refs: list[str]) -> None:
    for marker in re.findall(r'(?:skill:|@|\$)([A-Za-z0-9_.:-]+)|skill\s+"([^"]+)"', text):
        _append_ref(refs, marker[0] or marker[1])


def _append_ref(refs: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in refs:
        refs.append(text)


def _skill_context_token_budget(goal_constraints: dict[str, Any], limits: TurnLimits) -> int | None:
    trial_budget = dict(goal_constraints.get("trial_budget") or {})
    raw = trial_budget.get("skill_context_token_budget") or goal_constraints.get("skill_context_token_budget")
    if raw is not None:
        return _bounded_int(raw, default=1200, minimum=100, maximum=4000)
    if limits.token_budget:
        return _bounded_int(int(limits.token_budget) // 5, default=1200, minimum=100, maximum=3000)
    return None


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _skill_environment_scope(*, run: AgentRun, goal: GoalSpec | None) -> str:
    goal_constraints = dict(getattr(goal, "constraints", {}) or {})
    context_hints = dict(goal_constraints.get("context_hints") or getattr(goal, "context_hints", {}) or {})
    run_metadata = dict(run.runtime_metadata or {})
    candidates = [
        goal_constraints.get("environment_scope"),
        context_hints.get("environment_scope"),
        run_metadata.get("environment_scope"),
    ]
    if any(bool((value is True)) for value in (context_hints.get("mock_environment"), run_metadata.get("mock_environment"))):
        return "mock_only"
    if any(str(value or "").strip().lower().replace("-", "_") in {"mock", "mock_only", "boss_mock", "fixture"} for value in candidates):
        return "mock_only"
    if any(str(value or "").strip().lower().replace("-", "_") in {"simulated", "simulation"} for value in candidates):
        return "simulated"
    if any(str(value or "").strip().lower().replace("-", "_") == "real_site_verified" for value in candidates):
        return "real_site_verified"
    return "unspecified"


def _skill_learning_audit_log(review_payload: dict[str, Any], draft_contract: dict[str, Any]) -> str:
    return json.dumps(
        {
            "review_payload": review_payload,
            "draft_contract": draft_contract,
        },
        ensure_ascii=False,
        default=str,
    )


def _summarize_turn_tool_activity(events: list[AgentRuntimeEvent]) -> list[dict[str, Any]]:
    activity: list[dict[str, Any]] = []
    for event in events:
        if event.event_type not in {"tool_event", "permission_requested"}:
            continue
        payload = dict(event.payload or {})
        data = dict(payload.get("data") or {})
        kind = str(data.get("kind") or event.event_type)
        tool_name = str(data.get("tool_name") or data.get("name") or event.message or "").strip()
        if not tool_name:
            continue
        item = {
            "event_type": event.event_type,
            "kind": kind,
            "tool_name": tool_name,
        }
        if event.event_type == "tool_event" and kind in {"tool_call_started", "tool_use_completed"}:
            item["arguments"] = dict(data.get("input") or {})
        elif event.event_type == "tool_event" and kind == "tool_result_ready":
            item["is_error"] = bool(data.get("is_error"))
            item["output_excerpt"] = _compact_event_payload(data.get("content"))
        else:
            item["reason"] = str(data.get("reason") or event.message or "").strip() or None
        activity.append(item)
    return activity[:12]


def _summarize_turn_events(events: list[AgentRuntimeEvent]) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    for event in events:
        if event.event_type in {"llm_invocation_started", "llm_invocation_completed", "tool_event", "permission_requested"}:
            outline.append(
                {
                    "event_type": event.event_type,
                    "message": event.message,
                }
            )
    return outline[-12:]


def _compact_event_payload(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:320] if text else None


def _runtime_output_payload(output: InteractionOutput) -> dict[str, Any]:
    return {
        "type": output.type,
        "conversation_id": output.conversation_id,
        "turn_id": output.turn_id,
        "seq": output.seq,
        "data": dict(output.data or {}),
    }


def _record_engine_output(
    session: Session,
    *,
    run: AgentRun,
    goal: GoalSpec | None,
    turn_id: str,
    output: InteractionOutput,
) -> None:
    _append_runtime_event(
        session,
        run=run,
        goal=goal,
        turn_id=turn_id,
        seq=output.seq,
        event_type=output.type,
        message=output.type,
        payload=_runtime_output_payload(output),
    )
    session.commit()


def _append_runtime_event(
    session: Session,
    *,
    run: AgentRun,
    goal: GoalSpec | None,
    turn_id: str | None,
    seq: int,
    event_type: str,
    message: str,
    payload: dict[str, Any],
) -> None:
    event_payload = dict(payload or {})
    application_id = _resolve_run_application_id(run)
    if application_id and not str(event_payload.get("application_id") or "").strip():
        event_payload["application_id"] = application_id
    session.add(
        AgentRuntimeEvent(
            session_id=run.session_id,
            run_id=run.id,
            person_id=run.person_id,
            application_id=application_id,
            source="autonomous",
            event_type=event_type,
            message=message,
            turn_id=turn_id,
            seq=seq,
            payload=event_payload,
        )
    )
    if goal is not None:
        goal.last_activity_at = utcnow()


def _resolve_run_application_id(run: AgentRun) -> str | None:
    for raw in (
        run.application_id,
        (run.runtime_metadata or {}).get("application_id"),
        (run.context_manifest or {}).get("application_id"),
        (run.wakeup_state or {}).get("application_id"),
    ):
        normalized = str(raw or "").strip()
        if normalized:
            return normalized
    return None


def _resolve_run_person_id(run: AgentRun) -> str | None:
    for raw in (
        run.person_id,
        (run.runtime_metadata or {}).get("person_id"),
        (run.context_manifest or {}).get("person_id"),
        (run.wakeup_state or {}).get("person_id"),
    ):
        normalized = str(raw or "").strip()
        if normalized:
            return normalized
    return None


def _resolve_application_subject(
    *,
    run: AgentRun,
    envelope: dict[str, Any],
    goal: GoalSpec | None = None,
) -> str | None:
    metadata = dict(envelope.get("metadata") or {}) if isinstance(envelope.get("metadata"), dict) else {}
    world_snapshot = dict(envelope.get("world_snapshot") or {}) if isinstance(envelope.get("world_snapshot"), dict) else {}
    candidates: list[Any] = [
        envelope.get("application_id"),
        metadata.get("application_id"),
        world_snapshot.get("application_id"),
        _resolve_run_application_id(run),
    ]
    if goal is not None:
        candidates.extend(
            [
                (goal.constraints or {}).get("application_id"),
                (goal.context_hints or {}).get("application_id"),
                (goal.goal_metadata or {}).get("application_id"),
            ]
        )
    for raw in candidates:
        normalized = str(raw or "").strip()
        if normalized:
            return normalized
    return None


def _resolve_person_subject(
    session: Session,
    *,
    run: AgentRun,
    envelope: dict[str, Any],
    goal: GoalSpec | None = None,
    application_id: str | None = None,
) -> str | None:
    metadata = dict(envelope.get("metadata") or {}) if isinstance(envelope.get("metadata"), dict) else {}
    world_snapshot = dict(envelope.get("world_snapshot") or {}) if isinstance(envelope.get("world_snapshot"), dict) else {}
    candidates: list[Any] = [
        envelope.get("person_id"),
        envelope.get("personId"),
        metadata.get("person_id"),
        metadata.get("personId"),
        world_snapshot.get("person_id"),
        world_snapshot.get("personId"),
        _resolve_run_person_id(run),
    ]
    if goal is not None:
        candidates.extend(
            [
                (goal.constraints or {}).get("person_id"),
                (goal.constraints or {}).get("personId"),
                (goal.context_hints or {}).get("person_id"),
                (goal.context_hints or {}).get("personId"),
                (goal.goal_metadata or {}).get("person_id"),
                (goal.goal_metadata or {}).get("personId"),
            ]
        )
    for raw in candidates:
        normalized = str(raw or "").strip()
        if normalized:
            return normalized
    resolved_application_id = str(application_id or "").strip()
    if not resolved_application_id:
        return None
    application = session.scalars(
        select(CandidateApplication).where(CandidateApplication.candidate_application_id == resolved_application_id)
    ).first()
    if application is None:
        return None
    person = session.get(Candidate, application.person_id)
    return str(person.candidate_person_id or "").strip() or None if person is not None else None


def _interrupt_open_run(session: Session, *, run: AgentRun, reason: str) -> None:
    run.status = "interrupted"
    if run.finished_at is None:
        run.finished_at = utcnow()
    if not run.last_error:
        run.last_error = reason
    checkpoint = session.scalars(
        select(AgentRunCheckpoint)
        .where(AgentRunCheckpoint.run_id == run.id, AgentRunCheckpoint.status == "open")
        .order_by(AgentRunCheckpoint.created_at.desc(), AgentRunCheckpoint.id.desc())
    ).first()
    if checkpoint is not None:
        checkpoint.status = "resolved"
        checkpoint.resolved_at = utcnow()
        checkpoint.resolved_by = "system"

        if checkpoint.approval_id:
            approval = session.get(ApprovalItem, checkpoint.approval_id)
            if approval is not None and approval.status == "pending":
                approval.status = "rejected"
                approval.reviewed_by = "system"
                approval.reviewed_at = utcnow()
                approval.notes = reason
                approval_payload = dict(approval.payload or {})
                approval_payload["resolution"] = {
                    "status": "rejected",
                    "reviewer": "system",
                    "reason": reason,
                    "approved": False,
                    "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None,
                }
                approval.payload = approval_payload

        interaction = session.scalars(
            select(OperatorInteraction)
            .where(OperatorInteraction.checkpoint_id == checkpoint.id, OperatorInteraction.status == "pending")
            .order_by(OperatorInteraction.created_at.desc(), OperatorInteraction.id.desc())
        ).first()
        if interaction is not None:
            interaction.status = "resolved"
            interaction.operator_response = {"action": "interrupt", "comment": reason}
            interaction.effect_summary = reason
            interaction.resolved_at = utcnow()
            interaction.resolved_by = "system"

    run.checkpoint_status = "resolved" if checkpoint is not None else "none"
    run.wakeup_state = {}
    goal_spec = session.get(GoalSpec, run.goal_spec_id) if run.goal_spec_id else None
    if goal_spec is not None and str(goal_spec.status or "").strip().lower() in AUTONOMOUS_OPEN_RUN_STATUSES:
        goal_spec.status = "interrupted"
        goal_spec.latest_run_id = run.run_id
        goal_spec.last_activity_at = utcnow()


def _materialize_wait_human_records(
    session: Session,
    *,
    run: AgentRun,
    turn: AgentTurnRecord,
    envelope: dict[str, Any],
    outcome: AgentTurnOutcome,
) -> None:
    pending_tool_calls = [
        payload
        for payload in list(outcome.metadata.get("pending_tool_calls") or [])
        if isinstance(payload, dict)
    ]
    tool_names = [
        _pending_tool_name(payload)
        for payload in pending_tool_calls
    ]
    first_tool_name = next((name for name in tool_names if name), None)
    title = (
        f"Approve autonomous tool call: {first_tool_name}"
        if first_tool_name
        else f"Resume autonomous run {run.run_id or run.id}"
    )
    summary = (
        f"Run {run.run_id or run.id} is waiting for operator confirmation"
        + (f" before executing {first_tool_name}." if first_tool_name else ".")
    )
    application_id = _resolve_application_subject(run=run, envelope=envelope)
    resume_envelope = _build_resume_envelope(
        run=run,
        envelope=envelope,
        pending_tool_calls=pending_tool_calls,
        application_id=application_id,
    )
    resume_task = {
        "task_id": run.queue_task_id or f"run-{run.id}",
        "task_type": "autonomous_turn",
        "priority": int(run.priority or 100),
        "payload": resume_envelope,
        "person_id": _resolve_run_person_id(run),
        "metadata": {
            "agent_kind": run.agent_kind,
            "goal_spec_id": run.goal_spec_id,
            "checkpoint_kind": "wait_human",
        },
    }
    if application_id:
        resume_task["application_id"] = application_id
        resume_task["metadata"]["application_id"] = application_id
    approval_payload = {
        "run_pk": run.id,
        "run_id": run.run_id,
        "turn_id": turn.turn_id,
        "pending_tool_calls": pending_tool_calls,
        "resume_task": resume_task,
        "checkpoint_kind": "wait_human",
    }
    if application_id:
        approval_payload["application_id"] = application_id
    approval = _upsert_wait_human_approval(
        session,
        run=run,
        turn=turn,
        title=title,
        summary=summary,
        payload=approval_payload,
        tool_name=first_tool_name,
        args_digest=_tool_args_digest(pending_tool_calls[0]) if pending_tool_calls else None,
    )
    checkpoint = _upsert_wait_human_checkpoint(
        session,
        run=run,
        approval=approval,
        title=title,
        summary=summary,
        payload={
            "run_pk": run.id,
            "run_id": run.run_id,
            "turn_id": turn.turn_id,
            "pending_tool_calls": pending_tool_calls,
            "resume_task": resume_task,
            **({"application_id": application_id} if application_id else {}),
        },
    )
    _upsert_wait_human_interaction(
        session,
        run=run,
        checkpoint=checkpoint,
        approval=approval,
        title=title,
        summary=summary,
        pending_tool_calls=pending_tool_calls,
        application_id=application_id,
    )
    run.checkpoint_status = "open"
    run.wakeup_state = {
        "checkpoint_id": checkpoint.id,
        "approval_id": approval.id,
        "pending_tool_calls": pending_tool_calls,
        **({"application_id": application_id} if application_id else {}),
    }


def _resolve_wait_human_records(session: Session, *, run: AgentRun) -> None:
    checkpoint = session.scalars(
        select(AgentRunCheckpoint)
        .where(AgentRunCheckpoint.run_id == run.id, AgentRunCheckpoint.status == "open")
        .order_by(AgentRunCheckpoint.created_at.desc(), AgentRunCheckpoint.id.desc())
    ).first()
    if checkpoint is None:
        run.checkpoint_status = "none"
        run.wakeup_state = {}
        return

    checkpoint.status = "resolved"
    checkpoint.resolved_at = utcnow()
    checkpoint.resolved_by = "system"
    interaction = session.scalars(
        select(OperatorInteraction)
        .where(OperatorInteraction.checkpoint_id == checkpoint.id, OperatorInteraction.status == "pending")
        .order_by(OperatorInteraction.created_at.desc(), OperatorInteraction.id.desc())
    ).first()
    if interaction is not None:
        interaction.status = "resolved"
        interaction.effect_summary = interaction.effect_summary or "Run resumed and checkpoint cleared."
        interaction.resolved_at = utcnow()
        interaction.resolved_by = interaction.resolved_by or "system"

    if checkpoint.approval_id:
        approval = session.get(ApprovalItem, checkpoint.approval_id)
        if approval is not None and approval.status == "pending":
            approval.status = "approved"
            approval.reviewed_by = approval.reviewed_by or "system"
            approval.reviewed_at = utcnow()
            approval.notes = approval.notes or "Auto-resolved after run resumed."
            payload = dict(approval.payload or {})
            payload.setdefault(
                "resolution",
                {
                    "status": "approved",
                    "reviewer": "system",
                    "reason": "run_resumed",
                    "approved": True,
                    "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None,
                },
            )
            approval.payload = payload

    run.checkpoint_status = "resolved"
    run.wakeup_state = {}


def _build_resume_envelope(
    *,
    run: AgentRun,
    envelope: dict[str, Any],
    pending_tool_calls: list[dict[str, Any]],
    application_id: str | None = None,
) -> dict[str, Any]:
    scope_kind = str(envelope.get("scope_kind") or ("application" if application_id else run.lane or "global"))
    if scope_kind == "application":
        scope_ref = str(envelope.get("scope_ref") or application_id or run.id)
    else:
        scope_ref = str(envelope.get("scope_ref") or _resolve_run_person_id(run) or run.job_description_id or run.id)
    payload: dict[str, Any] = {
        "run_pk": run.id,
        "run_id": run.run_id,
        "scope_kind": scope_kind,
        "scope_ref": scope_ref,
        "trigger_type": "resume",
    }
    if application_id:
        payload["application_id"] = application_id
    person_id = _resolve_run_person_id(run)
    if person_id:
        payload["person_id"] = person_id
    if isinstance(envelope.get("world_snapshot"), dict):
        payload["world_snapshot"] = dict(envelope.get("world_snapshot") or {})
    if pending_tool_calls:
        payload["approved_tool_calls"] = pending_tool_calls
    metadata = dict(envelope.get("metadata") or {}) if isinstance(envelope.get("metadata"), dict) else {}
    if application_id:
        metadata["application_id"] = application_id
    if person_id:
        metadata["person_id"] = person_id
    if metadata:
        payload["metadata"] = metadata
    return payload


def _upsert_wait_human_approval(
    session: Session,
    *,
    run: AgentRun,
    turn: AgentTurnRecord,
    title: str,
    summary: str,
    payload: dict[str, Any],
    tool_name: str | None,
    args_digest: str | None,
) -> ApprovalItem:
    checkpoint = session.scalars(
        select(AgentRunCheckpoint)
        .where(AgentRunCheckpoint.run_id == run.id, AgentRunCheckpoint.status == "open")
        .order_by(AgentRunCheckpoint.created_at.desc(), AgentRunCheckpoint.id.desc())
    ).first()
    approval = session.get(ApprovalItem, checkpoint.approval_id) if checkpoint and checkpoint.approval_id else None
    if approval is None:
        approval = ApprovalItem(
            target_type="blocked_task",
            target_id=run.run_id or run.id,
            title=title,
            status="pending",
            requested_by="autonomous",
            payload=payload,
            notes=summary,
            run_pk=run.id,
            turn_pk=turn.id,
            source_kind="autonomous",
            tool_name=tool_name,
            args_digest=args_digest,
            idempotency_key=f"wait-human:{run.id}:{turn.id}",
        )
        session.add(approval)
        session.flush()
        return approval

    approval.target_type = "blocked_task"
    approval.target_id = run.run_id or run.id
    approval.title = title
    approval.status = "pending"
    approval.payload = payload
    approval.notes = summary
    approval.run_pk = run.id
    approval.turn_pk = turn.id
    approval.source_kind = "autonomous"
    approval.tool_name = tool_name
    approval.args_digest = args_digest
    approval.reviewed_by = None
    approval.reviewed_at = None
    return approval


def _upsert_wait_human_checkpoint(
    session: Session,
    *,
    run: AgentRun,
    approval: ApprovalItem,
    title: str,
    summary: str,
    payload: dict[str, Any],
) -> AgentRunCheckpoint:
    checkpoint = session.scalars(
        select(AgentRunCheckpoint)
        .where(AgentRunCheckpoint.run_id == run.id, AgentRunCheckpoint.status == "open")
        .order_by(AgentRunCheckpoint.created_at.desc(), AgentRunCheckpoint.id.desc())
    ).first()
    if checkpoint is None:
        checkpoint = AgentRunCheckpoint(
            session_id=run.session_id,
            run_id=run.id,
            person_id=run.person_id,
            application_id=_resolve_run_application_id(run),
            approval_id=approval.id,
            checkpoint_kind="wait_human",
            status="open",
            title=title,
            summary=summary,
            payload=payload,
        )
        session.add(checkpoint)
        session.flush()
        return checkpoint

    checkpoint.approval_id = approval.id
    checkpoint.person_id = run.person_id
    checkpoint.application_id = _resolve_run_application_id(run)
    checkpoint.checkpoint_kind = "wait_human"
    checkpoint.status = "open"
    checkpoint.title = title
    checkpoint.summary = summary
    checkpoint.payload = payload
    checkpoint.resolved_by = None
    checkpoint.resolved_at = None
    return checkpoint


def _upsert_wait_human_interaction(
    session: Session,
    *,
    run: AgentRun,
    checkpoint: AgentRunCheckpoint,
    approval: ApprovalItem,
    title: str,
    summary: str,
    pending_tool_calls: list[dict[str, Any]],
    application_id: str | None = None,
) -> OperatorInteraction:
    interaction = session.scalars(
        select(OperatorInteraction)
        .where(OperatorInteraction.checkpoint_id == checkpoint.id, OperatorInteraction.status == "pending")
        .order_by(OperatorInteraction.created_at.desc(), OperatorInteraction.id.desc())
    ).first()
    interaction_metadata = {
        "pending_tool_calls": pending_tool_calls,
        "tool_names": [
            _pending_tool_name(payload)
            for payload in pending_tool_calls
        ],
    }
    if application_id:
        interaction_metadata["application_id"] = application_id
    if interaction is None:
        interaction = OperatorInteraction(
            session_id=run.session_id,
            run_id=run.id,
            checkpoint_id=checkpoint.id,
            approval_id=approval.id,
            goal_spec_id=run.goal_spec_id,
            person_id=run.person_id,
            application_id=application_id,
            lane=run.lane,
            interaction_type="confirm",
            status="pending",
            title=title,
            agent_prompt=summary,
            suggested_options=[
                {"action": "approve", "label": "批准并继续"},
                {"action": "reject", "label": "停止当前路径"},
            ],
            scope="run_only",
            interaction_metadata=interaction_metadata,
        )
        session.add(interaction)
        session.flush()
        return interaction

    interaction.approval_id = approval.id
    interaction.run_id = run.id
    interaction.goal_spec_id = run.goal_spec_id
    interaction.person_id = run.person_id
    interaction.application_id = application_id
    interaction.status = "pending"
    interaction.title = title
    interaction.agent_prompt = summary
    interaction.suggested_options = [
        {"action": "approve", "label": "批准并继续"},
        {"action": "reject", "label": "停止当前路径"},
    ]
    interaction.operator_response = {}
    interaction.effect_summary = None
    interaction.scope = "run_only"
    interaction.interaction_metadata = interaction_metadata
    interaction.resolved_at = None
    interaction.resolved_by = None
    return interaction


def _tool_args_digest(payload: dict[str, Any]) -> str | None:
    raw_input = payload.get("input")
    if raw_input is None:
        return None
    return json.dumps(raw_input, ensure_ascii=False, sort_keys=True, default=str)


def _pending_tool_name(payload: dict[str, Any]) -> str:
    return str(payload.get("tool_name") or payload.get("name") or "").strip()
