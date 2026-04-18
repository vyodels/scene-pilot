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
class ApiAppTests(unittest.TestCase):
    def setUp(self) -> None:
        from scene_pilot.core.settings import load_settings
        from scene_pilot.server import create_app

        self.tempdir = tempfile.TemporaryDirectory()
        os.environ["RECRUIT_AGENT_DATA_DIR"] = self.tempdir.name
        load_settings.cache_clear()
        self.client = TestClient(create_app())
        self.client.__enter__()
        self._load_settings = load_settings

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.tempdir.cleanup()
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        self._load_settings.cache_clear()

    def test_health_and_agent_queue_surface(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ready")

        heartbeat = self.client.get("/api/agent/heartbeat/status")
        self.assertEqual(heartbeat.status_code, 200)
        self.assertIn("autonomous_paused", heartbeat.json())

        task = self.client.post(
            "/api/agent/tasks",
            json={"task_type": "autonomous_tick", "priority": 100, "payload": {"scope_kind": "global", "scope_ref": "system"}},
        )
        self.assertEqual(task.status_code, 200)

        queue = self.client.get("/api/agent/queue")
        self.assertEqual(queue.status_code, 200)
        self.assertEqual(len(queue.json()), 1)

    def test_assistant_recruit_and_evolution_surfaces(self) -> None:
        conversation = self.client.post(
            "/api/assistant/conversations",
            json={"user_id": "user-1", "title": "Hiring"},
        )
        self.assertEqual(conversation.status_code, 200)
        conversation_id = conversation.json()["conversation_id"]

        listed = self.client.get("/api/assistant/conversations", params={"user_id": "user-1"})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["conversation_id"], conversation_id)

        recruit = self.client.get("/api/recruit/candidates/locks")
        self.assertEqual(recruit.status_code, 200)
        self.assertEqual(recruit.json(), [])

        evolution = self.client.get("/api/evolution/queue", params={"status": "pending_review"})
        self.assertEqual(evolution.status_code, 200)
        self.assertEqual(evolution.json(), [])


if __name__ == "__main__":
    unittest.main()
