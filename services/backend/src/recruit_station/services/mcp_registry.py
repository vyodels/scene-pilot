from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session, sessionmaker

from recruit_station.asset_paths import mcp_preset_templates_root
from recruit_station.db.base import unix_seconds_now, utcnow
from recruit_station.models import McpServer, McpTool
from recruit_station.repositories import McpServerRepository, McpToolRepository
from recruit_station.capabilities.tools import ToolDefinition, ToolRegistry
from recruit_station.services.browser_mcp_bridge import (
    BROWSER_SOCKET_PRESET_KEY,
    default_browser_mcp_server_command,
    default_browser_upstream_endpoint,
    run_mcp_stdio_request,
)


class McpBridgeError(RuntimeError):
    pass


STANDARD_MCP_PROTOCOL = "mcp_jsonrpc"
LEGACY_MCP_TOOL_CALL_PROTOCOL = "json_socket_tool_call"
LEGACY_BROWSER_COMMAND_PROTOCOL = "json_socket_browser_command"
MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_STDIO_REQUEST_TIMEOUT_SECONDS = 8.0
MCP_HID_ACTION_TIMEOUT_BUFFER_SECONDS = 6.0
MCP_HID_ACTION_MAX_TIMEOUT_SECONDS = 60.0
MCP_TRANSIENT_RETRY_DELAY_SECONDS = 0.35
VIRTUALHID_SOCKET_PRESET_KEY = "virtualhid-json-socket"
MCP_RESOURCE_TOOL_NAMES = {"list_mcp_resources", "read_mcp_resource"}
BUILTIN_MCP_SERVER_SPECS: tuple[tuple[str, str, str], ...] = (
    (BROWSER_SOCKET_PRESET_KEY, "browser-mcp", "Browser MCP"),
    (VIRTUALHID_SOCKET_PRESET_KEY, "virtualhid", "VirtualHID MCP"),
)
_VIRTUALHID_MCP_SERVER_ENV = "VIRTUALHID_MCP_SERVER"
_VIRTUALHID_MCP_COMMAND_ENV = "VIRTUALHID_MCP_COMMAND"
_KNOWN_STDIO_COMMAND_RESOLVERS = {"browser_mcp_server", "virtualhid_mcp_server"}
_BROWSER_HID_TOOL_LOCK = threading.RLock()
_BROWSER_HID_SEQUENCE_STATE: dict[str, dict[str, Any]] = {}
_BROWSER_TARGET_IDENTIFICATION_TOOL_NAMES = {
    "browser_list_tabs",
    "browser_get_active_tab",
}
_BROWSER_OBSERVATION_TOOL_NAMES = {
    "browser_snapshot",
    "browser_query_elements",
    "browser_get_element",
    "browser_debug_dom",
    "browser_wait_for_element",
    "browser_wait_for_text",
    "browser_wait_for_navigation",
    "browser_wait_for_disappear",
    "browser_wait_for_url",
}
_BROWSER_READ_ONLY_RUNTIME_TOOL_NAMES = set(_BROWSER_TARGET_IDENTIFICATION_TOOL_NAMES) | set(_BROWSER_OBSERVATION_TOOL_NAMES)
_HID_BROWSER_SEQUENCE_PRIMITIVE_TYPES = {"click", "drag", "scroll", "type", "pasteText", "key"}


@dataclass(slots=True)
class _ConfiguredMcpServer:
    id: str
    server_key: str
    name: str
    transport_kind: str
    protocol: str
    endpoint: str
    enabled: bool
    preset_key: str | None
    auth_config: dict[str, Any]
    server_metadata: dict[str, Any]
    health_status: str = "unknown"
    health_error: str | None = None
    last_health_at: int | None = None
    created_at: int = 0
    updated_at: int = 0


def _default_browser_endpoint() -> str:
    return default_browser_upstream_endpoint()


def default_virtualhid_upstream_endpoint() -> str:
    return os.environ.get("VIRTUALHID_SOCKET") or str(
        Path.home() / "Library" / "Application Support" / "VirtualHID" / "virtualhid.sock"
    )


def _reset_browser_hid_sequence_state_for_tests() -> None:
    with _BROWSER_HID_TOOL_LOCK:
        _BROWSER_HID_SEQUENCE_STATE.clear()


def default_virtualhid_mcp_server_command() -> tuple[str, ...] | None:
    command_override = str(os.environ.get(_VIRTUALHID_MCP_COMMAND_ENV) or "").strip()
    if command_override:
        command = tuple(part.strip() for part in shlex.split(command_override) if part.strip())
        return command or None

    script_path = _discover_virtualhid_mcp_server_script()
    node_path = shutil.which("node")
    if script_path is None or node_path is None:
        return None
    return (node_path, script_path)


def _discover_virtualhid_mcp_server_script() -> str | None:
    override = str(os.environ.get(_VIRTUALHID_MCP_SERVER_ENV) or "").strip()
    if override:
        return override
    return _discover_local_mcp_server_script("VirtualHID")


def _discover_local_mcp_server_script(repo_dir_name: str) -> str | None:
    current = Path(__file__).resolve()
    candidates: list[Path] = []
    seen: set[str] = set()
    for ancestor in current.parents:
        for candidate in (
            ancestor / repo_dir_name / "mcp" / "server.mjs",
            ancestor.parent / repo_dir_name / "mcp" / "server.mjs",
        ):
            candidate_key = str(candidate)
            if candidate_key in seen:
                continue
            seen.add(candidate_key)
            candidates.append(candidate)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _default_endpoint_for_preset(preset_key: str) -> str:
    if preset_key == BROWSER_SOCKET_PRESET_KEY:
        return _default_browser_endpoint()
    if preset_key == VIRTUALHID_SOCKET_PRESET_KEY:
        return default_virtualhid_upstream_endpoint()
    return ""


def _resolve_stdio_command_from_resolver(resolver_name: str) -> list[str]:
    normalized = str(resolver_name or "").strip()
    if not normalized:
        return []
    if normalized == "browser_mcp_server":
        return list(default_browser_mcp_server_command() or [])
    if normalized == "virtualhid_mcp_server":
        return list(default_virtualhid_mcp_server_command() or [])
    raise ValueError(f"Unknown MCP stdio command resolver: {normalized}")


def _normalize_preset_stdio_command_resolver(value: Any) -> str:
    resolver = str(value or "").strip()
    if resolver and resolver not in _KNOWN_STDIO_COMMAND_RESOLVERS:
        raise ValueError(f"Invalid MCP preset asset: unknown stdio_command_resolver={resolver}")
    return resolver


