from __future__ import annotations

from typing import Any

import pytest

from recruit_station.core.settings import AppSettings
from recruit_station.models.domain import McpServer, McpTool
from recruit_station.services.container import AppContainer
from recruit_station.services.mcp_registry import McpBridgeError, _mcp_call_tool, _reset_browser_hid_sequence_state_for_tests


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

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)

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
        assert "dynamic_echo" not in container.autonomous_adapter.tool_registry.tools
        assert "dynamic_echo" not in container.scene_context_tool_registry.tools

        container.reload_settings(container.settings)

        assert container.autonomous_adapter.tool_registry is container.tool_registry
        assert "dynamic_echo" in container.tool_registry.tools
        assert "dynamic_echo" in container.autonomous_adapter.tool_registry.tools
        assert "dynamic_echo" not in container.scene_context_tool_registry.tools

        executed = container.tool_registry.execute("dynamic_echo", {"text": "reload path"})
        assert executed.is_error is False
        assert executed.output == {
            "tool": "dynamic_echo",
            "echoed": {"text": "reload path"},
            "source": "mcp://dynamic-runtime",
        }

        rebuilt = AppContainer.build(settings)
        assert rebuilt.autonomous_adapter.tool_registry is rebuilt.tool_registry
        assert "dynamic_echo" in rebuilt.tool_registry.tools
        assert "dynamic_echo" in rebuilt.autonomous_adapter.tool_registry.tools
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

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)

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

    executed = container.tool_registry.execute("dynamic_echo", {"text": "after healthcheck"})
    assert executed.is_error is False
    assert executed.output == {
        "tool": "dynamic_echo",
        "echoed": {"text": "after healthcheck"},
        "source": "mcp://dynamic-runtime",
    }


def test_browser_runtime_filters_download_and_cookie_tools(tmp_path, monkeypatch) -> None:
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
        },
        {
            "name": "browser_get_cookies",
            "description": "Read browser cookies.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "browser_open_tab",
            "description": "Open a browser tab.",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "additionalProperties": False},
        },
        {
            "name": "browser_snapshot",
            "description": "Read page snapshot.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        },
    ]

    def fake_list_tools(server) -> list[dict[str, Any]]:
        assert server.endpoint == "mcp://browser-runtime"
        return discovered_tools

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)

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

    assert "browser_snapshot" in container.scene_context_tool_registry.tools
    assert "browser_locate_download" not in container.scene_context_tool_registry.tools
    assert "browser_get_cookies" not in container.scene_context_tool_registry.tools
    assert "browser_open_tab" not in container.scene_context_tool_registry.tools


