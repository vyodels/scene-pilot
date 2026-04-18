from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from scene_pilot.mcp.health import summarize_mcp_health
from scene_pilot.models.domain import AgentRun
from scene_pilot.services.container import AppContainer


def build_router(container: AppContainer) -> APIRouter:
    router = APIRouter(prefix="/api/debug", tags=["debug"])

    @router.get("/runs/{run_id}/replay")
    def replay_run(run_id: str) -> dict:
        with container.session_factory() as session:
            run = session.scalars(select(AgentRun).where(AgentRun.run_id == run_id)).first()
            if run is None:
                run = session.get(AgentRun, run_id)
            return {} if run is None else {"run_id": run.run_id, "status": run.status, "context_manifest": run.context_manifest}

    @router.get("/cache/stats")
    def cache_stats() -> dict:
        return {"entries": 0}

    @router.get("/mcp/health")
    def mcp_health() -> dict:
        return summarize_mcp_health(container.mcp_registry.list_servers())

    @router.get("/circuit-breakers")
    def circuit_breakers() -> dict:
        return {"breakers": []}

    @router.get("/alerts")
    def alerts() -> list:
        return []

    return router
