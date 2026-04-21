from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from recruit_agent.evolution.learning_writer import LearningWriter
from recruit_agent.models.domain import EvolutionArtifact, Skill

from ._helpers import make_session_factory


def test_record_learning_auto_promotes_when_trial_metrics_meet_threshold(tmp_path: Path) -> None:
    session_factory = make_session_factory(tmp_path, "record-learning-auto.db")
    writer = LearningWriter(session_factory)

    recorded = writer.record_learning(
        content="Use the candidate's original wording when confirming interest.",
        tags=["prompt"],
        promote=True,
        skill_name="candidate-confirmation",
        trial_metrics={"runs": 3, "successes": 3},
    )

    with session_factory() as session:
        skill = session.get(Skill, recorded["skill_id"])
        artifact = session.get(EvolutionArtifact, recorded["artifact_id"])
        assert skill is not None
        assert artifact is not None
        assert skill.status == "active"
        assert artifact.status == "auto_promoted"
        assert artifact.artifact_metadata["judgment"]["auto_promote"] is True
        assert recorded["auto_promoted"] is True
