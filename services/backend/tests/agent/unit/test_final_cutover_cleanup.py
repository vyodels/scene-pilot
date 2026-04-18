from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_legacy_runtime_paths_are_removed() -> None:
    missing_targets = [
        ROOT / "src" / "scene_pilot" / "runtime" / "agent_loop.py",
        ROOT / "src" / "scene_pilot" / "runtime" / "prompts.py",
        ROOT / "src" / "scene_pilot" / "services" / "agent.py",
        ROOT / "src" / "scene_pilot" / "services" / "autonomy.py",
        ROOT / "src" / "scene_pilot" / "services" / "runtime.py",
        ROOT / "src" / "scene_pilot" / "services" / "runtime_control.py",
        ROOT / "src" / "scene_pilot" / "services" / "context_assembler.py",
        ROOT / "src" / "scene_pilot" / "api" / "routers" / "runtime.py",
        ROOT / "src" / "recruit_agent" / "server.py",
        ROOT / "src" / "recruit_agent" / "core" / "app.py",
        ROOT / "tests" / "test_runtime_agent_loop.py",
        ROOT / "tests" / "test_runtime_prompts.py",
        ROOT / "tests" / "test_runtime_tools.py",
        ROOT / "tests" / "test_api_runtime.py",
        ROOT / "tests" / "test_autonomy_loop.py",
    ]

    present = [str(path.relative_to(ROOT)) for path in missing_targets if path.exists()]
    assert not present, f"legacy cutover paths still present: {present}"
