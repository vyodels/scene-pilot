from __future__ import annotations

import asyncio
import inspect
from typing import Any

from scene_pilot.kernel.guard import run_preflight
from scene_pilot.plugins.host import PluginHost
from scene_pilot.runtime.limits import RoundLimits
from scene_pilot.runtime.models import CancellationToken, Deliberation, LLMResponse, LLMUsage, Message, Observation, ToolCall, ToolExecutionResult
from scene_pilot.runtime.providers import LLMProvider
from scene_pilot.runtime.tools import ToolRegistry


def deliberate(
    *,
    provider: LLMProvider,
    messages: list[Message],
    tool_registry: ToolRegistry,
    observation: Observation,
    plugin_host: PluginHost | None = None,
    limits: RoundLimits | None = None,
    cancel_token: CancellationToken | None = None,
    event_sink: Any | None = None,
) -> Deliberation:
    active_limits = limits or RoundLimits()
    history = list(messages)
    tool_results: list[ToolExecutionResult] = []
    tool_calls: list[ToolCall] = []
    pending_tool_calls: list[ToolCall] = []
    final_content = ""
    stop_reason = "stop"
    usage = LLMUsage()
    seed_tool_calls = list(observation.input.seed_tool_calls) if observation.input is not None else []
    if cancel_token is not None and cancel_token.is_cancelled():
        return Deliberation(
            messages=history,
            stop_reason="cancelled",
            usage=usage,
            metadata={"tool_result_count": 0, "cancelled": True, "pending_tool_calls": []},
        )

    if event_sink is not None:
        event_sink(
            "provider_started",
            {
                "message_count": len(history),
                "tool_count": len(tool_registry.tools),
            },
        )
    try:
        response = _response_for_round(
            provider,
            history,
            tool_registry,
            cancel_token=cancel_token,
            seed_tool_calls=seed_tool_calls,
        )
    except Exception as exc:
        if event_sink is not None:
            event_sink("provider_failed", {"error": str(exc)})
        raise
    usage = response.usage
    stop_reason = response.finish_reason
    tool_calls.extend(response.tool_calls)
    final_content = response.content
    if event_sink is not None:
        event_sink(
            "provider_completed",
            {
                "finish_reason": response.finish_reason,
                "tool_call_count": len(response.tool_calls),
                "has_content": bool(response.content),
            },
        )

    history.append(
        Message(
            role="assistant",
            content=response.content,
            metadata={"tool_calls": [call.to_provider_payload() for call in response.tool_calls]},
        )
    )
    if response.content and event_sink is not None:
        event_sink("llm_delta", {"delta": response.content})

    if cancel_token is not None and cancel_token.is_cancelled():
        stop_reason = "cancelled"
    else:
        for call in response.tool_calls[: active_limits.max_tool_roundtrips]:
            if event_sink is not None:
                event_sink("tool_call", {"id": call.id, "name": call.name, "arguments": dict(call.arguments or {})})
            if cancel_token is not None and cancel_token.is_cancelled():
                stop_reason = "cancelled"
                break
            seeded_confirmation = any(seed.id == call.id and seed.name == call.name for seed in seed_tool_calls)

            verdicts = run_preflight(call.name, call.arguments, observation, plugin_host=plugin_host)
            rejected = next((verdict for verdict in verdicts if not verdict.allowed), None)
            if rejected is not None:
                if rejected.severity == "waiting_human" and not seeded_confirmation:
                    pending_tool_calls.append(call)
                    stop_reason = "wait_human"
                    break
                history.append(
                    Message(role="tool", name=call.name, tool_call_id=call.id, content=rejected.reason or "blocked")
                )
                if event_sink is not None:
                    event_sink(
                        "tool_blocked",
                        {
                            "tool_name": call.name,
                            "reason": rejected.reason,
                            "severity": rejected.severity,
                        },
                    )
                continue

            result = asyncio.run(tool_registry.execute_async(call.name, call.arguments, cancel_token=cancel_token))
            tool_results.append(result)
            if event_sink is not None:
                event_sink(
                    "tool_result",
                    {
                        "tool_name": call.name,
                        "is_error": result.is_error,
                        "output": result.output,
                    },
                )
            history.append(
                Message(role="tool", name=call.name, tool_call_id=call.id, content=result.to_message_content())
            )
            if cancel_token is not None and cancel_token.is_cancelled():
                stop_reason = "cancelled"
                break

    return Deliberation(
        messages=history,
        tool_calls=tool_calls,
        tool_results=tool_results,
        final_content=final_content,
        stop_reason=stop_reason,
        usage=usage,
        metadata={
            "tool_result_count": len(tool_results),
            "cancelled": bool(cancel_token and cancel_token.cancelled),
            "pending_tool_calls": [call.to_provider_payload() for call in pending_tool_calls],
        },
    )


def _response_for_round(
    provider: LLMProvider,
    history: list[Message],
    tool_registry: ToolRegistry,
    *,
    cancel_token: CancellationToken | None,
    seed_tool_calls: list[ToolCall] | None,
) -> LLMResponse:
    if seed_tool_calls:
        return LLMResponse(tool_calls=list(seed_tool_calls), finish_reason="tool_calls")

    parameters = inspect.signature(provider.generate).parameters
    kwargs: dict[str, Any] = {"tools": tool_registry.describe()}
    if "cancel_token" in parameters:
        kwargs["cancel_token"] = cancel_token
    return provider.generate(history, **kwargs)
