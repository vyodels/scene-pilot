from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scene_pilot.api import include_api_routers
from scene_pilot.core.settings import AppSettings
from scene_pilot.services.container import AppContainer


def create_app(settings: AppSettings | None = None) -> FastAPI:
    container = AppContainer.build(settings)
    app = FastAPI(title="Scene Pilot", version="0.2.0")
    app.state.container = container
    app.state.settings = container.settings
    app.state.session_factory = container.session_factory
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    include_api_routers(app, container)
    return app


def main() -> dict[str, Any]:
    return {"app": "Scene Pilot backend"}