def _normalize_runtime_tool_capability_hints(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    hints = {
        "default": _normalize_string_list(value.get("default")),
        "read_only": _normalize_string_list(value.get("read_only")),
        "mutating": _normalize_string_list(value.get("mutating")),
    }
    if not any(hints.values()):
        return {}
    return hints


def _interpolate_preset_value(value: Any, *, endpoint: str) -> Any:
    if isinstance(value, str):
        return value.replace("${endpoint}", endpoint)
    if isinstance(value, list):
        return [_interpolate_preset_value(item, endpoint=endpoint) for item in value]
    if isinstance(value, dict):
        return {
            str(key).strip(): _interpolate_preset_value(item, endpoint=endpoint)
            for key, item in value.items()
            if str(key).strip()
        }
    return value


def _resolve_preset_server_metadata(
    template: dict[str, Any],
    *,
    endpoint: str,
    existing_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = dict(existing_metadata or {})
    metadata["preset_installed"] = True

    for key in _normalize_string_list(template.get("metadata_remove_keys")):
        metadata.pop(key, None)

    if str(template.get("transport_kind") or "").strip() == "stdio":
        stdio_command = _normalize_string_list(metadata.get("stdio_command"))
        if not stdio_command:
            template_command = _normalize_string_list(_interpolate_preset_value(template.get("stdio_command"), endpoint=endpoint))
            if template_command:
                stdio_command = template_command
            else:
                stdio_command = _resolve_stdio_command_from_resolver(template.get("stdio_command_resolver"))
        stdio_env = _normalize_string_dict(metadata.get("stdio_env"))
        stdio_env.update(_normalize_string_dict(_interpolate_preset_value(template.get("stdio_env"), endpoint=endpoint)))
        metadata["stdio_command"] = stdio_command
        metadata["stdio_env"] = stdio_env

    runtime_tool_capabilities = _normalize_runtime_tool_capability_hints(template.get("runtime_tool_capabilities"))
    if runtime_tool_capabilities:
        metadata["runtime_tool_capabilities"] = runtime_tool_capabilities

    read_only_names = _normalize_string_list(template.get("runtime_tool_read_only_names"))
    if read_only_names:
        metadata["runtime_tool_read_only_names"] = read_only_names

    return metadata


def _apply_preset_server_defaults(
    template: dict[str, Any],
    *,
    endpoint: str,
    existing_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "transport_kind": template["transport_kind"],
        "protocol": template["protocol"],
        "server_metadata": _resolve_preset_server_metadata(
            template,
            endpoint=endpoint,
            existing_metadata=existing_metadata,
        ),
    }


def _standard_mcp_server_config(server: McpServer) -> dict[str, Any]:
    metadata = dict(server.server_metadata or {})
    if server.transport_kind == "stdio":
        command = _normalize_string_list(metadata.get("stdio_command"))
        config: dict[str, Any] = {}
        if command:
            config["command"] = command[0]
            config["args"] = command[1:]
        env = _normalize_string_dict(metadata.get("stdio_env"))
        if env:
            config["env"] = env
        config["transport"] = "stdio"
        return {"mcpServers": {server.server_key: config}}

    parsed = urlparse(str(server.endpoint or ""))
    if parsed.scheme in {"http", "https"}:
        return {"mcpServers": {server.server_key: {"url": server.endpoint}}}
    return {
        "mcpServers": {
            server.server_key: {
                "transport": server.transport_kind,
                "endpoint": server.endpoint,
            }
        }
    }


def _configured_server_from_payload(payload: dict[str, Any]) -> _ConfiguredMcpServer:
    return _ConfiguredMcpServer(
        id=str(payload["id"]),
        server_key=str(payload["server_key"]),
        name=str(payload["name"]),
        transport_kind=str(payload["transport_kind"]),
        protocol=str(payload["protocol"]),
        endpoint=str(payload["endpoint"]),
        enabled=bool(payload.get("enabled", True)),
        preset_key=str(payload.get("preset_key") or "") or None,
        auth_config=dict(payload.get("auth_config") or {}),
        server_metadata=dict(payload.get("server_metadata") or {}),
        health_status=str(payload.get("health_status") or "unknown"),
        health_error=str(payload.get("health_error") or "") or None,
        last_health_at=payload.get("last_health_at"),
        created_at=int(payload.get("created_at") or 0),
        updated_at=int(payload.get("updated_at") or 0),
    )


def _configured_builtin_server_payloads(
    *,
    exclude_keys: set[str] | None = None,
    exclude_preset_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded = {str(item).strip() for item in set(exclude_keys or set()) if str(item).strip()}
    excluded_presets = {str(item).strip() for item in set(exclude_preset_keys or set()) if str(item).strip()}
    payloads: list[dict[str, Any]] = []
    for preset_key, server_key, name in BUILTIN_MCP_SERVER_SPECS:
        if server_key in excluded or preset_key in excluded_presets:
            continue
        template = _preset_template_by_key(preset_key)
        if template is None:
            continue
        endpoint = _default_endpoint_for_preset(preset_key) or str(template.get("endpoint_example") or "").strip()
        server_payload = {
            "id": f"builtin:{server_key}",
            "server_key": server_key,
            "name": name,
            "transport_kind": template["transport_kind"],
            "protocol": template["protocol"],
            "endpoint": endpoint,
            "enabled": True,
            "preset_key": preset_key,
            "auth_config": {},
            "server_metadata": {"builtin": True},
            "health_status": "unknown",
            "health_error": None,
            "last_health_at": None,
            "created_at": 0,
            "updated_at": 0,
        }
        server_payload.update(
            _apply_preset_server_defaults(
                template,
                endpoint=endpoint,
                existing_metadata=server_payload["server_metadata"],
            )
        )
        server_payload["standard_config"] = _standard_mcp_server_config(_configured_server_from_payload(server_payload))  # type: ignore[arg-type]
        payloads.append(server_payload)
    return payloads


def _configured_builtin_server_by_ref(ref: str) -> _ConfiguredMcpServer | None:
    normalized = str(ref or "").strip()
    if not normalized:
        return None
    for payload in _configured_builtin_server_payloads():
        if normalized in {payload["id"], payload["server_key"], str(payload.get("preset_key") or "")}:
            return _configured_server_from_payload(payload)
    return None


def _preset_template_by_key(preset_key: str) -> dict[str, Any] | None:
    normalized = str(preset_key or "").strip()
    if not normalized:
        return None
    return next((item for item in preset_templates() if item["key"] == normalized), None)


def _load_preset_template_asset(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid MCP preset asset at {path}")

    template = {
        "key": str(payload.get("key") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "description": str(payload.get("description") or "").strip(),
        "transport_kind": str(payload.get("transport_kind") or "").strip(),
        "protocol": str(payload.get("protocol") or "").strip(),
        "endpoint_example": str(payload.get("endpoint_example") or "").strip(),
        "stdio_command": _normalize_string_list(payload.get("stdio_command")),
        "stdio_command_resolver": _normalize_preset_stdio_command_resolver(payload.get("stdio_command_resolver")),
        "stdio_env": _normalize_string_dict(payload.get("stdio_env")),
        "runtime_tool_capabilities": _normalize_runtime_tool_capability_hints(payload.get("runtime_tool_capabilities")),
        "runtime_tool_read_only_names": _normalize_string_list(payload.get("runtime_tool_read_only_names")),
        "metadata_remove_keys": _normalize_string_list(payload.get("metadata_remove_keys")),
        "tools": [dict(item) for item in list(payload.get("tools") or []) if isinstance(item, dict)],
    }
    if not template["endpoint_example"]:
        template["endpoint_example"] = _default_endpoint_for_preset(template["key"])
    required_fields = ("key", "name", "description", "transport_kind", "protocol", "endpoint_example")
    missing_fields = [field for field in required_fields if not str(template.get(field) or "").strip()]
    if missing_fields:
        missing = ", ".join(missing_fields)
        raise ValueError(f"Invalid MCP preset asset at {path}: missing {missing}")
    return template


def preset_templates() -> list[dict[str, Any]]:
    preset_root = mcp_preset_templates_root()
    if not preset_root.exists():
        return []
    return [_load_preset_template_asset(path) for path in sorted(preset_root.glob("*.json")) if path.is_file()]


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


def _raise_for_jsonrpc_error(response: dict[str, Any], *, label: str) -> None:
    error = response.get("error")
    if not isinstance(error, dict):
        return
    message = str(error.get("message") or "MCP request failed")
    raise McpBridgeError(f"{message} ({label})")


def _is_method_not_found_for(exc: Exception, method: str) -> bool:
    message = str(exc).lower()
    return method.lower() in message and ("method not found" in message or "unknown method" in message)


@dataclass(slots=True)
class _JsonLineSession:
    endpoint: str
    timeout_seconds: float = 8.0

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(self.endpoint)
                initialize_response = self._send_request(
                    connection,
                    {
                        "jsonrpc": "2.0",
                        "method": "initialize",
                        "params": {
                            "protocolVersion": MCP_PROTOCOL_VERSION,
                            "capabilities": {},
                            "clientInfo": {"name": "recruit-station", "version": "0.1.0"},
                        },
                    },
                )
                _raise_for_jsonrpc_error(initialize_response, label=self.endpoint)
                connection.sendall(
                    (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, ensure_ascii=False) + "\n").encode(
                        "utf-8"
                    )
                )
                response = self._send_request(
                    connection,
                    {"jsonrpc": "2.0", "method": method, "params": dict(params or {})},
                )
        except FileNotFoundError as exc:
            raise McpBridgeError(f"MCP socket not found: {self.endpoint}") from exc
        except socket.timeout as exc:
            raise McpBridgeError(f"MCP call timed out: {self.endpoint}") from exc
        except OSError as exc:
            raise McpBridgeError(f"MCP unavailable at {self.endpoint}: {exc}") from exc
        _raise_for_jsonrpc_error(response, label=self.endpoint)
        result = response.get("result")
        if isinstance(result, dict):
            return result
        return {}

    def _send_request(self, connection: socket.socket, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("id") or uuid.uuid4().hex)
        request = {**payload, "id": request_id}
        connection.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        buffer = b""
        while True:
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                response = json.loads(line.decode("utf-8"))
                if str(response.get("id") or "") != request_id:
                    continue
                return response
            chunk = connection.recv(65536)
            if not chunk:
                break
            buffer += chunk
        raise McpBridgeError(f"MCP returned no response: {self.endpoint}")


def _normalize_string_list(value: Any) -> list[str]:
    items: list[str] = []
    for raw in list(value or []) if isinstance(value, list) else []:
        text = str(raw).strip()
        if text and text not in items:
            items.append(text)
    return items


def _normalize_string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    items: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key:
            continue
        items[key] = str(raw_value)
    return items


def _mcp_session_request(
    server: McpServer,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = MCP_STDIO_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if server.transport_kind == "unix_socket":
        return _JsonLineSession(endpoint=server.endpoint, timeout_seconds=timeout_seconds).request(method, params)
    if server.transport_kind == "stdio":
        metadata = dict(server.server_metadata or {})
        command = _normalize_string_list(metadata.get("stdio_command"))
        env = _normalize_string_dict(metadata.get("stdio_env"))
        try:
            return run_mcp_stdio_request(
                command,
                method=method,
                params=params,
                env=env,
                timeout_seconds=timeout_seconds,
                command_label=str(server.server_key or server.name or "mcp-stdio"),
            )
        except RuntimeError as exc:
            raise McpBridgeError(str(exc)) from exc
    raise McpBridgeError(f"Unsupported MCP transport: {server.transport_kind}")


def _mcp_list_tools(server: McpServer) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params = {"cursor": cursor} if cursor else {}
        result = _mcp_session_request(server, "tools/list", params)
        raw_tools = result.get("tools")
        if isinstance(raw_tools, list):
            tools.extend(item for item in raw_tools if isinstance(item, dict))
        next_cursor = result.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor.strip():
            break
        cursor = next_cursor
    return tools


def _mcp_list_resources(server: McpServer) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params = {"cursor": cursor} if cursor else {}
        try:
            result = _mcp_session_request(server, "resources/list", params)
        except McpBridgeError as exc:
            if _is_method_not_found_for(exc, "resources/list"):
                return []
            raise
        raw_resources = result.get("resources")
        if isinstance(raw_resources, list):
            resources.extend(item for item in raw_resources if isinstance(item, dict))
        next_cursor = result.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor.strip():
            break
        cursor = next_cursor
    return resources


def _mcp_read_resource(server: McpServer, uri: str) -> dict[str, Any]:
    return _mcp_session_request(server, "resources/read", {"uri": uri})


def _mcp_call_tool(server: McpServer, tool_name: str, arguments: dict[str, Any]) -> Any:
    result = _mcp_session_request(
        server,
        "tools/call",
        {"name": tool_name, "arguments": dict(arguments or {})},
        timeout_seconds=_mcp_tool_timeout_seconds(tool_name, arguments),
    )
    structured = result.get("structuredContent")
    if bool(result.get("isError")):
        if structured is not None:
            if isinstance(structured, dict):
                return {**structured, "isError": True}
            return {"isError": True, "structuredContent": structured}
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


def _mcp_tool_timeout_seconds(tool_name: str, arguments: dict[str, Any]) -> float:
    if str(tool_name or "") != "hid_action":
        return MCP_STDIO_REQUEST_TIMEOUT_SECONDS
    timeout_ms = _hid_action_timeout_ms(arguments)
    if timeout_ms <= 0:
        return max(MCP_STDIO_REQUEST_TIMEOUT_SECONDS, 20.0)
    requested_seconds = timeout_ms / 1000.0 + MCP_HID_ACTION_TIMEOUT_BUFFER_SECONDS
    return min(max(MCP_STDIO_REQUEST_TIMEOUT_SECONDS, requested_seconds), MCP_HID_ACTION_MAX_TIMEOUT_SECONDS)


def _hid_action_timeout_ms(arguments: dict[str, Any]) -> int:
    options = arguments.get("options")
    if not isinstance(options, dict):
        return 0
    value = options.get("timeoutMs") or options.get("timeout_ms")
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _is_transient_mcp_error(error: BaseException) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "transport closed",
            "socket not found",
            "connect enoent",
            "connection refused",
            "timed out",
            "returned no response",
            "mcp unavailable",
            "native host unavailable",
        )
    )


def _normalize_mcp_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return dict(arguments or {})


def _tool_has_zero_argument_schema(parameters: dict[str, Any]) -> bool:
    required = parameters.get("required")
    if isinstance(required, list) and required:
        return False
    properties = parameters.get("properties")
    if isinstance(properties, dict) and properties:
        return False
    return parameters.get("type") == "object"


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


def _tool_read_only_hint(server: McpServer, name: str, annotations: dict[str, Any]) -> bool:
    if bool(annotations.get("readOnlyHint")):
        return True
    metadata = dict(server.server_metadata or {})
    return name in _normalize_string_list(metadata.get("runtime_tool_read_only_names"))


def _mcp_runtime_capability_names(server: McpServer) -> set[str]:
    metadata = dict(server.server_metadata or {})
    hints = metadata.get("runtime_tool_capabilities")
    capabilities: set[str] = set()
    if isinstance(hints, dict):
        for key in ("default", "read_only", "mutating"):
            capabilities.update(_normalize_string_list(hints.get(key)))
    return capabilities


def _is_browser_mcp_tool(server: McpServer, tool_name: str) -> bool:
    name = str(tool_name or "").strip()
    if name.startswith("browser_"):
        return True
    if str(server.server_key or "").strip() == BROWSER_SOCKET_PRESET_KEY:
        return True
    if str(server.preset_key or "").strip() == BROWSER_SOCKET_PRESET_KEY:
        return True
    return bool(_mcp_runtime_capability_names(server) & {"browser", "document"})


def _is_virtualhid_mcp_tool(server: McpServer, tool_name: str) -> bool:
    name = str(tool_name or "").strip()
    if name.startswith("hid_"):
        return True
    if str(server.server_key or "").strip() == VIRTUALHID_SOCKET_PRESET_KEY:
        return True
    if str(server.preset_key or "").strip() == VIRTUALHID_SOCKET_PRESET_KEY:
        return True
    return bool(_mcp_runtime_capability_names(server) & {"computer", "computer_read", "computer_write", "hid", "virtualhid"})


def _requires_linear_browser_hid_execution(server: McpServer, tool_name: str) -> bool:
    return _is_browser_mcp_tool(server, tool_name) or _is_virtualhid_mcp_tool(server, tool_name)


def _is_browser_observation_tool(server: McpServer, tool_name: str) -> bool:
    name = str(tool_name or "").strip()
    return _is_browser_mcp_tool(server, name) and name in _BROWSER_OBSERVATION_TOOL_NAMES


def _is_browser_target_identification_tool(server: McpServer, tool_name: str) -> bool:
    name = str(tool_name or "").strip()
    return _is_browser_mcp_tool(server, name) and name in _BROWSER_TARGET_IDENTIFICATION_TOOL_NAMES


def _hid_action_targets_browser(arguments: dict[str, Any]) -> bool:
    target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
    context = arguments.get("context") if isinstance(arguments.get("context"), dict) else {}
    geometry = arguments.get("geometry") if isinstance(arguments.get("geometry"), dict) else {}
    if str(target.get("host") or context.get("host") or "").strip():
        return True
    if str(context.get("url") or "").strip():
        return True
    if target.get("tabId") is not None or target.get("tab_id") is not None:
        return True
    return str(geometry.get("coordSpace") or "").strip() in {"viewport", "document"}


def _hid_action_has_browser_sequence_primitive(arguments: dict[str, Any]) -> bool:
    primitives = arguments.get("primitives")
    if not isinstance(primitives, list):
        return False
    for primitive in primitives:
        if not isinstance(primitive, dict):
            continue
        if str(primitive.get("type") or "").strip() in _HID_BROWSER_SEQUENCE_PRIMITIVE_TYPES:
            return True
    return False


def _hid_action_uses_browser_address_bar_navigation(arguments: dict[str, Any]) -> bool:
    primitives = arguments.get("primitives")
    if not isinstance(primitives, list):
        return False
    return any(_is_address_bar_focus_primitive(primitive) for primitive in primitives if isinstance(primitive, dict))


def _is_address_bar_focus_primitive(primitive: dict[str, Any]) -> bool:
    if str(primitive.get("type") or "").strip() != "key":
        return False
    key_code = primitive.get("keyCode")
    virtual_key = primitive.get("virtualKey")
    if str(key_code) != "37" and str(virtual_key) != "37":
        return False
    return _has_command_modifier(primitive.get("modifiers"))


def _has_command_modifier(value: Any) -> bool:
    if isinstance(value, list):
        return any(str(item).strip().lower() in {"cmd", "command", "meta"} for item in value)
    if isinstance(value, str):
        return value.strip().lower() in {"cmd", "command", "meta"}
    if isinstance(value, dict):
        return any(bool(value.get(key)) for key in ("cmd", "command", "meta"))
    return False


def _hid_action_can_use_target_identification(arguments: dict[str, Any]) -> bool:
    primitives = arguments.get("primitives")
    if not isinstance(primitives, list) or not primitives:
        return False
    allowed = {"key", "pasteText", "type"}
    for primitive in primitives:
        if not isinstance(primitive, dict):
            return False
        if str(primitive.get("type") or "").strip() not in allowed:
            return False
    return True


def _is_browser_hid_sequence_action(server: McpServer, tool_name: str, arguments: dict[str, Any]) -> bool:
    if not _is_virtualhid_mcp_tool(server, tool_name):
        return False
    if str(tool_name or "").strip() != "hid_action":
        return False
    return _hid_action_targets_browser(arguments) and _hid_action_has_browser_sequence_primitive(arguments)


def _browser_hid_sequence_scope_key(arguments: dict[str, Any], result: Any | None = None) -> str | None:
    target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
    context = arguments.get("context") if isinstance(arguments.get("context"), dict) else {}
    options = arguments.get("options") if isinstance(arguments.get("options"), dict) else {}
    metadata = arguments.get("metadata") if isinstance(arguments.get("metadata"), dict) else {}
    run_id = _first_scope_value(
        arguments.get("run_id"),
        arguments.get("runId"),
        arguments.get("run_pk"),
        context.get("run_id"),
        context.get("runId"),
        context.get("run_pk"),
        options.get("run_id"),
        metadata.get("run_id"),
        _result_path(result, "run_id"),
        _result_path(result, "runId"),
    )
    episode_id = _first_scope_value(
        arguments.get("episode_id"),
        arguments.get("episodeId"),
        context.get("episode_id"),
        context.get("episodeId"),
        target.get("episode_id"),
        target.get("episodeId"),
        options.get("episode_id"),
        metadata.get("episode_id"),
        _result_path(result, "episode_id"),
        _result_path(result, "episodeId"),
    )
    account = _first_scope_value(
        arguments.get("account"),
        arguments.get("account_id"),
        arguments.get("site_account"),
        context.get("account"),
        context.get("account_id"),
        context.get("site_account"),
        target.get("account"),
        target.get("account_id"),
        metadata.get("account"),
        _result_path(result, "account"),
    )
    host = _most_specific_scope_host(
        [
            target.get("host"),
            context.get("host"),
            _host_from_url(target.get("url")),
            _host_from_url(context.get("url")),
            _host_from_url(arguments.get("url")),
            _host_from_url(arguments.get("expectedOrigin")),
            _host_from_url(arguments.get("expected_origin")),
            _host_from_url(arguments.get("targetOrigin")),
            _host_from_url(arguments.get("target_origin")),
            arguments.get("expectedHost"),
            arguments.get("expected_host"),
            arguments.get("host"),
            _result_host(result),
        ]
    )
    if not any((run_id, episode_id, account, host)):
        return None
    return "|".join(
        (
            f"run={run_id or 'unspecified'}",
            f"episode={episode_id or 'unspecified'}",
            f"account={account or 'unspecified'}",
            f"host={_normalize_scope_host(host) or 'unspecified'}",
        )
    )


def _first_scope_value(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _most_specific_scope_host(values: list[Any]) -> str | None:
    selected: str | None = None
    for value in values:
        host = _normalize_scope_host(value)
        if not host:
            continue
        if selected is None:
            selected = host
            continue
        if _scope_hostnames_match(selected, host) and _scope_host_has_explicit_port(host) and not _scope_host_has_explicit_port(selected):
            selected = host
    return selected


def _scope_hostnames_match(left: Any, right: Any) -> bool:
    left_name = _scope_hostname_part(left)
    right_name = _scope_hostname_part(right)
    return bool(left_name and right_name and left_name == right_name)


def _scope_hostname_part(value: Any) -> str | None:
    host = _normalize_scope_host(_host_from_url(value) or value)
    if not host:
        return None
    try:
        parsed = urlparse(f"//{host}")
        return parsed.hostname.lower() if parsed.hostname else None
    except ValueError:
        return host.split(":", 1)[0].lower() if ":" in host else host.lower()


def _scope_host_has_explicit_port(value: Any) -> bool:
    host = _normalize_scope_host(_host_from_url(value) or value)
    if not host:
        return False
    try:
        return urlparse(f"//{host}").port is not None
    except ValueError:
        return ":" in host


def _host_from_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = parsed.netloc or parsed.path.split("/", 1)[0]
    return _normalize_scope_host(host)


def _normalize_scope_host(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def _result_path(result: Any, key: str) -> Any:
    if not isinstance(result, dict):
        return None
    if key in result:
        return result.get(key)
    for container_key in ("snapshot", "target", "tab", "context", "metadata"):
        container = result.get(container_key)
        if isinstance(container, dict) and key in container:
            return container.get(key)
    return None


def _result_host(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    for candidate in (
        _result_path(result, "host"),
        _host_from_url(_result_path(result, "url")),
    ):
        host = _normalize_scope_host(candidate)
        if host:
            return host
    tabs = result.get("tabs")
    if isinstance(tabs, list):
        for tab in [item for item in tabs if isinstance(item, dict) and item.get("active")] or [item for item in tabs if isinstance(item, dict)][:1]:
            host = _normalize_scope_host(tab.get("host")) or _host_from_url(tab.get("url"))
            if host:
                return host
    return None


def _result_browser_target_context(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    candidates = _browser_result_tab_candidates(result)
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
    target = result.get("target") if isinstance(result.get("target"), dict) else {}
    active = candidates[0] if candidates else {}
    host = _normalize_scope_host(active.get("host")) or _normalize_scope_host(target.get("host")) or _result_host(result)
    url = active.get("url") or target.get("url") or snapshot.get("url") or _result_path(result, "url")
    tab_id = active.get("tabId") or active.get("tab_id") or active.get("id") or target.get("tabId") or target.get("tab_id") or result.get("tabId") or result.get("tab_id")
    window_id = active.get("windowId") or active.get("window_id") or target.get("windowId") or target.get("window_id") or result.get("windowId") or result.get("window_id")
    window_title = active.get("windowTitle") or active.get("window_title") or target.get("windowTitle") or target.get("window_title") or active.get("title") or target.get("title") or snapshot.get("title")
    viewport = _browser_result_viewport(result, active=active, target=target, snapshot=snapshot)
    bounds = _browser_result_window_bounds(result, active=active, target=target, snapshot=snapshot, viewport=viewport)
    context = {
        key: value
        for key, value in {
            "host": host,
            "url": url,
            "tabId": tab_id,
            "windowId": window_id,
            "windowTitle": window_title,
            "browserWindowBounds": bounds,
            "viewport": viewport,
        }.items()
        if value not in (None, "", {})
    }
    return context


def _browser_result_tab_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in ("target", "tab"):
        value = result.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    tabs = result.get("tabs")
    if isinstance(tabs, list):
        tab_dicts = [item for item in tabs if isinstance(item, dict)]
        candidates.extend([item for item in tab_dicts if item.get("active")])
        candidates.extend([item for item in tab_dicts if not item.get("active")])
    if any(key in result for key in ("id", "tabId", "tab_id", "url", "title", "windowId", "window_id", "host")):
        candidates.append(result)
    return candidates


def _browser_result_viewport(
    result: dict[str, Any],
    *,
    active: dict[str, Any],
    target: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    for candidate in (
        active.get("viewport"),
        target.get("viewport"),
        snapshot.get("viewport"),
        result.get("viewport"),
    ):
        viewport = candidate if isinstance(candidate, dict) else None
        if viewport:
            return viewport
    return None


def _browser_result_window_bounds(
    result: dict[str, Any],
    *,
    active: dict[str, Any],
    target: dict[str, Any],
    snapshot: dict[str, Any],
    viewport: dict[str, Any] | None,
) -> dict[str, Any] | None:
    for candidate in (
        active.get("browserWindowBounds"),
        active.get("browser_window_bounds"),
        active.get("windowBounds"),
        active.get("window_bounds"),
        target.get("browserWindowBounds"),
        target.get("browser_window_bounds"),
        target.get("windowBounds"),
        target.get("window_bounds"),
        result.get("browserWindowBounds"),
        result.get("browser_window_bounds"),
        result.get("windowBounds"),
        result.get("window_bounds"),
        _browser_window_bounds_from_window(active.get("window")),
        _browser_window_bounds_from_window(target.get("window")),
        _browser_window_bounds_from_window(result.get("window")),
        _browser_window_bounds_from_viewport(viewport),
        _browser_window_bounds_from_viewport(snapshot.get("viewport")),
    ):
        bounds = _normalize_browser_window_bounds(candidate)
        if bounds:
            return bounds
    return None


def _browser_window_bounds_from_window(window: Any) -> dict[str, Any] | None:
    if not isinstance(window, dict):
        return None
    return _normalize_browser_window_bounds(
        {
            "x": window.get("left"),
            "y": window.get("top"),
            "width": window.get("width"),
            "height": window.get("height"),
        }
    )


def _browser_window_bounds_from_viewport(viewport: Any) -> dict[str, Any] | None:
    if not isinstance(viewport, dict):
        return None
    return _normalize_browser_window_bounds(
        {
            "x": viewport.get("screenX"),
            "y": viewport.get("screenY"),
            "width": viewport.get("outerWidth"),
            "height": viewport.get("outerHeight"),
        }
    )


def _normalize_browser_window_bounds(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    x = _optional_float(value.get("x") if value.get("x") is not None else value.get("left"))
    y = _optional_float(value.get("y") if value.get("y") is not None else value.get("top"))
    width = _optional_float(value.get("width"))
    height = _optional_float(value.get("height"))
    if x is None or y is None or width is None or height is None or width <= 0 or height <= 0:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _optional_float(value: Any) -> float | int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return number


def _sequence_state_for_scope(scope_key: str) -> dict[str, Any]:
    return _BROWSER_HID_SEQUENCE_STATE.setdefault(
        scope_key,
        {
            "last_browser_observation": None,
            "last_browser_target_identification": None,
            "last_browser_target_context": None,
            "pending_browser_observation_after_hid": None,
            "audit": [],
        },
    )


def _append_sequence_audit(scope_key: str, *, event: str, tool_name: str, blocked: bool = False, reason: str | None = None) -> None:
    state = _sequence_state_for_scope(scope_key)
    audit = list(state.get("audit") or [])
    audit.append(
        {
            "event": event,
            "tool_name": tool_name,
            "blocked": blocked,
            "reason": reason,
            "scope": scope_key,
            "at": utcnow().isoformat(),
        }
    )
    state["audit"] = audit[-50:]


def _sequence_audit_summary(scope_key: str) -> dict[str, Any]:
    state = _sequence_state_for_scope(scope_key)
    audit = list(state.get("audit") or [])
    return {
        "scope": scope_key,
        "last_browser_observation": state.get("last_browser_observation"),
        "last_browser_target_identification": state.get("last_browser_target_identification"),
        "pending_browser_observation_after_hid": state.get("pending_browser_observation_after_hid"),
        "event_count": len(audit),
        "last_events": audit[-5:],
    }


def _prepare_linear_browser_hid_tool_call(server: McpServer, tool_name: str, arguments: dict[str, Any]) -> None:
    if not _is_browser_hid_sequence_action(server, tool_name, arguments):
        return
    if _hid_action_uses_browser_address_bar_navigation(arguments):
        raise McpBridgeError(
            "Browser/HID policy violation: browser address-bar navigation is not an allowed recovery path. "
            "Use page-internal visible links, buttons, scrolling, back navigation, or return a structured blocker when page-internal evidence is insufficient."
        )
    scope_key = _browser_hid_sequence_scope_key(arguments)
    if scope_key is None:
        raise McpBridgeError(
            "Browser/HID sequence violation: browser-targeted hid_action requires a run, episode, account, or browser host scope. "
            "Re-observe the browser target and carry the scoped target/context into hid_action."
        )
    state = _sequence_state_for_scope(scope_key)
    pending = state["pending_browser_observation_after_hid"]
    if pending:
        _append_sequence_audit(scope_key, event="hid_blocked", tool_name=tool_name, blocked=True, reason="pending_observation_after_hid")
        raise McpBridgeError(
            "Browser/HID sequence violation: the previous browser-targeted hid_action has not been followed by a browser observation. "
            "Call browser_snapshot, browser_wait_for_*, browser_query_elements, or another page observation tool before the next click/type/scroll HID action."
        )
    if state["last_browser_observation"] is None:
        if _hid_action_can_use_target_identification(arguments) and isinstance(state.get("last_browser_target_context"), dict):
            _hydrate_browser_hid_target_context(arguments, state)
            return
        _append_sequence_audit(scope_key, event="hid_blocked", tool_name=tool_name, blocked=True, reason="missing_prior_observation")
        raise McpBridgeError(
            "Browser/HID sequence violation: substantive browser HID actions require a prior browser observation. "
            "Call browser_snapshot or an equivalent browser observation/wait tool before hid_action."
        )
    _hydrate_browser_hid_target_context(arguments, state)


def _hydrate_browser_hid_target_context(arguments: dict[str, Any], state: dict[str, Any]) -> None:
    observed = state.get("last_browser_target_context")
    if not isinstance(observed, dict) or not observed:
        return
    original_target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
    target = dict(original_target)
    observed_bounds = _normalize_browser_window_bounds(observed.get("browserWindowBounds"))
    existing_bounds = _normalize_browser_window_bounds(target.get("browserWindowBounds") or target.get("browser_window_bounds") or target.get("windowBounds") or target.get("window_bounds"))
    if observed_bounds and not existing_bounds:
        target["browserWindowBounds"] = observed_bounds
    for source_key, target_key in (
        ("host", "host"),
        ("tabId", "tabId"),
        ("windowId", "windowId"),
        ("windowTitle", "windowTitle"),
    ):
        value = observed.get(source_key)
        if value not in (None, "", {}) and target.get(target_key) in (None, "", {}):
            target[target_key] = value
    if target != original_target:
        arguments["target"] = target


def _browser_observation_result_is_valid(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    if result.get("success") is False or result.get("ok") is False or bool(result.get("isError")):
        return False
    if str(result.get("error") or "").strip():
        return False
    status = str(result.get("status") or "").strip().lower()
    return status not in {"blocked", "error", "failed", "failure", "timeout"}


def _record_linear_browser_hid_tool_call(server: McpServer, tool_name: str, arguments: dict[str, Any], result: Any) -> None:
    name = str(tool_name or "").strip()
    if _is_browser_target_identification_tool(server, name):
        if not _browser_observation_result_is_valid(result):
            return
        scope_key = _browser_hid_sequence_scope_key(arguments, result)
        if scope_key is None:
            return
        state = _sequence_state_for_scope(scope_key)
        observed_context = _result_browser_target_context(result)
        if observed_context:
            state["last_browser_target_identification"] = name
            state["last_browser_target_context"] = observed_context
            _append_sequence_audit(scope_key, event="browser_target_identified", tool_name=name)
            if isinstance(result, dict):
                result.setdefault("sequence_audit", _sequence_audit_summary(scope_key))
        return
    if _is_browser_observation_tool(server, name):
        if not _browser_observation_result_is_valid(result):
            return
        scope_key = _browser_hid_sequence_scope_key(arguments, result)
        if scope_key is None:
            return
        state = _sequence_state_for_scope(scope_key)
        state["last_browser_observation"] = name
        state["last_browser_target_identification"] = name
        observed_context = _result_browser_target_context(result)
        if observed_context:
            state["last_browser_target_context"] = observed_context
        state["pending_browser_observation_after_hid"] = None
        _append_sequence_audit(scope_key, event="browser_observed", tool_name=name)
        if isinstance(result, dict):
            result.setdefault("sequence_audit", _sequence_audit_summary(scope_key))
        return
    if _is_browser_hid_sequence_action(server, name, arguments):
        scope_key = _browser_hid_sequence_scope_key(arguments)
        if scope_key is None:
            return
        state = _sequence_state_for_scope(scope_key)
        state["pending_browser_observation_after_hid"] = name
        _append_sequence_audit(scope_key, event="hid_action", tool_name=name)
        if isinstance(result, dict):
            result.setdefault("sequence_audit", _sequence_audit_summary(scope_key))


def _normalize_discovered_tool(server: McpServer, payload: dict[str, Any]) -> dict[str, Any] | None:
    name = str(payload.get("name") or "").strip()
    if not name:
        return None
    if _is_browser_mcp_tool(server, name) and name not in _BROWSER_READ_ONLY_RUNTIME_TOOL_NAMES:
        return None
    if _is_virtualhid_mcp_tool(server, name) and not name.startswith("hid_"):
        return None
    annotations = payload.get("annotations") if isinstance(payload.get("annotations"), dict) else {}
    parameters = payload.get("inputSchema") if isinstance(payload.get("inputSchema"), dict) else {"type": "object", "properties": {}, "additionalProperties": True}
    read_only = _tool_read_only_hint(server, name, annotations)
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
    _configured_runtime_state: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)

    def install_preset(
        self,
        preset_key: str,
        *,
        server_key: str | None = None,
        name: str | None = None,
        endpoint: str | None = None,
    ) -> McpServer:
        template = _preset_template_by_key(preset_key)
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
            server_payload.update(
                _apply_preset_server_defaults(
                    template,
                    endpoint=resolved_endpoint,
                    existing_metadata=server_payload["server_metadata"],
                )
            )

            server = server_repo.create(server_payload)
            for tool in template["tools"]:
                tool_repo.create({**tool, "server_id": server.id})
            self._best_effort_sync_tools(session, server, tool_repo=tool_repo)
            return self._serialize_server(session, server.id)

    def list_servers(self) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            repo = McpServerRepository(session)
            db_servers = repo.list(limit=500, offset=0)
            db_keys = {str(item.server_key or "").strip() for item in db_servers}
            db_preset_keys = {str(item.preset_key or "").strip() for item in db_servers if str(item.preset_key or "").strip()}
            configured = []
            for payload in _configured_builtin_server_payloads(exclude_keys=db_keys, exclude_preset_keys=db_preset_keys):
                server = _configured_server_from_payload(payload)
                state = self._configured_runtime_state.get(server.id)
                if state is not None and state.get("endpoint") != server.endpoint:
                    state = None
                configured.append(
                    self._serialize_configured_server_payload(
                        server,
                        health_status=None if state is None else str(state.get("health_status") or "unknown"),
                        health_error=None if state is None else state.get("health_error"),
                        last_health_at=None if state is None else state.get("last_health_at"),
                        tools=None if state is None else list(state.get("tools") or []),
                    )
                )
            return configured + [self._serialize_server_payload(session, item) for item in db_servers]

    def create_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        tools = list(payload.pop("tools", []) or [])
        with self.session_factory() as session:
            server_repo = McpServerRepository(session)
            tool_repo = McpToolRepository(session)
            if server_repo.by_key(str(payload.get("server_key") or "").strip()) is not None:
                raise ValueError("MCP server key already exists")

            protocol = str(payload.get("protocol") or LEGACY_MCP_TOOL_CALL_PROTOCOL).strip()
            endpoint = str(payload.get("endpoint") or "").strip()
            preset_key = str(payload.get("preset_key") or "").strip()
            template = _preset_template_by_key(preset_key)
            if template is not None:
                payload.update(
                    _apply_preset_server_defaults(
                        template,
                        endpoint=endpoint,
                        existing_metadata=payload.get("server_metadata"),
                    )
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
            server = self._refresh_server_from_preset(session, server)

            next_server_key = str(payload.get("server_key") or server.server_key).strip()
            existing = server_repo.by_key(next_server_key)
            if existing is not None and existing.id != server.id:
                raise ValueError("MCP server key already exists")

            next_preset_key = str(payload.get("preset_key") or server.preset_key or "").strip()
            next_endpoint = str(payload.get("endpoint") or server.endpoint).strip()
            template = _preset_template_by_key(next_preset_key)
            if template is not None:
                payload.update(
                    _apply_preset_server_defaults(
                        template,
                        endpoint=next_endpoint,
                        existing_metadata={
                            **dict(server.server_metadata or {}),
                            **dict(payload.get("server_metadata") or {}),
                        },
                    )
                )

            updated = server_repo.update(server, payload)
            updated = self._refresh_server_from_preset(session, updated)
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
        configured = _configured_builtin_server_by_ref(server_id)
        if configured is not None:
            return self._healthcheck_configured_server(configured)

        with self.session_factory() as session:
            server_repo = McpServerRepository(session)
            tool_repo = McpToolRepository(session)
            server = server_repo.get(server_id)
            if server is None:
                raise ValueError("MCP server not found")
            server = self._refresh_server_from_preset(session, server)

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
                        _ = _mcp_list_tools(server)
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
            has_standard_mcp_server = False
            db_servers = [self._refresh_server_from_preset(session, server) for server in server_repo.enabled()]
            db_keys = {str(server.server_key or "").strip() for server in db_servers}
            db_preset_keys = {str(server.preset_key or "").strip() for server in db_servers if str(server.preset_key or "").strip()}
            for server in (
                _configured_server_from_payload(payload)
                for payload in _configured_builtin_server_payloads(exclude_keys=db_keys, exclude_preset_keys=db_preset_keys)
            ):
                if server.protocol == STANDARD_MCP_PROTOCOL:
                    has_standard_mcp_server = True
                    try:
                        discovered_tools = self._discover_tools_for_server(server)  # type: ignore[arg-type]
                    except Exception:
                        discovered_tools = []
                    for item in discovered_tools:
                        name = str(item.get("name") or "").strip()
                        if not name or name in MCP_RESOURCE_TOOL_NAMES or tools.has(name):
                            continue
                        tools.register(self._to_configured_tool_definition(server, item))  # type: ignore[arg-type]
            for server in db_servers:
                server = self._refresh_server_from_preset(session, server)
                if server.protocol == STANDARD_MCP_PROTOCOL:
                    has_standard_mcp_server = True
                    self._best_effort_sync_tools(session, server, tool_repo=tool_repo, replace_existing=True)
                for item in tool_repo.by_server(server.id, enabled_only=True):
                    if item.name in MCP_RESOURCE_TOOL_NAMES:
                        continue
                    if tools.has(item.name):
                        continue
                    tools.register(self._to_tool_definition(server, item))
            if has_standard_mcp_server:
                self._register_resource_tools(tools)

    def reconcile_servers(self) -> None:
        with self.session_factory() as session:
            server_repo = McpServerRepository(session)
            tool_repo = McpToolRepository(session)
            for server in server_repo.list(limit=500, offset=0):
                server = self._refresh_server_from_preset(session, server)
                if server.protocol == STANDARD_MCP_PROTOCOL:
                    self._best_effort_sync_tools(session, server, tool_repo=tool_repo, replace_existing=True)

    def browser_hid_preflight(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        browser_ok = False
        hid_ok = False

        def append_check(server: McpServer, *, kind: str, enabled_names: set[str], missing: list[str]) -> bool:
            if missing:
                checks.append(
                    {
                        "server_key": server.server_key,
                        "kind": kind,
                        "status": "missing_tools",
                        "missing_tools": missing,
                    }
                )
                return False
            probe_name = ""
            if kind == "browser-mcp":
                for candidate in ("browser_get_active_tab", "browser_list_tabs"):
                    if candidate in enabled_names:
                        probe_name = candidate
                        break
            else:
                probe_name = "hid_state" if "hid_state" in enabled_names else ""
            try:
                if probe_name:
                    self._invoke_tool_unlocked(server, probe_name, {})
                checks.append(
                    {
                        "server_key": server.server_key,
                        "kind": kind,
                        "status": "healthy",
                        "missing_tools": [],
                        "probe_tool": probe_name or None,
                    }
                )
                return True
            except Exception as exc:
                checks.append(
                    {
                        "server_key": server.server_key,
                        "kind": kind,
                        "status": "unhealthy",
                        "missing_tools": [],
                        "probe_tool": probe_name or None,
                        "error": str(exc),
                    }
                )
                return False

        with self.session_factory() as session:
            server_repo = McpServerRepository(session)
            tool_repo = McpToolRepository(session)
            db_servers = [self._refresh_server_from_preset(session, server) for server in server_repo.enabled()]
            db_keys = {str(server.server_key or "").strip() for server in db_servers}
            db_preset_keys = {str(server.preset_key or "").strip() for server in db_servers if str(server.preset_key or "").strip()}
            configured_servers = [
                _configured_server_from_payload(payload)
                for payload in _configured_builtin_server_payloads(exclude_keys=db_keys, exclude_preset_keys=db_preset_keys)
            ]
            for server in configured_servers:
                is_browser = _is_browser_mcp_tool(server, "browser_snapshot")
                is_hid = _is_virtualhid_mcp_tool(server, "hid_action")
                if not is_browser and not is_hid:
                    continue
                try:
                    enabled_names = {
                        str(item.get("name") or "").strip()
                        for item in self._discover_tools_for_server(server)  # type: ignore[arg-type]
                        if bool(item.get("enabled", True))
                    }
                    if is_browser:
                        browser_ok = browser_ok or append_check(
                            server, kind="browser-mcp", enabled_names=enabled_names, missing=sorted({"browser_snapshot"} - enabled_names)
                        )
                    if is_hid:
                        hid_ok = hid_ok or append_check(
                            server, kind="VirtualHID", enabled_names=enabled_names, missing=sorted({"hid_action", "hid_state"} - enabled_names)
                        )
                except Exception as exc:
                    checks.append(
                        {
                            "server_key": server.server_key,
                            "kind": "browser-mcp" if is_browser else "VirtualHID",
                            "status": "unhealthy",
                            "error": str(exc),
                        }
                    )
            for server in db_servers:
                server = self._refresh_server_from_preset(session, server)
                is_browser = _is_browser_mcp_tool(server, "browser_snapshot")
                is_hid = _is_virtualhid_mcp_tool(server, "hid_action")
                if not is_browser and not is_hid:
                    continue
                try:
                    if server.protocol == STANDARD_MCP_PROTOCOL:
                        self._sync_tools_for_server(session, server, tool_repo=tool_repo, replace_existing=True)
                    enabled_names = {item.name for item in tool_repo.by_server(server.id, enabled_only=True)}
                    if is_browser:
                        missing = sorted({"browser_snapshot"} - enabled_names)
                        browser_ok = browser_ok or append_check(
                            server, kind="browser-mcp", enabled_names=enabled_names, missing=missing
                        )
                    if is_hid:
                        missing = sorted({"hid_action", "hid_state"} - enabled_names)
                        hid_ok = hid_ok or append_check(
                            server, kind="VirtualHID", enabled_names=enabled_names, missing=missing
                        )
                except Exception as exc:
                    self._mark_server_health(server.id, status="unhealthy", error_message=str(exc))
                    checks.append(
                        {
                            "server_key": server.server_key,
                            "kind": "browser-mcp" if is_browser else "VirtualHID",
                            "status": "unhealthy",
                            "error": str(exc),
                        }
                    )
        status = "healthy" if browser_ok and hid_ok else "blocked"
        missing_kinds = []
        if not browser_ok:
            missing_kinds.append("browser-mcp")
        if not hid_ok:
            missing_kinds.append("VirtualHID")
        return {
            "status": status,
            "ok": status == "healthy",
            "checks": checks,
            "missing": missing_kinds,
        }

    def invoke_tool(self, server: McpServer, tool: McpTool, arguments: dict[str, Any]) -> Any:
        remote_name = str(tool.remote_name or tool.name).strip()
        arguments = _normalize_mcp_tool_arguments(remote_name, arguments)
        if _requires_linear_browser_hid_execution(server, remote_name):
            with _BROWSER_HID_TOOL_LOCK:
                _prepare_linear_browser_hid_tool_call(server, remote_name, arguments)
                result = self._invoke_tool_unlocked(server, remote_name, arguments)
                _record_linear_browser_hid_tool_call(server, remote_name, arguments, result)
                return result
        return self._invoke_tool_unlocked(server, remote_name, arguments)

    def _invoke_tool_unlocked(self, server: McpServer, remote_name: str, arguments: dict[str, Any]) -> Any:
        last_error: McpBridgeError | None = None
        for attempt in range(2):
            try:
                result = self._invoke_tool_once(server, remote_name, arguments)
                if attempt > 0:
                    self._mark_server_health(server.id, status="healthy", error_message=None)
                return result
            except McpBridgeError as exc:
                last_error = exc
                if attempt == 0 and _is_transient_mcp_error(exc):
                    time.sleep(MCP_TRANSIENT_RETRY_DELAY_SECONDS)
                    continue
                if _is_transient_mcp_error(exc):
                    self._mark_server_health(server.id, status="unhealthy", error_message=str(exc))
                raise
        if last_error is not None:
            raise last_error
        raise McpBridgeError(f"MCP tool failed without response: {remote_name}")

    def _invoke_tool_once(self, server: McpServer, remote_name: str, arguments: dict[str, Any]) -> Any:
        if server.protocol == STANDARD_MCP_PROTOCOL:
            return _mcp_call_tool(server, remote_name, arguments)
        if server.transport_kind != "unix_socket":
            raise McpBridgeError(f"Unsupported MCP transport: {server.transport_kind}")
        if server.protocol == LEGACY_BROWSER_COMMAND_PROTOCOL:
            return _json_socket_request(
                server.endpoint,
                {
                    "type": "browser_command",
                    "command": {"name": remote_name, "arguments": dict(arguments or {})},
                },
            )
        if server.protocol == LEGACY_MCP_TOOL_CALL_PROTOCOL:
            return _json_socket_request(
                server.endpoint,
                {
                    "type": "mcp_tool_call",
                    "tool": {"name": remote_name, "arguments": dict(arguments or {})},
                },
            )
        raise McpBridgeError(f"Unsupported MCP protocol: {server.protocol}")

    def _mark_server_health(self, server_id: str, *, status: str, error_message: str | None) -> None:
        with self.session_factory() as session:
            repo = McpServerRepository(session)
            current = repo.get(server_id)
            if current is None:
                return
            repo.update(
                current,
                {
                    "health_status": status,
                    "health_error": error_message,
                    "last_health_at": utcnow(),
                },
            )

    def _to_tool_definition(self, server: McpServer, tool: McpTool) -> ToolDefinition:
        def _handler(
            arguments: dict[str, Any],
            *,
            server_id: str = server.id,
            tool_id: str = tool.id,
            tool_name: str = tool.name,
        ) -> Any:
            with self.session_factory() as session:
                current_server = McpServerRepository(session).get(server_id)
                tool_repo = McpToolRepository(session)
                current_tool = tool_repo.get(tool_id)
                if current_tool is None:
                    current_tool = next(
                        (item for item in tool_repo.by_server(server_id, enabled_only=True) if item.name == tool_name),
                        None,
                    )
                if current_server is None or current_tool is None or not current_server.enabled or not current_tool.enabled:
                    raise McpBridgeError("MCP tool is unavailable or disabled")
                current_server = self._refresh_server_from_preset(session, current_server)
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

    def _to_configured_tool_definition(self, server: McpServer, tool_payload: dict[str, Any]) -> ToolDefinition:
        remote_name = str(tool_payload.get("remote_name") or tool_payload.get("name") or "").strip()
        read_only = str(tool_payload.get("risk_level") or "") == "low"

        def _handler(arguments: dict[str, Any], *, tool_name: str = remote_name) -> Any:
            if _requires_linear_browser_hid_execution(server, tool_name):
                with _BROWSER_HID_TOOL_LOCK:
                    normalized_args = _normalize_mcp_tool_arguments(tool_name, arguments)
                    _prepare_linear_browser_hid_tool_call(server, tool_name, normalized_args)
                    result = self._invoke_tool_unlocked(server, tool_name, normalized_args)
                    _record_linear_browser_hid_tool_call(server, tool_name, normalized_args, result)
                    return result
            return self._invoke_tool_unlocked(server, tool_name, _normalize_mcp_tool_arguments(tool_name, arguments))

        metadata = {
            "capabilities": list(tool_payload.get("capabilities") or _resolve_runtime_capabilities(server, read_only=read_only)),
            "external_tool": True,
            "real_environment": True,
            "mcp_server_id": server.id,
            "mcp_server_key": server.server_key,
            "mcp_server_name": server.name,
            "mcp_tool_id": f"{server.id}:{remote_name}",
            "mcp_tool_name": str(tool_payload.get("name") or remote_name),
            "mcp_remote_name": remote_name,
            "mcp_protocol": server.protocol,
            "builtin_mcp": bool(dict(server.server_metadata or {}).get("builtin")),
        }
        return ToolDefinition(
            name=str(tool_payload.get("name") or remote_name),
            description=str(tool_payload.get("description") or remote_name),
            parameters=dict(tool_payload.get("parameters") or {}),
            handler=_handler,
            metadata=metadata,
        )

    def _register_resource_tools(self, tools: ToolRegistry) -> None:
        if not tools.has("list_mcp_resources"):
            tools.register(
                ToolDefinition(
                    name="list_mcp_resources",
                    description=(
                        "List resources exposed by enabled standard MCP JSON-RPC servers. "
                        "This is for MCP servers that implement resources/list; browser and VirtualHID MCP servers usually expose tools, not resources."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "server_key": {
                                "type": "string",
                                "description": "Optional MCP server key. When omitted, resources from all enabled standard MCP servers are listed.",
                            },
                            "server_id": {
                                "type": "string",
                                "description": "Optional MCP server id. Use when server_key is unavailable.",
                            },
                        },
                        "additionalProperties": False,
                    },
                    handler=self._handle_list_mcp_resources,
                    metadata={
                        "capabilities": ["mcp", "resource"],
                        "external_tool": True,
                        "real_environment": True,
                        "mcp_protocol": STANDARD_MCP_PROTOCOL,
                        "mcp_resource_tool": True,
                    },
                )
            )
        if not tools.has("read_mcp_resource"):
            tools.register(
                ToolDefinition(
                    name="read_mcp_resource",
                    description="Read a resource from an enabled standard MCP JSON-RPC server.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "server_key": {
                                "type": "string",
                                "description": "MCP server key returned by list_mcp_resources. Optional when only one enabled standard MCP server exists.",
                            },
                            "server_id": {
                                "type": "string",
                                "description": "MCP server id returned by list_mcp_resources. Optional when only one enabled standard MCP server exists.",
                            },
                            "uri": {"type": "string", "description": "Resource URI to read."},
                        },
                        "required": ["uri"],
                        "additionalProperties": False,
                    },
                    handler=self._handle_read_mcp_resource,
                    metadata={
                        "capabilities": ["mcp", "resource"],
                        "external_tool": True,
                        "real_environment": True,
                        "mcp_protocol": STANDARD_MCP_PROTOCOL,
                        "mcp_resource_tool": True,
                    },
                )
            )

    def list_mcp_resources(self, *, server_key: str = "", server_id: str = "") -> dict[str, Any]:
        with self.session_factory() as session:
            servers = self._select_enabled_standard_servers(session, server_key=server_key, server_id=server_id)
            return {
                "servers": [
                    {
                        "server_id": server.id,
                        "server_key": server.server_key,
                        "name": server.name,
                        "resources": _mcp_list_resources(server),
                    }
                    for server in servers
                ]
            }

    def read_mcp_resource(self, *, uri: str, server_key: str = "", server_id: str = "") -> dict[str, Any]:
        normalized_uri = str(uri or "").strip()
        if not normalized_uri:
            raise McpBridgeError("read_mcp_resource requires uri")
        with self.session_factory() as session:
            server = self._resolve_enabled_standard_server(session, server_key=server_key, server_id=server_id)
            return {
                "server_id": server.id,
                "server_key": server.server_key,
                "name": server.name,
                "uri": normalized_uri,
                "resource": _mcp_read_resource(server, normalized_uri),
            }

    def _handle_list_mcp_resources(self, arguments: dict[str, Any]) -> dict[str, Any]:
        server_key = str(arguments.get("server_key") or "").strip()
        server_id = str(arguments.get("server_id") or "").strip()
        return self.list_mcp_resources(server_key=server_key, server_id=server_id)

    def _handle_read_mcp_resource(self, arguments: dict[str, Any]) -> dict[str, Any]:
        uri = str(arguments.get("uri") or "").strip()
        server_key = str(arguments.get("server_key") or "").strip()
        server_id = str(arguments.get("server_id") or "").strip()
        return self.read_mcp_resource(uri=uri, server_key=server_key, server_id=server_id)

    def _select_enabled_standard_servers(self, session: Session, *, server_key: str, server_id: str) -> list[McpServer]:
        if server_key or server_id:
            return [self._resolve_enabled_standard_server(session, server_key=server_key, server_id=server_id)]
        repo = McpServerRepository(session)
        servers: list[McpServer] = []
        for server in repo.enabled():
            server = self._refresh_server_from_preset(session, server)
            if server.protocol == STANDARD_MCP_PROTOCOL:
                servers.append(server)
        return servers

    def _resolve_enabled_standard_server(self, session: Session, *, server_key: str, server_id: str) -> McpServer:
        repo = McpServerRepository(session)
        if server_id:
            server = repo.get(server_id)
        elif server_key:
            server = repo.by_key(server_key)
        else:
            servers = self._select_enabled_standard_servers(session, server_key="", server_id="")
            if len(servers) == 1:
                return servers[0]
            if not servers:
                raise McpBridgeError("No enabled standard MCP JSON-RPC servers are available")
            raise McpBridgeError("read_mcp_resource requires server_key or server_id when multiple MCP servers are enabled")
        if server is None:
            raise McpBridgeError("MCP server not found")
        server = self._refresh_server_from_preset(session, server)
        if not server.enabled or server.protocol != STANDARD_MCP_PROTOCOL:
            raise McpBridgeError("MCP server is unavailable or does not use standard MCP JSON-RPC")
        return server

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
            "standard_config": _standard_mcp_server_config(server),
            "standardConfig": _standard_mcp_server_config(server),
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

    def _serialize_configured_server_payload(
        self,
        server: McpServer,
        *,
        health_status: str | None = None,
        health_error: str | None = None,
        last_health_at: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        serialized_tools = []
        for index, item in enumerate(list(tools or []), start=1):
            name = str(item.get("name") or "").strip()
            serialized_tools.append(
                {
                    "id": f"{server.id}:{name or index}",
                    "server_id": server.id,
                    "name": name,
                    "description": str(item.get("description") or name),
                    "parameters": dict(item.get("parameters") or {}),
                    "capabilities": list(item.get("capabilities") or []),
                    "enabled": bool(item.get("enabled", True)),
                    "risk_level": str(item.get("risk_level") or "medium"),
                    "remote_name": item.get("remote_name"),
                    "tool_metadata": dict(item.get("tool_metadata") or {}),
                    "created_at": 0,
                    "updated_at": 0,
                }
            )
        standard_config = _standard_mcp_server_config(server)
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
            "standard_config": standard_config,
            "standardConfig": standard_config,
            "health_status": health_status or server.health_status,
            "health_error": health_error if health_error is not None else server.health_error,
            "last_health_at": last_health_at if last_health_at is not None else server.last_health_at,
            "tools": serialized_tools,
            "created_at": server.created_at,
            "updated_at": server.updated_at,
        }

    def _healthcheck_configured_server(self, server: McpServer) -> dict[str, Any]:
        status = "healthy"
        error_message: str | None = None
        discovered: list[dict[str, Any]] = []
        try:
            discovered = self._discover_tools_for_server(server)
            probe = next(
                (
                    item
                    for item in discovered
                    if isinstance(item.get("parameters"), dict) and _tool_has_zero_argument_schema(dict(item.get("parameters") or {}))
                ),
                None,
            )
            if probe is not None:
                self._invoke_tool_unlocked(server, str(probe.get("remote_name") or probe.get("name") or ""), {})
            else:
                _ = _mcp_list_tools(server)
        except Exception as exc:
            status = "unhealthy"
            error_message = str(exc)
        now = unix_seconds_now()
        serialized = self._serialize_configured_server_payload(
            server,
            health_status=status,
            health_error=error_message,
            last_health_at=now,
            tools=discovered,
        )
        self._configured_runtime_state[server.id] = {
            "endpoint": server.endpoint,
            "health_status": status,
            "health_error": error_message,
            "last_health_at": now,
            "tools": discovered,
        }
        return serialized

    def _refresh_server_from_preset(self, session: Session, server: McpServer) -> McpServer:
        preset_key = str(server.preset_key or "").strip()
        if not preset_key:
            return server
        template = _preset_template_by_key(preset_key)
        if template is None:
            return server
        target_protocol = server.protocol
        if not str(target_protocol or "").strip() or target_protocol == LEGACY_BROWSER_COMMAND_PROTOCOL:
            target_protocol = template["protocol"]
        target_transport = template["transport_kind"]
        target_metadata = _resolve_preset_server_metadata(
            template,
            endpoint=server.endpoint,
            existing_metadata=server.server_metadata,
        )
        if (
            target_protocol == server.protocol
            and target_transport == server.transport_kind
            and target_metadata == dict(server.server_metadata or {})
        ):
            return server
        updated = McpServerRepository(session).update(
            server,
            {
                "protocol": target_protocol,
                "transport_kind": target_transport,
                "server_metadata": target_metadata,
            },
        )
        return updated

    def _discover_tools_for_server(self, server: McpServer) -> list[dict[str, Any]]:
        raw_tools = _mcp_list_tools(server)
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
