from __future__ import annotations

import json

from fastapi.testclient import TestClient

from recruit_station.core.settings import AppSettings
from recruit_station.server import create_app
from recruit_station.services.mcp_registry import VIRTUALHID_SOCKET_PRESET_KEY


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


def test_mcp_presets_load_from_recruit_station_assets(tmp_path, monkeypatch) -> None:
    preset_dir = tmp_path / ".recruit-station" / "mcp" / "presets"
    preset_dir.mkdir(parents=True)
    (preset_dir / "custom-unix.json").write_text(
        json.dumps(
            {
                "key": "custom-unix",
                "name": "Custom Unix MCP",
                "description": "asset-backed MCP preset",
                "transport_kind": "unix_socket",
                "protocol": "json_socket_tool_call",
                "endpoint_example": "/virtual/custom.sock",
                "tools": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.mcp_preset_templates_root",
        lambda: preset_dir,
    )

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-preset-assets.db'}",
        provider_config={},
    )

    app = create_app(settings)
    with TestClient(app) as client:
        listed = client.get("/api/mcp/presets")
        assert listed.status_code == 200
        assert listed.json() == [
            {
                "key": "custom-unix",
                "name": "Custom Unix MCP",
                "description": "asset-backed MCP preset",
                "transport_kind": "unix_socket",
                "protocol": "json_socket_tool_call",
                "endpoint_example": "/virtual/custom.sock",
                "tools": [],
            }
        ]

        installed = client.post(
            "/api/mcp/presets/custom-unix/install",
            json={
                "server_key": "custom-installed",
                "name": "Custom Installed MCP",
                "endpoint": "/virtual/runtime.sock",
            },
        )
        assert installed.status_code == 201
        payload = installed.json()
        assert payload["preset_key"] == "custom-unix"
        assert payload["server_key"] == "custom-installed"
        assert payload["name"] == "Custom Installed MCP"
        assert payload["transport_kind"] == "unix_socket"
        assert payload["protocol"] == "json_socket_tool_call"
        assert payload["endpoint"] == "/virtual/runtime.sock"
        assert payload["server_metadata"] == {"preset_installed": True}


def test_mcp_servers_include_builtin_standard_config_without_db_install(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_browser_mcp_server_command",
        lambda: ("node", "/virtual/browser-mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_browser_upstream_endpoint",
        lambda: "/virtual/default-browser.sock",
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_virtualhid_mcp_server_command",
        lambda: ("node", "/virtual/VirtualHID/mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_virtualhid_upstream_endpoint",
        lambda: "/virtual/default-virtualhid.sock",
    )

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-builtin-config.db'}",
        provider_config={},
    )

    app = create_app(settings)
    with TestClient(app) as client:
        servers = client.get("/api/mcp/servers")

    assert servers.status_code == 200
    by_key = {item["server_key"]: item for item in servers.json()}
    assert {"browser-mcp", "virtualhid"}.issubset(by_key)
    browser_config = by_key["browser-mcp"]["standardConfig"]["mcpServers"]["browser-mcp"]
    assert browser_config == {
        "command": "node",
        "args": ["/virtual/browser-mcp/server.mjs"],
        "env": {"MCP_BROWSER_CHROME_SOCKET": "/virtual/default-browser.sock"},
        "transport": "stdio",
    }
    virtualhid_config = by_key["virtualhid"]["standardConfig"]["mcpServers"]["virtualhid"]
    assert virtualhid_config == {
        "command": "node",
        "args": ["/virtual/VirtualHID/mcp/server.mjs"],
        "env": {"VIRTUALHID_SOCKET": "/virtual/default-virtualhid.sock"},
        "transport": "stdio",
    }
    assert by_key["browser-mcp"]["id"] == "builtin:browser-mcp"
    assert by_key["virtualhid"]["id"] == "builtin:virtualhid"


def test_browser_preset_healthcheck_uses_upstream_stdio_mcp_server(tmp_path, monkeypatch) -> None:
    runtime_requests: list[tuple[str, str, str, dict[str, object]]] = []

    def fake_mcp_session_request(server, method: str, params: dict[str, object] | None = None, *, timeout_seconds: float = 8.0) -> dict[str, object]:
        runtime_requests.append(
            (
                server.server_key,
                server.transport_kind,
                server.endpoint,
                {"method": method, "params": dict(params or {}), "timeout_seconds": timeout_seconds},
            )
        )
        if method == "tools/list":
            return {"tools": _browser_tool_payloads()}
        if method == "tools/call":
            return {
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "structuredContent": {"ok": True},
                "isError": False,
            }
        return {}

    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_browser_mcp_server_command",
        lambda: ("node", "/virtual/browser-mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_browser_upstream_endpoint",
        lambda: "/virtual/default-browser.sock",
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry._mcp_session_request",
        fake_mcp_session_request,
    )

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-api-routes.db'}",
        provider_config={},
    )

    app = create_app(settings)
    client = TestClient(app)
    client.__enter__()
    try:
        presets = client.get("/api/mcp/presets")
        assert presets.status_code == 200
        browser_preset = next(item for item in presets.json() if item["key"] == "browser-json-socket")
        assert browser_preset["transport_kind"] == "stdio"
        assert browser_preset["protocol"] == "mcp_jsonrpc"
        assert browser_preset["endpoint_example"] == "/virtual/default-browser.sock"

        installed = client.post(
            "/api/mcp/presets/browser-json-socket/install",
            json={
                "server_key": "browser-managed",
                "name": "Browser MCP",
                "endpoint": "/virtual/upstream-browser.sock",
            },
        )
        assert installed.status_code == 201
        payload = installed.json()
        assert payload["protocol"] == "mcp_jsonrpc"
        assert payload["transport_kind"] == "stdio"
        assert payload["server_metadata"]["stdio_command"] == ["node", "/virtual/browser-mcp/server.mjs"]
        assert payload["server_metadata"]["stdio_env"] == {"MCP_BROWSER_CHROME_SOCKET": "/virtual/upstream-browser.sock"}

        checked = client.post(f"/api/mcp/servers/{payload['id']}/healthcheck")
        assert checked.status_code == 200
        checked_payload = checked.json()
        assert checked_payload["health_status"] == "healthy"
        tool_names = {tool["name"] for tool in checked_payload["tools"]}
        assert len(tool_names) == 11
        assert {
            "browser_list_tabs",
            "browser_get_active_tab",
            "browser_snapshot",
            "browser_query_elements",
            "browser_wait_for_url",
        }.issubset(tool_names)
        assert {"browser_open_tab", "browser_screenshot", "browser_get_cookies", "browser_locate_download"}.isdisjoint(tool_names)

        assert any(
            server_key == "browser-managed"
            and transport_kind == "stdio"
            and endpoint == "/virtual/upstream-browser.sock"
            and request["method"] == "tools/list"
            for server_key, transport_kind, endpoint, request in runtime_requests
        )
        assert any(
            server_key == "browser-managed"
            and transport_kind == "stdio"
            and endpoint == "/virtual/upstream-browser.sock"
            and request["method"] == "tools/call"
            for server_key, transport_kind, endpoint, request in runtime_requests
        )
    finally:
        client.__exit__(None, None, None)


def test_builtin_mcp_healthcheck_state_is_reflected_in_server_list(tmp_path, monkeypatch) -> None:
    def fake_mcp_session_request(server, method: str, params: dict[str, object] | None = None, *, timeout_seconds: float = 8.0) -> dict[str, object]:
        if method == "tools/list":
            if server.server_key == "browser-mcp":
                return {"tools": _browser_tool_payloads()}
            if server.server_key == "virtualhid":
                return {"tools": _virtualhid_tool_payloads()}
        if method == "tools/call":
            return {
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "structuredContent": {"ok": True},
                "isError": False,
            }
        return {}

    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_browser_mcp_server_command",
        lambda: ("node", "/virtual/browser-mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_browser_upstream_endpoint",
        lambda: "/virtual/default-browser.sock",
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_virtualhid_mcp_server_command",
        lambda: ("node", "/virtual/VirtualHID/mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_virtualhid_upstream_endpoint",
        lambda: "/virtual/default-virtualhid.sock",
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry._mcp_session_request",
        fake_mcp_session_request,
    )

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'builtin-mcp-state.db'}",
        provider_config={},
    )

    app = create_app(settings)
    with TestClient(app) as client:
        browser_check = client.post("/api/mcp/servers/builtin:browser-mcp/healthcheck")
        assert browser_check.status_code == 200
        assert browser_check.json()["health_status"] == "healthy"

        virtualhid_check = client.post("/api/mcp/servers/builtin:virtualhid/healthcheck")
        assert virtualhid_check.status_code == 200
        assert virtualhid_check.json()["health_status"] == "healthy"

        servers = client.get("/api/mcp/servers")
        assert servers.status_code == 200
        by_key = {item["server_key"]: item for item in servers.json()}
        assert by_key["browser-mcp"]["health_status"] == "healthy"
        assert by_key["virtualhid"]["health_status"] == "healthy"
        assert by_key["browser-mcp"]["last_health_at"] is not None
        assert by_key["virtualhid"]["last_health_at"] is not None
        assert "browser_snapshot" in {tool["name"] for tool in by_key["browser-mcp"]["tools"]}
        assert {"hid_action", "hid_state"}.issubset({tool["name"] for tool in by_key["virtualhid"]["tools"]})


