from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SceneExecutionLimits:
    token_budget: int | None = None
    max_llm_invocations: int = 8
    tool_timeout_seconds: int = 30
    min_wakeup_delay_seconds: int = 60
    max_wakeup_delay_seconds: int = 86_400


@dataclass(slots=True)
class TurnLimits:
    max_llm_invocations: int | None = None
    turn_timeout_seconds: int | None = None
    token_budget: int | None = None
    cooldown_seconds: int = 0
