from __future__ import annotations

import asyncio

from recruit_agent.runtime.tools import ToolDefinition, ToolRegistry, build_delegate_scene_context_tool, is_scene_context_tool, register_core_tools
from recruit_agent.agent_runtime.models import CancellationToken


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


def test_toolbus_sync_execute_works_inside_running_event_loop() -> None:
    registry = ToolRegistry()
    token = CancellationToken()

    async def _async_handler(arguments: dict[str, object], *, cancel_token: CancellationToken | None = None) -> dict[str, object]:
        assert cancel_token is token
        return {"echo": arguments}

    registry.register(
        ToolDefinition(
            name="core.echo",
            description="Echo content.",
            parameters={"type": "object"},
            handler=_async_handler,
        )
    )

    async def _scenario():
        return registry.execute("core.echo", {"value": 1}, cancel_token=token)

    result = asyncio.run(_scenario())

    assert result.is_error is False
    assert result.output == {"echo": {"value": 1}}


def test_register_core_tools_supports_custom_invoke_skill_handler() -> None:
    registry = ToolRegistry()
    register_core_tools(
        registry,
        invoke_skill_handler=lambda arguments: {
            "skill_id": arguments.get("skill_id"),
            "executor_mode": "python_inline",
            "result": {"status": "completed"},
        },
    )

    result = asyncio.run(_run_async(registry, "invoke_skill", {"skill_id": "demo", "input": {}}))

    assert result.is_error is False
    assert result.output["skill_id"] == "demo"
    assert result.output["executor_mode"] == "python_inline"


def test_scene_context_tool_detection_covers_computer_capabilities() -> None:
    browser_like = ToolDefinition(
        name="hid.semantic_action",
        description="Computer action",
        parameters={"type": "object"},
        handler=lambda arguments: arguments,
        metadata={"external_tool": True, "real_environment": True, "capabilities": ["computer", "computer_write"]},
    )

    assert is_scene_context_tool(browser_like) is True


def test_delegate_scene_context_tool_schema_mentions_browser_computer_contracts() -> None:
    tool = build_delegate_scene_context_tool(lambda arguments: arguments)
    properties = tool.parameters["properties"]

    assert "artifact_expectations" in properties["output_contract"]["description"]
    assert "browser_locate_download" in properties["output_contract"]["description"]
    assert "business_writeback" in properties["output_contract"]["description"]
    assert "attach_resume_artifact" in properties["output_contract"]["description"]
    assert "browser_target" in properties["environment_requirements"]["description"]
    assert "structured fields" in properties["environment_requirements"]["description"]
    assert "browser_target" in properties
    assert "artifact_expectations" in properties
    assert "candidate landing regions" in properties["context"]["description"]