def test_virtualhid_preset_healthcheck_uses_upstream_stdio_mcp_server(tmp_path, monkeypatch) -> None:
    runtime_requests: list[tuple[str, str, str, dict[str, object]]] = []

    def fake_mcp_session_request(server, method: str, params: dict[str, object] | None = None, *, timeout_seconds: float = 8.0) -> dict[str, object]:
        runtime_requests.append(
            (
                server.server_key,
                server.transport_kind,
                server.endpoint,
                {"method": method, "params": dict(params or {}), "timeout_seconds": timeout_seconds},
            )
        )
        if method == "tools/list":
            return {"tools": _virtualhid_tool_payloads()}
        if method == "tools/call":
            return {
                "content": [{"type": "text", "text": '{"killSwitch": false}'}],
                "structuredContent": {"killSwitch": False},
                "isError": False,
            }
        return {}

    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_virtualhid_mcp_server_command",
        lambda: ("node", "/virtual/VirtualHID/mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry.default_virtualhid_upstream_endpoint",
        lambda: "/virtual/default-virtualhid.sock",
    )
    monkeypatch.setattr(
        "recruit_station.services.mcp_registry._mcp_session_request",
        fake_mcp_session_request,
    )

    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'mcp-virtualhid-routes.db'}",
        provider_config={},
    )

    app = create_app(settings)
    with TestClient(app) as client:
        presets = client.get("/api/mcp/presets")
        assert presets.status_code == 200
        virtualhid_preset = next(item for item in presets.json() if item["key"] == VIRTUALHID_SOCKET_PRESET_KEY)
        assert virtualhid_preset["transport_kind"] == "stdio"
        assert virtualhid_preset["protocol"] == "mcp_jsonrpc"
        assert virtualhid_preset["endpoint_example"] == "/virtual/default-virtualhid.sock"

        installed = client.post(
            f"/api/mcp/presets/{VIRTUALHID_SOCKET_PRESET_KEY}/install",
            json={
                "server_key": "virtualhid-managed",
                "name": "VirtualHID MCP",
                "endpoint": "/virtual/upstream-virtualhid.sock",
            },
        )
        assert installed.status_code == 201
        payload = installed.json()
        assert payload["protocol"] == "mcp_jsonrpc"
        assert payload["transport_kind"] == "stdio"
        assert payload["server_metadata"]["stdio_command"] == ["node", "/virtual/VirtualHID/mcp/server.mjs"]
        assert payload["server_metadata"]["stdio_env"] == {"VIRTUALHID_SOCKET": "/virtual/upstream-virtualhid.sock"}
        assert payload["server_metadata"]["runtime_tool_capabilities"] == {
            "default": ["mcp", "hid", "computer"],
            "read_only": ["computer_read", "read_only"],
            "mutating": ["computer_write"],
        }
        assert payload["server_metadata"]["runtime_tool_read_only_names"] == [
            "hid_state",
            "hid_profiles_list",
            "hid_profiles_get",
            "hid_trace_tail",
        ]

        checked = client.post(f"/api/mcp/servers/{payload['id']}/healthcheck")
        assert checked.status_code == 200
        checked_payload = checked.json()
        assert checked_payload["health_status"] == "healthy"
        tool_names = {tool["name"] for tool in checked_payload["tools"]}
        assert len(tool_names) == 10
        assert {"hid_action", "hid_state", "hid_observe", "hid_profiles_get", "hid_trace_commit"}.issubset(tool_names)

        hid_state = next(tool for tool in checked_payload["tools"] if tool["name"] == "hid_state")
        assert hid_state["risk_level"] == "low"
        assert set(hid_state["capabilities"]) == {"mcp", "hid", "computer", "computer_read", "read_only"}

        hid_action = next(tool for tool in checked_payload["tools"] if tool["name"] == "hid_action")
        assert hid_action["risk_level"] == "medium"
        assert set(hid_action["capabilities"]) == {"mcp", "hid", "computer", "computer_write"}

    assert any(
        server_key == "virtualhid-managed"
        and transport_kind == "stdio"
        and endpoint == "/virtual/upstream-virtualhid.sock"
        and request["method"] == "tools/list"
        for server_key, transport_kind, endpoint, request in runtime_requests
    )
    assert any(
        server_key == "virtualhid-managed"
        and transport_kind == "stdio"
        and endpoint == "/virtual/upstream-virtualhid.sock"
        and request["method"] == "tools/call"
        for server_key, transport_kind, endpoint, request in runtime_requests
    )
