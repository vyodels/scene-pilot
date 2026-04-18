from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RuntimeLimits:
    max_turns: int = 8
    token_budget: int = 12_000
    max_tool_roundtrips: int = 8
    min_wakeup_delay_seconds: int = 60
    max_wakeup_delay_seconds: int = 86_400
