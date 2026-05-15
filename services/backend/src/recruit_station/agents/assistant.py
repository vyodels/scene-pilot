from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from queue import Queue
from threading import Thread
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from recruit_station.agent_runtime.engine import InteractionEngine
from recruit_station.agent_runtime.types import LLMMessage, LLMProvider
from recruit_station.assistant.conversation import ConversationService
from recruit_station.assistant.session_store import AssistantSessionStore
from recruit_station.memory.filesystem import MemoryFileStore
from recruit_station.models.domain import AgentDefinition, McpServer, Skill
from recruit_station.product_adapters.limits import TurnLimits
from recruit_station.product_adapters.context_builder import build_assistant_turn_context
from recruit_station.product_adapters.agent_runner import AgentTurnStatusDefaults, run_agent_turn, runtime_output_payload
from recruit_station.plugins.host import PluginHost
from recruit_station.capabilities.tools import ToolRegistry
from recruit_station.skills.context import build_skill_context_injections


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
        try:
            definition_context = self._agent_definition_context(message or "")
            agent_definition_id = definition_context["agent_definition_id"]
            memory_entries = []
            if self.memory_file_store is not None:
                memory_entries = _read_memory_file_index_entries(
                    self.memory_file_store,
                    scope_kind="conversation",
                    scope_ref=conversation_id,
                    agent_definition_id=agent_definition_id,
                )
            adapter_context = build_assistant_turn_context(
                history_messages=self._runtime_history_messages(conversation_id, exclude_turn_id=user_turn_id),
                user_message=message or "",
                agent_name=definition_context["agent_name"],
                system_prompt=definition_context["system_prompt"],
                agent_definition_id=agent_definition_id,
                memory_entries=memory_entries,
                available_tools=sorted(self.tool_registry.tools.keys()),
                skill_contexts=definition_context["skill_contexts"],
                available_mcps=definition_context["available_mcps"],
                response_policy=definition_context["response_policy"],
            )
            active = self.active_turns.get(conversation_id)

            def _bind_engine(engine: InteractionEngine) -> None:
                if active is not None and active.turn_id == assistant_turn_id:
                    active.engine = engine
                    if active.cancel_reason:
                        engine.interrupt()

            result = run_agent_turn(
                provider=self.provider,
                tool_registry=self.tool_registry,
                agent_definition_id=agent_definition_id,
                conversation_id=conversation_id,
                initial_messages=adapter_context.initial_messages,
                turn_input=adapter_context.turn_input,
                max_llm_invocations=self.turn_limits.max_llm_invocations or 12,
                max_history_messages=self.max_history_messages,
                output_sink=lambda output: event_queue.put((output.type, runtime_output_payload(output))),
                engine_sink=_bind_engine,
                status_defaults=AgentTurnStatusDefaults(completed_status="completed"),
                include_tool_result_metadata=True,
            )
            if result.status == "waiting_human":
                self.pending_permission_engines[conversation_id] = result.engine
            else:
                self.pending_permission_engines.pop(conversation_id, None)
            self.session_store.update_turn(
                assistant_turn_id,
                content={"text": result.final_output},
                tool_calls=result.tool_calls,
                tool_results=result.tool_results,
                status=result.status,
                cancel_reason=active.cancel_reason if active is not None and result.status == "cancelled" else None,
            )
            conversation = self.session_store.get_session(conversation_id)
            if conversation is not None:
                compaction_event = self.session_store.append_jsonl(
                    conversation,
                    {
                        "role": "assistant",
                        "content": result.final_output,
                        "turn_id": assistant_turn_id,
                        "status": result.status,
                        "tool_calls": result.tool_calls,
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

    def _agent_definition_id(self) -> str | None:
        with self.session_factory() as session:
            definition = session.query(AgentDefinition).filter(AgentDefinition.definition_key == "assistant").first()
            return None if definition is None else str(definition.id)

    def _agent_definition_context(self, task_text: str) -> dict[str, Any]:
        with self.session_factory() as session:
            definition = session.query(AgentDefinition).filter(AgentDefinition.definition_key == "assistant").first()
            prompt_config = dict((definition.prompt_config if definition is not None else {}) or {})
            skills = list(session.query(Skill).filter(Skill.status.in_(("trial", "active"))).order_by(Skill.name.asc(), Skill.skill_id.asc()).all())
            return {
                "agent_definition_id": None if definition is None else str(definition.id),
                "agent_name": str((definition.name if definition is not None else None) or "Assistant"),
                "system_prompt": _definition_system_prompt(definition),
                "response_policy": dict(prompt_config.get("response_policy") or {}),
                "skill_contexts": [
                    item.to_prompt_payload()
                    for item in build_skill_context_injections(
                        skills,
                        query=task_text,
                        task_text=task_text,
                    )
                ],
                "available_mcps": [str(name) for name in session.scalars(select(McpServer.name).order_by(McpServer.name.asc())).all()],
            }

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
        result = run_agent_turn(
            provider=self.provider,
            tool_registry=self.tool_registry,
            agent_definition_id=self._agent_definition_id(),
            conversation_id=conversation_id,
            initial_messages=[],
            turn_input="",
            max_llm_invocations=self.turn_limits.max_llm_invocations or 12,
            existing_engine=engine,
            resolve_permission=True,
            output_sink=lambda output: event_sink(output.type, runtime_output_payload(output)),
            status_defaults=AgentTurnStatusDefaults(completed_status="completed"),
            include_tool_result_metadata=True,
        )
        tool_results.extend(result.tool_results)
        return {"status": result.status, "final_output": result.final_output, "tool_results": tool_results}

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


def _read_memory_file_index_entries(
    memory_file_store: MemoryFileStore,
    *,
    scope_kind: str,
    scope_ref: str,
    agent_definition_id: str | None,
) -> list[dict[str, Any]]:
    try:
        entries: list[dict[str, Any]] = []
        for item in memory_file_store.list_files(scope_kind=scope_kind, scope_ref=scope_ref, agent_definition_id=agent_definition_id)[:12]:
            content = memory_file_store.read_file(
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                agent_definition_id=agent_definition_id,
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


def _definition_system_prompt(definition: AgentDefinition | None) -> str:
    if definition is None:
        return "你是 Assistant 类型的 RecruitStation。你的职责是在聊天界面中与用户协作，清晰解释状态、回答问题，并在高风险动作前等待确认。"
    prompt_config = dict(definition.prompt_config or {})
    return str(
        prompt_config.get("system_prompt")
        or prompt_config.get("systemPrompt")
        or prompt_config.get("prompt")
        or definition.description
        or ""
    )
