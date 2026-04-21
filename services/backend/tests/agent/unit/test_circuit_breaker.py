from __future__ import annotations

from datetime import UTC, datetime, timedelta

from recruit_agent.runtime.circuit_breaker import CircuitBreaker


def test_circuit_breaker_opens_after_threshold_and_recovers_after_timeout() -> None:
    now = datetime(2026, 4, 19, tzinfo=UTC)

    def _clock() -> datetime:
        return now

    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=timedelta(seconds=30), clock=_clock)

    assert breaker.allow_request() is True

    breaker.record_failure("timeout")
    assert breaker.allow_request() is True

    breaker.record_failure("timeout")
    assert breaker.allow_request() is False
    assert breaker.snapshot().state == "open"

    now = now + timedelta(seconds=31)
    assert breaker.allow_request() is True
    assert breaker.snapshot().state == "half_open"

    breaker.record_success()
    assert breaker.allow_request() is True
    assert breaker.snapshot().state == "closed"


def test_circuit_breaker_tracks_last_error() -> None:
    breaker = CircuitBreaker(failure_threshold=1)

    breaker.record_failure("boom")

    snapshot = breaker.snapshot()
    assert snapshot.state == "open"
    assert snapshot.last_error == "boom"
