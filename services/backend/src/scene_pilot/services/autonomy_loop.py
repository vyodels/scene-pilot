from __future__ import annotations

import asyncio
import logging
from typing import Any

from scene_pilot.agents.heartbeat import Heartbeat

logger = logging.getLogger(__name__)


class AutonomyLoop:
    def __init__(
        self,
        *,
        heartbeat: Heartbeat,
        enabled: bool,
        health_sweep_enabled: bool,
        health_sweep_interval: float,
        idle_poll_interval_seconds: float = 1.0,
        processed_poll_interval_seconds: float = 0.05,
        paused_poll_interval_seconds: float = 1.0,
    ) -> None:
        self.heartbeat = heartbeat
        self.enabled = enabled
        self.health_sweep_enabled = health_sweep_enabled
        self.health_sweep_interval = health_sweep_interval
        self.idle_poll_interval_seconds = idle_poll_interval_seconds
        self.processed_poll_interval_seconds = processed_poll_interval_seconds
        self.paused_poll_interval_seconds = paused_poll_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="scene-pilot-autonomy-loop")

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                if not self.enabled:
                    await asyncio.sleep(self.paused_poll_interval_seconds)
                    continue

                try:
                    result = await asyncio.to_thread(self.heartbeat.run_once)
                except Exception:
                    logger.exception("autonomy loop failed while processing heartbeat task")
                    await asyncio.sleep(self.idle_poll_interval_seconds)
                    continue

                status = str((result or {}).get("status") or "idle").strip().lower()
                if status == "processed":
                    await asyncio.sleep(self.processed_poll_interval_seconds)
                elif status == "paused":
                    await asyncio.sleep(self.paused_poll_interval_seconds)
                else:
                    await asyncio.sleep(self.idle_poll_interval_seconds)
        except asyncio.CancelledError:
            raise
