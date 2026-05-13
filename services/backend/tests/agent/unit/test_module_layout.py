from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3] / "src" / "recruit_agent"


def test_agent_packages_exist() -> None:
    expected_dirs = [
        ROOT / "agents",
        ROOT / "agent_runtime",
        ROOT / "capabilities",
        ROOT / "product_adapters",
        ROOT / "memory",
        ROOT / "assistant",
        ROOT / "plugins",
        ROOT / "plugins" / "recruit",
        ROOT / "mcp",
        ROOT / "skills",
        ROOT / "evolution",
    ]

    missing = [str(path.relative_to(ROOT)) for path in expected_dirs if not path.is_dir()]
    assert not missing, f"missing agent package directories: {missing}"


def test_agent_test_packages_exist() -> None:
    tests_root = Path(__file__).resolve().parents[1]
    expected_dirs = [
        tests_root / "unit",
        tests_root / "integration",
    ]

    missing = [str(path.relative_to(tests_root)) for path in expected_dirs if not path.is_dir()]
    assert not missing, f"missing agent test directories: {missing}"


def test_agent_runtime_does_not_import_product_capability_layers() -> None:
    forbidden_import_fragments = [
        "recruit_agent.agents",
        "recruit_agent.assistant",
        "recruit_agent.memory",
        "recruit_agent.mcp",
        "recruit_agent.models",
        "recruit_agent.plugins",
        "recruit_agent.capabilities",
        "recruit_agent.product_adapters",
        "recruit_agent.services",
        "recruit_agent.skills",
    ]
    offenders: list[str] = []
    for path in (ROOT / "agent_runtime").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for fragment in forbidden_import_fragments:
            if fragment in source:
                offenders.append(f"{path.relative_to(ROOT)} imports {fragment}")

    assert not (ROOT / "agent_runtime" / "models.py").exists()
    assert not (ROOT / "runtime").exists()
    assert not (ROOT / "scheduler" / "types.py").exists()
    assert not offenders


def test_agent_runtime_does_not_reintroduce_product_run_concepts() -> None:
    forbidden_terms = [
        "GoalSpec",
        "AgentProfile",
        "RecruitAgentProfile",
        "Assistant",
        "Autonomous",
        "AgentRun",
        "Candidate",
        "JobDescription",
        "business_tool",
        "agent_work_items",
        "work_item",
        "automationInstruction",
        "instructionTemplate",
        "instruction_template",
    ]
    offenders: list[str] = []
    for path in (ROOT / "agent_runtime").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            if term in source:
                offenders.append(f"{path.relative_to(ROOT)} contains {term}")
        for token in source.replace('"', " ").replace("'", " ").split():
            if token.strip(".,:;()[]{}") == "goal":
                offenders.append(f"{path.relative_to(ROOT)} contains goal")

    assert not offenders


def test_agent_runtime_keeps_agent_definition_product_agnostic() -> None:
    allowed_agent_definition_classes = {"AgentDefinition"}
    forbidden_agent_definition_terms = [
        "AssistantDefinition",
        "AutonomousDefinition",
        "AssistantAgentDefinition",
        "AutonomousAgentDefinition",
    ]
    forbidden_agent_definition_fragments = [
        "Assistant",
        "Autonomous",
        "AgentRun",
        "AgentTurnRecord",
        "agent_kind",
        "product_type",
    ]

    offenders: list[str] = []
    for path in (ROOT / "agent_runtime").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source)
        for node in ast.walk(module):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name in forbidden_agent_definition_terms:
                offenders.append(f"{path.relative_to(ROOT)} defines product-specific {node.name}")
            if node.name.endswith("AgentDefinition") and node.name not in allowed_agent_definition_classes:
                offenders.append(f"{path.relative_to(ROOT)} defines duplicate agent definition contract {node.name}")
            if node.name != "AgentDefinition":
                continue
            class_source = ast.get_source_segment(source, node) or ""
            for fragment in forbidden_agent_definition_fragments:
                if fragment in class_source:
                    offenders.append(f"{path.relative_to(ROOT)} AgentDefinition contains product term {fragment}")

    assert not offenders
