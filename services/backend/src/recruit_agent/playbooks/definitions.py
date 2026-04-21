from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BlueprintTransition:
    condition: str
    target_node_id: str


@dataclass(slots=True)
class BlueprintNode:
    node_id: str
    name: str
    task_type: str
    transitions: list[BlueprintTransition] = field(default_factory=list)
    requires_skill: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlaybookBlueprint:
    blueprint_id: str
    name: str
    start_node_id: str
    nodes: dict[str, BlueprintNode]
    version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def node(self, node_id: str) -> BlueprintNode:
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"Unknown blueprint node: {node_id}") from exc

    def validate(self) -> None:
        if self.start_node_id not in self.nodes:
            raise ValueError(f"Start node missing: {self.start_node_id}")
        for node in self.nodes.values():
            for transition in node.transitions:
                if transition.target_node_id not in self.nodes:
                    raise ValueError(
                        f"Node {node.node_id} points to unknown target {transition.target_node_id}"
                    )

    def next_nodes(self, node_id: str, outcome: str | None = None) -> list[BlueprintNode]:
        node = self.node(node_id)
        matched: list[BlueprintNode] = []
        default_target: BlueprintNode | None = None

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


_KIND_TO_STAGE = {
    "discover": "candidate_discovery",
    "screen": "candidate_probe",
    "communicate": "candidate_outreach",
    "communication": "candidate_outreach",
    "resume": "resume_collection",
    "score": "candidate_scoring",
    "review": "strategy_distill",
    "archive": "candidate_archive",
    "cooldown": "strategy_distill",
    "talent_pool": "scale_execution",
}


def _coerce_transition(raw_transition: Any) -> BlueprintTransition | None:
    if isinstance(raw_transition, BlueprintTransition):
        return raw_transition
    if isinstance(raw_transition, str) and raw_transition.strip():
        return BlueprintTransition(condition="default", target_node_id=raw_transition.strip())
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
    return BlueprintTransition(condition=str(condition), target_node_id=target_node_id.strip())


def _node_task_type(node_id: str, payload: dict[str, Any], fallback: BlueprintNode | None) -> str:
    explicit = payload.get("task_type") or payload.get("task")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    kind = payload.get("kind")
    if isinstance(kind, str) and kind.strip():
        return _KIND_TO_STAGE.get(kind.strip().lower(), node_id)

    if fallback is not None:
        return fallback.task_type

    return node_id


def playbook_blueprint_from_payload(
    *,
    blueprint_id: str,
    name: str,
    blueprint: dict[str, Any] | None,
    version: int | str | None = None,
    fallback: PlaybookBlueprint | None = None,
) -> PlaybookBlueprint:
    payload = dict(blueprint or {})
    default_blueprint = fallback or build_default_recruiting_playbook_blueprint()
    default_nodes = default_blueprint.nodes

    nodes_payload = payload.get("nodes")
    if isinstance(nodes_payload, dict):
        nodes_payload = list(nodes_payload.values())
    if not isinstance(nodes_payload, list) or not nodes_payload:
        return default_blueprint

    edge_map: dict[str, list[BlueprintTransition]] = {}
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

    nodes: dict[str, BlueprintNode] = {}
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
        transitions: list[BlueprintTransition] = []
        transition_payload = node_payload.get("transitions")
        if isinstance(transition_payload, list):
            for item in transition_payload:
                if (transition := _coerce_transition(item)) is not None:
                    transitions.append(transition)
        elif node_id in edge_map:
            transitions.extend(edge_map[node_id])
        elif fallback_node is not None:
            transitions.extend(
                BlueprintTransition(condition=item.condition, target_node_id=item.target_node_id)
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

        nodes[node_id] = BlueprintNode(
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
        return default_blueprint

    for node_id, node in nodes.items():
        if node_id in inherited_transition_nodes:
            node.transitions = [
                transition
                for transition in node.transitions
                if transition.target_node_id in nodes
            ]

    start_node_id = str(payload.get("start_node_id") or payload.get("startNodeId") or ordered_ids[0]).strip()
    definition = PlaybookBlueprint(
        blueprint_id=blueprint_id,
        name=name,
        start_node_id=start_node_id,
        nodes=nodes,
        version=str(version or payload.get("version") or "1.0.0"),
        metadata={key: value for key, value in payload.items() if key not in {"start_node_id", "startNodeId", "nodes", "edges", "transitions"}},
    )
    definition.validate()
    return definition


def build_default_recruiting_playbook_blueprint() -> PlaybookBlueprint:
    nodes = {
        "candidate_discovery": BlueprintNode(
            node_id="candidate_discovery",
            name="Candidate Discovery",
            task_type="candidate_discovery",
            transitions=[BlueprintTransition(condition="default", target_node_id="candidate_probe")],
        ),
        "candidate_probe": BlueprintNode(
            node_id="candidate_probe",
            name="Candidate Probe",
            task_type="candidate_probe",
            transitions=[
                BlueprintTransition(condition="pass", target_node_id="candidate_outreach"),
                BlueprintTransition(condition="fail", target_node_id="strategy_distill"),
                BlueprintTransition(condition="default", target_node_id="candidate_outreach"),
            ],
        ),
        "candidate_outreach": BlueprintNode(
            node_id="candidate_outreach",
            name="Candidate Outreach",
            task_type="candidate_outreach",
            transitions=[
                BlueprintTransition(condition="resume_requested", target_node_id="resume_collection"),
                BlueprintTransition(condition="default", target_node_id="resume_collection"),
            ],
        ),
        "resume_collection": BlueprintNode(
            node_id="resume_collection",
            name="Resume Collection",
            task_type="resume_collection",
            transitions=[BlueprintTransition(condition="default", target_node_id="candidate_scoring")],
        ),
        "candidate_scoring": BlueprintNode(
            node_id="candidate_scoring",
            name="Candidate Scoring",
            task_type="candidate_scoring",
            transitions=[
                BlueprintTransition(condition="pass", target_node_id="scale_execution"),
                BlueprintTransition(condition="fail", target_node_id="strategy_distill"),
                BlueprintTransition(condition="default", target_node_id="strategy_distill"),
            ],
        ),
        "scale_execution": BlueprintNode(
            node_id="scale_execution",
            name="Scale Execution",
            task_type="scale_execution",
        ),
        "strategy_distill": BlueprintNode(
            node_id="strategy_distill",
            name="Strategy Distill",
            task_type="strategy_distill",
        ),
    }
    blueprint = PlaybookBlueprint(
        blueprint_id="default_recruiting",
        name="Default Recruiting Playbook",
        start_node_id="candidate_discovery",
        nodes=nodes,
    )
    blueprint.validate()
    return blueprint
