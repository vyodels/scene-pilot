from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.db.base import utcnow
from scene_pilot.kernel.kernel import AgentKernel
from scene_pilot.memory.service import MemoryService
from scene_pilot.models.domain import (
    AgentRun,
    AgentRunCheckpoint,
    AgentRuntimeEvent,
    AgentSession,
    AgentTurnRecord,
    ApprovalItem,
    GoalSpec,
    McpServer,
    OperatorInteraction,
    Skill,
)
from scene_pilot.runtime.limits import TurnLimits
from scene_pilot.runtime.models import GoalRef, InputEnvelope, Message, Observation, RoundOutcome, ToolCall

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
class AutonomousAgent:
    session_factory: sessionmaker[Session]
    kernel: AgentKernel
    turn_limits: TurnLimits = field(default_factory=TurnLimits)

    def run_turn_from_envelope(self, envelope: dict[str, Any]) -> RoundOutcome:
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
                event_type="turn.started",
                message="turn started",
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

            goal = GoalRef(
                goal_id=run.run_id or run.id,
                scope_kind=str(envelope.get("scope_kind") or run.lane or "global"),
                scope_ref=str(envelope.get("scope_ref") or run.candidate_id or run.job_description_id or run.id),
                title=str(getattr(goal_spec, "title", None) or run.run_type or "Autonomous execution").strip() or None,
                goal_text=str(
                    (run.context_manifest or {}).get("goal")
                    or getattr(goal_spec, "goal_text", None)
                    or run.run_type
                    or "Autonomous execution"
                ),
                constraints=goal_constraints,
            )
            active_turn_limits = _resolve_turn_limits(self.turn_limits, goal_spec)

            round_history: list[Message] = []
            current_seed_tool_calls = [
                ToolCall.from_payload(payload)
                for payload in list(envelope.get("seed_tool_calls") or [])
                if isinstance(payload, dict)
            ]
            round_seq = 0
            started_at = time.monotonic()
            last_outcome = RoundOutcome(status="continue", gate_signal="continue")
            try:
                while True:
                    if round_seq >= active_turn_limits.max_rounds_per_turn:
                        last_outcome = RoundOutcome(
                            status="continue",
                            gate_signal="budget_exhausted",
                            final_output=last_outcome.final_output,
                        )
                        break
                    if time.monotonic() - started_at >= active_turn_limits.turn_timeout_seconds:
                        last_outcome = RoundOutcome(
                            status="continue",
                            gate_signal="budget_exhausted",
                            final_output=last_outcome.final_output,
                        )
                        break

                    round_seq += 1
                    _append_runtime_event(
                        session,
                        run=run,
                        goal=goal_spec,
                        turn_id=turn.turn_id,
                        seq=round_seq,
                        event_type="round.started",
                        message="round started",
                        payload={"round_seq": round_seq},
                    )
                    session.commit()

                    observation = Observation(
                        world_snapshot=dict(envelope.get("world_snapshot") or {}),
                        scope_kind=goal.scope_kind,
                        scope_ref=goal.scope_ref,
                        recent_events=memory_service.fetch_recent_events(run_id=run.id, limit=8),
                        available_tools=sorted(self.kernel.tool_registry.tools.keys()),
                        available_skills=self._available_skill_names(session),
                        available_mcps=self._available_mcp_names(session),
                        hash=str(envelope.get("observation_hash") or turn.turn_id),
                        input=InputEnvelope(
                            history_messages=list(round_history),
                            seed_tool_calls=list(current_seed_tool_calls),
                        ),
                    )
                    last_outcome = self.kernel.run_round(
                        goal=goal,
                        observation=observation,
                        limits=self.kernel.limits,
                        memory_service=memory_service,
                        learning_writer=self.kernel.learning_writer,
                        event_sink=lambda event_type, data: _record_kernel_event(
                            session,
                            run=run,
                            goal=goal_spec,
                            turn_id=turn.turn_id,
                            seq=round_seq,
                            event_type=event_type,
                            data=data,
                        ),
                    )
                    round_history = list(last_outcome.metadata.get("history_messages") or [])
                    current_seed_tool_calls = []
                    _append_runtime_event(
                        session,
                        run=run,
                        goal=goal_spec,
                        turn_id=turn.turn_id,
                        seq=round_seq,
                        event_type="round.completed",
                        message=last_outcome.final_output or last_outcome.status,
                        payload={
                            "round_seq": round_seq,
                            "status": last_outcome.status,
                            "gate_signal": last_outcome.gate_signal,
                            "tool_calls": [call.to_provider_payload() for call in last_outcome.tool_calls],
                            "tool_results": [
                                {
                                    "tool_name": result.tool_name,
                                    "is_error": result.is_error,
                                    "output": result.output,
                                }
                                for result in last_outcome.tool_results
                            ],
                        },
                    )
                    session.commit()
                    if last_outcome.status == "cancelled" or last_outcome.gate_signal not in {None, "continue"}:
                        break
            except Exception as exc:
                turn.status = "failed"
                turn.phase = "evaluate"
                turn.outcome_kind = "error"
                turn.turn_metadata = {"error": str(exc), "round_count": round_seq}
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
                    event_type="turn.failed",
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
                "round_count": round_seq,
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

            _append_runtime_event(
                session,
                run=run,
                goal=goal_spec,
                turn_id=turn.turn_id,
                seq=next_seq,
                event_type=_terminal_event_type(last_outcome),
                message=last_outcome.final_output or last_outcome.status,
                payload={"status": last_outcome.status, "gate_signal": last_outcome.gate_signal},
            )
            session.commit()
            session.refresh(run)
            self._maybe_record_trial_skill(
                session,
                run=run,
                goal=goal_spec,
                turn=turn,
                outcome=last_outcome,
                round_count=round_seq,
                agent_profile_id=agent_profile_id,
            )
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

    def _available_skill_names(self, session: Session) -> list[str]:
        stmt = select(Skill.name).where(Skill.status.in_(("trial", "active"))).order_by(Skill.name.asc())
        return [str(name) for name in session.scalars(stmt).all()]

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
        outcome: RoundOutcome,
        round_count: int,
        agent_profile_id: str | None,
    ) -> None:
        if run.status != "completed":
            return
        if self.kernel.learning_writer is None:
            return

        from scene_pilot.services.evolution import build_skill_distill_review_payload, distill_skill_contract_from_run

        turn_events = self._turn_events(session, run_id=run.id, turn_id=turn.turn_id)
        tool_activity = _summarize_turn_tool_activity(turn_events)
        if not tool_activity:
            return

        review_payload = build_skill_distill_review_payload(
            run_id=str(run.run_id or run.id),
            run_type=run.run_type,
            goal_kind=None if goal is None else goal.goal_kind,
            round_count=round_count,
            final_output=outcome.final_output,
            tool_activity=tool_activity,
            event_outline=_summarize_turn_events(turn_events),
        )
        seq = max(int(round_count or 0), 1) + 1
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
            draft_contract, response = distill_skill_contract_from_run(
                provider=self.kernel.provider,
                review_payload=review_payload,
            )
            recorded = self.kernel.learning_writer.record_skill_draft(
                draft_contract=draft_contract,
                tags=_skill_distill_tags(run=run, goal=goal),
                trial_metrics={"runs": 1, "successes": 1},
                learning_content=_skill_learning_audit_log(review_payload, draft_contract),
                source_run_id=run.id,
                source_turn_id=turn.turn_id,
                source_kind="autonomous",
                agent_profile_id=agent_profile_id,
                proposed_by="autonomous",
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
                "usage_total_tokens": response.usage.total_tokens,
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


def _run_status_from_outcome(outcome: RoundOutcome) -> str:
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


def _turn_status_from_outcome(outcome: RoundOutcome) -> str:
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


def _terminal_event_type(outcome: RoundOutcome) -> str:
    if outcome.status == "wait_human" or outcome.gate_signal == "wait_human":
        return "turn.waiting_human"
    if outcome.status == "cancelled" or outcome.gate_signal == "paused":
        return "turn.cancelled"
    if outcome.status == "error":
        return "turn.failed"
    if outcome.status == "escalate" or outcome.gate_signal == "escalate":
        return "turn.failed"
    return "turn.completed"


def _is_waiting_human(outcome: RoundOutcome) -> bool:
    return outcome.status == "wait_human" or outcome.gate_signal == "wait_human"


def _resolve_turn_limits(defaults: TurnLimits, goal_spec: GoalSpec | None) -> TurnLimits:
    if goal_spec is None:
        return defaults

    overrides = dict(getattr(goal_spec, "trial_budget", {}) or {})
    if not overrides:
        return defaults

    resolved: dict[str, int] = {}
    for field_name in (
        "max_rounds_per_turn",
        "turn_timeout_seconds",
        "token_budget",
        "cooldown_seconds",
    ):
        raw_value = overrides.get(field_name)
        if raw_value is None:
            continue
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            continue
        if parsed <= 0:
            continue
        resolved[field_name] = parsed

    if not resolved:
        return defaults
    return replace(defaults, **resolved)


def _skill_distill_tags(*, run: AgentRun, goal: GoalSpec | None) -> list[str]:
    tags = ["autonomous", "skill_distill"]
    goal_kind = str((goal.goal_kind if goal is not None else run.run_type) or "").strip()
    if goal_kind:
        tags.append(goal_kind)
    return tags


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
        if event.event_type not in {"tool.call", "tool.result", "tool.blocked"}:
            continue
        payload = dict(event.payload or {})
        tool_name = str(payload.get("tool_name") or event.message or "").strip()
        if not tool_name:
            continue
        item = {
            "event_type": event.event_type,
            "tool_name": tool_name,
        }
        if event.event_type == "tool.call":
            item["arguments"] = dict(payload.get("arguments") or {})
        elif event.event_type == "tool.result":
            item["is_error"] = bool(payload.get("is_error"))
            item["output_excerpt"] = _compact_event_payload(payload.get("output"))
        else:
            item["reason"] = str(payload.get("reason") or event.message or "").strip() or None
        activity.append(item)
    return activity[:12]


def _summarize_turn_events(events: list[AgentRuntimeEvent]) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    for event in events:
        if event.event_type in {"provider.started", "provider.completed", "round.started", "round.completed"}:
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


def _record_kernel_event(
    session: Session,
    *,
    run: AgentRun,
    goal: GoalSpec | None,
    turn_id: str,
    seq: int,
    event_type: str,
    data: dict[str, Any],
) -> None:
    mapped = _map_kernel_event(event_type, data)
    if mapped is None:
        return
    normalized_event_type, message, payload = mapped
    _append_runtime_event(
        session,
        run=run,
        goal=goal,
        turn_id=turn_id,
        seq=seq,
        event_type=normalized_event_type,
        message=message,
        payload=payload,
    )
    session.commit()


def _map_kernel_event(event_type: str, data: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    normalized = event_type.strip().lower()
    if normalized == "provider_started":
        return (
            "provider.started",
            "calling model",
            {
                "message_count": int(data.get("message_count") or 0),
                "tool_count": int(data.get("tool_count") or 0),
            },
        )
    if normalized == "provider_completed":
        return (
            "provider.completed",
            "model completed",
            {
                "finish_reason": data.get("finish_reason"),
                "tool_call_count": int(data.get("tool_call_count") or 0),
                "has_content": bool(data.get("has_content")),
            },
        )
    if normalized == "provider_failed":
        return ("provider.failed", str(data.get("error") or "provider failed"), {"error": data.get("error")})
    if normalized == "tool_call":
        tool_name = str(data.get("name") or "unknown")
        return (
            "tool.call",
            f"calling tool {tool_name}",
            {
                "tool_name": tool_name,
                "arguments": dict(data.get("arguments") or {}),
                "tool_call_id": data.get("id"),
            },
        )
    if normalized == "tool_result":
        tool_name = str(data.get("tool_name") or "unknown")
        return (
            "tool.result",
            f"tool {tool_name} returned",
            {
                "tool_name": tool_name,
                "is_error": bool(data.get("is_error")),
                "output": data.get("output"),
            },
        )
    if normalized == "tool_blocked":
        tool_name = str(data.get("tool_name") or "unknown")
        return (
            "tool.blocked",
            f"tool {tool_name} blocked",
            {
                "tool_name": tool_name,
                "reason": data.get("reason"),
                "severity": data.get("severity"),
            },
        )
    return None


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
    session.add(
        AgentRuntimeEvent(
            session_id=run.session_id,
            run_id=run.id,
            candidate_id=run.candidate_id,
            source="autonomous",
            event_type=event_type,
            message=message,
            turn_id=turn_id,
            seq=seq,
            payload=payload,
        )
    )
    if goal is not None:
        goal.last_activity_at = utcnow()


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
    outcome: RoundOutcome,
) -> None:
    pending_tool_calls = [
        payload
        for payload in list(outcome.metadata.get("pending_tool_calls") or [])
        if isinstance(payload, dict)
    ]
    tool_names = [
        str((payload.get("function") or {}).get("name") or payload.get("name") or "").strip()
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
    resume_envelope = _build_resume_envelope(run=run, envelope=envelope, pending_tool_calls=pending_tool_calls)
    resume_task = {
        "task_id": run.queue_task_id or f"run-{run.id}",
        "task_type": "autonomous_turn",
        "priority": int(run.priority or 100),
        "payload": resume_envelope,
        "candidate_id": run.candidate_id,
        "metadata": {
            "agent_kind": run.agent_kind,
            "goal_spec_id": run.goal_spec_id,
            "checkpoint_kind": "wait_human",
        },
    }
    approval_payload = {
        "run_pk": run.id,
        "run_id": run.run_id,
        "turn_id": turn.turn_id,
        "pending_tool_calls": pending_tool_calls,
        "resume_task": resume_task,
        "checkpoint_kind": "wait_human",
    }
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
    )
    run.checkpoint_status = "open"
    run.wakeup_state = {
        "checkpoint_id": checkpoint.id,
        "approval_id": approval.id,
        "pending_tool_calls": pending_tool_calls,
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
) -> dict[str, Any]:
    scope_kind = str(envelope.get("scope_kind") or run.lane or "global")
    scope_ref = str(envelope.get("scope_ref") or run.candidate_id or run.job_description_id or run.id)
    payload: dict[str, Any] = {
        "run_pk": run.id,
        "run_id": run.run_id,
        "scope_kind": scope_kind,
        "scope_ref": scope_ref,
        "trigger_type": "resume",
    }
    if isinstance(envelope.get("world_snapshot"), dict):
        payload["world_snapshot"] = dict(envelope.get("world_snapshot") or {})
    if pending_tool_calls:
        payload["seed_tool_calls"] = pending_tool_calls
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
            candidate_id=run.candidate_id,
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
    checkpoint.candidate_id = run.candidate_id
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
) -> OperatorInteraction:
    interaction = session.scalars(
        select(OperatorInteraction)
        .where(OperatorInteraction.checkpoint_id == checkpoint.id, OperatorInteraction.status == "pending")
        .order_by(OperatorInteraction.created_at.desc(), OperatorInteraction.id.desc())
    ).first()
    interaction_metadata = {
        "pending_tool_calls": pending_tool_calls,
        "tool_names": [
            str((payload.get("function") or {}).get("name") or payload.get("name") or "").strip()
            for payload in pending_tool_calls
        ],
    }
    if interaction is None:
        interaction = OperatorInteraction(
            session_id=run.session_id,
            run_id=run.id,
            checkpoint_id=checkpoint.id,
            approval_id=approval.id,
            goal_spec_id=run.goal_spec_id,
            candidate_id=run.candidate_id,
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
    interaction.candidate_id = run.candidate_id
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
    function_payload = payload.get("function")
    if not isinstance(function_payload, dict):
        return None
    raw_arguments = function_payload.get("arguments")
    if isinstance(raw_arguments, str):
        try:
            raw_arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            return raw_arguments or None
    if raw_arguments is None:
        return None
    return json.dumps(raw_arguments, ensure_ascii=False, sort_keys=True, default=str)
