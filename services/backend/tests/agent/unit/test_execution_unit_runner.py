from __future__ import annotations

from scene_pilot.execution_units.runner import ExecutionUnitRunner
from scene_pilot.execution_units.store import ExecutionUnitStore


def test_execution_unit_runner_executes_and_returns_result() -> None:
    store = ExecutionUnitStore()
    runner = ExecutionUnitRunner(
        store=store,
        workers={
            "browser": lambda payload: {"observed": payload["url"]},
        },
    )

    unit = runner.create_execution_unit("browser", {"url": "https://example.com"}, cooldown_seconds=5)
    waited = runner.wait_unit(unit.unit_id)
    result = runner.unit_result(unit.unit_id)

    assert unit.status == "succeeded"
    assert waited.status == "succeeded"
    assert result.output == {"observed": "https://example.com"}
    assert result.metadata["cooldown_seconds"] == 5
