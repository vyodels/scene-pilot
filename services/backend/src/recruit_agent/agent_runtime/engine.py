from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Iterator
from uuid import uuid4

from .history import ConversationHistory
from .tools import ToolRegistry
from .transcript import InMemoryTranscript, Transcript, TranscriptState
from .types import (
    InteractionOutput,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolUse,
    TurnContext,
)


@dataclass(slots=True)
class InteractionEngineConfig:
    conversation_id: str
    provider: LLMProvider
    tools: list[ToolDefinition] = field(default_factory=list)
    transcript: Transcript | None = None
    initial_messages: list[LLMMessage] = field(default_factory=list)
    model: str | None = None
    system_prompt: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop_sequences: list[str] = field(default_factory=list)
    tool_choice: str | dict[str, object] | None = None
    thinking: dict[str, object] | None = None
    reasoning: dict[str, object] | None = None
    text_format: dict[str, object] | None = None
    parallel_tool_calls: bool | None = None
    max_tool_calls: int | None = None
    previous_response_id: str | None = None
    store: bool | None = None
    truncation: str | None = None
    openai_payload_overrides: dict[str, object] | None = None
    anthropic_payload_overrides: dict[str, object] | None = None
    max_llm_invocations: int = 12
    max_history_messages: int | None = None
    compaction_summary_max_chars: int = 2000
    initial_seq: int = 1


@dataclass(slots=True)
class PendingPermissionState:
    turn_id: str
    tool_call: ToolCall
    context: TurnContext
    next_invocation_index: int


