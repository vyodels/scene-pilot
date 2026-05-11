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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.asset_paths import mcp_preset_templates_root
from recruit_agent.db.base import utcnow
from recruit_agent.models import McpServer, McpTool
from recruit_agent.repositories import McpServerRepository, McpToolRepository
from recruit_agent.capabilities.tools import ToolDefinition, ToolRegistry
from recruit_agent.services.browser_mcp_bridge import (
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
MCP_TRANSIENT_RETRY_DELAY_SECONDS = 0.35
BROWSER_LOCATE_DOWNLOAD_MAX_WAIT_MS = 5_000
VIRTUALHID_SOCKET_PRESET_KEY = "virtualhid-json-socket"
MCP_RESOURCE_TOOL_NAMES = {"list_mcp_resources", "read_mcp_resource"}
_VIRTUALHID_MCP_SERVER_ENV = "VIRTUALHID_MCP_SERVER"
_VIRTUALHID_MCP_COMMAND_ENV = "VIRTUALHID_MCP_COMMAND"
_KNOWN_STDIO_COMMAND_RESOLVERS = {"browser_mcp_server", "virtualhid_mcp_server"}
_BROWSER_HID_TOOL_LOCK = threading.RLock()
_BROWSER_HID_SEQUENCE_STATE: dict[str, str | None] = {
    "last_browser_observation": None,
    "pending_browser_observation_after_hid": None,
}
_BROWSER_OBSERVATION_TOOL_NAMES = {
    "browser_list_tabs",
    "browser_get_active_tab",
    "browser_snapshot",
    "browser_query_elements",
    "browser_get_element",
    "browser_debug_dom",
    "browser_wait_for_element",
    "browser_wait_for_text",
    "browser_wait_for_navigation",
    "browser_wait_for_disappear",
    "browser_wait_for_url",
    "browser_screenshot",
    "browser_get_cookies",
    "browser_locate_download",
}
_HID_BROWSER_SEQUENCE_PRIMITIVE_TYPES = {"click", "drag", "scroll", "type", "pasteText", "key"}


def _default_browser_endpoint() -> str:
    return default_browser_upstream_endpoint()


def default_virtualhid_upstream_endpoint() -> str:
    return os.environ.get("VIRTUALHID_SOCKET") or f"{tempfile.gettempdir()}/virtualhid.sock"


def _reset_browser_hid_sequence_state_for_tests() -> None:
    with _BROWSER_HID_TOOL_LOCK:
        _BROWSER_HID_SEQUENCE_STATE["last_browser_observation"] = None
        _BROWSER_HID_SEQUENCE_STATE["pending_browser_observation_after_hid"] = None


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
                            "clientInfo": {"name": "recruit-agent", "version": "0.1.0"},
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
        result = _mcp_session_request(server, "resources/list", params)
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
    result = _mcp_session_request(server, "tools/call", {"name": tool_name, "arguments": dict(arguments or {})})
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
    normalized = dict(arguments or {})
    if tool_name != "browser_locate_download":
        return normalized
    if "waitMs" not in normalized:
        normalized["waitMs"] = BROWSER_LOCATE_DOWNLOAD_MAX_WAIT_MS
        return normalized
    wait_ms = _coerce_number(normalized.get("waitMs"))
    if wait_ms is None:
        normalized.pop("waitMs", None)
        return normalized
    normalized["waitMs"] = max(0, min(int(wait_ms), BROWSER_LOCATE_DOWNLOAD_MAX_WAIT_MS))
    return normalized


def _coerce_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _is_browser_hid_sequence_action(server: McpServer, tool_name: str, arguments: dict[str, Any]) -> bool:
    if not _is_virtualhid_mcp_tool(server, tool_name):
        return False
    if str(tool_name or "").strip() != "hid_action":
        return False
    return _hid_action_targets_browser(arguments) and _hid_action_has_browser_sequence_primitive(arguments)


def _prepare_linear_browser_hid_tool_call(server: McpServer, tool_name: str, arguments: dict[str, Any]) -> None:
    if not _is_browser_hid_sequence_action(server, tool_name, arguments):
        return
    pending = _BROWSER_HID_SEQUENCE_STATE["pending_browser_observation_after_hid"]
    if pending:
        raise McpBridgeError(
            "Browser/HID sequence violation: the previous browser-targeted hid_action has not been followed by a browser observation. "
            "Call browser_snapshot, browser_wait_for_*, browser_get_active_tab, browser_query_elements, browser_locate_download, or another browser observation tool before the next click/type/scroll HID action."
        )
    if _BROWSER_HID_SEQUENCE_STATE["last_browser_observation"] is None:
        raise McpBridgeError(
            "Browser/HID sequence violation: substantive browser HID actions require a prior browser observation. "
            "Call browser_snapshot or an equivalent browser observation/wait tool before hid_action."
        )


def _record_linear_browser_hid_tool_call(server: McpServer, tool_name: str, arguments: dict[str, Any]) -> None:
    name = str(tool_name or "").strip()
    if _is_browser_observation_tool(server, name):
        _BROWSER_HID_SEQUENCE_STATE["last_browser_observation"] = name
        _BROWSER_HID_SEQUENCE_STATE["pending_browser_observation_after_hid"] = None
        return
    if _is_browser_hid_sequence_action(server, name, arguments):
        _BROWSER_HID_SEQUENCE_STATE["pending_browser_observation_after_hid"] = name


def _normalize_discovered_tool(server: McpServer, payload: dict[str, Any]) -> dict[str, Any] | None:
    name = str(payload.get("name") or "").strip()
    if not name:
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
            return [self._serialize_server_payload(session, item) for item in repo.list(limit=500, offset=0)]

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
            for server in server_repo.enabled():
                server = self._refresh_server_from_preset(session, server)
                if server.protocol == STANDARD_MCP_PROTOCOL:
                    has_standard_mcp_server = True
                    self._best_effort_sync_tools(session, server, tool_repo=tool_repo, replace_existing=True)
                for item in tool_repo.by_server(server.id, enabled_only=True):
                    if item.name in MCP_RESOURCE_TOOL_NAMES:
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

    def invoke_tool(self, server: McpServer, tool: McpTool, arguments: dict[str, Any]) -> Any:
        remote_name = str(tool.remote_name or tool.name).strip()
        arguments = _normalize_mcp_tool_arguments(remote_name, arguments)
        if _requires_linear_browser_hid_execution(server, remote_name):
            with _BROWSER_HID_TOOL_LOCK:
                _prepare_linear_browser_hid_tool_call(server, remote_name, arguments)
                result = self._invoke_tool_unlocked(server, remote_name, arguments)
                _record_linear_browser_hid_tool_call(server, remote_name, arguments)
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

    def _register_resource_tools(self, tools: ToolRegistry) -> None:
        if not tools.has("list_mcp_resources"):
            tools.register(
                ToolDefinition(
                    name="list_mcp_resources",
                    description="List resources exposed by enabled standard MCP JSON-RPC servers.",
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
