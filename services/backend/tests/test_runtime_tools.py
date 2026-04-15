from __future__ import annotations

import sys
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.runtime.models import ToolExecutionResult
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

    def test_boss_discover_candidates_tool_message_is_compacted(self) -> None:
        result = ToolExecutionResult(
            tool_name="boss_discover_candidates",
            output=[
                {
                    "candidate_id": "cand-1",
                    "platform_candidate_id": "cand-1",
                    "name": "王利霖",
                    "platform": "boss",
                    "status": "discovered",
                    "contact_info": {
                        "summary": "20-30K | 王利霖 | 刚刚活跃 | 北京 售前技术支持",
                    },
                    "online_resume_text": "A" * 5000,
                    "profile_or_resume_evidence": {
                        "kind": "embedded_profile_card",
                        "summary": "候选人摘要",
                        "text_excerpt": "B" * 5000,
                    },
                    "source_scene": {"url": "https://example.com"},
                    "upload_status": "not_started",
                }
            ],
        )

        message = result.to_message_content()

        self.assertIn('"candidate_count": 1', message)
        self.assertIn('"name": "王利霖"', message)
        self.assertIn('"profile_or_resume_evidence"', message)
        self.assertNotIn('"text_excerpt"', message)
        self.assertNotIn("A" * 1000, message)
        self.assertNotIn("B" * 1000, message)

    def test_browser_capture_scene_tool_message_omits_large_raw_lists(self) -> None:
        result = ToolExecutionResult(
            tool_name="browser_capture_scene",
            output={
                "source": "browser",
                "environment_key": "recruiting:boss_recommend_candidates",
                "url": "https://example.com",
                "title": "推荐牛人",
                "page_type": "listing_surface",
                "observed_entities": [{"kind": "candidate_card", "label": "王利霖"}] * 10,
                "affordances": [{"kind": "button", "label": "打招呼"}] * 8,
                "runtime_metadata": {
                    "candidate_cards": [{"name": "王利霖", "profile_text": "X" * 5000}] * 5,
                    "page_text_excerpt": "Y" * 5000,
                },
            },
        )

        message = result.to_message_content()

        self.assertIn('"observed_entity_count": 10', message)
        self.assertIn('"affordance_count": 8', message)
        self.assertIn('"candidate_names": [', message)
        self.assertNotIn('"candidate_cards"', message)
        self.assertNotIn("X" * 1000, message)
        self.assertNotIn("Y" * 1000, message)

    def test_control_tool_messages_only_echo_minimum_fields(self) -> None:
        observation = ToolExecutionResult(
            tool_name="record_observation",
            output={
                "accepted": True,
                "payload": {
                    "step_id": "assess_runtime_scene",
                    "capability": "browser",
                    "summary": "S" * 1000,
                    "signals": ["listing_surface", "detail_surface", "well_observed_scene"],
                    "evidence": {"huge": "X" * 5000},
                },
            },
        )
        progress = ToolExecutionResult(
            tool_name="advance_plan_step",
            output={
                "accepted": True,
                "payload": {
                    "step_id": "assess_runtime_scene",
                    "status": "completed",
                    "summary": "P" * 1000,
                    "artifacts": {"huge": "Y" * 5000},
                },
            },
        )

        observation_message = observation.to_message_content()
        progress_message = progress.to_message_content()

        self.assertIn('"step_id": "assess_runtime_scene"', observation_message)
        self.assertIn('"capability": "browser"', observation_message)
        self.assertNotIn("X" * 1000, observation_message)
        self.assertIn('"status": "completed"', progress_message)
        self.assertNotIn("Y" * 1000, progress_message)


if __name__ == "__main__":
    unittest.main()
