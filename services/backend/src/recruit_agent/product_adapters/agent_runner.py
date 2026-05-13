from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from recruit_agent.agent_runtime.engine import InteractionEngine, InteractionEngineConfig
from recruit_agent.agent_runtime.transcript import Transcript
from recruit_agent.agent_runtime.types import InteractionOutput, LLMMessage, LLMProvider
from recruit_agent.capabilities.tools import ToolRegistry


@dataclass(frozen=True, slots=True)
class AgentRunStatusDefaults:
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
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    engine_output_count: int
    last_seq: int
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
    initial_seq: int = 1,
    transcript: Transcript | None = None,
    existing_engine: InteractionEngine | None = None,
    resolve_permission: bool = False,
    output_sink: Callable[[InteractionOutput], None] | None = None,
    engine_sink: Callable[[InteractionEngine], None] | None = None,
    structured_status_resolver: Callable[[Any], tuple[str, str] | None] | None = None,
    status_defaults: AgentRunStatusDefaults | None = None,
    include_tool_result_metadata: bool = False,
) -> AgentEngineResult:
    defaults = status_defaults or AgentRunStatusDefaults(completed_status="completed")
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
            initial_seq=initial_seq,
        )
    )
    if engine_sink is not None:
        engine_sink(engine)

    output_iter: Iterable[InteractionOutput]
    if resolve_permission:
        output_iter = engine.resolvePermission(approved=True)
    else:
        output_iter = engine.submitMessage(turn_input)

    final_output = ""
    status = defaults.completed_status
    gate_signal = defaults.completed_gate_signal
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    pending_tool_calls: list[dict[str, Any]] = []
    engine_output_count = 0
    last_seq = initial_seq - 1

    for output in output_iter:
        engine_output_count += 1
        last_seq = max(last_seq, int(output.seq or last_seq))
        if output_sink is not None:
            output_sink(output)

        if output.type == "assistant_message_completed":
            final_output = str(output.data.get("message") or "")
            continue
        if output.type == "llm_invocation_completed" and structured_status_resolver is not None:
            resolved = structured_status_resolver(output.data.get("result_data"))
            if resolved is not None:
                status, gate_signal = resolved
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

    return AgentEngineResult(
        status=status,
        gate_signal=gate_signal,
        final_output=final_output,
        tool_calls=tool_calls,
        tool_results=tool_results,
        pending_tool_calls=pending_tool_calls,
        engine_output_count=engine_output_count,
        last_seq=last_seq,
        engine=engine,
    )


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
