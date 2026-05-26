---
name: complex-task-execution-orchestrator
description: "Use whenever the user names $complex-task-execution-orchestrator or asks to execute a plan/goal, continue a complex task, run a multi-phase implementation, coordinate/coordinator mode, use repeated review-fix-verify loops, manage a long-running goal, handle high-risk migrations, or deliver work across multiple files/modules/sessions. Provides role selection, coordinator/hybrid/direct execution rules, phase/wave batching, checkpoints, subagent delegation when appropriate, handoffs, integration gates, final verification, and strict role-preserving fallback behavior when tools are unavailable. Pair with subagent-orchestrator when the user asks for parallel subagents."
---

# Complex Task Execution Orchestrator

## Overview

Run complex tasks, plans, and goals with disciplined execution. Optimize for forward progress, reviewability, verification, risk control, and low context drift across multiple phases, iterations, or agents.

This skill is a complex-task execution protocol. Context hygiene is one mechanism; the broader purpose is to make non-trivial work easier to execute, resume, review, and complete.

## Apply This Skill When

Use this skill when one or more are true:

- The user explicitly names `complex-task-execution-orchestrator`, `$complex-task-execution-orchestrator`, "orchestrator", "coordinator", "协调", "编排", "多阶段", "执行 plan", "继续 goal", or asks to run work according to an existing plan.
- The user asks to execute or continue a plan document, task breakdown, goal, roadmap, migration, implementation phase, or acceptance checklist.
- The task has 3 or more meaningful phases.
- The work spans multiple modules, services, files, or ownership areas.
- The user gives a plan or goal and expects sustained execution, review, or validation.
- The task requires repeated review, fix, test, and re-review loops.
- The task benefits from subagents, parallel work, or dependency-aware scheduling.
- The task has high regression, data, money, security, or migration risk.
- The task needs a checkpoint trail to avoid losing state or being misled by stale context.

Do not use this skill for small one-shot fixes where direct execution is clearer than orchestration.

If the user explicitly names this skill, use it even for a small task. In that case, keep the protocol lightweight but still honor any chosen role.

## Role Selection Gate

When this skill triggers for real execution and the user has not already specified how the main agent should participate, ask the user to choose the main agent role before substantial execution. Do not silently choose for the user.

Prefer an interactive choice UI only in runtimes where a choice/input tool is available, such as Plan mode. When that tool is available, call it instead of asking in plain text. In normal execution modes where no choice UI is exposed, use the plain-text fallback and wait for the user answer. Use exactly one role-selection question with these options, preserving this order:

- `coordinator`
- `hybrid`
- `direct executor`

If the runtime does not expose an interactive choice UI, ask this exact plain-text fallback question and wait for the user answer:

```text
这个任务属于复杂任务执行场景。请选择主 agent 角色：
1. coordinator：我主要负责拆解、调度、验收和集成；适合 subagent/并行推进。
2. hybrid：我抓关键路径和最终集成，同时委派独立子任务；适合多数中等复杂开发任务。
3. direct executor：我主要自己实现，少用子代理；适合耦合高或你想减少流程的任务。
```

Offer these roles:

- `coordinator`: the main agent primarily frames the objective, decomposes phases, dispatches agents when allowed, reviews results, maintains checkpoints, handles integration, and reports final status. Best when subagents or parallel work are desired.
- `hybrid`: the main agent owns the critical path and final integration, while delegating bounded exploration, implementation, repair, or verification nodes when useful. Best default for many medium-complexity development tasks.
- `direct executor`: the main agent does most implementation locally and uses subagents only when explicitly useful for narrow checks or independent side work. Best when the task is tightly coupled, small enough to keep local, or the user wants fewer moving parts.

If the user explicitly says `orchestrate`, `delegate`, `use subagents`, or `main agent should coordinate`, treat that as `coordinator`. If the user explicitly says `do it yourself`, `no subagents`, or `directly implement`, treat that as `direct executor`. If the user asks only for a plan or review, choose the matching execution mode but still ask for the main-agent role before any large execution step.

Before the role is selected, the main agent may do only lightweight scoping that helps present a better choice, such as reading the plan, listing likely phases, or identifying obvious dependencies.

Once selected, the role persists for the active goal until the user changes it. A continuation turn, context compaction, missing tool, or resumed session must not silently reset or reinterpret the role. In particular, `coordinator` must not degrade into `hybrid` or `direct executor`, and `direct executor` must not introduce orchestration overhead unless the user asks for it.

## Execution Modes

Choose the lightest mode that fits the request:

- `plan`: produce a phased execution plan with checkpoints, dependencies, risks, and validation gates. Stop after the plan only when the user asks for planning or review rather than execution.
- `execute`: advance through phases according to the selected role, review accepted increments, repair failures, integrate, and verify.
- `review`: inspect an existing plan or implementation; lead with findings, then blockers, then recommended repair phases.
- `goal`: continue across multiple turns until the goal is complete or genuinely blocked; maintain a compact checkpoint as the authority.
- `orchestrated`: combine this skill with `subagent-orchestrator` when the user explicitly asks for subagents, parallel work, delegation, DAG scheduling, or selects the `coordinator` role.

