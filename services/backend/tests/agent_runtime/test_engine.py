from __future__ import annotations

from dataclasses import dataclass, field

from recruit_station.agent_runtime.engine import InteractionEngine, InteractionEngineConfig, transcript_from_checkpoint
from recruit_station.agent_runtime.tools import FunctionToolHandler
from recruit_station.agent_runtime.transcript import InMemoryTranscript
from recruit_station.agent_runtime.types import (
    LLMInvocationResult,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    TokenUsage,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolSchema,
    ToolUse,
    TurnContext,
)


@dataclass(slots=True)
class FixtureLLMProvider:
    responses: list[LLMResponse]
    provider_name: str = "test"
    captured_requests: list[LLMRequest] = field(default_factory=list)

    def invoke(self, request: LLMRequest) -> LLMInvocationResult:
        self.captured_requests.append(request)
        return LLMInvocationResult(events=[], response=self.responses.pop(0))


def test_submit_message_completes_with_assistant_output() -> None:
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="hello"),
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )
        ]
    )
    engine = InteractionEngine(InteractionEngineConfig(conversation_id="conv-1", provider=provider))

    outputs = list(engine.submitMessage("hi"))

    assert [item.type for item in outputs if item.type.startswith("turn_")] == ["turn_started", "turn_completed"]
    assert any(item.type == "assistant_message_completed" and item.data["message"] == "hello" for item in outputs)
    assert provider.captured_requests[0].messages[-1].content == "hi"


def test_pre_start_interrupt_is_preserved() -> None:
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="should not run"),
            )
        ]
    )
    engine = InteractionEngine(InteractionEngineConfig(conversation_id="conv-interrupt", provider=provider))

    engine.interrupt()
    outputs = list(engine.submitMessage("hi"))

    assert [item.type for item in outputs if item.type.startswith("turn_")] == ["turn_started", "turn_interrupted"]
    assert provider.captured_requests == []


def test_tool_loop_uses_injected_business_tool_without_bash() -> None:
    tool_use = ToolUse(id="call-1", name="upsert_candidate", input={"name": "Ada"})
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="", tool_uses=[tool_use]),
                tool_uses=[tool_use],
                stop_reason="tool_calls",
            ),
            LLMResponse(
                id="resp-2",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="candidate saved"),
            ),
        ]
    )
    tool = ToolDefinition(
        name="upsert_candidate",
        description="Create or update a candidate.",
        schema=ToolSchema(
            name="upsert_candidate",
            description="Create or update a candidate.",
            input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        ),
        handler=FunctionToolHandler(lambda args: {"candidate_id": "cand-1", **args}),
        metadata={"capabilities": ["candidate", "recruit_write"]},
    )
    engine = InteractionEngine(InteractionEngineConfig(conversation_id="conv-1", provider=provider, tools=[tool]))

    outputs = list(engine.submitMessage("save Ada"))

    assert any(item.type == "tool_event" and item.data["kind"] == "tool_call_started" for item in outputs)
    assert any(item.type == "tool_event" and item.data["kind"] == "tool_result_ready" for item in outputs)
    assert any(item.type == "assistant_message_completed" and item.data["message"] == "candidate saved" for item in outputs)
    second_request = provider.captured_requests[1]
    assert second_request.messages[-1].role == "tool"
    assert "cand-1" in str(second_request.messages[-1].content)


def test_llm_request_and_tool_context_receive_same_abort_signal() -> None:
    tool_use = ToolUse(id="call-1", name="capture_signal", input={})
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="", tool_uses=[tool_use]),
                tool_uses=[tool_use],
                stop_reason="tool_calls",
            ),
            LLMResponse(
                id="resp-2",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="done"),
            ),
        ]
    )
    seen: dict[str, object] = {}

    class CaptureSignalHandler:
        def handle(self, call: ToolCall, context: TurnContext) -> ToolResult:
            seen["abort_signal"] = context.abort_signal
            return ToolResult(
                tool_call_id=call.id,
                tool_use_id=call.tool_use_id,
                name=call.name,
                content={"ok": True},
            )

    tool = ToolDefinition(
        name="capture_signal",
        description="Capture the runtime abort signal.",
        schema=ToolSchema(
            name="capture_signal",
            description="Capture the runtime abort signal.",
            input_schema={"type": "object"},
        ),
        handler=CaptureSignalHandler(),
    )
    engine = InteractionEngine(InteractionEngineConfig(conversation_id="conv-signal", provider=provider, tools=[tool]))

    outputs = list(engine.submitMessage("run tool"))

    assert any(item.type == "turn_completed" for item in outputs)
    assert provider.captured_requests[0].abort_signal is not None
    assert seen["abort_signal"] is provider.captured_requests[0].abort_signal
    assert provider.captured_requests[1].abort_signal is provider.captured_requests[0].abort_signal


