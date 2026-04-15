from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from scene_pilot.api import include_api_routers
from scene_pilot.core.settings import AppSettings
from scene_pilot.services.autonomy import AutonomyLoopService
from scene_pilot.services.container import AppContainer


@asynccontextmanager
async def lifespan(app: FastAPI):
    container: AppContainer = app.state.bootstrap_container  # type: ignore[assignment]
    autonomy = AutonomyLoopService(
        agent_control=container.agent_control,
        events=container.events,
        enabled=container.flags.is_enabled("feature.autonomy"),
        run_skill_health_sweep=container.run_skill_health_sweep,
        health_sweep_enabled=container.flags.is_enabled("skills.health_autonomy"),
        health_sweep_interval=float(container.settings.skill_health_autonomy_interval_seconds),
    )
    app.state.container = container
    app.state.settings = container.settings
    app.state.session_factory = container.session_factory
    app.state.autonomy_loop = autonomy
    await autonomy.start()
    try:
        yield
    finally:
        await autonomy.stop()


def create_app(settings: AppSettings | None = None) -> FastAPI:
    container = AppContainer.build(settings)
    app = FastAPI(title="Recruit Agent", version="0.1.0", lifespan=lifespan)
    app.state.bootstrap_container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    include_api_routers(app)

    @app.websocket("/ws/agent-stream")
    async def agent_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        container: AppContainer = app.state.container  # type: ignore[assignment]
        cursor = 0
        try:
            while True:
                events = container.events.snapshot()
                if cursor < len(events):
                    for event in events[cursor:]:
                        await websocket.send_json(
                            {
                                "id": event.id,
                                "level": event.level,
                                "source": event.source,
                                "message": event.message,
                                "at": event.at,
                            }
                        )
                    cursor = len(events)
                else:
                    await websocket.send_json({"type": "heartbeat"})
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            return

    return app

def main() -> dict[str, Any]:
    return {"app": "Recruit Agent backend"}