@dataclass(slots=True)
class InteractionEngine:
    config: InteractionEngineConfig
    history: ConversationHistory = field(init=False)
    transcript: Transcript = field(init=False)
    active_turn_id: str | None = field(default=None, init=False)
    pending_permission: PendingPermissionState | None = field(default=None, init=False)
    _seq: count = field(default_factory=lambda: count(1), init=False)
    _interrupted: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.transcript = self.config.transcript or InMemoryTranscript()
        state = None if self.config.initial_messages else self.transcript.load(self.config.conversation_id)
        messages = list(self.config.initial_messages or (state.messages if state else []))
        self.history = ConversationHistory(messages)
        if self.config.initial_messages:
            self.transcript.record_messages(self.config.conversation_id, messages)
        if state is not None:
            self._seq = count(state.next_seq)
            self.pending_permission = _pending_permission_from_payload(
                state.pending_permissions[-1] if state.pending_permissions else None,
                conversation_id=self.config.conversation_id,
                tools=self.config.tools,
            )
        elif self.config.initial_seq > 1:
            self._seq = count(self.config.initial_seq)

    def submitMessage(self, input: str | list[dict[str, object]]) -> Iterator[InteractionOutput]:
        if self.active_turn_id is not None:
            raise RuntimeError("A turn is already active for this conversation")
        if self.pending_permission is not None:
            raise RuntimeError("The active turn is waiting for a permission decision")
        turn_id = f"turn_{uuid4().hex}"
        self.active_turn_id = turn_id
        user_message = LLMMessage(role="user", content=input)
        self.history.append([user_message])
        self.transcript.record_messages(self.config.conversation_id, [user_message])
        try:
            yield self._output("turn_started", turn_id, {})
            yield from self._run_turn(turn_id)
        except Exception as exc:
            yield self._output("turn_failed", turn_id, {"error": str(exc)})
            raise
        finally:
            self.active_turn_id = None

    def resolvePermission(self, *, approved: bool) -> Iterator[InteractionOutput]:
        if self.active_turn_id is not None:
            raise RuntimeError("A turn is already active for this conversation")
        pending = self.pending_permission
        if pending is None:
            raise RuntimeError("No pending permission for this conversation")
        self.pending_permission = None
        self.transcript.clear_pending_permission(self.config.conversation_id)
        self.active_turn_id = pending.turn_id
        try:
            yield self._output(
                "runtime_event",
                pending.turn_id,
                {
                    "kind": "permission_resolved",
                    "tool_name": pending.tool_call.name,
                    "tool_use_id": pending.tool_call.tool_use_id,
                    "tool_call_id": pending.tool_call.id,
                    "approved": approved,
                },
            )
            registry = ToolRegistry.from_tools(self.config.tools)
            if approved:
                yield from self._run_tool_call(registry, pending.tool_call, pending.context)
            else:
                result = ToolResult(
                    tool_call_id=pending.tool_call.id,
                    tool_use_id=pending.tool_call.tool_use_id,
                    name=pending.tool_call.name,
                    content="Permission denied by operator.",
                    is_error=True,
                    metadata={"permission_denied": True},
                )
                yield from self._record_tool_result(result, pending.turn_id)
            yield from self._run_turn(pending.turn_id, start_invocation_index=pending.next_invocation_index)
        except Exception as exc:
            yield self._output("turn_failed", pending.turn_id, {"error": str(exc)})
            raise
        finally:
            self.active_turn_id = None

    def interrupt(self) -> None:
        self._interrupted = True

    def _run_turn(self, turn_id: str, *, start_invocation_index: int = 0) -> Iterator[InteractionOutput]:
        registry = ToolRegistry.from_tools(self.config.tools)
        context = TurnContext(
            turn_id=turn_id,
            conversation_id=self.config.conversation_id,
            tools=self.config.tools,
        )
        for invocation_index in range(start_invocation_index, self.config.max_llm_invocations):
            if self._interrupted:
                yield self._output("turn_interrupted", turn_id, {"reason": "interrupted"})
                return
            compaction = self._compact_history_if_needed()
            if compaction is not None:
                yield self._output("runtime_event", turn_id, {"kind": "context_compacted", **compaction})
            invocation_id = f"llm_{uuid4().hex}"
            request = LLMRequest(
                id=f"req_{uuid4().hex}",
                turn_id=turn_id,
                invocation_id=invocation_id,
                messages=self.history.snapshot(),
                tools=registry.schemas(),
                model=self.config.model,
                system_prompt=self.config.system_prompt,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                stop_sequences=list(self.config.stop_sequences),
                tool_choice=self.config.tool_choice,
                thinking=dict(self.config.thinking) if self.config.thinking is not None else None,
                reasoning=dict(self.config.reasoning) if self.config.reasoning is not None else None,
                text_format=dict(self.config.text_format) if self.config.text_format is not None else None,
                parallel_tool_calls=self.config.parallel_tool_calls,
                max_tool_calls=self.config.max_tool_calls,
                previous_response_id=self.config.previous_response_id,
                store=self.config.store,
                truncation=self.config.truncation,
                openai_payload_overrides=dict(self.config.openai_payload_overrides)
                if self.config.openai_payload_overrides is not None
                else None,
                anthropic_payload_overrides=dict(self.config.anthropic_payload_overrides)
                if self.config.anthropic_payload_overrides is not None
                else None,
            )
            yield self._output("llm_invocation_started", turn_id, {"invocation_id": invocation_id, "index": invocation_index})
            result = self.config.provider.invoke(request)
            for event in result.events:
                yield from self._map_llm_event(turn_id, invocation_id, event.type, event.data)
            response = result.response
            if response.assistant_message is not None:
                self.history.append([response.assistant_message])
                self.transcript.record_messages(self.config.conversation_id, [response.assistant_message])
                text = _message_text(response.assistant_message)
                if text:
                    yield self._output(
                        "assistant_message_completed",
                        turn_id,
                        {"message": text, "invocation_id": invocation_id},
                    )
            yield self._output(
                "llm_invocation_completed",
                turn_id,
                {
                    "invocation_id": invocation_id,
                    "stop_reason": response.stop_reason,
                    "tool_use_count": len(response.tool_uses),
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    },
                    "result_data": dict(response.result_data or {}),
                },
            )
            if not response.tool_uses:
                yield self._output("turn_completed", turn_id, {"status": "completed"})
                return
            for tool_use in response.tool_uses:
                tool_call = ToolCall(
                    id=f"tool_{uuid4().hex}",
                    turn_id=turn_id,
                    llm_invocation_id=invocation_id,
                    tool_use_id=tool_use.id,
                    name=tool_use.name,
                    input=dict(tool_use.input or {}),
                )
                yield self._output(
                    "tool_event",
                    turn_id,
                    {
                        "kind": "tool_call_started",
                        "tool_name": tool_call.name,
                        "tool_use_id": tool_call.tool_use_id,
                        "tool_call_id": tool_call.id,
                    },
                )
                if self._requires_permission(registry, tool_call):
                    self.pending_permission = PendingPermissionState(
                        turn_id=turn_id,
                        tool_call=tool_call,
                        context=context,
                        next_invocation_index=invocation_index + 1,
                    )
                    self.transcript.record_pending_permission(
                        self.config.conversation_id,
                        _pending_permission_payload(self.pending_permission),
                    )
                    yield self._output(
                        "permission_requested",
                        turn_id,
                        {
                            "tool_name": tool_call.name,
                            "tool_use_id": tool_call.tool_use_id,
                            "tool_call_id": tool_call.id,
                            "input": dict(tool_call.input or {}),
                            "reason": "pending_confirmation",
                        },
                    )
                    return
                yield from self._run_tool_call(registry, tool_call, context)
        yield self._output("turn_failed", turn_id, {"error": "max_llm_invocations_exhausted"})

    def _compact_history_if_needed(self) -> dict[str, object] | None:
        max_messages = self.config.max_history_messages
        if max_messages is None:
            return None
        before_count = len(self.history.messages)
        compacted = self.history.compact(
            max_messages=max_messages,
            summary_max_chars=self.config.compaction_summary_max_chars,
        )
        if compacted is None:
            return None
        self.transcript.replace_messages(self.config.conversation_id, compacted)
        summary = next(
            (
                message
                for message in compacted
                if message.role == "system" and message.metadata.get("kind") == "context_compaction_summary"
            ),
            None,
        )
        return {
            "messages_before": before_count,
            "messages_after": len(compacted),
            "summary": summary.content if summary is not None else "",
        }

    def _requires_permission(self, registry: ToolRegistry, call: ToolCall) -> bool:
        try:
            tool = registry.get(call.name)
        except Exception:
            return False
        metadata = dict(tool.metadata or {})
        return bool(
            metadata.get("requires_confirmation")
            or metadata.get("external_target")
            or call.input.get("requires_confirmation")
        )

    def _run_tool(self, registry: ToolRegistry, call: ToolCall, context: TurnContext) -> ToolResult:
        try:
            tool = registry.get(call.name)
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                tool_use_id=call.tool_use_id,
                name=call.name,
                content=str(exc),
                is_error=True,
            )
        return tool.handler.handle(call, context)

    def _run_tool_call(self, registry: ToolRegistry, call: ToolCall, context: TurnContext) -> Iterator[InteractionOutput]:
        result = self._run_tool(registry, call, context)
        yield from self._record_tool_result(result, call.turn_id)

    def _record_tool_result(self, result: ToolResult, turn_id: str) -> Iterator[InteractionOutput]:
        self.transcript.record_tool_result(self.config.conversation_id, result)
        tool_message = LLMMessage(
            role="tool",
            name=result.name,
            tool_use_id=result.tool_use_id,
            content=_tool_result_content(result),
            metadata={"is_error": result.is_error, "tool_call_id": result.tool_call_id},
        )
        self.history.append([tool_message])
        self.transcript.record_messages(self.config.conversation_id, [tool_message])
        yield self._output(
            "tool_event",
            turn_id,
            {
                "kind": "tool_result_ready",
                "tool_name": result.name,
                "tool_use_id": result.tool_use_id,
                "tool_call_id": result.tool_call_id,
                "is_error": result.is_error,
                "content": result.content,
            },
        )

    def _map_llm_event(self, turn_id: str, invocation_id: str, event_type: str, data: dict[str, object]) -> Iterator[InteractionOutput]:
        if event_type == "assistant_delta":
            yield self._output("assistant_message_delta", turn_id, {"delta": data.get("delta", ""), "invocation_id": invocation_id})
        elif event_type == "reasoning_delta":
            yield self._output("reasoning_delta", turn_id, {"delta": data.get("delta", ""), "invocation_id": invocation_id})
        elif event_type in {"tool_use_delta", "tool_use_completed"}:
            yield self._output("tool_event", turn_id, {"kind": event_type, **data, "invocation_id": invocation_id})
        elif event_type == "usage_delta":
            yield self._output("runtime_event", turn_id, {"kind": "token_usage", **data})

    def _output(self, output_type: str, turn_id: str | None, data: dict[str, object]) -> InteractionOutput:
        output = InteractionOutput(
            type=output_type,
            conversation_id=self.config.conversation_id,
            turn_id=turn_id,
            seq=next(self._seq),
            id=f"out_{uuid4().hex}",
            data=dict(data),
        )
        self.transcript.record_output(self.config.conversation_id, output)
        return output

    def checkpoint_state(self) -> dict[str, object]:
        state = self.transcript.load(self.config.conversation_id) or TranscriptState()
        return transcript_state_to_payload(state)


