from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from recruit_station.agents.autonomous import AutonomousAdapter
from recruit_station.core.settings import ProviderRuntimeSettings
from recruit_station.db.base import utcnow
from recruit_station.models.domain import AgentGlobalState
from recruit_station.models.domain import AgentRun
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
            queue = TaskQueueRepository(session)
            control_state = _control_state(state)
            if control_state == "terminating":
                return {"status": control_state, "reason": _control_metadata(state).get("reason")}
            if control_state == "paused" or (state is not None and state.autonomous_paused):
                return {"status": "paused", "reason": _control_metadata(state).get("reason") or (state.pause_reason if state is not None else None)}
            task = None
            if control_state == "stopped":
                task = queue.claim_next_for_agent_kind("jd_sync", locked_by=self.worker_id)
                if task is None:
                    return {"status": control_state, "reason": _control_metadata(state).get("reason")}
            if task is None:
                task = queue.claim_next(locked_by=self.worker_id)
            if task is None:
                return {"status": "idle"}

            payload = dict(task.payload or {})
            budget_defer = self._behavior_budget_defer(session, payload)
            if budget_defer is not None:
                task.scheduled_for = budget_defer["deferred_until"]
                self._record_behavior_budget_defer(session, payload, defer=budget_defer)
                queue.mark_pending(task.id, attempts=int(task.attempts or 0), error="behavior_budget_defer")
                return {
                    "status": "deferred",
                    "task_id": task.id,
                    "reason": "behavior_budget_defer",
                    "deferred_until": budget_defer["deferred_until"].isoformat(),
                    "behavior_budget_defer": {
                        **budget_defer,
                        "deferred_until": budget_defer["deferred_until"].isoformat(),
                    },
                }

            preflight = self._preflight_task(payload)
            if preflight is not None:
                payload = _payload_with_mcp_readiness(payload, preflight=preflight)
                task.payload = payload
                self._record_run_mcp_readiness(session, payload, preflight=preflight)
                session.commit()

            try:
                self.autonomous_adapter.run_turn_from_envelope(payload)
            except Exception as exc:
                queue.mark_failed(task.id, error=str(exc))
                raise
            session.refresh(task)
            if task.status != "running":
                return {"status": task.status, "task_id": task.id}
            queue.mark_complete(task.id)
            return {"status": "processed", "task_id": task.id}

    def _behavior_budget_defer(self, session: Session, payload: dict[str, Any]) -> dict[str, Any] | None:
        budget = _adapter_behavior_budget(self.autonomous_adapter)
        checks = (
            ("hourly", _positive_int(budget.get("max_candidates_per_hour")), timedelta(hours=1)),
            ("daily", _positive_int(budget.get("max_candidates_per_day")), timedelta(days=1)),
        )
        if not any(limit for _, limit, _ in checks):
            return None
        run = _resolve_run_for_payload(session, payload)
        subject = _candidate_budget_ref(payload, run)
        if subject is None:
            return None

        now = utcnow()
        selected: dict[str, Any] | None = None
        for window_name, limit, window in checks:
            if limit is None:
                continue
            usage = _candidate_budget_usage(session, since=now - window, exclude_run_pk=run.id if run else None)
            if subject.key in usage:
                continue
            if len(usage) < limit:
                continue
            deferred_until = min(usage.values()) + window
            marker = {
                "reason": "candidate_budget_exceeded",
                "window": window_name,
                "limit": limit,
                "used": len(usage),
                "candidate_ref": subject.ref,
                "candidate_ref_kind": subject.kind,
                "deferred_until": deferred_until,
            }
            if selected is None or deferred_until > selected["deferred_until"]:
                selected = marker
        return selected

    def _record_behavior_budget_defer(self, session: Session, payload: dict[str, Any], *, defer: dict[str, Any]) -> None:
        run = _resolve_run_for_payload(session, payload)
        if run is None:
            session.commit()
            return
        metadata = dict(run.runtime_metadata or {})
        metadata["behavior_budget_defer"] = {
            **defer,
            "deferred_until": defer["deferred_until"].isoformat(),
        }
        run.runtime_metadata = metadata
        session.commit()

    def _preflight_task(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not _payload_requires_browser_hid_preflight(payload):
            return None
        registry = getattr(self.autonomous_adapter, "mcp_registry", None)
        if registry is None or not hasattr(registry, "browser_hid_preflight"):
            return {
                "ok": False,
                "status": "blocked",
                "missing": ["browser-mcp", "VirtualHID"],
                "checks": [],
                "reason": "mcp_registry_unavailable",
            }
        return registry.browser_hid_preflight()

    def _record_run_mcp_readiness(self, session: Session, payload: dict[str, Any], *, preflight: dict[str, Any]) -> None:
        run = _resolve_run_for_payload(session, payload)
        if run is None:
            return
        metadata = dict(run.runtime_metadata or {})
        metadata["mcp_readiness"] = preflight
        run.runtime_metadata = metadata

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


@dataclass(frozen=True, slots=True)
class _BudgetSubject:
    kind: str
    ref: str

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.ref}"


