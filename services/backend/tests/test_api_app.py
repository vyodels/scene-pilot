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

    def test_health_and_dashboard(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ready")

        dashboard = self.client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        payload = dashboard.json()
        self.assertIn("metrics", payload)
        self.assertIn("applications", payload)
        self.assertIn("agent", payload)

    def test_settings_patch(self) -> None:
        response = self.client.patch(
            "/api/settings",
            json={
                "intranetEnabled": True,
                "platform": {"account": "boss-02", "allowOutboundMessaging": True},
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["intranetEnabled"])
        self.assertEqual(payload["platform"]["account"], "boss-02")
        self.assertTrue(payload["platform"]["allowOutboundMessaging"])


if __name__ == "__main__":
    unittest.main()
