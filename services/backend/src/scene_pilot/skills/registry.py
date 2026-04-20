from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.models.domain import Skill


class SkillRegistry:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_skills(self, *, status: str | None = None) -> list[Skill]:
        with self.session_factory() as session:
            stmt = select(Skill).order_by(Skill.updated_at.desc(), Skill.id.asc())
            if status is not None:
                stmt = stmt.where(Skill.status == status)
            return list(session.scalars(stmt).all())

    def get_skill(self, skill_id: str) -> Skill | None:
        with self.session_factory() as session:
            item = session.get(Skill, skill_id)
            if item is not None:
                return item
            stmt = select(Skill).where(Skill.skill_id == skill_id)
            return session.scalars(stmt).first()
