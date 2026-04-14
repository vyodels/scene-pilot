from __future__ import annotations

import sys
import tempfile
from datetime import timedelta
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.models import SyncBacklogEntry, TaskQueueItem
from scene_pilot.scheduler.queue import InMemoryQueue, SqlAlchemyQueue, TaskEnvelope
from scene_pilot.scheduler.scheduler import SerialScheduler
from scene_pilot.runtime.models import AgentResult
from scene_pilot.services.sync import SyncService


class QueueTests(unittest.TestCase):
    def test_priority_ordering(self) -> None:
        queue = InMemoryQueue()
        queue.put(TaskEnvelope(task_id="low", task_type="screen", priority=1))
        queue.put(TaskEnvelope(task_id="high", task_type="screen", priority=10))
        queue.put(TaskEnvelope(task_id="mid", task_type="screen", priority=5))

        self.assertEqual(queue.peek().task_id, "high")
        self.assertEqual(queue.get().task_id, "high")
        self.assertEqual(queue.get().task_id, "mid")
        self.assertEqual(queue.get().task_id, "low")
        self.assertTrue(queue.empty())

    def test_sqlalchemy_queue_persists_priority_order(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = AppSettings(
                data_dir=tempdir,
                database_url="sqlite:///./queue-test.db",
            )
            engine = create_engine_from_settings(settings)
            initialize_database(engine)
            session_factory = create_session_factory(engine)
            queue = SqlAlchemyQueue(session_factory)

            queue.put(TaskEnvelope(task_id="low", task_type="screen", priority=1, candidate_id="cand-low"))
            queue.put(TaskEnvelope(task_id="high", task_type="screen", priority=10, candidate_id="cand-high"))

            self.assertEqual(queue.size(), 2)
            self.assertEqual(queue.peek().task_id, "high")

            claimed = queue.get()
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.task_id, "high")
            self.assertEqual(claimed.candidate_id, "cand-high")
            self.assertEqual(queue.size(), 1)

            queue.mark_complete(claimed.task_id)
            self.assertEqual(queue.get().task_id, "low")

    def test_sync_service_uses_persistent_backlog_when_session_factory_present(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = AppSettings(
                data_dir=tempdir,
                database_url="sqlite:///./sync-test.db",
            )
            engine = create_engine_from_settings(settings)
            initialize_database(engine)
            session_factory = create_session_factory(engine)
            sync = SyncService(intranet_enabled=True, session_factory=session_factory)

            item = sync.enqueue("candidate", "cand-001", {"status": "passed"})
            self.assertEqual(item.item_id, "cand-001")
            self.assertEqual(sync.pending_count(), 1)
            pending_item = sync.pending()[0]
            self.assertEqual(pending_item.body["status"], "passed")
            self.assertEqual(pending_item.payload["delivery"]["mode"], "local_first")

            sync.mark_synced("cand-001", item_type="candidate")
            self.assertEqual(sync.pending_count(), 0)

    def test_sqlalchemy_queue_recovers_stale_running_task(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = AppSettings(
                data_dir=tempdir,
                database_url="sqlite:///./queue-recovery.db",
            )
            engine = create_engine_from_settings(settings)
            initialize_database(engine)
            session_factory = create_session_factory(engine)
            queue = SqlAlchemyQueue(session_factory, stale_after=timedelta(seconds=0))

            queue.put(TaskEnvelope(task_id="recover-me", task_type="screen", priority=5))
            claimed = queue.get()

            self.assertIsNotNone(claimed)
            self.assertEqual(queue.size(), 0)
            self.assertEqual(queue.recover_stale(), 1)
            self.assertEqual(queue.size(), 1)
            self.assertEqual(queue.get().task_id, "recover-me")

            with session_factory() as session:
                record = session.get(TaskQueueItem, "recover-me")
                self.assertIsNotNone(record)
                history = (record.payload.get("queue_audit") or {}).get("history") or []
                self.assertEqual([event["kind"] for event in history], ["enqueued", "claimed", "recovered_stale", "claimed"])

    def test_sync_service_keeps_backlog_pending_without_remote_target(self) -> None:
        sync = SyncService(intranet_enabled=True)
        sync.enqueue("candidate", "cand-002", {"status": "pending"})

        result = sync.flush_pending()

        self.assertEqual(result.attempted, 0)
        self.assertEqual(result.synced, 0)
        self.assertEqual(result.pending, 1)

    def test_sync_service_flushes_when_transport_available(self) -> None:
        sync = SyncService(
            intranet_enabled=True,
            target={"kind": "intranet", "base_url": "http://intranet.example"},
            transport=lambda item: {"success": True, "item_id": item.item_id},
        )
        sync.enqueue("candidate", "cand-003", {"status": "ready"})

        result = sync.flush_pending()

        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.synced, 1)
        self.assertEqual(sync.pending_count(), 0)

    def test_sync_service_records_failed_delivery_attempt(self) -> None:
        sync = SyncService(
            intranet_enabled=True,
            target={"kind": "intranet", "base_url": "http://intranet.example"},
            transport=lambda item: {"success": False, "error": f"failed:{item.item_id}"},
        )
        sync.enqueue("candidate", "cand-004", {"status": "ready"})

        result = sync.flush_pending()

        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.failed, 1)
        pending_item = sync.pending()[0]
        self.assertEqual(pending_item.attempt_count, 1)
        self.assertEqual(pending_item.last_error, "failed:cand-004")
        self.assertIsNotNone(pending_item.next_attempt_at)

    def test_sync_service_defers_retry_until_next_attempt_window(self) -> None:
        sync = SyncService(
            intranet_enabled=True,
            target={"kind": "intranet", "base_url": "http://intranet.example"},
            transport=lambda item: {"success": False, "error": f"failed:{item.item_id}"},
            retry_backoff_seconds=120,
        )
        sync.enqueue("candidate", "cand-005", {"status": "ready"})

        first = sync.flush_pending()
        second = sync.flush_pending()

        self.assertEqual(first.attempted, 1)
        self.assertEqual(first.failed, 1)
        self.assertEqual(second.attempted, 0)
        self.assertEqual(second.deferred, 1)
        self.assertEqual(second.pending, 1)
        self.assertIsNotNone(second.next_attempt_at)

    def test_sync_service_marks_item_failed_after_max_attempts(self) -> None:
        sync = SyncService(
            intranet_enabled=True,
            target={"kind": "intranet", "base_url": "http://intranet.example"},
            transport=lambda item: {"success": False, "error": f"failed:{item.item_id}"},
            retry_backoff_seconds=1,
            max_attempts=1,
        )
        sync.enqueue("candidate", "cand-006", {"status": "ready"})

        result = sync.flush_pending()

        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.pending, 0)
        backlog_item = sync.list_backlog(status="failed")[0]
        self.assertEqual(backlog_item.status, "failed")
        self.assertEqual(backlog_item.attempt_count, 1)
        self.assertIsNone(backlog_item.next_attempt_at)

    def test_sync_service_clears_delivery_error_after_successful_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = AppSettings(
                data_dir=tempdir,
                database_url="sqlite:///./sync-retry-success.db",
            )
            engine = create_engine_from_settings(settings)
            initialize_database(engine)
            session_factory = create_session_factory(engine)
            attempts = {"count": 0}

            def transport(item):
                attempts["count"] += 1
                return {"success": attempts["count"] > 1, "item_id": item.item_id, "error": f"failed:{item.item_id}"}

            sync = SyncService(
                intranet_enabled=True,
                session_factory=session_factory,
                target={"kind": "intranet", "base_url": "http://intranet.example"},
                transport=transport,
                retry_backoff_seconds=0,
            )
            sync.enqueue("candidate", "cand-007", {"status": "ready"})

            first = sync.flush_pending()
            second = sync.flush_pending()

            self.assertEqual(first.failed, 1)
            self.assertEqual(second.synced, 1)
            status = sync.status_snapshot()
            self.assertEqual(status.pending_count, 0)
            self.assertEqual(status.failed_delivery_count, 0)

            with session_factory() as session:
                record = session.query(SyncBacklogEntry).filter(SyncBacklogEntry.item_id == "cand-007").first()
                self.assertIsNotNone(record)
                self.assertEqual(record.status, "synced")
                self.assertIsNone(record.last_error)
                delivery = (record.payload or {}).get("delivery") or {}
                self.assertIsNone(delivery.get("last_error"))
                self.assertIsNone(delivery.get("next_attempt_at"))

    def test_serial_scheduler_persists_retry_and_failure_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = AppSettings(
                data_dir=tempdir,
                database_url="sqlite:///./queue-audit.db",
            )
            engine = create_engine_from_settings(settings)
            initialize_database(engine)
            session_factory = create_session_factory(engine)
            queue = SqlAlchemyQueue(session_factory)
            scheduler = SerialScheduler(queue=queue, max_attempts=2)

            def runner(task: TaskEnvelope) -> AgentResult:
                raise RuntimeError(f"boom:{task.task_id}")

            scheduler.runner = runner
            scheduler.submit(TaskEnvelope(task_id="audit-me", task_type="screen", priority=10))

            first = scheduler.run_once()
            second = scheduler.run_once()

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertEqual(first.error, "boom:audit-me")
            self.assertEqual(second.error, "boom:audit-me")

            with session_factory() as session:
                record = session.get(TaskQueueItem, "audit-me")
                self.assertIsNotNone(record)
                self.assertEqual(record.status, "failed")
                audit = (record.payload.get("queue_audit") or {})
                history = audit.get("history") or []
                self.assertEqual(
                    [event["kind"] for event in history],
                    ["enqueued", "claimed", "returned_to_queue", "claimed", "failed"],
                )
                self.assertEqual(history[2]["error"], "boom:audit-me")
                self.assertEqual(history[-1]["error"], "boom:audit-me")


if __name__ == "__main__":
    unittest.main()
