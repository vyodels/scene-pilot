from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.agents.assistant import AssistantAdapter
from recruit_agent.agents.autonomous import AutonomousAdapter
from recruit_agent.agents.heartbeat import Heartbeat
from recruit_agent.agent_runtime.providers import (
    AnthropicProvider,
    LLMProvider,
    OpenAIProvider,
    ProviderConfig as AgentRuntimeProviderConfig,
    ProviderRegistry,
    UnavailableProvider,
)
from recruit_agent.assistant.session_store import AssistantSessionStore
from recruit_agent.core.settings import AppSettings, load_settings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.evolution.learning_writer import LearningWriter
from recruit_agent.memory.filesystem import MemoryFileStore
from recruit_agent.evolution.promotion import PromotionService
from recruit_agent.evolution.queue import EvolutionQueue
from recruit_agent.plugins.host import PluginHost
from recruit_agent.plugins.loader import install_manifest
from recruit_agent.plugins.recruit.manifest import RecruitPluginManifest
from recruit_agent.capabilities.tools import (
    ToolRegistry,
    build_delegate_scene_context_tool,
    is_approval_tool,
    is_scene_context_tool,
    register_core_tools,
)
from recruit_agent.scheduler.queue import SqlAlchemyQueue
from recruit_agent.scheduler.scheduler import SerialScheduler
from recruit_agent.services.recruit_agent import (
    default_recruit_agent_profile,
    resolve_context_policy,
    resolve_goal_template,
    resolve_memory_policy,
)
from recruit_agent.services.dashboard import DashboardService
from recruit_agent.services.events import EventStreamService
from recruit_agent.services.feature_flags import FeatureFlagService
from recruit_agent.services.mcp_registry import McpRegistryService
from recruit_agent.services.scene_context import SceneContextService
from recruit_agent.repositories.domain import RecruitAgentProfileRepository, SettingsRepository
from recruit_agent.services.sync import SyncService
from recruit_agent.services.system_commands import SystemCommandService


