---
name: "subagent-orchestrator"
description: "Use when the user asks to use subagents or 子代理, delegation, 并行执行, 最大并发, 加快开发速度 through parallel agent work, DAG or 依赖图调度, manager-worker execution, 总工程师式编排, or wants the main agent to orchestrate and review work instead of doing most implementation itself. By default, all spawned subagents should use the latest available model (currently `gpt-5.5`) with `high` reasoning effort. Only switch to per-node model selection when the user explicitly asks to 看情况选择模型, 自定义模型, 动态选择模型, avoid hardcoding one model for all subagents, or says 不要全部 high. Especially useful for complex coding, debugging, research, and delivery tasks that benefit from dependency-aware scheduling and visible status reporting."
---

# Subagent Orchestrator

## Overview

Drive the task primarily by decomposing it into a dependency graph of bounded subagent jobs and keeping the ready queue saturated. Default every spawned subagent to the latest available model (currently `gpt-5.5`) with `high` reasoning effort unless the user explicitly asks for dynamic or custom model routing. Stay out of hands-on implementation unless a tiny local unblocker or final integration step is the fastest safe way to keep the graph moving.

## Compatibility With Complex Task Execution Orchestration

When `complex-task-execution-orchestrator` is also active, use this skill for DAG planning, dispatch, dependency tracking, review, repair, and integration mechanics. Defer to `complex-task-execution-orchestrator` for main-agent role selection, execution mode, context passing, `fork_context` policy, subagent output shape, checkpointing, agent reuse, and agent closure.

If the two skills conflict, follow `subagent-orchestrator` for subagent scheduling mechanics and `complex-task-execution-orchestrator` for complex-task execution protocol, role choice, checkpoints, and context hygiene. Do not independently default the main agent to coordinator mode when the complex-task skill is responsible for role selection.

## Core Rules

- Only spawn subagents when the user explicitly requested subagents, 子代理, delegation, 并行执行, 最大并发, parallel agent work, or explicitly invoked this skill.
- Prefer orchestration over direct execution. The main agent should plan, schedule, review, integrate, and re-dispatch. Do local hands-on work only for tiny unblockers, final integration, or when system constraints require keeping the critical path moving.
- Decompose into bounded tasks with explicit ownership, inputs, outputs, write scope, dependencies, and validation criteria. Worker nodes must have a clear write set; explorer nodes are read-only unless explicitly promoted to worker.
- Default every spawned subagent to the latest available model (currently `gpt-5.5`) with `high` reasoning effort.
- Only deviate from that default when the user explicitly asks for dynamic selection, custom models, per-task routing, lower effort, lower cost, higher speed, or otherwise makes model choice part of the request.
- Keep the ready queue full. Spawn all independent ready nodes in parallel instead of serializing them.
- Respect dependencies strictly. Do not dispatch a blocked node early.
- Review every completed node before accepting it and unlocking downstream work.
- Never stop merely because no agent is currently running. Re-check the DAG, unblock blockers, dispatch the next wave, or continue integration until the user task is truly complete.

## Workflow

### 1. Build the DAG

- Extract deliverables, constraints, risks, and acceptance checks.
- Split work into nodes with:
  - `id`
  - `goal`
  - `agent type`
  - `chosen model`
  - `chosen reasoning effort`
  - `selection rationale` when deviating from the default
  - `deps`
  - `owned files or scope`
  - `expected output`
  - `validation`
- Minimize coupling. Prefer disjoint write sets and narrow interfaces between nodes. Do not schedule parallel workers that write the same files unless a serial integration owner is explicit.

### 2. Publish the initial schedule

- Show the user the initial dependency graph before or alongside the first dispatch wave.
- Identify:
  - `ready` nodes that can run now
  - `blocked` nodes and which deps block them
  - `integration` nodes reserved for the main agent or a dedicated worker

### 3. Dispatch by wave

- Spawn every `ready` node in parallel.
- Use explorer-style agents for narrow codebase questions; keep them read-only by default.
- Use worker-style agents for concrete implementation or fix tasks with owned files and an explicit write set.
- Keep prompts concrete: task, ownership, inputs, outputs, acceptance criteria, and coordination notes. Default `fork_context` to false unless full parent conversation history is explicitly required.
- Avoid reflexively waiting. While nodes run, keep scheduling, reviewing completed work, preparing follow-up prompts, and planning integration.

### 4. Review on completion

- For each completed node:
  - inspect the result
  - verify the expected output exists
  - check correctness and compatibility
  - accept it, request follow-up, or spawn a repair node
  - close accepted agents when their context is no longer needed
