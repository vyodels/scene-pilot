from __future__ import annotations

import json
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


class _StaticProvider:
    def __init__(self, provider_name: str, response) -> None:
        self.provider_name = provider_name
        self._response = response

    def generate(self, messages, *, tools=None, task=None, max_tokens=None, temperature=None):
        return self._response


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
        self.container = self.client.app.state.container
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
        self.assertTrue(any(item["version"] for item in domain_packs.json()))

        compiler_contract = self.client.get("/api/runtime/compiler-contract")
        self.assertEqual(compiler_contract.status_code, 200)
        compiler_payload = compiler_contract.json()
        self.assertEqual(compiler_payload["strategy"], "llm_first_structured_semantic_compiler")
        self.assertIn("goal", compiler_payload["required_fields"])
        self.assertTrue(any(item["key"] == "browser" for item in compiler_payload["available_capabilities"]))

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
        self.assertIsNotNone(executed_payload["template_approval"])
        self.assertEqual(executed_payload["template_approval"]["target_type"], "template_candidate")

        confirmed_trial = self.client.post(
            f"/api/runtime/trial-runs/{episode_id}/confirm",
            json={"reviewer": "desktop-user", "reason": "Ready for production", "activate_template": True},
        )
        self.assertEqual(confirmed_trial.status_code, 200)
        confirmed_payload = confirmed_trial.json()
        self.assertEqual(confirmed_payload["episode"]["status"], "confirmed")
        self.assertIsNotNone(confirmed_payload["template"])
        self.assertEqual(confirmed_payload["template"]["status"], "active")
        self.assertEqual(confirmed_payload["template_approval"]["status"], "approved")

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

    def test_capability_driver_catalog_and_environment_assessment(self) -> None:
        capability_response = self.client.get("/api/runtime/capability-drivers?domain=web_research")
        self.assertEqual(capability_response.status_code, 200)
        capability_payload = capability_response.json()
        browser_driver = next(item for item in capability_payload if item["key"] == "browser")
        self.assertIn("web_research", browser_driver["supported_domains"])
        self.assertTrue(browser_driver["requires_supervision"])
        all_capabilities = self.client.get("/api/runtime/capability-drivers")
        self.assertEqual(all_capabilities.status_code, 200)
        self.assertTrue(any(item["key"] == "filesystem" for item in all_capabilities.json()))

        compiled_task = self.client.post(
            "/api/runtime/task-specs/compile",
            json={
                "instruction": "Open the web and find useful PDF converters, compare them, and prepare a shortlist.",
                "title": "PDF converter shortlist",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        task_spec_id = compiled_task.json()["task_spec"]["id"]
        plan_id = compiled_task.json()["execution_plan"]["id"]

        snapshot = self.client.post(
            "/api/runtime/environment-snapshots",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "source": "browser",
                "environment_key": "web:tool_listing",
                "status": "captured",
                "url": "https://example.com/tools",
                "title": "PDF Converter Tools",
                "page_type": "tool_listing",
                "capability_hints": ["browser", "search"],
                "affordances": [{"kind": "link", "label": "View details"}],
            },
        )
        self.assertEqual(snapshot.status_code, 201)
        snapshot_id = snapshot.json()["id"]

        assessment = self.client.post(
            "/api/runtime/environment-assessment",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "environment_snapshot_id": snapshot_id,
            },
        )
        self.assertEqual(assessment.status_code, 200)
        assessment_payload = assessment.json()
        self.assertEqual(assessment_payload["scene_type"], "tool_listing")
        self.assertEqual(assessment_payload["plan_fit"], "aligned")
        self.assertIn("browser", assessment_payload["recommended_capabilities"])
        self.assertIn("search", assessment_payload["recommended_capabilities"])
        self.assertEqual(assessment_payload["audit_metadata"]["site_assumption_policy"], "generic_only")
        self.assertEqual(assessment_payload["snapshot"]["id"], snapshot_id)

    def test_replan_derives_new_execution_plan_from_episode_and_compiler_payload(self) -> None:
        compiled_task = self.client.post(
            "/api/runtime/task-specs/compile",
            json={
                "instruction": "Open GitHub trends, inspect repositories, and prepare a concise digest.",
                "title": "GitHub digest trial",
                "domain_hint": "github_trends",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        task_spec_id = compiled_task.json()["task_spec"]["id"]
        plan_id = compiled_task.json()["execution_plan"]["id"]
        previous_plan = compiled_task.json()["execution_plan"]

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

        snapshots = self.client.get(f"/api/runtime/environment-snapshots?execution_episode_id={episode_id}")
        self.assertEqual(snapshots.status_code, 200)
        snapshot_id = snapshots.json()[-1]["id"]

        replanned = self.client.post(
            f"/api/runtime/plans/{plan_id}/replan",
            json={
                "requested_by": "desktop-user",
                "reason": "The trial diverged and needs a safer generic branch.",
                "execution_episode_id": episode_id,
                "environment_snapshot_id": snapshot_id,
                "compiler_payload": {
                    "compiler_notes": ["Need a safer branch before retrying."],
                    "preferred_capabilities": ["browser", "document"],
                    "environment_requirements": {"requires_network": True},
                    "checkpoints": [{"kind": "approval", "label": "Review replan"}],
                    "step_outline": [
                        {"id": "reassess", "capability": "analyze"},
                        {"id": "retry_browser", "capability": "browser"},
                        {"id": "draft_digest", "capability": "document"},
                    ],
                },
            },
        )
        self.assertEqual(replanned.status_code, 201)
        replanned_payload = replanned.json()
        self.assertEqual(replanned_payload["previous_plan"]["id"], plan_id)
        self.assertNotEqual(replanned_payload["execution_plan"]["id"], plan_id)
        self.assertEqual(replanned_payload["execution_plan"]["version"], previous_plan["version"] + 1)
        self.assertEqual(
            replanned_payload["execution_plan"]["runtime_metadata"]["replanned_from_plan_id"],
            plan_id,
        )
        self.assertEqual(
            replanned_payload["execution_plan"]["runtime_metadata"]["site_assumption_policy"],
            "generic_only",
        )
        self.assertEqual(replanned_payload["audit_metadata"]["site_assumption_policy"], "generic_only")
        self.assertEqual(replanned_payload["execution_plan"]["plan_body"]["steps"][0]["id"], "reassess")
        self.assertTrue(
            any(item["label"] == "Review replan" for item in replanned_payload["execution_plan"]["checkpoints"])
        )
        self.assertIn("Need a safer branch before retrying.", replanned_payload["compiler_notes"])

        listed_tasks = self.client.get("/api/runtime/task-specs")
        self.assertEqual(listed_tasks.status_code, 200)
        refreshed_task = next(item for item in listed_tasks.json() if item["id"] == task_spec_id)
        self.assertEqual(refreshed_task["active_plan_id"], replanned_payload["execution_plan"]["id"])

    def test_task_compile_prefers_llm_semantic_compiler_when_provider_returns_valid_json(self) -> None:
        from recruit_agent.runtime.models import LLMResponse

        self.container.providers.providers["openai_compatible"] = _StaticProvider(
            "openai_compatible",
            LLMResponse(
                content=json.dumps(
                    {
                        "title": "Daily market-moving headlines",
                        "description": "Compile a fresh digest of market-moving news.",
                        "goal": "Collect the newest stock-market headlines, compare sources, and publish a concise digest.",
                        "domain": "market_news",
                        "constraints": {"requires_source_links": True},
                        "success_criteria": {"minimum_sources": 4, "include_market_impact": True},
                        "approval_policy": {"mode": "desktop_review"},
                        "output_contract": {"kind": "news_digest", "format": "bullet_summary"},
                        "preferred_capabilities": ["search", "browser", "document", "llm"],
                        "preferred_domains": ["market_news", "general"],
                        "compiler_notes": ["Detected a source-comparison and summarization task."],
                    }
                )
            ),
        )
        self.container.providers.fallback_order = ["openai_compatible", "scripted_default"]

        compiled_task = self.client.post(
            "/api/runtime/task-specs/compile",
            json={
                "instruction": "Find today's most important stock market news and turn it into a short digest with sources.",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        payload = compiled_task.json()
        self.assertEqual(payload["domain_pack"]["key"], "market_news")
        self.assertEqual(payload["task_spec"]["compiled_payload"]["compiler"], "llm_structured")
        self.assertEqual(payload["execution_plan"]["runtime_metadata"]["compiler"], "llm_structured")
        self.assertIn("openai_compatible", "\n".join(payload["compiler_notes"]))

    def test_task_compile_falls_back_to_heuristic_when_llm_output_is_invalid(self) -> None:
        from recruit_agent.runtime.models import LLMResponse

        self.container.providers.providers["openai_compatible"] = _StaticProvider(
            "openai_compatible",
            LLMResponse(content="This is not valid JSON."),
        )
        self.container.providers.fallback_order = ["openai_compatible", "scripted_default"]

        compiled_task = self.client.post(
            "/api/runtime/task-specs/compile",
            json={
                "instruction": "Open GitHub trending and prepare a repository digest.",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        payload = compiled_task.json()
        self.assertEqual(payload["domain_pack"]["key"], "github_trends")
        self.assertEqual(payload["task_spec"]["compiled_payload"]["compiler"], "heuristic")
        self.assertIn("failed", "\n".join(payload["compiler_notes"]).lower())
        self.assertIn("fell back", "\n".join(payload["compiler_notes"]).lower())

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
        _ = next(item["id"] for item in templates.json() if item["template_key"] == "patch_review_loop")

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
        patched_plan_id = approved_payload["runtime_metadata"]["apply_result"]["execution_plan_id"]
        patched_template_id = approved_payload["runtime_metadata"]["apply_result"]["template_id"]
        self.assertEqual(approved_payload["runtime_metadata"]["apply_result"]["previous_plan_id"], plan_id)
        self.assertIsNotNone(patched_template_id)

        refreshed_approvals = self.client.get("/api/approvals")
        self.assertEqual(refreshed_approvals.status_code, 200)
        approved_approval = next(item for item in refreshed_approvals.json() if item["target_id"] == patch_payload["id"])
        self.assertEqual(approved_approval["status"], "approved")
        self.assertEqual(approved_approval["payload"]["resolution"]["status"], "applied")
        self.assertEqual(approved_approval["payload"]["resolution"]["execution_plan_id"], patched_plan_id)
        self.assertEqual(approved_approval["payload"]["resolution"]["template_id"], patched_template_id)

        plans = self.client.get(f"/api/runtime/plans?task_spec_id={task_spec_id}")
        self.assertEqual(plans.status_code, 200)
        plan_by_id = {item["id"]: item for item in plans.json()}
        self.assertIn(patched_plan_id, plan_by_id)
        self.assertEqual(plan_by_id[patched_plan_id]["compiled_from_patch_id"], patch_payload["id"])
        self.assertEqual(plan_by_id[patched_plan_id]["runtime_metadata"]["workflow_template_id"], patched_template_id)

        templates = self.client.get("/api/runtime/templates")
        self.assertEqual(templates.status_code, 200)
        template_by_id = {item["id"]: item for item in templates.json()}
        self.assertIn(patched_template_id, template_by_id)
        self.assertEqual(template_by_id[patched_template_id]["status"], "active")
        self.assertTrue(
            any(
                checkpoint["label"] == "Add or refine a supervised checkpoint before repeating this action."
                for checkpoint in template_by_id[patched_template_id]["template_body"]["checkpoints"]
            )
        )

        approved_patch_again = self.client.post(
            f"/api/runtime/workflow-patches/{patch_payload['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Reconfirm applied patch", "apply_immediately": True},
        )
        self.assertEqual(approved_patch_again.status_code, 200)
        second_payload = approved_patch_again.json()
        self.assertEqual(second_payload["runtime_metadata"]["apply_result"]["execution_plan_id"], patched_plan_id)
        self.assertEqual(second_payload["runtime_metadata"]["apply_result"]["template_id"], patched_template_id)

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
        first_template = execute.json()["template"]
        first_learning = execute.json()["learning_draft"]
        first_template_approval = execute.json()["template_approval"]
        self.assertIsNotNone(first_template)
        self.assertIsNotNone(first_learning)
        self.assertIsNotNone(first_template_approval)

        learn_again = self.client.post(f"/api/runtime/trial-runs/{episode_id}/learn")
        self.assertEqual(learn_again.status_code, 200)
        self.assertEqual(learn_again.json()["episode"]["id"], episode_id)
        self.assertEqual(learn_again.json()["template"]["id"], first_template["id"])
        self.assertEqual(learn_again.json()["template"]["version"], first_template["version"])
        self.assertEqual(learn_again.json()["learning_draft"]["id"], first_learning["id"])
        self.assertEqual(learn_again.json()["template_approval"]["id"], first_template_approval["id"])

    def test_episode_replay_returns_task_plan_snapshot_and_timeline(self) -> None:
        compiled_task = self.client.post(
            "/api/runtime/task-specs/compile",
            json={
                "instruction": "Find useful PDF converters, inspect them, and produce a shortlist.",
                "title": "Replayable PDF research",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        task_spec_id = compiled_task.json()["task_spec"]["id"]
        plan_id = compiled_task.json()["execution_plan"]["id"]

        created_trial = self.client.post(
            "/api/runtime/trial-runs",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "requested_by": "desktop-user",
                "notes": "Capture a replay timeline.",
            },
        )
        self.assertEqual(created_trial.status_code, 201)
        episode_id = created_trial.json()["id"]

        executed_trial = self.client.post(
            f"/api/runtime/trial-runs/{episode_id}/execute",
            json={
                "source": "browser",
                "url": "https://example.com/tools",
                "title": "Example Tools",
                "page_type": "tool_listing",
                "observed_entities": [{"kind": "tool_card", "name": "Converter A"}],
                "affordances": [{"kind": "open_tool", "label": "Open tool detail"}],
            },
        )
        self.assertEqual(executed_trial.status_code, 200)

        replay = self.client.get(f"/api/runtime/trial-runs/{episode_id}/replay")
        self.assertEqual(replay.status_code, 200)
        payload = replay.json()
        self.assertEqual(payload["task_spec"]["id"], task_spec_id)
        self.assertEqual(payload["execution_plan"]["id"], plan_id)
        self.assertEqual(payload["episode"]["id"], episode_id)
        self.assertEqual(payload["diagnostics"]["snapshot_count"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["action_count"], 1)
        self.assertGreaterEqual(len(payload["timeline"]), 5)
        self.assertTrue(any(item["kind"] == "snapshot" for item in payload["timeline"]))
        self.assertTrue(any(item["kind"] == "learning" for item in payload["timeline"]))
        self.assertEqual(payload["snapshots"][0]["page_type"], "tool_listing")


if __name__ == "__main__":
    unittest.main()
