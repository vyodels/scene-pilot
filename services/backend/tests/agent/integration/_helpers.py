from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.agents.assistant import AssistantAgent
from recruit_agent.api.routers.assistant import build_router as build_assistant_router
from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.kernel.kernel import AgentKernel
from recruit_agent.plugins.host import PluginHost
from recruit_agent.runtime.providers import LLMProvider
from recruit_agent.runtime.tools import ToolRegistry, register_core_tools
from recruit_agent.assistant.session_store import AssistantSessionStore


def make_session_factory(tmp_path: Path, db_name: str) -> sessionmaker[Session]:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / db_name}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)


def make_session(tmp_path: Path, db_name: str) -> Session:
    return make_session_factory(tmp_path, db_name)()


def build_assistant_client(
    tmp_path: Path,
    *,
    provider: LLMProvider,
    tools: ToolRegistry | None = None,
    plugin_host: PluginHost | None = None,
) -> tuple[TestClient, AssistantAgent, sessionmaker[Session]]:
    session_factory = make_session_factory(tmp_path, "assistant.db")
    registry = tools or ToolRegistry()
    if not registry.tools:
        register_core_tools(registry)
    kernel = AgentKernel(
        provider=provider,
        tool_registry=registry,
        plugin_host=plugin_host or PluginHost(),
    )
    store = AssistantSessionStore(session_factory=session_factory, base_dir=tmp_path / "assistant-jsonl")
    agent = AssistantAgent(kernel=kernel, session_factory=session_factory, session_store=store)
    app = FastAPI()
    app.include_router(build_assistant_router(agent))
    return TestClient(app), agent, session_factory
