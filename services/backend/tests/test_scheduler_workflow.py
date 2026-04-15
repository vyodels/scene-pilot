from __future__ import annotations

from pathlib import Path
import sys
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.runtime.models import AgentResult
from scene_pilot.scheduler.queue import TaskEnvelope
from scene_pilot.workflows.dag import reachable_nodes, topological_sort, validate_acyclic
from scene_pilot.workflows.definitions import WorkflowDefinition, WorkflowNode, WorkflowTransition, build_default_recruiting_workflow
from scene_pilot.workflows.engine import WorkflowEngine


class WorkflowTests(unittest.TestCase):
    def test_default_workflow_is_acyclic_and_reachable(self) -> None:
        workflow = build_default_recruiting_workflow()
        order = topological_sort(workflow)
        self.assertIn("candidate_discovery", order)
        self.assertIn("scale_execution", reachable_nodes(workflow))
        validate_acyclic(workflow)

    def test_transition_resolution(self) -> None:
        workflow = build_default_recruiting_workflow()
        next_nodes = workflow.next_nodes("candidate_probe", outcome="pass")
        self.assertEqual([node.node_id for node in next_nodes], ["candidate_outreach"])

    def test_invalid_target_raises(self) -> None:
        workflow = WorkflowDefinition(
            workflow_id="bad",
            name="Bad",
            start_node_id="start",
            nodes={
                "start": WorkflowNode(
                    node_id="start",
                    name="Start",
                    task_type="start",
                    transitions=[WorkflowTransition(condition="default", target_node_id="missing")],
                )
            },
        )
        with self.assertRaises(ValueError):
            workflow.validate()

    def test_engine_generates_next_adaptive_stage(self) -> None:
        workflow_engine = WorkflowEngine()
        follow_ups = workflow_engine.next_tasks(
            TaskEnvelope(
                task_id="task-1",
                task_type="candidate_probe",
                candidate_id="candidate-1",
            ),
            AgentResult(success=True, status="completed", data={"status": "pass"}),
        )

        self.assertEqual(len(follow_ups), 1)
        self.assertEqual(follow_ups[0].metadata["adaptive_stage"], "candidate_outreach")
        self.assertEqual(follow_ups[0].task_type, "candidate_outreach")

    def test_engine_routes_using_nested_business_decision(self) -> None:
        workflow = WorkflowDefinition(
            workflow_id="decision-flow",
            name="Decision Flow",
            start_node_id="screen",
            nodes={
                "screen": WorkflowNode(
                    node_id="screen",
                    name="Screen",
                    task_type="candidate_probe",
                    transitions=[WorkflowTransition(condition="pass", target_node_id="resume")],
                ),
                "resume": WorkflowNode(
                    node_id="resume",
                    name="Resume",
                    task_type="resume_collection",
                ),
            },
        )

        workflow_engine = WorkflowEngine(workflow=workflow)
        follow_ups = workflow_engine.next_tasks(
            TaskEnvelope(task_id="task-2", task_type="candidate_probe"),
            AgentResult(
                success=True,
                status="completed",
                data={"status": "completed", "screening_result": {"decision": "pass"}},
            ),
        )

        self.assertEqual(len(follow_ups), 1)
        self.assertEqual(follow_ups[0].task_type, "resume_collection")


if __name__ == "__main__":
    unittest.main()
