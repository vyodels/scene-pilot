from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class EventEnvelope:
    id: str
    level: str
    source: str
    message: str
    at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EventStreamService:
    max_events: int = 200
    _events: deque[EventEnvelope] = field(default_factory=deque, init=False, repr=False)

    def publish(self, level: str, source: str, message: str, **metadata: Any) -> EventEnvelope:
        event = EventEnvelope(
            id=uuid4().hex,
            level=level,
            source=source,
            message=message,
            at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata,
        )
        self._events.append(event)
        while len(self._events) > self.max_events:
            self._events.popleft()
        return event

    def snapshot(self) -> list[EventEnvelope]:
        return list(self._events)