@dataclass(slots=True)
class AppContainer:
    settings: AppSettings
    session_factory: sessionmaker[Session]
    provider: LLMProvider
    providers: ProviderRegistry
    tool_registry: ToolRegistry
    scene_context_tool_registry: ToolRegistry
    plugin_host: PluginHost
    scene_context_service: SceneContextService
    autonomous_adapter: AutonomousAdapter
    heartbeat: Heartbeat
    session_store: AssistantSessionStore
    assistant_adapter: AssistantAdapter
    learning_writer: LearningWriter
    evolution_queue: EvolutionQueue
    promotion: PromotionService
    mcp_registry: McpRegistryService
    events: EventStreamService
    flags: FeatureFlagService
    system_commands: SystemCommandService
    sync: SyncService
    dashboard: DashboardService
    scheduler: SerialScheduler

    @classmethod
    def build(cls, settings: AppSettings | None = None) -> "AppContainer":
        resolved_settings = settings or load_settings()
        engine = create_engine_from_settings(resolved_settings)
        initialize_database(engine)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            stored_settings = SettingsRepository(session).load(resolved_settings)
        resolved_settings = AppSettings.model_validate(stored_settings.model_dump())
        _seed_builtin_agent_profiles(session_factory)

        plugin_host = PluginHost()
        install_manifest(plugin_host, RecruitPluginManifest(session_factory))
        mcp_registry = McpRegistryService(session_factory)
        memory_file_store = _build_memory_file_store(resolved_settings)

        providers, provider = _build_provider_bundle(resolved_settings)
        tool_registry, scene_context_tool_registry = _build_runtime_tool_registries(
            settings=resolved_settings,
            session_factory=session_factory,
            plugin_host=plugin_host,
            mcp_registry=mcp_registry,
        )

        learning_writer = LearningWriter(session_factory)
        scene_context_service = SceneContextService(
            session_factory=session_factory,
            provider=provider,
            tool_registry=scene_context_tool_registry,
            plugin_host=plugin_host,
        )
        _register_delegate_scene_context_tool(tool_registry, scene_context_service=scene_context_service)
        autonomous_adapter = AutonomousAdapter(
            session_factory=session_factory,
            provider=provider,
            tool_registry=tool_registry,
            plugin_host=plugin_host,
            learning_writer=learning_writer,
            mcp_registry=mcp_registry,
            memory_file_store=memory_file_store,
        )
        heartbeat = Heartbeat(session_factory=session_factory, autonomous_adapter=autonomous_adapter)

        data_dir = resolved_settings.resolved_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        session_store = AssistantSessionStore(session_factory=session_factory, base_dir=Path(data_dir) / "assistant-jsonl")
        assistant_adapter = AssistantAdapter(
            provider=provider,
            tool_registry=tool_registry,
            plugin_host=plugin_host,
            session_factory=session_factory,
            session_store=session_store,
            max_history_messages=resolved_settings.assistant_max_history_messages,
        )

        evolution_queue = EvolutionQueue(session_factory)
        promotion = PromotionService(session_factory)
        events = EventStreamService()
        flags = _build_flags(resolved_settings)
        sync = _build_sync_service(resolved_settings, session_factory)
        dashboard = DashboardService(settings=resolved_settings, events=events, sync_service=sync)
        scheduler = SerialScheduler(queue=SqlAlchemyQueue(session_factory))
        system_commands = SystemCommandService(
            session_factory=session_factory,
            flags=flags,
            events=events,
            execution_enabled=resolved_settings.feature_flags.enable_system_commands,
        )
        return cls(
            settings=resolved_settings,
            session_factory=session_factory,
            provider=provider,
            providers=providers,
            tool_registry=tool_registry,
            scene_context_tool_registry=scene_context_tool_registry,
            plugin_host=plugin_host,
            scene_context_service=scene_context_service,
            autonomous_adapter=autonomous_adapter,
            heartbeat=heartbeat,
            session_store=session_store,
            assistant_adapter=assistant_adapter,
            learning_writer=learning_writer,
            evolution_queue=evolution_queue,
            promotion=promotion,
            mcp_registry=mcp_registry,
            events=events,
            flags=flags,
            system_commands=system_commands,
            sync=sync,
            dashboard=dashboard,
            scheduler=scheduler,
        )

    def reload_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.providers, self.provider = _build_provider_bundle(settings)
        self.tool_registry, self.scene_context_tool_registry = _build_runtime_tool_registries(
            settings=settings,
            session_factory=self.session_factory,
            plugin_host=self.plugin_host,
            mcp_registry=self.mcp_registry,
        )
        self.scene_context_service = SceneContextService(
            session_factory=self.session_factory,
            provider=self.provider,
            tool_registry=self.scene_context_tool_registry,
            plugin_host=self.plugin_host,
        )
        _register_delegate_scene_context_tool(self.tool_registry, scene_context_service=self.scene_context_service)
        self.autonomous_adapter.provider = self.provider
        self.autonomous_adapter.tool_registry = self.tool_registry
        self.autonomous_adapter.memory_file_store = _build_memory_file_store(settings)
        self.assistant_adapter.provider = self.provider
        self.assistant_adapter.tool_registry = self.tool_registry
        self.assistant_adapter.max_history_messages = settings.assistant_max_history_messages
        self.dashboard.settings = settings

        self.flags.flags.clear()
        self.flags.merge(
            {
                "skills.system_command": settings.feature_flags.enable_system_commands,
                "skills.auto_activate": bool(settings.provider_config.get("skills_auto_activate", False)),
            }
        )

        self.sync.intranet_enabled = settings.feature_flags.enable_intranet_sync
        self.sync.target = _build_sync_target(settings)
        self.system_commands.execution_enabled = settings.feature_flags.enable_system_commands


def _build_provider_bundle(settings: AppSettings) -> tuple[ProviderRegistry, LLMProvider]:
    registry = ProviderRegistry()
    runtime_settings = settings.provider_runtime_settings()
    if runtime_settings.openai_api_key:
        registry.register(
            OpenAIProvider(
                AgentRuntimeProviderConfig(
                    provider_name="openai",
                    model=runtime_settings.openai_model,
                    base_url=runtime_settings.openai_base_url,
                    api_key=runtime_settings.openai_api_key,
                    timeout_seconds=runtime_settings.openai_timeout_seconds,
                )
            )
        )
    if runtime_settings.anthropic_api_key:
        registry.register(
            AnthropicProvider(
                AgentRuntimeProviderConfig(
                    provider_name="anthropic",
                    model=runtime_settings.anthropic_model,
                    base_url=runtime_settings.anthropic_base_url,
                    api_key=runtime_settings.anthropic_api_key,
                    timeout_seconds=runtime_settings.anthropic_timeout_seconds,
                )
            )
        )
    if registry.providers:
        preferred = registry.fallback_order[0]
        return registry, registry.get(preferred)
    return registry, UnavailableProvider(
        reason="provider unavailable: configure RECRUIT_AGENT_PROVIDER_CONFIG__OPENAI_API_KEY or RECRUIT_AGENT_PROVIDER_CONFIG__ANTHROPIC_API_KEY",
    )


