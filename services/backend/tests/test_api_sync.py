from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None  # type: ignore[assignment]


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed")
class ApiSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        from scene_pilot.core.settings import load_settings
        from scene_pilot.server import create_app

        self.tempdir = tempfile.TemporaryDirectory()
        os.environ["SCENE_PILOT_DATA_DIR"] = self.tempdir.name
        load_settings.cache_clear()
        self.client = TestClient(create_app())
        self.client.__enter__()
        self._load_settings = load_settings
        self.container = self.client.app.state.container

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.tempdir.cleanup()
        os.environ.pop("SCENE_PILOT_DATA_DIR", None)
        self._load_settings.cache_clear()

    def test_sync_status_and_backlog_listing(self) -> None:
        self.container.sync.enqueue("candidate", "cand-001", {"status": "pending"})
        self.container.sync.enqueue("digest", "news-001", {"status": "ready"})

        status = self.client.get("/api/sync/status")
        self.assertEqual(status.status_code, 200)
        payload = status.json()
        self.assertEqual(payload["pending_count"], 2)
        self.assertEqual(payload["backlog_total"], 2)
        self.assertEqual(payload["by_status"]["pending"], 2)
        self.assertFalse(payload["remote_available"])
        self.assertEqual(payload["deferred_count"], 0)
        self.assertIsNone(payload["next_attempt_at"])

        backlog = self.client.get("/api/sync/backlog")
        self.assertEqual(backlog.status_code, 200)
        self.assertEqual(len(backlog.json()), 2)
        self.assertEqual(backlog.json()[0]["status"], "pending")
        self.assertEqual(backlog.json()[0]["delivery_mode"], "local_first")

    def test_sync_flush_updates_status_and_backlog(self) -> None:
        self.container.sync.intranet_enabled = True
        self.container.sync.target = {"kind": "intranet", "base_url": "http://intranet.example", "api_path": "/sync"}
        self.container.sync.transport = lambda item: {"success": True, "item_id": item.item_id}
        self.container.sync.enqueue("candidate", "cand-002", {"status": "ready"})

        flushed = self.client.post("/api/sync/flush?limit=10")
        self.assertEqual(flushed.status_code, 200)
        flush_payload = flushed.json()
        self.assertEqual(flush_payload["attempted"], 1)
        self.assertEqual(flush_payload["synced"], 1)
        self.assertEqual(flush_payload["deferred"], 0)
        self.assertEqual(flush_payload["pending"], 0)
        self.assertTrue(flush_payload["remote_available"])
        self.assertIsNone(flush_payload["next_attempt_at"])

        status = self.client.get("/api/sync/status")
        self.assertEqual(status.status_code, 200)
        status_payload = status.json()
        self.assertEqual(status_payload["pending_count"], 0)
        self.assertEqual(status_payload["synced_count"], 1)
        self.assertEqual(status_payload["failed_delivery_count"], 0)

        backlog = self.client.get("/api/sync/backlog?status=synced")
        self.assertEqual(backlog.status_code, 200)
        self.assertEqual(len(backlog.json()), 1)
        self.assertEqual(backlog.json()[0]["item_id"], "cand-002")

    def test_sync_api_reports_deferred_retry_window(self) -> None:
        self.container.sync.intranet_enabled = True
        self.container.sync.target = {"kind": "intranet", "base_url": "http://intranet.example", "api_path": "/sync"}
        self.container.sync.retry_backoff_seconds = 120
        self.container.sync.transport = lambda item: {"success": False, "error": f"failed:{item.item_id}"}
        self.container.sync.enqueue("candidate", "cand-003", {"status": "ready"})

        first = self.client.post("/api/sync/flush?limit=10")
        second = self.client.post("/api/sync/flush?limit=10")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["failed"], 1)
        self.assertEqual(second.json()["attempted"], 0)
        self.assertEqual(second.json()["deferred"], 1)
        self.assertIsNotNone(second.json()["next_attempt_at"])

        status = self.client.get("/api/sync/status")
        self.assertEqual(status.status_code, 200)
        payload = status.json()
        self.assertEqual(payload["pending_count"], 1)
        self.assertEqual(payload["deferred_count"], 1)
        self.assertIsNotNone(payload["next_attempt_at"])

        backlog = self.client.get("/api/sync/backlog?status=pending")
        self.assertEqual(backlog.status_code, 200)
        self.assertEqual(len(backlog.json()), 1)
        self.assertIsNotNone(backlog.json()[0]["next_attempt_at"])


if __name__ == "__main__":
    unittest.main()
