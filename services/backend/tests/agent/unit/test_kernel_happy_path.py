from __future__ import annotations

from dataclasses import dataclass
import json

from recruit_agent.agent_runtime.kernel import AgentKernel
from recruit_agent.plugins.host import PluginHost
from recruit_agent.runtime.limits import RoundLimits
from recruit_agent.agent_runtime.models import GoalRef, InputEnvelope, LLMResponse, Observation, ToolCall
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.runtime.tools import ToolDefinition, ToolRegistry


@dataclass
class StubMemoryService:
    def read(self, **_: object) -> list[dict[str, object]]:
        return [{"summary": "Candidate prefers async updates."}]


def test_kernel_run_round_supports_driver_managed_multi_round_flow() -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="tool-1", name="core.echo", arguments={"value": "hello"})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="completed", finish_reason="stop"),
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="core.echo",
            description="Echo input.",
            parameters={"type": "object"},
            handler=lambda arguments: {"echo": arguments["value"]},
            category="core",
            external_target=False,
            resource_target_kind="memory",
        )
    )
    plugin_host = PluginHost()
    plugin_host.register_persona_fragment("demo", "style", "Keep outputs concise.")

    async def _enricher(observation: Observation) -> dict[str, object]:
        return {"candidate_ready": observation.scope_ref}

    plugin_host.register_observation_enricher("demo", _enricher)

    kernel = AgentKernel(
        provider=provider,
        tool_registry=tools,
        plugin_host=plugin_host,
        memory_service=StubMemoryService(),
    )
    goal = GoalRef(goal_id="goal-1", scope_kind="candidate", scope_ref="candidate-1", goal_text="Follow up candidate")
    observation = Observation(
        world_snapshot={"stage": "new"},
        scope_ref="candidate-1",
        scope_kind="candidate",
        recent_events=[],
        available_tools=["core.echo"],
        available_skills=[],
        available_mcps=[],
        hash="obs-1",
    )

    first = kernel.run_round(goal=goal, observation=observation, limits=RoundLimits())
    second = kernel.run_round(
        goal=goal,
        observation=Observation(
            world_snapshot={"stage": "new"},
            scope_ref="candidate-1",
            scope_kind="candidate",
            recent_events=[],
            available_tools=["core.echo"],
            available_skills=[],
            available_mcps=[],
            hash="obs-1",
            input=InputEnvelope(history_messages=list(first.metadata["history_messages"])),
        ),
        limits=RoundLimits(),
    )

    assert first.status == "continue"
    assert first.gate_signal == "continue"
    assert first.tool_results[0].output == {"echo": "hello"}
    assert second.status == "complete"
    assert second.gate_signal == "goal_done"
    assert second.final_output == "completed"
    assert second.metadata["assembled_messages"][0].role == "system"


def test_kernel_run_round_history_keeps_raw_tool_result_payloads() -> None:
    snapshot_output = {
        "display_label": "JD Detail",
        "environment_kind": "job_detail",
        "resource_locator": "https://example.test/jobs/1",
        "observed_entities": [{"kind": "candidate", "name": "Alice"}],
        "action_hints": [{"kind": "button", "label": "立即沟通"}],
        "runtime_metadata": {"viewport": {"width": 1440, "height": 900}},
    }
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                tool_calls=[ToolCall(id="tool-1", name="browser_snapshot", arguments={"capture": "jd-detail"})],
                finish_reason="tool_calls",
            )
        ],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Capture the current browser snapshot.",
            parameters={"type": "object"},
            handler=lambda arguments: snapshot_output,
        )
    )
    kernel = AgentKernel(provider=provider, tool_registry=tools, plugin_host=PluginHost())

    outcome = kernel.run_round(
        goal=GoalRef(goal_id="goal-1", scope_kind="conversation", scope_ref="conv-1"),
        observation=Observation(scope_kind="conversation", scope_ref="conv-1"),
        limits=RoundLimits(),
    )

    history_messages = outcome.metadata["history_messages"]

    assert outcome.tool_results[0].output == snapshot_output
    assert history_messages[-1].role == "tool"
    assert history_messages[-1].name == "browser_snapshot"
    assert history_messages[-1].content == json.dumps(snapshot_output, ensure_ascii=False, sort_keys=True, default=str)


def test_kernel_run_round_preserves_structured_result_data() -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                content="scene completed",
                result_data={
                    "status": "completed",
                    "summary": "scene completed",
                    "artifact": {"path": "/tmp/resume.pdf", "format": "pdf"},
                },
                finish_reason="stop",
            )
        ],
    )
    kernel = AgentKernel(provider=provider, tool_registry=ToolRegistry(), plugin_host=PluginHost())

    outcome = kernel.run_round(
        goal=GoalRef(goal_id="goal-1", scope_kind="conversation", scope_ref="conv-1"),
        observation=Observation(scope_kind="conversation", scope_ref="conv-1"),
        limits=RoundLimits(),
    )

    assert outcome.status == "complete"
    assert outcome.gate_signal == "goal_done"
    assert outcome.final_output == "scene completed"
    assert outcome.result_data == {
        "status": "completed",
        "summary": "scene completed",
        "artifact": {"path": "/tmp/resume.pdf", "format": "pdf"},
    }
