from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from scene_pilot.models.domain import AgentRun, AgentTickRecord, AgentTurnRecord, JobAssembly, RecruitAgentProfile
from scene_pilot.repositories.domain import TaskQueueRepository
from scene_pilot.services.container import AppContainer


class AgentTaskCreate(BaseModel):
    task_type: str
    priority: int = 100
    payload: dict[str, Any] = Field(default_factory=dict)


def build_router(container: AppContainer) -> APIRouter:
    router = APIRouter(prefix="/api/agent", tags=["agent"])

    @router.get("")
    def get_agent_status() -> dict[str, Any]:
        return {
            "autonomous_paused": container.heartbeat.status()["autonomous_paused"],
            "queue_depth": _queue_depth(container),
        }

    @router.post("/tasks")
    def enqueue_task(payload: AgentTaskCreate) -> dict[str, Any]:
        with container.session_factory() as session:
            task = TaskQueueRepository(session).enqueue(
                task_id=payload.payload.get("task_id") or payload.task_type,
                task_type=payload.task_type,
                priority=payload.priority,
                payload=payload.payload,
            )
            return {"task_id": task.id, "task_type": task.task_type, "priority": task.priority}

    @router.post("/run-once")
    def run_once() -> dict[str, Any]:
        return container.heartbeat.run_once()

    @router.get("/queue")
    def list_queue() -> list[dict[str, Any]]:
        with container.session_factory() as session:
            return [
                {
                    "task_id": item.id,
                    "task_type": item.task_type,
                    "status": item.status,
                    "priority": item.priority,
                    "payload": dict(item.payload or {}),
                }
                for item in TaskQueueRepository(session).list()
            ]

    @router.post("/queue/recover")
    def recover_queue() -> dict[str, Any]:
        with container.session_factory() as session:
            recovered = TaskQueueRepository(session).recover_stale_running()
            return {"recovered_count": recovered}

    @router.get("/runs")
    def list_runs(status: str | None = None) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            stmt = select(AgentRun).order_by(AgentRun.updated_at.desc(), AgentRun.id.desc())
            if status is not None:
                stmt = stmt.where(AgentRun.status == status)
            return [
                {
                    "id": run.id,
                    "run_id": run.run_id,
                    "status": run.status,
                    "ticks_count": run.ticks_count,
                    "turns_count": run.turns_count,
                }
                for run in session.scalars(stmt).all()
            ]

    @router.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        with container.session_factory() as session:
            run = _resolve_run(session, run_id)
            return {
                "id": run.id,
                "run_id": run.run_id,
                "status": run.status,
                "ticks_count": run.ticks_count,
                "turns_count": run.turns_count,
            }

    @router.get("/runs/{run_id}/ticks")
    def list_ticks(run_id: str) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            run = _resolve_run(session, run_id)
            stmt = select(AgentTickRecord).where(AgentTickRecord.run_pk == run.id).order_by(AgentTickRecord.seq.asc())
            return [
                {
                    "id": tick.id,
                    "tick_id": tick.tick_id,
                    "seq": tick.seq,
                    "status": tick.status,
                    "outcome_kind": tick.outcome_kind,
                }
                for tick in session.scalars(stmt).all()
            ]

    @router.get("/runs/{run_id}/ticks/{tick_id}/turns")
    def list_turns(run_id: str, tick_id: str) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            run = _resolve_run(session, run_id)
            tick = session.scalars(
                select(AgentTickRecord).where(AgentTickRecord.run_pk == run.id, AgentTickRecord.tick_id == tick_id)
            ).first()
            if tick is None:
                return []
            stmt = select(AgentTurnRecord).where(AgentTurnRecord.tick_pk == tick.id).order_by(AgentTurnRecord.seq.asc())
            return [
                {
                    "id": turn.id,
                    "turn_id": turn.turn_id,
                    "seq": turn.seq,
                    "role": turn.role,
                    "stop_reason": turn.stop_reason,
                }
                for turn in session.scalars(stmt).all()
            ]

    @router.post("/assemblies/{jd_id}")
    def create_assembly(jd_id: str) -> dict[str, Any]:
        with container.session_factory() as session:
            profile = session.scalars(select(RecruitAgentProfile).order_by(RecruitAgentProfile.created_at.asc())).first()
            if profile is None:
                profile = RecruitAgentProfile(agent_key="default", name="Default", is_primary=True)
                session.add(profile)
                session.flush()
            assembly = JobAssembly(job_description_id=jd_id, agent_profile_id=profile.id)
            session.add(assembly)
            session.commit()
            session.refresh(assembly)
            return {"id": assembly.id, "job_description_id": assembly.job_description_id, "version": assembly.version}

    @router.get("/assemblies/{jd_id}/versions")
    def list_assembly_versions(jd_id: str) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            stmt = select(JobAssembly).where(JobAssembly.job_description_id == jd_id).order_by(JobAssembly.version.asc())
            return [{"id": item.id, "version": item.version, "status": item.status} for item in session.scalars(stmt).all()]

    @router.post("/heartbeat/pause")
    def pause_heartbeat() -> dict[str, Any]:
        state = container.heartbeat.pause(reason="manual")
        return {"autonomous_paused": state.autonomous_paused, "pause_reason": state.pause_reason}

    @router.post("/heartbeat/resume")
    def resume_heartbeat() -> dict[str, Any]:
        state = container.heartbeat.resume()
        return {"autonomous_paused": state.autonomous_paused, "pause_reason": state.pause_reason}

    @router.get("/heartbeat/status")
    def heartbeat_status() -> dict[str, Any]:
        return container.heartbeat.status()

    @router.post("/autonomous/pause")
    def pause_autonomous() -> dict[str, Any]:
        state = container.heartbeat.pause(reason="manual")
        return {"autonomous_paused": state.autonomous_paused, "pause_reason": state.pause_reason}

    @router.post("/autonomous/resume")
    def resume_autonomous() -> dict[str, Any]:
        state = container.heartbeat.resume()
        return {"autonomous_paused": state.autonomous_paused, "pause_reason": state.pause_reason}

    @router.get("/autonomous/state")
    def autonomous_state() -> dict[str, Any]:
        return container.heartbeat.status()

    return router


def _queue_depth(container: AppContainer) -> int:
    with container.session_factory() as session:
        return TaskQueueRepository(session).pending_count()


def _resolve_run(session, run_id: str) -> AgentRun:
    run = session.scalars(select(AgentRun).where(AgentRun.run_id == run_id)).first()
    if run is None:
        run = session.get(AgentRun, run_id)
    if run is None:
        raise KeyError(f"unknown run: {run_id}")
    return run
