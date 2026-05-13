from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class AgentTurnOutcome:
    status: Literal["continue", "complete", "wait_human", "escalate", "error", "cancelled"]
    gate_signal: Literal["continue", "wait_human", "budget_exhausted", "run_done", "paused", "escalate"] | None = None
    final_output: str | None = None
    result_data: dict[str, Any] | None = None
    skill_draft: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    memory_updates: list[dict[str, Any]] = field(default_factory=list)
    effects: dict[str, Any] = field(default_factory=dict)
    escalate_reason: str | None = None
    checkpoint: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
