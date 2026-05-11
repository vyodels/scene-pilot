from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Iterable

from .queue import InMemoryQueue, TaskEnvelope, TaskQueue


TaskRunner = Callable[[TaskEnvelope], dict[str, Any]]
FollowUpFactory = Callable[[TaskEnvelope, dict[str, Any]], Iterable[TaskEnvelope]]


class TaskDeferred(RuntimeError):
    pass


@dataclass(slots=True)
class ScheduledOutcome:
    task: TaskEnvelope
    result: dict[str, Any]
    enqueued_follow_ups: int = 0
    error: str | None = None


@dataclass(slots=True)
class SerialScheduler:
    queue: TaskQueue = field(default_factory=InMemoryQueue)
    runner: TaskRunner | None = None
    follow_up_factory: FollowUpFactory | None = None
    max_attempts: int = 3
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    history: list[ScheduledOutcome] = field(default_factory=list)

    def submit(self, task: TaskEnvelope) -> None:
        self.queue.put(task)

    def _mark_complete(self, task_id: str) -> None:
        mark_complete = getattr(self.queue, "mark_complete", None)
        if callable(mark_complete):
            mark_complete(task_id)

    def _mark_pending(self, task: TaskEnvelope, *, error: str | None = None) -> None:
        mark_pending = getattr(self.queue, "mark_pending", None)
        if callable(mark_pending):
            mark_pending(task, error=error)
            return
        self.queue.put(task)

    def _mark_failed(self, task_id: str, *, error: str | None = None) -> None:
        mark_failed = getattr(self.queue, "mark_failed", None)
        if callable(mark_failed):
            mark_failed(task_id, error=error)

    def run_once(self) -> ScheduledOutcome | None:
        recover_stale = getattr(self.queue, "recover_stale", None)
        if callable(recover_stale):
            recover_stale()
        task = self.queue.get()
        if task is None:
            return None

        if not self._lock.acquire(blocking=False):
            self.queue.put(task)
            return None

        try:
            if self.runner is None:
                result = {"success": False, "status": "no_runner", "content": ""}
            else:
                result = self.runner(task)

            enqueued_follow_ups = 0
            if self.follow_up_factory is not None and bool(result.get("success")):
                for follow_up in self.follow_up_factory(task, result):
                    self.queue.put(follow_up)
                    enqueued_follow_ups += 1

            outcome = ScheduledOutcome(task=task, result=result, enqueued_follow_ups=enqueued_follow_ups)
            self.history.append(outcome)
            self._mark_complete(task.task_id)
            return outcome
        except TaskDeferred as exc:
            self._mark_pending(task, error=str(exc))
            outcome = ScheduledOutcome(
                task=task,
                result={"success": False, "status": "deferred", "content": str(exc)},
                error=str(exc),
            )
            self.history.append(outcome)
            return outcome
        except Exception as exc:  # pragma: no cover - defensive guard
            task.attempts += 1
            if task.attempts < self.max_attempts:
                self._mark_pending(task, error=str(exc))
            else:
                self._mark_failed(task.task_id, error=str(exc))
            outcome = ScheduledOutcome(
                task=task,
                result={"success": False, "status": "failed", "content": str(exc)},
                error=str(exc),
            )
            self.history.append(outcome)
            return outcome
        finally:
            self._lock.release()

    def run_until_empty(self, limit: int | None = None) -> list[ScheduledOutcome]:
        outcomes: list[ScheduledOutcome] = []
        processed = 0
        while not self.queue.empty() and (limit is None or processed < limit):
            outcome = self.run_once()
            if outcome is None:
                break
            outcomes.append(outcome)
            processed += 1
        return outcomes
