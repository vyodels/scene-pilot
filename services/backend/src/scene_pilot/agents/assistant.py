from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scene_pilot.assistant.conversation import ConversationService
from scene_pilot.assistant.session_store import AssistantSessionStore
from scene_pilot.runtime.models import CancellationToken, Message
from scene_pilot.runtime.providers import LLMProvider
from scene_pilot.runtime.tools import ToolRegistry


@dataclass(slots=True)
class AssistantAgent:
    provider: LLMProvider
    tool_registry: ToolRegistry
    session_store: AssistantSessionStore
    active_tokens: dict[str, CancellationToken] = field(default_factory=dict)
    conversations: ConversationService = field(init=False)

    def __post_init__(self) -> None:
        self.conversations = ConversationService(self.session_store)

    def create_conversation(self, *, user_id: str, title: str | None = None) -> Any:
        return self.conversations.create(user_id=user_id, title=title)

    def list_conversations(self, *, user_id: str | None = None) -> list[Any]:
        return self.conversations.list(user_id=user_id)

    def get_conversation(self, conversation_id: str) -> Any:
        return self.conversations.get(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        return self.session_store.delete_session(conversation_id)

    def run_turn(self, conversation_id: str, message: str) -> list[tuple[str, dict[str, Any]]]:
        conversation = self.session_store.get_session(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")
        token = self.active_tokens.setdefault(conversation_id, CancellationToken())
        user_turn = self.session_store.append_turn(conversation_id, role="user", content={"text": message})
        self.session_store.append_jsonl(conversation, {"role": "user", "content": message, "turn_id": user_turn.turn_id})

        events: list[tuple[str, dict[str, Any]]] = [("turn_started", {"conversation_id": conversation_id})]
        if token.cancelled:
            assistant_turn = self.session_store.append_turn(
                conversation_id,
                role="assistant",
                content={},
                status="cancelled",
                cancel_reason=token.reason,
            )
            events.append(("turn_cancelled", {"turn_id": assistant_turn.turn_id, "reason": token.reason}))
            return events

        history = self.session_store.load_history(conversation)
        messages = [Message(role=item["role"], content=str(item["content"])) for item in history if "role" in item and "content" in item]
        messages.append(Message(role="user", content=message))
        response = self.provider.generate(messages, tools=self.tool_registry.describe())

        assistant_turn = self.session_store.append_turn(
            conversation_id,
            role="assistant",
            content={"text": response.content},
            tool_calls=[call.to_provider_payload() for call in response.tool_calls],
            status="completed",
        )
        self.session_store.append_jsonl(
            conversation,
            {"role": "assistant", "content": response.content, "turn_id": assistant_turn.turn_id},
        )
        events.append(("llm_delta", {"delta": response.content}))
        for call in response.tool_calls:
            events.append(("tool_call", {"name": call.name, "arguments": call.arguments}))
        events.append(("llm_final", {"content": response.content}))
        events.append(("turn_completed", {"turn_id": assistant_turn.turn_id, "status": "completed"}))
        self.active_tokens.pop(conversation_id, None)
        return events

    def confirm_turn(self, conversation_id: str) -> dict[str, Any]:
        return {"conversation_id": conversation_id, "confirmed": True}

    def cancel_turn(self, conversation_id: str) -> dict[str, Any]:
        token = self.active_tokens.get(conversation_id)
        if token is None:
            return {"conversation_id": conversation_id, "cancelled": False}
        token.cancel("operator_cancelled")
        return {"conversation_id": conversation_id, "cancelled": True}
