from __future__ import annotations

import asyncio

from scene_pilot.kernel.guard import run_preflight
from scene_pilot.plugins.host import PluginHost
from scene_pilot.runtime.limits import RuntimeLimits
from scene_pilot.runtime.models import Deliberation, LLMUsage, Message, Observation, ToolExecutionResult
from scene_pilot.runtime.providers import LLMProvider
from scene_pilot.runtime.tools import ToolRegistry


def deliberate(
    *,
    provider: LLMProvider,
    messages: list[Message],
    tool_registry: ToolRegistry,
    observation: Observation,
    plugin_host: PluginHost | None = None,
    limits: RuntimeLimits | None = None,
) -> Deliberation:
    active_limits = limits or RuntimeLimits()
    history = list(messages)
    tool_results: list[ToolExecutionResult] = []
    final_content = ""
    stop_reason = "stop"
    usage = LLMUsage()

    for _turn in range(active_limits.max_turns):
        response = provider.generate(history, tools=tool_registry.describe())
        usage = response.usage
        stop_reason = response.finish_reason
        history.append(
            Message(
                role="assistant",
                content=response.content,
                metadata={"tool_calls": [call.to_provider_payload() for call in response.tool_calls]},
            )
        )
        if not response.tool_calls:
            final_content = response.content
            break

        for call in response.tool_calls[: active_limits.max_tool_roundtrips]:
            verdicts = run_preflight(call.name, call.arguments, observation, plugin_host=plugin_host)
            rejected = next((verdict for verdict in verdicts if not verdict.allowed), None)
            if rejected is not None:
                history.append(
                    Message(role="tool", name=call.name, tool_call_id=call.id, content=rejected.reason or "blocked")
                )
                continue
            result = asyncio.run(tool_registry.execute_async(call.name, call.arguments))
            tool_results.append(result)
            history.append(
                Message(role="tool", name=call.name, tool_call_id=call.id, content=result.to_message_content())
            )

    return Deliberation(
        messages=history,
        tool_results=tool_results,
        final_content=final_content,
        stop_reason=stop_reason,
        usage=usage,
        metadata={"tool_result_count": len(tool_results)},
    )
