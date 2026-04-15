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


if __name__ == "__main__":
    unittest.main()
