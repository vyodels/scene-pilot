from __future__ import annotations

from recruit_agent.execution_units.browser_worker import run_browser_worker
from recruit_agent.execution_units.runner import ExecutionUnitRunner
from recruit_agent.execution_units.store import ExecutionUnitStore


def test_functional_closure_execution_units_have_intermediate_states() -> None:
    runner = ExecutionUnitRunner(store=ExecutionUnitStore(), workers={"browser": run_browser_worker})
    unit = runner.create_execution_unit(
        "browser",
        {"url": "https://example.com", "action": "inspect", "step_delay_ms": 40},
    )
    assert runner.wait_unit(unit.unit_id).status in {"queued", "running"}

    running = runner.wait_unit(unit.unit_id, timeout_seconds=0.3, until_statuses={"running", "succeeded"})
    assert running.status in {"running", "succeeded"}

    finished = runner.wait_unit(unit.unit_id, timeout_seconds=1, until_statuses={"succeeded"})
    assert finished.status == "succeeded"
    assert finished.output["trace"]
    assert runner.unit_result(unit.unit_id).status == "succeeded"