def _payload_requires_browser_hid_preflight(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("require_browser_hid_preflight") is True or value.get("real_browser_hid") is True:
            return True
        if any(key in value for key in ("browser_target", "computer_target", "target_regions", "action_plan")):
            return True
        capabilities = value.get("preferred_capabilities")
        if isinstance(capabilities, list):
            normalized = {str(item).strip().lower().replace("-", "_") for item in capabilities}
            if normalized & {"browser", "browser_mcp", "computer", "virtual_hid", "virtualhid", "computer_write", "hid"}:
                return True
        return any(_payload_requires_browser_hid_preflight(item) for item in value.values())
    if isinstance(value, list):
        return any(_payload_requires_browser_hid_preflight(item) for item in value)
    return False


def _payload_with_mcp_readiness(payload: dict[str, Any], *, preflight: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload or {})
    metadata = dict(updated.get("metadata") or {}) if isinstance(updated.get("metadata"), dict) else {}
    metadata["mcp_readiness"] = dict(preflight or {})
    updated["metadata"] = metadata
    constraints = dict(updated.get("constraints") or {}) if isinstance(updated.get("constraints"), dict) else {}
    constraints["mcp_readiness"] = dict(preflight or {})
    updated["constraints"] = constraints
    return updated


def _resolve_run_for_payload(session: Session, payload: dict[str, Any]) -> AgentRun | None:
    run_pk = str(payload.get("run_pk") or "").strip()
    if run_pk:
        return session.get(AgentRun, run_pk)
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        return None
    return session.query(AgentRun).filter(AgentRun.run_id == run_id).first()


def _adapter_behavior_budget(adapter: AutonomousAdapter) -> dict[str, Any]:
    budget = getattr(adapter, "behavior_budget", None)
    if isinstance(budget, dict):
        return dict(budget)
    return dict(ProviderRuntimeSettings().behavior_budget)


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _candidate_budget_usage(session: Session, *, since, exclude_run_pk: str | None) -> dict[str, Any]:
    stmt = select(AgentRun).where(
        or_(
            AgentRun.started_at >= since,
            AgentRun.finished_at >= since,
        )
    )
    if exclude_run_pk:
        stmt = stmt.where(AgentRun.id != exclude_run_pk)
    usage: dict[str, Any] = {}
    for run in session.scalars(stmt).all():
        subject = _candidate_budget_ref({}, run)
        if subject is None:
            continue
        seen_at = _datetime_from_timestamp(run.started_at or run.finished_at or run.created_at)
        existing = usage.get(subject.key)
        if existing is None or seen_at < existing:
            usage[subject.key] = seen_at
    return usage


def _candidate_budget_ref(payload: dict[str, Any], run: AgentRun | None) -> _BudgetSubject | None:
    run_metadata = dict(run.runtime_metadata or {}) if run is not None else {}
    person_ref = (
        _text_or_none(run.person_id if run is not None else None)
        or _first_ref(payload, _PERSON_REF_KEYS)
        or _first_ref(run_metadata, _PERSON_REF_KEYS)
    )
    if person_ref:
        return _BudgetSubject(kind="person", ref=person_ref)
    application_ref = (
        _text_or_none(run.application_id if run is not None else None)
        or _first_ref(payload, _APPLICATION_REF_KEYS)
        or _first_ref(run_metadata, _APPLICATION_REF_KEYS)
    )
    if application_ref:
        return _BudgetSubject(kind="application", ref=application_ref)
    return None


_PERSON_REF_KEYS = (
    "person_id",
    "personId",
    "candidate_person_id",
    "candidatePersonId",
    "candidate_ref",
    "candidateRef",
    "candidate_id",
    "candidateId",
)
_APPLICATION_REF_KEYS = (
    "application_id",
    "applicationId",
    "candidate_application_id",
    "candidateApplicationId",
    "application_ref",
    "applicationRef",
)


def _first_ref(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        scope_kind = str(value.get("scope_kind") or value.get("scopeKind") or "").strip().lower()
        if keys is _PERSON_REF_KEYS and scope_kind in {"candidate", "person"}:
            scoped = _text_or_none(value.get("scope_ref") or value.get("scopeRef"))
            if scoped:
                return scoped
        if keys is _APPLICATION_REF_KEYS and scope_kind == "application":
            scoped = _text_or_none(value.get("scope_ref") or value.get("scopeRef"))
            if scoped:
                return scoped
        for key in keys:
            found = _text_or_none(value.get(key))
            if found:
                return found
        for item in value.values():
            found = _first_ref(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first_ref(item, keys)
            if found:
                return found
    return None


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _datetime_from_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(int(value), tz=timezone.utc)
