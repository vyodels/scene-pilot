from __future__ import annotations

from dataclasses import dataclass

from scene_pilot.kernel.kernel import AgentKernel
from scene_pilot.plugins.host import PluginHost
from scene_pilot.runtime.models import GoalRef, LLMResponse, Observation, ToolCall
from scene_pilot.runtime.providers import ScriptedProvider
from scene_pilot.runtime.tools import ToolDefinition, ToolRegistry


@dataclass
class StubMemoryService:
    def read(self, **_: object) -> list[dict[str, object]]:
        return [{"summary": "Candidate prefers async updates."}]


def test_kernel_happy_path_executes_tool_loop_and_returns_complete_outcome() -> None:
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

    outcome = kernel.run_tick(goal, observation)

    assert outcome.status == "complete"
    assert outcome.final_output == "completed"
    assert outcome.metadata["tool_results"][0].output == {"echo": "hello"}
    assert outcome.metadata["assembled_messages"][0].role == "system"
