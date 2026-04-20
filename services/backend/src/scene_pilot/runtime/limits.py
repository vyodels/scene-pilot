from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RoundLimits:
    token_budget: int = 1_200_000
    max_tool_roundtrips: int = 8
    tool_timeout_seconds: int = 30
    min_wakeup_delay_seconds: int = 60
    max_wakeup_delay_seconds: int = 86_400


@dataclass(slots=True)
class TurnLimits:
    max_rounds_per_turn: int = 800
    turn_timeout_seconds: int = 120
    token_budget: int = 2_400_000
    cooldown_seconds: int = 0