def _message_text(message: LLMMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


def _tool_result_content(result: ToolResult) -> str:
    if isinstance(result.content, str):
        return result.content
    import json

    return json.dumps(result.content, ensure_ascii=False, sort_keys=True, default=str)


def transcript_state_to_payload(state: TranscriptState) -> dict[str, object]:
    return {
        "messages": [_message_to_payload(message) for message in state.messages],
        "next_seq": state.next_seq,
        "pending_permissions": [dict(item) for item in state.pending_permissions],
        "tool_states": [dict(item) for item in state.tool_states],
    }


def transcript_state_from_payload(payload: dict[str, object] | None) -> TranscriptState:
    raw = dict(payload or {})
    return TranscriptState(
        messages=[
            _message_from_payload(item)
            for item in list(raw.get("messages") or [])
            if isinstance(item, dict)
        ],
        next_seq=_positive_int(raw.get("next_seq"), default=1),
        pending_permissions=[
            dict(item)
            for item in list(raw.get("pending_permissions") or [])
            if isinstance(item, dict)
        ],
        tool_states=[
            dict(item)
            for item in list(raw.get("tool_states") or [])
            if isinstance(item, dict)
        ],
    )


def transcript_from_checkpoint(conversation_id: str, payload: dict[str, object] | None) -> InMemoryTranscript:
    transcript = InMemoryTranscript()
    transcript.states[conversation_id] = transcript_state_from_payload(payload)
    return transcript


def _pending_permission_payload(pending: PendingPermissionState | None) -> dict[str, object]:
    if pending is None:
        return {}
    return {
        "turn_id": pending.turn_id,
        "next_invocation_index": pending.next_invocation_index,
        "tool_call": {
            "id": pending.tool_call.id,
            "turn_id": pending.tool_call.turn_id,
            "llm_invocation_id": pending.tool_call.llm_invocation_id,
            "tool_use_id": pending.tool_call.tool_use_id,
            "name": pending.tool_call.name,
            "input": dict(pending.tool_call.input or {}),
        },
        "context": {
            "turn_id": pending.context.turn_id,
            "conversation_id": pending.context.conversation_id,
            "runtime": dict(pending.context.runtime or {}),
        },
    }


def _pending_permission_from_payload(
    payload: dict[str, object] | None,
    *,
    conversation_id: str,
    tools: list[ToolDefinition],
) -> PendingPermissionState | None:
    if not isinstance(payload, dict):
        return None
    raw_tool_call = payload.get("tool_call")
    if not isinstance(raw_tool_call, dict):
        return None
    tool_call = ToolCall(
        id=str(raw_tool_call.get("id") or ""),
        turn_id=str(raw_tool_call.get("turn_id") or payload.get("turn_id") or ""),
        llm_invocation_id=str(raw_tool_call.get("llm_invocation_id") or ""),
        tool_use_id=str(raw_tool_call.get("tool_use_id") or ""),
        name=str(raw_tool_call.get("name") or ""),
        input=dict(raw_tool_call.get("input") or {}),
    )
    if not tool_call.id or not tool_call.turn_id or not tool_call.name:
        return None
    raw_context = payload.get("context")
    context_payload = dict(raw_context) if isinstance(raw_context, dict) else {}
    context = TurnContext(
        turn_id=str(context_payload.get("turn_id") or tool_call.turn_id),
        conversation_id=str(context_payload.get("conversation_id") or conversation_id),
        tools=tools,
        runtime=dict(context_payload.get("runtime") or {}),
    )
    return PendingPermissionState(
        turn_id=str(payload.get("turn_id") or tool_call.turn_id),
        tool_call=tool_call,
        context=context,
        next_invocation_index=_positive_int(payload.get("next_invocation_index"), default=1),
    )


def _message_to_payload(message: LLMMessage) -> dict[str, object]:
    return {
        "role": message.role,
        "content": message.content,
        "name": message.name,
        "tool_use_id": message.tool_use_id,
        "tool_uses": [
            {
                "id": tool_use.id,
                "name": tool_use.name,
                "input": dict(tool_use.input or {}),
                "raw": dict(tool_use.raw or {}),
            }
            for tool_use in message.tool_uses
        ],
        "metadata": dict(message.metadata or {}),
    }


def _message_from_payload(payload: dict[str, object]) -> LLMMessage:
    raw_tool_uses = [
        item
        for item in list(payload.get("tool_uses") or [])
        if isinstance(item, dict)
    ]
    return LLMMessage(
        role=payload.get("role") if payload.get("role") in {"system", "user", "assistant", "tool"} else "user",  # type: ignore[arg-type]
        content=payload.get("content") if isinstance(payload.get("content"), (str, list)) else "",
        name=str(payload.get("name") or "") or None,
        tool_use_id=str(payload.get("tool_use_id") or "") or None,
        tool_uses=[
            ToolUse(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                input=dict(item.get("input") or {}),
                raw=dict(item.get("raw") or {}),
            )
            for item in raw_tool_uses
        ],
        metadata=dict(payload.get("metadata") or {}),
    )


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)
