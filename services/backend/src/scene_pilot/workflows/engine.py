from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.runtime.models import AgentResult
from scene_pilot.runtime.result_semantics import extract_business_status
from scene_pilot.scheduler.queue import TaskEnvelope

from .definitions import WorkflowDefinition, WorkflowNode, build_default_recruiting_workflow


def _build_adaptive_execution_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id="adaptive-managed",
        name="Adaptive Managed Execution",
        start_node_id="scale_execution",
        nodes={
            "scale_execution": WorkflowNode(
                node_id="scale_execution",
                name="Scale Execution",
                task_type="scale_execution",
                transitions=[],
                requires_skill=False,
                metadata={"adaptive_managed": True},
            )
        },
        version="1.0.0",
        metadata={"adaptive_managed": True},
    )


@dataclass(slots=True)
class WorkflowEngine:
    workflow: WorkflowDefinition = field(default_factory=build_default_recruiting_workflow)
    runtime_workflow: WorkflowDefinition = field(default_factory=_build_adaptive_execution_workflow)
    session_factory: sessionmaker[Session] | None = None

    def resolve_workflow(self, task: TaskEnvelope) -> WorkflowDefinition:
        if self._is_runtime_managed_task(task):
            return self.runtime_workflow
        return self.workflow

    def resolve_node(self, task: TaskEnvelope, *, workflow: WorkflowDefinition | None = None) -> WorkflowNode | None:
        definition = workflow or self.resolve_workflow(task)
        current_node_id = task.task_type or definition.start_node_id
        if current_node_id in definition.nodes:
            return definition.nodes[current_node_id]
        for node in definition.nodes.values():
            if node.task_type == task.task_type:
                return node
        return None

    def next_tasks(self, task: TaskEnvelope, result: AgentResult) -> list[TaskEnvelope]:
        workflow = self.resolve_workflow(task)
        current_node = self.resolve_node(task, workflow=workflow)
        current_node_id = current_node.node_id if current_node is not None else (task.task_type or workflow.start_node_id)
        outcome = extract_business_status(result.data, fallback="default") or "default"
        next_nodes = workflow.next_nodes(current_node_id, outcome=outcome)
        return [
            TaskEnvelope(
                task_id=f"{task.task_id}:{node.node_id}",
                task_type=node.task_type,
                candidate_id=task.candidate_id,
                priority=max(task.priority - 1, 1),
                payload=dict(task.payload),
                metadata={
                    **dict(task.metadata or {}),
                    "adaptive_stage": node.task_type,
                    "stage_name": node.name,
                    "stage_metadata": dict(node.metadata),
                    "blueprint_id": workflow.workflow_id,
                    "requires_skill": node.requires_skill,
                    **(
                        {"skill_id": str(node.metadata.get("preferred_skill_id") or node.metadata.get("skill_id"))}
                        if node.metadata.get("preferred_skill_id") or node.metadata.get("skill_id")
                        else {}
                    ),
                },
            )
            for node in next_nodes
        ]

    def build_follow_up_factory(self) -> Callable[[TaskEnvelope, AgentResult], Iterable[TaskEnvelope]]:
        def _follow_up(task: TaskEnvelope, result: AgentResult) -> Iterable[TaskEnvelope]:
            if not result.success:
                return []
            return self.next_tasks(task, result)

        return _follow_up

    def _is_runtime_managed_task(self, task: TaskEnvelope) -> bool:
        if task.task_type == "scale_execution":
            return True
        metadata = dict(task.metadata or {})
        return bool(metadata.get("task_spec_id") and metadata.get("execution_plan_id"))
