from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class FeatureFlagError(RuntimeError):
    pass


@dataclass(slots=True)
class FeatureFlagService:
    flags: dict[str, bool] = field(default_factory=dict)

    def is_enabled(self, name: str, default: bool = False) -> bool:
        return bool(self.flags.get(name, default))

    def set_flag(self, name: str, enabled: bool) -> None:
        self.flags[name] = bool(enabled)

    def merge(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self.set_flag(key, bool(value))

    def require_enabled(self, name: str) -> None:
        if not self.is_enabled(name):
            raise FeatureFlagError(f"Feature flag disabled: {name}")
