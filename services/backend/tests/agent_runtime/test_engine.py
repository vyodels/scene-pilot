from __future__ import annotations

from dataclasses import dataclass, field

from recruit_agent.agent_runtime.engine import InteractionEngine, InteractionEngineConfig
from recruit_agent.agent_runtime.tools import FunctionToolHandler
from recruit_agent.agent_runtime.types import LLMInvocationResult, LLMMessage, LLMRequest, LLMResponse, TokenUsage, ToolDefinition, ToolSchema, ToolUse


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
