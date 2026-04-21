from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from recruit_agent.api.routers.evolution import build_router
from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.evolution.learning_writer import LearningWriter
from recruit_agent.evolution.promotion import PromotionService
from recruit_agent.evolution.queue import EvolutionQueue
from recruit_agent.mcp.health import summarize_mcp_health
from recruit_agent.mcp.registry import McpRegistry
from recruit_agent.models.domain import McpServer


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'evolution.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_evolution_pipeline_records_learning_and_promotes_trial_skill(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        session.add(
            McpServer(
                server_key="browser",
                name="Browser MCP",
                endpoint="http://localhost/browser",
                health_status="healthy",
            )
        )
        session.commit()

        session_factory = create_session_factory(session.get_bind())
        writer = LearningWriter(session_factory)
        queue = EvolutionQueue(session_factory)
        promotion = PromotionService(session_factory)

        recorded = writer.record_learning(
            content="Use a shorter greeting when candidate already replied.",
            tags=["prompt", "greeting"],
            promote=True,
            skill_name="candidate-greeting",
        )

        assert recorded["skill_id"] is not None
        pending = queue.list_pending(status="pending_review")
        assert pending[0].title == "candidate-greeting"

        app = FastAPI()
        app.include_router(build_router(queue=queue, promotion=promotion))
        client = TestClient(app)

        approve = client.post(f"/api/evolution/queue/{pending[0].id}/approve")
        assert approve.status_code == 200
        assert approve.json()["status"] == "applied"
        assert approve.json()["artifact_kind"] == "skill_draft"

        active_skills = client.get("/api/evolution/skills", params={"status": "active"}).json()
        assert active_skills[0]["name"] == "candidate-greeting"

        health = summarize_mcp_health(McpRegistry(session_factory).list_servers())
        assert health["healthy"] == 1
    finally:
        session.close()
