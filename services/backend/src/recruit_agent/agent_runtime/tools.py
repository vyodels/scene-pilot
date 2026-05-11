from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .types import ToolCall, ToolDefinition, ToolHandler, ToolResult, ToolSchema, TurnContext


@dataclass(slots=True)
class FunctionToolHandler(ToolHandler):
    fn: Callable[[dict[str, Any]], Any]

    def handle(self, call: ToolCall, context: TurnContext) -> ToolResult:
        try:
            return ToolResult(
                tool_call_id=call.id,
                tool_use_id=call.tool_use_id,
                name=call.name,
                content=self.fn(dict(call.input or {})),
                is_error=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                tool_use_id=call.tool_use_id,
                name=call.name,
                content=str(exc),
                is_error=True,
            )


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, ToolDefinition] = field(default_factory=dict)

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self.tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self.tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        try:
            return self.tools[name]
        except KeyError as exc:
            raise ValueError(f"Unknown tool: {name}") from exc

    def schemas(self) -> list[ToolSchema]:
        return [tool.schema for tool in self.tools.values()]

    @classmethod
    def from_tools(cls, tools: list[ToolDefinition]) -> "ToolRegistry":
        registry = cls()
        for tool in tools:
            registry.register(tool)
        return registry
