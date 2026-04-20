from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from scene_pilot.core.settings import AppSettings, load_settings
from scene_pilot.models.domain import McpServer
from scene_pilot.server import create_app
from scene_pilot.services.browser_mcp_bridge import BROWSER_SOCKET_PRESET_KEY
from scene_pilot.services.container import AppContainer


def _settings(tmp_path: Path, name: str) -> AppSettings:
    return AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / name}",
        provider_config={},
    )


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


def test_container_build_registers_enabled_browser_mcp_tools(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "scene_pilot.services.mcp_registry.default_browser_mcp_server_command",
        lambda: ("node", "/virtual/browser-mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "scene_pilot.services.mcp_registry._mcp_list_tools",
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
    assert "browser_get_active_tab" in reloaded.tool_registry.tools
    assert "browser_open_tab" in reloaded.tool_registry.tools
    assert "browser_wait_for_url" in reloaded.tool_registry.tools
    tool = reloaded.tool_registry.tools["browser_get_active_tab"]
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
        "scene_pilot.services.mcp_registry.default_browser_mcp_server_command",
        lambda: ("node", "/virtual/browser-mcp/server.mjs"),
    )
    monkeypatch.setattr(
        "scene_pilot.services.mcp_registry._mcp_list_tools",
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
        "scene_pilot.services.mcp_registry._mcp_call_tool",
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
        assert len(tool_names) >= 30
        assert {"browser_get_active_tab", "browser_open_tab", "browser_wait_for_url"}.issubset(tool_names)

    assert tool_calls
    assert tool_calls[-1]["server_key"] == "browser"
    assert tool_calls[-1]["transport_kind"] == "stdio"
    assert tool_calls[-1]["endpoint"] == upstream
    assert tool_calls[-1]["tool_name"] in {"browser_get_active_tab", "browser_list_tabs"}
    assert tool_calls[-1]["arguments"] == {}
    assert tool_calls[-1]["stdio_env"] == {"MCP_BROWSER_CHROME_SOCKET": upstream}
