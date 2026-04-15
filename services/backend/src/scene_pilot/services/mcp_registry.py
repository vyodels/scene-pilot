from __future__ import annotations

import json
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.db.base import utcnow
from scene_pilot.models import McpServer, McpTool
from scene_pilot.repositories import McpServerRepository, McpToolRepository
from scene_pilot.runtime.tools import ToolDefinition, ToolRegistry


class McpBridgeError(RuntimeError):
    pass


BROWSER_SOCKET_PRESET_KEY = "browser-json-socket"


def _default_browser_endpoint() -> str:
    import os
    import tempfile

    return os.environ.get("MCP_BROWSER_CHROME_SOCKET") or f"{tempfile.gettempdir()}/browser-mcp.sock"


def preset_templates() -> list[dict[str, Any]]:
    return [
        {
            "key": BROWSER_SOCKET_PRESET_KEY,
            "name": "Browser MCP",
            "description": "通过本地 socket 连接浏览器 MCP，向 runtime 暴露通用浏览器工具。该模板不包含任何 Boss 专用动作。",
            "transport_kind": "unix_socket",
            "protocol": "json_socket_browser_command",
            "endpoint_example": _default_browser_endpoint(),
            "tools": [
                {
                    "name": "browser_list_tabs",
                    "description": "列出当前浏览器已打开的标签页。",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                    "capabilities": ["browser", "document"],
                    "enabled": True,
                    "risk_level": "low",
                    "remote_name": "browser_list_tabs",
                    "tool_metadata": {"external_tool": True, "real_environment": True},
                },
                {
                    "name": "browser_snapshot",
                    "description": "读取指定标签页的结构化页面快照，用于观察真实网页状态。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tabId": {"type": "integer"},
                            "maxTextLength": {"type": "integer"},
                            "interactiveLimit": {"type": "integer"},
                        },
                        "required": ["tabId"],
                        "additionalProperties": False,
                    },
                    "capabilities": ["browser", "document"],
                    "enabled": True,
                    "risk_level": "low",
                    "remote_name": "browser_snapshot",
                    "tool_metadata": {"external_tool": True, "real_environment": True},
                },
                {
                    "name": "browser_execute_script",
                    "description": "在指定标签页执行脚本。仅在真实外部环境中使用，适合由 skill 生成的解析/交互逻辑。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tabId": {"type": "integer"},
                            "script": {"type": "string"},
                        },
                        "required": ["tabId", "script"],
                        "additionalProperties": False,
                    },
                    "capabilities": ["browser", "api", "document", "approval"],
                    "enabled": True,
                    "risk_level": "high",
                    "remote_name": "browser_execute_script",
                    "tool_metadata": {"external_tool": True, "real_environment": True, "writes_state": True},
                },
            ],
        }
    ]


def _json_socket_request(endpoint: str, payload: dict[str, Any], *, timeout_seconds: float = 8.0) -> Any:
    request_id = str(payload.get("id") or uuid.uuid4().hex)
    request = {**payload, "id": request_id}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout_seconds)
            connection.connect(endpoint)
            connection.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            buffer = b""
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    response = json.loads(line.decode("utf-8"))
                    if response.get("id") != request_id:
                        continue
                    if not bool(response.get("ok", False)):
                        error = response.get("error")
                        if isinstance(error, dict):
                            raise McpBridgeError(str(error.get("message") or error))
                        raise McpBridgeError(str(error or "MCP call failed"))
                    return response.get("result")
    except FileNotFoundError as exc:
        raise McpBridgeError(f"MCP socket not found: {endpoint}") from exc
    except socket.timeout as exc:
        raise McpBridgeError(f"MCP call timed out: {endpoint}") from exc
    except OSError as exc:
        raise McpBridgeError(f"MCP unavailable at {endpoint}: {exc}") from exc
    raise McpBridgeError(f"MCP returned no response: {endpoint}")