def _build_flags(settings: AppSettings) -> FeatureFlagService:
    flags = FeatureFlagService()
    flags.merge(
        {
            "skills.system_command": settings.feature_flags.enable_system_commands,
            "skills.auto_activate": bool(settings.provider_config.get("skills_auto_activate", False)),
        }
    )
    return flags


def _build_sync_target(settings: AppSettings) -> dict[str, Any]:
    return {
        "kind": "intranet",
        "base_url": settings.intranet_sync.base_url,
        "api_path": settings.intranet_sync.api_path,
    }


def _build_sync_service(settings: AppSettings, session_factory: sessionmaker[Session]) -> SyncService:
    return SyncService(
        intranet_enabled=settings.feature_flags.enable_intranet_sync,
        session_factory=session_factory,
        target=_build_sync_target(settings),
    )


def _build_read_memory_handler(store: MemoryFileStore):
    def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
        scope_kind, scope_ref, agent_profile_id = _memory_file_scope(arguments)
        limit = _bounded_int(arguments.get("limit"), default=50, minimum=1, maximum=100)
        query = str(arguments.get("query") or "").strip()
        entries = []
        for item in store.list_files(scope_kind=scope_kind, scope_ref=scope_ref, agent_profile_id=agent_profile_id):
            content = store.read_file(
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                agent_profile_id=agent_profile_id,
                path=str(item["path"]),
            ).get("content", "")
            if query and query.lower() not in f"{item['path']}\n{content}".lower():
                continue
            entries.append(
                {
                    "memory_item_id": item["path"],
                    "kind": "memory_file",
                    "summary": _first_non_empty_line(str(content or "")) or item["path"],
                    "content": {"path": item["path"], "text": content},
                    "updated_at": item.get("updated_at"),
                }
            )
            if len(entries) >= limit:
                break
        return {"entries": entries, "count": len(entries), "scope_kind": scope_kind, "scope_ref": scope_ref}

    return _handler


def _build_memory_file_store(settings: AppSettings) -> MemoryFileStore:
    return MemoryFileStore(settings.resolved_data_dir() / "memory-files")


def _build_list_memory_files_handler(store: MemoryFileStore):
    def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
        scope_kind, scope_ref, agent_profile_id = _memory_file_scope(arguments)
        files = store.list_files(scope_kind=scope_kind, scope_ref=scope_ref, agent_profile_id=agent_profile_id)
        return {"files": files, "count": len(files), "scope_kind": scope_kind, "scope_ref": scope_ref}

    return _handler


def _build_read_memory_file_handler(store: MemoryFileStore):
    def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
        scope_kind, scope_ref, agent_profile_id = _memory_file_scope(arguments)
        return store.read_file(
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            agent_profile_id=agent_profile_id,
            path=str(arguments.get("path") or "MEMORY.md"),
        )

    return _handler


def _build_write_memory_file_handler(store: MemoryFileStore):
    def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
        scope_kind, scope_ref, agent_profile_id = _memory_file_scope(arguments)
        return store.write_file(
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            agent_profile_id=agent_profile_id,
            path=str(arguments.get("path") or "MEMORY.md"),
            content=str(arguments.get("content") or ""),
            mode=str(arguments.get("mode") or "overwrite"),
        )

    return _handler


def _build_delete_memory_file_handler(store: MemoryFileStore):
    def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
        scope_kind, scope_ref, agent_profile_id = _memory_file_scope(arguments)
        return store.delete_file(
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            agent_profile_id=agent_profile_id,
            path=str(arguments.get("path") or ""),
        )

    return _handler


def _memory_file_scope(arguments: dict[str, Any]) -> tuple[str, str, str | None]:
    scope_kind = str(arguments.get("scope_kind") or arguments.get("scopeKind") or "").strip()
    scope_ref = str(arguments.get("scope_ref") or arguments.get("scopeRef") or "").strip()
    if not scope_kind or not scope_ref:
        raise ValueError("memory file tools require scope_kind and scope_ref")
    agent_profile_id = arguments.get("agent_profile_id") or arguments.get("agentProfileId")
    return scope_kind, scope_ref, str(agent_profile_id) if agent_profile_id else None


