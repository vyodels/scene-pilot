# mypy: ignore-errors
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event
from typing import Any, Literal
import json


MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class Message:
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {"role": self.role, "content": self.content}
        if self.name is not None:
            payload["name"] = self.name
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        tool_calls = self.metadata.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            payload["tool_calls"] = list(tool_calls)
        return payload


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_provider_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ToolCall":
        if "function" in payload:
            function = payload.get("function") or {}
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {"_raw": arguments}
            return cls(
                id=str(payload.get("id", "")),
                name=str(function.get("name", "")),
                arguments=dict(arguments or {}),
            )

        arguments = payload.get("input", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw": arguments}

        return cls(
            id=str(payload.get("id", "")),
            name=str(payload.get("name", "")),
            arguments=dict(arguments or {}),
        )


@dataclass(slots=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "LLMUsage":
        if not payload:
            return cls()
        prompt_tokens = int(payload.get("prompt_tokens", 0) or 0)
        completion_tokens = int(payload.get("completion_tokens", 0) or 0)
        total_tokens = int(payload.get("total_tokens", 0) or (prompt_tokens + completion_tokens))
        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )


@dataclass(slots=True)
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: LLMUsage = field(default_factory=LLMUsage)
    requires_human_input: bool = False
    result_data: dict[str, Any] | None = None
    skill_draft: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "LLMResponse":
        if "choices" in payload:
            choice = (payload.get("choices") or [{}])[0] or {}
            message = choice.get("message") or {}
            tool_calls = [
                ToolCall.from_payload(raw_call)
                for raw_call in message.get("tool_calls", []) or []
            ]
            content = message.get("content") or ""
            return cls(
                content=content if isinstance(content, str) else json.dumps(content),
                tool_calls=tool_calls,
                finish_reason=str(choice.get("finish_reason", "stop")),
                usage=LLMUsage.from_payload(payload.get("usage")),
                raw=dict(payload),
            )

        content_blocks = payload.get("content")
        tool_calls: list[ToolCall] = []
        content = ""
        if isinstance(content_blocks, list):
            text_parts: list[str] = []
            for block in content_blocks:
                block_type = block.get("type")
                if block_type == "text":
                    text_parts.append(str(block.get("text", "")))
                elif block_type in {"tool_use", "tool_call"}:
                    tool_calls.append(ToolCall.from_payload(block))
            content = "\n".join(part for part in text_parts if part)
        elif isinstance(content_blocks, str):
            content = content_blocks

        return cls(
            content=content,
            tool_calls=tool_calls,
            finish_reason=str(payload.get("stop_reason", payload.get("finish_reason", "stop"))),
            usage=LLMUsage.from_payload(payload.get("usage")),
            requires_human_input=bool(payload.get("requires_human_input", False)),
            result_data=payload.get("result_data"),
            skill_draft=payload.get("skill_draft"),
            raw=dict(payload),
        )


@dataclass(slots=True)
class ToolExecutionResult:
    tool_name: str
    output: Any
    is_error: bool = False
    arguments: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_message_content(self) -> str:
        if isinstance(self.output, str):
            return self.output
        return json.dumps(self.output, ensure_ascii=False, sort_keys=True, default=str)


@dataclass(slots=True)
class AgentResult:
    success: bool
    status: str
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    skill_draft: dict[str, Any] | None = None
    messages: list[Message] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    tool_outputs: list[ToolExecutionResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GoalRef:
    goal_id: str
    scope_kind: str
    scope_ref: str
    title: str | None = None
    goal_text: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CheckpointRef:
    checkpoint_id: str
    run_id: str | None = None
    turn_id: str | None = None
    summary: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FairnessState:
    last_scope_ref: str | None = None
    same_scope_turns: int = 0
    soft_limit: int = 3
    hard_limit: int = 6
    cooldown_until: datetime | None = None


@dataclass(slots=True)
class InputEnvelope:
    history_messages: list[Message] = field(default_factory=list)
    input_message: str | None = None
    seed_tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(slots=True)
class Observation:
    world_snapshot: dict[str, Any] = field(default_factory=dict)
    scope_ref: str | None = None
    scope_kind: str | None = None
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    available_tools: list[str] = field(default_factory=list)
    available_skills: list[str] = field(default_factory=list)
    available_mcps: list[str] = field(default_factory=list)
    hash: str | None = None
    input: InputEnvelope | None = None


@dataclass(slots=True)
class CacheBlock:
    cache_key: str
    content: dict[str, Any] = field(default_factory=dict)
    token_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class LLMRequest:
    messages: list[Message] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int | None = None
    temperature: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Deliberation:
    messages: list[Message] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolExecutionResult] = field(default_factory=list)
    final_content: str = ""
    result_data: dict[str, Any] | None = None
    skill_draft: dict[str, Any] | None = None
    stop_reason: str = "stop"
    usage: LLMUsage = field(default_factory=LLMUsage)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GuardVerdict:
    allowed: bool
    reason: str | None = None
    severity: str = "info"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WakeupRequest:
    delay_seconds: int
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionUnitResult:
    unit_id: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Effects:
    state_updates: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    follow_ups: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    wakeup_request: WakeupRequest | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RoundOutcome:
    status: Literal["continue", "complete", "wait_human", "escalate", "error", "cancelled"]
    gate_signal: Literal["continue", "wait_human", "budget_exhausted", "goal_done", "paused", "escalate"] | None = None
    final_output: str | None = None
    result_data: dict[str, Any] | None = None
    skill_draft: dict[str, Any] | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolExecutionResult] = field(default_factory=list)
    memory_updates: list[dict[str, Any]] = field(default_factory=list)
    effects: Effects = field(default_factory=Effects)
    escalate_reason: str | None = None
    checkpoint: CheckpointRef | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CancellationToken:
    cancelled: bool = False
    reason: str | None = None
    _event: Event = field(default_factory=Event, init=False, repr=False)

    def cancel(self, reason: str | None = None) -> None:
        self.cancelled = True
        self.reason = reason
        self._event.set()

    def is_cancelled(self) -> bool:
        return self.cancelled

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeError(self.reason or "cancelled")

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)
