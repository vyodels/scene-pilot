# Recruit Agent

Recruit Agent is a local-first recruiting automation workspace.

The current direction is no longer the earlier execution console model. The product now centers on a built-in recruiting agent with editable execution blueprints, isolated memory, skill governance, candidate progress tracking, and operator-controlled communication review.

## Product Focus

Current scope:

- one primary built-in `Recruit Agent`
- candidate pipeline and progress tracking
- candidate-isolated memory and JD-isolated memory
- editable agent profile, prompt, role, boundaries, and compression policies
- editable recruiting playbook with patch-based evolution
- structured skills with user management and review
- chat-like candidate communication review
- local-first persistence with optional later-stage intranet upload

Not the current product focus:

- generic runtime productization
- execution-record-first operations
- fixed backlog of site integrations

## Core Objects

- `RecruitAgentProfile`: agent identity, prompt assets, tone, boundaries, success criteria, forbidden actions, compression policies
- `RecruitAgentPlaybook`: recruiting playbook graph used internally by the agent
- `Candidate`: structured candidate record and progress source of truth
- `Candidate Memory`: long-term memory isolated per candidate
- `Job / JD Memory`: long-term memory isolated per JD
- `Agent Global Memory`: reusable global recruiting strategy memory
- `Skill`: structured capability unit with metadata, health, and governance
- `Candidate Thread`: runtime communication and confirmation thread for one candidate

## Agent Runtime Architecture

The agent runtime is organised in three strict layers. Keeping these boundaries clean is the main discipline of the v2 runtime; do not move responsibilities across layers.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Driver  (AutonomousAgent / AssistantAgent)                          │
│  ─────────────────────────────────────────                           │
│  Owns: turn record, SSE stream, cancel token, fairness budget,       │
│        human-gate decision, persistence                              │
│                                                                      │
│  ┌── one turn lifecycle ─────────────────────────────────────────┐   │
│  │   while not gate and round_no < max_rounds_per_turn:          │   │
│  │      ┌── one round ────────────────────────────────────────┐  │   │
│  │      │  AgentKernel.run_round(goal, observation, limits)   │  │   │
│  │      │  Sense → Assemble → Deliberate → Guard               │  │   │
│  │      │        → Act → UpdateMemory → Evaluate               │  │   │
│  │      │  → RoundOutcome (with gate_signal hint)              │  │   │
│  │      └──────────────────────────────────────────────────────┘  │   │
│  │      Driver decides: continue / stop turn / emit gate        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### Terminology anchor

- `turn` uses the Codex semantic: one complete LLM-driven cycle from a trigger (user message, scheduler wake, run continuation) until the next point where a human must intervene.
- `round` is one `model → tool → observe` iteration inside a turn. This is what the Claude Agent SDK documentation calls a "turn"; in this project we call it a `round` to avoid colliding with the outer concept.
- `tick` is **not used** anywhere in this project.

### Layer responsibilities

| Layer | Knows | Does not know |
|-------|-------|---------------|
| `AgentKernel` (mechanism) | provider, tool registry, plugin host, memory service; how to run the 8-node pipeline once | database, HTTP, SSE, scheduler, user identity, conversation/run, turn count, whether it is serving Autonomous or Assistant |
| `round` (one Kernel call) | one `RoundOutcome` for one `Observation`, including a `gate_signal` hint | whether to continue, whether to persist, how to talk to the human |
| `turn` (Driver loop) | when to trigger, when to stop, how to persist, how to stream, how to cancel, how to decide the human boundary | Kernel internals, individual node semantics |

### Ownership of grey-area concerns

| Concern | Owner | Why |
|---------|-------|-----|
| Tool execution | `AgentKernel` (Act node) | round-internal mechanism |
| Tool approval / permission | `AgentKernel` (Guard node) reports `gate_signal`; Driver decides whether to stop | Guard evaluates, Driver handles the human interaction |
| Memory read / write | `AgentKernel` (Assemble / UpdateMemory nodes, via injected `MemoryService`) | round-internal I/O |
| Turn record, SSE stream, run record | Driver | Kernel has no lifecycle concept |
| Cancel coordination | Driver owns cancellation; Kernel, provider, and tool workers observe `cancel_token` at supported checkpoints | cancellation is cooperative and best-effort; already committed side effects are not rolled back |
| Round-level budget (tokens per round, tool timeout) | Kernel, via `RoundLimits` | round-internal constraint |
| Turn-level budget (`max_rounds_per_turn`, turn timeout) | Driver | turn-shell concern |
| Scheduler fairness, scope cooldown | Driver (Autonomous only) | cross-turn scheduling, unrelated to Kernel |
| Human confirmation interaction | Driver | only the Driver knows how to notify a human and wait |
| Recovery turn after confirm | Driver | a new turn is re-issued by the Driver |

### One-line summary

- `AgentKernel` is pure mechanism: one call runs the 8-node pipeline exactly once and returns a `RoundOutcome`.
- `round` is the smallest Kernel execution unit: one call yields one `RoundOutcome`, but cancellation may still surface within the round at provider or tool checkpoints.
- `turn` is the Driver-owned sequence of rounds that runs until the next human boundary; everything about lifecycle, persistence, cancellation, streaming, and human gating lives here.
- Cancellation is Driver-led and cooperative: the Driver stops issuing new rounds, while Kernel/provider/tool workers respond at observable points; already committed output and tool side effects are preserved.

Kernel must not know that `turn` exists, and `turn` must not reach into the Kernel's internal nodes. This is the clean boundary.

## Current Repository Layout

- `apps/desktop`: Electron + React desktop app
- `services/backend`: FastAPI backend, SQLite persistence, agent execution, approvals, sync scaffolding
- `packages/shared`: shared frontend contracts and mock/demo data
- `docs`: handoff and release notes

## Current Refactor Direction

The codebase still contains legacy execution structures from the earlier architecture phase. They are being retained as implementation machinery, but the product surface is moving to a recruit-agent-first model:

- blueprint becomes the agent’s internal playbook
- execution records remain technical artifacts, not the main user-facing object
- candidate progress, memory, communication, and evolution governance become the primary UI surfaces

See [Plan.md](./Plan.md) for the active implementation plan.

## Development

Frontend:

```bash
npm install --ignore-scripts
npm run desktop:dev
```

Backend:

```bash
cd services/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn recruit_agent.server:create_app --reload --factory
```

Tests:

```bash
python3 -m pytest services/backend/tests -q
npm run desktop:typecheck
```

Runtime terminology and schema note:

- 本次 turn / round 收敛直接改了本地 SQLite 的表名与字段名，不保留兼容层。升级后如果本地数据库来自旧版本，请删除旧的 workspace SQLite 文件后再启动后端，让新模型直接重建。

## Packaging

For local desktop verification:

```bash
npm run desktop:release:prepare
npm run desktop:release:preflight
npm run desktop:package:dir
```

For distribution-grade macOS packaging, see [docs/macos-release.md](./docs/macos-release.md).
