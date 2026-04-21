from __future__ import annotations

import time
from threading import Event

from recruit_agent.execution_units.runner import ExecutionUnitRunner
from recruit_agent.execution_units.store import ExecutionUnitStore


def test_execution_unit_runner_honors_cooldown_and_waits_for_state_transitions() -> None:
    store = ExecutionUnitStore()
    started = Event()
    release = Event()

    def _worker(payload: dict[str, object]) -> dict[str, object]:
        started.set()
        release.wait(timeout=1)
        return {"output": {"observed": payload["url"]}}

    runner = ExecutionUnitRunner(store=store, workers={"browser": _worker})
    unit = runner.create_execution_unit("browser", {"url": "https://example.com"}, cooldown_seconds=1)

    queued = runner.wait_unit(unit.unit_id, timeout_seconds=0.05, until_statuses={"running"})
    assert queued.status == "queued"
    assert queued.started_at is None
    assert started.is_set() is False

    running = runner.wait_unit(unit.unit_id, timeout_seconds=1.5, until_statuses={"running"})
    assert running.status == "running"
    assert started.wait(timeout=0.2) is True

    release.set()
    finished = runner.wait_unit(unit.unit_id, timeout_seconds=1, until_statuses={"succeeded", "failed"})
    assert finished.status == "succeeded"

    result = runner.unit_result(unit.unit_id)
    assert result.status == "succeeded"
    assert result.output == {"observed": "https://example.com"}
    assert result.metadata["cooldown_seconds"] == 1
