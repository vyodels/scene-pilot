from __future__ import annotations

from recruit_agent.agents.outcome import AgentTurnOutcome


def test_autonomous_completion_gate_uses_run_done() -> None:
    outcome = AgentTurnOutcome(status="complete", gate_signal="run_done")

    assert outcome.gate_signal == "run_done"
