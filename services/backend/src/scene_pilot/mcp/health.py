from __future__ import annotations

from scene_pilot.models.domain import McpServer


def summarize_mcp_health(servers: list[McpServer]) -> dict[str, int]:
    healthy = sum(1 for server in servers if server.health_status == "healthy")
    unhealthy = sum(1 for server in servers if server.health_status != "healthy")
    return {"healthy": healthy, "unhealthy": unhealthy}
