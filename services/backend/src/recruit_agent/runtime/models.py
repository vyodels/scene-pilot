from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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
