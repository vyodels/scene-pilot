from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


EXECUTION_UNIT_STATES = (
    "queued",
    "running",
    "blocked_human",
    "blocked_environment",
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
)


@dataclass(slots=True)
class ExecutionUnit:
    unit_id: str
    worker_name: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
