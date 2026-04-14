from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkflowTransition:
    condition: str
    target_node_id: str


@dataclass(slots=True)
class WorkflowNode:
    node_id: str
    name: str
    task_type: str
    transitions: list[WorkflowTransition] = field(default_factory=list)
    requires_skill: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowDefinition:
    workflow_id: str
    name: str
    start_node_id: str
    nodes: dict[str, WorkflowNode]
    version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def node(self, node_id: str) -> WorkflowNode:
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"Unknown workflow node: {node_id}") from exc

    def validate(self) -> None:
        if self.start_node_id not in self.nodes:
            raise ValueError(f"Start node missing: {self.start_node_id}")
        for node in self.nodes.values():
            for transition in node.transitions:
                if transition.target_node_id not in self.nodes:
                    raise ValueError(
                        f"Node {node.node_id} points to unknown target {transition.target_node_id}"
                    )

    def next_nodes(self, node_id: str, outcome: str | None = None) -> list[WorkflowNode]:
        node = self.node(node_id)
        matched: list[WorkflowNode] = []
        default_target: WorkflowNode | None = None

        for transition in node.transitions:
            if transition.condition == "default":
                default_target = self.nodes[transition.target_node_id]
            elif outcome is not None and transition.condition == outcome:
                matched.append(self.nodes[transition.target_node_id])

        if matched:
            return matched
        if default_target is not None:
            return [default_target]
        return []


_KIND_TO_TASK_TYPE = {
    "discover": "discover_candidate",
    "screen": "initial_screening",
    "communicate": "initiate_communication",
    "communication": "initiate_communication",
    "resume": "request_resume",
    "score": "candidate_scoring",
    "review": "hr_review",
    "archive": "archive_candidate",
    "cooldown": "cooldown",
    "talent_pool": "talent_pool_upload",
}


def _coerce_transition(raw_transition: Any) -> WorkflowTransition | None:
    if isinstance(raw_transition, WorkflowTransition):
        return raw_transition
    if isinstance(raw_transition, str) and raw_transition.strip():
        return WorkflowTransition(condition="default", target_node_id=raw_transition.strip())
    if not isinstance(raw_transition, dict):
        return None

    condition = (
        raw_transition.get("condition")
        or raw_transition.get("outcome")
        or raw_transition.get("status")
        or "default"
    )
    target_node_id = (
        raw_transition.get("target_node_id")
        or raw_transition.get("target")
        or raw_transition.get("to")
        or raw_transition.get("node_id")
        or raw_transition.get("id")
    )
    if not isinstance(target_node_id, str) or not target_node_id.strip():
        return None
    return WorkflowTransition(condition=str(condition), target_node_id=target_node_id.strip())


def _node_task_type(node_id: str, payload: dict[str, Any], fallback: WorkflowNode | None) -> str:
    explicit = payload.get("task_type") or payload.get("task")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    kind = payload.get("kind")
    if isinstance(kind, str) and kind.strip():
        return _KIND_TO_TASK_TYPE.get(kind.strip().lower(), node_id)

    if fallback is not None:
        return fallback.task_type

    return node_id


