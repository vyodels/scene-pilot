from __future__ import annotations

import asyncio

from recruit_agent.services.autonomy_loop import AutonomyLoop


class StubHeartbeat:
    def __init__(self) -> None:
        self.calls = 0

    def run_once(self) -> dict[str, str]:
        self.calls += 1
        return {"status": "idle"}


async def _wait_until(predicate, *, timeout_seconds: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def test_autonomy_loop_runs_heartbeat_when_enabled() -> None:
    heartbeat = StubHeartbeat()
    loop = AutonomyLoop(
        heartbeat=heartbeat,
        enabled=True,
        health_sweep_enabled=False,
        health_sweep_interval=300.0,
        idle_poll_interval_seconds=0.01,
        processed_poll_interval_seconds=0.01,
        paused_poll_interval_seconds=0.01,
    )

    async def scenario() -> None:
        await loop.start()
        await _wait_until(lambda: heartbeat.calls >= 1)
        await loop.stop()

    asyncio.run(scenario())
    assert heartbeat.calls >= 1


def test_autonomy_loop_can_resume_after_being_enabled_later() -> None:
    heartbeat = StubHeartbeat()
    loop = AutonomyLoop(
        heartbeat=heartbeat,
        enabled=False,
        health_sweep_enabled=False,
        health_sweep_interval=300.0,
        idle_poll_interval_seconds=0.01,
        processed_poll_interval_seconds=0.01,
        paused_poll_interval_seconds=0.01,
    )

    async def scenario() -> None:
        await loop.start()
        await asyncio.sleep(0.05)
        assert heartbeat.calls == 0
        loop.enabled = True
        await _wait_until(lambda: heartbeat.calls >= 1)
        await loop.stop()

    asyncio.run(scenario())
    assert heartbeat.calls >= 1
