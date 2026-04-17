from __future__ import annotations

from fastapi import FastAPI

from .deps import get_container, get_db, get_runtime_settings, get_session, get_session_factory
from .routers.agent import router as agent_router
from .routers.approvals import router as approvals_router
from .routers.candidate_applications import router as candidate_applications_router
from .routers.candidate_persons import router as candidate_persons_router
from .routers.dashboard import router as dashboard_router
from .routers.health import router as health_router
from .routers.job_descriptions import router as job_descriptions_router
from .routers.metrics import router as metrics_router
from .routers.mcp import router as mcp_router
from .routers.recruit_agent import router as recruit_agent_router
from .routers.runtime import router as runtime_router
from .routers.settings import router as settings_router
from .routers.skills import router as skills_router
from .routers.state_machine import router as state_machine_router
from .routers.sync import router as sync_router
from .routers.playbooks import router as playbooks_router

ALL_ROUTERS = [
    health_router,
    playbooks_router,
    candidate_persons_router,
    candidate_applications_router,
    job_descriptions_router,
    skills_router,
    mcp_router,
    settings_router,
    state_machine_router,
    approvals_router,
    metrics_router,
    runtime_router,
    recruit_agent_router,
    sync_router,
    dashboard_router,
    agent_router,
]


def include_api_routers(app: FastAPI) -> None:
    for router in ALL_ROUTERS:
        app.include_router(router)


__all__ = [
    "ALL_ROUTERS",
    "get_container",
    "get_db",
    "get_runtime_settings",
    "get_session",
    "get_session_factory",
    "include_api_routers",
]
