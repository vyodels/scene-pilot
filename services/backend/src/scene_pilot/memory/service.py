from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from scene_pilot.memory.retrieve import semantic_filter
from scene_pilot.models.domain import (
    AgentGlobalMemory,
    AgentRun,
    AgentRuntimeEvent,
    CandidatePersonMemory,
    ConversationSession,
    JobDescriptionMemory,
)


class MemoryVersionConflict(RuntimeError):
    pass


@dataclass(slots=True)
class MemoryRecord:
    id: str
    memory_item_id: str | None
    scope_kind: str
    scope_ref: str
    agent_profile_id: str
    kind: str
    summary: str | None
    content: dict[str, Any]
    index_name: str | None
    index_description: str | None
    version: int
    confidence: float
    trust_level: str
    evidence_refs: list[Any]


class MemoryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def index_for_scope(
        self,
        scope_kind: str,
        scope_ref: str,
        *,
        agent_profile_id: str | None = None,
    ) -> list[dict[str, Any]]:
        model: Any = _memory_model(scope_kind)
        stmt = select(model).where(_scope_column(model) == scope_ref)
        if agent_profile_id is not None:
            stmt = stmt.where(model.agent_profile_id == agent_profile_id)
        stmt = stmt.order_by(model.updated_at.desc(), model.id.asc())
        return [self._serialize(record, scope_kind=scope_kind, scope_ref=scope_ref) for record in self.session.scalars(stmt).all()]

    def read(
        self,
        *,
        scope_kind: str,
        scope_ref: str,
        agent_profile_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.index_for_scope(scope_kind, scope_ref, agent_profile_id=agent_profile_id)[:limit]

    def write(
        self,
        *,
        scope_kind: str,
        scope_ref: str,
        agent_profile_id: str,
        memory_item_id: str,
        kind: str,
        index_name: str | None,
        index_description: str | None,
        summary: str | None,
        content: dict[str, Any],
        expected_version: int | None = None,
        confidence: float = 0.5,
        trust_level: str = "unverified",
        evidence_refs: list[Any] | None = None,
    ) -> dict[str, Any]:
        model: Any = _memory_model(scope_kind)
        record: Any = self.session.scalars(select(model).where(model.memory_item_id == memory_item_id)).first()
        if record is None:
            record = model(
                agent_profile_id=agent_profile_id,
                memory_item_id=memory_item_id,
                kind=kind,
                index_name=index_name,
                index_description=index_description,
                summary=summary,
                content=content,
                raw_content=content,
                confidence=confidence,
                trust_level=trust_level,
                evidence_refs=list(evidence_refs or []),
            )
            setattr(record, _scope_attr_name(scope_kind), scope_ref)
            self.session.add(record)
        else:
            if expected_version is not None and int(record.version or 0) != int(expected_version):
                raise MemoryVersionConflict(
                    f"memory item {memory_item_id} expected version {expected_version}, got {record.version}"
                )
            record.kind = kind
            record.index_name = index_name
            record.index_description = index_description
            record.summary = summary
            record.content = content
            record.raw_content = content
            record.confidence = confidence
            record.trust_level = trust_level
            record.evidence_refs = list(evidence_refs or [])
            record.version = int(record.version or 0) + 1
        self.session.commit()
        self.session.refresh(record)
        return self._serialize(record, scope_kind=scope_kind, scope_ref=scope_ref)

    def search_semantic(
        self,
        query: str,
        *,
        scope_kind: str,
        scope_ref: str,
        agent_profile_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        entries = self.index_for_scope(scope_kind, scope_ref, agent_profile_id=agent_profile_id)
        return semantic_filter(entries, query)[:limit]

    def fetch_session_summary(self, conversation_pk: str) -> str | None:
        conversation = self.session.get(ConversationSession, conversation_pk)
        return None if conversation is None else conversation.context_summary

    def fetch_run_context(self, run_pk: str) -> dict[str, Any]:
        run = self.session.get(AgentRun, run_pk)
        return {} if run is None else dict(run.context_manifest or {})

    def set_run_context(self, run_pk: str, context: dict[str, Any]) -> dict[str, Any]:
        run = self.session.get(AgentRun, run_pk)
        if run is None:
            raise KeyError(f"unknown run: {run_pk}")
        run.context_manifest = dict(context)
        self.session.commit()
        self.session.refresh(run)
        return dict(run.context_manifest or {})

    def fetch_recent_events(
        self,
        *,
        run_id: str | None = None,
        conversation_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        stmt = select(AgentRuntimeEvent)
        if run_id is not None:
            stmt = stmt.where(AgentRuntimeEvent.run_id == run_id)
        if conversation_id is not None:
            stmt = stmt.where(AgentRuntimeEvent.conversation_id == conversation_id)
        stmt = stmt.order_by(AgentRuntimeEvent.occurred_at.desc(), AgentRuntimeEvent.id.desc()).limit(limit)
        events = list(self.session.scalars(stmt).all())
        events.reverse()
        return [
            {
                "event_type": event.event_type,
                "source": event.source,
                "message": event.message,
                "tick_id": event.tick_id,
                "turn_id": event.turn_id,
                "conversation_id": event.conversation_id,
                "payload": dict(event.payload or {}),
                "seq": event.seq,
            }
            for event in events
        ]

    def _serialize(self, record: Any, *, scope_kind: str, scope_ref: str) -> dict[str, Any]:
        payload = MemoryRecord(
            id=record.id,
            memory_item_id=record.memory_item_id,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            agent_profile_id=record.agent_profile_id,
            kind=record.kind,
            summary=record.summary,
            content=dict(record.content or {}),
            index_name=record.index_name,
            index_description=record.index_description,
            version=int(record.version or 0),
            confidence=float(record.confidence or 0.0),
            trust_level=record.trust_level,
            evidence_refs=list(record.evidence_refs or []),
        )
        data = asdict(payload)
        data["updated_at"] = record.updated_at
        return data


def _memory_model(scope_kind: str) -> Any:
    normalized = scope_kind.strip().lower()
    if normalized == "candidate":
        return CandidatePersonMemory
    if normalized == "job":
        return JobDescriptionMemory
    if normalized == "global":
        return AgentGlobalMemory
    raise ValueError(f"unsupported memory scope: {scope_kind}")


def _scope_attr_name(scope_kind: str) -> str:
    normalized = scope_kind.strip().lower()
    if normalized == "candidate":
        return "person_id"
    if normalized == "job":
        return "job_description_id"
    if normalized == "global":
        return "agent_profile_id"
    raise ValueError(f"unsupported memory scope: {scope_kind}")


def _scope_column(model: Any) -> Any:
    if model is CandidatePersonMemory:
        return CandidatePersonMemory.person_id
    if model is JobDescriptionMemory:
        return JobDescriptionMemory.job_description_id
    if model is AgentGlobalMemory:
        return AgentGlobalMemory.agent_profile_id
    raise ValueError(f"unsupported memory model: {model}")
