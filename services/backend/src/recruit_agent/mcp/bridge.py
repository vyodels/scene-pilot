from __future__ import annotations

from recruit_agent.models.domain import McpServer


def bridge_call(server: McpServer, tool_name: str) -> dict[str, str]:
    return {"server": server.server_key, "tool_name": tool_name}
