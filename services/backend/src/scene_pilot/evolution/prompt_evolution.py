from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.models.domain import PromptOverlayRevision


class PromptEvolution:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_revision(self, *, job_description_id: str, content: dict[str, object]) -> PromptOverlayRevision:
        with self.session_factory() as session:
            revision = PromptOverlayRevision(job_description_id=job_description_id, content=dict(content))
            session.add(revision)
            session.commit()
            session.refresh(revision)
            return revision
