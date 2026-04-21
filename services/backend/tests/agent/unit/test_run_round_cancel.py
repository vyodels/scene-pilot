from __future__ import annotations

from recruit_agent.kernel.kernel import AgentKernel
from recruit_agent.plugins.host import PluginHost
from recruit_agent.runtime.limits import RoundLimits
from recruit_agent.runtime.models import CancellationToken, GoalRef, LLMResponse, Observation, ToolCall
from recruit_agent.runtime.tools import ToolDefinition, ToolRegistry


def test_run_round_returns_cancelled_before_provider_is_called() -> None:
    class CountingProvider:
        provider_name = "counting"

        def __init__(self) -> None:
            self.calls = 0

        def generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.calls += 1
            return LLMResponse(content="should not happen")

    provider = CountingProvider()
    token = CancellationToken()
    token.cancel("operator_cancelled")
    kernel = AgentKernel(provider=provider, tool_registry=ToolRegistry(), plugin_host=PluginHost())

    outcome = kernel.run_round(
        goal=GoalRef(goal_id="goal-1", scope_kind="candidate", scope_ref="cand-1"),
        observation=Observation(scope_kind="candidate", scope_ref="cand-1"),
        limits=RoundLimits(),
        cancel_token=token,
    )

    assert provider.calls == 0
    assert outcome.status == "cancelled"
    assert outcome.gate_signal == "paused"
    assert outcome.memory_updates == []


def test_run_round_stops_between_tool_calls_when_cancelled() -> None:
    provider = type(
        "TwoToolProvider",
        (),
        {
            "provider_name": "two-tools",
            "generate": lambda self, *args, **kwargs: LLMResponse(
                tool_calls=[
                    ToolCall(id="tool-1", name="tool.first", arguments={}),
                    ToolCall(id="tool-2", name="tool.second", arguments={}),
                ],
                finish_reason="tool_calls",
            ),
        },
    )()
    token = CancellationToken()
    calls: list[str] = []
    tools = ToolRegistry()

    def _first(arguments: dict[str, object], *, cancel_token: CancellationToken | None = None) -> dict[str, object]:
        calls.append("first")
        if cancel_token is not None:
            cancel_token.cancel("tool_requested_cancel")
        return {"ok": True}

    def _second(arguments: dict[str, object], *, cancel_token: CancellationToken | None = None) -> dict[str, object]:
        calls.append("second")
        return {"ok": True}

    tools.register(ToolDefinition(name="tool.first", description="first", parameters={"type": "object"}, handler=_first))
    tools.register(ToolDefinition(name="tool.second", description="second", parameters={"type": "object"}, handler=_second))
    kernel = AgentKernel(provider=provider, tool_registry=tools, plugin_host=PluginHost())

    outcome = kernel.run_round(
        goal=GoalRef(goal_id="goal-1", scope_kind="candidate", scope_ref="cand-1"),
        observation=Observation(scope_kind="candidate", scope_ref="cand-1"),
        limits=RoundLimits(),
        cancel_token=token,
    )

    assert calls == ["first"]
    assert outcome.status == "cancelled"
    assert outcome.gate_signal == "paused"
    assert len(outcome.tool_results) == 1
    assert outcome.memory_updates == []
