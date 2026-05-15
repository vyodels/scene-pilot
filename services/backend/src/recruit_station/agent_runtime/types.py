from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event
from typing import Any, Literal, Protocol


Content = str | list[dict[str, Any]]
MessageRole = Literal["system", "user", "assistant", "tool"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AbortSignal:
    __slots__ = ("_event", "_reason")

    def __init__(self) -> None:
        self._event = Event()
        self._reason: str | None = None

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return self._reason

    def _abort(self, reason: str | None = None) -> None:
        if self._event.is_set():
            return
        self._reason = reason or "aborted"
        self._event.set()


class AbortController:
    __slots__ = ("_signal",)

    def __init__(self) -> None:
        self._signal = AbortSignal()

    @property
    def signal(self) -> AbortSignal:
        return self._signal

    def abort(self, reason: str | None = None) -> None:
        self._signal._abort(reason)


@dataclass(slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def openai(cls, payload: dict[str, Any] | None) -> "TokenUsage":
        if not payload:
            return cls()
        prompt = int(payload.get("prompt_tokens", 0) or 0)
        completion = int(payload.get("completion_tokens", 0) or 0)
        total = int(payload.get("total_tokens", 0) or (prompt + completion))
        return cls(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)

    @classmethod
    def anthropic(cls, payload: dict[str, Any] | None) -> "TokenUsage":
        if not payload:
            return cls()
        prompt = int(payload.get("input_tokens", payload.get("prompt_tokens", 0)) or 0)
        completion = int(payload.get("output_tokens", payload.get("completion_tokens", 0)) or 0)
        total = int(payload.get("total_tokens", 0) or (prompt + completion))
        return cls(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


@dataclass(slots=True)
class LLMMessage:
    role: MessageRole
    content: Content
    name: str | None = None
    tool_use_id: str | None = None
    tool_uses: list["ToolUse"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolSchema:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCall:
    id: str
    turn_id: str
    llm_invocation_id: str
    tool_use_id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    tool_call_id: str
    tool_use_id: str
    name: str
    content: Any
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolHandler(Protocol):
    def handle(self, call: ToolCall, context: "TurnContext") -> ToolResult: ...


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    schema: ToolSchema
    handler: ToolHandler
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMRequest:
    id: str
    turn_id: str
    invocation_id: str
    messages: list[LLMMessage]
    tools: list[ToolSchema] = field(default_factory=list)
    model: str | None = None
    system_prompt: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop_sequences: list[str] = field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None
    thinking: dict[str, Any] | None = None
    reasoning: dict[str, Any] | None = None
    text_format: dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    max_tool_calls: int | None = None
    previous_response_id: str | None = None
    store: bool | None = None
    truncation: str | None = None
    openai_payload_overrides: dict[str, Any] | None = None
    anthropic_payload_overrides: dict[str, Any] | None = None
    abort_signal: AbortSignal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMStreamEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    raw: Any | None = None


@dataclass(slots=True)
class LLMResponse:
    id: str
    request_id: str
    invocation_id: str
    assistant_message: LLMMessage | None = None
    reasoning: str | None = None
    tool_uses: list[ToolUse] = field(default_factory=list)
    result_data: dict[str, Any] | None = None
    stop_reason: str = "stop"
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMInvocationResult:
    events: list[LLMStreamEvent]
    response: LLMResponse


class LLMProvider(Protocol):
    provider_name: str

    def invoke(self, request: LLMRequest) -> LLMInvocationResult: ...


@dataclass(slots=True)
class InteractionOutput:
    type: str
    conversation_id: str
    seq: int
    id: str
    turn_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    data: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None


@dataclass(slots=True)
class TurnContext:
    turn_id: str
    conversation_id: str
    tools: list[ToolDefinition]
    abort_signal: AbortSignal | None = None
    runtime: dict[str, Any] = field(default_factory=dict)
