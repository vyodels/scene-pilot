from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import InteractionOutput, LLMMessage, ToolResult


@dataclass(slots=True)
class TranscriptState:
    messages: list[LLMMessage] = field(default_factory=list)
    next_seq: int = 1
    pending_permissions: list[dict[str, object]] = field(default_factory=list)
    tool_states: list[dict[str, object]] = field(default_factory=list)


class Transcript:
    def load(self, conversation_id: str) -> TranscriptState | None:
        raise NotImplementedError

    def record_messages(self, conversation_id: str, messages: list[LLMMessage]) -> None:
        raise NotImplementedError

    def record_output(self, conversation_id: str, output: InteractionOutput) -> None:
        raise NotImplementedError

    def record_tool_result(self, conversation_id: str, result: ToolResult) -> None:
        raise NotImplementedError

    def record_pending_permission(self, conversation_id: str, pending: dict[str, Any]) -> None:
        raise NotImplementedError

    def clear_pending_permission(self, conversation_id: str) -> None:
        raise NotImplementedError

    def replace_messages(self, conversation_id: str, messages: list[LLMMessage]) -> None:
        raise NotImplementedError


@dataclass(slots=True)
class InMemoryTranscript(Transcript):
    states: dict[str, TranscriptState] = field(default_factory=dict)
    outputs: dict[str, list[InteractionOutput]] = field(default_factory=dict)
    tool_results: dict[str, list[ToolResult]] = field(default_factory=dict)

    def load(self, conversation_id: str) -> TranscriptState | None:
        state = self.states.get(conversation_id)
        if state is None:
            return None
        return TranscriptState(
            messages=list(state.messages),
            next_seq=state.next_seq,
            pending_permissions=list(state.pending_permissions),
            tool_states=list(state.tool_states),
        )

    def record_messages(self, conversation_id: str, messages: list[LLMMessage]) -> None:
        state = self.states.setdefault(conversation_id, TranscriptState())
        state.messages.extend(messages)

    def record_output(self, conversation_id: str, output: InteractionOutput) -> None:
        self.outputs.setdefault(conversation_id, []).append(output)
        state = self.states.setdefault(conversation_id, TranscriptState())
        state.next_seq = max(state.next_seq, output.seq + 1)

    def record_tool_result(self, conversation_id: str, result: ToolResult) -> None:
        self.tool_results.setdefault(conversation_id, []).append(result)

    def record_pending_permission(self, conversation_id: str, pending: dict[str, Any]) -> None:
        state = self.states.setdefault(conversation_id, TranscriptState())
        state.pending_permissions = [dict(pending)]

    def clear_pending_permission(self, conversation_id: str) -> None:
        state = self.states.setdefault(conversation_id, TranscriptState())
        state.pending_permissions = []

    def replace_messages(self, conversation_id: str, messages: list[LLMMessage]) -> None:
        state = self.states.setdefault(conversation_id, TranscriptState())
        state.messages = list(messages)