def workflow_definition_from_config(
    *,
    workflow_id: str,
    name: str,
    config: dict[str, Any] | None,
    version: int | str | None = None,
    fallback: WorkflowDefinition | None = None,
) -> WorkflowDefinition:
    payload = dict(config or {})
    default_workflow = fallback or build_default_recruiting_workflow()
    default_nodes = default_workflow.nodes

    nodes_payload = payload.get("nodes")
    if isinstance(nodes_payload, dict):
        nodes_payload = list(nodes_payload.values())
    if not isinstance(nodes_payload, list) or not nodes_payload:
        return default_workflow

    edge_map: dict[str, list[WorkflowTransition]] = {}
    raw_edges = payload.get("edges") or payload.get("transitions") or []
    if isinstance(raw_edges, list):
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                continue
            source = raw_edge.get("source_node_id") or raw_edge.get("source") or raw_edge.get("from")
            if not source:
                continue
            transition = _coerce_transition(raw_edge)
            if transition is None:
                continue
            edge_map.setdefault(str(source), []).append(transition)

    nodes: dict[str, WorkflowNode] = {}
    inherited_transition_nodes: set[str] = set()
    ordered_ids: list[str] = []
    for raw_node in nodes_payload:
        if isinstance(raw_node, str):
            node_payload: dict[str, Any] = {"id": raw_node}
        elif isinstance(raw_node, dict):
            node_payload = dict(raw_node)
        else:
            continue

        node_id = str(node_payload.get("id") or node_payload.get("node_id") or "").strip()
        if not node_id:
            continue

        ordered_ids.append(node_id)
        fallback_node = default_nodes.get(node_id)
        transitions: list[WorkflowTransition] = []
        transition_payload = node_payload.get("transitions")
        if isinstance(transition_payload, list):
            for item in transition_payload:
                if (transition := _coerce_transition(item)) is not None:
                    transitions.append(transition)
        elif node_id in edge_map:
            transitions.extend(edge_map[node_id])
        elif fallback_node is not None:
            transitions.extend(
                WorkflowTransition(condition=item.condition, target_node_id=item.target_node_id)
                for item in fallback_node.transitions
            )
            inherited_transition_nodes.add(node_id)

        metadata = dict(node_payload.get("metadata") or {})
        for key, value in node_payload.items():
            if key not in {"id", "node_id", "name", "task_type", "task", "kind", "transitions", "requires_skill", "metadata"}:
                metadata.setdefault(key, value)
        kind = node_payload.get("kind")
        if isinstance(kind, str) and kind.strip():
            metadata.setdefault("kind", kind.strip())

        nodes[node_id] = WorkflowNode(
            node_id=node_id,
            name=str(node_payload.get("name") or (fallback_node.name if fallback_node is not None else node_id.replace("_", " ").title())),
            task_type=_node_task_type(node_id, node_payload, fallback_node),
            transitions=transitions,
            requires_skill=bool(
                node_payload.get("requires_skill", fallback_node.requires_skill if fallback_node is not None else False)
                or metadata.get("skill_id")
                or metadata.get("preferred_skill_id")
            ),
            metadata=metadata,
        )

    if not nodes:
        return default_workflow

    for node_id, node in nodes.items():
        if node_id in inherited_transition_nodes:
            node.transitions = [
                transition
                for transition in node.transitions
                if transition.target_node_id in nodes
            ]

    start_node_id = str(payload.get("start_node_id") or payload.get("startNodeId") or ordered_ids[0]).strip()
    definition = WorkflowDefinition(
        workflow_id=workflow_id,
        name=name,
        start_node_id=start_node_id,
        nodes=nodes,
        version=str(version or payload.get("version") or "1.0.0"),
        metadata={key: value for key, value in payload.items() if key not in {"start_node_id", "startNodeId", "nodes", "edges", "transitions"}},
    )
    definition.validate()
    return definition


def build_default_recruiting_workflow() -> WorkflowDefinition:
    nodes = {
        "discover_candidate": WorkflowNode(
            node_id="discover_candidate",
            name="Discover Candidate",
            task_type="discover_candidate",
            transitions=[WorkflowTransition(condition="default", target_node_id="initial_screening")],
        ),
        "initial_screening": WorkflowNode(
            node_id="initial_screening",
            name="Initial Screening",
            task_type="initial_screening",
            transitions=[
                WorkflowTransition(condition="pass", target_node_id="pending_communication"),
                WorkflowTransition(condition="fail", target_node_id="cooldown"),
                WorkflowTransition(condition="default", target_node_id="pending_communication"),
            ],
        ),
        "pending_communication": WorkflowNode(
            node_id="pending_communication",
            name="Pending Communication",
            task_type="initiate_communication",
            transitions=[
                WorkflowTransition(condition="resume_requested", target_node_id="request_resume"),
                WorkflowTransition(condition="default", target_node_id="request_resume"),
            ],
        ),
        "request_resume": WorkflowNode(
            node_id="request_resume",
            name="Request Resume",
            task_type="request_resume",
            transitions=[WorkflowTransition(condition="default", target_node_id="candidate_scoring")],
        ),
        "candidate_scoring": WorkflowNode(
            node_id="candidate_scoring",
            name="Candidate Scoring",
            task_type="candidate_scoring",
            transitions=[
                WorkflowTransition(condition="pass", target_node_id="passed_to_talent_pool"),
                WorkflowTransition(condition="fail", target_node_id="cooldown"),
                WorkflowTransition(condition="default", target_node_id="passed_to_talent_pool"),
            ],
        ),
        "passed_to_talent_pool": WorkflowNode(
            node_id="passed_to_talent_pool",
            name="Talent Pool",
            task_type="talent_pool_upload",
        ),
        "cooldown": WorkflowNode(
            node_id="cooldown",
            name="Cooldown",
            task_type="cooldown",
        ),
    }
    workflow = WorkflowDefinition(
        workflow_id="default_recruiting",
        name="Default Recruiting Workflow",
        start_node_id="discover_candidate",
        nodes=nodes,
    )
    workflow.validate()
    return workflow
