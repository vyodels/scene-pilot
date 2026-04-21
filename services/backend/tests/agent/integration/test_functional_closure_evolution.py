from __future__ import annotations

from recruit_agent.evolution.learning_writer import LearningWriter
from recruit_agent.evolution.prompt_evolution import PromptEvolution
from recruit_agent.evolution.queue import EvolutionQueue
from recruit_agent.models.domain import EvolutionArtifact, JobDescription, PromptOverlayRevision, Skill

from ._helpers import make_session_factory


def test_functional_closure_evolution_is_closed_loop(tmp_path) -> None:
    session_factory = make_session_factory(tmp_path, "functional-evolution.db")
    writer = LearningWriter(session_factory)
    queue = EvolutionQueue(session_factory)
    prompt_evolution = PromptEvolution(session_factory)

    promoted = writer.record_learning(
        content="High confidence prompt improvement.",
        tags=["prompt"],
        promote=True,
        skill_name="high-confidence-skill",
        trial_metrics={"runs": 3, "successes": 3},
    )
    queued = writer.record_learning(
        content="Needs more evidence.",
        tags=["prompt"],
        promote=True,
        skill_name="needs-review-skill",
        trial_metrics={"runs": 1, "successes": 0, "failures": 1},
    )

    with session_factory() as session:
        job = JobDescription(title="Backend Engineer")
        session.add(job)
        session.commit()
        session.refresh(job)
        revision = prompt_evolution.create_revision(
            job_description_id=job.job_description_id,
            content={"overlay": "ask for concrete backend examples"},
        )
        prompt_evolution.record_trial_metrics(revision.id, success=False, latency_ms=120)

    with session_factory() as session:
        promoted_skill = session.get(Skill, promoted["skill_id"])
        queued_skill = session.get(Skill, queued["skill_id"])
        assert promoted_skill is not None and promoted_skill.status == "active"
        assert queued_skill is not None and queued_skill.status == "trial"
        prompt_revision = session.get(PromptOverlayRevision, revision.id)
        assert prompt_revision is not None and prompt_revision.status == "trial"

    pending = queue.list_pending()
    assert any(item.id == queued["artifact_id"] for item in pending)
    prompt_artifact = next(item for item in pending if item.artifact_kind == "prompt_overlay_revision")
    queue.reject(prompt_artifact.id)

    with session_factory() as session:
        rejected_revision = session.get(PromptOverlayRevision, revision.id)
        rejected_artifact = session.get(EvolutionArtifact, prompt_artifact.id)
        assert rejected_revision is not None and rejected_revision.status == "rejected"
        assert rejected_artifact is not None and rejected_artifact.status == "rejected"
