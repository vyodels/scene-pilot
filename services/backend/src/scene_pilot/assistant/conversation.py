from __future__ import annotations

from scene_pilot.assistant.session_store import AssistantSessionStore
from scene_pilot.models.domain import ConversationSession


class ConversationService:
    def __init__(self, store: AssistantSessionStore) -> None:
        self.store = store

    def create(self, *, user_id: str, title: str | None = None) -> ConversationSession:
        return self.store.create_session(user_id=user_id, title=title)

    def list(self, *, user_id: str | None = None) -> list[ConversationSession]:
        return self.store.list_sessions(user_id=user_id)

    def get(self, conversation_id: str) -> ConversationSession | None:
        return self.store.get_session(conversation_id)
