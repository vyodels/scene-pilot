from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from heapq import heappop, heappush
from itertools import count
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker


@dataclass(slots=True)
class TaskEnvelope:
    task_id: str
    task_type: str
    priority: int = 100
    payload: dict[str, Any] = field(default_factory=dict)
    platform: str = "site"
    application_id: str | None = None
    candidate_id: str | None = None
    due_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attempts: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskQueue(Protocol):
    def put(self, task: TaskEnvelope) -> None: ...

    def get(self) -> TaskEnvelope | None: ...

    def peek(self) -> TaskEnvelope | None: ...

    def size(self) -> int: ...

    def empty(self) -> bool: ...


def _serialize_task(task: TaskEnvelope) -> dict[str, Any]:
    return {
        "payload": dict(task.payload),
        "platform": task.platform,
        "application_id": task.application_id,
        "candidate_id": task.candidate_id,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "created_at": task.created_at.isoformat(),
        "metadata": dict(task.metadata),
    }


def _deserialize_task(task_id: str, task_type: str, priority: int, attempts: int, payload: dict[str, Any]) -> TaskEnvelope:
    envelope = dict(payload or {})
    due_at = envelope.get("due_at")
    created_at = envelope.get("created_at")
    return TaskEnvelope(
        task_id=task_id,
        task_type=task_type,
        priority=priority,
        payload=dict(envelope.get("payload", {})),
        platform=str(envelope.get("platform", "site")),
        application_id=envelope.get("application_id"),
        candidate_id=envelope.get("candidate_id"),
        due_at=datetime.fromisoformat(due_at) if isinstance(due_at, str) and due_at else None,
        created_at=datetime.fromisoformat(created_at) if isinstance(created_at, str) and created_at else datetime.now(timezone.utc),
        attempts=attempts,
        metadata=dict(envelope.get("metadata", {})),
    )


class InMemoryQueue:
    def __init__(self) -> None:
        self._heap: list[tuple[int, datetime, int, TaskEnvelope]] = []
        self._counter = count()

    def put(self, task: TaskEnvelope) -> None:
        heappush(self._heap, (-task.priority, task.created_at, next(self._counter), task))

    def get(self) -> TaskEnvelope | None:
        if not self._heap:
            return None
        return heappop(self._heap)[3]

    def peek(self) -> TaskEnvelope | None:
        if not self._heap:
            return None
        return self._heap[0][3]

    def size(self) -> int:
        return len(self._heap)

    def empty(self) -> bool:
        return not self._heap

    def clear(self) -> None:
        self._heap.clear()

    def extend(self, tasks: Iterable[TaskEnvelope]) -> None:
        for task in tasks:
            self.put(task)


class RedisQueueStub(InMemoryQueue):
    def __init__(self, namespace: str = "recruit-agent", redis_url: str | None = None) -> None:
        super().__init__()
        self.namespace = namespace
        self.redis_url = redis_url


class SqlAlchemyQueue:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        locked_by: str = "scheduler",
        stale_after: timedelta = timedelta(minutes=5),
    ) -> None:
        self.session_factory = session_factory
        self.locked_by = locked_by
        self.stale_after = stale_after

    def put(self, task: TaskEnvelope) -> None:
        from scene_pilot.repositories.domain import TaskQueueRepository

        with self.session_factory() as session:
            TaskQueueRepository(session).enqueue(
                task_id=task.task_id,
                task_type=task.task_type,
                priority=task.priority,
                payload=_serialize_task(task),
                scheduled_for=task.due_at,
                attempts=task.attempts,
            )

    def get(self) -> TaskEnvelope | None:
        from scene_pilot.repositories.domain import TaskQueueRepository

        with self.session_factory() as session:
            record = TaskQueueRepository(session).claim_next(locked_by=self.locked_by)
            if record is None:
                return None
            return _deserialize_task(record.id, record.task_type, record.priority, record.attempts, record.payload)

    def peek(self) -> TaskEnvelope | None:
        from scene_pilot.repositories.domain import TaskQueueRepository

        with self.session_factory() as session:
            records = TaskQueueRepository(session).list_pending(limit=1)
            if not records:
                return None
            record = records[0]
            return _deserialize_task(record.id, record.task_type, record.priority, record.attempts, record.payload)

    def size(self) -> int:
        from scene_pilot.repositories.domain import TaskQueueRepository

        with self.session_factory() as session:
            return TaskQueueRepository(session).pending_count()

    def empty(self) -> bool:
        return self.size() == 0

    def mark_complete(self, task_id: str) -> None:
        from scene_pilot.repositories.domain import TaskQueueRepository

        with self.session_factory() as session:
            TaskQueueRepository(session).mark_complete(task_id)

    def mark_pending(self, task: TaskEnvelope, *, error: str | None = None) -> None:
        from scene_pilot.repositories.domain import TaskQueueRepository

        with self.session_factory() as session:
            TaskQueueRepository(session).mark_pending(task.task_id, attempts=task.attempts, error=error)

    def mark_failed(self, task_id: str, *, error: str | None = None) -> None:
        from scene_pilot.repositories.domain import TaskQueueRepository

        with self.session_factory() as session:
            TaskQueueRepository(session).mark_failed(task_id, error=error)

    def recover_stale(self, *, stale_after: timedelta | None = None) -> int:
        from scene_pilot.db.base import utcnow
        from scene_pilot.repositories.domain import TaskQueueRepository

        effective_stale_after = self.stale_after if stale_after is None else stale_after
        locked_before = utcnow() - effective_stale_after
        with self.session_factory() as session:
            return TaskQueueRepository(session).recover_stale_running(locked_before=locked_before)
