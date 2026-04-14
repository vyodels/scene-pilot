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
class ApiWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        from scene_pilot.core.settings import load_settings
        from scene_pilot.server import create_app

        self.tempdir = tempfile.TemporaryDirectory()
        os.environ["SCENE_PILOT_DATA_DIR"] = self.tempdir.name
        load_settings.cache_clear()
        self.client = TestClient(create_app())
        self.client.__enter__()
        self._load_settings = load_settings

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.tempdir.cleanup()
        os.environ.pop("SCENE_PILOT_DATA_DIR", None)
        self._load_settings.cache_clear()

    def test_candidate_crud_and_approval(self) -> None:
        created = self.client.post(
            "/api/candidates",
            json={
                "name": "Test Candidate",
                "platform": "boss",
                "status": "discovered",
                "jd_id": "jd-test",
            },
        )
        self.assertEqual(created.status_code, 201)
        candidate_id = created.json()["id"]

        updated = self.client.patch(
            f"/api/candidates/{candidate_id}",
            json={"status": "screening", "current_workflow_node": "initial_screening"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["status"], "screening")

        approvals = self.client.get("/api/approvals")
        self.assertEqual(approvals.status_code, 200)
        approval_id = approvals.json()[0]["id"]
        approved = self.client.post(
            f"/api/approvals/{approval_id}/approve",
            json={"reviewer": "desktop-user", "reason": "Looks safe"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")

    def test_agent_queue_and_run(self) -> None:
        dashboard = self.client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        candidate_id = dashboard.json()["candidates"][0]["id"]

        queued = self.client.post(
            "/api/agent/tasks",
            json={
                "task_type": "initial_screening",
                "priority": 150,
                "candidate_id": candidate_id,
                "payload": {"jd_criteria": "Python"},
            },
        )
        self.assertEqual(queued.status_code, 200)
        self.assertEqual(queued.json()["queue_depth"], 1)
        task_id = queued.json()["task_id"]

        run_once = self.client.post("/api/agent/run-once")
        self.assertEqual(run_once.status_code, 200)
        payload = run_once.json()
        self.assertTrue(payload["processed"])
        self.assertIn(payload["status"], {"completed", "idle"})

        agent_status = self.client.get("/api/agent")
        self.assertEqual(agent_status.status_code, 200)
        self.assertGreaterEqual(agent_status.json()["queueDepth"], 1)

        request_resume = self.client.post(
            "/api/agent/tasks",
            json={"task_type": "request_resume", "priority": 300, "candidate_id": candidate_id},
        )
        self.assertEqual(request_resume.status_code, 200)
        self.assertGreaterEqual(request_resume.json()["queue_depth"], 2)

        direct_run = self.client.post("/api/agent/run-once")
        self.assertEqual(direct_run.status_code, 200)
        direct_payload = direct_run.json()
        self.assertTrue(direct_payload["processed"])
        self.assertEqual(direct_payload["status"], "completed")

        queue_snapshot = self.client.get("/api/agent/queue")
        self.assertEqual(queue_snapshot.status_code, 200)
        queue_item = next(item for item in queue_snapshot.json() if item["task_id"] == task_id)
        self.assertIn(queue_item["status"], {"completed", "failed", "pending", "running"})
        self.assertGreaterEqual(len(queue_item["queue_audit"]), 2)

        recover = self.client.post("/api/agent/queue/recover")
        self.assertEqual(recover.status_code, 200)
        self.assertIsInstance(recover.json()["by_status"], dict)

    def test_runtime_skill_draft_persists_learning_and_approval(self) -> None:
        from scene_pilot.runtime.models import LLMResponse
        from scene_pilot.runtime.providers import ScriptedProvider

        container = self.client.app.state.container
        container.agent_control.agent_loop.provider = ScriptedProvider(
            provider_name="scripted-learning",
            responses=[
                LLMResponse(
                    content="Drafted a sharper screening heuristic.",
                    result_data={
                        "status": "pass",
                        "learning": {
                            "content": "Track architecture ownership signals during screening.",
                            "tags": ["screening", "architecture"],
                        },
                    },
                    skill_draft={
                        "content": "Promote architecture ownership as a primary screening factor.",
                        "tags": ["screening", "skill"],
                        "skill_name": "architecture_screening_v2",
                        "summary": "Increase emphasis on architecture ownership evidence.",
                    },
                )
            ],
        )

        dashboard = self.client.get("/api/dashboard")
        candidate_id = dashboard.json()["candidates"][0]["id"]
        queued = self.client.post(
            "/api/agent/tasks",
            json={
                "task_type": "initial_screening",
                "priority": 200,
                "candidate_id": candidate_id,
                "payload": {"jd_criteria": "Architecture"},
            },
        )
        task_id = queued.json()["task_id"]

        run_once = self.client.post("/api/agent/run-once")
        self.assertEqual(run_once.status_code, 200)
        self.assertEqual(run_once.json()["status"], "completed")

        learnings = self.client.get("/api/skills/learnings")
        self.assertEqual(learnings.status_code, 200)
        runtime_learning = next(
            item
            for item in learnings.json()
            if item["source_task_id"] == task_id and "skill_draft" in item["tags"]
        )
        self.assertIn("runtime", runtime_learning["tags"])

        approvals = self.client.get("/api/approvals?pending_only=true")
        self.assertEqual(approvals.status_code, 200)
        skill_draft_approval = next(
            item for item in approvals.json() if item["target_type"] == "skill_draft" and item["target_id"] == runtime_learning["id"]
        )
        self.assertEqual(skill_draft_approval["payload"]["task_id"], task_id)

        approved = self.client.post(
            f"/api/approvals/{skill_draft_approval['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Promote this runtime draft"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(approved.json()["payload"]["promoted_skill"]["status"], "approved")
        promoted_skill_id = approved.json()["payload"]["promoted_skill"]["id"]

        skills = self.client.get("/api/skills")
        self.assertEqual(skills.status_code, 200)
        promoted_skill = next(item for item in skills.json() if item["id"] == promoted_skill_id)
        self.assertEqual(promoted_skill["bound_to_workflow_node"], "initial_screening")
        self.assertEqual(promoted_skill["status"], "approved")
        self.assertEqual(promoted_skill["platform"], "runtime-scene")

        event_sources = [event.source for event in container.events.snapshot()]
        self.assertIn("learning", event_sources)
        self.assertIn("approval", event_sources)

        approved = self.client.post(
            f"/api/approvals/{skill_draft_approval['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Looks production-ready"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(approved.json()["payload"]["promoted_skill"]["status"], "approved")

        skills = self.client.get("/api/skills")
        self.assertEqual(skills.status_code, 200)
        promoted_skill = next(item for item in skills.json() if item["skill_id"].startswith("architecture_screening_v2"))
        self.assertEqual(promoted_skill["status"], "approved")

    def test_runtime_persists_session_skill_and_workflow_run(self) -> None:
        from scene_pilot.models import CandidateSession, DecisionLog, WorkflowRun
        from scene_pilot.runtime.models import LLMResponse
        from scene_pilot.runtime.providers import ScriptedProvider

        container = self.client.app.state.container
        container.agent_control.agent_loop.provider = ScriptedProvider(
            provider_name="scripted-runtime-persistence",
            responses=[
                LLMResponse(
                    content="Applied the active screening playbook.",
                    result_data={"status": "pass", "overall": 88, "summary": "Strong backend depth."},
                )
            ],
        )

        created_skill = self.client.post(
            "/api/skills",
            json={
                "skill_id": "screening_active_v1",
                "name": "Screening Active V1",
                "status": "active",
                "platform": "boss",
                "bound_to_workflow_node": "initial_screening",
                "strategy": {"summary": "Prioritize architecture ownership."},
                "execution_hints": {"style": "structured"},
            },
        )
        self.assertEqual(created_skill.status_code, 201)

        created_workflow = self.client.post(
            "/api/workflows",
            json={
                "name": "Persisted Screening Flow",
                "status": "active",
                "version": 2,
                "config": {
                    "start_node_id": "initial_screening",
                    "nodes": [
                        {
                            "id": "initial_screening",
                            "name": "Initial Screening",
                            "kind": "screen",
                            "task_type": "initial_screening",
                            "transitions": [{"condition": "pass", "target": "request_resume"}],
                        },
                        {
                            "id": "request_resume",
                            "name": "Request Resume",
                            "kind": "resume",
                            "task_type": "request_resume",
                        },
                    ],
                },
            },
        )
        self.assertEqual(created_workflow.status_code, 201)
        workflow_id = created_workflow.json()["id"]

        dashboard = self.client.get("/api/dashboard")
        candidate_id = dashboard.json()["candidates"][0]["id"]

        queued = self.client.post(
            "/api/agent/tasks",
            json={
                "task_type": "initial_screening",
                "priority": 240,
                "candidate_id": candidate_id,
                "workflow_id": workflow_id,
                "workflow_node_id": "initial_screening",
                "payload": {"jd_criteria": "Distributed systems"},
            },
        )
        self.assertEqual(queued.status_code, 200)
        task_id = queued.json()["task_id"]

        first_run = self.client.post("/api/agent/run-once")
        self.assertEqual(first_run.status_code, 200)
        self.assertEqual(first_run.json()["status"], "completed")

        agent_status = self.client.get("/api/agent")
        self.assertEqual(agent_status.status_code, 200)
        self.assertGreaterEqual(agent_status.json()["queueDepth"], 1)

        second_run = self.client.post("/api/agent/run-once")
        self.assertEqual(second_run.status_code, 200)
        self.assertEqual(second_run.json()["status"], "completed")

        with container.session_factory() as session:
            workflow_runs = session.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow_id).all()
            workflow_run = next((item for item in workflow_runs if item.context.get("task_id") == task_id), None)
            self.assertIsNotNone(workflow_run)
            self.assertEqual(workflow_run.status, "completed")
            self.assertEqual(workflow_run.current_node, "initial_screening")
            self.assertEqual(workflow_run.context["task_id"], task_id)
            self.assertEqual(workflow_run.context["skill"]["skill_id"], "screening_active_v1")
            self.assertEqual(workflow_run.context["session"]["candidate"]["id"], candidate_id)

            candidate_session = session.query(CandidateSession).filter(CandidateSession.candidate_id == candidate_id).first()
            self.assertIsNotNone(candidate_session)
            self.assertEqual(candidate_session.status, "active")
            self.assertEqual(candidate_session.facts["active_skill"]["skill_id"], "screening_active_v1")
            self.assertEqual(candidate_session.facts["last_result_status"], "pass")
            self.assertEqual(candidate_session.facts["last_execution_status"], "completed")
            self.assertEqual(workflow_run.context["result"]["business_status"], "pass")

            decision_log = session.query(DecisionLog).filter(DecisionLog.task_id == task_id).first()
            self.assertIsNotNone(decision_log)
            self.assertEqual(decision_log.decision_type, "initial_screening")
            self.assertEqual(decision_log.decision, "pass")

    def test_runtime_normalizes_provider_business_status_across_persistence(self) -> None:
        from scene_pilot.models import CandidateSession, DecisionLog, WorkflowRun
        from scene_pilot.runtime.models import LLMResponse
        from scene_pilot.runtime.providers import ScriptedProvider

        container = self.client.app.state.container
        container.agent_control.agent_loop.provider = ScriptedProvider(
            provider_name="scripted-provider-shape",
            responses=[
                LLMResponse(
                    content="Applied the active screening playbook.",
                    result_data={
                        "status": "completed",
                        "screening_result": {
                            "decision": "pass",
                            "summary": "Strong backend depth.",
                        },
                    },
                )
            ],
        )

        dashboard = self.client.get("/api/dashboard")
        candidate_id = dashboard.json()["candidates"][0]["id"]

        created_workflow = self.client.post(
            "/api/workflows",
            json={
                "name": "Provider Shape Flow",
                "status": "active",
                "config": {
                    "start_node_id": "initial_screening",
                    "nodes": [
                        {
                            "id": "initial_screening",
                            "name": "Initial Screening",
                            "kind": "screen",
                            "task_type": "initial_screening",
                            "transitions": [{"condition": "pass", "target": "request_resume"}],
                        },
                        {
                            "id": "request_resume",
                            "name": "Request Resume",
                            "kind": "resume",
                            "task_type": "request_resume",
                        },
                    ],
                },
            },
        )
        workflow_id = created_workflow.json()["id"]

        queued = self.client.post(
            "/api/agent/tasks",
            json={
                "task_type": "initial_screening",
                "priority": 240,
                "candidate_id": candidate_id,
                "workflow_id": workflow_id,
                "workflow_node_id": "initial_screening",
                "payload": {"jd_criteria": "Distributed systems"},
            },
        )
        task_id = queued.json()["task_id"]

        run_once = self.client.post("/api/agent/run-once")
        self.assertEqual(run_once.status_code, 200)
        self.assertEqual(run_once.json()["status"], "completed")

        with container.session_factory() as session:
            workflow_runs = session.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow_id).all()
            workflow_run = next((item for item in workflow_runs if item.context.get("task_id") == task_id), None)
            self.assertIsNotNone(workflow_run)
            self.assertEqual(workflow_run.context["result"]["business_status"], "pass")
            self.assertEqual(workflow_run.context["result"]["data"]["status"], "pass")
            self.assertEqual(workflow_run.context["result"]["data"]["execution_status"], "completed")

            candidate_session = session.query(CandidateSession).filter(CandidateSession.candidate_id == candidate_id).first()
            self.assertIsNotNone(candidate_session)
            self.assertEqual(candidate_session.facts["last_result_status"], "pass")
            self.assertEqual(candidate_session.facts["last_execution_status"], "completed")

            decision_log = session.query(DecisionLog).filter(DecisionLog.task_id == task_id).first()
            self.assertIsNotNone(decision_log)
            self.assertEqual(decision_log.decision, "pass")

    def test_runtime_updates_active_skill_health_after_execution(self) -> None:
        from scene_pilot.models import Skill
        from scene_pilot.runtime.models import LLMResponse
        from scene_pilot.runtime.providers import ScriptedProvider

        container = self.client.app.state.container
        container.agent_control.agent_loop.provider = ScriptedProvider(
            provider_name="scripted-skill-health",
            responses=[
                LLMResponse(
                    content="Screening completed below quality threshold.",
                    result_data={"status": "pass", "overall": 72, "summary": "Candidate is borderline."},
                )
            ],
        )

        created_skill = self.client.post(
            "/api/skills",
            json={
                "skill_id": "health_sensitive_screening",
                "name": "Health Sensitive Screening",
                "status": "active",
                "platform": "boss",
                "bound_to_workflow_node": "initial_screening",
                "strategy": {"summary": "Require stronger quality bar."},
                "health_check_config": {"minimum_overall_score": 85},
            },
        )
        self.assertEqual(created_skill.status_code, 201)
        skill_id = created_skill.json()["id"]

        dashboard = self.client.get("/api/dashboard")
        candidate_id = dashboard.json()["candidates"][0]["id"]

        queued = self.client.post(
            "/api/agent/tasks",
            json={
                "task_type": "initial_screening",
                "priority": 240,
                "candidate_id": candidate_id,
                "workflow_node_id": "initial_screening",
                "payload": {"jd_criteria": "Distributed systems"},
            },
        )
        self.assertEqual(queued.status_code, 200)

        run_once = self.client.post("/api/agent/run-once")
        self.assertEqual(run_once.status_code, 200)
        self.assertEqual(run_once.json()["status"], "completed")

        with container.session_factory() as session:
            skill = session.query(Skill).filter(Skill.id == skill_id).first()
            self.assertIsNotNone(skill)
            self.assertEqual(skill.status, "degraded")
            self.assertEqual(skill.last_health_status, "warning")
            self.assertIsNotNone(skill.last_health_check)

    def test_blocked_task_approval_resumes_execution(self) -> None:
        from scene_pilot.runtime.models import LLMResponse
        from scene_pilot.runtime.providers import ScriptedProvider

        container = self.client.app.state.container
        container.agent_control.agent_loop.provider = ScriptedProvider(
            provider_name="scripted-blocked-task",
            responses=[
                LLMResponse(
                    content="Need human review before continuing.",
                    requires_human_input=True,
                ),
                LLMResponse(
                    content="Human review applied.",
                    result_data={"status": "pass", "summary": "Resume completed."},
                ),
            ],
        )

        dashboard = self.client.get("/api/dashboard")
        candidate_id = dashboard.json()["candidates"][0]["id"]
        queued = self.client.post(
            "/api/agent/tasks",
            json={
                "task_type": "initial_screening",
                "priority": 210,
                "candidate_id": candidate_id,
                "payload": {"jd_criteria": "Resume review"},
            },
        )
        task_id = queued.json()["task_id"]

        first_run = self.client.post("/api/agent/run-once")
        self.assertEqual(first_run.status_code, 200)
        self.assertEqual(first_run.json()["status"], "waiting_human")

        approvals = self.client.get("/api/approvals?pending_only=true")
        self.assertEqual(approvals.status_code, 200)
        blocked_approval = next(
            item
            for item in approvals.json()
            if item["target_type"] == "blocked_task" and item["target_id"] == task_id
        )
        self.assertEqual(blocked_approval["payload"]["blocked_task"]["task_id"], task_id)
        self.assertIn("resume_task", blocked_approval["payload"])

        approved = self.client.post(
            f"/api/approvals/{blocked_approval['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Continue after human review"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(approved.json()["payload"]["resolution"]["status"], "approved")
        self.assertTrue(approved.json()["payload"]["resolution"]["resumed"])

        second_run = self.client.post("/api/agent/run-once")
        self.assertEqual(second_run.status_code, 200)
        self.assertEqual(second_run.json()["status"], "completed")

    def test_blocked_task_reject_marks_closure_metadata(self) -> None:
        from scene_pilot.runtime.models import LLMResponse
        from scene_pilot.runtime.providers import ScriptedProvider

        container = self.client.app.state.container
        container.agent_control.agent_loop.provider = ScriptedProvider(
            provider_name="scripted-blocked-task-reject",
            responses=[LLMResponse(content="Need human review before continuing.", requires_human_input=True)],
        )

        dashboard = self.client.get("/api/dashboard")
        candidate_id = dashboard.json()["candidates"][0]["id"]
        queued = self.client.post(
            "/api/agent/tasks",
            json={
                "task_type": "initial_screening",
                "priority": 205,
                "candidate_id": candidate_id,
                "payload": {"jd_criteria": "Resume review"},
            },
        )
        task_id = queued.json()["task_id"]

        first_run = self.client.post("/api/agent/run-once")
        self.assertEqual(first_run.status_code, 200)
        self.assertEqual(first_run.json()["status"], "waiting_human")

        approvals = self.client.get("/api/approvals?pending_only=true")
        self.assertEqual(approvals.status_code, 200)
        blocked_approval = next(
            item
            for item in approvals.json()
            if item["target_type"] == "blocked_task" and item["target_id"] == task_id
        )

        rejected = self.client.post(
            f"/api/approvals/{blocked_approval['id']}/reject",
            json={"reviewer": "desktop-user", "reason": "Do not resume"},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], "rejected")
        self.assertEqual(rejected.json()["payload"]["resolution"]["status"], "rejected")
        self.assertIn("closed_at", rejected.json()["payload"])
        self.assertFalse(rejected.json()["payload"]["resolution"]["resumed"])

    def test_system_command_request_enforces_flag_and_whitelist(self) -> None:
        container = self.client.app.state.container

        policy = self.client.get("/api/agent/system-commands/policy")
        self.assertEqual(policy.status_code, 200)
        self.assertFalse(policy.json()["enabled"])

        blocked = self.client.post(
            "/api/agent/system-commands/request",
            json={"command": ["python3", "-m", "pytest"], "requested_by": "desktop-user"},
        )
        self.assertEqual(blocked.status_code, 403)

        container.flags.set_flag("skills.system_command", True)

        rejected = self.client.post(
            "/api/agent/system-commands/request",
            json={"command": ["rm", "-rf", "/tmp/not-allowed"], "requested_by": "desktop-user"},
        )
        self.assertEqual(rejected.status_code, 400)

        requested = self.client.post(
            "/api/agent/system-commands/request",
            json={
                "command": ["python3", "-m", "pytest", "services/backend/tests/test_runtime_tools.py"],
                "requested_by": "desktop-user",
                "rationale": "Validate the runtime tool contract.",
            },
        )
        self.assertEqual(requested.status_code, 201)
        self.assertEqual(requested.json()["target_type"], "system_command")
        self.assertEqual(requested.json()["status"], "pending")
        self.assertEqual(requested.json()["payload"]["command"][0:3], ["python3", "-m", "pytest"])

        approved = self.client.post(
            f"/api/approvals/{requested.json()['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Allowed for validation"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(approved.json()["payload"]["execution_status"], "approved_but_disabled")
        self.assertFalse(approved.json()["payload"]["resolution"]["execution_enabled"])

    def test_system_command_execute_after_approval_when_enabled(self) -> None:
        container = self.client.app.state.container
        container.flags.set_flag("skills.system_command", True)
        container.system_commands.execution_enabled = True
        container.system_commands.whitelist = (
            *container.system_commands.whitelist,
            ("python3", "-c"),
        )

        requested = self.client.post(
            "/api/agent/system-commands/request",
            json={
                "command": ["python3", "-c", "print('system-command-ok')"],
                "requested_by": "desktop-user",
            },
        )
        self.assertEqual(requested.status_code, 201)

        not_ready = self.client.post(
            f"/api/agent/system-commands/{requested.json()['id']}/execute",
            json={"requested_by": "desktop-user"},
        )
        self.assertEqual(not_ready.status_code, 409)

        approved = self.client.post(
            f"/api/approvals/{requested.json()['id']}/approve",
            json={"reviewer": "desktop-user", "reason": "Safe local command"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["payload"]["command_resolution"]["execution_status"], "approved_ready")

        executed = self.client.post(
            f"/api/agent/system-commands/{requested.json()['id']}/execute",
            json={"requested_by": "desktop-user"},
        )
        self.assertEqual(executed.status_code, 200)
        self.assertEqual(executed.json()["payload"]["execution"]["status"], "completed")
        self.assertEqual(executed.json()["payload"]["command_resolution"]["execution_status"], "completed")
        self.assertIn("system-command-ok", executed.json()["payload"]["execution"]["stdout"])


if __name__ == "__main__":
    unittest.main()