def _build_record_learning_handler(session_factory: sessionmaker[Session]):
    writer = LearningWriter(session_factory)

    def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
        payload = dict(arguments.get("payload") or {})
        content = str(arguments.get("content") or payload.get("content") or payload.get("summary") or "").strip()
        if not content:
            raise ValueError("record_learning requires content or payload.content")
        tags = _string_list(arguments.get("tags") or payload.get("tags") or [str(arguments.get("kind") or "learning")])
        return writer.record_learning(
            content=content,
            tags=tags,
            promote=bool(arguments.get("promote") or payload.get("promote") or False),
            skill_name=_optional_string(arguments.get("skill_name") or payload.get("skill_name")),
            trial_metrics=dict(arguments.get("trial_metrics") or payload.get("trial_metrics") or {}),
            job_description_id=_optional_string(arguments.get("job_description_id") or payload.get("job_description_id")),
            artifact_kind=_optional_string(arguments.get("artifact_kind") or arguments.get("kind") or payload.get("artifact_kind")),
        )

    return _handler


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _string_list(value: Any) -> list[str]:
    source = value if isinstance(value, list) else [value]
    items: list[str] = []
    for item in source:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items or ["learning"]


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _first_non_empty_line(text: str) -> str | None:
    for line in str(text or "").splitlines():
        stripped = line.strip(" #-\t")
        if stripped:
            return stripped[:240]
    return None


def _build_runtime_tool_registries(
    *,
    settings: AppSettings,
    session_factory: sessionmaker[Session],
    plugin_host: PluginHost,
    mcp_registry: McpRegistryService,
) -> tuple[ToolRegistry, ToolRegistry]:
    parent_registry = ToolRegistry()
    scene_registry = ToolRegistry()
    memory_file_store = _build_memory_file_store(settings)

    register_core_tools(
        parent_registry,
        read_memory_handler=_build_read_memory_handler(memory_file_store),
        list_memory_files_handler=_build_list_memory_files_handler(memory_file_store),
        read_memory_file_handler=_build_read_memory_file_handler(memory_file_store),
        write_memory_file_handler=_build_write_memory_file_handler(memory_file_store),
        delete_memory_file_handler=_build_delete_memory_file_handler(memory_file_store),
        record_learning_handler=_build_record_learning_handler(session_factory),
    )

    for tool in plugin_host.tool_registry.tools.values():
        if is_approval_tool(tool):
            parent_registry.register(tool.clone())
            scene_registry.register(tool.clone())
            continue
        if is_scene_context_tool(tool):
            scene_registry.register(tool.clone())
            continue
        parent_registry.register(tool.clone())

    mcp_registry_tools = ToolRegistry()
    mcp_registry.register_enabled_runtime_tools(mcp_registry_tools)
    for tool in mcp_registry_tools.tools.values():
        if is_scene_context_tool(tool):
            scene_registry.register(tool.clone())
            continue
        parent_registry.register(tool.clone())

    return parent_registry, scene_registry


def _register_delegate_scene_context_tool(
    tool_registry: ToolRegistry,
    *,
    scene_context_service: SceneContextService,
) -> None:
    tool_registry.register(build_delegate_scene_context_tool(scene_context_service.delegate))


