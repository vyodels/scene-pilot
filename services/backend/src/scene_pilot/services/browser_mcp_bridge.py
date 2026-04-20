from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Sequence


MCP_PROTOCOL_VERSION = "2025-03-26"
BROWSER_SOCKET_PRESET_KEY = "browser-json-socket"
_BROWSER_MCP_SERVER_ENV = "MCP_BROWSER_CHROME_MCP_SERVER"
_BROWSER_MCP_COMMAND_ENV = "MCP_BROWSER_CHROME_MCP_COMMAND"


def default_browser_upstream_endpoint() -> str:
    return os.environ.get("MCP_BROWSER_CHROME_SOCKET") or f"{tempfile.gettempdir()}/browser-mcp.sock"


def default_browser_mcp_server_command() -> tuple[str, ...] | None:
    command_override = str(os.environ.get(_BROWSER_MCP_COMMAND_ENV) or "").strip()
    if command_override:
        command = tuple(part.strip() for part in shlex.split(command_override) if part.strip())
        return command or None

    script_path = _discover_browser_mcp_server_script()
    node_path = shutil.which("node")
    if script_path is None or node_path is None:
        return None
    return (node_path, script_path)


def run_mcp_stdio_request(
    command: Sequence[str],
    *,
    method: str,
    params: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    timeout_seconds: float = 8.0,
    command_label: str | None = None,
) -> dict[str, Any]:
    resolved_command = [str(part).strip() for part in command if str(part).strip()]
    if not resolved_command:
        raise RuntimeError("MCP stdio command is not configured")

    initialize_id = uuid.uuid4().hex
    request_id = uuid.uuid4().hex
    messages = [
        {
            "jsonrpc": "2.0",
            "id": initialize_id,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "scene-pilot", "version": "0.1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params or {})},
    ]
    stdin_payload = "\n".join(json.dumps(message, ensure_ascii=False) for message in messages) + "\n"
    process_env = os.environ.copy()
    process_env.update({key: value for key, value in dict(env or {}).items() if str(key).strip()})
    label = command_label or " ".join(resolved_command)
    try:
        completed = subprocess.run(
            resolved_command,
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=process_env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"MCP stdio command not found: {label}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"MCP stdio request timed out after {timeout_seconds:.1f}s: {label}") from exc
    responses = _parse_newline_json_messages(completed.stdout)
    for response in responses:
        if str(response.get("id") or "") != request_id:
            continue
        error = response.get("error")
        if isinstance(error, dict):
            raise RuntimeError(str(error.get("message") or f"MCP request failed via {label}"))
        result = response.get("result")
        if isinstance(result, dict):
            return result
        return {}
    stderr = str(completed.stderr or "").strip()
    if stderr:
        raise RuntimeError(f"MCP stdio returned no response via {label}: {stderr}")
    raise RuntimeError(f"MCP stdio returned no response via {label}")


def _discover_browser_mcp_server_script() -> str | None:
    override = str(os.environ.get(_BROWSER_MCP_SERVER_ENV) or "").strip()
    if override:
        return override

    current = Path(__file__).resolve()
    candidates: list[Path] = []
    seen: set[str] = set()
    for ancestor in current.parents:
        for candidate in (
            ancestor / "mcp-browser-chrome" / "mcp" / "server.mjs",
            ancestor.parent / "mcp-browser-chrome" / "mcp" / "server.mjs",
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


def _parse_newline_json_messages(stdout: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            messages.append(parsed)
    return messages
