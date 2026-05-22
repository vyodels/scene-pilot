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

    def compact(self, *, max_messages: int, summary_max_chars: int = 2000) -> list[LLMMessage] | None:
        if max_messages < 2 or len(self.messages) <= max_messages:
            return None

        prefix: list[LLMMessage] = []
        compactable = list(self.messages)
        while compactable and compactable[0].role == "system" and compactable[0].metadata.get("kind") != "context_compaction_summary":
            prefix.append(compactable.pop(0))

        recent_count = max(1, max_messages - len(prefix) - 1)
        if len(compactable) <= recent_count:
            return None

        recent_start = max(0, len(compactable) - recent_count)
        recent_start = _include_tool_context(compactable, recent_start)
        old_messages = compactable[:recent_start]
        recent_messages = compactable[recent_start:]
        if not old_messages:
            return None

        summary = _summarize_messages(old_messages, max_chars=summary_max_chars)
        summary_message = LLMMessage(
            role="system",
            content=f"Conversation history compacted. Earlier messages summary:\n{summary}",
            metadata={
                "kind": "context_compaction_summary",
                "compacted_message_count": len(old_messages),
            },
        )
        compacted = [*prefix, summary_message, *recent_messages]
        self.replace(compacted)
        return compacted

    def compact_for_context_budget(
        self,
        *,
        max_chars: int,
        summary_max_chars: int = 2000,
        preserve_recent_messages: int = 1,
    ) -> list[LLMMessage] | None:
        if max_chars <= 0 or _messages_chars(self.messages) <= max_chars:
            return None

        messages = list(self.messages)
        changed = False
        for index, message in enumerate(messages):
            if not _is_auto_compactable(message):
                continue
            replacement = _compaction_summary_message(
                [message],
                summary_max_chars=summary_max_chars,
                reason="auto_compact_runtime_context",
            )
            if _message_chars(replacement) >= _message_chars(message):
                continue
            messages[index] = replacement
            changed = True
            if _messages_chars(messages) <= max_chars:
                self.replace(messages)
                return messages

        preserve_recent_messages = max(1, preserve_recent_messages)
        prefix: list[LLMMessage] = []
        compactable = list(messages)
        while compactable and compactable[0].role == "system" and compactable[0].metadata.get("kind") != "context_compaction_summary":
            prefix.append(compactable.pop(0))
        if len(compactable) <= preserve_recent_messages:
            if changed:
                self.replace(messages)
                return messages
            return None
        split_at = max(0, len(compactable) - preserve_recent_messages)
        split_at = _include_tool_context(compactable, split_at)
        old_messages = compactable[:split_at]
        recent_messages = compactable[split_at:]
        if old_messages:
            messages = [
                *prefix,
                _compaction_summary_message(
                    old_messages,
                    summary_max_chars=summary_max_chars,
                    reason="auto_compact_older_messages",
                ),
                *recent_messages,
            ]
            changed = True

        if changed:
            self.replace(messages)
            return messages
        return None


def _include_tool_context(messages: list[LLMMessage], recent_start: int) -> int:
    while recent_start > 0 and messages[recent_start].role == "tool":
        tool_use_id = messages[recent_start].tool_use_id
        assistant_index = recent_start - 1
        while assistant_index >= 0:
            candidate = messages[assistant_index]
            if candidate.role == "assistant" and any(tool_use.id == tool_use_id for tool_use in candidate.tool_uses):
                recent_start = assistant_index
                break
            assistant_index -= 1
        else:
            break
    return recent_start


def _summarize_messages(messages: list[LLMMessage], *, max_chars: int) -> str:
    parts: list[str] = []
    for message in messages:
        text = _message_text(message).strip()
        if not text and message.tool_uses:
            text = ", ".join(tool_use.name for tool_use in message.tool_uses)
        if not text:
            continue
        parts.append(f"- {message.role}: {_clip(text, 240)}")
    summary = "\n".join(parts) or "- Earlier messages were compacted."
    return _clip(summary, max_chars)


def _compaction_summary_message(
    messages: list[LLMMessage],
    *,
    summary_max_chars: int,
    reason: str,
) -> LLMMessage:
    return LLMMessage(
        role="system",
        content=f"Conversation context compacted automatically before provider request. Earlier context summary:\n{_summarize_messages(messages, max_chars=summary_max_chars)}",
        metadata={
            "kind": "context_compaction_summary",
            "reason": reason,
            "compacted_message_count": len(messages),
        },
    )


def _is_auto_compactable(message: LLMMessage) -> bool:
    return bool(message.metadata.get("auto_compact")) or str(message.metadata.get("kind") or "") in {
        "runtime_context",
        "context_payload",
    }


def _messages_chars(messages: list[LLMMessage]) -> int:
    return sum(_message_chars(message) for message in messages)


def _message_chars(message: LLMMessage) -> int:
    return len(str(message.role)) + len(_message_text(message)) + sum(len(str(tool_use.name)) + len(str(tool_use.input)) for tool_use in message.tool_uses)


def _message_text(message: LLMMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


def _clip(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."
