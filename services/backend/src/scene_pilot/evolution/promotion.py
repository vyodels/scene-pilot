from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.models.domain import Skill
from scene_pilot.skills.registry import SkillRegistry


class PromotionService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory
        self.skills = SkillRegistry(session_factory)

    def list_skills(self, *, status: str | None = None) -> list[Skill]:
        return self.skills.list_skills(status=status)

    def promote_skill(self, skill_pk: str) -> Skill:
        with self.session_factory() as session:
            skill = session.get(Skill, skill_pk)
            if skill is None:
                raise KeyError(f"unknown skill: {skill_pk}")
            skill.status = "active"
            session.commit()
            session.refresh(skill)
            return skill
