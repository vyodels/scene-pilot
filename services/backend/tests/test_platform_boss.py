from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.platforms import BossPlatformAdapter, CandidateSnapshot


class BossPlatformAdapterTests(unittest.TestCase):
    def test_memory_backed_adapter_supports_core_actions(self) -> None:
        now = datetime.now(timezone.utc)
        adapter = BossPlatformAdapter(
            candidate_store={
                "cand-001": {
                    "name": "Mia Chen",
                    "platform": "boss",
                    "status": "screening",
                    "contact_info": {
                        "title": "Senior Frontend Engineer",
                        "location": "Shanghai",
                        "tags": ["React", "Design Systems"],
                    },
                    "ai_scores": {"overall": 92},
                    "last_contacted_at": (now - timedelta(days=10)).isoformat(),
                    "cooldown_days": 7,
                },
                "cand-002": {
                    "candidate_id": "cand-002",
                    "name": "Jason Li",
                    "platform": "boss",
                    "status": "pending_communication",
                    "contact_info": {
                        "title": "Backend Engineer",
                        "location": "Hangzhou",
                        "tags": ["Go", "APIs"],
                    },
                    "cooldown_until": (now + timedelta(days=2)).isoformat(),
                },
                "cand-003": {
                    "candidate_id": "cand-003",
                    "name": "Luna Wang",
                    "platform": "boss",
                    "status": "cooldown",
                    "contact_info": {
                        "title": "Product Manager",
                        "location": "Beijing",
                        "tags": ["Discovery", "Roadmap"],
                    },
                    "ai_scores": {"overall": 64},
                },
            }
        )

        self.assertTrue(adapter.healthcheck())

        matches = adapter.discover_candidates({"search": "frontend", "location": "shanghai", "tag": "react"})
        self.assertEqual(len(matches), 1)
        self.assertIsInstance(matches[0], CandidateSnapshot)
        self.assertEqual(matches[0].candidate_id, "cand-001")

        inspected = adapter.inspect_candidate("cand-001")
        self.assertEqual(inspected.name, "Mia Chen")
        self.assertEqual(inspected.raw["contact_info"]["title"], "Senior Frontend Engineer")

        self.assertFalse(adapter.check_cooldown("cand-001"))
        self.assertTrue(adapter.check_cooldown("cand-002"))

        message_result = adapter.send_message("cand-001", "Hello Mia, we would like to schedule a chat.")
        self.assertEqual(message_result["candidate_id"], "cand-001")
        self.assertEqual(message_result["status"], "sent")
        self.assertEqual(adapter.candidate_store["cand-001"]["status"], "pending_reply")
        self.assertEqual(len(adapter.browser_context["message_log"]), 1)

        resume_result = adapter.request_resume("cand-001")
        self.assertEqual(resume_result["status"], "requested")
        self.assertEqual(adapter.candidate_store["cand-001"]["status"], "awaiting_resume")
        self.assertEqual(len(adapter.browser_context["resume_requests"]), 1)

        score_result = adapter.score_candidate("cand-003", {"overall": 81, "reasoning": "strong"})
        self.assertEqual(score_result["recommendation"], "advance")
        self.assertEqual(adapter.candidate_store["cand-003"]["status"], "screening")
        self.assertEqual(adapter.candidate_store["cand-003"]["ai_scores"]["reasoning"], "strong")

        archive_result = adapter.archive_candidate("cand-003", "Moved to archived pipeline")
        self.assertEqual(archive_result["status"], "archived")
        self.assertEqual(adapter.candidate_store["cand-003"]["archive_reason"], "Moved to archived pipeline")
        self.assertEqual(len(adapter.browser_context["archive_log"]), 1)

    def test_injected_handlers_override_memory_defaults(self) -> None:
        calls: list[tuple[str, tuple[object, ...]]] = []

        def discover_handler(query: dict[str, object]) -> list[dict[str, object]]:
            calls.append(("discover", (query,)))
            return [{"candidate_id": "boss-007", "name": "Handled", "status": "screening", "source": "boss"}]

        def inspect_handler(candidate_id: str) -> dict[str, object]:
            calls.append(("inspect", (candidate_id,)))
            return {"candidate_id": candidate_id, "name": "Handled", "status": "screening"}

        def send_handler(candidate_id: str, message: str) -> dict[str, object]:
            calls.append(("send", (candidate_id, message)))
            return {"candidate_id": candidate_id, "message": message, "status": "sent"}

        def resume_handler(candidate_id: str) -> dict[str, object]:
            calls.append(("resume", (candidate_id,)))
            return {"candidate_id": candidate_id, "status": "requested"}

        def score_handler(candidate_id: str, scores: dict[str, object]) -> dict[str, object]:
            calls.append(("score", (candidate_id, scores)))
            return {"candidate_id": candidate_id, "status": "screening", "scores": scores}

        def archive_handler(candidate_id: str, reason: str) -> dict[str, object]:
            calls.append(("archive", (candidate_id, reason)))
            return {"candidate_id": candidate_id, "status": "archived", "reason": reason}

        def cooldown_handler(candidate_id: str) -> bool:
            calls.append(("cooldown", (candidate_id,)))
            return True

        adapter = BossPlatformAdapter(
            browser_context={
                "candidate_store": {
                    "boss-007": {
                        "candidate_id": "boss-007",
                        "name": "Fallback",
                        "platform": "boss",
                        "status": "pending_communication",
                    }
                }
            },
            action_handlers={
                "discover_candidates": discover_handler,
                "inspect_candidate": inspect_handler,
                "send_message": send_handler,
                "request_resume": resume_handler,
                "score_candidate": score_handler,
                "archive_candidate": archive_handler,
                "check_cooldown": cooldown_handler,
            },
        )

        discovered = adapter.discover_candidates({"search": "handled"})
        self.assertEqual(discovered[0].candidate_id, "boss-007")
        self.assertEqual(adapter.inspect_candidate("boss-007").name, "Handled")
        self.assertEqual(adapter.send_message("boss-007", "hello")["status"], "sent")
        self.assertEqual(adapter.request_resume("boss-007")["status"], "requested")
        self.assertEqual(adapter.score_candidate("boss-007", {"overall": 88})["status"], "screening")
        self.assertEqual(adapter.archive_candidate("boss-007", "done")["status"], "archived")
        self.assertTrue(adapter.check_cooldown("boss-007"))

        self.assertEqual([call[0] for call in calls], ["discover", "inspect", "send", "resume", "score", "archive", "cooldown"])


if __name__ == "__main__":
    unittest.main()
