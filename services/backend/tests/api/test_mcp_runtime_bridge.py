from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from recruit_agent.core.settings import AppSettings, load_settings
from recruit_agent.models.domain import McpServer
from recruit_agent.server import create_app
from recruit_agent.services.browser_mcp_bridge import BROWSER_SOCKET_PRESET_KEY
from recruit_agent.services.container import AppContainer
from recruit_agent.services.mcp_registry import VIRTUALHID_SOCKET_PRESET_KEY


def _settings(tmp_path: Path, name: str) -> AppSettings:
    return AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / name}",
        provider_config={},
    )


def _browser_tool_payloads() -> list[dict[str, object]]:
    tools = [
        ("browser_list_tabs", {"currentWindowOnly": {"type": "boolean"}}),
        ("browser_get_active_tab", {}),
        ("browser_select_tab", {"tabId": {"type": "number"}}),
        ("browser_open_tab", {"tabId": {"type": "number"}, "windowId": {"type": "number"}, "url": {"type": "string"}, "active": {"type": "boolean"}}),
        (
            "browser_snapshot",
            {
                "tabId": {"type": "number"},
                "includeHtml": {"type": "boolean"},
                "includeText": {"type": "boolean"},
                "maxTextLength": {"type": "number"},
                "maxHtmlLength": {"type": "number"},
                "clickableLimit": {"type": "number"},
            },
        ),
        (
            "browser_query_elements",
            {
                "tabId": {"type": "number"},
                "ref": {"type": "string"},
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "role": {"type": "string"},
                "index": {"type": "number"},
                "limit": {"type": "number"},
                "visibleOnly": {"type": "boolean"},
            },
        ),
        (
            "browser_get_element",
            {
                "tabId": {"type": "number"},
                "ref": {"type": "string"},
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "role": {"type": "string"},
                "index": {"type": "number"},
                "visibleOnly": {"type": "boolean"},
            },
        ),
        ("browser_debug_dom", {"tabId": {"type": "number"}}),
        (
            "browser_wait_for_element",
            {
                "tabId": {"type": "number"},
                "ref": {"type": "string"},
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "role": {"type": "string"},
                "index": {"type": "number"},
                "limit": {"type": "number"},
                "visibleOnly": {"type": "boolean"},
                "timeoutMs": {"type": "number"},
                "pollIntervalMs": {"type": "number"},
            },
        ),
        (
            "browser_wait_for_text",
            {
                "tabId": {"type": "number"},
                "text": {"type": "string"},
                "timeoutMs": {"type": "number"},
                "pollIntervalMs": {"type": "number"},
            },
        ),
        ("browser_wait_for_navigation", {"tabId": {"type": "number"}, "timeoutMs": {"type": "number"}}),
        (
            "browser_wait_for_disappear",
            {
                "tabId": {"type": "number"},
                "ref": {"type": "string"},
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "role": {"type": "string"},
                "index": {"type": "number"},
                "limit": {"type": "number"},
                "visibleOnly": {"type": "boolean"},
                "timeoutMs": {"type": "number"},
                "pollIntervalMs": {"type": "number"},
            },
        ),
        ("browser_screenshot", {"tabId": {"type": "number"}}),
        ("browser_get_cookies", {"url": {"type": "string"}, "domain": {"type": "string"}, "name": {"type": "string"}}),
        (
            "browser_locate_download",
            {
                "downloadId": {"type": "number"},
                "fileName": {"type": "string"},
                "filename": {"type": "string"},
                "filenameRegex": {"type": "string"},
                "url": {"type": "string"},
                "urlRegex": {"type": "string"},
                "sourceUrl": {"type": "string"},
                "sourceUrlRegex": {"type": "string"},
                "finalUrl": {"type": "string"},
                "finalUrlRegex": {"type": "string"},
                "referrer": {"type": "string"},
                "referrerRegex": {"type": "string"},
                "query": {"type": "string"},
                "expectedExtensions": {"type": "array", "items": {"type": "string"}},
                "state": {"type": "string"},
                "states": {"type": "array", "items": {"type": "string"}},
                "requireExists": {"type": "boolean"},
                "requireComplete": {"type": "boolean"},
                "requireSafe": {"type": "boolean"},
                "requireSourceCorrelation": {"type": "boolean"},
                "requireUnique": {"type": "boolean"},
                "startedAfter": {"type": "string"},
                "since": {"type": "string"},
                "endedAfter": {"type": "string"},
                "limit": {"type": "number"},
                "waitMs": {"type": "number"},
                "pollIntervalMs": {"type": "number"},
            },
        ),
        ("browser_wait_for_url", {"tabId": {"type": "number"}, "pattern": {"type": "string"}, "timeoutMs": {"type": "number"}}),
    ]
    return [
        {
            "name": name,
            "description": name,
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
            },
        }
        for name, properties in tools
    ]


