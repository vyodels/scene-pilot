from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RoundLimits:
    token_budget: int | None = None
    max_tool_roundtrips: int = 8
    tool_timeout_seconds: int = 30
    min_wakeup_delay_seconds: int = 60
    max_wakeup_delay_seconds: int = 86_400


@dataclass(slots=True)
class TurnLimits:
    max_rounds_per_turn: int | None = None
    turn_timeout_seconds: int | None = None
    token_budget: int | None = None
    cooldown_seconds: int = 0
