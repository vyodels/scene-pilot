from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.agent_runtime.models import AgentResult
from recruit_agent.runtime.result_semantics import extract_business_status
from recruit_agent.scheduler.queue import TaskEnvelope

from .definitions import BlueprintNode, PlaybookBlueprint, build_default_recruiting_playbook_blueprint


def _build_adaptive_execution_blueprint() -> PlaybookBlueprint:
    return PlaybookBlueprint(
        blueprint_id="adaptive-managed",
        name="Adaptive Managed Execution",
        start_node_id="scale_execution",
        nodes={
            "scale_execution": BlueprintNode(
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
class PlaybookEngine:
    playbook: PlaybookBlueprint = field(default_factory=build_default_recruiting_playbook_blueprint)
    runtime_blueprint: PlaybookBlueprint = field(default_factory=_build_adaptive_execution_blueprint)
    session_factory: sessionmaker[Session] | None = None

    def resolve_playbook(self, task: TaskEnvelope) -> PlaybookBlueprint:
        if self._is_runtime_managed_task(task):
            return self.runtime_blueprint
        return self.playbook

    def resolve_node(self, task: TaskEnvelope, *, playbook: PlaybookBlueprint | None = None) -> BlueprintNode | None:
        definition = playbook or self.resolve_playbook(task)
        current_node_id = task.task_type or definition.start_node_id
        if current_node_id in definition.nodes:
            return definition.nodes[current_node_id]
        for node in definition.nodes.values():
            if node.task_type == task.task_type:
                return node
        return None

    def next_tasks(self, task: TaskEnvelope, result: AgentResult) -> list[TaskEnvelope]:
        playbook = self.resolve_playbook(task)
        current_node = self.resolve_node(task, playbook=playbook)
        current_node_id = current_node.node_id if current_node is not None else (task.task_type or playbook.start_node_id)
        outcome = extract_business_status(result.data, fallback="default") or "default"
        next_nodes = playbook.next_nodes(current_node_id, outcome=outcome)
        return [
            TaskEnvelope(
                task_id=f"{task.task_id}:{node.node_id}",
                task_type=node.task_type,
                person_id=task.person_id,
                application_id=task.application_id,
                priority=max(task.priority - 1, 1),
                payload=dict(task.payload),
                metadata={
                    **dict(task.metadata or {}),
                    "adaptive_stage": node.task_type,
                    "stage_name": node.name,
                    "stage_metadata": dict(node.metadata),
                    "blueprint_id": playbook.blueprint_id,
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
