from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from recruit_agent.agent_runtime.types import LLMInvocationResult, LLMMessage, LLMRequest, LLMResponse as RuntimeLLMResponse, TokenUsage, ToolUse


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: LLMUsage = field(default_factory=LLMUsage)
    result_data: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScriptedProvider:
    provider_name: str
    responses: list[Any]
    captured_requests: list[LLMRequest] = field(default_factory=list)

    def invoke(self, request: LLMRequest) -> LLMInvocationResult:
        self.captured_requests.append(request)
        if not self.responses:
            raise RuntimeError(f"{self.provider_name} has no scripted responses left")
        return LLMInvocationResult(events=[], response=_to_runtime_response(self.responses.pop(0), request))


def _to_runtime_response(response: Any, request: LLMRequest) -> RuntimeLLMResponse:
    if isinstance(response, RuntimeLLMResponse):
        return response
    content = str(getattr(response, "content", "") or "")
    tool_uses = [
        ToolUse(id=str(call.id), name=str(call.name), input=dict(call.arguments or {}))
        for call in list(getattr(response, "tool_calls", []) or [])
    ]
    usage = getattr(response, "usage", None)
    return RuntimeLLMResponse(
        id=f"resp_{request.invocation_id}",
        request_id=request.id,
        invocation_id=request.invocation_id,
        assistant_message=LLMMessage(role="assistant", content=content, tool_uses=tool_uses),
        tool_uses=tool_uses,
        result_data=dict(getattr(response, "result_data", {}) or {}) or None,
        stop_reason=str(getattr(response, "finish_reason", "stop") or "stop"),
        usage=TokenUsage(
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        ),
        raw=dict(getattr(response, "raw", {}) or {}),
    )
