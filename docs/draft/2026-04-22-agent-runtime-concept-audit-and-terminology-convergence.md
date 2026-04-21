# Agent Runtime Concept Audit and Terminology Convergence Draft

**Status**: Draft  
**Date**: 2026-04-22  
**Background**: Based on the current review of internal Agent runtime concepts in `recruit-agent`, and a terminology comparison against Anthropic Claude API / Managed Agents, Claude Code, OpenAI Agents, and Codex.

---

## 0. Conclusion first

The highest-level judgment is:

- `Agent` must remain a **generic, agentic execution body**.
- Specialization should primarily come from **assembled prompt, context, tools, memory, permissions, and lifecycle**, not from hardcoded business-specific Agent species.
- `Autonomous` should not be special because the class itself “knows how recruiting follow-up works”. It should be special because it is assembled with a different role prompt, different lifecycle, different budget/policy, and capabilities such as browser MCP access.

Under this principle, the current codebase has two different situations:

- A **healthy core runtime chain** that should mostly be kept.
- A **ring of project-invented concepts** around isolated execution, strategy distillation, and graph projection that should be re-evaluated and reduced.

The clearest example of an over-invented concept is `SceneContext`.

---

## 1. Positioning of this document

This document records the current judgment about which internal Agent concepts are healthy, which are over-invented, and which should be demoted, renamed, or removed from the main product/runtime narrative.

This document is not yet a formal spec. It does not override `docs/specs/`. If the team later decides to converge terminology formally, the result should be promoted into the relevant long-term specs.

---

## 2. Top-level principle: Agent must stay generic and agentic

The project should keep the following principle stable:

- `Agent` is a generic execution body.
- `Assistant`, `Autonomous`, and any future specialist role should be different mainly because of **assembly**, not because the core runtime grows new business-specific species.
- The system should give the Agent environment, tools, memory boundaries, permissions, and prompts, then let the model decide how to act within those boundaries.
- The system should avoid turning the Agent into a hardcoded workflow runner.

This means the system should prefer:

- `profile / prompt / context / tool policy / memory policy / lifecycle policy`

instead of:

- `FollowUpAgent / OutreachAgent / BrowserAgent / RecruitingAgent` as separate core runtime species.

---

## 3. External reference summary

### 3.1 Anthropic Claude Managed Agents

Anthropic’s Managed Agents documentation centers the model around:

- `Agent`
- `Environment`
- `Session`
- `Events`

The important implication is that the Agent is defined by model + system prompt + tools + MCP + skills, not by a business-specific species.

### 3.2 Claude Code

Claude Code’s official description centers on the `agentic loop`:

- gather context
- take action
- verify results

Its stable runtime vocabulary is closer to:

- `session`
- `conversation`
- `tools`
- `permissions`
- `skills`
- `subagents`
- `hooks`

It does not make product architecture revolve around a special business-class Agent type.

### 3.3 OpenAI Agents and Codex

OpenAI’s newer agent/process vocabulary is closer to:

- `conversation`
- `run`
- `turn`
- `tool call`
- `handoff`
- `approval`

This is useful because it describes execution and governance stages directly, without inventing extra business-specific runtime species.

### 3.4 Practical implication for this project

A stable terminology stack for this project should stay close to:

- `Agent`
- `Profile`
- `Conversation` or `Session`
- `Goal`
- `Run`
- `Turn`
- `Tool Call`
- `Approval`
- `Handoff`
- `Memory`

Anything beyond this should justify itself by representing a real first-class boundary.

---

## 4. Review criteria for internal concepts

A concept should be treated as suspicious if one or more of the following are true:

1. It does not map to a real first-class boundary.
2. It mainly exists to explain an implementation workaround.
3. It quietly hardcodes business behavior into the Agent body.
4. A more standard and clearer industry term already exists.
5. It makes the product narrative revolve around internal machinery instead of business objects and execution state.

A self-defined term is not automatically wrong. The issue is not “did we invent the word”, but “does this word represent a stable and necessary boundary”.

---

## 5. Current concept audit

## 5.1 Concepts that should mostly be kept

| Concept | Current role | Judgment | Recommendation |
|---|---|---|---|
| `AgentKernel` | Generic mechanism layer for `sense -> assemble -> deliberate -> act -> evaluate -> update_memory` | Reasonable internal runtime term | Keep as implementation-layer concept; do not make it the product’s main language |
| `GoalSpec` | Persistent goal definition | Reasonable engineering split from runtime goal refs | Keep |
| `AgentSession` | Long-lived autonomous session container | Reasonable, but somewhat overloaded | Keep for now, but treat it carefully in user-facing language |
| `AgentRun` | One execution instance around a goal | Good and industry-aligned | Keep |
| `turn` / `round` | Outer driver unit vs inner model/tool loop | Healthy terminology | Keep |
| `AgentRuntimeEvent` | Runtime event log | Clear and useful | Keep |
| `AgentRunCheckpoint` | Recovery / resume boundary | Clear and governance-aligned | Keep |
| `EnvironmentSnapshot` | Structured evidence snapshot of the execution environment | Clear data object | Keep |

### 5.2 Concepts that should be re-evaluated or demoted

