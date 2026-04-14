from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .models import ToolExecutionResult

EXECUTION_CONTROL_CAPABILITIES = [
    "analyze",
    "browser",
    "search",
    "http",
    "document",
    "filesystem",
    "api",
    "command",
    "llm",
    "approval",
]


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
    metadata: dict[str, Any] = field(default_factory=dict)

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
        if tool_name not in self.tools:
            raise ToolExecutionError(f"Unknown tool: {tool_name}")
        tool = self.tools[tool_name]
        payload = dict(arguments or {})
        try:
            output = tool.handler(payload)
            return ToolExecutionResult(
                tool_name=tool_name,
                output=output,
                is_error=False,
                arguments=payload,
                metadata=dict(tool.metadata or {}),
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            return ToolExecutionResult(
                tool_name=tool_name,
                output=str(exc),
                is_error=True,
                arguments=payload,
                metadata=dict(tool.metadata or {}),
            )

    def build_result_submission_tool(self, name: str = "submit_result") -> ToolDefinition:
        def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
            return {"accepted": True, "payload": arguments}

        return ToolDefinition(
            name=name,
            description="Submit a structured task result.",
            parameters={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "data": {"type": "object"},
                },
                "required": ["status"],
                "additionalProperties": True,
            },
            handler=_handler,
            metadata={
                "terminal_result_submission": True,
                "capabilities": ["document", "llm"],
            },
        )

    def build_observation_tool(self, name: str = "record_observation") -> ToolDefinition:
        def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
            return {"accepted": True, "payload": arguments}

        return ToolDefinition(
            name=name,
            description="Record a structured observation about the current runtime scene, evidence, or step outcome.",
            parameters={
                "type": "object",
                "properties": {
                    "step_id": {"type": "string"},
                    "capability": {"type": "string"},
                    "summary": {"type": "string"},
                    "signals": {"type": "array", "items": {"type": "string"}},
                    "evidence": {},
                    "scene_update": {"type": "object"},
                },
                "required": ["summary"],
                "additionalProperties": True,
            },
            handler=_handler,
            metadata={
                "observation_capture": True,
                "executor_observation_submission": True,
                "capabilities": list(EXECUTION_CONTROL_CAPABILITIES),
            },
        )

    def build_plan_progress_tool(self, name: str = "advance_plan_step") -> ToolDefinition:
        def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
            return {"accepted": True, "payload": arguments}

        return ToolDefinition(
            name=name,
            description="Record progress for a plan step, including completion, skip, or blocked state.",
            parameters={
                "type": "object",
                "properties": {
                    "step_id": {"type": "string"},
                    "status": {"type": "string"},
                    "capability": {"type": "string"},
                    "summary": {"type": "string"},
                    "artifacts": {"type": "object"},
                },
                "required": ["step_id", "status"],
                "additionalProperties": True,
            },
            handler=_handler,
            metadata={
                "plan_progress": True,
                "executor_step_completion": True,
                "capabilities": list(EXECUTION_CONTROL_CAPABILITIES),
            },
        )

    def build_step_completion_tool(self, name: str = "advance_plan_step") -> ToolDefinition:
        return self.build_plan_progress_tool(name=name)

    def build_replan_request_tool(self, name: str = "request_replan") -> ToolDefinition:
        def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
            return {"accepted": True, "payload": arguments}

        return ToolDefinition(
            name=name,
            description="Request a plan revision because the current scene, evidence, or tool results diverged from the active execution plan.",
            parameters={
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "step_id": {"type": "string"},
                    "blockers": {"type": "array", "items": {"type": "string"}},
                    "preferred_capabilities": {"type": "array", "items": {"type": "string"}},
                    "suggested_steps": {"type": "array", "items": {"type": "object"}},
                    "scene_update": {"type": "object"},
                },
                "required": ["reason"],
                "additionalProperties": True,
            },
            handler=_handler,
            metadata={
                "replan_request": True,
                "executor_replan_request": True,
                "capabilities": list(EXECUTION_CONTROL_CAPABILITIES),
            },
        )

    def build_human_checkpoint_tool(self, name: str = "request_human_checkpoint") -> ToolDefinition:
        def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
            return {"accepted": True, "payload": arguments}

        return ToolDefinition(
            name=name,
            description="Pause execution and request a human checkpoint for approval, verification, or operator takeover.",
            parameters={
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "step_id": {"type": "string"},
                    "review_kind": {"type": "string"},
                    "summary": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["reason"],
                "additionalProperties": True,
            },
            handler=_handler,
            metadata={
                "human_checkpoint": True,
                "requires_approval": True,
                "capabilities": list(EXECUTION_CONTROL_CAPABILITIES),
            },
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
        selected = [
            tool
            for tool in candidates
            if tool.name in preferred or tool.metadata.get("terminal_result_submission")
        ]
        return selected or candidates