@dataclass(slots=True)
class McpRegistryService:
    session_factory: sessionmaker[Session]

    def install_preset(
        self,
        preset_key: str,
        *,
        server_key: str | None = None,
        name: str | None = None,
        endpoint: str | None = None,
    ) -> McpServer:
        template = next((item for item in preset_templates() if item["key"] == preset_key), None)
        if template is None:
            raise ValueError("Unknown MCP preset template")

        resolved_server_key = (server_key or preset_key).strip()
        resolved_name = (name or template["name"]).strip()
        resolved_endpoint = (endpoint or template["endpoint_example"]).strip()
        if not resolved_server_key or not resolved_name or not resolved_endpoint:
            raise ValueError("Preset install requires server_key, name, and endpoint")

        with self.session_factory() as session:
            server_repo = McpServerRepository(session)
            tool_repo = McpToolRepository(session)
            existing = server_repo.by_key(resolved_server_key)
            if existing is not None:
                raise ValueError("MCP server key already exists")
            server = server_repo.create(
                {
                    "server_key": resolved_server_key,
                    "name": resolved_name,
                    "transport_kind": template["transport_kind"],
                    "protocol": template["protocol"],
                    "endpoint": resolved_endpoint,
                    "enabled": True,
                    "preset_key": template["key"],
                    "auth_config": {},
                    "server_metadata": {"preset_installed": True},
                }
            )
            for tool in template["tools"]:
                tool_repo.create({**tool, "server_id": server.id})
            return self._serialize_server(session, server.id)

    def list_servers(self) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            repo = McpServerRepository(session)
            return [self._serialize_server_payload(session, item) for item in repo.list(limit=500, offset=0)]

    def create_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        tools = list(payload.pop("tools", []) or [])
        with self.session_factory() as session:
            server_repo = McpServerRepository(session)
            tool_repo = McpToolRepository(session)
            if server_repo.by_key(str(payload.get("server_key") or "").strip()) is not None:
                raise ValueError("MCP server key already exists")
            server = server_repo.create(payload)
            for tool in tools:
                tool_repo.create({**tool, "server_id": server.id})
            return self._serialize_server_payload(session, server)

    def update_server(self, server_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        tools = payload.pop("tools", None)
        with self.session_factory() as session:
            server_repo = McpServerRepository(session)
            tool_repo = McpToolRepository(session)
            server = server_repo.get(server_id)
            if server is None:
                raise ValueError("MCP server not found")
            next_server_key = str(payload.get("server_key") or server.server_key).strip()
            existing = server_repo.by_key(next_server_key)
            if existing is not None and existing.id != server.id:
                raise ValueError("MCP server key already exists")
            updated = server_repo.update(server, payload)
            if tools is not None:
                for item in tool_repo.by_server(server.id):
                    tool_repo.delete(item)
                for tool in list(tools or []):
                    tool_repo.create({**tool, "server_id": server.id})
            return self._serialize_server_payload(session, updated)

    def delete_server(self, server_id: str) -> None:
        with self.session_factory() as session:
            repo = McpServerRepository(session)
            server = repo.get(server_id)
            if server is None:
                raise ValueError("MCP server not found")
            repo.delete(server)

    def healthcheck_server(self, server_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            server_repo = McpServerRepository(session)
            tool_repo = McpToolRepository(session)
            server = server_repo.get(server_id)
            if server is None:
                raise ValueError("MCP server not found")
            status = "healthy"
            error_message: str | None = None
            try:
                if server.protocol == "json_socket_browser_command":
                    _json_socket_request(
                        server.endpoint,
                        {
                            "type": "browser_command",
                            "command": {"name": "browser_list_tabs", "arguments": {}},
                        },
                    )
                else:
                    probe = next((item for item in tool_repo.by_server(server.id, enabled_only=True)), None)
                    if probe is None:
                        raise McpBridgeError("No enabled tools available for health check")
                    self.invoke_tool(server, probe, {})
            except Exception as exc:
                status = "unhealthy"
                error_message = str(exc)
            updated = server_repo.update(
                server,
                {
                    "health_status": status,
                    "health_error": error_message,
                    "last_health_at": utcnow(),
                },
            )
            return self._serialize_server_payload(session, updated)

    def register_enabled_runtime_tools(self, tools: ToolRegistry) -> None:
        with self.session_factory() as session:
            server_repo = McpServerRepository(session)
            tool_repo = McpToolRepository(session)
            for server in server_repo.enabled():
                for item in tool_repo.by_server(server.id, enabled_only=True):
                    tools.register(self._to_tool_definition(server, item))

    def invoke_tool(self, server: McpServer, tool: McpTool, arguments: dict[str, Any]) -> Any:
        remote_name = str(tool.remote_name or tool.name).strip()
        if server.transport_kind != "unix_socket":
            raise McpBridgeError(f"Unsupported MCP transport: {server.transport_kind}")
        if server.protocol == "json_socket_browser_command":
            return _json_socket_request(
                server.endpoint,
                {
                    "type": "browser_command",
                    "command": {"name": remote_name, "arguments": dict(arguments or {})},
                },
            )
        if server.protocol == "json_socket_tool_call":
            return _json_socket_request(
                server.endpoint,
                {
                    "type": "mcp_tool_call",
                    "tool": {"name": remote_name, "arguments": dict(arguments or {})},
                },
            )
        raise McpBridgeError(f"Unsupported MCP protocol: {server.protocol}")

    def _to_tool_definition(self, server: McpServer, tool: McpTool) -> ToolDefinition:
        def _handler(arguments: dict[str, Any], *, server_id: str = server.id, tool_id: str = tool.id) -> Any:
            with self.session_factory() as session:
                current_server = McpServerRepository(session).get(server_id)
                current_tool = McpToolRepository(session).get(tool_id)
                if current_server is None or current_tool is None or not current_server.enabled or not current_tool.enabled:
                    raise McpBridgeError("MCP tool is unavailable or disabled")
                return self.invoke_tool(current_server, current_tool, arguments)

        metadata = {
            **dict(tool.tool_metadata or {}),
            "capabilities": list(tool.capabilities or []),
            "external_tool": True,
            "real_environment": True,
            "mcp_server_id": server.id,
            "mcp_server_key": server.server_key,
            "mcp_tool_id": tool.id,
            "mcp_protocol": server.protocol,
        }
        return ToolDefinition(
            name=tool.name,
            description=tool.description,
            parameters=dict(tool.parameters or {}),
            handler=_handler,
            metadata=metadata,
        )

    def _serialize_server(self, session: Session, server_id: str) -> McpServer:
        server = McpServerRepository(session).get(server_id)
        if server is None:
            raise ValueError("MCP server not found")
        return server

    def _serialize_server_payload(self, session: Session, server: McpServer) -> dict[str, Any]:
        tools = McpToolRepository(session).by_server(server.id)
        return {
            "id": server.id,
            "server_key": server.server_key,
            "name": server.name,
            "transport_kind": server.transport_kind,
            "protocol": server.protocol,
            "endpoint": server.endpoint,
            "enabled": server.enabled,
            "preset_key": server.preset_key,
            "auth_config": dict(server.auth_config or {}),
            "server_metadata": dict(server.server_metadata or {}),
            "health_status": server.health_status,
            "health_error": server.health_error,
            "last_health_at": server.last_health_at,
            "tools": [
                {
                    "id": item.id,
                    "server_id": item.server_id,
                    "name": item.name,
                    "description": item.description,
                    "parameters": dict(item.parameters or {}),
                    "capabilities": list(item.capabilities or []),
                    "enabled": item.enabled,
                    "risk_level": item.risk_level,
                    "remote_name": item.remote_name,
                    "tool_metadata": dict(item.tool_metadata or {}),
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                }
                for item in tools
            ],
            "created_at": server.created_at,
            "updated_at": server.updated_at,
        }
