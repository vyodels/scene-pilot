# mypy: ignore-errors
from __future__ import annotations

import asyncio
from copy import deepcopy
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .models import CancellationToken, ToolExecutionResult


class ToolExecutionError(RuntimeError):
    pass


class ToolHandler(Protocol):
    def __call__(self, arguments: dict[str, Any]) -> Any: ...


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

    def execute(self, tool_name: str, arguments: dict[str, Any] | None = None) -> ToolExecutionResult:
        return asyncio.run(self.execute_async(tool_name, arguments))

    async def execute_async(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> ToolExecutionResult:
        if tool_name not in self.tools:
            raise ToolExecutionError(f"Unknown tool: {tool_name}")
        tool = self.tools[tool_name]
        payload = dict(arguments or {})
        try:
            output = _invoke_handler(tool.handler, payload, cancel_token=cancel_token)
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


def register_core_tools(registry: ToolRegistry, *, invoke_skill_handler: ToolHandler | None = None) -> None:
    registry.register(
        ToolDefinition(
            name="read_memory",
            description="Read memory entries for a scope.",
            parameters={
                "type": "object",
                "properties": {"scope_kind": {"type": "string"}, "scope_ref": {"type": "string"}},
                "additionalProperties": True,
            },
            handler=lambda arguments: {"accepted": True, "action": "read_memory", "arguments": arguments},
            category="core",
            external_target=False,
            resource_target_kind="memory",
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
            handler=lambda arguments: {"accepted": True, "action": "record_learning", "arguments": arguments},
            category="core",
            external_target=False,
            resource_target_kind="memory",
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
    registry.register(
        ToolDefinition(
            name="invoke_skill",
            description="Invoke a registered skill by identifier.",
            parameters={
                "type": "object",
                "properties": {"skill_id": {"type": "string"}, "input": {"type": "object"}},
                "additionalProperties": True,
            },
            handler=invoke_skill_handler or (lambda arguments: {"accepted": True, "action": "invoke_skill", "arguments": arguments}),
            category="skill",
            external_target=False,
            resource_target_kind="skill",
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
    return bool(capabilities & {"browser", "document", "search"})


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
                "output_contract": {"type": "object"},
                "preferred_capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "environment_requirements": {"type": "object"},
                "approval_policy": {"type": "object"},
                "input": {"type": "object"},
                "context": {"type": "object"},
                "requested_by": {"type": "string"},
                "max_rounds": {"type": "integer", "minimum": 1, "maximum": 32},
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
    *,
    cancel_token: CancellationToken | None = None,
) -> Any:
    parameters = inspect.signature(handler).parameters
    if "cancel_token" in parameters:
        return handler(arguments, cancel_token=cancel_token)
    return handler(arguments)
