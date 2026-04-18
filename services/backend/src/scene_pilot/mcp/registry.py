from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.models.domain import McpServer


class McpRegistry:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_servers(self) -> list[McpServer]:
        with self.session_factory() as session:
            stmt = select(McpServer).order_by(McpServer.name.asc(), McpServer.id.asc())
            return list(session.scalars(stmt).all())
