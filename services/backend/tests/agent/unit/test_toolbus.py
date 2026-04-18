from __future__ import annotations

import asyncio

from scene_pilot.runtime.tools import ToolDefinition, ToolRegistry, register_core_tools
from scene_pilot.runtime.models import CancellationToken


async def _run_async(tool_registry: ToolRegistry, tool_name: str, arguments: dict[str, object], token: CancellationToken | None = None):
    return await tool_registry.execute_async(tool_name, arguments, cancel_token=token)


def test_toolbus_executes_async_and_sync_tools_and_merges_sources() -> None:
    registry = ToolRegistry()

    async def _async_handler(arguments: dict[str, object], *, cancel_token: CancellationToken | None = None) -> dict[str, object]:
        assert cancel_token is not None
        return {"echo": arguments, "cancelled": cancel_token.cancelled}

    registry.register(
        ToolDefinition(
            name="core.echo",
            description="Echo content.",
            parameters={"type": "object"},
            handler=_async_handler,
            category="core",
            external_target=False,
            resource_target_kind="memory",
        )
    )
    register_core_tools(registry)

    plugin_registry = ToolRegistry()
    plugin_registry.register(
        ToolDefinition(
            name="plugin.note",
            description="Record note.",
            parameters={"type": "object"},
            handler=lambda arguments: {"noted": arguments.get("note")},
            category="plugin",
            external_target=False,
            resource_target_kind="candidate",
        )
    )
    registry.merge(plugin_registry)

    token = CancellationToken()
    result = asyncio.run(_run_async(registry, "core.echo", {"value": 1}, token))
    plugin_result = asyncio.run(_run_async(registry, "plugin.note", {"note": "hello"}))

    assert result.is_error is False
    assert result.output == {"echo": {"value": 1}, "cancelled": False}
    assert plugin_result.output == {"noted": "hello"}
    assert registry.tools["core.echo"].category == "core"
    assert registry.tools["plugin.note"].resource_target_kind == "candidate"
    assert "read_memory" in registry.tools
