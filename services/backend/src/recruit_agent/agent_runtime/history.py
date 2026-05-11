from __future__ import annotations

from dataclasses import dataclass, field

from .types import LLMMessage


@dataclass(slots=True)
class ConversationHistory:
    messages: list[LLMMessage] = field(default_factory=list)

    def append(self, messages: list[LLMMessage]) -> None:
        self.messages.extend(messages)

    def snapshot(self) -> list[LLMMessage]:
        return list(self.messages)

    def replace(self, messages: list[LLMMessage]) -> None:
        self.messages = list(messages)