def test_interrupt_after_tool_result_prevents_next_llm_invocation() -> None:
    tool_use = ToolUse(id="call-1", name="stop_after_tool", input={})
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="", tool_uses=[tool_use]),
                tool_uses=[tool_use],
                stop_reason="tool_calls",
            ),
            LLMResponse(
                id="resp-2",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="should not run"),
            ),
        ]
    )
    engine_ref: dict[str, InteractionEngine] = {}

    class InterruptingHandler:
        def handle(self, call: ToolCall, context: TurnContext) -> ToolResult:
            engine_ref["engine"].interrupt("stop after tool")
            return ToolResult(
                tool_call_id=call.id,
                tool_use_id=call.tool_use_id,
                name=call.name,
                content={"ok": True},
            )

    tool = ToolDefinition(
        name="stop_after_tool",
        description="Interrupt after returning a tool result.",
        schema=ToolSchema(
            name="stop_after_tool",
            description="Interrupt after returning a tool result.",
            input_schema={"type": "object"},
        ),
        handler=InterruptingHandler(),
    )
    engine = InteractionEngine(InteractionEngineConfig(conversation_id="conv-tool-interrupt", provider=provider, tools=[tool]))
    engine_ref["engine"] = engine

    outputs = list(engine.submitMessage("run tool"))

    assert len(provider.captured_requests) == 1
    assert any(item.type == "tool_event" and item.data["kind"] == "tool_result_ready" for item in outputs)
    assert any(item.type == "turn_interrupted" and item.data["reason"] == "stop after tool" for item in outputs)
    assert not any(item.type == "assistant_message_completed" and item.data["message"] == "should not run" for item in outputs)


def test_permission_resolution_continues_same_runtime_turn() -> None:
    tool_use = ToolUse(id="call-approval", name="send_message", input={"text": "hello"})
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="", tool_uses=[tool_use]),
                tool_uses=[tool_use],
                stop_reason="tool_calls",
            ),
            LLMResponse(
                id="resp-2",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="sent"),
            ),
        ]
    )
    tool = ToolDefinition(
        name="send_message",
        description="Send a message.",
        schema=ToolSchema(
            name="send_message",
            description="Send a message.",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        ),
        handler=FunctionToolHandler(lambda args: {"sent": args["text"]}),
        metadata={"requires_confirmation": True},
    )
    engine = InteractionEngine(InteractionEngineConfig(conversation_id="conv-approval", provider=provider, tools=[tool]))

    first_outputs = list(engine.submitMessage("send hello"))

    permission = next(item for item in first_outputs if item.type == "permission_requested")
    assert engine.pending_permission is not None
    assert permission.turn_id is not None

    continued_outputs = list(engine.resolvePermission(approved=True))

    assert engine.pending_permission is None
    assert any(item.type == "tool_event" and item.data["kind"] == "tool_result_ready" for item in continued_outputs)
    assert any(item.type == "assistant_message_completed" and item.data["message"] == "sent" for item in continued_outputs)
    assert any(item.type == "turn_completed" and item.turn_id == permission.turn_id for item in continued_outputs)
    second_request = provider.captured_requests[1]
    assert second_request.turn_id == permission.turn_id
    assert second_request.messages[-2].role == "assistant"
    assert second_request.messages[-2].tool_uses[0].id == "call-approval"
    assert second_request.messages[-1].role == "tool"
    assert "hello" in str(second_request.messages[-1].content)


def test_permission_resolution_can_resume_from_transcript_checkpoint() -> None:
    tool_use = ToolUse(id="call-approval", name="send_message", input={"text": "hello"})
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="", tool_uses=[tool_use]),
                tool_uses=[tool_use],
                stop_reason="tool_calls",
            ),
            LLMResponse(
                id="resp-2",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="sent"),
            ),
        ]
    )
    tool = ToolDefinition(
        name="send_message",
        description="Send a message.",
        schema=ToolSchema(
            name="send_message",
            description="Send a message.",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        ),
        handler=FunctionToolHandler(lambda args: {"sent": args["text"]}),
        metadata={"requires_confirmation": True},
    )
    engine = InteractionEngine(InteractionEngineConfig(conversation_id="conv-durable", provider=provider, tools=[tool]))

    first_outputs = list(engine.submitMessage("send hello"))
    permission = next(item for item in first_outputs if item.type == "permission_requested")
    checkpoint = engine.checkpoint_state()
    assert checkpoint["pending_permissions"]

    rebuilt = InteractionEngine(
        InteractionEngineConfig(
            conversation_id="conv-durable",
            provider=provider,
            tools=[tool],
            transcript=transcript_from_checkpoint("conv-durable", checkpoint),
        )
    )
    continued_outputs = list(rebuilt.resolvePermission(approved=True))

    assert rebuilt.pending_permission is None
    assert any(item.type == "assistant_message_completed" and item.data["message"] == "sent" for item in continued_outputs)
    assert any(item.type == "turn_completed" and item.turn_id == permission.turn_id for item in continued_outputs)
    assert provider.captured_requests[1].turn_id == permission.turn_id
    assert provider.captured_requests[1].messages[-1].role == "tool"


