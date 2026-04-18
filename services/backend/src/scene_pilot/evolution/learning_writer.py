from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.models.domain import AgentLearning, EvolutionArtifact, Skill


class LearningWriter:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def record_learning(
        self,
        *,
        content: str,
        tags: list[str],
        promote: bool = False,
        skill_name: str | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            learning = AgentLearning(content=content, tags=list(tags))
            session.add(learning)

            skill: Skill | None = None
            if promote:
                resolved_skill_name = skill_name or "trial-skill"
                skill = Skill(
                    skill_id=resolved_skill_name,
                    name=resolved_skill_name,
                    status="trial",
                    trigger_hint=resolved_skill_name,
                    body={"content": content},
                    strategy={"content": content},
                )
                session.add(skill)
                session.flush()

            artifact = EvolutionArtifact(
                artifact_kind="skill_draft" if promote else "prompt_lesson",
                title=skill_name or "learning-artifact",
                status="pending_review",
                artifact_body={"content": content, "tags": tags},
                related_skill_id=None if skill is None else skill.id,
            )
            session.add(artifact)
            session.commit()
            session.refresh(artifact)
            return {"learning_id": learning.id, "artifact_id": artifact.id, "skill_id": None if skill is None else skill.id}
