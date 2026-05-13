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
        from recruit_agent.core.settings import load_settings
        from recruit_agent.server import create_app

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

        heartbeat = self.client.get("/api/agents/heartbeat/status")
        self.assertEqual(heartbeat.status_code, 200)
        self.assertIn("autonomous_paused", heartbeat.json())

        task = self.client.post(
            "/api/agents/tasks",
            json={"task_type": "autonomous_turn", "priority": 100, "payload": {"scope_kind": "global", "scope_ref": "system"}},
        )
        self.assertEqual(task.status_code, 200)

        queue = self.client.get("/api/agents/queue")
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

        recruit = self.client.get("/api/recruit/applications/locks")
        self.assertEqual(recruit.status_code, 200)
        self.assertEqual(recruit.json(), [])

        evolution = self.client.get("/api/evolution/queue", params={"status": "pending_review"})
        self.assertEqual(evolution.status_code, 200)
        self.assertEqual(evolution.json(), [])

    def test_workspace_bootstrap_surfaces(self) -> None:
        responses = {
            "/api/settings": self.client.get("/api/settings"),
            "/api/dashboard": self.client.get("/api/dashboard"),
            "/api/agents": self.client.get("/api/agents"),
            "/api/agents/autonomous": self.client.get("/api/agents/autonomous"),
            "/api/agents/autonomous/runs": self.client.get("/api/agents/autonomous/runs"),
            "/api/agents/autonomous/approvals": self.client.get("/api/agents/autonomous/approvals"),
            "/api/agents/autonomous/memory/global": self.client.get("/api/agents/autonomous/memory/global"),
            "/api/agents/autonomous/skills": self.client.get("/api/agents/autonomous/skills"),
            "/api/agents/autonomous/mcp": self.client.get("/api/agents/autonomous/mcp"),
            "/api/approvals": self.client.get("/api/approvals"),
            "/api/skills": self.client.get("/api/skills"),
            "/api/sync/status": self.client.get("/api/sync/status"),
            "/api/mcp/presets": self.client.get("/api/mcp/presets"),
            "/api/mcp/servers": self.client.get("/api/mcp/servers"),
            "/api/recruit-agent/agent-definition": self.client.get("/api/recruit-agent/agent-definition"),
            "/api/recruit-agent/runtime/traces": self.client.get("/api/recruit-agent/runtime/traces"),
            "/api/recruit-agent/runtime/graphs": self.client.get("/api/recruit-agent/runtime/graphs"),
            "/api/recruit-agent/runtime/strategy-fragments": self.client.get("/api/recruit-agent/runtime/strategy-fragments"),
            "/api/recruit-agent/runtime/operator-interactions": self.client.get("/api/recruit-agent/runtime/operator-interactions"),
            "/api/candidate-applications/threads": self.client.get("/api/candidate-applications/threads"),
            "/api/state-machine": self.client.get("/api/state-machine"),
            "/api/recruit-agent/evolution-artifacts": self.client.get("/api/recruit-agent/evolution-artifacts"),
        }

        for path, response in responses.items():
            with self.subTest(path=path):
                self.assertEqual(response.status_code, 200, path)

    def test_dashboard_learning_alerts_do_not_parse_jsonish_content_as_business_protocol(self) -> None:
        from recruit_agent.models.domain import AgentLearning

        with self.client.app.state.session_factory() as session:
            session.add(
                AgentLearning(
                    content=(
                        '{"run_title":"同步 JD（增量）","status":"blocked","created":0,"updated":0,"skipped":0,"blocked":1,'
                        '"evidence":["当前浏览器仅有 1 个标签页：\'CLI Proxy API Management Center\'",'
                        '"活动页 URL: http://127.0.0.1:8317/management.html#/auth-files"],'
                        '"next_step":"请先在浏览器中打开并切换到招聘平台的职位列表或职位详情页面，然后继续同步。"}'
                    ),
                    tags=["autonomous", "global"],
                    is_active=True,
                )
            )
            session.commit()

        dashboard = self.client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        learning_alert = next(item for item in dashboard.json()["alerts"] if item["label"] == "可用学习草案")
        self.assertNotIn("标签页", learning_alert["detail"])
        self.assertNotIn("http://", learning_alert["detail"])
        self.assertEqual(learning_alert["detail"], "学习草案包含结构化内容，待查看。")

    def test_approval_update_and_blocked_task_approve_surfaces(self) -> None:
        created = self.client.post(
            "/api/approvals",
            json={
                "target_type": "blocked_task",
                "target_id": "approval-target-1",
                "title": "Resume blocked task",
                "payload": {"blocked_task": {"task_type": "instruction_intake", "payload": {"run_id": "r-1"}}},
            },
        )
        self.assertEqual(created.status_code, 201)
        approval_id = created.json()["id"]

        patched = self.client.patch(
            f"/api/approvals/{approval_id}",
            json={"notes": "updated from api test"},
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["notes"], "updated from api test")

        approved = self.client.post(
            f"/api/approvals/{approval_id}/approve",
            json={"reviewer": "api-test", "reason": "resume now"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")


if __name__ == "__main__":
    unittest.main()
