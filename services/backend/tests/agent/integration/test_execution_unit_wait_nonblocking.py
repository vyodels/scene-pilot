from __future__ import annotations

import time
from threading import Event

from recruit_agent.execution_units.runner import ExecutionUnitRunner
from recruit_agent.execution_units.store import ExecutionUnitStore


def test_execution_unit_wait_is_nonblocking_for_inflight_work() -> None:
    blocker = Event()

    def _worker(payload: dict[str, object]) -> dict[str, object]:
        blocker.wait(timeout=1)
        return {"output": {"payload": payload}}

    runner = ExecutionUnitRunner(store=ExecutionUnitStore(), workers={"browser": _worker})
    unit = runner.create_execution_unit("browser", {"url": "https://example.com"})

    started_at = time.time()
    snapshot = runner.wait_unit(unit.unit_id, timeout_seconds=0.05, until_statuses={"succeeded"})
    elapsed = time.time() - started_at
    assert snapshot.status in {"queued", "running"}
    assert elapsed < 0.2

    blocker.set()
    finished = runner.wait_unit(unit.unit_id, timeout_seconds=1, until_statuses={"succeeded"})

    assert finished.status == "succeeded"
    assert runner.unit_result(unit.unit_id).status == "succeeded"
