from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import inspect
from typing import Any

from recruit_station.agent_runtime.engine import InteractionEngine, InteractionEngineConfig
from recruit_station.agent_runtime.transcript import Transcript
from recruit_station.agent_runtime.types import InteractionOutput, LLMMessage, LLMProvider, ToolCall, ToolResult, TurnContext
from recruit_station.capabilities.tools import ToolRegistry


@dataclass(frozen=True, slots=True)
class AgentTurnStatusDefaults:
    completed_status: str
    completed_gate_signal: str | None = None
    failed_status: str = "failed"
    failed_gate_signal: str | None = "escalate"
    interrupted_status: str = "cancelled"
    interrupted_gate_signal: str | None = "paused"
    permission_status: str = "waiting_human"
    permission_gate_signal: str | None = "wait_human"


@dataclass(frozen=True, slots=True)
class AgentEngineResult:
    status: str
    gate_signal: str | None
    final_output: str
    final_result_data: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    engine_output_count: int
    last_seq: int
    continuation_attempts: int
    engine: InteractionEngine


def run_agent_turn(
    *,
    provider: LLMProvider,
    tool_registry: ToolRegistry,
    agent_definition_id: str | None,
    conversation_id: str,
    initial_messages: list[LLMMessage],
    turn_input: str,
    max_llm_invocations: int,
    system_prompt: str | None = None,
    max_history_messages: int | None = None,
    max_context_chars: int | None = None,
    compaction_summary_max_chars: int = 2000,
    initial_seq: int = 1,
    transcript: Transcript | None = None,
    existing_engine: InteractionEngine | None = None,
    resolve_permission: bool = False,
    output_sink: Callable[[InteractionOutput], None] | None = None,
    engine_sink: Callable[[InteractionEngine], None] | None = None,
    structured_status_resolver: Callable[[Any], tuple[str, str] | None] | None = None,
    final_output_status_resolver: Callable[[str], tuple[str, str] | None] | None = None,
    final_output_continuation_resolver: Callable[[str, list[dict[str, Any]], list[dict[str, Any]], int], str | None] | None = None,
    status_defaults: AgentTurnStatusDefaults | None = None,
    include_tool_result_metadata: bool = False,
    runtime: dict[str, Any] | None = None,
    pending_user_input_after_next_tool_call_provider: Callable[
        [TurnContext, ToolCall, ToolResult],
        list[LLMMessage],
    ] | None = None,
) -> AgentEngineResult:
    defaults = status_defaults or AgentTurnStatusDefaults(completed_status="completed")
    normalized_system_prompt, normalized_initial_messages = _extract_system_prompt(
        initial_messages,
        explicit_system_prompt=system_prompt,
    )
    engine_initial_messages = [] if resolve_permission and transcript is not None else normalized_initial_messages
    engine = existing_engine or InteractionEngine(
        InteractionEngineConfig(
            conversation_id=conversation_id,
            provider=provider,
            tools=scoped_tool_registry(tool_registry, agent_definition_id).to_agent_runtime_tools(),
            transcript=transcript,
            initial_messages=engine_initial_messages,
            system_prompt=normalized_system_prompt,
            max_llm_invocations=max_llm_invocations,
            max_history_messages=max_history_messages,
            max_context_chars=max_context_chars,
            compaction_summary_max_chars=compaction_summary_max_chars,
            initial_seq=initial_seq,
            runtime=dict(runtime or {}),
            pending_user_input_after_next_tool_call_provider=pending_user_input_after_next_tool_call_provider,
        )
    )
    if engine_sink is not None:
        engine_sink(engine)

    output_iter: Iterable[InteractionOutput]
    final_output = ""
    final_result_data: dict[str, Any] = {}
    status = defaults.completed_status
    gate_signal = defaults.completed_gate_signal
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    pending_tool_calls: list[dict[str, Any]] = []
    engine_output_count = 0
    last_seq = initial_seq - 1
    continuation_attempt = 0
    next_turn_input = turn_input
    resolve_permission_next = resolve_permission

    while True:
        if resolve_permission_next:
            output_iter = engine.resolvePermission(approved=True)
        else:
            output_iter = engine.submitMessage(next_turn_input)
        resolve_permission_next = False

        turn_start_tool_call_count = len(tool_calls)
        turn_start_tool_result_count = len(tool_results)
        final_output = ""
        final_result_data = {}
        status = defaults.completed_status
        gate_signal = defaults.completed_gate_signal
        pending_tool_calls = []

        for output in output_iter:
            engine_output_count += 1
            last_seq = max(last_seq, int(output.seq or last_seq))
            if output_sink is not None:
                output_sink(output)

            if output.type == "assistant_message_completed":
                final_output = str(output.data.get("message") or "")
                continue
            if output.type == "llm_invocation_completed" and structured_status_resolver is not None:
                final_result_data = dict(output.data.get("result_data") or {})
                resolved = structured_status_resolver(final_result_data)
                if resolved is not None:
                    status, gate_signal = resolved
                continue
            if output.type == "llm_invocation_completed":
                final_result_data = dict(output.data.get("result_data") or {})
                continue
            if output.type == "tool_event":
                data = dict(output.data)
                if data.get("kind") in {"tool_call_started", "tool_use_completed"}:
                    tool_calls.append(data)
                elif data.get("kind") == "tool_result_ready":
                    result = {
                        "tool_name": data.get("tool_name"),
                        "output": data.get("content"),
                        "is_error": data.get("is_error", False),
                    }
                    if include_tool_result_metadata:
                        result["metadata"] = {}
                    tool_results.append(result)
                continue
            if output.type == "permission_requested":
                status = defaults.permission_status
                gate_signal = defaults.permission_gate_signal
                pending_tool_calls = [_permission_payload(dict(output.data))]
                tool_calls = list(pending_tool_calls)
                continue
            if output.type == "turn_failed":
                status = defaults.failed_status
                gate_signal = defaults.failed_gate_signal
                continue
            if output.type == "turn_interrupted":
                status = defaults.interrupted_status
                gate_signal = defaults.interrupted_gate_signal

        if (
            final_output_status_resolver is not None
            and status == defaults.completed_status
            and gate_signal == defaults.completed_gate_signal
        ):
            resolved = final_output_status_resolver(final_output)
            if resolved is not None:
                status, gate_signal = resolved

        current_turn_tool_calls = tool_calls[turn_start_tool_call_count:]
        current_turn_tool_results = tool_results[turn_start_tool_result_count:]
        continuation = (
            _resolve_final_output_continuation(
                final_output_continuation_resolver,
                final_output,
                current_turn_tool_calls,
                current_turn_tool_results,
                continuation_attempt,
                final_result_data,
            )
            if final_output_continuation_resolver is not None
            else None
        )
        if not continuation:
            break
        continuation_attempt += 1
        next_turn_input = continuation

    return AgentEngineResult(
        status=status,
        gate_signal=gate_signal,
        final_output=final_output,
        final_result_data=final_result_data,
        tool_calls=tool_calls,
        tool_results=tool_results,
        pending_tool_calls=pending_tool_calls,
        engine_output_count=engine_output_count,
        last_seq=last_seq,
        continuation_attempts=continuation_attempt,
        engine=engine,
    )