- Only unlock downstream nodes after review passes. Do not reuse a completed agent for unrelated work; spawn a fresh node unless the follow-up depends tightly on that agent's task-local context.

### 5. Integrate and verify

- Keep integration as a first-class node in the DAG.
- After prerequisites are complete, perform final merge/integration and targeted verification.
- If verification fails, create repair nodes and continue execution.

### 6. Completion gate

Before ending the turn, ask:

- Are all user-visible deliverables finished?
- Were completed nodes reviewed rather than blindly trusted?
- Was required verification run, or clearly reported as not run?
- Is any node still pending, blocked, partially integrated, or awaiting follow-up?

If any answer is "no", continue execution.

## Model Selection

Default policy:

- Unless the user explicitly says otherwise, spawn every subagent with `model: gpt-5.5` and `reasoning_effort: high`.
- Treat this as the hard default for all nodes, including scouting, exploration, implementation, repair, verification, and review subagents.
- In the common case, record the model and reasoning effort, but you do not need a per-node justification beyond "default policy".

Override policy:

- Switch away from the default only when the user explicitly asks for any of the following:
  - 看情况选择模型 or 按任务复杂度选择模型
  - 自定义模型 or 指定某些节点用不同模型
  - 动态选择模型 or 不要硬编码一个模型
  - 不要全部 `high`
  - 更省钱, 更快, or similar cost/latency-driven routing requirements
- When such an override is explicitly requested, the main agent may choose concrete models and reasoning effort per node from the models available at runtime.
- In override mode, record the rationale for each non-default choice.

## Status Reporting

Every substantial update should include:

- the current DAG rendered as a terminal-friendly ASCII dependency graph; use Mermaid only when the user explicitly asks for it or the target UI is known to render it correctly
- the chosen model and reasoning effort for each active or newly scheduled node
- whether each node is using the default latest available model (currently `gpt-5.5`) + `high` policy or an explicit user-requested override
- running nodes
- newly unblocked nodes
- blocked nodes and blockers
- completed nodes and whether review passed
- the next dispatch wave

Do not present a dependency table as the primary DAG view. A table is optional supplemental detail after the graph.
Do not use `graph TD`, `flowchart`, or other Mermaid syntax in terminal-first outputs by default.
Only use a continuously refreshed live execution board when the runtime or UI actually supports in-place refresh of the latest status surface. In plain chat or terminal outputs that append new messages, do not keep re-emitting a full board on every state change.
For terminal-first outputs, emit one full snapshot at the start of execution or at major phase boundaries, then prefer compact delta updates that report only the meaningful state changes, blockers, and next wave. Do not reprint the full DAG for routine node transitions.
Publish a compact status delta whenever any node changes state in a meaningful way, including queued or ready to running, running to review, running to done, blocked to ready, review failed, repair dispatched, or final verification started or completed. Keep deltas short unless the user asks for a full board.
When the user wants a Claude Code style progress surface and the UI supports actual refresh, use [live-execution-board.md](references/live-execution-board.md) as the primary status format. Otherwise use the token-efficient delta and checkpoint format described in that file.

## Prompt Construction

When dispatching a node, always include:

- the node id and goal
- the exact model and reasoning effort to use; default to `gpt-5.5` and `high` unless the user explicitly requested an override
- exact ownership boundaries
- inputs or artifacts to inspect
- expected output
- acceptance criteria
- compact handoff output requirements; prefer results, files, verification, risks, and next unblockers over detailed work logs
- coordination note that other agents may be editing elsewhere and must not be reverted
- for coding tasks: the owned files or modules, explicit write set, and any files that must not be touched
- for exploratory tasks: the concrete question to answer and confirmation that the task is read-only

Subagents should not paste full command logs, full file contents, or broad exploration transcripts unless explicitly requested.

## Failure Handling

- If a node stalls or fails review, spawn a focused repair node instead of broadening scope.
- If the graph is too serial, re-plan the DAG and split oversized nodes.
- If multiple nodes want the same files, collapse them into one owner node and move checks to downstream verification nodes.
- If a blocker cannot be delegated safely, do the minimal local unblock yourself and resume orchestration.

## Plan Mode And Default Mode

- In plan-oriented work, output a dependency-aware execution plan, not just a linear checklist.
- In executable work, begin dispatch as soon as the first ready wave is clear.
- Do not hand the user a plan and stop if execution can continue in the current turn.

## End Condition

End only when the task is complete, integrated, reviewed, and reported, or when a hard external blocker remains and has been clearly surfaced to the user.
