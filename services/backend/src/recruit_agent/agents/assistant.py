from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from queue import Queue
from threading import Thread
from typing import Any, cast

from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.agent_runtime.engine import InteractionEngine, InteractionEngineConfig
from recruit_agent.agent_runtime.types import InteractionOutput, LLMMessage, LLMProvider
from recruit_agent.assistant.conversation import ConversationService
from recruit_agent.assistant.session_store import AssistantSessionStore
from recruit_agent.memory.filesystem import MemoryFileStore
from recruit_agent.models.domain import RecruitAgentProfile
from recruit_agent.product_adapters.limits import TurnLimits
from recruit_agent.product_adapters.context_builder import build_assistant_turn_context
from recruit_agent.plugins.host import PluginHost
from recruit_agent.capabilities.tools import ToolRegistry


@dataclass(slots=True)
class ActiveTurn:
    conversation_id: str
    turn_id: str
    queue: Queue[tuple[str, dict[str, Any]] | None]
    worker: Thread
    engine: InteractionEngine | None = None
    cancel_reason: str | None = None


@dataclass(slots=True)
class AssistantAdapter:
    provider: LLMProvider
    tool_registry: ToolRegistry
    plugin_host: PluginHost
    session_factory: sessionmaker[Session]
    session_store: AssistantSessionStore
    memory_file_store: MemoryFileStore | None = None
    turn_limits: TurnLimits = field(default_factory=TurnLimits)
    max_history_messages: int | None = None
    active_turns: dict[str, ActiveTurn] = field(default_factory=dict)
    pending_permission_engines: dict[str, InteractionEngine] = field(default_factory=dict)
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

    def run_turn_stream(self, conversation_id: str, message: str) -> Iterator[tuple[str, dict[str, Any]]]:
        conversation = self.session_store.get_session(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")

        user_turn = self.session_store.append_turn(
            conversation_id,
            role="user",
            content={"text": message},
            turn_metadata={"input_kind": "message"},
        )
        self.session_store.append_jsonl(
            conversation,
            {"role": "user", "content": message, "turn_id": user_turn.turn_id},
        )

        assistant_turn = self.session_store.append_turn(
            conversation_id,
            role="assistant",
            content={},
            status="running",
        )
        event_queue: Queue[tuple[str, dict[str, Any]] | None] = Queue()
        worker = Thread(
            target=self._execute_turn,
            args=(conversation_id, conversation.id, user_turn.turn_id, assistant_turn.turn_id, message, event_queue),
            daemon=True,
        )
        self.active_turns[conversation_id] = ActiveTurn(
            conversation_id=conversation_id,
            turn_id=assistant_turn.turn_id,
            queue=event_queue,
            worker=worker,
        )
        worker.start()
        try:
            while True:
                item = event_queue.get()
                if item is None:
                    break
                yield item
        finally:
            active = self.active_turns.get(conversation_id)
            if active is not None and active.turn_id == assistant_turn.turn_id and active.worker.is_alive():
                active.cancel_reason = "sse_disconnected"
                if active.engine is not None:
                    active.engine.interrupt()

    def confirm_turn(self, conversation_id: str) -> dict[str, Any]:
        pending_turn = self.session_store.latest_pending_turn(conversation_id)
        if pending_turn is None:
            return {"conversation_id": conversation_id, "confirmed": False}
        conversation = self.session_store.get_session(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")

        events: list[tuple[str, dict[str, Any]]] = []
        engine = self.pending_permission_engines.pop(conversation_id, None)
        if engine is None:
            raise RuntimeError("Pending runtime permission state is not available for this conversation")
        result = self._resolve_confirmed_permission(
            engine=engine,
            conversation_id=conversation_id,
            event_sink=lambda event, data: events.append((event, data)),
        )
        if result["status"] == "waiting_human":
            self.pending_permission_engines[conversation_id] = engine
        status = result["status"]
        self.session_store.update_turn(
            pending_turn.turn_id,
            content={"text": result["final_output"] or ""},
            tool_calls=list(pending_turn.tool_calls or []),
            tool_results=list(result["tool_results"]),
            status=status,
            turn_metadata={"confirmed": True, "events": [event for event, _data in events]},
        )
        self.session_store.append_jsonl(
            conversation,
            {
                "role": "assistant",
                "content": result["final_output"],
                "turn_id": pending_turn.turn_id,
                "confirmed": True,
            },
        )
        return {
            "conversation_id": conversation_id,
            "confirmed": True,
            "turn_id": pending_turn.turn_id,
            "status": status,
            "final_output": result["final_output"],
        }

    def cancel_turn(self, conversation_id: str) -> dict[str, Any]:
        active = self.active_turns.get(conversation_id)
        if active is None:
            return {"conversation_id": conversation_id, "cancelled": False}
        active.cancel_reason = "operator_cancelled"
        if active.engine is not None:
            active.engine.interrupt()
        active.worker.join(timeout=0.2)
        return {
            "conversation_id": conversation_id,
            "cancelled": True,
            "turn_id": active.turn_id,
            "active": active.worker.is_alive(),
        }

    def _execute_turn(
        self,
        conversation_id: str,
        conversation_pk: str,
        user_turn_id: str,
        assistant_turn_id: str,
        message: str | None,
        event_queue: Queue[tuple[str, dict[str, Any]] | None],
    ) -> None:
        def _emit_output(output: InteractionOutput) -> None:
            event_queue.put((output.type, _runtime_output_payload(output)))

        try:
            agent_profile_id = self._agent_profile_id()
            memory_entries = []
            if self.memory_file_store is not None:
                memory_entries = _read_memory_file_index_entries(
                    self.memory_file_store,
                    scope_kind="conversation",
                    scope_ref=conversation_id,
                    agent_profile_id=agent_profile_id,
                )
            adapter_context = build_assistant_turn_context(
                history_messages=self._runtime_history_messages(conversation_id, exclude_turn_id=user_turn_id),
                user_message=message or "",
                agent_profile_id=agent_profile_id,
                memory_entries=memory_entries,
            )
            engine = InteractionEngine(
                InteractionEngineConfig(
                    conversation_id=conversation_id,
                    provider=cast(Any, self.provider),
                    tools=_scoped_tool_registry(self.tool_registry, agent_profile_id).to_agent_runtime_tools(),
                    initial_messages=adapter_context.initial_messages,
                    max_llm_invocations=self.turn_limits.max_llm_invocations or 12,
                    max_history_messages=self.max_history_messages,
                )
            )
            active = self.active_turns.get(conversation_id)
            if active is not None and active.turn_id == assistant_turn_id:
                active.engine = engine
                if active.cancel_reason:
                    engine.interrupt()
            final_output = ""
            status = "completed"
            tool_results: list[dict[str, Any]] = []
            tool_calls: list[dict[str, Any]] = []
            for output in engine.submitMessage(adapter_context.turn_input):
                _emit_output(output)
                if output.type == "assistant_message_completed":
                    final_output = str(output.data.get("message") or "")
                elif output.type == "tool_event":
                    data = dict(output.data)
                    if data.get("kind") == "tool_result_ready":
                        tool_results.append(
                            {
                                "tool_name": data.get("tool_name"),
                                "output": data.get("content"),
                                "is_error": data.get("is_error", False),
                                "metadata": {},
                            }
                        )
                    elif data.get("kind") in {"tool_use_completed", "tool_call_started"}:
                        tool_calls.append(data)
                elif output.type == "turn_interrupted":
                    status = "cancelled"
                elif output.type == "turn_failed":
                    status = "failed"
                elif output.type == "permission_requested":
                    status = "waiting_human"
                    tool_calls = [_permission_payload(dict(output.data))]
                    self.pending_permission_engines[conversation_id] = engine
            self.session_store.update_turn(
                assistant_turn_id,
                content={"text": final_output},
                tool_calls=tool_calls,
                tool_results=tool_results,
                status=status,
                cancel_reason=active.cancel_reason if active is not None and status == "cancelled" else None,
            )
            conversation = self.session_store.get_session(conversation_id)
            if conversation is not None:
                compaction_event = self.session_store.append_jsonl(
                    conversation,
                    {
                        "role": "assistant",
                        "content": final_output,
                        "turn_id": assistant_turn_id,
                        "status": status,
                        "tool_calls": tool_calls,
                    },
                )
                if compaction_event is not None:
                    pass
        except Exception as exc:
            self.session_store.update_turn(
                assistant_turn_id,
                content={},
                status="failed",
                turn_metadata={"error": str(exc)},
            )
            event_queue.put(("turn_failed", {"conversation_id": conversation_id, "turn_id": assistant_turn_id, "error": str(exc)}))
        finally:
            if conversation_id in self.pending_permission_engines:
                active_engine = self.pending_permission_engines[conversation_id]
                if active_engine.pending_permission is None:
                    self.pending_permission_engines.pop(conversation_id, None)
            self.active_turns.pop(conversation_id, None)
            event_queue.put(None)

    def _agent_profile_id(self) -> str | None:
        with self.session_factory() as session:
            profile = session.query(RecruitAgentProfile).filter(RecruitAgentProfile.agent_key == "assistant").first()
            return None if profile is None else str(profile.id)

    def _resolve_confirmed_permission(
        self,
        *,
        engine: InteractionEngine,
        conversation_id: str,
        event_sink: Any,
    ) -> dict[str, Any]:
        conversation = self.session_store.get_session(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")
        tool_results: list[dict[str, Any]] = []
        final_output = ""
        status = "completed"
        for output in engine.resolvePermission(approved=True):
            event_sink(output.type, _runtime_output_payload(output))
            if output.type == "assistant_message_completed":
                final_output = str(output.data.get("message") or "")
            elif output.type == "tool_event":
                data = dict(output.data)
                if data.get("kind") == "tool_result_ready":
                    tool_results.append(
                        {
                            "tool_name": data.get("tool_name"),
                            "output": data.get("content"),
                            "is_error": data.get("is_error", False),
                            "metadata": {},
                        }
                    )
            elif output.type == "permission_requested":
                status = "waiting_human"
            elif output.type == "turn_interrupted":
                status = "cancelled"
            elif output.type == "turn_failed":
                status = "failed"
        return {"status": status, "final_output": final_output, "tool_results": tool_results}

    def _runtime_history_messages(self, conversation_id: str, *, exclude_turn_id: str | None) -> list[LLMMessage]:
        conversation = self.session_store.get_session(conversation_id)
        if conversation is None:
            return []
        messages: list[LLMMessage] = []
        for item in self.session_store.load_history(conversation):
            role = str(item.get("role") or "").strip()
            if role not in {"system", "user", "assistant", "tool"}:
                continue
            if exclude_turn_id is not None and item.get("turn_id") == exclude_turn_id:
                continue
            messages.append(LLMMessage(role=cast(Any, role), content=str(item.get("content") or "")))
        return messages


def _runtime_output_payload(output: InteractionOutput) -> dict[str, Any]:
    return {
        "type": output.type,
        "conversation_id": output.conversation_id,
        "turn_id": output.turn_id,
        "seq": output.seq,
        "data": dict(output.data or {}),
    }


def _permission_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": str(data.get("tool_name") or ""),
        "tool_use_id": str(data.get("tool_use_id") or ""),
        "tool_call_id": str(data.get("tool_call_id") or ""),
        "input": dict(data.get("input") or {}),
        "reason": str(data.get("reason") or "pending_confirmation"),
    }


def _read_memory_file_index_entries(
    memory_file_store: MemoryFileStore,
    *,
    scope_kind: str,
    scope_ref: str,
    agent_profile_id: str | None,
) -> list[dict[str, Any]]:
    try:
        entries: list[dict[str, Any]] = []
        for item in memory_file_store.list_files(scope_kind=scope_kind, scope_ref=scope_ref, agent_profile_id=agent_profile_id)[:12]:
            content = memory_file_store.read_file(
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                agent_profile_id=agent_profile_id,
                path=str(item["path"]),
            ).get("content", "")
            entries.append(
                {
                    "memory_item_id": item["path"],
                    "kind": "memory_file",
                    "summary": _first_non_empty_memory_line(str(content or "")) or item["path"],
                    "content": {"path": item["path"], "preview": str(content or "").strip()[:500]},
                    "size": item.get("size"),
                    "updated_at": item.get("updated_at"),
                }
            )
        return entries
    except Exception:
        return []


def _first_non_empty_memory_line(text: str) -> str | None:
    for line in str(text or "").splitlines():
        stripped = line.strip(" #-\t")
        if stripped:
            return stripped[:240]
    return None


def _scoped_tool_registry(registry: ToolRegistry, agent_profile_id: str | None) -> ToolRegistry:
    if not agent_profile_id:
        return registry
    scoped = ToolRegistry()
    for tool in registry.tools.values():
        cloned = tool.clone()
        if cloned.category == "memory":
            original_handler = cloned.handler

            def _handler(arguments: dict[str, Any], *, handler=original_handler) -> Any:
                scoped_arguments = dict(arguments or {})
                scoped_arguments["agent_profile_id"] = agent_profile_id
                return handler(scoped_arguments)

            cloned.handler = _handler
        scoped.register(cloned)
    return scoped
