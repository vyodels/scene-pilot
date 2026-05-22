from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from recruit_station.agents.assistant import AssistantAdapter
from recruit_station.agents.autonomous import AutonomousAdapter
from recruit_station.agents.heartbeat import Heartbeat
from recruit_station.agent_runtime.providers import (
    AnthropicProvider,
    LLMProvider,
    OpenAIProvider,
    ProviderConfig as AgentRuntimeProviderConfig,
    ProviderRegistry,
    UnavailableProvider,
)
from recruit_station.assistant.session_store import AssistantSessionStore
from recruit_station.core.settings import AppSettings, load_settings
from recruit_station.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_station.evolution.learning_writer import LearningWriter
from recruit_station.memory.filesystem import MemoryFileStore
from recruit_station.evolution.promotion import PromotionService
from recruit_station.evolution.queue import EvolutionQueue
from recruit_station.plugins.host import PluginHost
from recruit_station.plugins.loader import install_manifest
from recruit_station.plugins.recruit.manifest import RecruitPluginManifest
from recruit_station.capabilities.tools import (
    ToolDefinition,
    ToolRegistry,
    build_delegate_scene_context_tool,
    is_approval_tool,
    is_scene_context_tool,
    register_core_tools,
)
from recruit_station.scheduler.queue import SqlAlchemyQueue
from recruit_station.scheduler.scheduler import SerialScheduler
from recruit_station.services.recruit_station import (
    default_agent_definition,
    normalize_prompt_config,
    resolve_context_policy,
    resolve_memory_policy,
    _refresh_builtin_product_prompt_config,
)
from recruit_station.services.dashboard import DashboardService
from recruit_station.services.download_attribution import LocalDownloadAttributionService
from recruit_station.services.events import EventStreamService
from recruit_station.services.feature_flags import FeatureFlagService
from recruit_station.services.mcp_registry import McpRegistryService
from recruit_station.services.scene_context import SceneContextService
from recruit_station.repositories.domain import AgentDefinitionRepository, SettingsRepository
from recruit_station.services.sync import SyncService
from recruit_station.services.system_commands import SystemCommandService


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
    memory_file_store: MemoryFileStore
    events: EventStreamService
    flags: FeatureFlagService
    system_commands: SystemCommandService
    sync: SyncService
    dashboard: DashboardService
    scheduler: SerialScheduler
    download_attribution: LocalDownloadAttributionService

    @classmethod
    def build(cls, settings: AppSettings | None = None) -> "AppContainer":
        resolved_settings = settings or load_settings()
        engine = create_engine_from_settings(resolved_settings)
        initialize_database(engine)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            stored_settings = SettingsRepository(session).load(resolved_settings)
        resolved_settings = AppSettings.model_validate(stored_settings.model_dump())
        _seed_builtin_agent_definitions(session_factory)

        plugin_host = PluginHost()
        install_manifest(plugin_host, RecruitPluginManifest(session_factory))
        mcp_registry = McpRegistryService(session_factory)
        memory_file_store = _build_memory_file_store(resolved_settings)

        providers, provider = _build_provider_bundle(resolved_settings)
        download_attribution = LocalDownloadAttributionService(allowed_download_roots=(resolved_settings.resolved_data_dir(),))
        tool_registry, scene_context_tool_registry = _build_runtime_tool_registries(
            settings=resolved_settings,
            session_factory=session_factory,
            plugin_host=plugin_host,
            mcp_registry=mcp_registry,
            download_attribution=download_attribution,
        )

        learning_writer = LearningWriter(session_factory)
        runtime_settings = resolved_settings.provider_runtime_settings()
        scene_context_service = SceneContextService(
            session_factory=session_factory,
            provider=provider,
            tool_registry=scene_context_tool_registry,
            plugin_host=plugin_host,
            anti_detection_policy=dict(runtime_settings.anti_detection_policy),
            behavior_budget=dict(runtime_settings.behavior_budget),
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
            anti_detection_policy=dict(runtime_settings.anti_detection_policy),
            behavior_budget=dict(runtime_settings.behavior_budget),
            max_context_chars=resolved_settings.autonomous_max_context_chars,
            compaction_summary_max_chars=resolved_settings.autonomous_compaction_summary_max_chars,
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
            memory_file_store=memory_file_store,
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
            memory_file_store=memory_file_store,
            events=events,
            flags=flags,
            system_commands=system_commands,
            sync=sync,
            dashboard=dashboard,
            scheduler=scheduler,
            download_attribution=download_attribution,
        )

    def reload_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.providers, self.provider = _build_provider_bundle(settings)
        runtime_settings = settings.provider_runtime_settings()
        self.tool_registry, self.scene_context_tool_registry = _build_runtime_tool_registries(
            settings=settings,
            session_factory=self.session_factory,
            plugin_host=self.plugin_host,
            mcp_registry=self.mcp_registry,
            download_attribution=self.download_attribution,
        )
        self.scene_context_service = SceneContextService(
            session_factory=self.session_factory,
            provider=self.provider,
            tool_registry=self.scene_context_tool_registry,
            plugin_host=self.plugin_host,
            anti_detection_policy=dict(runtime_settings.anti_detection_policy),
            behavior_budget=dict(runtime_settings.behavior_budget),
        )
        _register_delegate_scene_context_tool(self.tool_registry, scene_context_service=self.scene_context_service)
        self.autonomous_adapter.provider = self.provider
        self.autonomous_adapter.tool_registry = self.tool_registry
        self.autonomous_adapter.anti_detection_policy = dict(runtime_settings.anti_detection_policy)
        self.autonomous_adapter.behavior_budget = dict(runtime_settings.behavior_budget)
        self.memory_file_store = _build_memory_file_store(settings)
        self.autonomous_adapter.memory_file_store = self.memory_file_store
        self.assistant_adapter.provider = self.provider
        self.assistant_adapter.tool_registry = self.tool_registry
        self.assistant_adapter.memory_file_store = self.memory_file_store
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
        reason="provider unavailable: configure RECRUIT_STATION_PROVIDER_CONFIG__OPENAI_API_KEY or RECRUIT_STATION_PROVIDER_CONFIG__ANTHROPIC_API_KEY",
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
        scope_kind, scope_ref, agent_definition_id = _memory_tool_scope(arguments)
        limit = _bounded_int(arguments.get("limit"), default=50, minimum=1, maximum=100)
        query = str(arguments.get("query") or "").strip()
        entries = []
        for item in store.list_files(scope_kind=scope_kind, scope_ref=scope_ref, agent_definition_id=agent_definition_id):
            content = store.read_file(
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                agent_definition_id=agent_definition_id,
                path=str(item["path"]),
            ).get("content", "")
            if query and query.lower() not in f"{item['path']}\n{content}".lower():
                continue
            entries.append(
                {
                    "memory_item_id": item["path"],
                    "kind": "memory_file",
                    "summary": _first_non_empty_line(str(content or "")) or item["path"],
                    "content": {"path": item["path"], "preview": str(content or "").strip()[:500]},
                    "size": item.get("size"),
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
        scope_kind, scope_ref, agent_definition_id = _memory_tool_scope(arguments)
        files = store.list_files(scope_kind=scope_kind, scope_ref=scope_ref, agent_definition_id=agent_definition_id)
        return {"files": files, "count": len(files), "scope_kind": scope_kind, "scope_ref": scope_ref}

    return _handler


def _build_read_memory_file_handler(store: MemoryFileStore):
    def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
        scope_kind, scope_ref, agent_definition_id = _memory_tool_scope(arguments)
        return store.read_file(
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            agent_definition_id=agent_definition_id,
            path=str(arguments.get("path") or "MEMORY.md"),
        )

    return _handler


def _build_write_memory_file_handler(store: MemoryFileStore):
    def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
        scope_kind, scope_ref, agent_definition_id = _memory_tool_scope(arguments)
        return store.write_file(
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            agent_definition_id=agent_definition_id,
            path=str(arguments.get("path") or "MEMORY.md"),
            content=str(arguments.get("content") or ""),
            mode=str(arguments.get("mode") or "overwrite"),
        )

    return _handler


def _build_delete_memory_file_handler(store: MemoryFileStore):
    def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
        scope_kind, scope_ref, agent_definition_id = _memory_tool_scope(arguments)
        return store.delete_file(
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            agent_definition_id=agent_definition_id,
            path=str(arguments.get("path") or ""),
        )

    return _handler


def _memory_tool_scope(arguments: dict[str, Any]) -> tuple[str, str, str | None]:
    scope_kind = str(arguments.get("scope_kind") or arguments.get("scopeKind") or "").strip()
    scope_ref = str(arguments.get("scope_ref") or arguments.get("scopeRef") or "").strip()
    if not scope_kind or not scope_ref:
        raise ValueError("memory tools require scope_kind and scope_ref")
    agent_definition_id = (
        arguments.get("agent_definition_id")
        or arguments.get("agentDefinitionId")
        or arguments.get("agent_definition_id")
        or arguments.get("agentDefinitionId")
    )
    return scope_kind, scope_ref, str(agent_definition_id) if agent_definition_id else None


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
    download_attribution: LocalDownloadAttributionService,
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
        if is_scene_context_tool(tool):
            scene_registry.register(tool.clone())
            continue
        if is_approval_tool(tool):
            parent_registry.register(tool.clone())
            continue
        parent_registry.register(tool.clone())

    mcp_registry_tools = ToolRegistry()
    mcp_registry.register_enabled_runtime_tools(mcp_registry_tools)
    for tool in mcp_registry_tools.tools.values():
        if is_scene_context_tool(tool):
            scene_registry.register(tool.clone())
            continue
        parent_registry.register(tool.clone())

    _register_local_download_attribution_tools(scene_registry, download_attribution)
    return parent_registry, scene_registry


def _register_local_download_attribution_tools(
    tool_registry: ToolRegistry,
    download_attribution: LocalDownloadAttributionService,
) -> None:
    if not tool_registry.has("local_download_create_attempt"):
        tool_registry.register(
            ToolDefinition(
                name="local_download_create_attempt",
                description=(
                    "Create a local download attribution attempt before HID clicks a download affordance. "
                    "Records candidate/source evidence, startedAt, and a snapshot of the local download directory."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "candidate": {"type": "object"},
                        "sourceUrl": {"type": "string"},
                        "source_url": {"type": "string"},
                        "href": {"type": "string"},
                        "download": {"type": "string"},
                        "expectedFileName": {"type": "string"},
                        "expected_file_name": {"type": "string"},
                        "startedAt": {"type": "string"},
                        "started_at": {"type": "string"},
                        "downloadDirectory": {"type": "string"},
                        "download_directory": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                handler=download_attribution.create_attempt,
                category="scene",
                metadata={"capabilities": ["scene", "download", "document"], "real_environment": True},
            )
        )
    if not tool_registry.has("local_download_attribute"):
        tool_registry.register(
            ToolDefinition(
                name="local_download_attribute",
                description=(
                    "Attribute a completed local file to a prior downloadAttemptId after HID triggers a browser download. "
                    "Returns status completed, timeout, or ambiguous."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "downloadAttemptId": {"type": "string"},
                        "download_attempt_id": {"type": "string"},
                        "timeoutMs": {"type": "integer"},
                        "timeout_ms": {"type": "integer"},
                        "pollIntervalMs": {"type": "integer"},
                        "poll_interval_ms": {"type": "integer"},
                    },
                    "required": ["downloadAttemptId"],
                    "additionalProperties": False,
                },
                handler=download_attribution.attribute_attempt,
                category="scene",
                metadata={"capabilities": ["scene", "download", "document"], "real_environment": True},
            )
        )


def _register_delegate_scene_context_tool(
    tool_registry: ToolRegistry,
    *,
    scene_context_service: SceneContextService,
) -> None:
    tool_registry.register(build_delegate_scene_context_tool(scene_context_service.delegate))


def _seed_builtin_agent_definitions(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repo = AgentDefinitionRepository(session)
        definition = repo.primary() or repo.by_definition_key("recruit-station")
        if definition is None:
            repo.create(_default_agent_definition())
            return

        updates: dict[str, Any] = {}
        if not definition.is_primary:
            updates["is_primary"] = True
        original_prompt_config = dict(definition.prompt_config or {})
        prompt_config = normalize_prompt_config(original_prompt_config)
        resolved_context_policy = resolve_context_policy(prompt_config)
        if prompt_config != original_prompt_config:
            updates["prompt_config"] = prompt_config
        if prompt_config.get("context_policy") != resolved_context_policy:
            prompt_config["context_policy"] = resolved_context_policy
            updates["prompt_config"] = prompt_config
        resolved_memory_policy = resolve_memory_policy(definition.memory_policy)
        if resolved_memory_policy != dict(definition.memory_policy or {}):
            updates["memory_policy"] = resolved_memory_policy
        default_definition = _default_agent_definition()
        for key in ("product_bindings", "product_config", "product_projections"):
            existing_value = dict(getattr(definition, key) or {})
            merged_value = _merge_missing_default_config(existing_value, dict(default_definition[key]))
            if key == "product_config":
                merged_value = _refresh_builtin_product_prompt_config(merged_value)
            if merged_value != existing_value:
                updates[key] = merged_value
        metadata = dict(definition.agent_metadata or {})
        metadata.update({"supports_builtin_agents": True, "current_primary_definition": "recruit-station"})
        if metadata != dict(definition.agent_metadata or {}):
            updates["agent_metadata"] = metadata
        if updates:
            repo.update(definition, updates)


def _default_agent_definition() -> dict[str, Any]:
    return default_agent_definition()


def _merge_missing_default_config(existing: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = deepcopy(value)
            continue
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge_missing_default_config(dict(merged[key]), value)
    return merged
