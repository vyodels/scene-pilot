from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Iterator
from uuid import uuid4

from .history import ConversationHistory
from .tools import ToolRegistry
from .transcript import InMemoryTranscript, Transcript
from .types import (
    InteractionOutput,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    ToolCall,
    ToolDefinition,
    ToolResult,
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
    max_turns: int = 12


@dataclass(slots=True)
class InteractionEngine:
    config: InteractionEngineConfig
    history: ConversationHistory = field(init=False)
    transcript: Transcript = field(init=False)
    active_turn_id: str | None = field(default=None, init=False)
    _seq: count = field(default_factory=lambda: count(1), init=False)
    _interrupted: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.transcript = self.config.transcript or InMemoryTranscript()
        state = None if self.config.initial_messages else self.transcript.load(self.config.conversation_id)
        messages = list(self.config.initial_messages or (state.messages if state else []))
        self.history = ConversationHistory(messages)
        if state is not None:
            self._seq = count(state.next_seq)

    def submitMessage(self, input: str | list[dict[str, object]]) -> Iterator[InteractionOutput]:
        if self.active_turn_id is not None:
            raise RuntimeError("A turn is already active for this conversation")
        self._interrupted = False
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

    def interrupt(self) -> None:
        self._interrupted = True

    def _run_turn(self, turn_id: str) -> Iterator[InteractionOutput]:
        registry = ToolRegistry.from_tools(self.config.tools)
        context = TurnContext(
            turn_id=turn_id,
            conversation_id=self.config.conversation_id,
            tools=self.config.tools,
        )
        for invocation_index in range(self.config.max_turns):
            if self._interrupted:
                yield self._output("turn_interrupted", turn_id, {"reason": "interrupted"})
                return
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
                result = self._run_tool(registry, tool_call, context)
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
        yield self._output("turn_failed", turn_id, {"error": "max_turns_exhausted"})

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
