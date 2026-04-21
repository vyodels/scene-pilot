from __future__ import annotations

from collections import deque

from .definitions import PlaybookBlueprint


def topological_sort(blueprint: PlaybookBlueprint) -> list[str]:
    blueprint.validate()
    indegree: dict[str, int] = {node_id: 0 for node_id in blueprint.nodes}
    for node in blueprint.nodes.values():
        for transition in node.transitions:
            indegree[transition.target_node_id] += 1

    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for transition in blueprint.nodes[node_id].transitions:
            indegree[transition.target_node_id] -= 1
            if indegree[transition.target_node_id] == 0:
                queue.append(transition.target_node_id)

    if len(ordered) != len(blueprint.nodes):
        raise ValueError("Playbook graph contains a cycle")
    return ordered


def reachable_nodes(blueprint: PlaybookBlueprint, start_node_id: str | None = None) -> set[str]:
    blueprint.validate()
    start = start_node_id or blueprint.start_node_id
    seen: set[str] = set()
    stack = [start]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = blueprint.nodes[node_id]
        stack.extend(transition.target_node_id for transition in node.transitions)
    return seen


def validate_acyclic(blueprint: PlaybookBlueprint) -> None:
    topological_sort(blueprint)
