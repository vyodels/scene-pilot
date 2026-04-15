from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from scene_pilot.core.settings import AppSettings
from scene_pilot.scheduler.queue import TaskEnvelope
from scene_pilot.services.agent import AgentControlService


class _DummyRuntimeService:
    def __init__(self) -> None:
        self.compile_task_calls = []
        self.compile_plan_calls = []

    def compile_task(self, payload):
        self.compile_task_calls.append(payload)
        return SimpleNamespace(
            task_spec=SimpleNamespace(
                id="task-spec-1",
                title="下载候选人附件简历",
                compiled_payload={
                    "compiler": "llm_structured",
                    "step_outline": [
                        {"id": "inspect_live_scene", "capability": "browser"},
                        {"id": "open_or_download_resume", "capability": "browser"},
                        {"id": "verify_local_artifact", "capability": "document"},
                        {"id": "summarize_result", "capability": "document"},
                    ],
                },
            ),
            compiler_notes=["semantic compile ok"],
        )

    def compile_plan(self, payload):
        self.compile_plan_calls.append(payload)
        return SimpleNamespace(id="plan-1")


def test_goal_intake_uses_runtime_task_compiler_and_compiled_step_outline(tmp_path):
    runtime_service = _DummyRuntimeService()
    service = AgentControlService(
        scheduler=SimpleNamespace(),
        settings=AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'recruit-agent.db'}",
        ),
        session_factory=lambda: nullcontext(object()),
        runtime_service_factory=lambda session: runtime_service,
    )
    task = TaskEnvelope(
        task_id="goal-intake-1",
        task_type="goal_intake",
        payload={
            "goal_id": "goal-1",
            "goal_text": "从当前 zhipin 页面下载 1 份附件简历 PDF 到本地。",
            "goal_kind": "recruiting",
            "success_criteria": {
                "minimum_candidates": 1,
                "requires_resume_or_profile": True,
                "requires_local_resume_file": True,
                "required_resume_extensions": [".pdf"],
            },
            "run_preferences": {"initial_stage": "resume_collection"},
        },
        metadata={
            "adaptive_stage": "goal_intake",
            "requested_by": "desktop-user",
            "goal_spec_id": "goal-1",
        },
    )

    result = service._run_goal_intake(task)

    assert result is not None
    assert result.success is True
    assert runtime_service.compile_task_calls
    assert runtime_service.compile_plan_calls

    compile_request = runtime_service.compile_task_calls[0]
    assert compile_request.auto_plan is False
    assert compile_request.constraints["follow_up_stage"] == "resume_collection"
    assert compile_request.success_criteria["requires_local_resume_file"] is True

    compile_plan_request = runtime_service.compile_plan_calls[0]
    assert compile_plan_request.steps == []
    assert compile_plan_request.runtime_metadata["compiler"] == "llm_structured"