def _resolve_final_output_continuation(
    resolver: Callable[..., str | None],
    final_output: str,
    tool_calls: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    attempt: int,
    result_data: dict[str, Any],
) -> str | None:
    try:
        parameters = inspect.signature(resolver).parameters
    except (TypeError, ValueError):
        parameters = {}
    if len(parameters) >= 5:
        return resolver(final_output, tool_calls, tool_results, attempt, result_data)
    return resolver(final_output, tool_calls, tool_results, attempt)


def runtime_output_payload(output: InteractionOutput) -> dict[str, Any]:
    return {
        "type": output.type,
        "conversation_id": output.conversation_id,
        "turn_id": output.turn_id,
        "seq": output.seq,
        "data": dict(output.data or {}),
    }


def scoped_tool_registry(registry: ToolRegistry, agent_definition_id: str | None) -> ToolRegistry:
    if not agent_definition_id:
        return registry
    scoped = ToolRegistry()
    for tool in registry.tools.values():
        cloned = tool.clone()
        if cloned.category == "memory":
            original_handler = cloned.handler

            def _handler(arguments: dict[str, Any], *, handler=original_handler) -> Any:
                scoped_arguments = dict(arguments or {})
                scoped_arguments["agent_definition_id"] = agent_definition_id
                return handler(scoped_arguments)

            cloned.handler = _handler
        scoped.register(cloned)
    return scoped


def _permission_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": str(data.get("tool_name") or ""),
        "tool_use_id": str(data.get("tool_use_id") or ""),
        "tool_call_id": str(data.get("tool_call_id") or ""),
        "input": dict(data.get("input") or {}),
        "reason": str(data.get("reason") or "pending_confirmation"),
    }


def _extract_system_prompt(
    messages: list[LLMMessage],
    *,
    explicit_system_prompt: str | None,
) -> tuple[str | None, list[LLMMessage]]:
    if not messages:
        return explicit_system_prompt, []
    first = messages[0]
    if first.role != "system" or first.metadata.get("kind") == "context_compaction_summary":
        return explicit_system_prompt, list(messages)
    return explicit_system_prompt or str(first.content or ""), list(messages[1:])
