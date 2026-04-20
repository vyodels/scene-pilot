from __future__ import annotations

import json

from fastapi.testclient import TestClient

from scene_pilot.core.settings import AppSettings
from scene_pilot.server import create_app


def _browser_tool_payloads() -> list[dict[str, object]]:
    names = [
        "browser_list_tabs",
        "browser_get_active_tab",
        "browser_select_tab",
        "browser_open_tab",
        "browser_close_tab",
        "browser_navigate",
        "browser_go_back",
        "browser_reload",
        "browser_snapshot",
        "browser_query_elements",
        "browser_get_element",
        "browser_debug_dom",
        "browser_click",
        "browser_hover",
        "browser_fill",
        "browser_clear",
        "browser_select_option",
        "browser_press_key",
        "browser_scroll",
        "browser_wait",
        "browser_wait_for_element",
        "browser_wait_for_text",
        "browser_wait_for_navigation",
        "browser_wait_for_disappear",
        "browser_screenshot",
        "browser_download_file",
        "browser_save_text",
        "browser_save_json",
        "browser_save_csv",
        "browser_double_click",
        "browser_scroll_element",
        "browser_execute_script",
        "browser_go_forward",
        "browser_get_cookies",
        "browser_wait_for_url",
        "browser_handle_dialog",
    ]
    read_only = {
        "browser_list_tabs",
        "browser_get_active_tab",
        "browser_snapshot",
        "browser_query_elements",
        "browser_get_element",
        "browser_debug_dom",
        "browser_wait",
        "browser_wait_for_element",
        "browser_wait_for_text",
        "browser_wait_for_navigation",
        "browser_wait_for_disappear",
        "browser_screenshot",
        "browser_get_cookies",
        "browser_wait_for_url",
    }
    zero_arg = {"browser_list_tabs", "browser_get_active_tab"}
    return [
        {
            "name": name,
            "description": name,
            "inputSchema": {
                "type": "object",
                "properties": {} if name in zero_arg else {"arg": {"type": "string"}},
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": name in read_only,
                "idempotentHint": name in read_only,
                "openWorldHint": True,
            },
        }
        for name in names
    ]


def test_mcp_presets_load_from_recruit_agent_assets(tmp_path, monkeypatch) -> None:
    preset_dir = tmp_path / ".recruit-agent" / "mcp" / "presets"
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
        "scene_pilot.services.mcp_registry.mcp_preset_templates_root",
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
        "scene_pilot.services.mcp_registry.default_browser_mcp_server_command",
        lambda: ("node", "/virtual/browser-mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "scene_pilot.services.mcp_registry.default_browser_upstream_endpoint",
        lambda: "/virtual/default-browser.sock",
    )
    monkeypatch.setattr(
        "scene_pilot.services.mcp_registry._mcp_session_request",
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
        assert len(tool_names) >= 30
        assert {
            "browser_list_tabs",
            "browser_get_active_tab",
            "browser_open_tab",
            "browser_navigate",
            "browser_snapshot",
            "browser_execute_script",
            "browser_wait_for_url",
        }.issubset(tool_names)

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