| Concept | Current role | Why it is problematic | Recommendation |
|---|---|---|---|
| `SceneContext` | An umbrella concept around isolated delegated execution | Too abstract, not industry-standard, and mixes execution isolation with scoped context language | Remove from main product/runtime narrative; demote or replace with clearer terms |
| `ExecutionEpisode` | One isolated execution instance | Understandable but weaker and less intuitive than `run`, `attempt`, or `execution run` | Consider renaming |
| `StrategyFragment` | Distilled local strategy unit | Feels like a project-invented intelligence layer rather than a necessary first-class object | Re-evaluate before keeping |
| `ExecutionGraphProjection` | Graph-shaped projection of execution | Looks more like a visualization artifact than a runtime concept | Demote to artifact/projection layer |
| `JobAssembly` | Job-level assembly object | More implementation-specific than product/runtime-level | Do not elevate to main concept layer |
| `PromptOverlayRevision` | Versioned prompt overlay object | Useful for implementation, but not a main runtime concept | Keep implementation-local only |

---

## 6. Why `SceneContext` is the clearest over-invented concept

`SceneContext` is currently the clearest example of a concept that should not remain in the long-term main narrative.

The problem is not just that the name is new. The bigger problem is that it mixes multiple different concerns under one label:

- delegated execution
- isolated execution environment
- local execution evidence
- scoped context language

Because of that, it is difficult to answer basic design questions cleanly:

- Is it a subagent?
- Is it a run?
- Is it a context container?
- Is it a recoverable thread?
- Is it just an execution sandbox?

The real boundaries the system needs are simpler:

1. **execution isolation**
2. **scoped persistent context**

It is usually better to name these directly than to keep a broad umbrella term like `SceneContext`.

---

## 7. Review of the core runtime chain

The main Agent runtime chain is comparatively healthy:

- `AgentKernel`
- `GoalSpec`
- `AgentSession`
- `AgentRun`
- `turn`
- `round`
- `AgentRuntimeEvent`
- `ApprovalItem`
- `AgentRunCheckpoint`

This chain is mostly about:

- execution lifecycle
- execution scope
- event logging
- recovery
- governance

It does **not** inherently force business-specific Agent species into the model.

That is why the current terminology problem is not mainly `Kernel / Run / Turn`. The larger issue is the extra concept ring that grew around them.

---

## 8. What this means for `Autonomous`

`Autonomous` should be treated as a **profile + lifecycle + policy assembly**, not as a business-special runtime species.

That means:

- it can have a different prompt
- it can have different permissions
- it can have different scheduling and wake-up behavior
- it can have access to browser MCP or other external tools
- it can have a different memory scope and budget policy

But it should **not** become special because its class contains recruiting-specific workflow knowledge.

In other words:

- the runtime should stay generic
- the assembly should create the specialization
- the model should remain agentic inside those boundaries

---

## 9. Recommended terminology layers

### 9.1 Product/runtime main layer

The preferred main vocabulary should be:

- `Agent`
- `Profile`
- `Conversation` / `Session`
- `Goal`
- `Run`
- `Turn`
- `Tool Call`
- `Approval`
- `Handoff`
- `Memory`

### 9.2 Execution isolation layer

When the system needs a separate execution-isolation concept, clearer names are preferable, such as:

- `delegated execution`
- `isolated execution`
- `environment execution`
- `execution run`
- `execution attempt`

### 9.3 Application-scoped follow-up layer

When the system needs a persistent context attached to one `CandidateApplication`, clearer names are preferable, such as:

- `ApplicationContext`
- `ApplicationThreadContext`
- `ApplicationSession` if the scope is made explicit

This layer should stay distinct from isolated execution.

---

## 10. Current recommendation

### 10.1 Keep

Keep the core runtime terms:

- `AgentKernel`
- `GoalSpec`
- `AgentRun`
- `turn`
- `round`
- `AgentRuntimeEvent`
- `AgentRunCheckpoint`
- `EnvironmentSnapshot`

### 10.2 Demote or rename

Prioritize review of:

- `SceneContext`
- `ExecutionEpisode`
- `StrategyFragment`
- `ExecutionGraphProjection`
- `JobAssembly`
- `PromptOverlayRevision`

### 10.3 Guardrail for future design

Before introducing any new runtime/product concept, always ask:

1. Does this represent a real boundary?
2. Is this term more precise than existing standard vocabulary?
3. Does it keep the Agent generic?
4. Does it move specialization into assembly rather than into Agent species?

If the answer is no, the concept probably should not be introduced.

---

## 11. Open questions

The following questions still need explicit convergence before implementation refactors:

1. Should `AgentSession` remain the persistent runtime term, or should the product-facing narrative prefer `conversation` more consistently?
2. Should `ExecutionEpisode` be renamed to a clearer execution term such as `ExecutionRun` or `ExecutionAttempt`?
3. Should `ApplicationSession` be promoted into a more explicit application-scoped context model?
4. If `SceneContext` is removed from the main narrative, what is the cleanest replacement for the current delegated execution path?

---

## 12. Current final judgment

The current judgment is:

- The project should preserve a **generic Agent runtime**.
- `Agent` should remain a generic execution body.
- Specialization should come from **assembled prompt, context, tools, memory, permissions, and lifecycle**.
- The main runtime chain built around `Kernel / Goal / Session / Run / Turn / Approval / Checkpoint` is broadly reasonable.
- The concepts most likely to be over-invented are the ones around `SceneContext`, execution projection, and strategy-fragment layers.

This draft should be treated as the current convergence direction for later spec work, not yet as a formal long-term spec.
