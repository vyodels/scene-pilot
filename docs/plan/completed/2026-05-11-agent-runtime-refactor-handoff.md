# Agent Runtime Refactor Handoff

Date: 2026-05-11
Repo: `/Users/vyodels/AgentProjects/recruit-agent`

## Current State

The agent runtime refactor has been landed as a direct cutover. There is no compatibility layer for the old provider `generate(...)` API, old `recruit_agent.kernel`, or old `runtime.models` / `runtime.providers`.

Core agent logic now lives under:

```text
services/backend/src/recruit_agent/agent_runtime/
```

That directory owns:

- `InteractionEngine` / `InteractionEngineConfig`
- `AgentKernel` and the round pipeline: assemble, sense, deliberate, act, evaluate, guard, memory update
- `LLMRequest`, `LLMResponse`, `LLMStreamEvent`, `LLMProvider`
- `OpenAIProvider`, `AnthropicProvider`, `ProviderRegistry`, `UnavailableProvider`
- Core round models such as `GoalRef`, `Observation`, `RoundOutcome`, `ToolCall`, `ToolExecutionResult`
- Conversation history and transcript primitives

The old paths were removed:

```text
services/backend/src/recruit_agent/kernel/
services/backend/src/recruit_agent/runtime/models.py
services/backend/src/recruit_agent/runtime/providers.py
```

`services/backend/src/recruit_agent/runtime/` now keeps runtime utilities such as limits, retry, circuit breaker, and tool registry only. It no longer owns core agent protocol or provider abstractions.

## Provider Contract

Provider names are:

```text
OpenAIProvider
AnthropicProvider
```

The abstraction is `invoke(request: LLMRequest) -> LLMInvocationResult`. Production code no longer uses `generate(...)`, `BlockingLLMProvider`, `ScriptedLLMProvider`, `OpenAICompatibleProvider`, or `ProviderRegistryAdapter`.

`LLMRequest` is neutral but shaped around Anthropic Messages semantics:

- system prompt is separate
- assistant tool use and tool result history follow message semantics
- tool schemas use neutral `ToolSchema`
- provider-specific request fields are white-listed per provider

Unsupported provider fields are ignored by the other provider:

- Anthropic-only options such as `thinking` and `stop_sequences` are ignored by OpenAI.
- OpenAI-only options such as `reasoning`, `text_format`, `parallel_tool_calls`, `max_tool_calls`, `previous_response_id`, `store`, and `truncation` are ignored by Anthropic.
- Raw unscoped `payload_overrides` is not used. Provider-specific overrides are `openai_payload_overrides` and `anthropic_payload_overrides`.

## Business Boundary

`assistant` and `autonomous` remain business/product adapters. They are not core agent modes.

Business capabilities are injected through tools, not through bash. Existing business services adapt their tool registries into the agent runtime via:

```text
services/backend/src/recruit_agent/agent_runtime/adapters.py
```

## Design Docs

The single canonical design doc is:

```text
docs/design/agent-core/00-agent-runtime-technical-design.md
```

Older split docs under `docs/design/agent-core/01-*` and `02-*` were removed to avoid design drift.

## Validation

Last verified commands:

```text
python -m compileall -q services/backend/src/recruit_agent
pytest
```

Result:

```text
223 passed, 26 subtests passed
```

## Continue From Here

Recommended next review points:

1. Tighten naming: consider whether `AgentKernel` should be renamed now that it lives in `agent_runtime`, or kept as the internal round runner name.
2. Reduce old domain terminology in tests where possible. Tests still use legacy-shaped fixture responses such as `LLMResponse(content=..., tool_calls=...)`, but those fixtures are test-only.
3. Decide whether `runtime/__init__.py` should keep re-exporting runtime utilities only, or become private to business adapters.
4. If adding a real provider smoke test, use configured API credentials and verify one OpenAI Responses stream and one Anthropic Messages stream end to end.

## Known Non-Issues

- `ToolInvocation` still exists as a database/domain entity name under `models/domain.py`; that is not the agent runtime `ToolInvocation` concept that was rejected.
- Test-only `ScriptedProvider` exists under `services/backend/tests/agent_runtime/fixtures.py`; it is not production runtime.
