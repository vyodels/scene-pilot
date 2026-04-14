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
class ApiRuntimeTests(unittest.TestCase):
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

    def test_natural_language_compile_trial_execution_and_snapshot_flow(self) -> None:
        domain_packs = self.client.get("/api/runtime/domain-packs")
        self.assertEqual(domain_packs.status_code, 200)
        self.assertTrue(any(item["key"] == "web_research" for item in domain_packs.json()))

        compiled_task = self.client.post(
            "/api/runtime/task-specs/compile",
            json={
                "instruction": "Open the web and find useful PDF converters, compare them, and prepare a shortlist.",
                "title": "Research PDF converters",
                "inputs": {"target_urls": ["https://example.com"]},
                "constraints": {"requires_human_supervision": True},
                "preferred_capabilities": ["browser"],
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        compile_payload = compiled_task.json()
        self.assertEqual(compile_payload["domain_pack"]["key"], "web_research")
        task_spec_id = compile_payload["task_spec"]["id"]
        plan_id = compile_payload["execution_plan"]["id"]

        listed_tasks = self.client.get("/api/runtime/task-specs")
        self.assertEqual(listed_tasks.status_code, 200)
        created_task = next(item for item in listed_tasks.json() if item["id"] == task_spec_id)
        self.assertEqual(created_task["status"], "trial_ready")
        self.assertEqual(created_task["active_plan_id"], plan_id)

        created_trial = self.client.post(
            "/api/runtime/trial-runs",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "requested_by": "desktop-user",
                "notes": "Run as a supervised dry run first.",
                "runtime_metadata": {"run_mode": "dry_run"},
            },
        )
        self.assertEqual(created_trial.status_code, 201)
        episode_payload = created_trial.json()
        self.assertEqual(episode_payload["status"], "pending")
        self.assertTrue(episode_payload["requires_confirmation"])
        self.assertEqual(episode_payload["requested_by"], "desktop-user")
        episode_id = episode_payload["id"]

        executed_trial = self.client.post(
            f"/api/runtime/trial-runs/{episode_id}/execute",
            json={
                "source": "browser",
                "url": "https://example.com",
                "title": "Example Domain",
                "page_type": "tool_listing",
                "affordances": [{"kind": "link", "label": "More information"}],
            },
        )
        self.assertEqual(executed_trial.status_code, 200)
        executed_payload = executed_trial.json()
        self.assertEqual(executed_payload["episode"]["status"], "awaiting_review")
        self.assertIsNotNone(executed_payload["template"])
        self.assertIsNotNone(executed_payload["learning_draft"])
        self.assertIsNotNone(executed_payload["approval"])
        self.assertEqual(executed_payload["approval"]["target_type"], "skill_draft")

        confirmed_trial = self.client.post(
            f"/api/runtime/trial-runs/{episode_id}/confirm",
            json={"reviewer": "desktop-user", "reason": "Ready for production", "activate_template": True},
        )
        self.assertEqual(confirmed_trial.status_code, 200)
        confirmed_payload = confirmed_trial.json()
        self.assertEqual(confirmed_payload["episode"]["status"], "confirmed")
        self.assertIsNotNone(confirmed_payload["template"])
        self.assertEqual(confirmed_payload["template"]["status"], "active")

        refreshed_task = self.client.get("/api/runtime/task-specs")
        self.assertEqual(refreshed_task.status_code, 200)
        self.assertEqual(
            next(item for item in refreshed_task.json() if item["id"] == task_spec_id)["status"],
            "production_ready",
        )

        listed_snapshots = self.client.get(f"/api/runtime/environment-snapshots?execution_episode_id={episode_id}")
        self.assertEqual(listed_snapshots.status_code, 200)
        self.assertEqual(len(listed_snapshots.json()), 1)
        self.assertEqual(listed_snapshots.json()[0]["page_type"], "tool_listing")

        missing_plan = self.client.post(
            "/api/runtime/trial-runs",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": "missing-plan",
            },
        )
        self.assertEqual(missing_plan.status_code, 404)

    def test_templates_and_workflow_patch_review_scaffold(self) -> None:
        created_task = self.client.post(
            "/api/runtime/task-specs/compile",
            json={
                "instruction": "Open GitHub trends, inspect the repositories, and propose a safer workflow when divergence happens.",
                "title": "GitHub trends mutation candidate",
                "domain_hint": "github_trends",
            },
        )
        self.assertEqual(created_task.status_code, 201)
        task_spec_id = created_task.json()["task_spec"]["id"]

        templates = self.client.get("/api/runtime/templates")
        self.assertEqual(templates.status_code, 200)
        self.assertGreaterEqual(len(templates.json()), 1)
        plan_id = created_task.json()["execution_plan"]["id"]
        template_id = next(item["id"] for item in templates.json() if item["template_key"] == "patch_review_loop")

        created_trial = self.client.post(
            "/api/runtime/trial-runs",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "requested_by": "desktop-user",
            },
        )
        self.assertEqual(created_trial.status_code, 201)
        episode_id = created_trial.json()["id"]

        executed = self.client.post(
            f"/api/runtime/trial-runs/{episode_id}/execute",
            json={
                "source": "browser",
                "url": "https://github.com/trending",
                "title": "GitHub Trending",
                "page_type": "repository_listing",
                "simulate_divergence": True,
            },
        )
        self.assertEqual(executed.status_code, 200)
        patch_payload = executed.json()["patch"]
        self.assertIsNotNone(patch_payload)
        self.assertEqual(patch_payload["status"], "pending_review")
        self.assertEqual(executed.json()["episode"]["status"], "diverged")

        approvals = self.client.get("/api/approvals?pending_only=true")
        self.assertEqual(approvals.status_code, 200)
        linked_approval = next(item for item in approvals.json() if item["target_type"] == "workflow_patch" and item["target_id"] == patch_payload["id"])
        self.assertEqual(linked_approval["status"], "pending")

        approved_patch = self.client.post(
            f"/api/runtime/workflow-patches/{patch_payload['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Safe for trial use", "apply_immediately": True},
        )
        self.assertEqual(approved_patch.status_code, 200)
        approved_payload = approved_patch.json()
        self.assertEqual(approved_payload["status"], "applied")
        self.assertEqual(approved_payload["reviewed_by"], "desktop-user")
        self.assertIsNotNone(approved_payload["applied_at"])

        refreshed_approvals = self.client.get("/api/approvals")
        self.assertEqual(refreshed_approvals.status_code, 200)
        approved_approval = next(item for item in refreshed_approvals.json() if item["target_id"] == patch_payload["id"])
        self.assertEqual(approved_approval["status"], "approved")
        self.assertEqual(approved_approval["payload"]["resolution"]["status"], "applied")

    def test_learning_endpoint_is_repeatable_and_returns_skill_health_when_plan_has_skill_id(self) -> None:
        created_task = self.client.post(
            "/api/runtime/task-specs/compile",
            json={
                "instruction": "Find matching candidates, capture resumes, and prepare a recruiter summary.",
                "title": "Recruiting screening loop",
                "domain_hint": "recruiting",
            },
        )
        self.assertEqual(created_task.status_code, 201)
        task_spec_id = created_task.json()["task_spec"]["id"]
        plan_id = created_task.json()["execution_plan"]["id"]

        skill = self.client.post(
            "/api/skills",
            json={
                "skill_id": "runtime_screening_skill",
                "name": "Runtime Screening Skill",
                "status": "active",
                "platform": "recruiting",
                "strategy": {"instruction": "Capture resume and score candidate."},
                "health_check_config": {"expected_result_status": "pass", "minimum_overall_score": 0.5},
            },
        )
        self.assertEqual(skill.status_code, 201)

        updated_plan = self.client.post(
            "/api/runtime/plans/compile",
            json={
                "task_spec_id": task_spec_id,
                "name": "Recruiting screening health plan",
                "runtime_metadata": {"skill_id": "runtime_screening_skill"},
            },
        )
        self.assertEqual(updated_plan.status_code, 201)
        plan_id = updated_plan.json()["id"]

        created_trial = self.client.post(
            "/api/runtime/trial-runs",
            json={"task_spec_id": task_spec_id, "execution_plan_id": plan_id},
        )
        self.assertEqual(created_trial.status_code, 201)
        episode_id = created_trial.json()["id"]

        execute = self.client.post(
            f"/api/runtime/trial-runs/{episode_id}/execute",
            json={"source": "browser", "url": "https://example.com/candidates"},
        )
        self.assertEqual(execute.status_code, 200)
        self.assertIsNotNone(execute.json()["skill_health"])
        self.assertEqual(execute.json()["skill_health"]["health"], "healthy")

        learn_again = self.client.post(f"/api/runtime/trial-runs/{episode_id}/learn")
        self.assertEqual(learn_again.status_code, 200)
        self.assertEqual(learn_again.json()["episode"]["id"], episode_id)


if __name__ == "__main__":
    unittest.main()
