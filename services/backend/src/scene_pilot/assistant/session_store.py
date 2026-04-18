from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.models.domain import ConversationSession, ConversationTurn


class AssistantSessionStore:
    def __init__(self, *, session_factory: sessionmaker[Session], base_dir: Path) -> None:
        self.session_factory = session_factory
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, *, user_id: str, title: str | None = None) -> ConversationSession:
        with self.session_factory() as session:
            conversation = ConversationSession(
                user_id=user_id,
                title=title,
                assistant_id="assistant",
                assistant_assembly_id="assistant-default",
                jsonl_path=str(self.base_dir / f"{user_id}-{len(list(self.base_dir.glob('*.jsonl')))+1}.jsonl"),
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            Path(conversation.jsonl_path).touch()
            return conversation

    def list_sessions(self, *, user_id: str | None = None) -> list[ConversationSession]:
        with self.session_factory() as session:
            stmt = select(ConversationSession).order_by(ConversationSession.updated_at.desc(), ConversationSession.id.asc())
            if user_id is not None:
                stmt = stmt.where(ConversationSession.user_id == user_id)
            return list(session.scalars(stmt).all())

    def get_session(self, conversation_id: str) -> ConversationSession | None:
        with self.session_factory() as session:
            stmt = select(ConversationSession).where(ConversationSession.conversation_id == conversation_id)
            return session.scalars(stmt).first()

    def delete_session(self, conversation_id: str) -> bool:
        with self.session_factory() as session:
            conversation = session.scalars(select(ConversationSession).where(ConversationSession.conversation_id == conversation_id)).first()
            if conversation is None:
                return False
            jsonl_path = Path(conversation.jsonl_path)
            session.delete(conversation)
            session.commit()
            if jsonl_path.exists():
                jsonl_path.unlink()
            return True

    def append_jsonl(self, conversation: ConversationSession, entry: dict[str, Any]) -> None:
        path = Path(conversation.jsonl_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def load_history(self, conversation: ConversationSession) -> list[dict[str, Any]]:
        path = Path(conversation.jsonl_path)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def append_turn(
        self,
        conversation_id: str,
        *,
        role: str,
        content: dict[str, Any],
        tool_calls: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        status: str = "completed",
        cancel_reason: str | None = None,
    ) -> ConversationTurn:
        with self.session_factory() as session:
            conversation = session.scalars(select(ConversationSession).where(ConversationSession.conversation_id == conversation_id)).first()
            if conversation is None:
                raise KeyError(f"unknown conversation: {conversation_id}")
            next_seq = int(
                session.scalar(
                    select(func.max(ConversationTurn.seq)).where(ConversationTurn.conversation_pk == conversation.id)
                )
                or 0
            ) + 1
            turn = ConversationTurn(
                conversation_pk=conversation.id,
                seq=next_seq,
                role=role,
                content=content,
                tool_calls=list(tool_calls or []),
                tool_results=list(tool_results or []),
                status=status,
                cancel_reason=cancel_reason,
            )
            session.add(turn)
            session.commit()
            session.refresh(turn)
            return turn
