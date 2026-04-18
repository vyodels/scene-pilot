from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.agents.assistant import AssistantAgent
from scene_pilot.agents.autonomous import AutonomousAgent
from scene_pilot.agents.heartbeat import Heartbeat
from scene_pilot.assistant.session_store import AssistantSessionStore
from scene_pilot.core.settings import AppSettings, load_settings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.evolution.learning_writer import LearningWriter
from scene_pilot.evolution.promotion import PromotionService
from scene_pilot.evolution.queue import EvolutionQueue
from scene_pilot.execution_units.browser_worker import run_browser_worker
from scene_pilot.execution_units.runner import ExecutionUnitRunner
from scene_pilot.execution_units.store import ExecutionUnitStore
from scene_pilot.kernel.kernel import AgentKernel
from scene_pilot.mcp.registry import McpRegistry
from scene_pilot.plugins.host import PluginHost
from scene_pilot.plugins.loader import install_manifest
from scene_pilot.plugins.recruit.manifest import RecruitPluginManifest
from scene_pilot.runtime.models import LLMResponse, Message
from scene_pilot.runtime.providers import LLMProvider
from scene_pilot.runtime.tools import ToolRegistry, register_core_tools


@dataclass(slots=True)
class DeterministicProvider:
    provider_name: str = "deterministic"

    def generate(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        latest_user_message = next((message.content for message in reversed(messages) if message.role == "user"), "")
        return LLMResponse(content=f"ack:{latest_user_message[:120]}")


@dataclass(slots=True)
class AppContainer:
    settings: AppSettings
    session_factory: sessionmaker[Session]
    provider: LLMProvider
    tool_registry: ToolRegistry
    plugin_host: PluginHost
    kernel: AgentKernel
    autonomous_agent: AutonomousAgent
    heartbeat: Heartbeat
    session_store: AssistantSessionStore
    assistant_agent: AssistantAgent
    execution_unit_store: ExecutionUnitStore
    execution_unit_runner: ExecutionUnitRunner
    learning_writer: LearningWriter
    evolution_queue: EvolutionQueue
    promotion: PromotionService
    mcp_registry: McpRegistry

    @classmethod
    def build(cls, settings: AppSettings | None = None) -> "AppContainer":
        resolved_settings = settings or load_settings()
        engine = create_engine_from_settings(resolved_settings)
        initialize_database(engine)
        session_factory = create_session_factory(engine)

        provider = DeterministicProvider()
        tool_registry = ToolRegistry()
        register_core_tools(tool_registry)

        plugin_host = PluginHost()
        install_manifest(plugin_host, RecruitPluginManifest(session_factory))
        tool_registry.merge(plugin_host.tool_registry)

        kernel = AgentKernel(provider=provider, tool_registry=tool_registry, plugin_host=plugin_host)
        autonomous_agent = AutonomousAgent(session_factory=session_factory, kernel=kernel)
        heartbeat = Heartbeat(session_factory=session_factory, autonomous_agent=autonomous_agent)

        data_dir = resolved_settings.resolved_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        session_store = AssistantSessionStore(session_factory=session_factory, base_dir=Path(data_dir) / "assistant-jsonl")
        assistant_agent = AssistantAgent(provider=provider, tool_registry=tool_registry, session_store=session_store)

        execution_unit_store = ExecutionUnitStore()
        execution_unit_runner = ExecutionUnitRunner(
            store=execution_unit_store,
            workers={"browser": run_browser_worker},
        )
        learning_writer = LearningWriter(session_factory)
        evolution_queue = EvolutionQueue(session_factory)
        promotion = PromotionService(session_factory)
        mcp_registry = McpRegistry(session_factory)

        return cls(
            settings=resolved_settings,
            session_factory=session_factory,
            provider=provider,
            tool_registry=tool_registry,
            plugin_host=plugin_host,
            kernel=kernel,
            autonomous_agent=autonomous_agent,
            heartbeat=heartbeat,
            session_store=session_store,
            assistant_agent=assistant_agent,
            execution_unit_store=execution_unit_store,
            execution_unit_runner=execution_unit_runner,
            learning_writer=learning_writer,
            evolution_queue=evolution_queue,
            promotion=promotion,
            mcp_registry=mcp_registry,
        )
