from __future__ import annotations

import contextlib
import json
import os
import socket
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


MCP_PROTOCOL_VERSION = "2025-03-26"
BROWSER_BRIDGE_SERVER_NAME = "scene-pilot-browser-mcp-bridge"
BROWSER_SOCKET_PRESET_KEY = "browser-json-socket"


def default_browser_upstream_endpoint() -> str:
    return os.environ.get("MCP_BROWSER_CHROME_SOCKET") or f"{tempfile.gettempdir()}/browser-mcp.sock"


def managed_bridge_endpoint(server_key: str) -> str:
    safe_key = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in server_key.strip() or "browser")
    return os.path.join(tempfile.gettempdir(), f"scene-pilot-{safe_key}-mcp.sock")


def browser_bridge_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "browser_get_active_tab",
            "description": "Read the active browser tab and return its id, title, and URL.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
        },
        {
            "name": "browser_list_tabs",
            "description": "List open browser tabs with their ids, titles, URLs, and active state.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
        },
        {
            "name": "browser_snapshot",
            "description": "Read a structured snapshot for a browser tab identified by tabId.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": {"type": "integer"},
                    "maxTextLength": {"type": "integer"},
                    "interactiveLimit": {"type": "integer"},
                },
                "required": ["tabId"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
        },
        {
            "name": "browser_execute_script",
            "description": "Execute a script in a browser tab identified by tabId.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tabId": {"type": "integer"},
                    "script": {"type": "string"},
                },
                "required": ["tabId", "script"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False, "idempotentHint": False, "openWorldHint": True},
        },
    ]


def _browser_command_request(endpoint: str, command_name: str, arguments: dict[str, Any], *, timeout_seconds: float = 8.0) -> Any:
    request_id = uuid.uuid4().hex
    request = {
        "id": request_id,
        "type": "browser_command",
        "command": {"name": command_name, "arguments": dict(arguments or {})},
    }
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
                            raise RuntimeError(str(error.get("message") or error))
                        raise RuntimeError(str(error or "Browser MCP call failed"))
                    return response.get("result")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Browser MCP socket not found: {endpoint}") from exc
    except socket.timeout as exc:
        raise RuntimeError(f"Browser MCP call timed out: {endpoint}") from exc
    except OSError as exc:
        raise RuntimeError(f"Browser MCP unavailable at {endpoint}: {exc}") from exc
    raise RuntimeError(f"Browser MCP returned no response: {endpoint}")


def _jsonrpc_result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _jsonrpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


@dataclass(slots=True)
class BrowserMcpBridgeServer:
    upstream_endpoint: str
    socket_path: str
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _server_socket: socket.socket | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.socket_path)
            server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server_socket.bind(self.socket_path)
            server_socket.listen()
            server_socket.settimeout(0.5)
            self._server_socket = server_socket
            self._thread = threading.Thread(target=self._serve_forever, name=f"browser-mcp-bridge:{self.socket_path}", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            if self._server_socket is not None:
                with contextlib.suppress(OSError):
                    self._server_socket.close()
                self._server_socket = None
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=1.0)
            self._thread = None
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.socket_path)

    def update_upstream(self, upstream_endpoint: str) -> None:
        self.upstream_endpoint = upstream_endpoint

    def _serve_forever(self) -> None:
        while not self._stop_event.is_set():
            server_socket = self._server_socket
            if server_socket is None:
                return
            try:
                connection, _ = server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            worker = threading.Thread(target=self._handle_connection, args=(connection,), daemon=True)
            worker.start()

    def _handle_connection(self, connection: socket.socket) -> None:
        with connection:
            connection.settimeout(0.5)
            buffer = b""
            while not self._stop_event.is_set():
                try:
                    chunk = connection.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        response = _jsonrpc_error(None, -32700, "Parse error")
                    else:
                        response = self._dispatch(payload)
                    if response is None:
                        continue
                    try:
                        connection.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
                    except OSError:
                        return

    def _dispatch(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        message_id = payload.get("id")
        method = str(payload.get("method") or "").strip()
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        if not method:
            return _jsonrpc_error(message_id, -32600, "Missing method")
        if method == "initialize":
            return _jsonrpc_result(
                message_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": BROWSER_BRIDGE_SERVER_NAME, "version": "0.1.0"},
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return _jsonrpc_result(message_id, {"tools": browser_bridge_tools()})
        if method == "tools/call":
            tool_name = str(params.get("name") or "").strip()
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            known_tool_names = {tool["name"] for tool in browser_bridge_tools()}
            if tool_name not in known_tool_names:
                return _jsonrpc_error(message_id, -32602, f"Unknown tool: {tool_name}")
            try:
                result = _browser_command_request(self.upstream_endpoint, tool_name, arguments)
                return _jsonrpc_result(
                    message_id,
                    {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
                        "isError": False,
                    },
                )
            except Exception as exc:
                return _jsonrpc_result(
                    message_id,
                    {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    },
                )
        return _jsonrpc_error(message_id, -32601, f"Method not found: {method}")


@dataclass(slots=True)
class BrowserMcpBridgeManager:
    bridges: dict[str, BrowserMcpBridgeServer] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def ensure_bridge(self, *, server_key: str, upstream_endpoint: str, runtime_endpoint: str | None = None) -> str:
        socket_path = runtime_endpoint or managed_bridge_endpoint(server_key)
        with self._lock:
            bridge = self.bridges.get(socket_path)
            if bridge is None:
                bridge = BrowserMcpBridgeServer(upstream_endpoint=upstream_endpoint, socket_path=socket_path)
                self.bridges[socket_path] = bridge
            else:
                bridge.update_upstream(upstream_endpoint)
            bridge.start()
        return socket_path

    def stop_all(self) -> None:
        with self._lock:
            bridges = list(self.bridges.values())
            self.bridges.clear()
        for bridge in bridges:
            bridge.stop()
