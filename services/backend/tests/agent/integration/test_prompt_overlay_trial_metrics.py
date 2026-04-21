from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from recruit_agent.evolution.prompt_evolution import PromptEvolution
from recruit_agent.models.domain import EvolutionArtifact, JobDescription

from ._helpers import make_session_factory


def test_prompt_overlay_trial_metrics_are_accumulated(tmp_path: Path) -> None:
    session_factory = make_session_factory(tmp_path, "prompt-evolution.db")
    with session_factory() as session:
        job = JobDescription(title="Backend Engineer")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_description_id = job.job_description_id

    evolution = PromptEvolution(session_factory)
    revision = evolution.create_revision(job_description_id=job_description_id, content={"overlay": "be concise"})
    updated = evolution.record_trial_metrics(revision.id, success=True, latency_ms=120)
    updated = evolution.record_trial_metrics(updated.id, success=True, latency_ms=180)
    updated = evolution.record_trial_metrics(updated.id, success=True, latency_ms=240)

    assert updated.status == "active"
    assert updated.trial_metrics["runs"] == 3
    assert updated.trial_metrics["successes"] == 3
    assert updated.trial_metrics["failures"] == 0
    assert updated.trial_metrics["success_rate"] == 1.0
    assert updated.trial_metrics["avg_latency_ms"] == 180
    with session_factory() as session:
        artifact = session.scalars(
            select(EvolutionArtifact).where(EvolutionArtifact.artifact_kind == "prompt_overlay_revision")
        ).first()
        assert artifact is not None
        assert artifact.status == "auto_promoted"
        assert artifact.artifact_metadata["prompt_revision_id"] == updated.id