def _virtualhid_tool_payloads() -> list[dict[str, object]]:
    return [
        {
            "name": "hid_action",
            "description": "hid_action",
            "inputSchema": {
                "type": "object",
                "required": ["id", "primitives", "context"],
                "properties": {
                    "id": {"type": "string"},
                    "primitives": {"type": "array"},
                    "context": {"type": "object"},
                    "options": {"type": "object"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "hid_state",
            "description": "hid_state",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "hid_stop",
            "description": "hid_stop",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "hid_unlock",
            "description": "hid_unlock",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "hid_observe",
            "description": "hid_observe",
            "inputSchema": {
                "type": "object",
                "required": ["enable"],
                "properties": {
                    "enable": {"type": "boolean"},
                    "host": {"type": "string"},
                    "taskId": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "hid_profiles_list",
            "description": "hid_profiles_list",
            "inputSchema": {
                "type": "object",
                "properties": {"host": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        {
            "name": "hid_profiles_get",
            "description": "hid_profiles_get",
            "inputSchema": {
                "type": "object",
                "required": ["host", "sig"],
                "properties": {"host": {"type": "string"}, "sig": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        {
            "name": "hid_profiles_forget",
            "description": "hid_profiles_forget",
            "inputSchema": {
                "type": "object",
                "properties": {"host": {"type": "string"}, "sig": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        {
            "name": "hid_trace_tail",
            "description": "hid_trace_tail",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "sinceEventId": {"type": "string"},
                    "onlyUnresolved": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "hid_trace_commit",
            "description": "hid_trace_commit",
            "inputSchema": {
                "type": "object",
                "required": ["eventId", "elementSig", "host"],
                "properties": {
                    "eventId": {"type": "string"},
                    "elementSig": {"type": "string"},
                    "host": {"type": "string"},
                    "role": {"type": "string"},
                    "text": {"type": "string"},
                    "taskId": {"type": "string"},
                    "stage": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
    ]


def test_container_build_registers_enabled_browser_mcp_tools(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "recruit_agent.services.mcp_registry.default_browser_mcp_server_command",
        lambda: ("node", "/virtual/browser-mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "recruit_agent.services.mcp_registry._mcp_list_tools",
        lambda server: _browser_tool_payloads(),
    )

    settings = _settings(tmp_path, "mcp-container.db")
    container = AppContainer.build(settings)
    with container.session_factory() as session:
        session.add(
            McpServer(
                server_key="browser",
                name="Browser MCP",
                endpoint=str(tmp_path / "browser-upstream.sock"),
                enabled=True,
                preset_key=BROWSER_SOCKET_PRESET_KEY,
            )
        )
        session.commit()

    reloaded = AppContainer.build(settings)
    assert "delegate_scene_context" in reloaded.tool_registry.tools
    assert "browser_get_active_tab" not in reloaded.tool_registry.tools
    assert "browser_open_tab" not in reloaded.tool_registry.tools
    assert "browser_locate_download" not in reloaded.tool_registry.tools
    assert "browser_wait_for_url" not in reloaded.tool_registry.tools
    assert "browser_get_active_tab" in reloaded.scene_context_tool_registry.tools
    assert "browser_open_tab" in reloaded.scene_context_tool_registry.tools
    assert "browser_locate_download" in reloaded.scene_context_tool_registry.tools
    assert "browser_wait_for_url" in reloaded.scene_context_tool_registry.tools
    assert "read_memory" not in reloaded.scene_context_tool_registry.tools
    assert "record_learning" not in reloaded.scene_context_tool_registry.tools
    assert "invoke_skill" not in reloaded.scene_context_tool_registry.tools
    assert "delegate_scene_context" not in reloaded.scene_context_tool_registry.tools
    tool = reloaded.scene_context_tool_registry.tools["browser_get_active_tab"]
    assert tool.metadata["external_tool"] is True
    assert tool.metadata["mcp_server_key"] == "browser"

    with reloaded.session_factory() as session:
        server = next(item for item in session.query(McpServer).all() if item.server_key == "browser")
        assert server.transport_kind == "stdio"
        metadata = dict(server.server_metadata or {})
        assert metadata["stdio_command"] == ["node", "/virtual/browser-mcp/server.mjs"]
        assert metadata["stdio_env"]["MCP_BROWSER_CHROME_SOCKET"] == str(tmp_path / "browser-upstream.sock")


def test_browser_mcp_preset_healthcheck_uses_stdio_mcp_server(tmp_path: Path, monkeypatch) -> None:
    tool_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "recruit_agent.services.mcp_registry.default_browser_mcp_server_command",
        lambda: ("node", "/virtual/browser-mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "recruit_agent.services.mcp_registry._mcp_list_tools",
        lambda server: _browser_tool_payloads(),
    )

    def fake_call_tool(server, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        tool_calls.append(
            {
                "server_key": server.server_key,
                "transport_kind": server.transport_kind,
                "endpoint": server.endpoint,
                "tool_name": tool_name,
                "arguments": dict(arguments),
                "stdio_env": dict((server.server_metadata or {}).get("stdio_env") or {}),
            }
        )
        return {
            "id": 1,
            "title": "Example",
            "url": "https://example.com",
        }

    monkeypatch.setattr(
        "recruit_agent.services.mcp_registry._mcp_call_tool",
        fake_call_tool,
    )

    settings = _settings(tmp_path, "mcp-health.db")
    load_settings.cache_clear()
    app = create_app(settings)
    with TestClient(app) as client:
        upstream = str(tmp_path / f"browser-upstream-{uuid.uuid4().hex}.sock")
        created = client.post(
            f"/api/mcp/presets/{BROWSER_SOCKET_PRESET_KEY}/install",
            json={
                "server_key": "browser",
                "name": "Browser MCP",
                "endpoint": upstream,
            },
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["transport_kind"] == "stdio"
        assert payload["server_metadata"]["stdio_command"] == ["node", "/virtual/browser-mcp/server.mjs"]
        assert payload["server_metadata"]["stdio_env"]["MCP_BROWSER_CHROME_SOCKET"] == upstream

        checked = client.post(f"/api/mcp/servers/{payload['id']}/healthcheck")
        assert checked.status_code == 200
        checked_payload = checked.json()
        assert checked_payload["health_status"] == "healthy"
        tool_names = {item["name"] for item in checked_payload["tools"]}
        assert len(tool_names) == 16
        assert {"browser_get_active_tab", "browser_open_tab", "browser_locate_download", "browser_wait_for_url"}.issubset(tool_names)

    assert tool_calls
    assert tool_calls[-1]["server_key"] == "browser"
    assert tool_calls[-1]["transport_kind"] == "stdio"
    assert tool_calls[-1]["endpoint"] == upstream
    assert tool_calls[-1]["tool_name"] in {"browser_get_active_tab", "browser_list_tabs"}
    assert tool_calls[-1]["arguments"] == {}
    assert tool_calls[-1]["stdio_env"] == {"MCP_BROWSER_CHROME_SOCKET": upstream}


def test_mcp_healthcheck_reload_registers_tools_discovered_after_install(tmp_path: Path, monkeypatch) -> None:
    upstream_available = False

    monkeypatch.setattr(
        "recruit_agent.services.mcp_registry.default_browser_mcp_server_command",
        lambda: ("node", "/virtual/browser-mcp/server.mjs"),
    )

    def fake_list_tools(_server) -> list[dict[str, object]]:
        if not upstream_available:
            raise RuntimeError("upstream unavailable")
        return _browser_tool_payloads()

    monkeypatch.setattr("recruit_agent.services.mcp_registry._mcp_list_tools", fake_list_tools)
    monkeypatch.setattr(
        "recruit_agent.services.mcp_registry._mcp_call_tool",
        lambda _server, _tool_name, _arguments: {"id": 1, "title": "Example", "url": "https://example.com"},
    )

    settings = _settings(tmp_path, "mcp-health-reload.db")
    load_settings.cache_clear()
    app = create_app(settings)
    with TestClient(app) as client:
        created = client.post(
            f"/api/mcp/presets/{BROWSER_SOCKET_PRESET_KEY}/install",
            json={
                "server_key": "browser",
                "name": "Browser MCP",
                "endpoint": str(tmp_path / "browser-upstream.sock"),
            },
        )
        assert created.status_code == 201
        assert "browser_get_active_tab" not in app.state.container.scene_context_tool_registry.tools

        upstream_available = True
        checked = client.post(f"/api/mcp/servers/{created.json()['id']}/healthcheck")
        assert checked.status_code == 200
        assert checked.json()["health_status"] == "healthy"
        assert "browser_get_active_tab" in app.state.container.scene_context_tool_registry.tools
        assert "browser_open_tab" in app.state.container.scene_context_tool_registry.tools


def test_container_build_registers_enabled_virtualhid_mcp_tools(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "recruit_agent.services.mcp_registry.default_virtualhid_mcp_server_command",
        lambda: ("node", "/virtual/VirtualHID/mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "recruit_agent.services.mcp_registry._mcp_list_tools",
        lambda server: _virtualhid_tool_payloads(),
    )

    settings = _settings(tmp_path, "virtualhid-container.db")
    container = AppContainer.build(settings)
    upstream = str(tmp_path / "virtualhid-upstream.sock")
    container.mcp_registry.install_preset(
        VIRTUALHID_SOCKET_PRESET_KEY,
        server_key="virtualhid",
        name="VirtualHID MCP",
        endpoint=upstream,
    )

    reloaded = AppContainer.build(settings)
    assert "hid_state" not in reloaded.tool_registry.tools
    assert "hid_action" not in reloaded.tool_registry.tools
    assert "hid_state" in reloaded.scene_context_tool_registry.tools
    assert "hid_action" in reloaded.scene_context_tool_registry.tools

    tool = reloaded.scene_context_tool_registry.tools["hid_state"]
    assert tool.metadata["external_tool"] is True
    assert tool.metadata["mcp_server_key"] == "virtualhid"
    assert set(tool.metadata["capabilities"]) == {"scene", "computer", "computer_read"}

    mutating_tool = reloaded.scene_context_tool_registry.tools["hid_action"]
    assert set(mutating_tool.metadata["capabilities"]) == {"scene", "computer", "computer_write"}

    with reloaded.session_factory() as session:
        server = next(item for item in session.query(McpServer).all() if item.server_key == "virtualhid")
        assert server.transport_kind == "stdio"
        metadata = dict(server.server_metadata or {})
        assert metadata["stdio_command"] == ["node", "/virtual/VirtualHID/mcp/server.mjs"]
        assert metadata["stdio_env"]["VIRTUALHID_SOCKET"] == upstream
