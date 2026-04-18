from __future__ import annotations

from fastapi import FastAPI

from .deps import get_container, get_db, get_runtime_settings, get_session, get_session_factory
from .routers.agent import build_router as build_agent_router
from .routers.assistant import build_router as build_assistant_router
from .routers.debug import build_router as build_debug_router
from .routers.evolution import build_router as build_evolution_router
from .routers.health import router as health_router
from scene_pilot.services.container import AppContainer


def include_api_routers(app: FastAPI, container: AppContainer) -> None:
    app.include_router(health_router)
    app.include_router(build_agent_router(container))
    app.include_router(build_assistant_router(container.assistant_agent))
    app.include_router(build_evolution_router(queue=container.evolution_queue, promotion=container.promotion))
    app.include_router(build_debug_router(container))
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
