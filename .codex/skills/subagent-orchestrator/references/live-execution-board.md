# Live Execution Board

Use this board when the user wants Claude Code style progress visibility, a persistent task list, or real-time orchestration status.
This format is only appropriate when the UI can actually refresh the latest board in place. In plain chat or terminal outputs that append new messages, prefer compact deltas instead of repeatedly reprinting the board.

## Goal

Keep the latest update centered around one live execution board that combines:

- current task list
- subagent scheduling status
- DAG graph
- latest transitions

This is not a separate capability from orchestration. It is the default user-facing status surface for `$subagent-orchestrator`.

## Rendering Rules

- Put the live execution board at the top of each substantial progress update.
- Treat the newest board as the current truth snapshot.
- If the UI supports in-place refresh, overwrite the latest board.
- Otherwise do not keep emitting a full board on every change; fall back to compact delta updates and periodic checkpoints.
- Keep wording compact and operational.
- Prefer a terminal-friendly ASCII dependency graph for the DAG.
- Do not use `graph TD`, `flowchart`, or Mermaid blocks by default in terminal-first outputs.
- Use Mermaid only when the user explicitly asks for Mermaid or the target UI is known to render Mermaid correctly.
- Keep the task list and scheduling panel text-first so it stays easy to scan.

## Board Layout

Render in this order:

1. title
2. task list summary
3. subagent scheduling summary
4. DAG graph
5. latest transitions
6. next wave

## Task List Template

Use a Claude Code style checklist summary:

```text
Execution Board
17 tasks (14 done, 1 in progress, 2 open)
✔ A1 审计划文档
◐ A2 审代码基线
◻ B1 文档收敛与 schema 第一波实施
◻ B2 API/前端/application 锚点迁移
◻ C1 集成验证
```

State markers:

- `✔` done
- `◐` in progress
- `◻` open or ready but not started
- `⛔` blocked
- `🔎` in review
- `🔁` repair

## Scheduling Summary Template

After the task list, show the scheduling panel:

```text
Subagent Scheduling
Ready: B1
Running: A2
Blocked: B2 <- B1, C1 <- B1,B2
Review: -
Repair: -
Done: A1
```

When useful, add the live agent mapping:

```text
Active agents
- A2 -> worker / gpt-5.4 / xhigh
- B1 -> queued
```

Unless the user explicitly requested model overrides, show every spawned subagent with the default `gpt-5.4` and `xhigh` pairing.

## DAG Template

Render the dependency graph after the scheduling summary:

```text
Dependency Graph
A1 [done] ------> B1 [ready]
A2 [running] ---> B1 [ready]
B1 [ready] -----> B2 [blocked]
B1 [ready] -----> C1 [blocked]
B2 [blocked] ---> C1 [blocked]
```

Use a tree only when the dependency structure is strictly hierarchical. Otherwise always render a DAG.

## Latest Transitions Template

After the graph, show only the newest meaningful changes:

```text
Latest transitions
- 10:31 A1 review -> done
- 10:32 A2 ready -> running
- 10:33 B1 blocked -> ready
```

## Next Wave Template

End the board with the next scheduler action:

```text
Next wave
- dispatch B1 after A2 review passes
```

## Refresh Triggers

Refresh the board whenever one of these happens:

- a node is dispatched
- a node finishes implementation
- review starts
- review passes
- review fails
- a repair node is spawned
- a node becomes blocked
- a node becomes unblocked
- integration starts
- verification starts or completes

If the UI cannot refresh in place, use these same triggers for compact deltas instead of full board re-renders.

## Delta Mode

When in-place refresh is unavailable, do this instead:

- Emit one full execution board at the start of execution.
- Emit short deltas for meaningful transitions.
- Re-emit a full checkpoint only at major phase boundaries, after large dispatch waves, or when the user explicitly asks for a fresh full snapshot.

### Delta Template

```text
Status delta
- A2 ready -> running
- B1 remains blocked on A2
Next wave
- wait for A2 review, then dispatch B1
```

### Checkpoint Template

```text
Checkpoint
Tasks: 14 done, 1 running, 2 open
Running: A2
Blocked: B2 <- B1, C1 <- B1,B2
Next wave: dispatch B1 after A2 review passes
```

## Compactness Rules

- Keep the board short enough to scan in seconds.
- Do not dump full prompts or verbose rationale inside the board.
- If extra detail is needed, place it after the board under a separate heading.
