from __future__ import annotations

from recruit_agent.agent_runtime.types import LLMInvocationResult, LLMRequest
from recruit_agent.agent_runtime.kernel import AgentKernel
from recruit_agent.plugins.host import PluginHost
from recruit_agent.runtime.limits import RoundLimits
from recruit_agent.agent_runtime.models import GoalRef, GuardVerdict, InputEnvelope, LLMResponse, Observation, ToolCall
from agent_runtime.fixtures import ScriptedProvider
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

        def invoke(self, request: LLMRequest) -> LLMInvocationResult:
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


def test_run_round_merges_goal_url_into_delegate_scene_context_contract() -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="scene-1",
                        name="delegate_scene_context",
                        arguments={
                            "instruction": "执行当前招聘目标，但模型漏掉了 browser_target。",
                            "preferred_capabilities": ["browser", "computer"],
                        },
                    )
                ],
                finish_reason="tool_calls",
            )
        ],
    )
    captured_arguments: list[dict[str, object]] = []
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="delegate_scene_context",
            description="Delegate scene context.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            handler=lambda arguments: captured_arguments.append(dict(arguments)) or {"status": "completed"},
            metadata={"capabilities": ["scene", "scene_delegate"]},
        )
    )
    kernel = AgentKernel(provider=provider, tool_registry=tools, plugin_host=PluginHost())

    outcome = kernel.run_round(
        goal=GoalRef(
            goal_id="goal-1",
            scope_kind="global",
            scope_ref="workspace",
            goal_text="在模拟招聘网站 http://127.0.0.1:64932/jobs 完成候选人发现与简历下载。",
            constraints={"goal_kind": "candidate_discovery", "context_hints": {}},
        ),
        observation=Observation(scope_kind="global", scope_ref="workspace"),
        limits=RoundLimits(),
    )

    assert outcome.status == "continue"
    assert captured_arguments
    scene_arguments = captured_arguments[0]
    expected_target = {"host": "127.0.0.1:64932", "url": "http://127.0.0.1:64932/jobs"}
    assert scene_arguments["browser_target"] == expected_target
    assert scene_arguments["environment_requirements"]["browser_target"] == expected_target
    assert scene_arguments["context"]["browser_target"] == expected_target


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


def test_run_round_marks_blocked_status_prefix_as_escalate() -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                content=(
                    '{"status":"blocked_missing_artifact","local_artifact":{"path":null},'
                    '"blocking_reason":"download record did not produce a local path"}'
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


def test_run_round_marks_failed_status_prefix_as_error() -> None:
    provider = ScriptedProvider(
        provider_name="scripted",
        responses=[
            LLMResponse(
                content=(
                    '{"status":"failed_no_verified_local_artifact",'
                    '"failure_reason":"download record did not produce a verified local path"}'
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

    assert outcome.status == "error"
    assert outcome.gate_signal == "escalate"
