from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.evolution.promotion import activate_prompt_revision, evaluate_trial_metrics
from recruit_agent.models.domain import EvolutionArtifact, PromptOverlayRevision


class PromptEvolution:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_revision(self, *, job_description_id: str, content: dict[str, object]) -> PromptOverlayRevision:
        with self.session_factory() as session:
            next_version = int(
                session.scalar(
                    select(func.max(PromptOverlayRevision.version)).where(
                        PromptOverlayRevision.job_description_id == job_description_id
                    )
                )
                or 0
            ) + 1
            revision = PromptOverlayRevision(
                job_description_id=job_description_id,
                version=next_version,
                content=dict(content),
                status="trial",
            )
            session.add(revision)
            session.commit()
            session.refresh(revision)
            return revision

    def record_trial_metrics(
        self,
        revision_id: str,
        *,
        success: bool,
        latency_ms: int | None = None,
    ) -> PromptOverlayRevision:
        with self.session_factory() as session:
            revision = session.get(PromptOverlayRevision, revision_id)
            if revision is None:
                raise KeyError(f"unknown prompt revision: {revision_id}")
            metrics = dict(revision.trial_metrics or {})
            metrics["runs"] = int(metrics.get("runs") or 0) + 1
            if success:
                metrics["successes"] = int(metrics.get("successes") or 0) + 1
            else:
                metrics["failures"] = int(metrics.get("failures") or 0) + 1
            if latency_ms is not None:
                latencies = list(metrics.get("latency_ms_samples") or [])
                latencies.append(int(latency_ms))
                metrics["latency_ms_samples"] = latencies[-20:]
                metrics["avg_latency_ms"] = sum(metrics["latency_ms_samples"]) / len(metrics["latency_ms_samples"])
            judgment = evaluate_trial_metrics(metrics)
            metrics.update(judgment)
            revision.trial_metrics = metrics
            if bool(judgment["auto_promote"]):
                activate_prompt_revision(revision, baseline_metrics=metrics)
            else:
                revision.status = "trial"
            self._upsert_artifact(session, revision, judgment=judgment)
            session.commit()
            session.refresh(revision)
            return revision

    def _upsert_artifact(
        self,
        session: Session,
        revision: PromptOverlayRevision,
        *,
        judgment: dict[str, object],
    ) -> EvolutionArtifact:
        artifacts = session.scalars(
            select(EvolutionArtifact)
            .where(EvolutionArtifact.artifact_kind == "prompt_overlay_revision")
            .order_by(EvolutionArtifact.created_at.desc())
        ).all()
        artifact = next(
            (
                item
                for item in artifacts
                if str((item.artifact_metadata or {}).get("prompt_revision_id") or "") == revision.id
            ),
            None,
        )
        status = "auto_promoted" if bool(judgment.get("auto_promote")) else "pending_review"
        payload = {
            "prompt_revision_id": revision.id,
            "prompt_revision_status": revision.status,
            "judgment": dict(judgment),
            "queue_state": status,
        }
        if artifact is None:
            artifact = EvolutionArtifact(
                artifact_kind="prompt_overlay_revision",
                title=f"prompt-overlay:{revision.job_description_id}:v{revision.version}",
                status=status,
                artifact_body={
                    "job_description_id": revision.job_description_id,
                    "content": dict(revision.content or {}),
                    "trial_metrics": dict(revision.trial_metrics or {}),
                },
                artifact_metadata=payload,
            )
            session.add(artifact)
            session.flush()
            return artifact
        artifact.status = status
        artifact.artifact_body = {
            "job_description_id": revision.job_description_id,
            "content": dict(revision.content or {}),
            "trial_metrics": dict(revision.trial_metrics or {}),
        }
        artifact.artifact_metadata = {
            **dict(artifact.artifact_metadata or {}),
            **payload,
        }
        return artifact
