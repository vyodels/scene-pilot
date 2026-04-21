from __future__ import annotations

from dataclasses import replace
from threading import Condition, RLock
from time import monotonic

from recruit_agent.execution_units.models import ExecutionUnit


class ExecutionUnitStore:
    def __init__(self) -> None:
        self._units: dict[str, ExecutionUnit] = {}
        self._lock = RLock()
        self._condition = Condition(self._lock)

    def add(self, unit: ExecutionUnit) -> ExecutionUnit:
        with self._condition:
            self._units[unit.unit_id] = unit
            self._condition.notify_all()
            return unit

    def get(self, unit_id: str) -> ExecutionUnit | None:
        with self._lock:
            unit = self._units.get(unit_id)
            return None if unit is None else replace(unit)

    def update(self, unit: ExecutionUnit) -> ExecutionUnit:
        with self._condition:
            self._units[unit.unit_id] = unit
            self._condition.notify_all()
            return unit

    def wait(
        self,
        unit_id: str,
        *,
        timeout_seconds: float | None = None,
        until_statuses: set[str] | None = None,
    ) -> ExecutionUnit:
        deadline = None if timeout_seconds is None else monotonic() + max(timeout_seconds, 0.0)
        with self._condition:
            unit = self._units.get(unit_id)
            if unit is None:
                raise KeyError(f"unknown execution unit: {unit_id}")
            while not _should_return(unit, until_statuses):
                if deadline is not None:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        break
                else:
                    remaining = None
                self._condition.wait(timeout=remaining)
                unit = self._units.get(unit_id)
                if unit is None:
                    raise KeyError(f"unknown execution unit: {unit_id}")
            return replace(unit)


def _should_return(unit: ExecutionUnit, until_statuses: set[str] | None) -> bool:
    if not until_statuses:
        return True
    return unit.status in until_statuses