## Relationship To Subagent Orchestrator

Use `subagent-orchestrator` for subagent DAG mechanics: agent-node decomposition, dispatch, dependency tracking, repair nodes, and parallel scheduling.

Use this skill for the overall execution protocol. If both skills are active, this skill has priority for:

- framing the objective, phases, checkpoints, and completion gate
- what counts as accepted work
- how much context is passed between phases or agents
- what handoff shape subagents and local phases must return
- when completed details become stale
- how integration and final verification are gated

## Role Operating Rules

All roles share the same completion discipline: define acceptance, work in bounded phases or batches, keep a compact checkpoint, review before accepting, and report verification honestly. They differ in who implements the work.

Use batches sized to the plan and risk. For large plans, a batch may be a full phase or a vertical slice; do not force a full review/test/fix loop after every tiny file or function edit. For high-risk changes, add targeted checks earlier without resetting the whole workflow.

### Coordinator

When the selected role is `coordinator`, the main agent owns decomposition, dispatch, review, integration, and acceptance. It must not do substantial implementation locally unless the user explicitly switches the role or approves a narrow exception.

Allowed local coordinator actions:

- Read plans, code, schemas, tests, logs, and diffs.
- Create or update task ledgers, DAGs, acceptance criteria, prompts, and handoff capsules.
- Spawn/dispatch subagents when tools are available.
- Review subagent output, inspect diffs, run targeted verification, classify findings, and request repairs.
- Make tiny integration edits only when they are mechanical, low-risk, and needed to merge accepted work, such as fixing an import name or resolving a trivial conflict.

Forbidden local coordinator actions without explicit user approval:

- Implement a phase, vertical slice, migration, runtime, schema, execution path, risk/accounting path, or broad refactor directly.
- Continue coding because subagent tools are missing.
- Treat tool unavailability as permission to become `hybrid` or `direct executor`.
- Accept unreviewed local changes as if they came from an owned implementation node.

If subagent or multi-agent tools are not available in a coordinator run:

1. Try normal tool discovery if a discovery tool is available.
2. If tools remain unavailable, state that coordinator execution is blocked for delegation.
3. Continue only with coordinator-safe work: current-state review, diff audit, task decomposition, risk assessment, and acceptance planning.
4. Ask the user whether to switch to `hybrid` or `direct executor` before any substantial local implementation.

For high-risk code such as trading, funds, live execution, schema migrations, accounting, reconciliation, security, or data integrity, coordinator local edits are limited to review notes and tiny mechanical integration unless the user explicitly changes role.

### Hybrid

When the selected role is `hybrid`, the main agent owns the critical path and final integration. It may implement tightly coupled or blocking work locally, while delegating independent research, verification, tests, repairs, or isolated modules when that reduces risk or wall-clock time.

Hybrid should:

- Implement core path work locally when it requires continuous architectural judgment or tight integration.
- Delegate independent nodes with clear scope, acceptance, and handoff contracts when subagent tools are available.
- Review and integrate delegated output before downstream work depends on it.
- Keep subagent use proportional; do not create a DAG for work the main agent can safely finish faster.

If subagent or multi-agent tools are not available in a hybrid run:

- Continue on the local critical path when safe.
- Note which parallel/delegated checks were skipped or converted to local work.
- Do not claim parallel review coverage that did not happen.
- Ask before switching to full `coordinator` or before pausing solely because delegation is unavailable.

### Direct Executor

When the selected role is `direct executor`, the main agent implements locally by default. Use this for scoped, tightly coupled, or speed-sensitive work where subagent coordination would add more overhead than value.

Direct executor should:

- Read enough context, implement, run targeted verification, and summarize the result.
- Keep planning and ledgers lightweight.
- Avoid spawning subagents unless the user explicitly requests it or a narrow independent check is clearly useful.
- Still obey phase boundaries, acceptance criteria, safety checks, and final verification for complex or high-risk work.

If a task unexpectedly becomes too large or risky for direct execution, stop and recommend switching to `hybrid` or `coordinator` instead of silently expanding scope.

## Core Rules

- Respect the user-selected main-agent role. Do not silently switch from direct execution to coordination or from coordination to local implementation without a reason and a status update.
- Anchor the work to a compact objective, explicit acceptance criteria, and current checkpoint.
- Split work into reviewable phases with bounded ownership and observable outputs.
- Prefer bounded accepted increments over large unreviewed batches; size the increment to the selected role, plan phase, and risk.
- Keep momentum with waves: dispatch or implement ready work according to role, review completed work, repair failed work, then integrate.
- Review before accepting. A phase is not accepted merely because an agent or command says it is done.
- Track unresolved risks explicitly with an owner, mitigation, or next check.
- Let newer reviewed checkpoints supersede older raw details and rejected hypotheses.
- Avoid over-orchestration: if the selected role allows local implementation and a phase can be completed directly and safely, do it directly. This does not override the `coordinator` local-implementation limits.

## Task Ledger

