from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.core.settings import AppSettings, load_settings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.repositories import SettingsRepository, SkillRepository
from scene_pilot.runtime.agent_loop import AgentLoop
from scene_pilot.runtime.models import LLMResponse, Message
from scene_pilot.runtime.prompts import PromptBuilder
from scene_pilot.runtime.providers import AnthropicProvider, LLMProvider, OpenAICompatibleProvider, ProviderRegistry
from scene_pilot.runtime.tools import ToolDefinition, ToolRegistry
from scene_pilot.scheduler.queue import SqlAlchemyQueue
from scene_pilot.scheduler.scheduler import SerialScheduler
from scene_pilot.services.agent import AgentControlService
from scene_pilot.services.dashboard import DashboardService
from scene_pilot.services.events import EventStreamService
from scene_pilot.services.feature_flags import FeatureFlagService
from scene_pilot.services.mcp_registry import McpRegistryService
from scene_pilot.services.runtime import PersistedRuntimeService
from scene_pilot.services.runtime_control import RuntimeControlService
from scene_pilot.services.skills import SkillHealthSweepService, SkillLifecycleService, SkillSafetyService
from scene_pilot.services.sync import SyncService
from scene_pilot.services.system_commands import SystemCommandService
from scene_pilot.workflows.engine import WorkflowEngine


