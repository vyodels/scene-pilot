from __future__ import annotations

import json
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.db.base import utcnow
from scene_pilot.models import McpServer, McpTool
from scene_pilot.repositories import McpServerRepository, McpToolRepository
from scene_pilot.runtime.tools import ToolDefinition, ToolRegistry
from scene_pilot.services.browser_mcp_bridge import (
    BROWSER_SOCKET_PRESET_KEY,
    BrowserMcpBridgeManager,
    default_browser_upstream_endpoint,
    managed_bridge_endpoint,
)


class McpBridgeError(RuntimeError):
    pass


STANDARD_MCP_PROTOCOL = "mcp_jsonrpc"
LEGACY_MCP_TOOL_CALL_PROTOCOL = "json_socket_tool_call"
LEGACY_BROWSER_COMMAND_PROTOCOL = "json_socket_browser_command"
MCP_PROTOCOL_VERSION = "2025-03-26"


def _default_browser_endpoint() -> str:
    return default_browser_upstream_endpoint()


def preset_templates() -> list[dict[str, Any]]:
    return [
        {
            "key": BROWSER_SOCKET_PRESET_KEY,
            "name": "Browser MCP",
            "description": "通过标准 MCP bridge 接入浏览器能力。预置只提供连接信息，工具通过 MCP `tools/list` 动态发现。",
            "transport_kind": "unix_socket",
            "protocol": STANDARD_MCP_PROTOCOL,
            "endpoint_example": _default_browser_endpoint(),
            "tools": [],
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
class _JsonLineSession:
    endpoint: str
    timeout_seconds: float = 8.0
    _connection: socket.socket | None = field(default=None, init=False, repr=False)
    _buffer: bytes = field(default=b"", init=False, repr=False)

    def __enter__(self) -> "_JsonLineSession":
        try:
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.settimeout(self.timeout_seconds)
            connection.connect(self.endpoint)
            self._connection = connection
            self._buffer = b""
            return self
        except FileNotFoundError as exc:
            raise McpBridgeError(f"MCP socket not found: {self.endpoint}") from exc
        except socket.timeout as exc:
            raise McpBridgeError(f"MCP call timed out: {self.endpoint}") from exc
        except OSError as exc:
            raise McpBridgeError(f"MCP unavailable at {self.endpoint}: {exc}") from exc

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None
                self._buffer = b""

    def notify(self, payload: dict[str, Any]) -> None:
        self._send(payload)

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("id") or uuid.uuid4().hex)
        request = {**payload, "id": request_id}
        self._send(request)
        return self._read_response(request_id)

    def _send(self, payload: dict[str, Any]) -> None:
        if self._connection is None:
            raise McpBridgeError("MCP session is not connected")
        try:
            self._connection.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        except socket.timeout as exc:
            raise McpBridgeError(f"MCP call timed out: {self.endpoint}") from exc
        except OSError as exc:
            raise McpBridgeError(f"MCP unavailable at {self.endpoint}: {exc}") from exc

    def _read_response(self, request_id: str) -> dict[str, Any]:
        if self._connection is None:
            raise McpBridgeError("MCP session is not connected")
        while True:
            while b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                response = json.loads(line.decode("utf-8"))
                if str(response.get("id") or "") != request_id:
                    continue
                return response
            try:
                chunk = self._connection.recv(65536)
            except socket.timeout as exc:
                raise McpBridgeError(f"MCP call timed out: {self.endpoint}") from exc
            except OSError as exc:
                raise McpBridgeError(f"MCP unavailable at {self.endpoint}: {exc}") from exc
            if not chunk:
                break
            self._buffer += chunk
        raise McpBridgeError(f"MCP returned no response: {self.endpoint}")


def _raise_for_jsonrpc_error(response: dict[str, Any], *, endpoint: str) -> None:
    error = response.get("error")
    if not isinstance(error, dict):
        return
    message = str(error.get("message") or "MCP request failed")
    raise McpBridgeError(f"{message} ({endpoint})")


def _mcp_session_request(endpoint: str, method: str, params: dict[str, Any] | None = None, *, timeout_seconds: float = 8.0) -> dict[str, Any]:
    with _JsonLineSession(endpoint=endpoint, timeout_seconds=timeout_seconds) as session:
        initialize_response = session.request(
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "scene-pilot", "version": "0.1.0"},
                },
            }
        )
        _raise_for_jsonrpc_error(initialize_response, endpoint=endpoint)
        session.notify({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        response = session.request({"jsonrpc": "2.0", "method": method, "params": dict(params or {})})
    _raise_for_jsonrpc_error(response, endpoint=endpoint)
    result = response.get("result")
    if isinstance(result, dict):
        return result
    return {}


def _mcp_list_tools(endpoint: str) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params = {"cursor": cursor} if cursor else {}
        result = _mcp_session_request(endpoint, "tools/list", params)
        raw_tools = result.get("tools")
        if isinstance(raw_tools, list):
            tools.extend(item for item in raw_tools if isinstance(item, dict))
        next_cursor = result.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor.strip():
            break
        cursor = next_cursor
    return tools


def _mcp_call_tool(endpoint: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    result = _mcp_session_request(endpoint, "tools/call", {"name": tool_name, "arguments": dict(arguments or {})})
    if bool(result.get("isError")):
        content = result.get("content")
        if isinstance(content, list):
            messages = [
                str(item.get("text") or "").strip()
                for item in content
                if isinstance(item, dict) and str(item.get("type") or "") == "text"
            ]
            detail = "\n".join(item for item in messages if item)
        else:
            detail = str(content or "").strip()
        raise McpBridgeError(detail or f"MCP tool failed: {tool_name}")
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    content = result.get("content")
    if isinstance(content, list):
        text_blocks = [
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and str(item.get("type") or "") == "text"
        ]
        if len(text_blocks) == 1:
            text = text_blocks[0]
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        if text_blocks:
            return "\n".join(block for block in text_blocks if block)
    return result


def _tool_has_zero_argument_schema(parameters: dict[str, Any]) -> bool:
    required = parameters.get("required")
    if isinstance(required, list) and required:
        return False
    return parameters.get("type") == "object"


def _normalize_string_list(value: Any) -> list[str]:
    items: list[str] = []
    for raw in list(value or []) if isinstance(value, list) else []:
        text = str(raw).strip()
        if text and text not in items:
            items.append(text)
    return items


def _resolve_runtime_capabilities(server: McpServer, *, read_only: bool) -> list[str]:
    metadata = dict(server.server_metadata or {})
    hints = metadata.get("runtime_tool_capabilities")
    if not isinstance(hints, dict):
        return []
    capabilities = _normalize_string_list(hints.get("default"))
    phase_key = "read_only" if read_only else "mutating"
    for item in _normalize_string_list(hints.get(phase_key)):
        if item not in capabilities:
            capabilities.append(item)
    return capabilities


def _normalize_discovered_tool(server: McpServer, payload: dict[str, Any]) -> dict[str, Any] | None:
    name = str(payload.get("name") or "").strip()
    if not name:
        return None
    annotations = payload.get("annotations") if isinstance(payload.get("annotations"), dict) else {}
    parameters = payload.get("inputSchema") if isinstance(payload.get("inputSchema"), dict) else {"type": "object", "properties": {}, "additionalProperties": True}
    read_only = bool(annotations.get("readOnlyHint"))
    return {
        "name": name,
        "description": str(payload.get("description") or name),
        "parameters": parameters,
        "capabilities": _resolve_runtime_capabilities(server, read_only=read_only),
        "enabled": True,
        "risk_level": "low" if read_only else "medium",
        "remote_name": None,
        "tool_metadata": {
            "external_tool": True,
            "real_environment": True,
            "mcp_annotations": annotations,
        },
    }


@dataclass(slots=True)
class McpRegistryService:
    session_factory: sessionmaker[Session]
    bridge_manager: BrowserMcpBridgeManager | None = None

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

            server_payload = {
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
            if preset_key == BROWSER_SOCKET_PRESET_KEY:
                server_payload["server_metadata"] = self._browser_preset_metadata(
                    server_key=resolved_server_key,
                    upstream_endpoint=resolved_endpoint,
                    existing_metadata=server_payload["server_metadata"],
                )

            server = server_repo.create(server_payload)
            for tool in template["tools"]:
                tool_repo.create({**tool, "server_id": server.id})
            self._best_effort_sync_tools(session, server, tool_repo=tool_repo)
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

            protocol = str(payload.get("protocol") or LEGACY_MCP_TOOL_CALL_PROTOCOL).strip()
            server_key = str(payload.get("server_key") or "").strip()
            endpoint = str(payload.get("endpoint") or "").strip()
            preset_key = str(payload.get("preset_key") or "").strip()
            if preset_key == BROWSER_SOCKET_PRESET_KEY:
                payload["protocol"] = STANDARD_MCP_PROTOCOL
                payload["server_metadata"] = self._browser_preset_metadata(
                    server_key=server_key,
                    upstream_endpoint=endpoint,
                    existing_metadata=payload.get("server_metadata"),
                )

            server = server_repo.create(payload)
            if protocol == STANDARD_MCP_PROTOCOL or payload.get("protocol") == STANDARD_MCP_PROTOCOL:
                self._best_effort_sync_tools(session, server, tool_repo=tool_repo)
            else:
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
            server = self._upgrade_legacy_browser_preset(session, server)

            next_server_key = str(payload.get("server_key") or server.server_key).strip()
            existing = server_repo.by_key(next_server_key)
            if existing is not None and existing.id != server.id:
                raise ValueError("MCP server key already exists")

            next_preset_key = str(payload.get("preset_key") or server.preset_key or "").strip()
            next_endpoint = str(payload.get("endpoint") or server.endpoint).strip()
            if next_preset_key == BROWSER_SOCKET_PRESET_KEY:
                payload["protocol"] = STANDARD_MCP_PROTOCOL
                payload["server_metadata"] = self._browser_preset_metadata(
                    server_key=next_server_key,
                    upstream_endpoint=next_endpoint,
                    existing_metadata={
                        **dict(server.server_metadata or {}),
                        **dict(payload.get("server_metadata") or {}),
                    },
                )

            updated = server_repo.update(server, payload)
            updated = self._upgrade_legacy_browser_preset(session, updated)
            if updated.protocol == STANDARD_MCP_PROTOCOL:
                self._best_effort_sync_tools(session, updated, tool_repo=tool_repo, replace_existing=True)
            elif tools is not None:
                for item in tool_repo.by_server(updated.id):
                    tool_repo.delete(item)
                for tool in list(tools or []):
                    tool_repo.create({**tool, "server_id": updated.id})
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
            server = self._upgrade_legacy_browser_preset(session, server)

            status = "healthy"
            error_message: str | None = None
            try:
                if server.protocol == STANDARD_MCP_PROTOCOL:
                    self._sync_tools_for_server(session, server, tool_repo=tool_repo, replace_existing=True)
                    probe = next(
                        (
                            item
                            for item in tool_repo.by_server(server.id, enabled_only=True)
                            if isinstance(item.parameters, dict) and _tool_has_zero_argument_schema(dict(item.parameters or {}))
                        ),
                        None,
                    )
                    if probe is not None:
                        self.invoke_tool(server, probe, {})
                    else:
                        _ = _mcp_list_tools(self._runtime_endpoint(server))
                elif server.protocol == LEGACY_BROWSER_COMMAND_PROTOCOL:
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
                server = self._upgrade_legacy_browser_preset(session, server)
                if server.protocol == STANDARD_MCP_PROTOCOL:
                    self._best_effort_sync_tools(session, server, tool_repo=tool_repo, replace_existing=True)
                for item in tool_repo.by_server(server.id, enabled_only=True):
                    tools.register(self._to_tool_definition(server, item))

    def reconcile_servers(self) -> None:
        with self.session_factory() as session:
            server_repo = McpServerRepository(session)
            tool_repo = McpToolRepository(session)
            for server in server_repo.list(limit=500, offset=0):
                server = self._upgrade_legacy_browser_preset(session, server)
                if server.protocol == STANDARD_MCP_PROTOCOL:
                    self._best_effort_sync_tools(session, server, tool_repo=tool_repo, replace_existing=True)

    def invoke_tool(self, server: McpServer, tool: McpTool, arguments: dict[str, Any]) -> Any:
        remote_name = str(tool.remote_name or tool.name).strip()
        if server.transport_kind != "unix_socket":
            raise McpBridgeError(f"Unsupported MCP transport: {server.transport_kind}")

        endpoint = self._runtime_endpoint(server)
        if server.protocol == STANDARD_MCP_PROTOCOL:
            return _mcp_call_tool(endpoint, remote_name, arguments)
        if server.protocol == LEGACY_BROWSER_COMMAND_PROTOCOL:
            return _json_socket_request(
                endpoint,
                {
                    "type": "browser_command",
                    "command": {"name": remote_name, "arguments": dict(arguments or {})},
                },
            )
        if server.protocol == LEGACY_MCP_TOOL_CALL_PROTOCOL:
            return _json_socket_request(
                endpoint,
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
                current_server = self._upgrade_legacy_browser_preset(session, current_server)
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

    def _browser_preset_metadata(
        self,
        *,
        server_key: str,
        upstream_endpoint: str,
        existing_metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        metadata = dict(existing_metadata or {})
        metadata.update(
            {
                "preset_installed": True,
                "managed_browser_bridge": True,
                "runtime_endpoint": managed_bridge_endpoint(server_key),
                "upstream_endpoint": upstream_endpoint,
                "runtime_tool_capabilities": {
                    "default": ["browser"],
                    "read_only": ["search", "document"],
                    "mutating": [],
                },
            }
        )
        return metadata

    def _runtime_endpoint(self, server: McpServer) -> str:
        metadata = dict(server.server_metadata or {})
        runtime_endpoint = str(metadata.get("runtime_endpoint") or "").strip()
        if metadata.get("managed_browser_bridge"):
            self._ensure_managed_bridge(server)
            if runtime_endpoint:
                return runtime_endpoint
        return server.endpoint

    def _ensure_managed_bridge(self, server: McpServer) -> None:
        metadata = dict(server.server_metadata or {})
        if not metadata.get("managed_browser_bridge"):
            return
        if self.bridge_manager is None:
            raise McpBridgeError("Managed Browser MCP bridge is unavailable")
        upstream_endpoint = str(server.endpoint or metadata.get("upstream_endpoint") or default_browser_upstream_endpoint()).strip()
        runtime_endpoint = str(metadata.get("runtime_endpoint") or managed_bridge_endpoint(server.server_key)).strip()
        self.bridge_manager.ensure_bridge(
            server_key=server.server_key,
            upstream_endpoint=upstream_endpoint,
            runtime_endpoint=runtime_endpoint,
        )

    def _upgrade_legacy_browser_preset(self, session: Session, server: McpServer) -> McpServer:
        if server.preset_key != BROWSER_SOCKET_PRESET_KEY:
            return server
        target_protocol = STANDARD_MCP_PROTOCOL if server.protocol == LEGACY_BROWSER_COMMAND_PROTOCOL else server.protocol
        target_metadata = self._browser_preset_metadata(
            server_key=server.server_key,
            upstream_endpoint=server.endpoint,
            existing_metadata=server.server_metadata,
        )
        if target_protocol == server.protocol and target_metadata == dict(server.server_metadata or {}):
            return server
        updated = McpServerRepository(session).update(
            server,
            {
                "protocol": target_protocol,
                "server_metadata": target_metadata,
            },
        )
        return updated

    def _discover_tools_for_server(self, server: McpServer) -> list[dict[str, Any]]:
        raw_tools = _mcp_list_tools(self._runtime_endpoint(server))
        discovered: list[dict[str, Any]] = []
        for item in raw_tools:
            normalized = _normalize_discovered_tool(server, item)
            if normalized is not None:
                discovered.append(normalized)
        return discovered

    def _sync_tools_for_server(
        self,
        session: Session,
        server: McpServer,
        *,
        tool_repo: McpToolRepository | None = None,
        replace_existing: bool = True,
    ) -> None:
        if server.protocol != STANDARD_MCP_PROTOCOL:
            return
        repo = tool_repo or McpToolRepository(session)
        existing_tools = repo.by_server(server.id)
        enabled_by_name = {item.name: item.enabled for item in existing_tools}
        discovered = self._discover_tools_for_server(server)
        if replace_existing:
            for item in existing_tools:
                repo.delete(item)
        for tool in discovered:
            repo.create(
                {
                    **tool,
                    "server_id": server.id,
                    "enabled": enabled_by_name.get(str(tool.get("name") or ""), bool(tool.get("enabled", True))),
                }
            )

    def _best_effort_sync_tools(
        self,
        session: Session,
        server: McpServer,
        *,
        tool_repo: McpToolRepository | None = None,
        replace_existing: bool = True,
    ) -> None:
        try:
            self._sync_tools_for_server(session, server, tool_repo=tool_repo, replace_existing=replace_existing)
        except Exception:
            return
