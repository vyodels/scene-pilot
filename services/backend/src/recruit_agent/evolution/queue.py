from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.evolution.promotion import (
    activate_prompt_revision,
    activate_skill,
    reject_prompt_revision,
    reject_skill,
)
from recruit_agent.models.domain import EvolutionArtifact, PromptOverlayRevision, Skill


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
            artifact.status = "applied"
            artifact.reviewed_at = datetime.now(UTC)
            artifact.reviewed_by = artifact.reviewed_by or "system"
            if artifact.related_skill_id:
                skill = session.get(Skill, artifact.related_skill_id)
                if skill is not None:
                    activate_skill(skill, reviewer=artifact.reviewed_by)
            revision = _resolve_prompt_revision(session, artifact)
            if revision is not None:
                activate_prompt_revision(revision, baseline_metrics=dict(revision.trial_metrics or {}))
                artifact.artifact_metadata = {
                    **dict(artifact.artifact_metadata or {}),
                    "prompt_revision_id": revision.id,
                    "prompt_revision_status": revision.status,
                    "queue_state": artifact.status,
                }
            session.commit()
            session.refresh(artifact)
            return artifact

    def reject(self, artifact_id: str) -> EvolutionArtifact:
        with self.session_factory() as session:
            artifact = session.get(EvolutionArtifact, artifact_id)
            if artifact is None:
                raise KeyError(f"unknown artifact: {artifact_id}")
            artifact.status = "rejected"
            artifact.reviewed_at = datetime.now(UTC)
            artifact.reviewed_by = artifact.reviewed_by or "system"
            if artifact.related_skill_id:
                skill = session.get(Skill, artifact.related_skill_id)
                if skill is not None:
                    reject_skill(skill)
            revision = _resolve_prompt_revision(session, artifact)
            if revision is not None:
                reject_prompt_revision(revision)
                artifact.artifact_metadata = {
                    **dict(artifact.artifact_metadata or {}),
                    "prompt_revision_id": revision.id,
                    "prompt_revision_status": revision.status,
                    "queue_state": artifact.status,
                }
            session.commit()
            session.refresh(artifact)
            return artifact


def _resolve_prompt_revision(session: Session, artifact: EvolutionArtifact) -> PromptOverlayRevision | None:
    revision_id = str((artifact.artifact_metadata or {}).get("prompt_revision_id") or "").strip()
    if revision_id:
        return session.get(PromptOverlayRevision, revision_id)
    if artifact.artifact_kind != "prompt_overlay_revision":
        return None
    stmt = select(PromptOverlayRevision).where(
        PromptOverlayRevision.job_description_id == str((artifact.artifact_body or {}).get("job_description_id") or "")
    )
    revisions = session.scalars(stmt).all()
    title = str(artifact.title or "")
    return next((item for item in revisions if f":v{item.version}" in title), None)
