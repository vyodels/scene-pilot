from __future__ import annotations

import time

from recruit_agent.execution_units.browser_worker import run_browser_worker
from recruit_agent.execution_units.runner import ExecutionUnitRunner
from recruit_agent.execution_units.store import ExecutionUnitStore


def test_execution_unit_supports_blocked_and_timeout_statuses() -> None:
    def _timeout_worker(payload: dict[str, object]) -> dict[str, object]:
        time.sleep(0.2)
        return {"output": {"done": True}}

    runner = ExecutionUnitRunner(
        store=ExecutionUnitStore(),
        workers={"browser": run_browser_worker, "timeout": _timeout_worker},
    )

    blocked_human = runner.create_execution_unit("browser", {"action": "click", "requires_human": True})
    blocked_environment = runner.create_execution_unit("browser", {"action": "navigate"})
    timeout = runner.create_execution_unit("timeout", {"candidate_id": "c-2"}, timeout_seconds=0)
    assert blocked_human.status == "queued"
    assert blocked_environment.status == "queued"

    blocked_human_state = runner.wait_unit(blocked_human.unit_id, timeout_seconds=0.5, until_statuses={"blocked_human"})
    blocked_environment_state = runner.wait_unit(
        blocked_environment.unit_id,
        timeout_seconds=0.5,
        until_statuses={"blocked_environment"},
    )

    timed = runner.create_execution_unit("timeout", {"candidate_id": "c-3"}, timeout_seconds=0.05)
    timed_state = runner.wait_unit(timed.unit_id, timeout_seconds=1, until_statuses={"timed_out", "succeeded", "failed"})

    assert blocked_human_state.status == "blocked_human"
    assert blocked_environment_state.status == "blocked_environment"
    assert runner.unit_result(blocked_human.unit_id).status == "blocked_human"
    assert runner.unit_result(blocked_environment.unit_id).status == "blocked_environment"
    assert timed_state.status == "timed_out"
    assert runner.unit_result(timed.unit_id).status == "timed_out"
    assert timeout.status in {"queued", "running"}
