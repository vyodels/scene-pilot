from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any
from uuid import uuid4

from scene_pilot.execution_units.models import ExecutionUnit
from scene_pilot.execution_units.store import ExecutionUnitStore
from scene_pilot.runtime.models import ExecutionUnitResult


class ExecutionUnitRunner:
    def __init__(self, *, store: ExecutionUnitStore, workers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]]) -> None:
        self.store = store
        self.workers = workers

    def create_execution_unit(
        self,
        worker_name: str,
        payload: dict[str, Any],
        *,
        cooldown_seconds: int = 0,
    ) -> ExecutionUnit:
        unit = ExecutionUnit(
            unit_id=uuid4().hex,
            worker_name=worker_name,
            payload=dict(payload),
            metadata={"cooldown_seconds": cooldown_seconds},
        )
        self.store.add(unit)
        self._run(unit)
        return self.store.get(unit.unit_id) or unit

    def wait_unit(self, unit_id: str) -> ExecutionUnit:
        unit = self.store.get(unit_id)
        if unit is None:
            raise KeyError(f"unknown execution unit: {unit_id}")
        return unit

    def unit_result(self, unit_id: str) -> ExecutionUnitResult:
        unit = self.wait_unit(unit_id)
        return ExecutionUnitResult(
            unit_id=unit.unit_id,
            status=unit.status,
            output=dict(unit.output),
            error=unit.error,
            metadata=dict(unit.metadata),
        )

    def _run(self, unit: ExecutionUnit) -> None:
        worker = self.workers.get(unit.worker_name)
        if worker is None:
            failed = replace(unit, status="failed", error=f"unknown worker: {unit.worker_name}")
            self.store.update(failed)
            return
        running = replace(unit, status="running")
        self.store.update(running)
        try:
            output = worker(dict(unit.payload))
        except Exception as exc:  # pragma: no cover - defensive guard
            failed = replace(running, status="failed", error=str(exc))
            self.store.update(failed)
            return
        succeeded = replace(running, status="succeeded", output=dict(output))
        self.store.update(succeeded)
