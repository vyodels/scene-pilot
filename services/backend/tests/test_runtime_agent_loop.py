from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scene_pilot.runtime.agent_loop import AgentLoop, AgentLoopConfig
from scene_pilot.runtime.models import LLMResponse, ToolCall
from scene_pilot.runtime.providers import ScriptedProvider
from scene_pilot.runtime.tools import ToolDefinition, ToolRegistry


class AgentLoopTests(unittest.TestCase):
    def test_execution_contract_filters_tools_by_current_capability(self) -> None:
        captured_tools: list[str] = []

        class _InspectingProvider:
            provider_name = "inspecting"

            def generate(self, messages, *, tools=None, task=None, max_tokens=None, temperature=None):
                nonlocal captured_tools
                captured_tools = [item["function"]["name"] for item in list(tools or [])]
                return LLMResponse(
                    content="done",
                    tool_calls=[
                        ToolCall(
                            id="submit-browser",
                            name="submit_result",
                            arguments={"status": "pass", "data": {"summary": "browser step complete"}},
                        )
                    ],
                )

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="browser_only",
                description="Browser capability tool",
                parameters={"type": "object"},
                handler=lambda args: {"ok": True},
                metadata={"capabilities": ["browser"]},
            )
        )
        registry.register(
            ToolDefinition(
                name="api_only",
                description="API capability tool",
                parameters={"type": "object"},
                handler=lambda args: {"ok": True},
                metadata={"capabilities": ["api"]},
            )
        )
        registry.register(registry.build_result_submission_tool())
        loop = AgentLoop(provider=_InspectingProvider(), tools=registry)
        task = SimpleNamespace(task_type="runtime_execution", payload={"goal": "Inspect the browser scene"})

        result = loop.run(
            task,
            extra_context={
                "execution_contract": {
                    "execution_plan_id": "plan-1",
                    "steps": [
                        {"id": "assess_runtime_scene", "capability": "browser", "summary": "Inspect the browser scene."}
                    ],
                }
            },
        )

        self.assertTrue(result.success)
        self.assertIn("browser_only", captured_tools)
        self.assertIn("submit_result", captured_tools)
        self.assertNotIn("api_only", captured_tools)

    def test_tool_call_then_result_submission(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="use tool",
                    tool_calls=[ToolCall(id="1", name="echo", arguments={"value": "alpha"})],
                ),
                LLMResponse(
                    content="final",
                    result_data={"status": "passed", "score": 88},
                ),
            ],
        )
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="echo",
                description="Echo args",
                parameters={"type": "object"},
                handler=lambda args: {"echoed": args["value"]},
            )
        )
        loop = AgentLoop(provider=provider, tools=registry, config=AgentLoopConfig(max_turns=4, token_budget=100))
        task = SimpleNamespace(task_type="initial_screening", payload={"jd_criteria": "Python"})

        result = loop.run(task)

        self.assertTrue(result.success)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.data["status"], "pass")
        self.assertEqual(len(result.tool_outputs), 1)
        self.assertEqual(result.tool_outputs[0].output["echoed"], "alpha")

    def test_waiting_human_response(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[LLMResponse(content="need review", requires_human_input=True)],
        )
        registry = ToolRegistry()
        loop = AgentLoop(provider=provider, tools=registry)
        task = SimpleNamespace(task_type="initial_screening", payload={"jd_criteria": "Python"})

        result = loop.run(task)
        self.assertFalse(result.success)
        self.assertEqual(result.status, "waiting_human")

    def test_submit_result_tool_call_finishes_with_structured_data(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="submitting structured result",
                    tool_calls=[
                        ToolCall(
                            id="submit-1",
                            name="submit_result",
                            arguments={
                                "status": "pass",
                                "data": {"score": 91, "summary": "Strong signal"},
                            },
                        )
                    ],
                )
            ],
        )
        registry = ToolRegistry()
        registry.register(registry.build_result_submission_tool())
        loop = AgentLoop(provider=provider, tools=registry)
        task = SimpleNamespace(task_type="initial_screening", payload={"jd_criteria": "Python"})

        result = loop.run(task)

        self.assertTrue(result.success)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.data["status"], "pass")
        self.assertEqual(result.data["score"], 91)
        self.assertEqual(result.tool_outputs[0].output["payload"]["status"], "pass")

    def test_tool_call_history_preserves_assistant_tool_calls(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="use tool",
                    tool_calls=[ToolCall(id="echo-1", name="echo", arguments={"value": "alpha"})],
                ),
                LLMResponse(
                    content="final",
                    result_data={"status": "passed", "score": 88},
                ),
            ],
        )
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="echo",
                description="Echo args",
                parameters={"type": "object"},
                handler=lambda args: {"echoed": args["value"]},
            )
        )
        loop = AgentLoop(provider=provider, tools=registry, config=AgentLoopConfig(max_turns=4, token_budget=100))
        task = SimpleNamespace(task_type="initial_screening", payload={"jd_criteria": "Python"})

        result = loop.run(task)

        assistant_with_tool_call = next(message for message in result.messages if message.role == "assistant" and message.metadata.get("tool_calls"))
        self.assertEqual(assistant_with_tool_call.metadata["tool_calls"][0]["function"]["name"], "echo")
        tool_message = next(message for message in result.messages if message.role == "tool")
        self.assertEqual(tool_message.tool_call_id, "echo-1")

    def test_submit_result_flattens_nested_screening_result(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="submitting nested screening result",
                    tool_calls=[
                        ToolCall(
                            id="submit-2",
                            name="submit_result",
                            arguments={
                                "status": "completed",
                                "result": {
                                    "screening_decision": "pass",
                                    "summary": "Strong frontend signal",
                                },
                            },
                        )
                    ],
                )
            ],
        )
        registry = ToolRegistry()
        registry.register(registry.build_result_submission_tool())
        loop = AgentLoop(provider=provider, tools=registry)
        task = SimpleNamespace(task_type="initial_screening", payload={"jd_criteria": "Python"})

        result = loop.run(task)

        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "pass")
        self.assertEqual(result.data["screening_decision"], "pass")
        self.assertEqual(result.data["summary"], "Strong frontend signal")

    def test_submit_result_promotes_decision_to_status(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="submitting decision result",
                    tool_calls=[
                        ToolCall(
                            id="submit-3",
                            name="submit_result",
                            arguments={
                                "status": "completed",
                                "result": {
                                    "decision": "pass",
                                    "summary": "Advance candidate",
                                },
                            },
                        )
                    ],
                )
            ],
        )
        registry = ToolRegistry()
        registry.register(registry.build_result_submission_tool())
        loop = AgentLoop(provider=provider, tools=registry)
        task = SimpleNamespace(task_type="initial_screening", payload={"jd_criteria": "Python"})

        result = loop.run(task)

        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "pass")
        self.assertEqual(result.data["decision"], "pass")

    def test_submit_result_promotes_nested_screening_result_decision(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="submitting nested decision result",
                    tool_calls=[
                        ToolCall(
                            id="submit-4",
                            name="submit_result",
                            arguments={
                                "status": "completed",
                                "result": {
                                    "screening_result": {
                                        "decision": "pass",
                                        "summary": "Advance candidate",
                                    }
                                },
                            },
                        )
                    ],
                )
            ],
        )
        registry = ToolRegistry()
        registry.register(registry.build_result_submission_tool())
        loop = AgentLoop(provider=provider, tools=registry)
        task = SimpleNamespace(task_type="initial_screening", payload={"jd_criteria": "Python"})

        result = loop.run(task)

        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "pass")
        self.assertEqual(result.data["screening_result"]["decision"], "pass")

    def test_submit_result_promotes_top_level_screening_result_decision(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="submitting provider-shaped result",
                    tool_calls=[
                        ToolCall(
                            id="submit-5",
                            name="submit_result",
                            arguments={
                                "status": "completed",
                                "screening_result": {
                                    "decision": "pass",
                                    "summary": "Advance candidate",
                                },
                            },
                        )
                    ],
                )
            ],
        )
        registry = ToolRegistry()
        registry.register(registry.build_result_submission_tool())
        loop = AgentLoop(provider=provider, tools=registry)
        task = SimpleNamespace(task_type="initial_screening", payload={"jd_criteria": "Python"})

        result = loop.run(task)

        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "pass")
        self.assertEqual(result.data["execution_status"], "completed")
        self.assertEqual(result.data["screening_result"]["decision"], "pass")

    def test_submit_result_promotes_top_level_screening_result_decision(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="submitting top-level screening result",
                    tool_calls=[
                        ToolCall(
                            id="submit-5",
                            name="submit_result",
                            arguments={
                                "status": "completed",
                                "screening_result": {
                                    "decision": "pass",
                                    "summary": "Advance candidate",
                                },
                            },
                        )
                    ],
                )
            ],
        )
        registry = ToolRegistry()
        registry.register(registry.build_result_submission_tool())
        loop = AgentLoop(provider=provider, tools=registry)
        task = SimpleNamespace(task_type="initial_screening", payload={"jd_criteria": "Python"})

        result = loop.run(task)

        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "pass")
        self.assertEqual(result.data["screening_result"]["decision"], "pass")

    def test_direct_result_data_promotes_nested_screening_result_decision(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="direct result payload",
                    result_data={
                        "status": "completed",
                        "screening_result": {
                            "decision": "pass",
                            "summary": "Advance candidate",
                        },
                    },
                )
            ],
        )
        loop = AgentLoop(provider=provider, tools=ToolRegistry())
        task = SimpleNamespace(task_type="initial_screening", payload={"jd_criteria": "Python"})

        result = loop.run(task)

        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "pass")
        self.assertEqual(result.data["execution_status"], "completed")
        self.assertEqual(result.data["screening_result"]["decision"], "pass")

    def test_runtime_execution_trace_requests_replan_from_control_tools(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="inspect the listing surface first",
                    tool_calls=[
                        ToolCall(
                            id="obs-1",
                            name="record_observation",
                            arguments={
                                "step_id": "assess_scene",
                                "capability": "browser",
                                "summary": "The scene is a noisy listing surface with drifting selectors.",
                                "signals": ["listing_surface", "selector_drift"],
                                "scene_update": {"page_type": "listing_surface", "auth_state": "ready"},
                            },
                        ),
                        ToolCall(
                            id="progress-1",
                            name="advance_plan_step",
                            arguments={
                                "step_id": "assess_scene",
                                "capability": "browser",
                                "status": "completed",
                                "summary": "The initial scene assessment is complete.",
                            },
                        ),
                    ],
                ),
                LLMResponse(
                    content="the current target is drifting, request a replan",
                    tool_calls=[
                        ToolCall(
                            id="replan-1",
                            name="request_replan",
                            arguments={
                                "step_id": "capture_detail",
                                "reason": "The current detail capture step no longer matches the live scene.",
                                "preferred_capabilities": ["browser", "document"],
                                "suggested_steps": [
                                    {"id": "refresh_scene", "capability": "browser"},
                                    {"id": "capture_new_detail", "capability": "document"},
                                ],
                                "scene_update": {"page_type": "detail_surface", "volatility": "high"},
                            },
                        )
                    ],
                ),
            ],
        )
        registry = ToolRegistry()
        registry.register(registry.build_observation_tool())
        registry.register(registry.build_plan_progress_tool())
        registry.register(registry.build_replan_request_tool())
        registry.register(registry.build_human_checkpoint_tool())
        registry.register(registry.build_result_submission_tool())
        loop = AgentLoop(provider=provider, tools=registry)
        task = SimpleNamespace(task_type="runtime_execution", payload={"goal": "Inspect and adapt to the live browser scene."})

        result = loop.run(
            task,
            extra_context={
                "execution_contract": {
                    "execution_plan_id": "plan-runtime-1",
                    "scene_type": "listing_surface",
                    "planner_posture": "adapt",
                    "steps": [
                        {
                            "id": "assess_scene",
                            "capability": "browser",
                            "summary": "Assess the scene before taking the next action.",
                            "preferred_tools": ["record_observation", "advance_plan_step", "request_replan"],
                        },
                        {
                            "id": "capture_detail",
                            "capability": "document",
                            "summary": "Capture the target detail if the scene still matches the plan.",
                            "preferred_tools": ["record_observation", "request_replan", "submit_result"],
                        },
                    ],
                }
            },
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "replan_requested")
        trace = result.metadata["executor_trace"]
        self.assertEqual(len(trace["observations"]), 1)
        self.assertEqual(len(trace["actions"]), 1)
        self.assertEqual(len(trace["replan_requests"]), 1)
        self.assertEqual(trace["current_step_id"], "capture_detail")
        self.assertEqual(result.metadata["executor_control"]["kind"], "replan_requested")
        self.assertEqual(result.metadata["pending_step_ids"], ["capture_detail"])

    def test_runtime_execution_trace_waits_for_human_checkpoint(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="checkpoint required before proceeding",
                    tool_calls=[
                        ToolCall(
                            id="checkpoint-1",
                            name="request_human_checkpoint",
                            arguments={
                                "step_id": "review_write_risk",
                                "reason": "The next action would write into a downstream system.",
                                "review_kind": "approval",
                                "summary": "Confirm the downstream write before proceeding.",
                                "payload": {"surface": "submission_scene"},
                            },
                        )
                    ],
                )
            ],
        )
        registry = ToolRegistry()
        registry.register(registry.build_observation_tool())
        registry.register(registry.build_plan_progress_tool())
        registry.register(registry.build_replan_request_tool())
        registry.register(registry.build_human_checkpoint_tool())
        registry.register(registry.build_result_submission_tool())
        loop = AgentLoop(provider=provider, tools=registry)
        task = SimpleNamespace(task_type="runtime_execution", payload={"goal": "Complete a gated downstream write."})

        result = loop.run(
            task,
            extra_context={
                "execution_contract": {
                    "execution_plan_id": "plan-runtime-approval",
                    "scene_type": "submission_scene",
                    "steps": [
                        {
                            "id": "review_write_risk",
                            "capability": "approval",
                            "summary": "Pause for human review before the write step.",
                            "preferred_tools": ["request_human_checkpoint", "advance_plan_step", "submit_result"],
                        }
                    ],
                }
            },
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "waiting_human")
        self.assertEqual(result.metadata["human_checkpoint_count"], 1)
        self.assertEqual(result.metadata["executor_control"]["kind"], "waiting_human")
        self.assertEqual(result.metadata["pending_step_ids"], ["review_write_risk"])

    def test_runtime_execution_auto_submits_when_step_completed_with_observation(self) -> None:
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content="complete current step",
                    tool_calls=[
                        ToolCall(id="discover-1", name="browser_snapshot", arguments={}),
                        ToolCall(
                            id="obs-1",
                            name="record_observation",
                            arguments={
                                "step_id": "assess_runtime_scene",
                                "capability": "browser",
                                "summary": "Candidate listing verified.",
                                "signals": ["listing_surface"],
                            },
                        ),
                        ToolCall(
                            id="step-1",
                            name="advance_plan_step",
                            arguments={
                                "step_id": "assess_runtime_scene",
                                "status": "completed",
                                "summary": "Scene validated.",
                            },
                        ),
                    ],
                )
            ],
        )
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="browser_snapshot",
                description="Read browser snapshot",
                parameters={"type": "object"},
                handler=lambda args: [
                    {
                        "candidate_id": "cand-1",
                        "name": "王利霖",
                        "profile_or_resume_evidence": {"summary": "embedded profile card"},
                        "resume_artifact_status": "profile_evidence_available",
                        "upload_status": "not_started",
                    }
                ],
                metadata={"capabilities": ["browser", "search"]},
            )
        )
        registry.register(registry.build_observation_tool())
        registry.register(registry.build_plan_progress_tool())
        loop = AgentLoop(provider=provider, tools=registry)
        task = SimpleNamespace(task_type="runtime_execution", payload={"goal": "Inspect the browser scene"})

        result = loop.run(
            task,
            extra_context={
                "execution_contract": {
                    "plan_name": "Runtime plan",
                    "scene_type": "listing_surface",
                    "steps": [
                        {"id": "assess_runtime_scene", "capability": "browser", "summary": "Inspect the scene."},
                        {"id": "next_step", "capability": "analyze", "summary": "Summarize the scene."},
                    ],
                }
            },
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.data["status"], "step_completed")
        self.assertEqual(result.data["step_id"], "assess_runtime_scene")
        self.assertEqual(result.data["next_step"], "next_step")
        self.assertEqual(result.data["candidate_name_or_identifier"], "cand-1 / 王利霖")


if __name__ == "__main__":
    unittest.main()