@dataclass(slots=True)
class RegistryBackedProvider:
    registry: ProviderRegistry
    preferred_provider: str | None = None
    provider_name: str = "registry_runtime"

    def generate(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        return self.registry.generate(
            messages,
            preferred_provider=self.preferred_provider,
            tools=tools,
            task=task,
            max_tokens=max_tokens,
            temperature=temperature,
        )


def _build_provider_registry(settings: AppSettings) -> tuple[ProviderRegistry, LLMProvider]:
    registry = ProviderRegistry()
    preferred_provider: str | None = None

    openai_config = settings.build_provider_config("openai_compatible")
    if openai_config.has_http_credentials():
        registry.register(OpenAICompatibleProvider(openai_config))
        preferred_provider = preferred_provider or openai_config.provider_name

    anthropic_config = settings.build_provider_config("anthropic")
    if anthropic_config.has_http_credentials():
        registry.register(AnthropicProvider(anthropic_config))
        preferred_provider = preferred_provider or anthropic_config.provider_name

    return registry, RegistryBackedProvider(registry=registry, preferred_provider=preferred_provider)


def _build_sync_target(settings: AppSettings) -> dict[str, Any]:
    sync_settings = settings.intranet_sync
    provider_config = settings.provider_config or {}
    return {
        "kind": "intranet",
        "base_url": str(sync_settings.base_url or provider_config.get("intranet_base_url") or ""),
        "api_path": str(sync_settings.api_path),
        "timeout_seconds": int(sync_settings.timeout_seconds or provider_config.get("intranet_timeout_seconds", 10) or 10),
    }


def _build_runtime_tools(system_commands: SystemCommandService, mcp_registry: McpRegistryService) -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(tools.build_result_submission_tool())
    tools.register(tools.build_observation_tool())
    tools.register(tools.build_step_completion_tool())
    tools.register(tools.build_replan_request_tool())
    tools.register(tools.build_human_checkpoint_tool())
    tools.register(
        ToolDefinition(
            name="record_note",
            description="Store an audit note for the current candidate.",
            parameters={
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"],
            },
            handler=lambda args: {"recorded": True, "note": args.get("note", "")},
            metadata={
                "capabilities": ["document", "analyze"],
                "produces_artifact": True,
            },
        )
    )
    tools.register(tools.build_system_command_tool(system_commands.request_tool_command))
    mcp_registry.register_enabled_runtime_tools(tools)
    return tools


@dataclass(slots=True)
class AppContainer:
    settings: AppSettings
    session_factory: sessionmaker[Session]
    flags: FeatureFlagService
    providers: ProviderRegistry
    tools: ToolRegistry
    workflow_engine: WorkflowEngine
    scheduler: SerialScheduler
    events: EventStreamService
    agent_control: AgentControlService
    dashboard: DashboardService
    sync: SyncService
    skill_lifecycle: SkillLifecycleService
    skill_safety: SkillSafetyService
    system_commands: SystemCommandService
    mcp_registry: McpRegistryService

    def reload_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.dashboard.settings = settings
        self.sync.intranet_enabled = settings.feature_flags.enable_intranet_sync
        self.sync.target = _build_sync_target(settings)
        self.agent_control.settings = settings
        self.flags.merge(
            {
                "skills.auto_activate": False,
                "skills.health_autonomy": settings.feature_flags.enable_skill_health_autonomy,
                "skills.system_command": settings.feature_flags.enable_system_commands,
                "feature.autonomy": settings.feature_flags.enable_autonomy,
                "feature.outbound_messaging": settings.feature_flags.enable_outbound_messaging,
            }
        )

        providers, runtime_provider = _build_provider_registry(settings)
        self.providers = providers

        tools = _build_runtime_tools(self.system_commands, self.mcp_registry)
        self.tools = tools
        self.agent_control.runtime_service_factory = lambda session: PersistedRuntimeService(
            session=session,
            providers=providers,
            tools=tools,
        )

        if self.agent_control.agent_loop is not None:
            self.agent_control.agent_loop.provider = runtime_provider
            self.agent_control.agent_loop.tools = tools

    @classmethod
    def build(cls, settings: AppSettings | None = None) -> "AppContainer":
        resolved_settings = settings or load_settings()
        engine = create_engine_from_settings(resolved_settings)
        initialize_database(engine)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            persisted_settings = SettingsRepository(session).load(resolved_settings)
        resolved_settings = AppSettings.model_validate(persisted_settings.model_dump())

        flags = FeatureFlagService(
            {
                "skills.auto_activate": False,
                "skills.health_autonomy": resolved_settings.feature_flags.enable_skill_health_autonomy,
                "skills.system_command": resolved_settings.feature_flags.enable_system_commands,
                "feature.autonomy": resolved_settings.feature_flags.enable_autonomy,
                "feature.outbound_messaging": resolved_settings.feature_flags.enable_outbound_messaging,
            }
        )
        providers, runtime_provider = _build_provider_registry(resolved_settings)

        events = EventStreamService()
        system_commands = SystemCommandService(
            session_factory=session_factory,
            flags=flags,
            events=events,
        )
        mcp_registry = McpRegistryService(session_factory=session_factory)
        tools = _build_runtime_tools(system_commands, mcp_registry)
        workflow_engine = WorkflowEngine(session_factory=session_factory)
        agent_loop = AgentLoop(provider=runtime_provider, tools=tools, prompt_builder=PromptBuilder())
        scheduler = SerialScheduler(queue=SqlAlchemyQueue(session_factory), follow_up_factory=workflow_engine.build_follow_up_factory())
        sync = SyncService(
            intranet_enabled=resolved_settings.feature_flags.enable_intranet_sync,
            session_factory=session_factory,
            target=_build_sync_target(resolved_settings),
        )
        agent_control = AgentControlService(
            scheduler=scheduler,
            workflow_engine=workflow_engine,
            settings=resolved_settings,
            agent_loop=agent_loop,
            events=events,
            flags=flags,
            sync_service=sync,
            session_factory=session_factory,
            runtime_service_factory=lambda session: PersistedRuntimeService(
                session=session,
                providers=providers,
                tools=tools,
            ),
        )
        scheduler.runner = agent_control.build_runner()
        dashboard = DashboardService(resolved_settings, events, sync)
        skill_lifecycle = SkillLifecycleService(flags=flags)
        skill_safety = SkillSafetyService(flags=flags)

        container = cls(
            settings=resolved_settings,
            session_factory=session_factory,
            flags=flags,
            providers=providers,
            tools=tools,
            workflow_engine=workflow_engine,
            scheduler=scheduler,
            events=events,
            agent_control=agent_control,
            dashboard=dashboard,
            sync=sync,
            skill_lifecycle=skill_lifecycle,
            skill_safety=skill_safety,
            system_commands=system_commands,
            mcp_registry=mcp_registry,
        )
        recovered_tasks = 0
        recover_stale = getattr(container.scheduler.queue, "recover_stale", None)
        if callable(recover_stale):
            recovered_tasks = int(recover_stale(stale_after=timedelta(seconds=0)))
        with container.session_factory() as session:
            recovered_episodes = PersistedRuntimeService(session=session, providers=container.providers).recover_running_episodes()
        with container.session_factory() as session:
            recovered_runs = RuntimeControlService(session, settings=resolved_settings, live_events=events).recover_running_runs()
        if recovered_tasks:
            events.publish(
                "warning",
                "scheduler",
                "已恢复上一次运行遗留的过期队列任务。",
                recovered_tasks=recovered_tasks,
            )
        if recovered_episodes:
            events.publish(
                "warning",
                "runtime",
                "已恢复上一次本地运行中断的执行记录。",
                recovered_episodes=recovered_episodes,
            )
        if recovered_runs:
            events.publish(
                "warning",
                "runtime_control",
                "已恢复上一次中断的 AgentRun 记录。",
                recovered_runs=recovered_runs,
            )
        events.publish("info", "bootstrap", "应用容器已初始化。")
        return container

    def run_skill_health_sweep(
        self,
        *,
        statuses: list[str] | None = None,
        platform: str | None = None,
        observed_results_by_skill: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            repo = SkillRepository(session)
            sweep = SkillHealthSweepService()
            selected_statuses = statuses or ["active", "approved"]
            selected_skills = sweep.filter_skills(
                repo.list(limit=5000, offset=0),
                statuses=selected_statuses,
                platform=platform,
            )
            sweep_result = sweep.run(
                selected_skills,
                observed_results_by_skill=observed_results_by_skill,
            )

            degraded_skill_ids: list[str] = []
            healthy_skill_ids: list[str] = []
            for skill, _result in sweep_result.results:
                updated = repo.update(
                    skill,
                    {
                        "status": str(skill.status),
                        "last_health_check": skill.last_health_check,
                        "last_health_status": skill.last_health_status,
                        "updated_at": skill.updated_at,
                    },
                )
                if updated.status == "degraded":
                    degraded_skill_ids.append(updated.skill_id)
                elif updated.last_health_status == "healthy":
                    healthy_skill_ids.append(updated.skill_id)

            return {
                "checked_count": sweep_result.checked_count,
                "degraded_count": sweep_result.degraded_count,
                "statuses": selected_statuses,
                "platform": platform,
                "degraded_skill_ids": degraded_skill_ids,
                "healthy_skill_ids": healthy_skill_ids,
            }
