from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import re
from threading import RLock
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from recruit_station.agent_runtime.engine import InteractionEngine, transcript_from_checkpoint
from recruit_station.agent_runtime.types import InteractionOutput, LLMProvider
from recruit_station.db.base import utcnow
from recruit_station.evolution.learning_writer import LearningWriter
from recruit_station.memory.filesystem import MemoryFileStore
from recruit_station.memory.writeback import (
    MemoryWritebackPolicy,
    memory_writeback_policy_from_config,
    select_stable_memory_facts_with_llm,
    should_start_memory_writeback_job,
    write_stable_memory_facts_to_files,
)
from recruit_station.models.domain import (
    AgentRun,
    AgentRunCheckpoint,
    AgentRuntimeEvent,
    AgentSession,
    AgentTurnRecord,
    ApprovalItem,
    Candidate,
    CandidateApplication,
    McpServer,
    OperatorInteraction,
    AgentDefinition,
    Skill,
    TaskQueueItem,
)
from recruit_station.product_adapters.limits import TurnLimits
from recruit_station.agents.outcome import AgentTurnOutcome
from recruit_station.plugins.host import PluginHost
from recruit_station.product_adapters.context_builder import build_autonomous_turn_context
from recruit_station.product_adapters.agent_runner import AgentTurnStatusDefaults, run_agent_turn
from recruit_station.product_adapters.mcp_resource_context import build_mcp_resource_context, extract_mcp_resource_context_policy
from recruit_station.product_adapters.result_semantics import extract_execution_status
from recruit_station.product_adapters.target_contracts import derive_browser_target
from recruit_station.capabilities.tools import ToolRegistry
from recruit_station.skills.context import build_skill_context_injections

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
class ActiveAutonomousTurn:
    run_pk: str
    run_id: str | None
    turn_id: str
    engine: InteractionEngine | None = None
    interrupt_reason: str | None = None


