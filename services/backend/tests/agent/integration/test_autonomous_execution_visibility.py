from __future__ import annotations

from recruit_agent.models.domain import AgentRun


def test_autonomous_visibility_model_is_run_based() -> None:
    run = AgentRun(
        session_id="session-1",
        lane="agent",
        run_type="candidate_discovery",
        status="queued",
        context_manifest={"instruction": "Find candidates", "title": "Find candidates"},
        runtime_metadata={"instruction": "Find candidates"},
        run_id="run-1",
        agent_kind="autonomous",
    )

    assert run.run_type == "candidate_discovery"
    assert run.context_manifest["instruction"] == "Find candidates"
