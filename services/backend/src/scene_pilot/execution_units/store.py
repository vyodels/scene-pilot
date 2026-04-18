from __future__ import annotations

from dataclasses import replace

from scene_pilot.execution_units.models import ExecutionUnit


class ExecutionUnitStore:
    def __init__(self) -> None:
        self._units: dict[str, ExecutionUnit] = {}

    def add(self, unit: ExecutionUnit) -> ExecutionUnit:
        self._units[unit.unit_id] = unit
        return unit

    def get(self, unit_id: str) -> ExecutionUnit | None:
        unit = self._units.get(unit_id)
        return None if unit is None else replace(unit)

    def update(self, unit: ExecutionUnit) -> ExecutionUnit:
        self._units[unit.unit_id] = unit
        return unit
