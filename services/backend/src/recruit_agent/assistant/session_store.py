from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.db.base import utcnow
from recruit_agent.models.domain import CompactionEvent, ConversationSession, ConversationTurn


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
                started_at=utcnow(),
                last_active_at=utcnow(),
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

    def append_jsonl(self, conversation: ConversationSession, entry: dict[str, Any]) -> dict[str, Any] | None:
        path = Path(conversation.jsonl_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return self._refresh_compaction(conversation.conversation_id)

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
        turn_metadata: dict[str, Any] | None = None,
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
                cancelled_at=utcnow() if status == "cancelled" else None,
                turn_metadata=dict(turn_metadata or {}),
            )
            session.add(turn)
            conversation.last_active_at = utcnow()
            session.commit()
            session.refresh(turn)
            return turn

    def update_turn(
        self,
        turn_id: str,
        *,
        content: dict[str, Any] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        status: str | None = None,
        cancel_reason: str | None = None,
        turn_metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn:
        with self.session_factory() as session:
            turn = session.scalars(select(ConversationTurn).where(ConversationTurn.turn_id == turn_id)).first()
            if turn is None:
                raise KeyError(f"unknown turn: {turn_id}")
            if content is not None:
                turn.content = dict(content)
            if tool_calls is not None:
                turn.tool_calls = list(tool_calls)
            if tool_results is not None:
                turn.tool_results = list(tool_results)
            if status is not None:
                turn.status = status
                if status == "cancelled":
                    turn.cancelled_at = utcnow()
            if cancel_reason is not None:
                turn.cancel_reason = cancel_reason
            if turn_metadata is not None:
                merged = dict(turn.turn_metadata or {})
                merged.update(turn_metadata)
                turn.turn_metadata = merged
            conversation = session.get(ConversationSession, turn.conversation_pk)
            if conversation is not None:
                conversation.last_active_at = utcnow()
            session.commit()
            session.refresh(turn)
            return turn

    def list_turns(self, conversation_id: str) -> list[ConversationTurn]:
        with self.session_factory() as session:
            conversation = session.scalars(select(ConversationSession).where(ConversationSession.conversation_id == conversation_id)).first()
            if conversation is None:
                return []
            stmt = select(ConversationTurn).where(ConversationTurn.conversation_pk == conversation.id).order_by(ConversationTurn.seq.asc())
            return list(session.scalars(stmt).all())

    def latest_pending_turn(self, conversation_id: str) -> ConversationTurn | None:
        with self.session_factory() as session:
            conversation = session.scalars(select(ConversationSession).where(ConversationSession.conversation_id == conversation_id)).first()
            if conversation is None:
                return None
            stmt = (
                select(ConversationTurn)
                .where(
                    ConversationTurn.conversation_pk == conversation.id,
                    ConversationTurn.role == "assistant",
                    ConversationTurn.status == "waiting_human",
                )
                .order_by(ConversationTurn.seq.desc(), ConversationTurn.id.desc())
            )
            return session.scalars(stmt).first()

    def get_turn(self, turn_id: str) -> ConversationTurn | None:
        with self.session_factory() as session:
            return session.scalars(select(ConversationTurn).where(ConversationTurn.turn_id == turn_id)).first()

    def _refresh_compaction(self, conversation_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            conversation = session.scalars(select(ConversationSession).where(ConversationSession.conversation_id == conversation_id)).first()
            if conversation is None:
                return None
            path = Path(conversation.jsonl_path)
            history = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
            token_count = sum(len(str(item.get("content") or "") .split()) for item in history)
            conversation.messages_token_count = token_count
            compacted_payload: dict[str, Any] | None = None
            if len(history) >= 6:
                summary_parts = [
                    f"{item.get('role')}: {str(item.get('content') or '')[:120]}"
                    for item in history[-4:]
                    if item.get("role")
                ]
                summary = " | ".join(summary_parts)
                if summary and summary != conversation.context_summary:
                    tokens_after = len(summary.split())
                    compacted_payload = {
                        "conversation_id": conversation.conversation_id,
                        "summary": summary,
                        "summary_digest": summary[:255],
                        "tokens_before": conversation.messages_token_count,
                        "tokens_after": tokens_after,
                        "items_before": len(history),
                        "items_after": min(len(history), 4),
                    }
                    session.add(
                        CompactionEvent(
                            level="conversation",
                            target_ref=conversation.conversation_id,
                            tokens_before=conversation.messages_token_count,
                            tokens_after=tokens_after,
                            items_before=len(history),
                            items_after=min(len(history), 4),
                            summary_digest=summary[:255],
                            triggered_by="assistant-session-store",
                        )
                    )
                conversation.context_summary = summary
                conversation.last_compact_at = utcnow()
            conversation.last_active_at = utcnow()
            session.commit()
            return compacted_payload
