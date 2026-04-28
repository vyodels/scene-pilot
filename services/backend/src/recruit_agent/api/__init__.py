from __future__ import annotations

from fastapi import FastAPI

from .deps import get_container, get_db, get_runtime_settings, get_session, get_session_factory
from .routers.approvals import router as approvals_router
from .routers.agent import build_router as build_agent_router
from .routers.assistant import build_router as build_assistant_router
from .routers.candidate_applications import router as candidate_applications_router
from .routers.candidate_persons import router as candidate_persons_router
from .routers.communication_templates import router as communication_templates_router
from .routers.dashboard import router as dashboard_router
from .routers.debug import build_router as build_debug_router
from .routers.evolution import build_router as build_evolution_router
from .routers.health import router as health_router
from .routers.job_descriptions import router as job_descriptions_router
from .routers.mcp import router as mcp_router
from .routers.metrics import router as metrics_router
from .routers.playbooks import router as playbooks_router
from .routers.recruit_agent import router as recruit_agent_router
from .routers.settings import router as settings_router
from .routers.skills import router as skills_router
from .routers.state_machine import router as state_machine_router
from .routers.sync import router as sync_router
from recruit_agent.services.container import AppContainer


def include_api_routers(app: FastAPI, container: AppContainer) -> None:
    app.include_router(health_router)
    app.include_router(dashboard_router)
    app.include_router(settings_router)
    app.include_router(build_agent_router(container))
    app.include_router(build_assistant_router(container.assistant_agent))
    app.include_router(approvals_router)
    app.include_router(skills_router)
    app.include_router(sync_router)
    app.include_router(mcp_router)
    app.include_router(communication_templates_router)
    app.include_router(candidate_persons_router)
    app.include_router(job_descriptions_router)
    app.include_router(candidate_applications_router)
    app.include_router(state_machine_router)
    app.include_router(playbooks_router)
    app.include_router(recruit_agent_router)
    app.include_router(build_evolution_router(queue=container.evolution_queue, promotion=container.promotion))
    app.include_router(build_debug_router(container))
    app.include_router(metrics_router)
    for router in container.plugin_host.routers:
        app.include_router(router)


__all__ = [
    "get_container",
    "get_db",
    "get_runtime_settings",
    "get_session",
    "get_session_factory",
    "include_api_routers",
]
