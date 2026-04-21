from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3] / "src" / "recruit_agent"


def test_agent_runtime_packages_exist() -> None:
    expected_dirs = [
        ROOT / "agents",
        ROOT / "kernel",
        ROOT / "runtime",
        ROOT / "memory",
        ROOT / "assistant",
        ROOT / "execution_units",
        ROOT / "plugins",
        ROOT / "plugins" / "recruit",
        ROOT / "mcp",
        ROOT / "skills",
        ROOT / "evolution",
    ]

    missing = [str(path.relative_to(ROOT)) for path in expected_dirs if not path.is_dir()]
    assert not missing, f"missing agent runtime package directories: {missing}"


def test_agent_test_packages_exist() -> None:
    tests_root = Path(__file__).resolve().parents[1]
    expected_dirs = [
        tests_root / "unit",
        tests_root / "integration",
    ]

    missing = [str(path.relative_to(tests_root)) for path in expected_dirs if not path.is_dir()]
    assert not missing, f"missing agent test directories: {missing}"
