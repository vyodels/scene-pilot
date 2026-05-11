from __future__ import annotations

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
