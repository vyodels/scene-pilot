from __future__ import annotations

from pathlib import Path

from recruit_agent.evolution.learning_writer import LearningWriter
from recruit_agent.evolution.queue import EvolutionQueue
from recruit_agent.models.domain import Skill

from ._helpers import make_session_factory


def test_record_learning_enters_review_queue_when_metrics_do_not_meet_threshold(tmp_path: Path) -> None:
    session_factory = make_session_factory(tmp_path, "record-learning-queue.db")
    writer = LearningWriter(session_factory)
    queue = EvolutionQueue(session_factory)

    recorded = writer.record_learning(
        content="Shorten the greeting for warm candidates.",
        tags=["prompt"],
        promote=True,
        skill_name="warm-greeting",
        trial_metrics={"runs": 2, "successes": 1, "failures": 1},
    )

    pending = queue.list_pending()
    assert pending
    assert pending[0].id == recorded["artifact_id"]
    assert pending[0].artifact_metadata["judgment"]["auto_promote"] is False
    with session_factory() as session:
        skill = session.get(Skill, recorded["skill_id"])
        assert skill is not None
        assert skill.status == "trial"
        assert recorded["auto_promoted"] is False
