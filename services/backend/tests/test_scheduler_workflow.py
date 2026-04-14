from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.models import Workflow
from scene_pilot.runtime.models import AgentResult
from scene_pilot.scheduler.queue import TaskEnvelope
from scene_pilot.workflows.dag import reachable_nodes, topological_sort, validate_acyclic
from scene_pilot.workflows.definitions import WorkflowDefinition, WorkflowNode, WorkflowTransition, build_default_recruiting_workflow
from scene_pilot.workflows.engine import WorkflowEngine


class WorkflowTests(unittest.TestCase):
    def test_default_workflow_is_acyclic_and_reachable(self) -> None:
        workflow = build_default_recruiting_workflow()
        order = topological_sort(workflow)
        self.assertIn("discover_candidate", order)
        self.assertIn("passed_to_talent_pool", reachable_nodes(workflow))
        validate_acyclic(workflow)

    def test_transition_resolution(self) -> None:
        workflow = build_default_recruiting_workflow()
        next_nodes = workflow.next_nodes("initial_screening", outcome="pass")
        self.assertEqual([node.node_id for node in next_nodes], ["pending_communication"])

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

    def test_engine_resolves_persisted_workflow_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = AppSettings(
                data_dir=tempdir,
                database_url=f"sqlite:///{Path(tempdir) / 'scene-pilot.db'}",
            )
            engine = create_engine_from_settings(settings)
            initialize_database(engine)
            session_factory = create_session_factory(engine)

            with session_factory() as session:
                workflow = Workflow(
                    name="Persisted Screening",
                    status="active",
                    version=2,
                    config={
                        "start_node_id": "screen",
                        "nodes": [
                            {
                                "id": "screen",
                                "name": "Screen",
                                "task_type": "initial_screening",
                                "kind": "screen",
                                "transitions": [{"condition": "pass", "target": "resume"}],
                            },
                            {
                                "id": "resume",
                                "name": "Resume",
                                "task_type": "request_resume",
                                "kind": "resume",
                            },
                        ],
                    },
                )
                session.add(workflow)
                session.commit()
                workflow_id = workflow.id

            workflow_engine = WorkflowEngine(session_factory=session_factory)
            follow_ups = workflow_engine.next_tasks(
                TaskEnvelope(
                    task_id="task-1",
                    task_type="initial_screening",
                    workflow_id=workflow_id,
                    workflow_node_id="screen",
                    candidate_id="candidate-1",
                ),
                AgentResult(success=True, status="completed", data={"status": "pass"}),
            )

            self.assertEqual(len(follow_ups), 1)
            self.assertEqual(follow_ups[0].workflow_node_id, "resume")
            self.assertEqual(follow_ups[0].task_type, "request_resume")

    def test_engine_routes_using_nested_business_decision(self) -> None:
        workflow = WorkflowDefinition(
            workflow_id="decision-flow",
            name="Decision Flow",
            start_node_id="screen",
            nodes={
                "screen": WorkflowNode(
                    node_id="screen",
                    name="Screen",
                    task_type="initial_screening",
                    transitions=[WorkflowTransition(condition="pass", target_node_id="resume")],
                ),
                "resume": WorkflowNode(
                    node_id="resume",
                    name="Resume",
                    task_type="request_resume",
                ),
            },
        )

        workflow_engine = WorkflowEngine(workflow=workflow)
        follow_ups = workflow_engine.next_tasks(
            TaskEnvelope(task_id="task-2", task_type="initial_screening", workflow_node_id="screen"),
            AgentResult(
                success=True,
                status="completed",
                data={"status": "completed", "screening_result": {"decision": "pass"}},
            ),
        )

        self.assertEqual(len(follow_ups), 1)
        self.assertEqual(follow_ups[0].workflow_node_id, "resume")


if __name__ == "__main__":
    unittest.main()
