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

EXECUTION_API_BASE = "/api/recruit-agent/execution"
ARCHIVED_PUBLIC_RESEARCH = "archived_public_research"
ARCHIVED_PUBLIC_BRIEFING = "archived_public_briefing"
ARCHIVED_REPOSITORY_WATCH = "archived_repository_watch"


class _StaticProvider:
    def __init__(self, provider_name: str, response) -> None:
        self.provider_name = provider_name
        self._response = response

    def generate(self, messages, *, tools=None, task=None, max_tokens=None, temperature=None):
        return self._response


class _SequentialProvider:
    def __init__(self, provider_name: str, responses) -> None:
        self.provider_name = provider_name
        self._responses = list(responses)
        self._index = 0

    def generate(self, messages, *, tools=None, task=None, max_tokens=None, temperature=None):
        if self._index >= len(self._responses):
            return self._responses[-1]
        response = self._responses[self._index]
        self._index += 1
        return response


class _FailingProvider:
    provider_name = "failing"

    def generate(self, messages, *, tools=None, task=None, max_tokens=None, temperature=None):
        raise AssertionError("Managed execution should not call the live executor for blocked preflight scenes")


class _SemanticCompileProvider:
    provider_name = "openai_compatible"

    def generate(self, messages, *, tools=None, task=None, max_tokens=None, temperature=None):
        from scene_pilot.runtime.models import LLMResponse

        instruction = str((task or {}).get("instruction") or "")
        lowered = instruction.lower()
        domain = "general"
        capabilities = ["analyze", "browser", "llm", "document"]
        output_contract = {"kind": "summary", "format": "markdown"}
        success_criteria = {"supervised_trial_ready": True}
        environment_requirements = {"requires_browser": "browser" in capabilities}
        checkpoints = [{"label": "Validate runtime scene before proceeding", "kind": "scene_assessment"}]
        step_outline = [
            {"id": "understand_task", "capability": "analyze"},
            {"id": "assess_runtime_scene", "capability": "browser"},
            {"id": "synthesize_result", "capability": "document"},
        ]
        notes = ["Semantic compile provider generated a structured task draft for tests."]

        if "pdf" in lowered:
            domain = ARCHIVED_PUBLIC_RESEARCH
            capabilities = ["search", "browser", "http", "llm", "document"]
            output_contract = {"kind": "shortlist", "format": "markdown", "minimum_candidates": 3}
            success_criteria = {"minimum_candidates": 3, "requires_comparison": True}
        elif "market" in lowered or "stock" in lowered or "digest" in lowered:
            domain = ARCHIVED_PUBLIC_BRIEFING
            capabilities = ["search", "http", "browser", "llm", "document"]
            output_contract = {"kind": "digest", "format": "markdown", "include_sources": True}
            success_criteria = {"minimum_sources": 3, "include_market_impact": True}
        elif "github" in lowered:
            domain = ARCHIVED_REPOSITORY_WATCH
            capabilities = ["http", "browser", "llm", "document"]
            output_contract = {"kind": "digest", "format": "markdown", "include_repo_links": True}
            success_criteria = {"minimum_candidates": 3, "requires_comparison": True}
        elif "candidate" in lowered or "resume" in lowered or "候选人" in instruction or "简历" in instruction:
            domain = "recruiting"
            capabilities = ["browser", "search", "document", "llm", "api"]
            output_contract = {"kind": "screening_packet", "format": "markdown", "include_score": True}
            success_criteria = {"requires_candidate_evidence": True, "requires_score": True}
            step_outline = [
                {"id": "confirm_requirements", "action": "确认任务输入"},
                {"id": "assess_recruiting_scene", "action": "评估招聘场景"},
                {"id": "search_candidates", "action": "搜索并选择候选人"},
                {"id": "inspect_candidate_resume", "action": "查看资料与简历并提取证据"},
                {"id": "score_candidate", "action": "完成初筛评分"},
                {"id": "prepare_screening_summary", "action": "输出候选人结论与下一步建议"},
            ]

        environment_requirements = {"requires_browser": "browser" in capabilities}
        return LLMResponse(
            result_data={
                "title": instruction[:48] or "Compiled task",
                "description": f"Structured compile for: {instruction}",
                "goal": instruction or "Complete the requested automation task.",
                "domain": domain,
                "inputs": {},
                "constraints": {"requires_supervised_trial": True},
                "success_criteria": success_criteria,
                "approval_policy": {"approval_actions": ["write", "outbound", "command"]},
                "output_contract": output_contract,
                "preferred_capabilities": capabilities,
                "preferred_domains": [domain, "general"],
                "environment_requirements": environment_requirements,
                "checkpoints": checkpoints,
                "step_outline": step_outline,
                "compiler_notes": notes,
            }
        )


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed")
class ApiRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        from scene_pilot.core.settings import load_settings
        from scene_pilot.server import create_app

        self.tempdir = tempfile.TemporaryDirectory()
        os.environ["RECRUIT_AGENT_DATA_DIR"] = self.tempdir.name
        load_settings.cache_clear()
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.container = self.client.app.state.container
        self.container.providers.providers["openai_compatible"] = _SemanticCompileProvider()
        self.container.providers.fallback_order = ["openai_compatible", "scripted_default"]
        self._load_settings = load_settings

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.tempdir.cleanup()
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        self._load_settings.cache_clear()

    def test_natural_language_compile_trial_execution_and_snapshot_flow(self) -> None:
        domain_packs = self.client.get(f"{EXECUTION_API_BASE}/profiles")
        self.assertEqual(domain_packs.status_code, 200)
        self.assertTrue(any(item["key"] == ARCHIVED_PUBLIC_RESEARCH for item in domain_packs.json()))
        self.assertTrue(any(item["version"] for item in domain_packs.json()))

        compiler_contract = self.client.get(f"{EXECUTION_API_BASE}/compiler-contract")
        self.assertEqual(compiler_contract.status_code, 200)
        compiler_payload = compiler_contract.json()
        self.assertEqual(compiler_payload["contract_version"], "runtime-task-compiler-v4")
        self.assertEqual(compiler_payload["strategy"], "llm_first_structured_semantic_compiler")
        self.assertIn("goal", compiler_payload["required_fields"])
        self.assertGreaterEqual(len(compiler_payload["quality_gates"]), 1)
        self.assertIn("max_repair_passes", compiler_payload["repair_policy"])
        self.assertTrue(any(item["key"] == "browser" for item in compiler_payload["available_capabilities"]))

        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
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
        self.assertEqual(compile_payload["domain_pack"]["key"], ARCHIVED_PUBLIC_RESEARCH)
        self.assertIn("quality_gates", compile_payload["domain_pack"])
        self.assertIn("template_count", compile_payload["domain_pack"])
        task_spec_id = compile_payload["task_spec"]["id"]
        plan_id = compile_payload["execution_plan"]["id"]
        self.assertEqual(compile_payload["execution_plan"]["plan_body"]["steps"][1]["id"], "assess_runtime_scene")
        self.assertIn("compiler_quality", compile_payload["task_spec"]["compiled_payload"])
        self.assertTrue(
            any(
                checkpoint["label"] == "Validate runtime scene before proceeding"
                for checkpoint in compile_payload["execution_plan"]["checkpoints"]
            )
        )

        listed_tasks = self.client.get(f"{EXECUTION_API_BASE}/playbooks")
        self.assertEqual(listed_tasks.status_code, 200)
        created_task = next(item for item in listed_tasks.json() if item["id"] == task_spec_id)
        self.assertEqual(created_task["status"], "trial_ready")
        self.assertEqual(created_task["active_plan_id"], plan_id)

        created_trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs",
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
            f"{EXECUTION_API_BASE}/runs/{episode_id}/execute",
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
        self.assertIn("governance", executed_payload["template"]["activation_strategy"])
        self.assertIsNotNone(executed_payload["learning_draft"])
        self.assertIsNotNone(executed_payload["approval"])
        self.assertEqual(executed_payload["approval"]["target_type"], "skill_draft")
        self.assertIn("version_governance", executed_payload["approval"]["payload"]["skill_draft"])
        self.assertIsNotNone(executed_payload["template_approval"])
        self.assertEqual(executed_payload["template_approval"]["target_type"], "template_candidate")
        self.assertIn("governance", executed_payload["template_approval"]["payload"])

        confirmed_trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs/{episode_id}/confirm",
            json={"reviewer": "desktop-user", "reason": "Ready for production", "activate_template": True},
        )
        self.assertEqual(confirmed_trial.status_code, 200)
        confirmed_payload = confirmed_trial.json()
        self.assertEqual(confirmed_payload["episode"]["status"], "confirmed")
        self.assertIsNotNone(confirmed_payload["template"])
        self.assertEqual(confirmed_payload["template"]["status"], "active")
        self.assertEqual(confirmed_payload["template_approval"]["status"], "approved")

        refreshed_task = self.client.get(f"{EXECUTION_API_BASE}/playbooks")
        self.assertEqual(refreshed_task.status_code, 200)
        self.assertEqual(
            next(item for item in refreshed_task.json() if item["id"] == task_spec_id)["status"],
            "production_ready",
        )

    def test_generic_approval_endpoint_confirms_template_candidates(self) -> None:
        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Open the web and compare PDF tools in a supervised trial.",
                "title": "Approve template via approval queue",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        task_spec_id = compiled_task.json()["task_spec"]["id"]
        plan_id = compiled_task.json()["execution_plan"]["id"]

        created_trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "requested_by": "desktop-user",
            },
        )
        self.assertEqual(created_trial.status_code, 201)
        episode_id = created_trial.json()["id"]

        executed_trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs/{episode_id}/execute",
            json={
                "source": "browser",
                "url": "https://example.com/tools",
                "title": "Example Tools",
                "page_type": "tool_listing",
            },
        )
        self.assertEqual(executed_trial.status_code, 200)
        executed_payload = executed_trial.json()
        template_approval = executed_payload["template_approval"]
        template_id = executed_payload["template"]["id"]

        approved = self.client.post(
            f"/api/approvals/{template_approval['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Ready for activation"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(approved.json()["payload"]["resolution"]["status"], "approved")

        refreshed_episode = self.client.get(f"{EXECUTION_API_BASE}/runs/{episode_id}")
        self.assertEqual(refreshed_episode.status_code, 200)
        self.assertEqual(refreshed_episode.json()["status"], "confirmed")

        refreshed_templates = self.client.get(f"{EXECUTION_API_BASE}/playbook-versions")
        self.assertEqual(refreshed_templates.status_code, 200)
        refreshed_template = next(item for item in refreshed_templates.json() if item["id"] == template_id)
        self.assertEqual(refreshed_template["status"], "active")

        refreshed_workflows = self.client.get(f"{EXECUTION_API_BASE}/playbooks")
        self.assertEqual(refreshed_workflows.status_code, 200)
        self.assertEqual(
            next(item for item in refreshed_workflows.json() if item["id"] == task_spec_id)["status"],
            "production_ready",
        )

    def test_generic_approval_endpoint_applies_workflow_patches(self) -> None:
        created_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Open GitHub trends, inspect repositories, and propose a safer workflow when divergence happens.",
                "title": "Queue patch approval through the approval inbox",
                "domain_hint": ARCHIVED_REPOSITORY_WATCH,
            },
        )
        self.assertEqual(created_task.status_code, 201)
        task_spec_id = created_task.json()["task_spec"]["id"]
        plan_id = created_task.json()["execution_plan"]["id"]

        created_trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs/trial",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "requested_by": "desktop-user",
            },
        )
        self.assertEqual(created_trial.status_code, 201)
        episode_id = created_trial.json()["id"]

        executed = self.client.post(
            f"{EXECUTION_API_BASE}/runs/{episode_id}/execute",
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

        approvals = self.client.get("/api/approvals?pending_only=true")
        self.assertEqual(approvals.status_code, 200)
        linked_approval = next(
            item
            for item in approvals.json()
            if item["target_type"] == "workflow_patch" and item["target_id"] == patch_payload["id"]
        )

        approved = self.client.post(
            f"/api/approvals/{linked_approval['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Apply the patch"},
        )
        self.assertEqual(approved.status_code, 200)
        approved_payload = approved.json()
        self.assertEqual(approved_payload["status"], "approved")
        self.assertEqual(approved_payload["payload"]["resolution"]["status"], "applied")

        patches = self.client.get(f"{EXECUTION_API_BASE}/adjustments")
        self.assertEqual(patches.status_code, 200)
        patched = next(item for item in patches.json() if item["id"] == patch_payload["id"])
        self.assertEqual(patched["status"], "applied")
        patched_plan_id = patched["runtime_metadata"]["apply_result"]["execution_plan_id"]

        plans = self.client.get(f"{EXECUTION_API_BASE}/plans?task_spec_id={task_spec_id}")
        self.assertEqual(plans.status_code, 200)
        patched_plan = next(item for item in plans.json() if item["id"] == patched_plan_id)
        self.assertEqual(patched_plan["compiled_from_patch_id"], patch_payload["id"])

        listed_snapshots = self.client.get(f"{EXECUTION_API_BASE}/snapshots?execution_episode_id={episode_id}")
        self.assertEqual(listed_snapshots.status_code, 200)
        self.assertEqual(len(listed_snapshots.json()), 1)
        self.assertEqual(listed_snapshots.json()[0]["page_type"], "repository_listing")
        self.assertEqual(self.client.get(f"{EXECUTION_API_BASE}/playbook-versions").status_code, 200)
        self.assertEqual(self.client.get(f"{EXECUTION_API_BASE}/adjustments").status_code, 200)

    def test_recruiting_compile_infers_actionable_step_capabilities(self) -> None:
        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "打开招聘网站，按照要求找到候选人，查看候选人资料和简历，完成初筛评分，并输出候选人结论和下一步建议。",
                "title": "Recruiting supervised trial",
                "domain_hint": "recruiting",
                "constraints": {
                    "requires_human_supervision": True,
                    "no_outbound_messaging_without_approval": True,
                    "no_downstream_write_without_approval": True,
                },
                "preferred_capabilities": ["browser", "search", "document", "llm"],
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        plan_steps = compiled_task.json()["execution_plan"]["plan_body"]["steps"]
        self.assertEqual(plan_steps[0]["capability"], "analyze")
        capability_sequence = [step["capability"] for step in plan_steps]
        self.assertIn("browser", capability_sequence)
        self.assertIn("search", capability_sequence)
        self.assertTrue(any(item in capability_sequence for item in ("llm", "document")))

    def test_capability_driver_catalog_and_environment_assessment(self) -> None:
        capability_response = self.client.get(f"{EXECUTION_API_BASE}/capabilities?domain={ARCHIVED_PUBLIC_RESEARCH}")
        self.assertEqual(capability_response.status_code, 200)
        capability_payload = capability_response.json()
        browser_driver = next(item for item in capability_payload if item["key"] == "browser")
        self.assertIn(ARCHIVED_PUBLIC_RESEARCH, browser_driver["supported_domains"])
        self.assertTrue(browser_driver["requires_supervision"])
        self.assertIn("scene_profile", browser_driver["signal_labels"])
        all_capabilities = self.client.get(f"{EXECUTION_API_BASE}/capabilities")
        self.assertEqual(all_capabilities.status_code, 200)
        self.assertTrue(any(item["key"] == "filesystem" for item in all_capabilities.json()))

        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Open the web and find useful PDF converters, compare them, and prepare a shortlist.",
                "title": "PDF converter shortlist",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        task_spec_id = compiled_task.json()["task_spec"]["id"]
        plan_id = compiled_task.json()["execution_plan"]["id"]

        snapshot = self.client.post(
            f"{EXECUTION_API_BASE}/snapshots",
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
                "observed_entities": [
                    {"kind": "tool_card", "label": "Converter A", "confidence": 0.94, "interactive": True},
                    {"kind": "tool_card", "label": "Converter B", "confidence": 0.91, "interactive": True},
                ],
                "affordances": [{"kind": "link", "label": "View details"}],
            },
        )
        self.assertEqual(snapshot.status_code, 201)
        snapshot_id = snapshot.json()["id"]

        assessment = self.client.post(
            f"{EXECUTION_API_BASE}/environment-assessments",
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
        self.assertEqual(assessment_payload["scene_profile"]["interaction_mode"], "navigate")
        self.assertIn("listing_surface", assessment_payload["scene_profile"]["signals"])
        self.assertEqual(assessment_payload["planner_guidance"]["posture"], "verify")
        self.assertTrue(assessment_payload["planner_guidance"]["requires_scene_assessment"])
        self.assertEqual(assessment_payload["observed_entities"][0]["kind"], "tool_card")
        self.assertEqual(assessment_payload["affordances"][0]["action"], "navigate")
        self.assertEqual(assessment_payload["audit_metadata"]["site_assumption_policy"], "generic_only")
        self.assertEqual(assessment_payload["snapshot"]["id"], snapshot_id)

        listed_assessments = self.client.get(f"{EXECUTION_API_BASE}/environment-assessments?execution_plan_id={plan_id}")
        self.assertEqual(listed_assessments.status_code, 200)
        self.assertGreaterEqual(len(listed_assessments.json()), 1)
        self.assertEqual(listed_assessments.json()[0]["execution_plan"]["id"], plan_id)

    def test_replan_derives_new_execution_plan_from_episode_and_compiler_payload(self) -> None:
        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Open GitHub trends, inspect repositories, and prepare a concise digest.",
                "title": "GitHub digest trial",
                "domain_hint": ARCHIVED_REPOSITORY_WATCH,
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        task_spec_id = compiled_task.json()["task_spec"]["id"]
        plan_id = compiled_task.json()["execution_plan"]["id"]
        previous_plan = compiled_task.json()["execution_plan"]

        created_trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs/trial",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "requested_by": "desktop-user",
            },
        )
        self.assertEqual(created_trial.status_code, 201)
        episode_id = created_trial.json()["id"]

        executed = self.client.post(
            f"{EXECUTION_API_BASE}/runs/{episode_id}/execute",
            json={
                "source": "browser",
                "url": "https://github.com/trending",
                "title": "GitHub Trending",
                "page_type": "repository_listing",
                "observed_entities": [
                    {"kind": "repository_card", "label": "runtime/project-alpha"},
                    {"kind": "repository_card", "label": "runtime/project-beta"},
                ],
                "affordances": [{"kind": "click", "label": "Open repository"}],
                "simulate_divergence": True,
            },
        )
        self.assertEqual(executed.status_code, 200)

        snapshots = self.client.get(f"{EXECUTION_API_BASE}/snapshots?execution_episode_id={episode_id}")
        self.assertEqual(snapshots.status_code, 200)
        snapshot_id = snapshots.json()[-1]["id"]

        replanned = self.client.post(
            f"{EXECUTION_API_BASE}/plans/{plan_id}/replan",
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
        self.assertEqual(replanned_payload["execution_plan"]["plan_body"]["steps"][0]["id"], "assess_runtime_scene")
        self.assertEqual(
            replanned_payload["execution_plan"]["runtime_metadata"]["planner_guidance"]["posture"],
            "recover",
        )
        self.assertTrue(
            any(item["label"] == "Review replan" for item in replanned_payload["execution_plan"]["checkpoints"])
        )
        self.assertIn("Need a safer branch before retrying.", replanned_payload["compiler_notes"])

        listed_tasks = self.client.get(f"{EXECUTION_API_BASE}/playbooks")
        self.assertEqual(listed_tasks.status_code, 200)
        refreshed_task = next(item for item in listed_tasks.json() if item["id"] == task_spec_id)
        self.assertEqual(refreshed_task["active_plan_id"], replanned_payload["execution_plan"]["id"])

    def test_replan_adds_auth_recovery_steps_for_browser_gate(self) -> None:
        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Open the web app, inspect the current page, and continue only when the scene is ready.",
                "title": "Auth gate recovery",
                "preferred_capabilities": ["browser", "document"],
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        plan_id = compiled_task.json()["execution_plan"]["id"]
        task_spec_id = compiled_task.json()["task_spec"]["id"]

        snapshot = self.client.post(
            f"{EXECUTION_API_BASE}/snapshots",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "source": "browser",
                "environment_key": "general:auth_gate",
                "status": "captured",
                "url": "https://example.com/login",
                "title": "Sign in to continue",
                "page_type": "auth_gate",
                "observed_entities": [{"kind": "form", "label": "Login form"}],
                "affordances": [{"kind": "submit", "label": "Sign in", "requires_confirmation": True}],
            },
        )
        self.assertEqual(snapshot.status_code, 201)
        snapshot_id = snapshot.json()["id"]

        replanned = self.client.post(
            f"{EXECUTION_API_BASE}/plans/{plan_id}/replan",
            json={
                "requested_by": "desktop-user",
                "reason": "The current scene is an auth gate and needs recovery handling.",
                "environment_snapshot_id": snapshot_id,
            },
        )
        self.assertEqual(replanned.status_code, 201)
        payload = replanned.json()
        self.assertIn("authentication_required", payload["assessment"]["blockers"])
        self.assertTrue(payload["assessment"]["planner_guidance"]["requires_human_review"])
        self.assertTrue(
            any(step["id"] == "resolve_access_gate" for step in payload["execution_plan"]["plan_body"]["steps"])
        )
        self.assertEqual(
            payload["execution_plan"]["runtime_metadata"]["planner_guidance"]["posture"],
            "recover",
        )

    def test_task_compile_prefers_llm_semantic_compiler_when_provider_returns_valid_json(self) -> None:
        from scene_pilot.runtime.models import LLMResponse

        self.container.providers.providers["openai_compatible"] = _StaticProvider(
            "openai_compatible",
            LLMResponse(
                content=json.dumps(
                    {
                        "title": "Daily market-moving headlines",
                        "description": "Compile a fresh digest of market-moving news.",
                        "goal": "Collect the newest stock-market headlines, compare sources, and publish a concise digest.",
                        "domain": ARCHIVED_PUBLIC_BRIEFING,
                        "constraints": {"requires_source_links": True},
                        "success_criteria": {"minimum_sources": 4, "include_market_impact": True},
                        "approval_policy": {"mode": "desktop_review"},
                        "output_contract": {"kind": "news_digest", "format": "bullet_summary"},
                        "preferred_capabilities": ["search", "browser", "document", "llm"],
                        "preferred_domains": [ARCHIVED_PUBLIC_BRIEFING, "general"],
                        "compiler_notes": ["Detected a source-comparison and summarization task."],
                    }
                )
            ),
        )
        self.container.providers.fallback_order = ["openai_compatible", "scripted_default"]

        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Find today's most important stock market news and turn it into a short digest with sources.",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        payload = compiled_task.json()
        self.assertEqual(payload["domain_pack"]["key"], ARCHIVED_PUBLIC_BRIEFING)
        self.assertEqual(payload["task_spec"]["compiled_payload"]["compiler"], "llm_structured")
        self.assertIn("compiler_quality", payload["task_spec"]["compiled_payload"])
        self.assertFalse(payload["task_spec"]["compiled_payload"]["compiler_quality"]["fallback_used"])
        self.assertEqual(payload["execution_plan"]["runtime_metadata"]["compiler"], "llm_structured")
        self.assertIn("openai_compatible", "\n".join(payload["compiler_notes"]))

    def test_task_compile_fails_when_llm_output_is_invalid(self) -> None:
        from scene_pilot.runtime.models import LLMResponse

        self.container.providers.providers["openai_compatible"] = _StaticProvider(
            "openai_compatible",
            LLMResponse(content="This is not valid JSON."),
        )
        self.container.providers.fallback_order = ["openai_compatible", "scripted_default"]

        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Open GitHub trending and prepare a repository digest.",
            },
        )
        self.assertEqual(compiled_task.status_code, 400)
        self.assertIn("llm", compiled_task.json()["detail"].lower())
        self.assertIn("任务编译失败", compiled_task.json()["detail"])

    def test_task_compile_repairs_schema_valid_but_quality_incomplete_llm_output(self) -> None:
        from scene_pilot.runtime.models import LLMResponse

        self.container.providers.providers["openai_compatible"] = _SequentialProvider(
            "openai_compatible",
            [
                LLMResponse(
                    content=json.dumps(
                        {
                            "title": "Daily market-moving headlines",
                            "description": "Compile a fresh digest of market-moving news.",
                            "goal": "Digest market news.",
                            "domain": ARCHIVED_PUBLIC_BRIEFING,
                            "constraints": {"requires_source_links": True},
                            "success_criteria": {},
                            "approval_policy": {"mode": "desktop_review"},
                            "output_contract": {"kind": "news_digest", "format": "bullet_summary"},
                            "preferred_capabilities": ["search", "browser", "document"],
                            "preferred_domains": [ARCHIVED_PUBLIC_BRIEFING],
                            "compiler_notes": ["Initial compile omitted actionable checkpoints."],
                        }
                    )
                ),
                LLMResponse(
                    content=json.dumps(
                        {
                            "title": "Daily market-moving headlines",
                            "description": "Compile a fresh digest of market-moving news.",
                            "goal": "Collect the newest market-moving headlines, compare them, and prepare a source-linked digest.",
                            "domain": ARCHIVED_PUBLIC_BRIEFING,
                            "constraints": {"requires_source_links": True},
                            "success_criteria": {"minimum_sources": 4, "include_market_impact": True},
                            "approval_policy": {"mode": "desktop_review"},
                            "output_contract": {"kind": "news_digest", "format": "bullet_summary"},
                            "preferred_capabilities": ["search", "browser", "document", "llm"],
                            "preferred_domains": [ARCHIVED_PUBLIC_BRIEFING, "general"],
                            "environment_requirements": {"requires_network": True, "scene_assessment_required": True},
                            "checkpoints": [{"kind": "quality_gate", "label": "Verify source links before finalizing output"}],
                            "step_outline": [
                                {"id": "collect_headlines", "capability": "search"},
                                {"id": "inspect_sources", "capability": "browser"},
                                {"id": "draft_digest", "capability": "document"},
                            ],
                            "compiler_notes": ["Repair pass restored explicit checkpoints and step outline."],
                        }
                    )
                ),
            ],
        )
        self.container.providers.fallback_order = ["openai_compatible", "scripted_default"]

        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Find today's most important stock market news and turn it into a short digest with sources.",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        payload = compiled_task.json()
        quality = payload["task_spec"]["compiled_payload"]["compiler_quality"]
        self.assertEqual(payload["task_spec"]["compiled_payload"]["compiler"], "llm_structured")
        self.assertEqual(quality["repair_count"], 1)
        self.assertFalse(quality["fallback_used"])
        self.assertIn("Verify source links before finalizing output", json.dumps(payload["task_spec"]["compiled_payload"]))

    def test_task_compile_normalizes_string_step_outline_and_uses_effective_approval_policy(self) -> None:
        from scene_pilot.runtime.models import LLMResponse

        self.container.providers.providers["openai_compatible"] = _StaticProvider(
            "openai_compatible",
            LLMResponse(
                result_data={
                    "title": "Recruiting screening flow",
                    "description": "Find candidates, capture resumes, and prepare approved handoff output.",
                    "goal": "Search for candidates, collect resume evidence, score them, and upload approved results.",
                    "domain": "recruiting",
                    "constraints": {"requires_supervised_trial": True},
                    "success_criteria": {
                        "requires_candidate_evidence": True,
                        "requires_score": True,
                        "requires_downstream_write_review": True,
                    },
                    "approval_policy": {},
                    "output_contract": {"kind": "candidate_bundle", "fields": ["resume", "score", "notes"]},
                    "preferred_capabilities": ["browser", "search", "document", "llm", "api"],
                    "preferred_domains": ["recruiting", "general"],
                    "environment_requirements": {"requires_browser": True},
                    "checkpoints": ["Validate the recruiting scene before searching."],
                    "step_outline": [
                        "Confirm screening requirements and candidate criteria.",
                        "Inspect recruiting pages and gather resume evidence.",
                        "Upload approved results to the downstream system.",
                    ],
                    "compiler_notes": ["The provider returned shorthand step descriptions."],
                }
            ),
        )
        self.container.providers.fallback_order = ["openai_compatible", "scripted_default"]

        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Open the recruiting site, find matching candidates, score them, and upload the approved results.",
                "domain_hint": "recruiting",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        payload = compiled_task.json()
        step_outline = payload["task_spec"]["compiled_payload"]["step_outline"]
        self.assertEqual(step_outline[0]["id"], "step_1")
        self.assertIn("Confirm screening requirements", step_outline[0]["action"])
        checkpoints = payload["task_spec"]["compiled_payload"]["checkpoints"]
        self.assertEqual(checkpoints[0]["kind"], "checkpoint")
        self.assertIn("Validate the recruiting scene", checkpoints[0]["label"])
        approval_actions = payload["task_spec"]["approval_policy"]["approval_actions"]
        self.assertIn("write_to_downstream_system", approval_actions)

    def test_templates_and_workflow_patch_review_scaffold(self) -> None:
        created_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Open GitHub trends, inspect the repositories, and propose a safer workflow when divergence happens.",
                "title": "GitHub trends mutation candidate",
                "domain_hint": ARCHIVED_REPOSITORY_WATCH,
            },
        )
        self.assertEqual(created_task.status_code, 201)
        task_spec_id = created_task.json()["task_spec"]["id"]

        templates = self.client.get(f"{EXECUTION_API_BASE}/playbook-versions")
        self.assertEqual(templates.status_code, 200)
        self.assertGreaterEqual(len(templates.json()), 1)
        plan_id = created_task.json()["execution_plan"]["id"]
        _ = next(item["id"] for item in templates.json() if item["template_key"] == "patch_review_loop")

        created_trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs/trial",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "requested_by": "desktop-user",
            },
        )
        self.assertEqual(created_trial.status_code, 201)
        episode_id = created_trial.json()["id"]

        executed = self.client.post(
            f"{EXECUTION_API_BASE}/runs/{episode_id}/execute",
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
            f"{EXECUTION_API_BASE}/adjustments/{patch_payload['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Safe for trial use", "apply_immediately": True},
        )
        self.assertEqual(approved_patch.status_code, 200)
        approved_payload = approved_patch.json()
        self.assertEqual(approved_payload["status"], "applied")
        self.assertEqual(approved_payload["reviewed_by"], "desktop-user")
        self.assertIsNotNone(approved_payload["applied_at"])
        patched_plan_id = approved_payload["runtime_metadata"]["apply_result"]["execution_plan_id"]
        patched_template_id = approved_payload["runtime_metadata"]["apply_result"]["template_id"]
        self.assertEqual(
            approved_payload["runtime_metadata"]["apply_result"]["previous_plan_id"],
            patch_payload["execution_plan_id"],
        )
        self.assertNotEqual(
            approved_payload["runtime_metadata"]["apply_result"]["previous_plan_id"],
            patched_plan_id,
        )
        self.assertIsNotNone(patched_template_id)

        refreshed_approvals = self.client.get("/api/approvals")
        self.assertEqual(refreshed_approvals.status_code, 200)
        approved_approval = next(item for item in refreshed_approvals.json() if item["target_id"] == patch_payload["id"])
        self.assertEqual(approved_approval["status"], "approved")
        self.assertEqual(approved_approval["payload"]["resolution"]["status"], "applied")
        self.assertEqual(approved_approval["payload"]["resolution"]["execution_plan_id"], patched_plan_id)
        self.assertEqual(approved_approval["payload"]["resolution"]["template_id"], patched_template_id)

        plans = self.client.get(f"{EXECUTION_API_BASE}/plans?task_spec_id={task_spec_id}")
        self.assertEqual(plans.status_code, 200)
        plan_by_id = {item["id"]: item for item in plans.json()}
        self.assertIn(patched_plan_id, plan_by_id)
        self.assertEqual(plan_by_id[patched_plan_id]["compiled_from_patch_id"], patch_payload["id"])
        self.assertEqual(plan_by_id[patched_plan_id]["runtime_metadata"]["workflow_template_id"], patched_template_id)

        templates = self.client.get(f"{EXECUTION_API_BASE}/playbook-versions")
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
            f"{EXECUTION_API_BASE}/adjustments/{patch_payload['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Reconfirm applied patch", "apply_immediately": True},
        )
        self.assertEqual(approved_patch_again.status_code, 200)
        second_payload = approved_patch_again.json()
        self.assertEqual(second_payload["runtime_metadata"]["apply_result"]["execution_plan_id"], patched_plan_id)
        self.assertEqual(second_payload["runtime_metadata"]["apply_result"]["template_id"], patched_template_id)

    def test_learning_endpoint_is_repeatable_and_returns_skill_health_when_plan_has_skill_id(self) -> None:
        created_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
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
            f"{EXECUTION_API_BASE}/plans",
            json={
                "task_spec_id": task_spec_id,
                "name": "Recruiting screening health plan",
                "runtime_metadata": {"skill_id": "runtime_screening_skill"},
            },
        )
        self.assertEqual(updated_plan.status_code, 201)
        plan_id = updated_plan.json()["id"]

        created_trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs/trial",
            json={"task_spec_id": task_spec_id, "execution_plan_id": plan_id},
        )
        self.assertEqual(created_trial.status_code, 201)
        episode_id = created_trial.json()["id"]

        execute = self.client.post(
            f"{EXECUTION_API_BASE}/runs/{episode_id}/execute",
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

        learn_again = self.client.post(f"{EXECUTION_API_BASE}/runs/{episode_id}/learn")
        self.assertEqual(learn_again.status_code, 200)
        self.assertEqual(learn_again.json()["episode"]["id"], episode_id)
        self.assertEqual(learn_again.json()["template"]["id"], first_template["id"])
        self.assertEqual(learn_again.json()["template"]["version"], first_template["version"])
        self.assertEqual(learn_again.json()["learning_draft"]["id"], first_learning["id"])
        self.assertEqual(learn_again.json()["template_approval"]["id"], first_template_approval["id"])

    def test_episode_replay_returns_task_plan_snapshot_and_timeline(self) -> None:
        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Find useful PDF converters, inspect them, and produce a shortlist.",
                "title": "Replayable PDF research",
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        task_spec_id = compiled_task.json()["task_spec"]["id"]
        plan_id = compiled_task.json()["execution_plan"]["id"]

        created_trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs/trial",
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
            f"{EXECUTION_API_BASE}/runs/{episode_id}/execute",
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

        replay = self.client.get(f"{EXECUTION_API_BASE}/runs/{episode_id}/replay")
        self.assertEqual(replay.status_code, 200)
        payload = replay.json()
        self.assertEqual(payload["task_spec"]["id"], task_spec_id)
        active_plan_id = payload["execution_plan"]["id"]
        self.assertEqual(active_plan_id, payload["episode"]["execution_plan_id"])
        preflight_plan_id = payload["episode"]["runtime_metadata"].get("preflight_replanned_from_plan_id")
        if preflight_plan_id is not None:
            self.assertEqual(preflight_plan_id, plan_id)
        else:
            self.assertEqual(active_plan_id, plan_id)
        self.assertEqual(payload["episode"]["id"], episode_id)
        self.assertEqual(payload["diagnostics"]["snapshot_count"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["action_count"], 0)
        self.assertGreaterEqual(len(payload["timeline"]), 5)
        self.assertTrue(any(item["kind"] == "snapshot" for item in payload["timeline"]))
        self.assertTrue(any(item["kind"] == "learning" for item in payload["timeline"]))
        self.assertEqual(payload["snapshots"][0]["page_type"], "tool_listing")

    def test_launch_managed_runtime_execution_through_queue_and_finalize_learning(self) -> None:
        from scene_pilot.runtime.models import LLMResponse, ToolCall

        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Open the web, inspect the tool listing, and prepare a shortlist.",
                "title": "Managed runtime execution",
                "preferred_capabilities": ["browser", "document"],
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        task_spec_id = compiled_task.json()["task_spec"]["id"]
        plan_id = compiled_task.json()["execution_plan"]["id"]

        self.container.providers.providers["openai_compatible"] = _SequentialProvider(
            "openai_compatible",
            [
                LLMResponse(
                    content="inspect the scene and mark the first step complete",
                    tool_calls=[
                        ToolCall(
                            id="obs-1",
                            name="record_observation",
                            arguments={
                                "step_id": "assess_runtime_scene",
                                "capability": "browser",
                                "summary": "The runtime scene is aligned with the current plan.",
                                "signals": ["tool_listing", "scene_aligned"],
                                "scene_update": {
                                    "source": "browser",
                                    "url": "https://example.com/tools",
                                    "title": "Example Tools",
                                    "page_type": "tool_listing",
                                    "observed_entities": [{"kind": "tool_card", "label": "Converter A"}],
                                    "affordances": [{"kind": "link", "label": "Open detail"}],
                                },
                            },
                        ),
                        ToolCall(
                            id="progress-1",
                            name="advance_plan_step",
                            arguments={
                                "step_id": "assess_runtime_scene",
                                "status": "completed",
                                "capability": "browser",
                                "summary": "The live scene has been assessed.",
                            },
                        ),
                    ],
                ),
                LLMResponse(
                    content="submit the structured runtime result",
                    tool_calls=[
                        ToolCall(
                            id="submit-1",
                            name="submit_result",
                            arguments={
                                "status": "pass",
                                "data": {
                                    "summary": "Prepared a shortlist-ready runtime output.",
                                    "items_found": 1,
                                },
                            },
                        )
                    ],
                ),
            ],
        )
        self.container.providers.fallback_order = ["openai_compatible", "scripted_default"]

        launch = self.client.post(
            f"{EXECUTION_API_BASE}/plans/{plan_id}/launch",
            json={
                "task_spec_id": task_spec_id,
                "requested_by": "desktop-user",
                "mode": "production",
                "payload": {
                    "environment_snapshot": {
                        "source": "browser",
                        "url": "https://example.com/tools",
                        "title": "Example Tools",
                        "page_type": "tool_listing",
                        "observed_entities": [{"kind": "tool_card", "label": "Converter A"}],
                        "affordances": [{"kind": "link", "label": "Open detail"}],
                    }
                },
            },
        )
        self.assertEqual(launch.status_code, 201)
        launch_payload = launch.json()
        episode_id = launch_payload["execution_episode"]["id"]
        self.assertEqual(launch_payload["task_type"], "scale_execution")
        self.assertEqual(launch_payload["execution_plan_id"], plan_id)
        self.assertEqual(launch_payload["execution_episode"]["status"], "pending")

        run_once = self.client.post("/api/agent/run-once")
        self.assertEqual(run_once.status_code, 200)
        self.assertTrue(run_once.json()["processed"])
        self.assertEqual(run_once.json()["status"], "completed")

        refreshed_episode = self.client.get(f"{EXECUTION_API_BASE}/runs/{episode_id}")
        self.assertEqual(refreshed_episode.status_code, 200)
        self.assertEqual(refreshed_episode.json()["status"], "completed")
        self.assertGreaterEqual(refreshed_episode.json()["metrics"]["completed_step_count"], 1)

        replay = self.client.get(f"{EXECUTION_API_BASE}/runs/{episode_id}/replay")
        self.assertEqual(replay.status_code, 200)
        replay_payload = replay.json()
        self.assertEqual(replay_payload["episode"]["id"], episode_id)
        self.assertEqual(replay_payload["diagnostics"]["status"], "completed")
        self.assertGreaterEqual(replay_payload["diagnostics"]["snapshot_count"], 1)
        self.assertIsNotNone(replay_payload["template"])
        self.assertIsNotNone(replay_payload["learning_draft"])

    def test_managed_runtime_execution_replans_and_enqueues_follow_up_task(self) -> None:
        from scene_pilot.runtime.models import LLMResponse, ToolCall

        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "Open the web app, inspect the live detail page, and keep the summary current.",
                "title": "Managed runtime replan",
                "preferred_capabilities": ["browser", "document"],
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        task_spec_id = compiled_task.json()["task_spec"]["id"]
        plan_id = compiled_task.json()["execution_plan"]["id"]
        base_version = compiled_task.json()["execution_plan"]["version"]

        self.container.providers.providers["openai_compatible"] = _SequentialProvider(
            "openai_compatible",
            [
                LLMResponse(
                    content="the scene diverged, request a replan",
                    tool_calls=[
                        ToolCall(
                            id="replan-1",
                            name="request_replan",
                            arguments={
                                "step_id": "inspect_detail_surface",
                                "reason": "The current detail surface no longer matches the active plan.",
                                "preferred_capabilities": ["browser", "document"],
                                "suggested_steps": [
                                    {"id": "refresh_scene", "capability": "browser"},
                                    {"id": "capture_revised_detail", "capability": "document"},
                                ],
                                "scene_update": {
                                    "source": "browser",
                                    "url": "https://example.com/detail",
                                    "title": "Example Detail",
                                    "page_type": "detail_surface",
                                },
                            },
                        )
                    ],
                )
            ],
        )
        self.container.providers.fallback_order = ["openai_compatible", "scripted_default"]

        launch = self.client.post(
            f"{EXECUTION_API_BASE}/plans/{plan_id}/launch",
            json={
                "task_spec_id": task_spec_id,
                "requested_by": "desktop-user",
                "mode": "production",
                "payload": {
                    "environment_snapshot": {
                        "source": "browser",
                        "url": "https://example.com/detail",
                        "title": "Example Detail",
                        "page_type": "detail_surface",
                        "observed_entities": [{"kind": "detail_card", "label": "Candidate detail"}],
                    }
                },
            },
        )
        self.assertEqual(launch.status_code, 201)
        episode_id = launch.json()["execution_episode"]["id"]

        run_once = self.client.post("/api/agent/run-once")
        self.assertEqual(run_once.status_code, 200)
        self.assertEqual(run_once.json()["status"], "replan_requested")

        refreshed_episode = self.client.get(f"{EXECUTION_API_BASE}/runs/{episode_id}")
        self.assertEqual(refreshed_episode.status_code, 200)
        self.assertEqual(refreshed_episode.json()["status"], "diverged")
        self.assertTrue(refreshed_episode.json()["divergence_detected"])

        replans = self.client.get(f"{EXECUTION_API_BASE}/replans")
        self.assertEqual(replans.status_code, 200)
        queue_items = self.client.get("/api/agent/queue")
        self.assertEqual(queue_items.status_code, 200)
        pending_runtime_tasks = [
            item for item in queue_items.json() if item["task_type"] == "scale_execution" and item["status"] == "pending"
        ]
        self.assertTrue(pending_runtime_tasks)
        follow_up_plan_id = pending_runtime_tasks[0]["payload"]["execution_plan_id"]
        replanned_item = next(item for item in replans.json() if item["execution_plan"]["id"] == follow_up_plan_id)
        self.assertEqual(replanned_item["execution_plan"]["version"], replanned_item["previous_plan"]["version"] + 1)
        if replanned_item["base_execution_plan_id"] != plan_id:
            self.assertEqual(
                replanned_item["previous_plan"]["runtime_metadata"].get("replanned_from_plan_id"),
                plan_id,
            )
        self.assertEqual(
            follow_up_plan_id,
            replanned_item["execution_plan"]["id"],
        )

    def test_managed_runtime_execution_waits_for_human_when_preflight_is_blocked(self) -> None:
        compiled_task = self.client.post(
            f"{EXECUTION_API_BASE}/playbooks/compile",
            json={
                "instruction": "打开招聘网站，按照要求找到候选人，查看候选人资料和简历，完成初筛评分，并输出候选人结论和下一步建议。",
                "title": "Recruiting production run",
                "domain_hint": "recruiting",
                "constraints": {
                    "requires_human_supervision": True,
                    "no_outbound_messaging_without_approval": True,
                    "no_downstream_write_without_approval": True,
                },
                "preferred_capabilities": ["browser", "search", "document", "llm"],
            },
        )
        self.assertEqual(compiled_task.status_code, 201)
        task_spec_id = compiled_task.json()["task_spec"]["id"]
        plan_id = compiled_task.json()["execution_plan"]["id"]

        trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs",
            json={
                "task_spec_id": task_spec_id,
                "execution_plan_id": plan_id,
                "requested_by": "desktop-user",
            },
        )
        self.assertEqual(trial.status_code, 201)
        episode_id = trial.json()["id"]

        execute_trial = self.client.post(
            f"{EXECUTION_API_BASE}/runs/{episode_id}/execute",
            json={
                "source": "browser",
                "url": "https://example.com/recruiting/listing",
                "title": "候选人列表页",
                "page_type": "listing_surface",
                "observed_entities": [
                    {"kind": "candidate_card", "label": "候选人卡片"},
                    {"kind": "resume_entry", "label": "简历入口"},
                ],
                "affordances": [
                    {"kind": "open_detail", "label": "查看候选人详情"},
                    {"kind": "open_resume", "label": "打开简历"},
                ],
            },
        )
        self.assertEqual(execute_trial.status_code, 200)

        confirm = self.client.post(
            f"{EXECUTION_API_BASE}/runs/{episode_id}/confirm",
            json={"reviewer": "desktop-user", "reason": "Promote for production", "activate_template": True},
        )
        self.assertEqual(confirm.status_code, 200)

        self.container.agent_control.agent_loop.provider = _FailingProvider()

        launch = self.client.post(
            f"{EXECUTION_API_BASE}/plans/{plan_id}/launch",
            json={
                "task_spec_id": task_spec_id,
                "requested_by": "desktop-user",
                "mode": "production",
                "payload": {},
            },
        )
        self.assertEqual(launch.status_code, 201)
        execution_episode_id = launch.json()["execution_episode"]["id"]

        run_once = self.client.post("/api/agent/run-once")
        self.assertEqual(run_once.status_code, 200)
        self.assertEqual(run_once.json()["status"], "waiting_human")

        refreshed_episode = self.client.get(f"{EXECUTION_API_BASE}/runs/{execution_episode_id}")
        self.assertEqual(refreshed_episode.status_code, 200)
        self.assertEqual(refreshed_episode.json()["status"], "awaiting_review")
        self.assertIn("缺少实时浏览器场景快照", refreshed_episode.json()["result_summary"])

        approvals = self.client.get("/api/approvals")
        self.assertEqual(approvals.status_code, 200)
        blocked = [item for item in approvals.json() if item["target_type"] == "blocked_task"]
        self.assertTrue(blocked)
        self.assertEqual(blocked[0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
