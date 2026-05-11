from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar


ResultT = TypeVar("ResultT")


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 5.0
    multiplier: float = 2.0

    def next_delay(self, attempt: int) -> float:
        bounded_attempt = max(attempt - 1, 0)
        delay = self.base_delay_seconds * (self.multiplier ** bounded_attempt)
        return min(delay, self.max_delay_seconds)


async def retry_async(
    fn: Callable[[], Awaitable[ResultT]],
    *,
    policy: RetryPolicy | None = None,
    should_retry: Callable[[Exception], bool] | None = None,
) -> ResultT:
    active_policy = policy or RetryPolicy()
    last_error: Exception | None = None
    for attempt in range(1, active_policy.max_attempts + 1):
        try:
            return await fn()
        except Exception as exc:  # pragma: no cover - shared retry guard
            last_error = exc
            if should_retry is not None and not should_retry(exc):
                raise
            if attempt >= active_policy.max_attempts:
                raise
            await asyncio.sleep(active_policy.next_delay(attempt))
    assert last_error is not None
    raise last_error
