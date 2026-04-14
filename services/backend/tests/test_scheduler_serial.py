from __future__ import annotations

import sys
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.runtime.models import AgentResult
from scene_pilot.scheduler.queue import InMemoryQueue, TaskEnvelope
from scene_pilot.scheduler.scheduler import SerialScheduler


class SerialSchedulerTests(unittest.TestCase):
    def test_runs_tasks_in_priority_order(self) -> None:
        processed: list[str] = []

        def runner(task: TaskEnvelope) -> AgentResult:
            processed.append(task.task_id)
            return AgentResult(success=True, status="completed", data={"task_id": task.task_id})

        scheduler = SerialScheduler(queue=InMemoryQueue(), runner=runner)
        scheduler.submit(TaskEnvelope(task_id="low", task_type="screen", priority=1))
        scheduler.submit(TaskEnvelope(task_id="high", task_type="screen", priority=10))

        outcomes = scheduler.run_until_empty()

        self.assertEqual(processed, ["high", "low"])
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].task.task_id, "high")
        self.assertEqual(outcomes[1].task.task_id, "low")

    def test_follow_up_factory_enqueues_new_task(self) -> None:
        def runner(task: TaskEnvelope) -> AgentResult:
            return AgentResult(success=True, status="completed", data={"task_id": task.task_id})

        def follow_up(task: TaskEnvelope, result: AgentResult):
            yield TaskEnvelope(task_id=f"{task.task_id}-next", task_type="follow_up", priority=2)

        scheduler = SerialScheduler(queue=InMemoryQueue(), runner=runner, follow_up_factory=follow_up)
        scheduler.submit(TaskEnvelope(task_id="root", task_type="discover", priority=5))

        first = scheduler.run_once()
        self.assertEqual(first.enqueued_follow_ups, 1)
        self.assertEqual(scheduler.queue.peek().task_id, "root-next")


if __name__ == "__main__":
    unittest.main()