def _seed_builtin_agent_profiles(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repo = RecruitAgentProfileRepository(session)
        assistant = repo.by_agent_key("assistant")
        autonomous = repo.by_agent_key("autonomous")
        legacy = repo.by_agent_key("recruit-agent")

        if autonomous is None and legacy is not None:
            autonomous = repo.update(
                legacy,
                {
                    "agent_key": "autonomous",
                    "is_primary": True,
                    "name": legacy.name or "Autonomous",
                    "status": legacy.status or "active",
                    "agent_metadata": _merge_agent_metadata(legacy.agent_metadata, kind="autonomous"),
                },
            )

        if autonomous is None:
            autonomous = repo.create(_default_autonomous_profile())
        else:
            autonomous_updates: dict[str, Any] = {}
            if not autonomous.is_primary:
                autonomous_updates["is_primary"] = True
            merged_metadata = _merge_agent_metadata(autonomous.agent_metadata, kind="autonomous")
            if merged_metadata != dict(autonomous.agent_metadata or {}):
                autonomous_updates["agent_metadata"] = merged_metadata
            prompt_config = dict(autonomous.prompt_config or {})
            resolved_context_policy = resolve_context_policy(prompt_config)
            resolved_goal_template = resolve_goal_template(prompt_config)
            if prompt_config.get("context_policy") != resolved_context_policy:
                prompt_config["context_policy"] = resolved_context_policy
                autonomous_updates["prompt_config"] = prompt_config
            if prompt_config.get("goal_template") != resolved_goal_template:
                prompt_config["goal_template"] = resolved_goal_template
                autonomous_updates["prompt_config"] = prompt_config
            resolved_memory_policy = resolve_memory_policy(autonomous.memory_policy)
            if resolved_memory_policy != dict(autonomous.memory_policy or {}):
                autonomous_updates["memory_policy"] = resolved_memory_policy
            if autonomous_updates:
                autonomous = repo.update(autonomous, autonomous_updates)

        if assistant is None:
            assistant = repo.create(_default_assistant_profile())
        else:
            assistant_updates: dict[str, Any] = {}
            if assistant.is_primary:
                assistant_updates["is_primary"] = False
            merged_metadata = _merge_agent_metadata(assistant.agent_metadata, kind="assistant")
            if merged_metadata != dict(assistant.agent_metadata or {}):
                assistant_updates["agent_metadata"] = merged_metadata
            if assistant_updates:
                repo.update(assistant, assistant_updates)

        if legacy is not None and autonomous is not None and legacy.id != autonomous.id and legacy.is_primary:
            repo.update(legacy, {"is_primary": False})


def _default_autonomous_profile() -> dict[str, Any]:
    payload = default_recruit_agent_profile()
    payload["agent_key"] = "autonomous"
    payload["name"] = "Autonomous"
    payload["agent_metadata"] = _merge_agent_metadata(payload.get("agent_metadata"), kind="autonomous")
    return payload


def _default_assistant_profile() -> dict[str, Any]:
    return {
        "agent_key": "assistant",
        "name": "Assistant",
        "status": "active",
        "description": "面向聊天界面的协作助手，负责解释状态、回答问题，并在需要时等待人工确认。",
        "is_primary": False,
        "role_definition": {
            "identity": "对话协作助手",
            "positioning": "在聊天窗口中协助用户理解系统状态、执行操作并保持确认意识。",
            "duties": [
                "回答用户问题并整理当前上下文。",
                "在需要时调用工具并解释结果。",
                "对高风险动作保留确认与暂停意识。",
            ],
            "tone": "clear, concise, collaborative",
            "boundaries": [
                "不要伪造系统状态或执行结果。",
                "高风险写入、外部动作、命令执行必须等待确认。",
                "不要把一个用户会话的上下文泄露到其他会话。",
            ],
            "success_criteria": [
                "回复清晰且可执行。",
                "工具结果与当前会话上下文一致。",
                "需要确认时能够显式停住并说明原因。",
            ],
            "forbidden_actions": [
                "未经确认执行高风险外部动作。",
                "伪造已完成但实际上未发生的操作。",
            ],
        },
        "prompt_config": {
            "system_prompt": "你是 Assistant 类型的 Recruit Agent。你的职责是在聊天界面中与用户协作，清晰解释状态、回答问题，并在高风险动作前等待确认。",
            "context_policy": {
                "memory_scope": "conversation",
                "share_global_context": True,
            },
            "response_policy": {
                "prefer_structured_output": False,
                "require_evidence_refs": False,
                "separate_fact_from_inference": True,
            },
        },
        "playbook_blueprint": {},
        "memory_policy": {
            "candidate_memory": {"isolation": "strict_by_candidate"},
            "job_memory": {"isolation": "strict_by_jd"},
            "agent_global_memory": {
                "scope": "agent_global",
                "share_read": True,
            },
        },
        "dashboard_config": {"layout": ["chat_sessions", "recent_activity"]},
        "channel_config": {"chat": {"enabled": True, "requires_confirmation": True}},
        "agent_metadata": _merge_agent_metadata({}, kind="assistant"),
    }


def _merge_agent_metadata(raw_metadata: Any, *, kind: str) -> dict[str, Any]:
    metadata = dict(raw_metadata or {})
    metadata.update(
        {
            "kind": kind,
            "builtin": True,
            "supports_builtin_agents": True,
        }
    )
    if kind == "autonomous":
        metadata["current_primary_agent"] = "autonomous"
    return metadata
