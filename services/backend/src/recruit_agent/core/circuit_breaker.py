from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class CircuitBreakerSnapshot:
    state: str
    failure_count: int
    opened_at: datetime | None
    circuit_until: datetime | None
    last_error: str | None


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_timeout: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.failure_threshold = max(int(failure_threshold), 1)
        self.recovery_timeout = recovery_timeout
        self.clock = clock or _utcnow
        self.state = "closed"
        self.failure_count = 0
        self.opened_at: datetime | None = None
        self.circuit_until: datetime | None = None
        self.last_error: str | None = None

    def allow_request(self) -> bool:
        now = self.clock()
        if self.state == "open":
            if self.circuit_until is not None and now >= self.circuit_until:
                self.state = "half_open"
                return True
            return False
        return True

    def record_failure(self, error: str | None = None) -> None:
        now = self.clock()
        self.failure_count += 1
        self.last_error = error
        if self.state == "half_open" or self.failure_count >= self.failure_threshold:
            self.state = "open"
            self.opened_at = now
            self.circuit_until = now + self.recovery_timeout

    def record_success(self) -> None:
        self.state = "closed"
        self.failure_count = 0
        self.opened_at = None
        self.circuit_until = None
        self.last_error = None

    def snapshot(self) -> CircuitBreakerSnapshot:
        return CircuitBreakerSnapshot(
            state=self.state,
            failure_count=self.failure_count,
            opened_at=self.opened_at,
            circuit_until=self.circuit_until,
            last_error=self.last_error,
        )
