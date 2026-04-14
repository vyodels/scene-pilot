from __future__ import annotations

import sys
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.services.feature_flags import FeatureFlagService
from scene_pilot.services.skills import SkillLifecycleService, SkillRecord, SkillSafetyService, SkillStatus


class ServiceTests(unittest.TestCase):
    def test_skill_lifecycle_and_flags(self) -> None:
        flags = FeatureFlagService({"skills.auto_activate": True, "skills.system_command": False})
        lifecycle = SkillLifecycleService(flags=flags)
        safety = SkillSafetyService(flags=flags)
        skill = SkillRecord(skill_id="skill-1", name="Screening", platform="boss")

        lifecycle.submit_for_review(skill)
        self.assertEqual(skill.status, SkillStatus.PENDING_REVIEW)

        lifecycle.approve(skill, reviewer="alice")
        self.assertEqual(skill.status, SkillStatus.APPROVED)
        self.assertTrue(safety.can_auto_activate(skill))

        lifecycle.activate(skill)
        self.assertEqual(skill.status, SkillStatus.ACTIVE)

        flags.set_flag("skills.auto_activate", False)
        self.assertFalse(safety.can_apply_system_command())


if __name__ == "__main__":
    unittest.main()
