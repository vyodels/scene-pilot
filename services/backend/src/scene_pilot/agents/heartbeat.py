from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.agents.autonomous import AutonomousAgent
from scene_pilot.models.domain import AgentGlobalState
from scene_pilot.repositories.domain import TaskQueueRepository


@dataclass(slots=True)
class Heartbeat:
    session_factory: sessionmaker[Session]
    autonomous_agent: AutonomousAgent
    worker_id: str = "heartbeat"

    def run_once(self) -> dict[str, Any]:
        with self.session_factory() as session:
            state = session.get(AgentGlobalState, "singleton")
            if state is not None and state.autonomous_paused:
                return {"status": "paused", "reason": state.pause_reason}

            queue = TaskQueueRepository(session)
            task = queue.claim_next(locked_by=self.worker_id)
            if task is None:
                return {"status": "idle"}

            try:
                self.autonomous_agent.run_tick_from_envelope(dict(task.payload or {}))
            except Exception as exc:
                queue.mark_failed(task.id, error=str(exc))
                raise
            queue.mark_complete(task.id)
            return {"status": "processed", "task_id": task.id}

    def pause(self, *, reason: str | None = None, updated_by: str | None = None) -> AgentGlobalState:
        with self.session_factory() as session:
            state = session.get(AgentGlobalState, "singleton")
            if state is None:
                state = AgentGlobalState(id="singleton")
                session.add(state)
                session.flush()
            state.autonomous_paused = True
            state.pause_reason = reason
            state.pause_updated_by = updated_by
            session.commit()
            session.refresh(state)
            return state

    def resume(self, *, updated_by: str | None = None) -> AgentGlobalState:
        with self.session_factory() as session:
            state = session.get(AgentGlobalState, "singleton")
            if state is None:
                state = AgentGlobalState(id="singleton")
                session.add(state)
                session.flush()
            state.autonomous_paused = False
            state.pause_reason = None
            state.pause_updated_by = updated_by
            session.commit()
            session.refresh(state)
            return state

    def status(self) -> dict[str, Any]:
        with self.session_factory() as session:
            state = session.get(AgentGlobalState, "singleton")
            if state is None:
                return {"autonomous_paused": False, "pause_reason": None}
            return {"autonomous_paused": state.autonomous_paused, "pause_reason": state.pause_reason}
