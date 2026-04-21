from __future__ import annotations

from typing import Any


def summarize_mcp_health(servers: list[Any]) -> dict[str, int]:
    def _status(server: Any) -> str:
        if isinstance(server, dict):
            return str(server.get("health_status") or "unknown")
        return str(getattr(server, "health_status", "unknown"))

    healthy = sum(1 for server in servers if _status(server) == "healthy")
    unhealthy = sum(1 for server in servers if _status(server) != "healthy")
    return {"healthy": healthy, "unhealthy": unhealthy}
