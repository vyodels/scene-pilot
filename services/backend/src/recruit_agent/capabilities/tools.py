# mypy: ignore-errors
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Awaitable, Callable, Protocol, TypeVar

_T = TypeVar("_T")


class ToolExecutionError(RuntimeError):
    pass


class ToolHandler(Protocol):
    def __call__(self, arguments: dict[str, Any]) -> Any: ...


@dataclass(slots=True)
class ToolExecutionResult:
    tool_name: str
    output: Any
    is_error: bool = False
    arguments: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_message_content(self) -> str:
        if isinstance(self.output, str):
            return self.output
        return json.dumps(self.output, ensure_ascii=False, sort_keys=True, default=str)


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    category: str = "core"
    external_target: bool = False
    resource_target_kind: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def clone(self) -> "ToolDefinition":
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=deepcopy(self.parameters),
            handler=self.handler,
            category=self.category,
            external_target=self.external_target,
            resource_target_kind=self.resource_target_kind,
            metadata=deepcopy(self.metadata),
        )

    def to_provider_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, ToolDefinition] = field(default_factory=dict)

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self.tools:
            raise ToolExecutionError(f"Tool already registered: {tool.name}")
        self.tools[tool.name] = tool

    def has(self, tool_name: str) -> bool:
        return tool_name in self.tools

    def merge(self, other: "ToolRegistry") -> None:
        for tool in other.tools.values():
            self.register(tool)

    def filtered(self, predicate: Callable[[ToolDefinition], bool]) -> "ToolRegistry":
        registry = ToolRegistry()
        for tool in self.tools.values():
            if predicate(tool):
                registry.register(tool.clone())
        return registry

    def describe(
        self,
        *,
        capabilities: list[str] | None = None,
        preferred_tool_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            tool.to_provider_spec()
            for tool in self._select_tools(capabilities=capabilities, preferred_tool_names=preferred_tool_names)
        ]

    def to_agent_runtime_tools(self) -> list[Any]:
        from recruit_agent.agent_runtime.types import (
            ToolCall as AgentRuntimeToolCall,
            ToolDefinition as AgentRuntimeToolDefinition,
            ToolResult as AgentRuntimeToolResult,
            ToolSchema,
            TurnContext,
        )

        registry = self

        @dataclass(slots=True)
        class _Handler:
            tool: ToolDefinition

            def handle(self, call: AgentRuntimeToolCall, context: TurnContext) -> AgentRuntimeToolResult:
                result = registry.execute(self.tool.name, dict(call.input or {}))
                return AgentRuntimeToolResult(
                    tool_call_id=call.id,
                    tool_use_id=call.tool_use_id,
                    name=call.name,
                    content=result.output,
                    is_error=result.is_error,
                    metadata=result.metadata,
                )

        return [
            AgentRuntimeToolDefinition(
                name=tool.name,
                description=tool.description,
                schema=ToolSchema(
                    name=tool.name,
                    description=tool.description,
                    input_schema=deepcopy(tool.parameters),
                ),
                handler=_Handler(tool),
                metadata={
                    **deepcopy(tool.metadata),
                    "category": tool.category,
                    "external_target": tool.external_target,
                    "resource_target_kind": tool.resource_target_kind,
                },
            )
            for tool in self.tools.values()
        ]

    def capability_tool_names(self, capability: str) -> list[str]:
        normalized = capability.strip().lower()
        names: list[str] = []
        for tool in self.tools.values():
            tool_capabilities = {
                str(item).strip().lower()
                for item in list(tool.metadata.get("capabilities") or [])
                if str(item).strip()
            }
            if normalized in tool_capabilities or tool.metadata.get("terminal_result_submission"):
                names.append(tool.name)
        return names

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        return run_awaitable_blocking(lambda: self.execute_async(tool_name, arguments))

    async def execute_async(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        if tool_name not in self.tools:
            raise ToolExecutionError(f"Unknown tool: {tool_name}")
        tool = self.tools[tool_name]
        payload = dict(arguments or {})
        try:
            output = _invoke_handler(tool.handler, payload)
            if inspect.isawaitable(output):
                output = await output
            return ToolExecutionResult(
                tool_name=tool_name,
                output=output,
                is_error=False,
                arguments=payload,
                metadata=_tool_metadata(tool),
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            return ToolExecutionResult(
                tool_name=tool_name,
                output=str(exc),
                is_error=True,
                arguments=payload,
                metadata=_tool_metadata(tool),
            )

    def build_system_command_tool(
        self,
        handler: ToolHandler,
        *,
        name: str = "request_system_command",
    ) -> ToolDefinition:
        return ToolDefinition(
            name=name,
            description="Request a whitelisted system command via desktop approval. Execution is disabled by default.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "rationale": {"type": "string"},
                    "requested_by": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            handler=handler,
            metadata={
                "requires_approval": True,
                "feature_flag": "skills.system_command",
                "execution_enabled": False,
                "capabilities": ["command", "approval"],
            },
        )

    def _select_tools(
        self,
        *,
        capabilities: list[str] | None = None,
        preferred_tool_names: list[str] | None = None,
    ) -> list[ToolDefinition]:
        if not capabilities:
            candidates = list(self.tools.values())
        else:
            normalized = {str(item).strip().lower() for item in capabilities if str(item).strip()}
            candidates: list[ToolDefinition] = []
            for tool in self.tools.values():
                tool_capabilities = {
                    str(item).strip().lower()
                    for item in list(tool.metadata.get("capabilities") or [])
                    if str(item).strip()
                }
                if not tool_capabilities or normalized & tool_capabilities or tool.metadata.get("terminal_result_submission"):
                    candidates.append(tool)

        if not preferred_tool_names:
            return candidates

        preferred = {str(item).strip() for item in preferred_tool_names if str(item).strip()}
        prioritized = [
            tool
            for tool in candidates
            if tool.name in preferred
        ]
        if not prioritized:
            return candidates
        remaining = [tool for tool in candidates if tool.name not in preferred]
        return [*prioritized, *remaining]


def register_core_tools(
    registry: ToolRegistry,
    *,
    read_memory_handler: ToolHandler | None = None,
    list_memory_files_handler: ToolHandler | None = None,
    read_memory_file_handler: ToolHandler | None = None,
    write_memory_file_handler: ToolHandler | None = None,
    delete_memory_file_handler: ToolHandler | None = None,
    record_learning_handler: ToolHandler | None = None,
) -> None:
    registry.register(
        ToolDefinition(
            name="read_memory",
            description="Read memory entries for a scope.",
            parameters={
                "type": "object",
                "properties": {"scope_kind": {"type": "string"}, "scope_ref": {"type": "string"}},
                "additionalProperties": True,
            },
            handler=read_memory_handler or (lambda arguments: {"accepted": True, "action": "read_memory", "arguments": arguments}),
            category="memory",
            external_target=False,
            resource_target_kind="memory",
            metadata={"capabilities": ["memory", "memory_read"], "permission_scope": "memory_read", "risk_level": "low"},
        )
    )
    memory_file_scope_properties = {
        "scope_kind": {"type": "string"},
        "scope_ref": {"type": "string"},
        "agent_profile_id": {"type": "string"},
    }
    registry.register(
        ToolDefinition(
            name="list_memory_files",
            description="List markdown memory files available inside a memory scope.",
            parameters={
                "type": "object",
                "properties": memory_file_scope_properties,
                "required": ["scope_kind", "scope_ref"],
                "additionalProperties": True,
            },
            handler=list_memory_files_handler
            or (lambda arguments: {"accepted": True, "action": "list_memory_files", "arguments": arguments}),
            category="memory",
            external_target=False,
            resource_target_kind="memory",
            metadata={"capabilities": ["memory", "memory_read"], "permission_scope": "memory_read", "risk_level": "low"},
        )
    )
    registry.register(
        ToolDefinition(
            name="read_memory_file",
            description="Read a markdown memory file inside a memory scope.",
            parameters={
                "type": "object",
                "properties": {**memory_file_scope_properties, "path": {"type": "string", "default": "MEMORY.md"}},
                "required": ["scope_kind", "scope_ref"],
                "additionalProperties": True,
            },
            handler=read_memory_file_handler
            or (lambda arguments: {"accepted": True, "action": "read_memory_file", "arguments": arguments}),
            category="memory",
            external_target=False,
            resource_target_kind="memory",
            metadata={"capabilities": ["memory", "memory_read"], "permission_scope": "memory_read", "risk_level": "low"},
        )
    )
    registry.register(
        ToolDefinition(
            name="write_memory_file",
            description=(
                "Write or append a markdown memory file inside a memory scope. "
                "Use this only for durable user-requested memories or memory maintenance."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **memory_file_scope_properties,
                    "path": {"type": "string", "default": "MEMORY.md"},
                    "content": {"type": "string"},
                    "mode": {"type": "string", "enum": ["overwrite", "append"], "default": "overwrite"},
                },
                "required": ["scope_kind", "scope_ref", "content"],
                "additionalProperties": True,
            },
            handler=write_memory_file_handler
            or (lambda arguments: {"accepted": True, "action": "write_memory_file", "arguments": arguments}),
            category="memory",
            external_target=False,
            resource_target_kind="memory",
            metadata={"capabilities": ["memory", "memory_write"], "permission_scope": "memory_write", "risk_level": "medium"},
        )
    )
    registry.register(
        ToolDefinition(
            name="delete_memory_file",
            description="Delete a markdown memory file inside a memory scope when the user asks to forget it.",
            parameters={
                "type": "object",
                "properties": {**memory_file_scope_properties, "path": {"type": "string"}},
                "required": ["scope_kind", "scope_ref", "path"],
                "additionalProperties": True,
            },
            handler=delete_memory_file_handler
            or (lambda arguments: {"accepted": True, "action": "delete_memory_file", "arguments": arguments}),
            category="memory",
            external_target=False,
            resource_target_kind="memory",
            metadata={"capabilities": ["memory", "memory_write"], "permission_scope": "memory_write", "risk_level": "medium"},
        )
    )
    registry.register(
        ToolDefinition(
            name="record_learning",
            description="Record a learning candidate for evolution.",
            parameters={
                "type": "object",
                "properties": {"kind": {"type": "string"}, "payload": {"type": "object"}},
                "additionalProperties": True,
            },
            handler=record_learning_handler or (lambda arguments: {"accepted": True, "action": "record_learning", "arguments": arguments}),
            category="learning",
            external_target=False,
            resource_target_kind="learning",
        )
    )
    registry.register(
        ToolDefinition(
            name="enqueue_follow_up",
            description="Schedule a follow up task for later execution.",
            parameters={
                "type": "object",
                "properties": {"task_type": {"type": "string"}, "payload": {"type": "object"}},
                "additionalProperties": True,
            },
            handler=lambda arguments: {"accepted": True, "action": "enqueue_follow_up", "arguments": arguments},
            category="core",
            external_target=False,
            resource_target_kind="queue",
        )
    )
    registry.register(
        ToolDefinition(
            name="schedule_self_wakeup",
            description="Request a future wakeup for the current run.",
            parameters={
                "type": "object",
                "properties": {"delay_seconds": {"type": "integer"}, "reason": {"type": "string"}},
                "additionalProperties": True,
            },
            handler=lambda arguments: {"accepted": True, "action": "schedule_self_wakeup", "arguments": arguments},
            category="core",
            external_target=False,
            resource_target_kind="run",
        )
    )


def tool_capabilities(tool: ToolDefinition) -> set[str]:
    return {
        str(item).strip().lower()
        for item in list(tool.metadata.get("capabilities") or [])
        if str(item).strip()
    }


def is_approval_tool(tool: ToolDefinition) -> bool:
    capabilities = tool_capabilities(tool)
    return "approval" in capabilities or bool(tool.metadata.get("requires_confirmation"))


def is_scene_context_tool(tool: ToolDefinition) -> bool:
    capabilities = tool_capabilities(tool)
    if "scene" in capabilities:
        return True
    if not (
        tool.external_target
        or bool(tool.metadata.get("external_tool"))
        or bool(tool.metadata.get("real_environment"))
    ):
        return False
    return bool(capabilities & {"browser", "document", "search", "computer", "computer_read", "computer_write"})


def build_delegate_scene_context_tool(
    handler: ToolHandler,
    *,
    name: str = "delegate_scene_context",
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Delegate a capability-oriented runtime scene task to an isolated scene context and return a structured scene result.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "instruction": {"type": "string"},
                "success_criteria": {"type": "object"},
                "output_contract": {
                    "type": "object",
                    "description": "Expected structured result. Put artifact_expectations here when local files matter; browser downloads should first be located through browser_locate_download before business path/format verification. For browser-managed downloads, a located complete record with exists/path/fileName/extension or mime/source correlation is valid path/format evidence. If a download affordance is selected, preserve browser-derived sourceUrl/href, expected filename, finalUrl/referrer hints, and startedAfter when available. When a local artifact is located, return it in result_data.artifact plus result_data.browser_download and include business_writeback arguments suitable for the later business tool such as attach_resume_artifact.",
                },
                "preferred_capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "environment_requirements": {
                    "type": "object",
                    "description": "Scene prerequisites and stable targets such as browser_target, computer_target, target_regions, and action_plan. Put these as structured fields here instead of embedding pseudo-JSON in instruction prose.",
                },
                "browser_target": {
                    "type": "object",
                    "description": "Optional top-level shortcut for the browser target; equivalent to environment_requirements.browser_target. When the operator goal or current contract includes an explicit web target URL, preserve it here as browser_target.url and derive host from that URL/browser evidence so stale tabs on a different origin are rejected.",
                },
                "computer_target": {
                    "type": "object",
                    "description": "Optional top-level shortcut for the computer/HID target; equivalent to environment_requirements.computer_target.",
                },
                "target_regions": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional top-level shortcut for candidate landing regions; equivalent to environment_requirements.target_regions.",
                },
                "action_plan": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional top-level shortcut for intent-level scene actions; equivalent to environment_requirements.action_plan. Download actions may include download_source with source_url/sourceUrl/href, expected_filename/fileName/download, started_after/startedAfter, final_url/finalUrl, or referrer fields copied from browser evidence.",
                },
                "artifact_expectations": {
                    "type": "object",
                    "description": "Optional top-level shortcut for artifact expectations; equivalent to output_contract.artifact_expectations. For browser downloads, include download_lookup/source_url/expected_filename/started_after when available so browser_locate_download can correlate the local file with the clicked link.",
                },
                "approval_policy": {"type": "object"},
                "input": {"type": "object"},
                "context": {
                    "type": "object",
                    "description": "Episode-scoped scene context, including browser/computer targets, candidate landing regions, action intent, and artifact_expectations. Use structured fields, not site-specific hardcoded flow.",
                },
                "requested_by": {"type": "string"},
                "max_llm_invocations": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional explicit safety budget for this delegated scene. Only set it when the operator/test request explicitly provides a finite budget; otherwise omit it so the scene runs until terminal outcome, cancellation, or human boundary.",
                },
            },
            "required": ["instruction"],
            "additionalProperties": True,
        },
        handler=handler,
        category="scene",
        external_target=False,
        resource_target_kind="execution_episode",
        metadata={"capabilities": ["scene", "scene_delegate"]},
    )


def _tool_metadata(tool: ToolDefinition) -> dict[str, Any]:
    metadata = dict(tool.metadata or {})
    metadata.setdefault("category", tool.category)
    metadata.setdefault("external_target", tool.external_target)
    metadata.setdefault("resource_target_kind", tool.resource_target_kind)
    return metadata


def _invoke_handler(
    handler: ToolHandler,
    arguments: dict[str, Any],
) -> Any:
    return handler(arguments)


def run_awaitable_blocking(factory: Callable[[], Awaitable[_T]]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    # Nested scene execution can enter synchronous runtime code while an event
    # loop is already active. Run the coroutine on an isolated loop instead of
    # calling asyncio.run() recursively in the same thread.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()
