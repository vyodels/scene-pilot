from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from queue import Queue
from threading import Thread
import time
from typing import Any, cast

from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.assistant.conversation import ConversationService
from recruit_agent.assistant.session_store import AssistantSessionStore
from recruit_agent.kernel.kernel import AgentKernel
from recruit_agent.memory.service import MemoryService
from recruit_agent.runtime.limits import TurnLimits
from recruit_agent.runtime.models import CancellationToken, GoalRef, GuardVerdict, InputEnvelope, Message, Observation, RoundOutcome, ToolCall


@dataclass(slots=True)
class ActiveTurn:
    conversation_id: str
    turn_id: str
    token: CancellationToken
    queue: Queue[tuple[str, dict[str, Any]] | None]
    worker: Thread


@dataclass(slots=True)
class AssistantAgent:
    kernel: AgentKernel
    session_factory: sessionmaker[Session]
    session_store: AssistantSessionStore
    turn_limits: TurnLimits = field(default_factory=TurnLimits)
    active_turns: dict[str, ActiveTurn] = field(default_factory=dict)
    conversations: ConversationService = field(init=False)
    _assistant_guard_registered: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.conversations = ConversationService(self.session_store)
        self._register_assistant_guard()

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
        token = CancellationToken()
        event_queue: Queue[tuple[str, dict[str, Any]] | None] = Queue()
        worker = Thread(
            target=self._execute_turn,
            args=(conversation_id, conversation.id, user_turn.turn_id, assistant_turn.turn_id, message, None, token, event_queue),
            daemon=True,
        )
        self.active_turns[conversation_id] = ActiveTurn(
            conversation_id=conversation_id,
            turn_id=assistant_turn.turn_id,
            token=token,
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
                active.token.cancel("sse_disconnected")

    def confirm_turn(self, conversation_id: str) -> dict[str, Any]:
        pending_turn = self.session_store.latest_pending_turn(conversation_id)
        if pending_turn is None:
            return {"conversation_id": conversation_id, "confirmed": False}
        conversation = self.session_store.get_session(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")

        recovery_turn = self.session_store.append_turn(
            conversation_id,
            role="assistant",
            content={},
            status="running",
            turn_metadata={"recovery_of_turn_id": pending_turn.turn_id},
        )
        tool_calls = [ToolCall.from_payload(payload) for payload in list(pending_turn.tool_calls or [])]
        token = CancellationToken()
        events: list[tuple[str, dict[str, Any]]] = []
        outcome = self._run_shared_kernel_turn_loop(
            conversation_id=conversation_id,
            conversation_pk=conversation.id,
            message=None,
            cancel_token=token,
            event_sink=lambda event, data: events.append((event, data)),
            seed_tool_calls=tool_calls,
        )
        tool_results = [_serialize_tool_result(item) for item in outcome.tool_results]
        status = _assistant_status(outcome)
        self.session_store.update_turn(
            recovery_turn.turn_id,
            content={"text": outcome.final_output or ""},
            tool_calls=list(outcome.metadata.get("pending_tool_calls") or []),
            tool_results=tool_results,
            status=status,
            cancel_reason=token.reason if status == "cancelled" else None,
            turn_metadata={"recovery_of_turn_id": pending_turn.turn_id, "events": [event for event, _data in events]},
        )
        self.session_store.append_jsonl(
            conversation,
            {
                "role": "assistant",
                "content": outcome.final_output,
                "turn_id": recovery_turn.turn_id,
                "recovery_of_turn_id": pending_turn.turn_id,
            },
        )
        return {
            "conversation_id": conversation_id,
            "confirmed": True,
            "recovery_turn_id": recovery_turn.turn_id,
            "status": status,
            "final_output": outcome.final_output,
        }

    def cancel_turn(self, conversation_id: str) -> dict[str, Any]:
        active = self.active_turns.get(conversation_id)
        if active is None:
            return {"conversation_id": conversation_id, "cancelled": False}
        active.token.cancel("operator_cancelled")
        active.queue.put(
            (
                "turn.cancelling",
                {
                    "conversation_id": conversation_id,
                    "turn_id": active.turn_id,
                    "reason": active.token.reason,
                },
            )
        )
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
        seed_tool_calls: list[ToolCall] | None,
        token: CancellationToken,
        event_queue: Queue[tuple[str, dict[str, Any]] | None],
    ) -> None:
        def _emit(event: str, payload: dict[str, Any]) -> None:
            event_queue.put((event, payload))

        _emit("turn.started", {"conversation_id": conversation_id, "turn_id": assistant_turn_id})
        try:
            outcome = self._run_shared_kernel_turn_loop(
                conversation_id=conversation_id,
                conversation_pk=conversation_pk,
                message=message,
                cancel_token=token,
                event_sink=_emit,
                seed_tool_calls=seed_tool_calls,
                exclude_turn_id=user_turn_id,
            )
            tool_results = [_serialize_tool_result(item) for item in outcome.tool_results]
            status = _assistant_status(outcome)
            tool_calls = list(outcome.metadata.get("pending_tool_calls") or [])
            if not tool_calls:
                tool_calls = [call.to_provider_payload() for call in outcome.tool_calls]
            self.session_store.update_turn(
                assistant_turn_id,
                content={"text": outcome.final_output or ""},
                tool_calls=tool_calls,
                tool_results=tool_results,
                status=status,
                cancel_reason=token.reason if status == "cancelled" else None,
            )
            conversation = self.session_store.get_session(conversation_id)
            if conversation is not None:
                compaction_event = self.session_store.append_jsonl(
                    conversation,
                    {
                        "role": "assistant",
                        "content": outcome.final_output,
                        "turn_id": assistant_turn_id,
                        "status": status,
                        "tool_calls": tool_calls,
                    },
                )
                if compaction_event is not None:
                    _emit("compacted", compaction_event)
            if status == "waiting_human":
                _emit(
                    "turn.waiting_human",
                    {
                        "turn_id": assistant_turn_id,
                        "pending_tool_calls": tool_calls,
                    },
                )
            elif status == "cancelled":
                _emit("turn.cancelled", {"turn_id": assistant_turn_id, "reason": token.reason})
            elif status == "completed":
                _emit("turn.completed", {"turn_id": assistant_turn_id, "status": status})
            else:
                _emit("turn.failed", {"turn_id": assistant_turn_id, "status": status, "reason": outcome.escalate_reason})
        except Exception as exc:
            self.session_store.update_turn(
                assistant_turn_id,
                content={},
                status="failed",
                turn_metadata={"error": str(exc)},
            )
            _emit("turn.failed", {"turn_id": assistant_turn_id, "error": str(exc)})
        finally:
            self.active_turns.pop(conversation_id, None)
            event_queue.put(None)

    def _run_shared_kernel_turn_loop(
        self,
        *,
        conversation_id: str,
        conversation_pk: str,
        message: str | None,
        cancel_token: CancellationToken,
        event_sink: Any,
        seed_tool_calls: list[ToolCall] | None = None,
        exclude_turn_id: str | None = None,
    ) -> RoundOutcome:
        conversation = self.session_store.get_session(conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {conversation_id}")
        with self.session_factory() as session:
            memory_service = MemoryService(session)
            goal = GoalRef(
                goal_id=conversation_id,
                scope_kind="conversation",
                scope_ref=conversation_id,
                goal_text="Respond to the user's request using the shared kernel.",
                constraints={
                    "conversation_pk": conversation_pk,
                    "memory_scope_kind": "global",
                    "memory_scope_ref": conversation.user_id,
                    "agent_profile_id": "assistant",
                    "source_kind": "assistant",
                    "persist_memory": False,
                },
            )
            history_messages = self._history_messages(conversation, exclude_turn_id=exclude_turn_id)
            current_input = message
            current_seed_tool_calls = list(seed_tool_calls or [])
            round_seq = 0
            started_at = time.monotonic()
            last_outcome = RoundOutcome(status="continue", gate_signal="continue")

            while True:
                if cancel_token.is_cancelled():
                    last_outcome = RoundOutcome(status="cancelled", gate_signal="paused")
                    break
                if self.turn_limits.max_rounds_per_turn is not None and round_seq >= self.turn_limits.max_rounds_per_turn:
                    last_outcome = RoundOutcome(
                        status="continue",
                        gate_signal="budget_exhausted",
                        final_output=last_outcome.final_output,
                    )
                    break
                if (
                    self.turn_limits.turn_timeout_seconds is not None
                    and time.monotonic() - started_at >= self.turn_limits.turn_timeout_seconds
                ):
                    last_outcome = RoundOutcome(
                        status="continue",
                        gate_signal="budget_exhausted",
                        final_output=last_outcome.final_output,
                    )
                    break

                round_seq += 1
                observation = Observation(
                    world_snapshot={
                        "conversation_id": conversation_id,
                        "assistant_id": conversation.assistant_id,
                        "context_summary": memory_service.fetch_session_summary(conversation_pk),
                        "assistant_confirmation_enabled": True,
                    },
                    scope_kind="conversation",
                    scope_ref=conversation_id,
                    recent_events=memory_service.fetch_recent_events(conversation_id=conversation_id, limit=8),
                    available_tools=sorted(self.kernel.tool_registry.tools.keys()),
                    available_skills=[],
                    available_mcps=[],
                    hash=conversation_id,
                    input=InputEnvelope(
                        history_messages=list(history_messages),
                        input_message=current_input,
                        seed_tool_calls=list(current_seed_tool_calls),
                    ),
                )
                last_outcome = self.kernel.run_round(
                    goal=goal,
                    observation=observation,
                    limits=self.kernel.limits,
                    memory_service=memory_service,
                    learning_writer=self.kernel.learning_writer,
                    cancel_token=cancel_token,
                    event_sink=event_sink,
                )
                history_messages = list(last_outcome.metadata.get("history_messages") or [])
                current_input = None
                current_seed_tool_calls = []
                event_sink(
                    "round.completed",
                    {
                        "round_seq": round_seq,
                        "status": last_outcome.status,
                        "gate_signal": last_outcome.gate_signal,
                    },
                )
                if last_outcome.final_output:
                    event_sink("llm_final", {"content": last_outcome.final_output, "round_seq": round_seq})
                if last_outcome.status == "cancelled" or last_outcome.gate_signal not in {None, "continue"}:
                    break
            return last_outcome

    def _history_messages(self, conversation: Any, *, exclude_turn_id: str | None) -> list[Message]:
        messages: list[Message] = []
        for item in self.session_store.load_history(conversation):
            role = str(item.get("role") or "").strip()
            if role not in {"user", "assistant", "tool"}:
                continue
            if exclude_turn_id is not None and item.get("turn_id") == exclude_turn_id:
                continue
            messages.append(Message(role=cast(Any, role), content=str(item.get("content") or "")))
        return messages

    def _register_assistant_guard(self) -> None:
        if self._assistant_guard_registered:
            return

        def _assistant_confirmation(tool_name: str, arguments: dict[str, Any], observation: Observation) -> GuardVerdict:
            if observation.scope_kind != "conversation":
                return GuardVerdict(allowed=True)
            if not bool(observation.world_snapshot.get("assistant_confirmation_enabled")):
                return GuardVerdict(allowed=True)
            tool = self.kernel.tool_registry.tools.get(tool_name)
            if tool is None:
                return GuardVerdict(allowed=True)
            if bool(tool.metadata.get("requires_confirmation")) or tool.external_target or bool(arguments.get("requires_confirmation")):
                return GuardVerdict(allowed=False, reason="pending_confirmation", severity="waiting_human")
            return GuardVerdict(allowed=True)

        self.kernel.plugin_host.register_guard_check("assistant_confirmation", _assistant_confirmation)
        self._assistant_guard_registered = True


def _assistant_status(outcome: RoundOutcome) -> str:
    if outcome.status == "cancelled" or outcome.gate_signal == "paused":
        return "cancelled"
    if outcome.status == "wait_human" or outcome.gate_signal == "wait_human":
        return "waiting_human"
    if outcome.status == "complete" or outcome.gate_signal == "goal_done":
        return "completed"
    if outcome.status == "escalate" or outcome.gate_signal == "escalate":
        return "failed"
    if outcome.gate_signal == "budget_exhausted":
        return "failed"
    return "completed"


def _serialize_tool_result(result: Any) -> dict[str, Any]:
    return {
        "tool_name": result.tool_name,
        "output": result.output,
        "is_error": result.is_error,
        "arguments": dict(result.arguments or {}),
        "metadata": dict(result.metadata or {}),
    }
