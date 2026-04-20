from __future__ import annotations

from typing import Any

from scene_pilot.core.settings import AppSettings
from scene_pilot.models.domain import McpTool
from scene_pilot.services.container import AppContainer


def test_container_build_and_reload_register_enabled_dynamic_mcp_tools(tmp_path, monkeypatch) -> None:
    discovered_tools = [
        {
            "name": "dynamic_echo",
            "description": "Echo back the payload.",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        }
    ]
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        assert server.endpoint == "mcp://dynamic-runtime"
        return discovered_tools

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        return {
            "tool": tool_name,
            "echoed": dict(arguments),
            "source": server.endpoint,
        }

    monkeypatch.setattr("scene_pilot.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("scene_pilot.services.mcp_registry._mcp_call_tool", fake_call_tool)

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-runtime-regression.db'}",
        provider_config={},
    )

    container = AppContainer.build(settings)
    rebuilt: AppContainer | None = None
    try:
        assert "dynamic_echo" not in container.tool_registry.tools

        created = container.mcp_registry.create_server(
            {
                "server_key": "dynamic-mcp",
                "name": "Dynamic MCP",
                "transport_kind": "unix_socket",
                "protocol": "mcp_jsonrpc",
                "endpoint": "mcp://dynamic-runtime",
                "enabled": True,
                "auth_config": {},
                "server_metadata": {},
                "tools": [],
            }
        )
        assert [tool["name"] for tool in created["tools"]] == ["dynamic_echo"]
        assert "dynamic_echo" not in container.kernel.tool_registry.tools

        container.reload_settings(container.settings)

        assert container.kernel.tool_registry is container.tool_registry
        assert "dynamic_echo" in container.tool_registry.tools
        assert "dynamic_echo" in container.kernel.tool_registry.tools

        executed = container.kernel.tool_registry.execute("dynamic_echo", {"text": "reload path"})
        assert executed.is_error is False
        assert executed.output == {
            "tool": "dynamic_echo",
            "echoed": {"text": "reload path"},
            "source": "mcp://dynamic-runtime",
        }

        rebuilt = AppContainer.build(settings)
        assert rebuilt.kernel.tool_registry is rebuilt.tool_registry
        assert "dynamic_echo" in rebuilt.tool_registry.tools
        assert "dynamic_echo" in rebuilt.kernel.tool_registry.tools

        rebuilt_result = rebuilt.tool_registry.execute("dynamic_echo", {"text": "build path"})
        assert rebuilt_result.is_error is False
        assert rebuilt_result.output == {
            "tool": "dynamic_echo",
            "echoed": {"text": "build path"},
            "source": "mcp://dynamic-runtime",
        }

        assert tool_calls == [
            ("mcp://dynamic-runtime", "dynamic_echo", {"text": "reload path"}),
            ("mcp://dynamic-runtime", "dynamic_echo", {"text": "build path"}),
        ]
    finally:
        pass


def test_dynamic_mcp_tool_handler_survives_healthcheck_resync(tmp_path, monkeypatch) -> None:
    discovered_tools = [
        {
            "name": "dynamic_echo",
            "description": "Echo back the payload.",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        }
    ]
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        assert server.endpoint == "mcp://dynamic-runtime"
        return discovered_tools

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        return {
            "tool": tool_name,
            "echoed": dict(arguments),
            "source": server.endpoint,
        }

    monkeypatch.setattr("scene_pilot.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("scene_pilot.services.mcp_registry._mcp_call_tool", fake_call_tool)

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-runtime-healthcheck.db'}",
        provider_config={},
    )

    container = AppContainer.build(settings)

    created = container.mcp_registry.create_server(
        {
            "server_key": "dynamic-mcp",
            "name": "Dynamic MCP",
            "transport_kind": "unix_socket",
            "protocol": "mcp_jsonrpc",
            "endpoint": "mcp://dynamic-runtime",
            "enabled": True,
            "auth_config": {},
            "server_metadata": {},
            "tools": [],
        }
    )
    container.reload_settings(container.settings)

    with container.session_factory() as session:
        original_tool_id = next(item.id for item in session.query(McpTool).all() if item.name == "dynamic_echo")

    checked = container.mcp_registry.healthcheck_server(created["id"])
    assert checked["health_status"] == "healthy"

    with container.session_factory() as session:
        refreshed_tool_id = next(item.id for item in session.query(McpTool).all() if item.name == "dynamic_echo")

    assert refreshed_tool_id != original_tool_id

    executed = container.kernel.tool_registry.execute("dynamic_echo", {"text": "after healthcheck"})
    assert executed.is_error is False
    assert executed.output == {
        "tool": "dynamic_echo",
        "echoed": {"text": "after healthcheck"},
        "source": "mcp://dynamic-runtime",
    }
    assert tool_calls == [
        ("mcp://dynamic-runtime", "dynamic_echo", {"text": "after healthcheck"}),
    ]
