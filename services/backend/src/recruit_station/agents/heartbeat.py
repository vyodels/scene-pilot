from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from recruit_station.agents.autonomous import AutonomousAdapter
from recruit_station.db.base import utcnow
from recruit_station.models.domain import AgentGlobalState
from recruit_station.repositories.domain import TaskQueueRepository

WORKSPACE_CONTROL_METADATA_KEY = "workspace_control"
WORKSPACE_CONTROL_STATES = {"stopped", "running", "paused", "terminating"}


def _control_metadata(state: AgentGlobalState | None) -> dict[str, Any]:
    metadata = dict(getattr(state, "state_metadata", None) or {})
    control = metadata.get(WORKSPACE_CONTROL_METADATA_KEY)
    return dict(control or {}) if isinstance(control, dict) else {}


def _control_state(state: AgentGlobalState | None) -> str:
    control = _control_metadata(state)
    value = str(control.get("state") or "").strip().lower()
    if value in WORKSPACE_CONTROL_STATES:
        return value
    if state is not None and state.autonomous_paused:
        return "paused"
    return "stopped"


def _write_control_state(
    state: AgentGlobalState,
    *,
    control_state: str,
    reason: str | None,
    updated_by: str | None,
) -> None:
    metadata = dict(state.state_metadata or {})
    metadata[WORKSPACE_CONTROL_METADATA_KEY] = {
        "state": control_state,
        "reason": reason,
        "updated_by": updated_by,
        "updated_at": utcnow().isoformat(),
    }
    state.state_metadata = metadata


def _ensure_global_state(session: Session) -> AgentGlobalState:
    state = session.get(AgentGlobalState, "singleton")
    if state is None:
        state = AgentGlobalState(id="singleton")
        session.add(state)
        session.flush()
    return state


@dataclass(slots=True)
class Heartbeat:
    session_factory: sessionmaker[Session]
    autonomous_adapter: AutonomousAdapter
    worker_id: str = "heartbeat"

    def run_once(self) -> dict[str, Any]:
        with self.session_factory() as session:
            state = session.get(AgentGlobalState, "singleton")
            control_state = _control_state(state)
            if control_state in {"stopped", "terminating"}:
                return {"status": control_state, "reason": _control_metadata(state).get("reason")}
            if control_state == "paused":
                return {"status": "paused", "reason": _control_metadata(state).get("reason") or (state.pause_reason if state is not None else None)}
            if state is not None and state.autonomous_paused:
                return {"status": "paused", "reason": state.pause_reason}

            queue = TaskQueueRepository(session)
            task = queue.claim_next(locked_by=self.worker_id)
            if task is None:
                return {"status": "idle"}

            try:
                self.autonomous_adapter.run_turn_from_envelope(dict(task.payload or {}))
            except Exception as exc:
                queue.mark_failed(task.id, error=str(exc))
                raise
            session.refresh(task)
            if task.status != "running":
                return {"status": task.status, "task_id": task.id}
            queue.mark_complete(task.id)
            return {"status": "processed", "task_id": task.id}

    def pause(self, *, reason: str | None = None, updated_by: str | None = None) -> AgentGlobalState:
        with self.session_factory() as session:
            state = _ensure_global_state(session)
            state.autonomous_paused = True
            state.pause_reason = reason
            state.pause_updated_by = updated_by
            _write_control_state(state, control_state="paused", reason=reason, updated_by=updated_by)
            session.commit()
            session.refresh(state)
            return state

    def resume(self, *, updated_by: str | None = None) -> AgentGlobalState:
        with self.session_factory() as session:
            state = _ensure_global_state(session)
            state.autonomous_paused = False
            state.pause_reason = None
            state.pause_updated_by = updated_by
            _write_control_state(state, control_state="running", reason=None, updated_by=updated_by)
            session.commit()
            session.refresh(state)
            return state

    def start(self, *, updated_by: str | None = None, reason: str | None = None) -> AgentGlobalState:
        with self.session_factory() as session:
            state = _ensure_global_state(session)
            state.autonomous_paused = False
            state.pause_reason = None
            state.pause_updated_by = updated_by
            _write_control_state(state, control_state="running", reason=reason, updated_by=updated_by)
            session.commit()
            session.refresh(state)
            return state

    def terminate(self, *, reason: str | None = None, updated_by: str | None = None) -> AgentGlobalState:
        with self.session_factory() as session:
            state = _ensure_global_state(session)
            state.autonomous_paused = True
            state.pause_reason = reason
            state.pause_updated_by = updated_by
            _write_control_state(state, control_state="stopped", reason=reason, updated_by=updated_by)
            session.commit()
            session.refresh(state)
            return state

    def status(self) -> dict[str, Any]:
        with self.session_factory() as session:
            state = session.get(AgentGlobalState, "singleton")
            if state is None:
                return {
                    "autonomous_paused": True,
                    "pause_reason": "workspace stopped",
                    "workspace_control": {"state": "stopped", "reason": "workspace stopped"},
                    "workspaceControl": {"state": "stopped", "reason": "workspace stopped"},
                }
            control = _control_metadata(state)
            control.setdefault("state", _control_state(state))
            return {
                "autonomous_paused": state.autonomous_paused,
                "pause_reason": state.pause_reason,
                "workspace_control": control,
                "workspaceControl": control,
            }
