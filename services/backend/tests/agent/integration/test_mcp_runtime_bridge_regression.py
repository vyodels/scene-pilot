from __future__ import annotations

from typing import Any

import pytest

from recruit_agent.core.settings import AppSettings
from recruit_agent.models.domain import McpServer, McpTool
from recruit_agent.services.container import AppContainer
from recruit_agent.services.mcp_registry import McpBridgeError, _reset_browser_hid_sequence_state_for_tests


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

    monkeypatch.setattr("recruit_agent.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_agent.services.mcp_registry._mcp_call_tool", fake_call_tool)

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-runtime-regression.db'}",
        provider_config={},
    )

    container = AppContainer.build(settings)
    rebuilt: AppContainer | None = None
    try:
        assert "dynamic_echo" not in container.tool_registry.tools
        assert "dynamic_echo" not in container.scene_context_tool_registry.tools

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
        assert "dynamic_echo" not in container.scene_context_tool_registry.tools

        container.reload_settings(container.settings)

        assert container.kernel.tool_registry is container.tool_registry
        assert "dynamic_echo" in container.tool_registry.tools
        assert "dynamic_echo" in container.kernel.tool_registry.tools
        assert "dynamic_echo" not in container.scene_context_tool_registry.tools

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
        assert "dynamic_echo" not in rebuilt.scene_context_tool_registry.tools

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

    monkeypatch.setattr("recruit_agent.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_agent.services.mcp_registry._mcp_call_tool", fake_call_tool)

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


def test_browser_locate_download_wait_ms_is_clamped_below_stdio_timeout(tmp_path, monkeypatch) -> None:
    discovered_tools = [
        {
            "name": "browser_locate_download",
            "description": "Locate a browser download.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sourceUrl": {"type": "string"},
                    "fileName": {"type": "string"},
                    "waitMs": {"type": "number"},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        }
    ]
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        assert server.endpoint == "mcp://browser-runtime"
        return discovered_tools

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        return {"located": True, "filename": "/tmp/candidate-resume.pdf", "state": "complete"}

    monkeypatch.setattr("recruit_agent.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_agent.services.mcp_registry._mcp_call_tool", fake_call_tool)

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-download-clamp.db'}",
        provider_config={},
    )
    container = AppContainer.build(settings)
    container.mcp_registry.create_server(
        {
            "server_key": "browser",
            "name": "Browser MCP",
            "transport_kind": "stdio",
            "protocol": "mcp_jsonrpc",
            "endpoint": "mcp://browser-runtime",
            "enabled": True,
            "auth_config": {},
            "server_metadata": {
                "stdio_command": ["node", "/virtual/browser-mcp/server.mjs"],
                "runtime_tool_capabilities": {
                    "default": ["browser"],
                    "read_only": ["document"],
                },
            },
            "tools": [],
        }
    )
    container.reload_settings(container.settings)

    result = container.scene_context_tool_registry.execute(
        "browser_locate_download",
        {
            "sourceUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
            "fileName": "candidate-resume.pdf",
            "waitMs": 120_000,
        },
    )

    assert result.is_error is False
    assert result.output["located"] is True
    assert tool_calls == [
        (
            "mcp://browser-runtime",
            "browser_locate_download",
            {
                "sourceUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
                "fileName": "candidate-resume.pdf",
                "waitMs": 5_000,
            },
        )
    ]
    tool_calls.clear()

    result = container.scene_context_tool_registry.execute(
        "browser_locate_download",
        {
            "sourceUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
            "fileName": "candidate-resume.pdf",
        },
    )

    assert result.is_error is False
    assert tool_calls == [
        (
            "mcp://browser-runtime",
            "browser_locate_download",
            {
                "sourceUrl": "https://recruiting.example.test/downloads/candidate-resume.pdf",
                "fileName": "candidate-resume.pdf",
                "waitMs": 5_000,
            },
        )
    ]


def test_browser_hid_runtime_requires_observe_after_substantive_hid_action(tmp_path, monkeypatch) -> None:
    _reset_browser_hid_sequence_state_for_tests()

    browser_tools = [
        {
            "name": "browser_snapshot",
            "description": "Read page snapshot.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "browser_wait_for_text",
            "description": "Wait for text.",
            "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        },
    ]
    hid_tools = [
        {
            "name": "hid_action",
            "description": "Run HID action.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
        }
    ]
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        if server.endpoint == "mcp://browser-runtime":
            return browser_tools
        if server.endpoint == "mcp://hid-runtime":
            return hid_tools
        return []

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        return {"ok": True, "tool": tool_name}

    monkeypatch.setattr("recruit_agent.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_agent.services.mcp_registry._mcp_call_tool", fake_call_tool)

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-browser-hid-sequence.db'}",
        provider_config={},
    )
    container = AppContainer.build(settings)
    container.mcp_registry.create_server(
        {
            "server_key": "browser",
            "name": "Browser MCP",
            "transport_kind": "stdio",
            "protocol": "mcp_jsonrpc",
            "endpoint": "mcp://browser-runtime",
            "enabled": True,
            "auth_config": {},
            "server_metadata": {"runtime_tool_capabilities": {"default": ["browser"], "read_only": ["document"]}},
            "tools": [],
        }
    )
    container.mcp_registry.create_server(
        {
            "server_key": "virtualhid",
            "name": "VirtualHID",
            "transport_kind": "stdio",
            "protocol": "mcp_jsonrpc",
            "endpoint": "mcp://hid-runtime",
            "enabled": True,
            "auth_config": {},
            "server_metadata": {"runtime_tool_capabilities": {"default": ["scene"], "mutating": ["computer_write"]}},
            "tools": [],
        }
    )

    def get_server_tool(server_key: str, tool_name: str) -> tuple[McpServer, McpTool]:
        server = next(item for item in session.query(McpServer).all() if item.server_key == server_key)
        tool = next(item for item in session.query(McpTool).all() if item.server_id == server.id and item.name == tool_name)
        return server, tool

    click_args = {
        "target": {"host": "recruit.example.test", "tabId": 42},
        "context": {"host": "recruit.example.test"},
        "primitives": [{"type": "click", "at": {"x": 160, "y": 80}}],
    }

    with container.session_factory() as session:
        browser_server, snapshot_tool = get_server_tool("browser", "browser_snapshot")
        _, wait_tool = get_server_tool("browser", "browser_wait_for_text")
        hid_server, hid_tool = get_server_tool("virtualhid", "hid_action")

        with pytest.raises(McpBridgeError, match="prior browser observation"):
            container.mcp_registry.invoke_tool(hid_server, hid_tool, click_args)

        container.mcp_registry.invoke_tool(browser_server, snapshot_tool, {})
        container.mcp_registry.invoke_tool(hid_server, hid_tool, click_args)

        with pytest.raises(McpBridgeError, match="followed by a browser observation"):
            container.mcp_registry.invoke_tool(hid_server, hid_tool, click_args)

        container.mcp_registry.invoke_tool(browser_server, wait_tool, {"text": "message sent"})
        container.mcp_registry.invoke_tool(hid_server, hid_tool, click_args)

    assert tool_calls == [
        ("mcp://browser-runtime", "browser_snapshot", {}),
        ("mcp://hid-runtime", "hid_action", click_args),
        ("mcp://browser-runtime", "browser_wait_for_text", {"text": "message sent"}),
        ("mcp://hid-runtime", "hid_action", click_args),
    ]

    _reset_browser_hid_sequence_state_for_tests()
