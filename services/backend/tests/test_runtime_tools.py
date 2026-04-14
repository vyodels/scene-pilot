from __future__ import annotations

import sys
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.runtime.tools import ToolDefinition, ToolExecutionError, ToolRegistry


class ToolRegistryTests(unittest.TestCase):
    def test_register_execute_and_duplicate_guard(self) -> None:
        registry = ToolRegistry()

        registry.register(
            ToolDefinition(
                name="echo",
                description="Echo arguments",
                parameters={"type": "object"},
                handler=lambda args: {"echoed": args},
            )
        )

        result = registry.execute("echo", {"value": "x"})
        self.assertFalse(result.is_error)
        self.assertEqual(result.output, {"echoed": {"value": "x"}})

        with self.assertRaises(ToolExecutionError):
            registry.register(
                ToolDefinition(
                    name="echo",
                    description="Duplicate",
                    parameters={"type": "object"},
                    handler=lambda args: args,
                )
            )

    def test_result_submission_tool(self) -> None:
        registry = ToolRegistry()
        tool = registry.build_result_submission_tool()
        registry.register(tool)
        result = registry.execute("submit_result", {"status": "completed"})
        self.assertFalse(result.is_error)
        self.assertEqual(result.output["accepted"], True)

    def test_system_command_tool_builder(self) -> None:
        registry = ToolRegistry()
        tool = registry.build_system_command_tool(
            lambda args: {"status": "pending_approval", "command": args["command"]},
        )
        registry.register(tool)

        result = registry.execute(
            "request_system_command",
            {"command": ["python3", "-m", "pytest"]},
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.output["status"], "pending_approval")
        self.assertTrue(registry.tools["request_system_command"].metadata["requires_approval"])


if __name__ == "__main__":
    unittest.main()
