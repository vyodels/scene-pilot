from __future__ import annotations

from recruit_agent.kernel.kernel import AgentKernel
from recruit_agent.plugins.host import PluginHost
from recruit_agent.runtime.limits import RoundLimits
from recruit_agent.runtime.models import GoalRef, GuardVerdict, InputEnvelope, LLMResponse, Observation, ToolCall
from recruit_agent.runtime.providers import ScriptedProvider
from recruit_agent.runtime.tools import ToolDefinition, ToolRegistry


def test_run_round_waits_for_human_when_guard_blocks_external_tool() -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[LLMResponse(tool_calls=[ToolCall(id="tool-1", name="outbound.send", arguments={"text": "hello"})], finish_reason="tool_calls")],
    )
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="outbound.send",
            description="Send a message.",
            parameters={"type": "object"},
            handler=lambda arguments: {"sent": arguments["text"]},
            external_target=True,
        )
    )
    plugin_host = PluginHost()
    plugin_host.register_guard_check(
        "test-wait-human",
        lambda tool_name, arguments, observation: GuardVerdict(
            allowed=False,
            reason="pending_confirmation",
            severity="waiting_human",
        )
        if tool_name == "outbound.send"
        else GuardVerdict(allowed=True),
    )
    kernel = AgentKernel(provider=provider, tool_registry=tools, plugin_host=plugin_host)

    outcome = kernel.run_round(
        goal=GoalRef(goal_id="goal-1", scope_kind="conversation", scope_ref="conv-1"),
        observation=Observation(scope_kind="conversation", scope_ref="conv-1"),
        limits=RoundLimits(),
    )

    assert outcome.status == "wait_human"
    assert outcome.gate_signal == "wait_human"
    assert outcome.metadata["pending_tool_calls"][0]["function"]["name"] == "outbound.send"


def test_run_round_uses_seed_tool_calls_without_calling_provider() -> None:
    class NeverCalledProvider:
        provider_name = "never-called"

        def generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("provider should not be called when seed_tool_calls are present")

    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="core.echo",
            description="Echo input.",
            parameters={"type": "object"},
            handler=lambda arguments: {"echo": arguments["value"]},
        )
    )
    kernel = AgentKernel(provider=NeverCalledProvider(), tool_registry=tools, plugin_host=PluginHost())

    outcome = kernel.run_round(
        goal=GoalRef(goal_id="goal-1", scope_kind="conversation", scope_ref="conv-1"),
        observation=Observation(
            scope_kind="conversation",
            scope_ref="conv-1",
            input=InputEnvelope(seed_tool_calls=[ToolCall(id="seed-1", name="core.echo", arguments={"value": "hello"})]),
        ),
        limits=RoundLimits(),
    )

    assert outcome.status == "continue"
    assert outcome.gate_signal == "continue"
    assert outcome.tool_results[0].output == {"echo": "hello"}


def test_run_round_marks_structured_blocked_final_result_as_escalate() -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                content=(
                    '{"status":"blocked","created":0,"updated":0,"skipped":0,"blocked":1,'
                    '"unfinished_reason":"browser_connection_unavailable"}'
                )
            )
        ],
    )
    kernel = AgentKernel(provider=provider, tool_registry=ToolRegistry(), plugin_host=PluginHost())

    outcome = kernel.run_round(
        goal=GoalRef(goal_id="goal-1", scope_kind="conversation", scope_ref="conv-1"),
        observation=Observation(scope_kind="conversation", scope_ref="conv-1"),
        limits=RoundLimits(),
    )

    assert outcome.status == "escalate"
    assert outcome.gate_signal == "escalate"
    assert outcome.final_output is not None
