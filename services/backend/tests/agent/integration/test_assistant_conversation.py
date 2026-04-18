from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scene_pilot.agents.assistant import AssistantAgent
from scene_pilot.api.routers.assistant import build_router
from scene_pilot.assistant.session_store import AssistantSessionStore
from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.runtime.models import CancellationToken, LLMResponse
from scene_pilot.runtime.providers import ScriptedProvider
from scene_pilot.runtime.tools import ToolRegistry, register_core_tools


def _build_app(tmp_path: Path) -> tuple[TestClient, AssistantAgent]:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'assistant.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    store = AssistantSessionStore(session_factory=session_factory, base_dir=tmp_path / "assistant-jsonl")
    provider = ScriptedProvider(provider_name="scripted", responses=[LLMResponse(content="assistant reply")])
    tools = ToolRegistry()
    register_core_tools(tools)
    agent = AssistantAgent(provider=provider, tool_registry=tools, session_store=store)
    app = FastAPI()
    app.include_router(build_router(agent))
    return TestClient(app), agent


def test_assistant_conversation_flow_and_cancel_endpoint(tmp_path: Path) -> None:
    client, agent = _build_app(tmp_path)
    with client:
        created = client.post("/api/assistant/conversations", json={"user_id": "user-1", "title": "Hiring"}).json()
        conversation_id = created["conversation_id"]

        stream_response = client.post(
            f"/api/assistant/conversations/{conversation_id}/turn",
            json={"message": "Summarize candidate status"},
        )
        body = stream_response.text
        assert stream_response.status_code == 200
        assert "event: turn_started" in body
        assert "event: llm_final" in body
        assert "event: turn_completed" in body

        listed = client.get("/api/assistant/conversations", params={"user_id": "user-1"}).json()
        assert listed[0]["conversation_id"] == conversation_id

        agent.active_tokens[conversation_id] = CancellationToken()
        cancelled = client.post(f"/api/assistant/conversations/{conversation_id}/cancel").json()
        assert cancelled["cancelled"] is True