Maintain a compact ledger in the main thread. For very long work, create or update a project file only when useful, such as `docs/agent_runs/<date>-task-checkpoint.md`.

Use this shape:

```text
Objective:
- <current objective in one or two lines>

Acceptance:
- <user-visible success criteria>

Accepted:
- <phase/node>: <reviewed result>; verified <check>; risk <risk/none>

In Progress:
- <phase/node>: <owner/status>

Blocked:
- <phase/node>: <blocker and needed input/change>

Risks:
- <risk>: <mitigation/check/owner>

Verification:
- <check>: <pass/fail/not run + reason>

Next:
- <next wave or next local action>
```

Do not store raw command transcripts, full logs, broad exploration traces, or speculative analysis in the ledger.

## Phase Design

Each phase or node should define:

- `goal`: bounded objective
- `scope`: owned files, modules, commands, or question area
- `deps`: prerequisites
- `output`: expected artifact or behavior
- `acceptance`: observable checks
- `verification`: command, test, runtime check, screenshot, review criterion, or explicit reason not run
- `risk`: expected failure mode or blast radius

Good phase boundaries let a reviewer answer: what changed, why it matters, how it was checked, and what risk remains.

## Subagent Protocol

Use subagents only when explicitly allowed by the user, when the user selects the `coordinator` or `hybrid` role and delegation is appropriate, or when another active instruction permits it. When using subagents:

- Default `fork_context` to false.
- Pass only the phase objective, accepted facts, relevant constraints, owned scope, and acceptance criteria.
- Treat subagents as disposable task-local contexts.
- Do not reuse a completed subagent for unrelated work.
- Close accepted subagents promptly after extracting the handoff.

Subagent prompt template:

```text
Node: <id>
Goal: <bounded objective>
Context bundle: <short accepted facts only>
Owned scope: <files/modules/questions>
Do not touch: <protected areas>
Acceptance criteria: <observable checks>
Verification expected: <commands/checks or explicit not-run reason>
Coordination: other agents may be editing elsewhere; do not revert unrelated work.
Output contract: return only the handoff capsule below.
```

## Handoff Capsule

Every subagent and every major local phase should end with a compact handoff:

```text
Node/Phase: <id>
Status: done | blocked | failed
Changed files: <paths or none>
Inspected files: <paths if relevant>
Result: <1-4 bullets>
Verification: <commands/checks and pass/fail, or not run with reason>
Risks: <remaining risks or none>
Next unblock: <recommended next node/action or none>
```

Keep capsules under 40 lines unless the user asks for a detailed report. Include only the smallest useful error excerpt when blocked or failed.

## Review And Acceptance

Before marking a phase accepted:

- Inspect changed files, cited source locations, produced artifacts, or runtime state.
- Run targeted checks when feasible.
- Compare the result against acceptance criteria.
- Classify as `accepted`, `needs_repair`, `blocked`, or `superseded`.
- Update the ledger with the reviewed result.
- Dispatch a focused repair phase if review fails.

Do not unlock downstream work from an unreviewed handoff.

## Checkpoint And Stale Context Control

Publish a compact checkpoint after each wave or meaningful phase boundary. Continue from the checkpoint plus current source/artifacts, not from raw historical exploration.

Treat context as stale when:

- a newer checkpoint supersedes it
- a repair phase changed the same behavior
- tests or runtime checks have since passed or failed differently
- relevant files or artifacts were edited after the observation
- the information came from an unaccepted handoff

When stale context conflicts with current files, current artifacts, or accepted checkpoints, trust the current state and accepted checkpoints.

## Integration Gate

Integrate only accepted work. During integration:

- Check that phase outputs are compatible.
- Re-run enough verification to cover cross-phase behavior.
- Look for duplicated logic, conflicting assumptions, or broken ownership boundaries.
- Confirm user-visible behavior and external contracts still match the objective.
- Record remaining risks explicitly instead of burying them in the final summary.

## Anti-Over-Orchestration

Keep the protocol lightweight:

- Do not create a DAG for a one-file fix unless the risk justifies it.
- Do not spawn subagents for work the main agent must immediately inspect before proceeding.
- Do not emit a full execution board on every small update; prefer deltas.
- Do not preserve detailed history once a reviewed checkpoint supersedes it.
- Do not let checkpoint maintenance become more work than the task itself.

## Output Discipline

For user updates, report only meaningful changes: accepted phases, failed review, new blockers, repair dispatch, integration start, and final verification.

For plan-only requests, return a phased execution plan with dependencies, checkpoints, and verification gates.

For executable requests, continue through role-appropriate execution, review, repair, integration, and verification when feasible. In `coordinator`, execution means dispatching, reviewing, and integrating rather than doing substantial local implementation.

## Completion Gate

Before declaring a complex task, goal, or plan complete, verify:

- Required phases are accepted or explicitly removed from scope.
- Accepted work was reviewed rather than blindly trusted.
- No needed subagents or local sessions remain running.
- Integration was checked against current source/artifact state.
- Required verification passed, or gaps are reported plainly.
- Unresolved risks are listed with next actions.
- The final answer is based on the latest checkpoint, not stale task history.
