from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.models.domain import EvolutionArtifact


class EvolutionQueue:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_pending(self, *, status: str = "pending_review") -> list[EvolutionArtifact]:
        with self.session_factory() as session:
            stmt = select(EvolutionArtifact).where(EvolutionArtifact.status == status).order_by(EvolutionArtifact.created_at.asc())
            return list(session.scalars(stmt).all())

    def approve(self, artifact_id: str) -> EvolutionArtifact:
        with self.session_factory() as session:
            artifact = session.get(EvolutionArtifact, artifact_id)
            if artifact is None:
                raise KeyError(f"unknown artifact: {artifact_id}")
            artifact.status = "approved"
            session.commit()
            session.refresh(artifact)
            return artifact

    def reject(self, artifact_id: str) -> EvolutionArtifact:
        with self.session_factory() as session:
            artifact = session.get(EvolutionArtifact, artifact_id)
            if artifact is None:
                raise KeyError(f"unknown artifact: {artifact_id}")
            artifact.status = "rejected"
            session.commit()
            session.refresh(artifact)
            return artifact
