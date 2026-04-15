from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.runtime.prompts import PromptBuilder, PromptLoader


class PromptTests(unittest.TestCase):
    def test_load_and_render_candidate_probe_prompt(self) -> None:
        loader = PromptLoader()
        template = loader.load_text("tasks/candidate_probe.md")
        self.assertIn("{jd_criteria}", template)

        builder = PromptBuilder(loader=loader)
        rendered = builder.render(template, {"jd_criteria": "Python, SQL, system design"})
        self.assertIn("Python, SQL, system design", rendered)

    def test_build_messages_includes_system_and_context(self) -> None:
        builder = PromptBuilder()
        task = SimpleNamespace(task_type="candidate_probe", payload={"jd_criteria": "Go"})

        messages = builder.build_messages(task, session={"session_id": "s-1"}, skill={"name": "screening"})
        self.assertGreaterEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[1].role, "user")
        self.assertIn("session_id", messages[1].content)
        self.assertIn("skill", messages[1].content)

    def test_managed_execution_includes_stage_specific_prompt(self) -> None:
        builder = PromptBuilder()
        task = SimpleNamespace(
            task_type="resume_collection",
            adaptive_stage="resume_collection",
            payload={"goal_text": "download one visible resume pdf"},
        )

        messages = builder.build_messages(
            task,
            extra_context={
                "execution_contract": {
                    "plan_name": "Resume Trial",
                    "domain": "recruiting",
                    "goal": "download one visible resume pdf",
                    "scene_type": "web_scene",
                    "planner_posture": "verify",
                    "current_step_id": "inspect_runtime_scene",
                    "steps": [
                        {
                            "id": "inspect_runtime_scene",
                            "capability": "browser",
                            "summary": "Inspect the active scene.",
                            "preferred_tools": ["browser_snapshot", "browser_execute_script"],
                        }
                    ],
                    "task_payload": {
                        "constraints": {"read_only_browser": True},
                        "success_criteria": {"requires_local_resume_file": True},
                    },
                }
            },
        )

        self.assertGreaterEqual(len(messages), 2)
        self.assertIn("adaptive execution layer", messages[0].content)
        self.assertIn("Collect an already-available resume or attachment", messages[0].content)
        self.assertIn("A visible attachment card, filename, preview link, or download affordance is only an entry point.", messages[0].content)


if __name__ == "__main__":
    unittest.main()
