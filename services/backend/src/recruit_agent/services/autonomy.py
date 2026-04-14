from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from recruit_agent.services.agent import AgentControlService
from recruit_agent.services.events import EventStreamService


@dataclass(slots=True)
class AutonomyLoopService:
    agent_control: AgentControlService
    events: EventStreamService
    enabled: bool = False
    idle_poll_interval: float = 0.5
    active_poll_interval: float = 0.05
    run_skill_health_sweep: Callable[[], dict[str, Any]] | None = None
    health_sweep_enabled: bool = False
    health_sweep_interval: float = 300.0
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _next_health_sweep_at: float = field(default=0.0, init=False, repr=False)

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if not self.enabled or self.is_running():
            return
        self._stop_event.clear()
        self._next_health_sweep_at = time.monotonic()
        self._task = asyncio.create_task(self._run(), name="recruit-agent-autonomy-loop")
        self.events.publish("info", "autonomy", "Autonomy loop started.")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        task = self._task
        self._task = None
        await task
        self.events.publish("info", "autonomy", "Autonomy loop stopped.")

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                outcome = self.agent_control.run_once()
            except Exception as exc:  # pragma: no cover - defensive guard
                self.events.publish("error", "autonomy", "Autonomy loop iteration failed.", error=str(exc))
                outcome = None

            self._maybe_run_skill_health_sweep()

            interval = self.active_poll_interval if outcome is not None else self.idle_poll_interval
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    def _maybe_run_skill_health_sweep(self) -> None:
        if not self.health_sweep_enabled or self.run_skill_health_sweep is None:
            return
        now = time.monotonic()
        if now < self._next_health_sweep_at:
            return

        self._next_health_sweep_at = now + max(self.health_sweep_interval, 1.0)
        try:
            result = self.run_skill_health_sweep()
        except Exception as exc:  # pragma: no cover - defensive guard
            self.events.publish("error", "autonomy", "Skill health sweep failed.", error=str(exc))
            return

        checked_count = int(result.get("checked_count", 0) or 0)
        degraded_count = int(result.get("degraded_count", 0) or 0)
        if checked_count == 0:
            return

        level = "warning" if degraded_count else "info"
        self.events.publish(
            level,
            "skill_health",
            "Autonomy skill health sweep completed.",
            checked_count=checked_count,
            degraded_count=degraded_count,
            degraded_skill_ids=list(result.get("degraded_skill_ids") or []),
            healthy_skill_ids=list(result.get("healthy_skill_ids") or []),
        )
