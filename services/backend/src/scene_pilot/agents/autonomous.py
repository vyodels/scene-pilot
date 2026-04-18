from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.db.base import utcnow
from scene_pilot.kernel.kernel import AgentKernel
from scene_pilot.models.domain import AgentRun, AgentRuntimeEvent, AgentTickRecord, AgentTurnRecord
from scene_pilot.runtime.models import GoalRef, Observation, TickOutcome


@dataclass(slots=True)
class AutonomousAgent:
    session_factory: sessionmaker[Session]
    kernel: AgentKernel

    def run_tick_from_envelope(self, envelope: dict[str, Any]) -> TickOutcome:
        with self.session_factory() as session:
            run = self._resolve_run(session, envelope)
            run.status = "running"
            if run.started_at is None:
                run.started_at = utcnow()
            next_seq = self._next_tick_seq(session, run.id)
            tick = AgentTickRecord(
                run_pk=run.id,
                seq=next_seq,
                trigger_type=str(envelope.get("trigger_type") or "manual"),
                status="started",
                phase="sense",
            )
            session.add(tick)
            session.flush()

            goal = GoalRef(
                goal_id=run.run_id or run.id,
                scope_kind=str(envelope.get("scope_kind") or run.lane or "global"),
                scope_ref=str(envelope.get("scope_ref") or run.candidate_id or run.job_description_id or run.id),
                goal_text=str(run.context_manifest.get("goal") or run.run_type or "Autonomous execution"),
            )
            observation = Observation(
                world_snapshot=dict(envelope.get("world_snapshot") or {}),
                scope_kind=goal.scope_kind,
                scope_ref=goal.scope_ref,
                recent_events=[],
                available_tools=sorted(self.kernel.tool_registry.tools.keys()),
                available_skills=[],
                available_mcps=[],
                hash=str(envelope.get("observation_hash") or tick.tick_id),
            )
            outcome = self.kernel.run_tick(goal, observation)

            turn = AgentTurnRecord(
                tick_pk=tick.id,
                seq=1,
                role="assistant",
                stop_reason=str(outcome.metadata.get("stop_reason") or "stop"),
                turn_metadata={"final_output": outcome.final_output},
            )
            session.add(turn)

            tick.status = "completed"
            tick.phase = "evaluate"
            tick.outcome_kind = outcome.status
            run.ticks_count = int(run.ticks_count or 0) + 1
            run.turns_count = int(run.turns_count or 0) + 1
            run.status = _map_outcome_status(outcome.status)

            session.add(
                AgentRuntimeEvent(
                    session_id=run.session_id,
                    run_id=run.id,
                    candidate_id=run.candidate_id,
                    source="autonomous",
                    event_type="tick_completed",
                    message=outcome.final_output or outcome.status,
                    tick_id=tick.tick_id,
                    turn_id=turn.turn_id,
                    seq=next_seq,
                    payload={"status": outcome.status},
                )
            )
            session.commit()
            session.refresh(run)
            return outcome

    def recover_stale(self) -> int:
        with self.session_factory() as session:
            stmt = select(AgentRun).where(AgentRun.status == "running")
            recovered = 0
            for run in session.scalars(stmt).all():
                run.status = "interrupted"
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

    def _next_tick_seq(self, session: Session, run_pk: str) -> int:
        stmt = select(func.max(AgentTickRecord.seq)).where(AgentTickRecord.run_pk == run_pk)
        return int(session.scalar(stmt) or 0) + 1


def _map_outcome_status(status: str) -> str:
    if status == "complete":
        return "completed"
    if status == "wait_human":
        return "waiting_human"
    if status == "escalate":
        return "blocked"
    return "running"
