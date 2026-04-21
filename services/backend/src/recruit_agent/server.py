from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from recruit_agent.api import include_api_routers
from recruit_agent.core.settings import AppSettings
from recruit_agent.services.container import AppContainer
from recruit_agent.services.autonomy_loop import AutonomyLoop


def create_app(settings: AppSettings | None = None) -> FastAPI:
    container = AppContainer.build(settings)
    autonomy_loop = AutonomyLoop(
        heartbeat=container.heartbeat,
        # Manual Autonomous runs must always be consumed, even when the
        # background sourcing loop is disabled in settings.
        enabled=True,
        health_sweep_enabled=container.settings.feature_flags.enable_skill_health_autonomy,
        health_sweep_interval=float(container.settings.skill_health_autonomy_interval_seconds),
    )

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        container.autonomous_agent.recover_stale()
        await autonomy_loop.start()
        try:
            yield
        finally:
            await autonomy_loop.stop()

    app = FastAPI(title="Recruit Agent", version="0.2.0", lifespan=_lifespan)
    app.state.container = container
    app.state.settings = container.settings
    app.state.session_factory = container.session_factory
    app.state.autonomy_loop = autonomy_loop
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    include_api_routers(app, container)
    return app


def main() -> dict[str, Any]:
    return {"app": "Recruit Agent backend"}
