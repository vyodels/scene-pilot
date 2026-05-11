from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from recruit_agent.runtime.tools import ToolDefinition as LegacyToolDefinition

from .types import ToolCall, ToolDefinition, ToolResult, ToolSchema, TurnContext


@dataclass(slots=True)
class LegacyToolHandler:
    tool: LegacyToolDefinition

    def handle(self, call: ToolCall, context: TurnContext) -> ToolResult:
        try:
            output = self.tool.handler(dict(call.input or {}))
            return ToolResult(
                tool_call_id=call.id,
                tool_use_id=call.tool_use_id,
                name=call.name,
                content=output,
                is_error=False,
                metadata=dict(self.tool.metadata or {}),
            )
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                tool_use_id=call.tool_use_id,
                name=call.name,
                content=str(exc),
                is_error=True,
                metadata=dict(self.tool.metadata or {}),
            )


def tool_from_legacy(tool: LegacyToolDefinition) -> ToolDefinition:
    return ToolDefinition(
        name=tool.name,
        description=tool.description,
        schema=ToolSchema(name=tool.name, description=tool.description, input_schema=dict(tool.parameters or {})),
        handler=LegacyToolHandler(tool),
        metadata={
            **dict(tool.metadata or {}),
            "category": tool.category,
            "external_target": tool.external_target,
            "resource_target_kind": tool.resource_target_kind,
        },
    )


def tools_from_legacy(tools: Any) -> list[ToolDefinition]:
    values = getattr(tools, "tools", tools)
    if isinstance(values, dict):
        iterable = values.values()
    else:
        iterable = values
    return [tool_from_legacy(tool) for tool in iterable]