def test_engine_passes_llm_request_options_to_provider() -> None:
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="done"),
            )
        ]
    )
    engine = InteractionEngine(
        InteractionEngineConfig(
            conversation_id="conv-1",
            provider=provider,
            max_tokens=128,
            temperature=0.3,
            top_p=0.8,
            stop_sequences=["END"],
            tool_choice="auto",
            thinking={"type": "enabled", "budget_tokens": 1024},
            reasoning={"effort": "medium"},
            text_format={"type": "json_object"},
            parallel_tool_calls=False,
            max_tool_calls=2,
            previous_response_id="resp-prev",
            store=False,
            truncation="auto",
            openai_payload_overrides={"service_tier": "flex"},
            anthropic_payload_overrides={"metadata": {"source": "engine-test"}},
        )
    )

    list(engine.submitMessage("hi"))

    request = provider.captured_requests[0]
    assert request.max_tokens == 128
    assert request.temperature == 0.3
    assert request.top_p == 0.8
    assert request.stop_sequences == ["END"]
    assert request.tool_choice == "auto"
    assert request.thinking == {"type": "enabled", "budget_tokens": 1024}
    assert request.reasoning == {"effort": "medium"}
    assert request.text_format == {"type": "json_object"}
    assert request.parallel_tool_calls is False
    assert request.max_tool_calls == 2
    assert request.previous_response_id == "resp-prev"
    assert request.store is False
    assert request.truncation == "auto"
    assert request.openai_payload_overrides == {"service_tier": "flex"}
    assert request.anthropic_payload_overrides == {"metadata": {"source": "engine-test"}}


def test_engine_compacts_model_visible_history_before_request() -> None:
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="done"),
            )
        ]
    )
    initial_messages = [
        LLMMessage(role="user", content="old user one"),
        LLMMessage(role="assistant", content="old assistant one"),
        LLMMessage(role="user", content="old user two"),
        LLMMessage(role="assistant", content="old assistant two"),
        LLMMessage(role="user", content="recent user"),
        LLMMessage(role="assistant", content="recent assistant"),
    ]
    engine = InteractionEngine(
        InteractionEngineConfig(
            conversation_id="conv-compact",
            provider=provider,
            initial_messages=initial_messages,
            max_history_messages=4,
        )
    )

    outputs = list(engine.submitMessage("current user"))

    request_messages = provider.captured_requests[0].messages
    assert len(request_messages) == 4
    assert request_messages[0].role == "system"
    assert request_messages[0].metadata["kind"] == "context_compaction_summary"
    assert "old user one" in str(request_messages[0].content)
    assert [message.content for message in request_messages[1:]] == ["recent user", "recent assistant", "current user"]
    assert any(
        output.type == "runtime_event"
        and output.data["kind"] == "context_compacted"
        and output.data["messages_before"] == 7
        and output.data["messages_after"] == 4
        for output in outputs
    )


def test_engine_compaction_replaces_transcript_materialized_history() -> None:
    provider = FixtureLLMProvider(
        responses=[
            LLMResponse(
                id="resp-1",
                request_id="",
                invocation_id="",
                assistant_message=LLMMessage(role="assistant", content="first reply"),
            )
        ]
    )
    transcript = InMemoryTranscript()
    engine = InteractionEngine(
        InteractionEngineConfig(
            conversation_id="conv-transcript",
            provider=provider,
            transcript=transcript,
            initial_messages=[
                LLMMessage(role="user", content="old one"),
                LLMMessage(role="assistant", content="old two"),
                LLMMessage(role="user", content="old three"),
                LLMMessage(role="assistant", content="old four"),
            ],
            max_history_messages=3,
        )
    )

    list(engine.submitMessage("latest"))

    state = transcript.load("conv-transcript")
    assert state is not None
    assert state.messages[:-1] == provider.captured_requests[0].messages
    assert state.messages[0].role == "system"
    assert state.messages[0].metadata["kind"] == "context_compaction_summary"
    assert len(state.messages) == 4