class AutonomousRunInterrupted(RuntimeError):
    pass


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
    active_turns: dict[str, ActiveAutonomousTurn] = field(default_factory=dict)
    _active_turns_lock: RLock = field(default_factory=RLock)

    def cancel_run(self, run_id: str, *, reviewer: str, reason: str | None = None) -> str:
        with self.session_factory() as session:
            run = _resolve_autonomous_run_for_control(session, run_id)
            if run.status == "completed":
                raise ValueError("Completed run cannot be cancelled.")
            cancel_reason = reason or "cancelled"
            self._interrupt_active_turn(run=run, reason=cancel_reason)
            self.pending_permission_engines.pop(run.id, None)
            _cancel_open_run_for_control(
                session,
                run=run,
                reviewer=reviewer,
                reason=cancel_reason,
                interaction_action="cancel",
            )
            session.commit()
            return run.id

    def terminate_open_runs(self, *, reviewer: str, reason: str) -> list[str]:
        with self.session_factory() as session:
            stmt = (
                select(AgentRun)
                .where(
                    AgentRun.agent_kind == "autonomous",
                    AgentRun.status.in_(AUTONOMOUS_OPEN_RUN_STATUSES),
                )
                .order_by(AgentRun.updated_at.desc(), AgentRun.id.desc())
            )
            terminated: list[str] = []
            for run in session.scalars(stmt).all():
                self._interrupt_active_turn(run=run, reason=reason)
                self.pending_permission_engines.pop(run.id, None)
                _cancel_open_run_for_control(
                    session,
                    run=run,
                    reviewer=reviewer,
                    reason=reason,
                    interaction_action="terminate",
                )
                terminated.append(str(run.run_id or run.id))
            session.commit()
            return terminated

    def run_turn_from_envelope(self, envelope: dict[str, Any]) -> AgentTurnOutcome:
        with self.session_factory() as session:
            run = self._resolve_run(session, envelope)
            interrupted_status = _terminal_interrupt_status(run.status)
            if interrupted_status is not None:
                return AgentTurnOutcome(
                    status="cancelled",
                    gate_signal="paused",
                    metadata={"interrupted_before_start": True, "run_status": interrupted_status},
                )
            run.status = "running"
            if run.started_at is None:
                run.started_at = utcnow()
            next_seq = self._next_turn_seq(session, run.id)
            agent_session = session.get(AgentSession, run.session_id)
            agent_definition_id = None if agent_session is None else agent_session.agent_definition_id
            instruction_snapshot = _run_instruction_snapshot(run=run, envelope=envelope)
            resolved_application_id = _resolve_application_subject(run=run, envelope=envelope, snapshot=instruction_snapshot)
            resolved_person_id = _resolve_person_subject(
                session,
                run=run,
                envelope=envelope,
                snapshot=instruction_snapshot,
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
                turn_id=turn.turn_id,
                seq=next_seq,
                event_type="adapter_turn_started",
                message="adapter_turn_started",
                payload={"trigger_type": turn.trigger_type},
            )
            session.commit()

            run_constraints = dict(instruction_snapshot.get("constraints") or {})
            run_constraints["run_pk"] = run.id
            run_constraints["agent_definition_id"] = agent_definition_id
            run_constraints["run_kind"] = _snapshot_kind(instruction_snapshot, run)
            run_constraints["success_criteria"] = dict(instruction_snapshot.get("success_criteria") or {})
            run_constraints["context_hints"] = dict(instruction_snapshot.get("context_hints") or {})
            run_constraints["trial_budget"] = dict(instruction_snapshot.get("trial_budget") or {})
            run_constraints["global_scope_ref"] = (
                str(run_constraints.get("global_scope_ref") or "") or agent_definition_id
            )
            run_constraints["source_kind"] = "autonomous"
            if resolved_application_id:
                run_constraints["application_id"] = resolved_application_id
            browser_target = derive_browser_target(
                existing=run_constraints.get("browser_target") or run_constraints["context_hints"].get("browser_target"),
                structured_sources=(
                    run_constraints,
                    run_constraints["context_hints"],
                    run.context_manifest,
                    run.runtime_metadata,
                    envelope.get("world_snapshot"),
                    envelope.get("metadata"),
                ),
                text_sources=(
                    (run.context_manifest or {}).get("instruction"),
                    instruction_snapshot.get("instruction"),
                    instruction_snapshot.get("title"),
                ),
            )
            if browser_target:
                run_constraints["browser_target"] = browser_target
                run_constraints["context_hints"]["browser_target"] = browser_target

            scope_kind = str(envelope.get("scope_kind") or ("application" if resolved_application_id else run.lane or "global"))
            if scope_kind == "application":
                scope_ref = str(envelope.get("scope_ref") or resolved_application_id or run.id)
            else:
                scope_ref = str(envelope.get("scope_ref") or resolved_person_id or run.person_id or run.job_description_id or run.id)

            memory_scope_kind = str(run_constraints.get("memory_scope_kind") or scope_kind or "global").strip() or "global"
            memory_scope_ref = str(run_constraints.get("memory_scope_ref") or scope_ref or agent_definition_id or run.id)
            if memory_scope_kind == "global" and agent_definition_id:
                memory_scope_ref = str(run_constraints.get("memory_scope_ref") or run_constraints.get("global_scope_ref") or agent_definition_id)
            memory_entries = []
            if self.memory_file_store is not None:
                memory_entries = _read_memory_file_index_entries(
                    self.memory_file_store,
                    scope_kind=memory_scope_kind,
                    scope_ref=memory_scope_ref,
                    agent_definition_id=agent_definition_id,
                )
            agent_definition = session.get(AgentDefinition, agent_definition_id) if agent_definition_id else None
            memory_writeback_policy = _memory_writeback_policy(agent_definition)
            instruction = _snapshot_instruction(instruction_snapshot, run)
            run_title = str(instruction_snapshot.get("title") or run.run_type or "Autonomous execution").strip() or None
            active_turn_limits = _resolve_turn_limits(self.turn_limits, dict(instruction_snapshot.get("trial_budget") or {}))

            last_outcome = AgentTurnOutcome(status="continue", gate_signal="continue")
            runtime_event_seq = 0
            engine_output_count = 0
            try:
                world_snapshot = dict(envelope.get("world_snapshot") or {})
                mcp_resource_contexts = _mcp_resource_contexts(
                    self.mcp_registry,
                    run_constraints,
                    dict(run_constraints.get("context_hints") or {}),
                    world_snapshot,
                    dict(envelope.get("metadata") or {}) if isinstance(envelope.get("metadata"), dict) else {},
                    envelope,
                )
                adapter_context = build_autonomous_turn_context(
                    title=run_title,
                    instruction=instruction,
                    agent_name=str((agent_definition.name if agent_definition is not None else None) or "Autonomous"),
                    system_prompt=_definition_system_prompt(agent_definition),
                    agent_definition_id=agent_definition_id,
                    scope_kind=scope_kind,
                    scope_ref=scope_ref,
                    constraints=run_constraints,
                    world_snapshot=world_snapshot,
                    recent_events=_fetch_recent_events(session, run_id=run.id, limit=8),
                    memory_entries=memory_entries,
                    available_tools=sorted(self.tool_registry.tools.keys()),
                    skill_contexts=self._skill_contexts(
                        session,
                        query=instruction,
                        task_text=json.dumps(
                            {
                                "instruction": instruction,
                                "constraints": run_constraints,
                                "world_snapshot": world_snapshot,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                        category=_snapshot_kind(instruction_snapshot, run),
                        explicit_skill_ids=_explicit_skill_refs(run_constraints, envelope),
                        token_budget=_skill_context_token_budget(run_constraints, active_turn_limits),
                    ),
                    available_mcps=self._available_mcp_names(session),
                    mcp_resource_contexts=mcp_resource_contexts,
                )
                approved_tool_calls = _approved_tool_calls_from_envelope(envelope, run=run)
                runtime_conversation_id = run.session_id or run.id
                existing_engine = None
                resume_transcript = None
                if approved_tool_calls:
                    existing_engine = self.pending_permission_engines.pop(run.id, None)
                    if existing_engine is None:
                        runtime_checkpoint = _runtime_checkpoint_from_sources(session, run=run, envelope=envelope)
                        if runtime_checkpoint is None:
                            raise RuntimeError("Pending runtime permission state is not available for this run; durable checkpoint is missing")
                        resume_transcript = transcript_from_checkpoint(runtime_conversation_id, runtime_checkpoint)
                active_turn = ActiveAutonomousTurn(run_pk=run.id, run_id=run.run_id, turn_id=turn.turn_id)
                self._register_active_turn(active_turn)

                def _bind_engine(engine: InteractionEngine) -> None:
                    with self._active_turns_lock:
                        active_turn.engine = engine
                    if active_turn.interrupt_reason or self._run_has_terminal_interrupt(run.id):
                        engine.interrupt(active_turn.interrupt_reason)

                try:
                    runner_result = run_agent_turn(
                        provider=self.provider,
                        tool_registry=self.tool_registry,
                        agent_definition_id=agent_definition_id,
                        conversation_id=runtime_conversation_id,
                        initial_messages=adapter_context.initial_messages,
                        turn_input=adapter_context.turn_input,
                        max_llm_invocations=active_turn_limits.max_llm_invocations or 12,
                        initial_seq=runtime_event_seq + 1,
                        transcript=resume_transcript,
                        existing_engine=existing_engine,
                        resolve_permission=bool(approved_tool_calls),
                        output_sink=lambda output: _record_engine_output(session, run=run, turn_id=turn.turn_id, output=output),
                        engine_sink=_bind_engine,
                        structured_status_resolver=_outcome_from_structured_result_data,
                        status_defaults=AgentTurnStatusDefaults(
                            completed_status="complete",
                            completed_gate_signal="run_done",
                            failed_status="error",
                            failed_gate_signal="escalate",
                            interrupted_status="cancelled",
                            interrupted_gate_signal="paused",
                            permission_status="wait_human",
                            permission_gate_signal="wait_human",
                        ),
                    )
                finally:
                    self._clear_active_turn(active_turn)
                runtime_event_seq = max(runtime_event_seq, runner_result.last_seq)
                engine_output_count = runner_result.engine_output_count
                last_outcome = AgentTurnOutcome(
                    status=runner_result.status,  # type: ignore[arg-type]
                    gate_signal=runner_result.gate_signal,  # type: ignore[arg-type]
                    final_output=runner_result.final_output,
                    tool_calls=[],
                    tool_results=[],
                    metadata={
                        "tool_calls": runner_result.tool_calls,
                        "pending_tool_calls": runner_result.pending_tool_calls,
                        "tool_results": runner_result.tool_results,
                        "runtime_checkpoint": runner_result.engine.checkpoint_state(),
                        "interaction_engine": True,
                    },
                )
                if runner_result.status == "wait_human":
                    self.pending_permission_engines[run.id] = runner_result.engine
                else:
                    self.pending_permission_engines.pop(run.id, None)
            except Exception as exc:
                self.pending_permission_engines.pop(run.id, None)
                session.refresh(run)
                interrupted_status = _terminal_interrupt_status(run.status)
                turn.status = interrupted_status or "failed"
                turn.phase = "evaluate"
                turn.outcome_kind = interrupted_status or "error"
                turn.turn_metadata = {"error": str(exc), "engine_output_count": engine_output_count}
                run.turns_count = int(run.turns_count or 0) + 1
                if interrupted_status:
                    if run.finished_at is None:
                        run.finished_at = utcnow()
                else:
                    run.status = "failed"
                    run.finished_at = utcnow()
                    run.last_error = str(exc)
                _resolve_wait_human_records(session, run=run)
                _append_runtime_event(
                    session,
                    run=run,
                    turn_id=turn.turn_id,
                    seq=next_seq,
                    event_type="adapter_failed",
                    message=str(exc),
                    payload={"status": "error", "error": str(exc)},
                )
                session.commit()
                raise

            session.refresh(run)
            interrupted_status = _terminal_interrupt_status(run.status)
            outcome_run_status = _run_status_from_outcome(last_outcome)
            preserve_interrupted_status = interrupted_status is not None
            turn.status = interrupted_status if preserve_interrupted_status else _turn_status_from_outcome(last_outcome)
            turn.phase = "evaluate"
            turn.outcome_kind = interrupted_status if preserve_interrupted_status else last_outcome.status
            turn.turn_metadata = {
                "final_output": last_outcome.final_output,
                "gate_signal": last_outcome.gate_signal,
                "engine_output_count": engine_output_count,
                **({"interrupted_before_writeback": True, "run_status": interrupted_status} if preserve_interrupted_status else {}),
            }
            run.turns_count = int(run.turns_count or 0) + 1
            if not preserve_interrupted_status:
                run.status = outcome_run_status
            if run.status in {"completed", "waiting_human", "blocked", "failed", "cancelled", "interrupted"}:
                run.finished_at = utcnow()
            if not preserve_interrupted_status:
                run.last_error = None
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
            if _terminal_interrupt_status(run.status) is not None:
                raise AutonomousRunInterrupted(f"Autonomous run {run.run_id or run.id} was interrupted.")
            session.refresh(run)
            self._maybe_record_trial_skill(
                session,
                run=run,
                snapshot=instruction_snapshot,
                turn=turn,
                outcome=last_outcome,
                engine_output_count=engine_output_count,
                agent_definition_id=agent_definition_id,
            )
            if _is_completed_outcome(last_outcome):
                _maybe_write_turn_memory(
                    session,
                    provider=self.provider,
                    scope_kind=memory_scope_kind,
                    scope_ref=memory_scope_ref,
                    agent_definition_id=agent_definition_id,
                    run=run,
                    turn=turn,
                    instruction=instruction,
                    memory_entries=memory_entries,
                    policy=memory_writeback_policy,
                    force=_memory_writeback_force_requested(envelope, run_constraints),
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

    def _register_active_turn(self, active: ActiveAutonomousTurn) -> None:
        with self._active_turns_lock:
            self.active_turns[active.run_pk] = active
            if active.run_id:
                self.active_turns[active.run_id] = active

    def _clear_active_turn(self, active: ActiveAutonomousTurn) -> None:
        with self._active_turns_lock:
            for key in (active.run_pk, active.run_id):
                if key and self.active_turns.get(key) is active:
                    self.active_turns.pop(key, None)

    def _interrupt_active_turn(self, *, run: AgentRun, reason: str) -> bool:
        with self._active_turns_lock:
            active = self.active_turns.get(run.id) or self.active_turns.get(str(run.run_id or ""))
            if active is None:
                return False
            active.interrupt_reason = reason
            engine = active.engine
        if engine is not None:
            engine.interrupt(reason)
        return True

    def _run_has_terminal_interrupt(self, run_pk: str) -> bool:
        with self.session_factory() as session:
            run = session.get(AgentRun, run_pk)
            return run is not None and _terminal_interrupt_status(run.status) is not None

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
        snapshot: dict[str, Any],
        turn: AgentTurnRecord,
        outcome: AgentTurnOutcome,
        engine_output_count: int,
        agent_definition_id: str | None,
    ) -> None:
        if not _is_completed_outcome(outcome):
            return
        if self.learning_writer is None:
            return

        from recruit_station.services.evolution import build_skill_distill_review_payload, distill_skill_contract_from_run

        turn_events = self._turn_events(session, run_id=run.id, turn_id=turn.turn_id)
        tool_activity = _summarize_turn_tool_activity(turn_events)
        if not tool_activity:
            return

        review_payload = build_skill_distill_review_payload(
            run_id=str(run.run_id or run.id),
            run_type=run.run_type,
            run_kind=_snapshot_kind(snapshot, run) or None,
            engine_output_count=engine_output_count,
            final_output=outcome.final_output,
            tool_activity=tool_activity,
            event_outline=_summarize_turn_events(turn_events),
        )
        seq = max(int(engine_output_count or 0), 1) + 1
        _append_runtime_event(
            session,
            run=run,
            turn_id=turn.turn_id,
            seq=seq,
            event_type="skill_distill.started",
            message="distilling trial skill from successful run",
            payload={"run_id": run.run_id, "run_kind": _snapshot_kind(snapshot, run) or None},
        )
        session.commit()
        try:
            draft_contract = distill_skill_contract_from_run(
                provider=self.provider,
                review_payload=review_payload,
            )
            recorded = self.learning_writer.record_skill_draft(
                draft_contract=draft_contract,
                tags=_skill_distill_tags(run=run, snapshot=snapshot),
                trial_metrics={"runs": 1, "successes": 1},
                learning_content=_skill_learning_audit_log(review_payload, draft_contract),
                source_run_id=run.id,
                source_turn_id=turn.turn_id,
                source_kind="autonomous",
                agent_definition_id=agent_definition_id,
                proposed_by="autonomous",
                environment_scope=_skill_environment_scope(run=run, snapshot=snapshot),
            )
        except Exception as exc:
            session.rollback()
            _append_runtime_event(
                session,
                run=run,
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
    if outcome.status == "complete" or outcome.gate_signal == "run_done":
        return "idle"
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


def _terminal_interrupt_status(status: str | None) -> str | None:
    normalized = str(status or "").strip().lower()
    if normalized in {"cancelled", "interrupted"}:
        return normalized
    return None


def _turn_status_from_outcome(outcome: AgentTurnOutcome) -> str:
    if outcome.status == "complete" or outcome.gate_signal == "run_done":
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


def _is_completed_outcome(outcome: AgentTurnOutcome) -> bool:
    return outcome.status == "complete" or outcome.gate_signal == "run_done"


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
        return "complete", "run_done"
    return None


def _resolve_turn_limits(defaults: TurnLimits, trial_budget: dict[str, Any] | None) -> TurnLimits:
    overrides = dict(trial_budget or {})
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


def _read_memory_file_index_entries(
    memory_file_store: MemoryFileStore,
    *,
    scope_kind: str,
    scope_ref: str,
    agent_definition_id: str | None,
) -> list[dict[str, Any]]:
    try:
        entries: list[dict[str, Any]] = []
        for item in memory_file_store.list_files(scope_kind=scope_kind, scope_ref=scope_ref, agent_definition_id=agent_definition_id)[:12]:
            content = memory_file_store.read_file(
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                agent_definition_id=agent_definition_id,
                path=str(item["path"]),
            ).get("content", "")
            entries.append(
                {
                    "memory_item_id": item["path"],
                    "kind": "memory_file",
                    "summary": _first_non_empty_memory_line(str(content or "")) or item["path"],
                    "content": {"path": item["path"], "preview": _memory_preview(str(content or ""))},
                    "size": item.get("size"),
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


def _memory_preview(text: str, *, limit: int = 500) -> str:
    return str(text or "").strip()[:limit]


def _fetch_recent_events(session: Session, *, run_id: str | None = None, conversation_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    stmt = select(AgentRuntimeEvent)
    if run_id is not None:
        stmt = stmt.where(AgentRuntimeEvent.run_id == run_id)
    if conversation_id is not None:
        stmt = stmt.where(AgentRuntimeEvent.conversation_id == conversation_id)
    stmt = stmt.order_by(AgentRuntimeEvent.occurred_at.desc(), AgentRuntimeEvent.id.desc()).limit(limit)
    events = list(session.scalars(stmt).all())
    events.reverse()
    return [
        {
            "event_type": event.event_type,
            "source": event.source,
            "message": event.message,
            "turn_id": event.turn_id,
            "conversation_id": event.conversation_id,
            "payload": dict(event.payload or {}),
            "seq": event.seq,
        }
        for event in events
    ]


def _maybe_write_turn_memory(
    session: Session,
    *,
    provider: LLMProvider,
    scope_kind: str,
    scope_ref: str,
    agent_definition_id: str | None,
    run: AgentRun,
    turn: AgentTurnRecord,
    instruction: str,
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
        instruction=instruction,
    )
    if not should_start_memory_writeback_job(
        policy,
        completed_turns_since_last_job=completed_turns_since_last_job,
        evidence_text=evidence_text,
        force=force,
    ):
        return
    attempted = _write_turn_memory(
        provider=provider,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        agent_definition_id=agent_definition_id,
        run=run,
        turn=turn,
        instruction=instruction,
        evidence_text=evidence_text,
        memory_entries=memory_entries,
        policy=policy,
        memory_file_store=memory_file_store,
    )
    if attempted:
        _record_memory_writeback_job(run, turn=turn, evidence_text=evidence_text)


def _write_turn_memory(
    *,
    provider: LLMProvider,
    scope_kind: str,
    scope_ref: str,
    agent_definition_id: str | None,
    run: AgentRun,
    turn: AgentTurnRecord,
    instruction: str,
    evidence_text: str,
    memory_entries: list[dict[str, Any]],
    policy: MemoryWritebackPolicy,
    memory_file_store: MemoryFileStore | None = None,
) -> bool:
    if memory_file_store is None:
        return False
    try:
        facts = select_stable_memory_facts_with_llm(
            provider,
            instruction=instruction,
            final_output=evidence_text,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            memory_entries=memory_entries,
            max_stable_facts=policy.max_stable_facts,
        )
        write_stable_memory_facts_to_files(
            memory_file_store,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            agent_definition_id=agent_definition_id,
            facts=facts,
            run_id=str(run.run_id or run.id),
            run_pk=run.id,
            turn_id=turn.turn_id,
            source="memory_writeback_pipeline",
            policy=policy,
        )
        return True
    except Exception:
        return False


def _memory_writeback_policy(definition: AgentDefinition | None) -> MemoryWritebackPolicy:
    config = dict((definition.memory_policy if definition is not None else {}) or {}).get("writeback")
    return memory_writeback_policy_from_config(dict(config or {}))


def _definition_system_prompt(definition: AgentDefinition | None) -> str:
    if definition is None:
        return "你是 RecruitStation。你的核心职责是严格在招聘场景中维护候选人与投递记录事实，以投递记录为单位推进流程、记录证据，并把高风险动作交给人工确认。"
    prompt_config = dict(definition.prompt_config or {})
    return str(
        prompt_config.get("system_prompt")
        or prompt_config.get("systemPrompt")
        or prompt_config.get("prompt")
        or definition.description
        or ""
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
    instruction: str,
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
    parts: list[str] = [f"Instruction: {instruction}"]
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


def _memory_writeback_force_requested(envelope: dict[str, Any], run_constraints: dict[str, Any]) -> bool:
    for source in (envelope.get("memory_writeback"), run_constraints.get("memory_writeback")):
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


def _approved_tool_calls_from_envelope(envelope: dict[str, Any], *, run: AgentRun) -> list[dict[str, Any]]:
    candidates = envelope.get("approved_tool_calls")
    if not isinstance(candidates, list):
        candidates = (run.wakeup_state or {}).get("approved_tool_calls")
    if not isinstance(candidates, list):
        candidates = (run.wakeup_state or {}).get("pending_tool_calls")
    return [dict(item) for item in candidates or [] if isinstance(item, dict)]


def _runtime_checkpoint_from_sources(
    session: Session,
    *,
    run: AgentRun,
    envelope: dict[str, Any],
) -> dict[str, Any] | None:
    for source in (
        envelope.get("runtime_checkpoint"),
        envelope.get("engine_checkpoint"),
        (run.wakeup_state or {}).get("runtime_checkpoint"),
    ):
        if _is_pending_runtime_checkpoint(source):
            return dict(source)

    checkpoint = session.scalars(
        select(AgentRunCheckpoint)
        .where(AgentRunCheckpoint.run_id == run.id)
        .order_by(AgentRunCheckpoint.created_at.desc(), AgentRunCheckpoint.id.desc())
    ).first()
    if checkpoint is None:
        return None
    checkpoint_payload = dict(checkpoint.payload or {})
    resume_task = checkpoint_payload.get("resume_task")
    resume_payload = resume_task.get("payload") if isinstance(resume_task, dict) else None
    for source in (
        checkpoint_payload.get("runtime_checkpoint"),
        resume_payload.get("runtime_checkpoint") if isinstance(resume_payload, dict) else None,
    ):
        if _is_pending_runtime_checkpoint(source):
            return dict(source)
    return None


def _is_pending_runtime_checkpoint(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    pending = value.get("pending_permissions")
    return isinstance(pending, list) and any(isinstance(item, dict) for item in pending)


def _skill_distill_tags(*, run: AgentRun, snapshot: dict[str, Any]) -> list[str]:
    tags = ["autonomous", "skill_distill"]
    run_kind = _snapshot_kind(snapshot, run)
    if run_kind:
        tags.append(run_kind)
    environment_scope = _skill_environment_scope(run=run, snapshot=snapshot)
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
            elif key in {"instruction", "query", "message"}:
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


def _skill_context_token_budget(run_constraints: dict[str, Any], limits: TurnLimits) -> int | None:
    trial_budget = dict(run_constraints.get("trial_budget") or {})
    raw = trial_budget.get("skill_context_token_budget") or run_constraints.get("skill_context_token_budget")
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


def _skill_environment_scope(*, run: AgentRun, snapshot: dict[str, Any]) -> str:
    run_constraints = dict(snapshot.get("constraints") or {})
    context_hints = dict(run_constraints.get("context_hints") or snapshot.get("context_hints") or {})
    run_metadata = dict(run.runtime_metadata or {})
    candidates = [
        run_constraints.get("environment_scope"),
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
    turn_id: str,
    output: InteractionOutput,
) -> None:
    _append_runtime_event(
        session,
        run=run,
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


def _run_instruction_snapshot(*, run: AgentRun, envelope: dict[str, Any]) -> dict[str, Any]:
    context_manifest = dict(run.context_manifest or {})
    runtime_metadata = dict(run.runtime_metadata or {})
    metadata = dict(envelope.get("metadata") or {}) if isinstance(envelope.get("metadata"), dict) else {}
    world_snapshot = dict(envelope.get("world_snapshot") or {}) if isinstance(envelope.get("world_snapshot"), dict) else {}
    constraints = _merged_dict(
        runtime_metadata.get("constraints"),
        context_manifest.get("constraints"),
        metadata.get("constraints"),
        world_snapshot.get("constraints"),
        envelope.get("constraints"),
    )
    context_hints = _merged_dict(
        runtime_metadata.get("context_hints"),
        context_manifest.get("context_hints"),
        metadata.get("context_hints"),
        world_snapshot.get("context_hints"),
        envelope.get("context_hints"),
    )
    return {
        "instruction": _first_text(
            context_manifest.get("instruction"),
            runtime_metadata.get("instruction"),
            metadata.get("instruction"),
            world_snapshot.get("instruction"),
            envelope.get("instruction"),
        ),
        "title": _first_text(
            context_manifest.get("title"),
            runtime_metadata.get("title"),
            metadata.get("title"),
            world_snapshot.get("title"),
            envelope.get("title"),
        ),
        "kind": _first_text(
            context_manifest.get("kind"),
            runtime_metadata.get("kind"),
            metadata.get("kind"),
            world_snapshot.get("kind"),
            envelope.get("kind"),
            run.run_type,
        ),
        "requested_by": _first_text(
            context_manifest.get("requested_by"),
            runtime_metadata.get("requested_by"),
            metadata.get("requested_by"),
            world_snapshot.get("requested_by"),
            envelope.get("requested_by"),
        ),
        "constraints": constraints,
        "success_criteria": _merged_dict(
            runtime_metadata.get("success_criteria"),
            context_manifest.get("success_criteria"),
            metadata.get("success_criteria"),
            world_snapshot.get("success_criteria"),
            envelope.get("success_criteria"),
        ),
        "context_hints": context_hints,
        "trial_budget": _merged_dict(
            runtime_metadata.get("trial_budget"),
            context_manifest.get("trial_budget"),
            metadata.get("trial_budget"),
            world_snapshot.get("trial_budget"),
            envelope.get("trial_budget"),
        ),
        "run_preferences": _merged_dict(
            runtime_metadata.get("run_preferences"),
            context_manifest.get("run_preferences"),
            metadata.get("run_preferences"),
            world_snapshot.get("run_preferences"),
            envelope.get("run_preferences"),
        ),
    }


def _snapshot_instruction(snapshot: dict[str, Any], run: AgentRun) -> str:
    return _first_text(snapshot.get("instruction"), run.run_type, "Autonomous execution") or "Autonomous execution"


def _snapshot_kind(snapshot: dict[str, Any], run: AgentRun) -> str:
    return _first_text(snapshot.get("kind"), run.run_type) or ""


def _merged_dict(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update(dict(value))
    return merged


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _resolve_application_subject(
    *,
    run: AgentRun,
    envelope: dict[str, Any],
    snapshot: dict[str, Any] | None = None,
) -> str | None:
    metadata = dict(envelope.get("metadata") or {}) if isinstance(envelope.get("metadata"), dict) else {}
    world_snapshot = dict(envelope.get("world_snapshot") or {}) if isinstance(envelope.get("world_snapshot"), dict) else {}
    snapshot_constraints = dict((snapshot or {}).get("constraints") or {})
    snapshot_context_hints = dict((snapshot or {}).get("context_hints") or {})
    candidates: list[Any] = [
        envelope.get("application_id"),
        metadata.get("application_id"),
        world_snapshot.get("application_id"),
        snapshot_constraints.get("application_id"),
        snapshot_context_hints.get("application_id"),
        _resolve_run_application_id(run),
    ]
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
    snapshot: dict[str, Any] | None = None,
    application_id: str | None = None,
) -> str | None:
    metadata = dict(envelope.get("metadata") or {}) if isinstance(envelope.get("metadata"), dict) else {}
    world_snapshot = dict(envelope.get("world_snapshot") or {}) if isinstance(envelope.get("world_snapshot"), dict) else {}
    snapshot_constraints = dict((snapshot or {}).get("constraints") or {})
    snapshot_context_hints = dict((snapshot or {}).get("context_hints") or {})
    candidates: list[Any] = [
        envelope.get("person_id"),
        envelope.get("personId"),
        metadata.get("person_id"),
        metadata.get("personId"),
        world_snapshot.get("person_id"),
        world_snapshot.get("personId"),
        snapshot_constraints.get("person_id"),
        snapshot_constraints.get("personId"),
        snapshot_context_hints.get("person_id"),
        snapshot_context_hints.get("personId"),
        _resolve_run_person_id(run),
    ]
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


def _resolve_autonomous_run_for_control(session: Session, run_id: str) -> AgentRun:
    normalized = str(run_id or "").strip()
    if not normalized:
        raise KeyError("unknown run: ")
    stmt = select(AgentRun).where(
        AgentRun.agent_kind == "autonomous",
        (AgentRun.run_id == normalized) | (AgentRun.id == normalized),
    )
    run = session.scalars(stmt).first()
    if run is None:
        raise KeyError(f"unknown run: {normalized}")
    return run


def _cancel_open_run_for_control(
    session: Session,
    *,
    run: AgentRun,
    reviewer: str,
    reason: str,
    interaction_action: str,
) -> None:
    run.status = "cancelled"
    run.finished_at = utcnow()
    run.blocked_reason = reason or run.blocked_reason
    _cancel_open_queue_tasks_for_run(session, run=run, reviewer=reviewer, reason=reason)
    _resolve_run_gate_records_for_control(
        session,
        run=run,
        reviewer=reviewer,
        reason=reason,
        approval_status="rejected",
        interaction_action=interaction_action,
    )


def _cancel_open_queue_tasks_for_run(session: Session, *, run: AgentRun, reviewer: str, reason: str | None) -> None:
    stmt = select(TaskQueueItem).where(TaskQueueItem.status.in_(("pending", "running")))
    for task in session.scalars(stmt).all():
        payload = dict(task.payload or {})
        if str(payload.get("run_pk") or "") != run.id and str(payload.get("run_id") or "") != str(run.run_id or ""):
            continue
        task.status = "failed"
        task.locked_at = None
        task.locked_by = None
        audit = dict((payload.get("queue_audit") or {})) if isinstance(payload.get("queue_audit"), dict) else {}
        history = list(audit.get("history") or [])
        history.append(
            {
                "kind": "cancelled",
                "at": utcnow().isoformat(),
                "reviewer": reviewer,
                "reason": reason,
            }
        )
        audit["history"] = history[-20:]
        audit["last_event"] = "cancelled"
        audit["last_event_at"] = history[-1]["at"]
        payload["queue_audit"] = audit
        task.payload = payload


def _resolve_run_gate_records_for_control(
    session: Session,
    *,
    run: AgentRun,
    reviewer: str,
    reason: str,
    approval_status: str,
    interaction_action: str,
) -> AgentRunCheckpoint | None:
    checkpoint = session.scalars(
        select(AgentRunCheckpoint)
        .where(AgentRunCheckpoint.run_id == run.id, AgentRunCheckpoint.status == "open")
        .order_by(AgentRunCheckpoint.created_at.desc(), AgentRunCheckpoint.id.desc())
    ).first()
    if checkpoint is None:
        run.checkpoint_status = "none"
        run.wakeup_state = {}
        return None

    checkpoint.status = "resolved"
    checkpoint.resolved_at = utcnow()
    checkpoint.resolved_by = reviewer

    if checkpoint.approval_id:
        approval = session.get(ApprovalItem, checkpoint.approval_id)
        if approval is not None:
            approval.status = approval_status
            approval.reviewed_by = reviewer
            approval.reviewed_at = utcnow()
            approval.notes = reason
            approval_payload = dict(approval.payload or {})
            approval_payload["resolution"] = {
                "status": approval_status,
                "reviewer": reviewer,
                "reason": reason,
                "approved": approval_status == "approved",
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
        interaction.operator_response = {"action": interaction_action, "comment": reason}
        interaction.effect_summary = reason
        interaction.resolved_at = utcnow()
        interaction.resolved_by = reviewer

    run.checkpoint_status = "resolved"
    run.wakeup_state = {}
    return checkpoint


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
    runtime_checkpoint = dict(outcome.metadata.get("runtime_checkpoint") or {})
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
        runtime_checkpoint=runtime_checkpoint,
    )
    resume_task = {
        "task_id": run.queue_task_id or f"run-{run.id}",
        "task_type": "autonomous_turn",
        "priority": int(run.priority or 100),
        "payload": resume_envelope,
        "person_id": _resolve_run_person_id(run),
        "metadata": {
            "agent_kind": run.agent_kind,
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
        "runtime_checkpoint": runtime_checkpoint,
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
            "runtime_checkpoint": runtime_checkpoint,
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
        "runtime_checkpoint": runtime_checkpoint,
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
    runtime_checkpoint: dict[str, Any] | None = None,
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
    if runtime_checkpoint:
        payload["runtime_checkpoint"] = dict(runtime_checkpoint)
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
