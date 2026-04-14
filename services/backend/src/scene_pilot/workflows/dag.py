from __future__ import annotations

from collections import deque

from .definitions import WorkflowDefinition


def topological_sort(workflow: WorkflowDefinition) -> list[str]:
    workflow.validate()
    indegree: dict[str, int] = {node_id: 0 for node_id in workflow.nodes}
    for node in workflow.nodes.values():
        for transition in node.transitions:
            indegree[transition.target_node_id] += 1

    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for transition in workflow.nodes[node_id].transitions:
            indegree[transition.target_node_id] -= 1
            if indegree[transition.target_node_id] == 0:
                queue.append(transition.target_node_id)

    if len(ordered) != len(workflow.nodes):
        raise ValueError("Workflow graph contains a cycle")
    return ordered


def reachable_nodes(workflow: WorkflowDefinition, start_node_id: str | None = None) -> set[str]:
    workflow.validate()
    start = start_node_id or workflow.start_node_id
    seen: set[str] = set()
    stack = [start]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = workflow.nodes[node_id]
        stack.extend(transition.target_node_id for transition in node.transitions)
    return seen


def validate_acyclic(workflow: WorkflowDefinition) -> None:
    topological_sort(workflow)