def test_browser_hid_preflight_requires_browser_and_virtualhid_tools(tmp_path, monkeypatch) -> None:
    def fake_list_tools(server) -> list[dict[str, Any]]:
        if server.endpoint == "mcp://browser-runtime":
            return [
                {
                    "name": "browser_snapshot",
                    "description": "Read page snapshot.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                    "annotations": {"readOnlyHint": True},
                }
            ]
        if server.endpoint == "mcp://hid-runtime":
            return [
                {
                    "name": "hid_action",
                    "description": "Run HID action.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
                },
                {
                    "name": "hid_state",
                    "description": "Read HID state.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            ]
        return []

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", lambda _server, _tool_name, _arguments: {"ok": True})
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-browser-hid-preflight.db'}",
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
    blocked = container.mcp_registry.browser_hid_preflight()
    assert blocked["ok"] is False
    assert blocked["missing"] == ["VirtualHID"]

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
    healthy = container.mcp_registry.browser_hid_preflight()
    assert healthy["ok"] is True
    assert healthy["missing"] == []


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
        if tool_name.startswith("browser_"):
            return {"ok": True, "tool": tool_name, "snapshot": {"url": "https://recruit.example.test/jobs"}, "tabId": arguments.get("tabId")}
        return {"ok": True, "tool": tool_name}

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)

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


def test_browser_hid_runtime_sequence_is_scoped_by_run_episode_account_host(tmp_path, monkeypatch) -> None:
    _reset_browser_hid_sequence_state_for_tests()
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        if server.endpoint == "mcp://browser-runtime":
            return [
                {
                    "name": "browser_snapshot",
                    "description": "Read page snapshot.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
                    "annotations": {"readOnlyHint": True},
                }
            ]
        if server.endpoint == "mcp://hid-runtime":
            return [{"name": "hid_action", "description": "Run HID action.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True}}]
        return []

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        if tool_name == "browser_snapshot":
            return {"success": True, "snapshot": {"url": f"https://{arguments['host']}/jobs"}, "run_id": arguments["run_id"], "episode_id": arguments["episode_id"]}
        return {"success": True, "tool": tool_name}

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)
    settings = AppSettings(data_dir=str(tmp_path / "data"), database_url=f"sqlite:///{tmp_path / 'mcp-sequence-scope.db'}", provider_config={})
    container = AppContainer.build(settings)
    for server_key, endpoint, capabilities in (
        ("browser", "mcp://browser-runtime", {"default": ["browser"], "read_only": ["document"]}),
        ("virtualhid", "mcp://hid-runtime", {"default": ["scene"], "mutating": ["computer_write"]}),
    ):
        container.mcp_registry.create_server(
            {
                "server_key": server_key,
                "name": server_key,
                "transport_kind": "stdio",
                "protocol": "mcp_jsonrpc",
                "endpoint": endpoint,
                "enabled": True,
                "auth_config": {},
                "server_metadata": {"runtime_tool_capabilities": capabilities},
                "tools": [],
            }
        )

    with container.session_factory() as session:
        browser_server = next(item for item in session.query(McpServer).all() if item.server_key == "browser")
        hid_server = next(item for item in session.query(McpServer).all() if item.server_key == "virtualhid")
        snapshot_tool = next(item for item in session.query(McpTool).all() if item.server_id == browser_server.id and item.name == "browser_snapshot")
        hid_tool = next(item for item in session.query(McpTool).all() if item.server_id == hid_server.id and item.name == "hid_action")

        scope_a = {"run_id": "run-a", "episode_id": "ep-a", "account": "acct-1", "host": "a.example.test"}
        scope_b = {"run_id": "run-b", "episode_id": "ep-b", "account": "acct-1", "host": "b.example.test"}
        hid_a = {"target": {"host": scope_a["host"]}, "context": scope_a, "primitives": [{"type": "click"}]}
        hid_b = {"target": {"host": scope_b["host"]}, "context": scope_b, "primitives": [{"type": "click"}]}

        container.mcp_registry.invoke_tool(browser_server, snapshot_tool, scope_a)
        container.mcp_registry.invoke_tool(hid_server, hid_tool, hid_a)
        container.mcp_registry.invoke_tool(browser_server, snapshot_tool, scope_b)
        container.mcp_registry.invoke_tool(hid_server, hid_tool, hid_b)
        with pytest.raises(McpBridgeError, match="followed by a browser observation"):
            container.mcp_registry.invoke_tool(hid_server, hid_tool, hid_a)

    assert [call[1] for call in tool_calls] == ["browser_snapshot", "hid_action", "browser_snapshot", "hid_action"]
    _reset_browser_hid_sequence_state_for_tests()


def test_browser_hid_runtime_sequence_uses_expected_origin_for_observation_scope(tmp_path, monkeypatch) -> None:
    _reset_browser_hid_sequence_state_for_tests()
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        if server.endpoint == "mcp://browser-runtime":
            return [
                {
                    "name": "browser_snapshot",
                    "description": "Read page snapshot.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
                    "annotations": {"readOnlyHint": True},
                }
            ]
        if server.endpoint == "mcp://hid-runtime":
            return [{"name": "hid_action", "description": "Run HID action.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True}}]
        return []

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        if tool_name == "browser_snapshot":
            return {"success": True, "snapshot": {"text": "职位列表"}, "tabId": arguments.get("tabId")}
        return {"success": True, "tool": tool_name}

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-sequence-expected-origin.db'}",
        provider_config={},
    )
    container = AppContainer.build(settings)
    for server_key, endpoint, capabilities in (
        ("browser", "mcp://browser-runtime", {"default": ["browser"], "read_only": ["document"]}),
        ("virtualhid", "mcp://hid-runtime", {"default": ["scene"], "mutating": ["computer_write"]}),
    ):
        container.mcp_registry.create_server(
            {
                "server_key": server_key,
                "name": server_key,
                "transport_kind": "stdio",
                "protocol": "mcp_jsonrpc",
                "endpoint": endpoint,
                "enabled": True,
                "auth_config": {},
                "server_metadata": {"runtime_tool_capabilities": capabilities},
                "tools": [],
            }
        )

    snapshot_args = {
        "tabId": 42,
        "expectedHost": "127.0.0.1",
        "expectedOrigin": "http://127.0.0.1:50149",
        "targetPolicy": "same-origin",
    }
    click_args = {
        "target": {"host": "127.0.0.1:50149", "tabId": 42},
        "primitives": [{"type": "click", "at": {"x": 160, "y": 80}}],
    }

    with container.session_factory() as session:
        browser_server = next(item for item in session.query(McpServer).all() if item.server_key == "browser")
        hid_server = next(item for item in session.query(McpServer).all() if item.server_key == "virtualhid")
        snapshot_tool = next(item for item in session.query(McpTool).all() if item.server_id == browser_server.id and item.name == "browser_snapshot")
        hid_tool = next(item for item in session.query(McpTool).all() if item.server_id == hid_server.id and item.name == "hid_action")

        container.mcp_registry.invoke_tool(browser_server, snapshot_tool, dict(snapshot_args))
        container.mcp_registry.invoke_tool(hid_server, hid_tool, dict(click_args))
        container.mcp_registry.invoke_tool(browser_server, snapshot_tool, dict(snapshot_args))
        container.mcp_registry.invoke_tool(hid_server, hid_tool, dict(click_args))

    assert [call[1] for call in tool_calls] == ["browser_snapshot", "hid_action", "browser_snapshot", "hid_action"]
    _reset_browser_hid_sequence_state_for_tests()


def test_browser_hid_runtime_sequence_ignores_scene_task_id_and_prefers_port_host(tmp_path, monkeypatch) -> None:
    _reset_browser_hid_sequence_state_for_tests()
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        if server.endpoint == "mcp://browser-runtime":
            return [
                {
                    "name": "browser_snapshot",
                    "description": "Read page snapshot.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
                    "annotations": {"readOnlyHint": True},
                }
            ]
        if server.endpoint == "mcp://hid-runtime":
            return [{"name": "hid_action", "description": "Run HID action.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True}}]
        return []

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        if tool_name == "browser_snapshot":
            return {
                "success": True,
                "snapshot": {"url": "http://127.0.0.1:5179/jobs/jd-solution-002"},
                "tabId": 1136767432,
                "target": {
                    "tabId": 1136767432,
                    "windowId": 1136767341,
                    "url": "http://127.0.0.1:5179/jobs/jd-solution-002",
                    "title": "职位详情 - 解决方案顾问",
                },
            }
        return {"success": True, "tool": tool_name}

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-sequence-scene-task-id.db'}",
        provider_config={},
    )
    container = AppContainer.build(settings)
    for server_key, endpoint, capabilities in (
        ("browser", "mcp://browser-runtime", {"default": ["browser"], "read_only": ["document"]}),
        ("virtualhid", "mcp://hid-runtime", {"default": ["scene"], "mutating": ["computer_write"]}),
    ):
        container.mcp_registry.create_server(
            {
                "server_key": server_key,
                "name": server_key,
                "transport_kind": "stdio",
                "protocol": "mcp_jsonrpc",
                "endpoint": endpoint,
                "enabled": True,
                "auth_config": {},
                "server_metadata": {"runtime_tool_capabilities": capabilities},
                "tools": [],
            }
        )

    with container.session_factory() as session:
        browser_server = next(item for item in session.query(McpServer).all() if item.server_key == "browser")
        hid_server = next(item for item in session.query(McpServer).all() if item.server_key == "virtualhid")
        snapshot_tool = next(item for item in session.query(McpTool).all() if item.server_id == browser_server.id and item.name == "browser_snapshot")
        hid_tool = next(item for item in session.query(McpTool).all() if item.server_id == hid_server.id and item.name == "hid_action")

        container.mcp_registry.invoke_tool(
            browser_server,
            snapshot_tool,
            {
                "tabId": 1136767432,
                "expectedHost": "127.0.0.1",
                "expectedOrigin": "http://127.0.0.1:5179",
            },
        )
        container.mcp_registry.invoke_tool(
            hid_server,
            hid_tool,
            {
                "target": {"host": "127.0.0.1", "tabId": 1136767432},
                "context": {"host": "127.0.0.1:5179", "taskId": "scene-episode-id"},
                "primitives": [{"type": "click", "at": {"x": 1424, "y": 79}}],
            },
        )

    assert [call[1] for call in tool_calls] == ["browser_snapshot", "hid_action"]
    _reset_browser_hid_sequence_state_for_tests()


def test_browser_hid_runtime_hydrates_window_bounds_from_browser_observation(tmp_path, monkeypatch) -> None:
    _reset_browser_hid_sequence_state_for_tests()
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        if server.endpoint == "mcp://browser-runtime":
            return [
                {
                    "name": "browser_snapshot",
                    "description": "Read page snapshot.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
                    "annotations": {"readOnlyHint": True},
                }
            ]
        if server.endpoint == "mcp://hid-runtime":
            return [{"name": "hid_action", "description": "Run HID action.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True}}]
        return []

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        if tool_name == "browser_snapshot":
            return {
                "success": True,
                "snapshot": {
                    "url": "http://127.0.0.1:50149/jobs",
                    "title": "职位列表 · Recruiting Workspace",
                    "viewport": {
                        "innerWidth": 1526,
                        "innerHeight": 1039,
                        "outerWidth": 1526,
                        "outerHeight": 1160,
                        "screenX": 3195,
                        "screenY": -1251,
                    },
                },
                "tabId": 1136767238,
                "target": {
                    "tabId": 1136767238,
                    "windowId": 1136767237,
                    "url": "http://127.0.0.1:50149/jobs",
                    "title": "职位列表 · Recruiting Workspace",
                },
            }
        return {"success": True, "tool": tool_name}

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-sequence-window-bounds.db'}",
        provider_config={},
    )
    container = AppContainer.build(settings)
    for server_key, endpoint, capabilities in (
        ("browser", "mcp://browser-runtime", {"default": ["browser"], "read_only": ["document"]}),
        ("virtualhid", "mcp://hid-runtime", {"default": ["scene"], "mutating": ["computer_write"]}),
    ):
        container.mcp_registry.create_server(
            {
                "server_key": server_key,
                "name": server_key,
                "transport_kind": "stdio",
                "protocol": "mcp_jsonrpc",
                "endpoint": endpoint,
                "enabled": True,
                "auth_config": {},
                "server_metadata": {"runtime_tool_capabilities": capabilities},
                "tools": [],
            }
        )

    click_args = {
        "target": {"host": "127.0.0.1:50149", "tabId": 1136767238},
        "geometry": {"coordSpace": "viewport"},
        "primitives": [{"type": "click", "at": {"x": 160, "y": 80}}],
    }

    with container.session_factory() as session:
        browser_server = next(item for item in session.query(McpServer).all() if item.server_key == "browser")
        hid_server = next(item for item in session.query(McpServer).all() if item.server_key == "virtualhid")
        snapshot_tool = next(item for item in session.query(McpTool).all() if item.server_id == browser_server.id and item.name == "browser_snapshot")
        hid_tool = next(item for item in session.query(McpTool).all() if item.server_id == hid_server.id and item.name == "hid_action")

        container.mcp_registry.invoke_tool(
            browser_server,
            snapshot_tool,
            {
                "tabId": 1136767238,
                "expectedHost": "127.0.0.1:50149",
                "expectedOrigin": "http://127.0.0.1:50149",
            },
        )
        container.mcp_registry.invoke_tool(hid_server, hid_tool, click_args)

    hid_call = next(call for call in tool_calls if call[1] == "hid_action")
    assert hid_call[2]["target"]["browserWindowBounds"] == {"x": 3195, "y": -1251, "width": 1526, "height": 1160}
    assert hid_call[2]["target"]["windowId"] == 1136767237
    assert hid_call[2]["target"]["windowTitle"] == "职位列表 · Recruiting Workspace"
    assert "browserWindowBounds" not in click_args["target"]
    _reset_browser_hid_sequence_state_for_tests()


def test_browser_hid_runtime_sequence_does_not_scope_by_hid_action_id(tmp_path, monkeypatch) -> None:
    _reset_browser_hid_sequence_state_for_tests()
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        if server.endpoint == "mcp://browser-runtime":
            return [
                {
                    "name": "browser_snapshot",
                    "description": "Read page snapshot.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
                    "annotations": {"readOnlyHint": True},
                }
            ]
        if server.endpoint == "mcp://hid-runtime":
            return [{"name": "hid_action", "description": "Run HID action.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True}}]
        return []

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        if tool_name == "browser_snapshot":
            return {"success": True, "snapshot": {"url": "http://127.0.0.1:50149/jobs/jd-sales-001"}, "tabId": arguments.get("tabId")}
        return {"success": True, "tool": tool_name}

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-sequence-action-id.db'}",
        provider_config={},
    )
    container = AppContainer.build(settings)
    for server_key, endpoint, capabilities in (
        ("browser", "mcp://browser-runtime", {"default": ["browser"], "read_only": ["document"]}),
        ("virtualhid", "mcp://hid-runtime", {"default": ["scene"], "mutating": ["computer_write"]}),
    ):
        container.mcp_registry.create_server(
            {
                "server_key": server_key,
                "name": server_key,
                "transport_kind": "stdio",
                "protocol": "mcp_jsonrpc",
                "endpoint": endpoint,
                "enabled": True,
                "auth_config": {},
                "server_metadata": {"runtime_tool_capabilities": capabilities},
                "tools": [],
            }
        )

    snapshot_args = {
        "tabId": 42,
        "expectedHost": "127.0.0.1",
        "expectedOrigin": "http://127.0.0.1:50149",
        "targetPolicy": "same-origin",
    }
    click_args = {
        "id": "jd-sync-open-job-list",
        "target": {"host": "127.0.0.1:50149", "tabId": 42},
        "primitives": [{"type": "click", "at": {"x": 160, "y": 80}}],
    }

    with container.session_factory() as session:
        browser_server = next(item for item in session.query(McpServer).all() if item.server_key == "browser")
        hid_server = next(item for item in session.query(McpServer).all() if item.server_key == "virtualhid")
        snapshot_tool = next(item for item in session.query(McpTool).all() if item.server_id == browser_server.id and item.name == "browser_snapshot")
        hid_tool = next(item for item in session.query(McpTool).all() if item.server_id == hid_server.id and item.name == "hid_action")

        container.mcp_registry.invoke_tool(browser_server, snapshot_tool, dict(snapshot_args))
        container.mcp_registry.invoke_tool(hid_server, hid_tool, dict(click_args))

    assert [call[1] for call in tool_calls] == ["browser_snapshot", "hid_action"]
    _reset_browser_hid_sequence_state_for_tests()


def test_browser_hid_runtime_target_identification_and_failed_observations_do_not_clear_gate(tmp_path, monkeypatch) -> None:
    _reset_browser_hid_sequence_state_for_tests()

    browser_tools = [
        {
            "name": "browser_list_tabs",
            "description": "List tabs.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "browser_get_active_tab",
            "description": "Get active tab.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "browser_snapshot",
            "description": "Read page snapshot.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "browser_query_elements",
            "description": "Query elements.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
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
        if tool_name == "browser_query_elements":
            return {"success": False, "error": "scene_browser_target_mismatch"}
        if tool_name.startswith("browser_"):
            return {"success": True, "tool": tool_name, "snapshot": {"url": "https://recruit.example.test/jobs"}, "tabId": arguments.get("tabId")}
        return {"success": True, "tool": tool_name}

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-browser-hid-failed-observation.db'}",
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
        browser_server, list_tool = get_server_tool("browser", "browser_list_tabs")
        _, active_tool = get_server_tool("browser", "browser_get_active_tab")
        _, snapshot_tool = get_server_tool("browser", "browser_snapshot")
        _, query_tool = get_server_tool("browser", "browser_query_elements")
        hid_server, hid_tool = get_server_tool("virtualhid", "hid_action")

        container.mcp_registry.invoke_tool(browser_server, list_tool, {})
        container.mcp_registry.invoke_tool(browser_server, active_tool, {})
        with pytest.raises(McpBridgeError, match="prior browser observation"):
            container.mcp_registry.invoke_tool(hid_server, hid_tool, click_args)

        container.mcp_registry.invoke_tool(browser_server, snapshot_tool, {})
        container.mcp_registry.invoke_tool(hid_server, hid_tool, click_args)
        container.mcp_registry.invoke_tool(browser_server, query_tool, {"tabId": 999, "selector": "a"})
        with pytest.raises(McpBridgeError, match="followed by a browser observation"):
            container.mcp_registry.invoke_tool(hid_server, hid_tool, click_args)

    assert tool_calls == [
        ("mcp://browser-runtime", "browser_list_tabs", {}),
        ("mcp://browser-runtime", "browser_get_active_tab", {}),
        ("mcp://browser-runtime", "browser_snapshot", {}),
        ("mcp://hid-runtime", "hid_action", click_args),
        ("mcp://browser-runtime", "browser_query_elements", {"tabId": 999, "selector": "a"}),
    ]

    _reset_browser_hid_sequence_state_for_tests()


def test_browser_hid_runtime_allows_keyboard_recovery_after_target_identification(tmp_path, monkeypatch) -> None:
    _reset_browser_hid_sequence_state_for_tests()

    browser_tools = [
        {
            "name": "browser_get_active_tab",
            "description": "Get active tab.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        }
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
        if tool_name == "browser_get_active_tab":
            return {
                "success": True,
                "target": {
                    "url": "http://127.0.0.1:50149/jobs/jd-sales-001",
                    "host": "127.0.0.1:50149",
                    "tabId": 42,
                    "windowId": 7,
                    "title": "职位详情 · Recruiting Workspace",
                },
            }
        return {"success": True, "tool": tool_name}

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-browser-hid-keyboard-recovery.db'}",
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

    keyboard_args = {
        "target": {"host": "127.0.0.1:50149"},
        "context": {"host": "127.0.0.1:50149"},
        "primitives": [
            {"type": "key", "keyCode": 37, "modifiers": ["cmd"]},
            {"type": "pasteText", "text": "http://127.0.0.1:50149/jobs", "restoreClipboard": True},
            {"type": "key", "keyCode": 36},
        ],
    }

    with container.session_factory() as session:
        browser_server = next(item for item in session.query(McpServer).all() if item.server_key == "browser")
        active_tool = next(item for item in session.query(McpTool).all() if item.server_id == browser_server.id and item.name == "browser_get_active_tab")
        hid_server = next(item for item in session.query(McpServer).all() if item.server_key == "virtualhid")
        hid_tool = next(item for item in session.query(McpTool).all() if item.server_id == hid_server.id and item.name == "hid_action")

        container.mcp_registry.invoke_tool(browser_server, active_tool, {})
        with pytest.raises(McpBridgeError, match="address-bar navigation is not an allowed recovery path"):
            container.mcp_registry.invoke_tool(hid_server, hid_tool, keyboard_args)

    assert [call[1] for call in tool_calls] == ["browser_get_active_tab"]

    _reset_browser_hid_sequence_state_for_tests()


def test_mcp_call_tool_preserves_structured_content_on_is_error(monkeypatch) -> None:
    server = McpServer(
        server_key="virtualhid",
        name="VirtualHID",
        transport_kind="stdio",
        protocol="mcp_jsonrpc",
        endpoint="mcp://hid-runtime",
        enabled=True,
        auth_config={},
        server_metadata={},
    )

    def fake_session_request(server, method: str, params: dict[str, Any] | None = None, *, timeout_seconds: float = 8.0) -> dict[str, Any]:
        assert method == "tools/call"
        return {
            "isError": True,
            "structuredContent": {
                "result": {
                    "preflight": {
                        "browserChromeOverlay": {"status": "blocked", "evidence": "toolbar-overlap"},
                    }
                }
            },
            "content": [{"type": "text", "text": "overlay blocked"}],
        }

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_session_request", fake_session_request)

    result = _mcp_call_tool(server, "hid_action", {"primitives": []})

    assert result["isError"] is True
    assert result["result"]["preflight"]["browserChromeOverlay"]["evidence"] == "toolbar-overlap"


def test_mcp_call_tool_extends_stdio_timeout_for_hid_action(monkeypatch) -> None:
    server = McpServer(
        server_key="virtualhid",
        name="VirtualHID",
        transport_kind="stdio",
        protocol="mcp_jsonrpc",
        endpoint="mcp://hid-runtime",
        enabled=True,
        auth_config={},
        server_metadata={},
    )
    captured: dict[str, Any] = {}

    def fake_session_request(server, method: str, params: dict[str, Any] | None = None, *, timeout_seconds: float = 8.0) -> dict[str, Any]:
        captured["timeout_seconds"] = timeout_seconds
        return {"structuredContent": {"success": True}}

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_session_request", fake_session_request)

    result = _mcp_call_tool(server, "hid_action", {"options": {"timeoutMs": 12000}, "primitives": []})

    assert result == {"success": True}
    assert captured["timeout_seconds"] == 18.0


def test_standard_mcp_tool_retries_once_on_transient_failure(tmp_path, monkeypatch) -> None:
    discovered_tools = [
        {
            "name": "dynamic_echo",
            "description": "Echo back the payload.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
            "annotations": {"readOnlyHint": True},
        }
    ]
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        assert server.endpoint == "mcp://retry-runtime"
        return discovered_tools

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        if len(tool_calls) == 1:
            raise McpBridgeError("Transport closed while reading MCP response")
        return {"ok": True, "tool": tool_name, "arguments": dict(arguments)}

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)
    monkeypatch.setattr("recruit_station.services.mcp_registry.time.sleep", lambda _: None)

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-transient-retry.db'}",
        provider_config={},
    )
    container = AppContainer.build(settings)
    container.mcp_registry.create_server(
        {
            "server_key": "dynamic-mcp",
            "name": "Dynamic MCP",
            "transport_kind": "stdio",
            "protocol": "mcp_jsonrpc",
            "endpoint": "mcp://retry-runtime",
            "enabled": True,
            "auth_config": {},
            "server_metadata": {},
            "tools": [],
        }
    )

    with container.session_factory() as session:
        server = session.query(McpServer).one()
        tool = session.query(McpTool).one()
        result = container.mcp_registry.invoke_tool(server, tool, {"text": "retry"})

    assert result == {"ok": True, "tool": "dynamic_echo", "arguments": {"text": "retry"}}
    assert tool_calls == [
        ("mcp://retry-runtime", "dynamic_echo", {"text": "retry"}),
        ("mcp://retry-runtime", "dynamic_echo", {"text": "retry"}),
    ]
    with container.session_factory() as session:
        server = session.query(McpServer).one()
        assert server.health_status == "healthy"
        assert server.health_error is None


def test_standard_mcp_tool_marks_server_unhealthy_after_persistent_transient_failure(tmp_path, monkeypatch) -> None:
    discovered_tools = [
        {
            "name": "dynamic_echo",
            "description": "Echo back the payload.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
            "annotations": {"readOnlyHint": True},
        }
    ]
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_list_tools(server) -> list[dict[str, Any]]:
        assert server.endpoint == "mcp://retry-runtime"
        return discovered_tools

    def fake_call_tool(server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((server.endpoint, tool_name, dict(arguments)))
        raise McpBridgeError("MCP socket not found: /tmp/browser-mcp.sock")

    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr("recruit_station.services.mcp_registry._mcp_call_tool", fake_call_tool)
    monkeypatch.setattr("recruit_station.services.mcp_registry.time.sleep", lambda _: None)

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-transient-unhealthy.db'}",
        provider_config={},
    )
    container = AppContainer.build(settings)
    container.mcp_registry.create_server(
        {
            "server_key": "dynamic-mcp",
            "name": "Dynamic MCP",
            "transport_kind": "stdio",
            "protocol": "mcp_jsonrpc",
            "endpoint": "mcp://retry-runtime",
            "enabled": True,
            "auth_config": {},
            "server_metadata": {},
            "tools": [],
        }
    )

    with container.session_factory() as session:
        server = session.query(McpServer).one()
        tool = session.query(McpTool).one()
        with pytest.raises(McpBridgeError, match="MCP socket not found"):
            container.mcp_registry.invoke_tool(server, tool, {"text": "retry"})

    assert tool_calls == [
        ("mcp://retry-runtime", "dynamic_echo", {"text": "retry"}),
        ("mcp://retry-runtime", "dynamic_echo", {"text": "retry"}),
    ]
    with container.session_factory() as session:
        server = session.query(McpServer).one()
        assert server.health_status == "unhealthy"
        assert server.health_error == "MCP socket not found: /tmp/browser-mcp.sock"
