# Agent v2 术语与分层收敛实施计划（tick → turn / round）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `2026-04-19-agent-v2-direct-cutover-plan.md` 完成之后，对 Agent v2 运行时做一次**术语与分层收敛**：彻底废弃 `tick` 一词，统一外层单位为 `turn`（Codex 语义），统一内层 `model↔tool` 往返为 `round`，并把 Kernel 严格降到"只跑一个 round"的机制层，把 turn 生命周期全部上浮到 Driver 层。**这是一次一次性的直接改名 + 结构调整，不做兼容层、不保留旧符号。**

**执行时机：** 本计划必须在 `2026-04-19-agent-v2-direct-cutover-plan.md` 全部任务完成、全量 backend 测试绿色之后才启动。在此之前 Codex 不得提前执行本计划。

**覆盖说明：** 本计划是 `2026-04-19-agent-v2-direct-cutover-plan.md` 完成后的后置收敛真相；如果 direct cutover 文档、实现残留或历史讨论里的命名 / event / API 术语与本计划冲突，以本计划收敛后的术语为准。

**Architecture:** 改造后的运行时只有三层：

1. **`AgentKernel`（机制）** — 只暴露 `run_round(goal, observation, limits) -> RoundOutcome`，一次调用 = 一次 8 节点流水线执行。不感知 turn、不感知 Agent 种类、不感知持久化。
2. **`round`（Kernel 最小执行单位）** — 一次 Kernel 调用；不独立落表（可选作为 event-log）；cancel 由 Driver 主导，Kernel/provider/tool worker 在可观察点响应，已提交副作用不回滚。
3. **`turn`（Driver 层）** — Driver 持有 `while not gate` 循环、turn 记录、SSE 流、cancel token、公平性预算、人机边界判定。`turn` 的概念只属于 Driver，Kernel 里不得出现。

**Tech Stack:** FastAPI、SQLAlchemy ORM、SQLite、Alembic、Pydantic、Anthropic/OpenAI-compatible provider、SSE/WebSocket、Python >= 3.14、TypeScript desktop client。

---

## 0. 本计划的地位与执行约束

### 0.1 本计划在 direct cutover 之后生效

- `2026-04-19-agent-v2-direct-cutover-plan.md` 决定"架构长什么样"，本计划决定"命名和分层怎么彻底干净"。
- cutover 完成后，代码里还会残留以下历史物：`run_tick`、`AgentTickRecord`、`tick_id`、`TickOutcome`、`same_scope_ticks`、`AgentKernel.run_tick` + `AgentKernel.run_turn` 两个近似方法、`tick_completed` 事件、`/ticks` API、`AgentTurnRecord` 作为 tick 的子记录等。本计划负责把它们一次性全部清掉。

### 0.2 强约束（Codex 不得自行发挥）

- 不保留 `tick` 一词的任何残留（代码、注释、字段、表、路由、事件、文档全部清空）。
- 不新增兼容层、兼容别名、过渡字段。
- 不保留 `AgentKernel.run_tick` 作为 `run_round` 的包装。
- 不保留 `AgentKernel.run_turn` 作为 Assistant 专用方法——`run_round` 必须统一承载 Autonomous 与 Assistant。
- 不把 turn 生命周期（record 起止、SSE 流、cancel、gate 判定、`while not gate` 循环）放回 Kernel。
- 不把 `AgentKernel` 重命名为 `AgentLoop` 或其他名字，`AgentKernel` 保持不变。
- 不重命名容器概念：`run`（Autonomous 长跑）和 `conversation`（Assistant 会话）保持不变。
- 不新建并行表；现有 tick 表直接在原 ORM 类上改名为 turn 表，原内层 turn 子表直接删除。
- 不以"大规模 rename 风险高"为由保留旧符号。
- **不搞 `_v2` / `_new` 风格的平行命名**——所有改名直接在原文件、原类、原表上进行，旧名一次性删除。
- **不写 Alembic migration、不写双写逻辑、不写 backfill**——项目是 local-first SQLite，无历史包袱，直接改模型即可（详见 §5）。如果 Codex 本能地想写 migration，立刻停止并走 §5 的直接改名路径。
- 任何"新建 `foo_v2.py`、把功能搬过去、留 `foo.py` 做 shim"的操作一律禁止。

### 0.2.1 不算完成的假实现

- Kernel 里仍然存在 `run_tick` / `run_turn` 两个方法（而不是统一的 `run_round`）。
- Driver 内没有 `while not gate` 循环，仍然是"一次调用 Kernel 就返回"。
- `RoundOutcome` 里不包含 `gate_signal` 字段，或者 Driver 不读它。
- 数据库里还存在 `agent_tick_records` 表或 `tick_id` 字段。
- API / SSE 里还存在 `tick_completed`、`/ticks`、`tick_id` 等字段或事件名。
- 文档里还出现 `tick` 一词（术语锚定段的反例说明不算）。
- Assistant 仍然有自己独立的一条 `run_turn` 主路径，没有和 Autonomous 共用 `run_round`。
- 内层循环里还叫 `turn_idx` / `max_turns_per_*`，而不是 `round_idx` / `max_rounds_per_turn`。
- `same_scope_ticks` 之类的字段没有改名为 `same_scope_turns`。

### 0.3 UI 测试策略

- 自动化范围：后端单测、集成测试、端到端 backend flow、desktop typecheck。
- 真实 UI 行为由 human 在实施完成后监督验收。
- Codex 不自动做 UI 交互测试，但 API/类型改动导致前端编译失败的必须修到 `npm run desktop:typecheck` 通过。

### 0.4 测试策略（Codex 必须自主补测试）

每个任务必须：
1. 先补最小失败测试；
2. 再改实现；
3. 运行对应最小测试；
4. 每个大阶段补集成测试；
5. 最后运行全量 backend 测试；
6. 如触及 desktop API/types，再跑 `npm run desktop:typecheck`。

### 0.5 唯一允许中途停止的情况

1. cutover plan 事实上未完成或未全绿（这时应该停下来告知 human）。
2. 仓库现状与本计划存在不可自解的矛盾。
3. 测试失败暴露的是本计划内部矛盾而不是代码 bug。

除此之外，必须一口气执行到底。

---

## 1. 术语与符号全量映射表（权威对照）

> Codex 在任何一处改名时都以本表为唯一标准。本表覆盖代码、数据库、API、SSE、文档。

### 1.1 概念层

| 改前 | 改后 | 含义 |
|------|------|------|
| tick（Autonomous 侧外层） | **turn** | 一次从触发到下次人类介入为止的完整 LLM 驱动循环（Codex 语义） |
| turn（Assistant 侧外层） | **turn** | 与上同义，两个 Agent 共用同一定义 |
| turn（Kernel 内部循环变量） | **round** | 一次 `model → tool → observe` 往返 |
| （无） | **RoundOutcome** | Kernel 单次调用返回值，包含 `gate_signal` 字段 |
| 旧 Autonomous 内层 `AgentTurnRecord`（每 tick 固定 1 条、本质只是消息落库） | **直接删除** | round 不独立落表；round 级事件通过 `AgentRuntimeEvent`（`event_type="round.*"`）作为 event-log 写入 |

### 1.1.x 作用域迁移对照（必须先看这张表再开始改）

本次改造的关键不是"换个名字"，而是把原来**混乱的 3 层作用域**（Autonomous 的 tick+inner turn + Assistant 的 turn）压平为**清晰的 2 层作用域**（外层 turn + 内层 round）。

| 旧作用域 | 旧作用域含义 | 新作用域 | 新作用域含义 | 语义变化 |
|---------|------------|---------|------------|---------|
| Autonomous: `AgentTickRecord` | Autonomous 一次执行（当前实现里一次 Kernel 调用后结束） | `AgentTurnRecord` | 两个 Agent 共用的外层单位，**由 Driver 的 while 循环串起多个 round** | 外层单位的**职责扩大**：以前一 tick = 一次 Kernel 调用，现在一 turn = N 次 Kernel 调用直到 gate |
| Autonomous: 内层 `AgentTurnRecord`（`tick_pk` FK，`seq=1, role="assistant"`） | 每 tick 固定 1 条的消息副本 | **删除**，被 `AgentRuntimeEvent(event_type="round.completed")` 取代 | round 级事件流 | 表结构**消失**；原来记录的信息下沉到 event-log |
| Assistant: `turns` 表（自己独立一套） | Assistant 一次用户消息 cycle | `AgentTurnRecord`（与 Autonomous 同表或平行同构表） | 同上 | 语义**完全一致**，只是命名和结构被对齐 |
| `AgentKernel.run_tick` | Autonomous 的一次 Kernel 执行 | `AgentKernel.run_round` | 一次 pipeline 执行，与 Agent 种类无关 | **不再按 Agent 分方法**；差异上浮到 `Observation` 和 `PluginHost` |
| `AgentKernel.run_turn` | Assistant 的一次 Kernel 执行（多了 history/input/confirmation_gate 参数） | 同上合并进 `run_round` | 同上 | 三个 Assistant 专属参数的归宿：<br>• `history_messages` / `input_message` → `Observation.input`<br>• `confirmation_gate` → `PluginHost.register_guard_check("assistant_confirmation", ...)` |
| `FairnessState.same_scope_ticks` | Autonomous 调度公平性计数 | `FairnessState.same_scope_turns` | 同义改名 | 概念不变 |
| `AgentRun.ticks_count` + `AgentRun.turns_count`（当前都在用） | 分别计数 tick 和内层 turn | `AgentRun.turns_count`（外层）+ **删除 `rounds_count`**（round 量太大，不在 run 级聚合） | 保留一个 `turns_count` 足够 | 计数维度**降级** |

**最重要的一条**：原 Autonomous 内层 `AgentTurnRecord` 表**直接删除**，不改名、不保留。Codex 不需要在"保留为 round 表"和"删除"之间二选一——**就是删除**。

### 1.2 Kernel API

| 改前 | 改后 |
|------|------|
| `AgentKernel.run_tick(goal, observation, ...)` | `AgentKernel.run_round(goal, observation, limits, ...)` |
| `AgentKernel.run_turn(goal, observation, history_messages, input_message, ...)` | **合并到** `run_round`；Assistant 相关的 `history_messages` / `input_message` / `confirmation_gate` 通过 `Observation` 和 `PluginHost` 注入，不作为 Kernel 方法签名的 Agent 专属参数 |
| 返回 `TickOutcome` | 返回 `RoundOutcome` |
| `AgentKernel` 类名 | **不变** |

### 1.3 Runtime 数据类

| 改前 | 改后 |
|------|------|
| `TickOutcome`（`scene_pilot.runtime.models`） | `RoundOutcome` |
| `TickOutcome.metadata` | `RoundOutcome.metadata`（字段不变） |
| `TickOutcome.status` | `RoundOutcome.status` |
| （`TickOutcome` 无 `gate_signal`） | `RoundOutcome.gate_signal: Literal["continue","wait_human","budget_exhausted","goal_done","paused","escalate"] | None` |
| `FairnessState.same_scope_ticks` | `FairnessState.same_scope_turns` |
| `Observation.hash` 中 fallback 的 `tick.tick_id` | `turn.turn_id`（见 §1.4） |

### 1.4 数据库模型

| 改前表 / 字段 | 改后 | 备注 |
|--------------|------|------|
| `AgentTickRecord`（ORM 类） | `AgentTurnRecord` | Autonomous 外层单位记录，**直接在原类上改名**，不新建 |
| `agent_tick_records` 表 | `agent_turn_records` | 表名统一，不做 `autonomous_turn_records` 这种带 Agent 前缀的命名 |
| `tick_id`（列 / 字符串 ID） | `turn_id` | |
| `tick_pk` / `tick_seq`（如有） | `turn_pk` / `turn_seq` | |
| 旧 `AgentTurnRecord`（内层、`tick_pk` FK、每 tick 固定 1 条的消息副本） | **ORM 类与 `agent_turn_records`（旧内层表）整体删除** | round 信息改走 `AgentRuntimeEvent(event_type="round.*")` |
| `AgentRun.ticks_count` | `AgentRun.turns_count` | 旧的 `AgentRun.turns_count`（指向内层 turn）**直接删除**，不改为 `rounds_count` |
| `AgentRuntimeEvent.tick_id` | `AgentRuntimeEvent.turn_id` | |
| `AgentRuntimeEvent.turn_id`（指向旧内层 turn） | **删除该列** | round 级事件用 `payload` 里的 `round_seq` 承载 |

> **命名冲突提示**：原来存在一个**内层** `AgentTurnRecord` ORM 类 + `agent_turn_records` 表，它与我们**新的外层** `AgentTurnRecord`（由原 `AgentTickRecord` 改名而来）会重名。处理方式：**先删除旧的内层类与表，再把原 `AgentTickRecord` / `agent_tick_records` 改名为 `AgentTurnRecord` / `agent_turn_records`**。中间不保留任何别名或 legacy 类。

### 1.5 API / 路由 / Envelope

| 改前 | 改后 |
|------|------|
| `AutonomousAgent.run_tick_from_envelope(envelope)` | `AutonomousAgent.run_turn_from_envelope(envelope)` |
| envelope `trigger_type` / `scope_kind` / `scope_ref` | 不变 |
| `/api/runs/{run_id}/ticks/...` 路由 | `/api/runs/{run_id}/turns/...` |
| router 函数名 `*_tick_*` | `*_turn_*` |

### 1.6 SSE / Event

| 改前事件名 | 改后事件名 |
|-----------|------------|
| `tick.started` | `turn.started` |
| `tick.completed` / `tick_completed` | `turn.completed` |
| `tick.waiting_human` | `turn.waiting_human` |
| `tick.failed` | `turn.failed` |
| event payload 里的 `tick_id` | `turn_id` |

### 1.7 配置 / 限额

| 改前 | 改后 | 归属层 |
|------|------|--------|
| `max_turns_per_tick`（如有） | `max_rounds_per_turn` | **Driver 层**（不是 Kernel）|
| `RuntimeLimits.max_*`（原 Kernel 用） | 拆分为 `RoundLimits`（Kernel 用）和 `TurnLimits`（Driver 用） | 见 §3 |
| `turn_idx`（Kernel 内） | `round_idx` | Kernel 内 |

### 1.8 日志 / metadata key

| 改前 | 改后 |
|------|------|
| `outcome.metadata["tick_id"]`（如有） | `outcome.metadata["round_id"]` 或删除 |
| `tick_no` / `tick_seq` | `turn_no` / `turn_seq` |

### 1.9 必须改动的文件清单（grep 白名单）

以下清单是在编写本计划时 `rg 'run_tick|AgentTickRecord|TickOutcome|tick_id|tick_completed|same_scope_ticks'` 的结果，Codex 开工前应重跑一次并以**更新后的结果**为准（如有新增文件也要一并处理）。desktop 侧当时 0 命中，如重跑出现命中同样处理。

**后端源码（11 个文件）：**

- [ ] `services/backend/src/scene_pilot/runtime/models.py` — `TickOutcome` 定义 + 相关导入
- [ ] `services/backend/src/scene_pilot/runtime/__init__.py` — `TickOutcome` 导出
- [ ] `services/backend/src/scene_pilot/kernel/kernel.py` — `run_tick` / `run_turn` 合并为 `run_round`
- [ ] `services/backend/src/scene_pilot/kernel/evaluate.py` — 产出 `RoundOutcome` + 计算 `gate_signal`
- [ ] `services/backend/src/scene_pilot/agents/autonomous.py` — `run_tick_from_envelope` 改名 + while 循环
- [ ] `services/backend/src/scene_pilot/agents/assistant.py` — `run_turn` 改造为 Driver while 循环
- [ ] `services/backend/src/scene_pilot/agents/heartbeat.py` — 调用点从 `run_tick_from_envelope` 改为 `run_turn_from_envelope`（见 §4.1 末尾说明）
- [ ] `services/backend/src/scene_pilot/memory/service.py` — `fetch_recent_events` 等里对 `tick_id` 的引用
- [ ] `services/backend/src/scene_pilot/api/routers/agent.py` — `/ticks` 路由 + 相关 envelope 字段
- [ ] `services/backend/src/scene_pilot/models/domain.py` — ORM 模型改名（见 §5.1）
- [ ] `services/backend/src/scene_pilot/models/__init__.py` — 导出更新

**后端测试（至少以下命中，实际开工前再 grep 一次）：**

- [ ] `services/backend/tests/agent/integration/test_tick_end_to_end.py` — 文件名建议改为 `test_turn_end_to_end.py`
- [ ] `services/backend/tests/agent/integration/test_heartbeat.py`
- [ ] `services/backend/tests/agent/integration/test_assistant_cancel_interrupts_active_turn.py`
- [ ] `services/backend/tests/agent/integration/test_assistant_confirm_recovery_turn.py`
- [ ] `services/backend/tests/agent/integration/test_functional_closure_assistant_shared_kernel.py`
- [ ] `services/backend/tests/agent/integration/test_functional_closure_assistant_cancel.py`
- [ ] `services/backend/tests/agent/integration/test_functional_closure_memory.py`
- [ ] `services/backend/tests/agent/integration/test_memory_backed_continuity.py`
- [ ] `services/backend/tests/agent/integration/test_assistant_conversation.py`
- [ ] `services/backend/tests/agent/integration/test_assistant_compacted_sse.py`
- [ ] `services/backend/tests/agent/integration/test_evolution_pipeline.py`
- [ ] `services/backend/tests/agent/integration/test_recruit_pack_external_action_gate.py`
- [ ] `services/backend/tests/agent/integration/test_recruit_pack_takeover_flow.py`
- [ ] `services/backend/tests/agent/integration/test_execution_unit_timeout_and_blocked_status.py`
- [ ] `services/backend/tests/agent/integration/test_execution_unit_wait_nonblocking.py`
- [ ] `services/backend/tests/agent/integration/test_assistant_cancel_token_not_reused.py`
- [ ] `services/backend/tests/agent/integration/_helpers.py`
- [ ] `services/backend/tests/agent/unit/test_kernel_happy_path.py`
- [ ] `services/backend/tests/agent/unit/test_execution_unit_runner.py`
- [ ] `services/backend/tests/test_api_app.py`

**Desktop / 前端：** 开工前 `rg 'run_tick|tickId|tick_id|TickOutcome' apps/desktop packages` 再验一次；当前为空，若改名过程中有类型扩散到前端，按命中点同步改名并跑 `npm run desktop:typecheck`。

**文档：**

- [ ] `README.md`（架构图与术语已提前加入，校对实际符号一致即可）
- [ ] `docs/agent-v2-design-summary.md`
- [ ] `docs/agent-v2-implementation-spec.md`
- [ ] `CLAUDE.md`（全量搜索 `tick`）
- [ ] `docs/` 其余子目录全量 ripgrep

---

## 2. Kernel API 合并与 round 执行语义

### 2.1 目标

当前 Kernel 存在两个近似方法：
- `run_tick`（服务 Autonomous）
- `run_turn`（服务 Assistant，多了 `history_messages` / `input_message` / `confirmation_gate`）

本计划要把二者**合并为唯一的 `run_round`**，并把 Agent 专属差异全部上浮：

- `history_messages` / `input_message`：通过 `Observation` 的扩展字段 `input: InputEnvelope | None` 承载，或由 Driver 预先装配进 `Observation.recent_events` / `world_snapshot`，Kernel 不再感知"这是 Assistant 的一次用户输入"。
- `confirmation_gate`：作为 `PluginHost.register_guard_check` 的一种检查（Assistant-only 的 guard check 在 Assistant Driver 装配时注册）；Kernel `Guard` 节点统一调用 plugin guard checks。
- `seed_tool_calls`：作为 `Observation.seed_tool_calls` 字段，如不为空则 Kernel `Deliberate` 跳过本 round 模型调用，直接以 seed tool calls 进入 `Act`。

### 2.2 RoundOutcome 契约

```python
@dataclass
class RoundOutcome:
    status: Literal["continue", "complete", "wait_human", "escalate", "error", "cancelled"]
    gate_signal: Literal[
        "continue",
        "wait_human",
        "budget_exhausted",
        "goal_done",
        "paused",          # 包含被 cancel 的情况
        "escalate",
    ] | None
    final_output: str | None
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]
    memory_updates: list[MemoryUpdate]
    metadata: dict[str, Any]
    escalate_reason: str | None
```

- `gate_signal is None` 或 `"continue"`：Driver 可继续下一 round。
- 其他值：Driver 必须停止当前 turn（由 Driver 决定是否收尾为 wait_human / escalate / completed / cancelled）。

### 2.3 Cancel 契约（mid-round 观察 + 分层保证）

**不要**把 cancel 写成"只在 round 边界生效"。Codex 和 Claude Code 的实际行为都是 **mid-round 多点观察 + best-effort**（参见 `claude-code#17466`、`openai/codex#5905`、`claude-agent-sdk-typescript#120`）。recruit-agent 场景工具可能跑 30 秒+（浏览器抓取、MCP 调用），round 边界 cancel 体验不可接受。

#### 2.3.1 Cancel 观察点

| 观察点 | 保证级别 | 负责人 |
|--------|---------|-------|
| 进入 `run_round` 时（Deliberate 入口之前） | 硬保证：立即返回 `RoundOutcome(status="cancelled", gate_signal="paused")`，不进模型 | `AgentKernel.run_round` |
| 模型流式输出期间 | 硬保证：中止 provider 流，保留已产出的 partial text | `kernel/deliberate.py`（provider 层支持 abort） |
| 两次 tool call 之间 | 硬保证：不再发起下一个 tool | `kernel/act.py` |
| tool call 执行期间 | **best-effort**：把 `cancel_token` 透传进 tool，由 tool 自身翻译为 HTTP abort / subprocess SIGTERM / page.close 等 | 工具实现方 |
| Driver 的 `while` 循环头 | 硬保证：`cancel_token.is_cancelled()` 或 `outcome.status == "cancelled"` 为真则不起新 round | Driver |

#### 2.3.2 被 cancel 的 round 的语义

- `RoundOutcome.status = "cancelled"`
- `RoundOutcome.gate_signal = "paused"`（**不要**单独加 `"cancelled"` 作为 gate_signal 值，cancel 在 Driver 视角就是一种"暂停/需要人工处理"）
- 已产生的 partial side effect（部分 model output、已执行完的 tool result）**保留**，通过 `AgentRuntimeEvent(event_type="round.completed", payload={"cancelled": true, "partial_output": ..., "completed_tool_calls": [...], ...})` 写入事件流
- Memory 写入策略：被 cancel 的 round 的 `UpdateMemory` 节点**跳过**，避免把不完整的推理结果写进长期记忆

#### 2.3.3 Driver 侧处理

- Driver 在 round 返回后检查 `cancel_token.is_cancelled() or outcome.status == "cancelled"`
- 为真则跳出 `while` 循环，把 turn 记录标记为 `cancelled`，SSE 发 `turn.cancelled`
- **Assistant 额外要求**：`cancel_token` 在一个 turn 结束后必须重置（新 turn 用新的 token 实例），避免 token 被复用导致下一 turn 一启动就是 cancelled 状态

### 2.4 任务

- [ ] 在 `runtime/models.py` 新增 `RoundOutcome`（含 `status="cancelled"` 取值），删除 `TickOutcome`；所有对 `TickOutcome` 的 import 和使用一次性替换为 `RoundOutcome`。
- [ ] 在 `runtime/models.py` 为 `Observation` 增加 `input: InputEnvelope | None` 字段（`InputEnvelope` 内含 `history_messages`、`input_message`、`seed_tool_calls`）。
- [ ] 在 `kernel/kernel.py` 合并 `run_tick` 与 `run_turn` 为 `run_round`，签名：
  ```python
  def run_round(
      self,
      *,
      goal: GoalRef,
      observation: Observation,
      limits: RoundLimits,
      cancel_token: CancellationToken | None = None,
      event_sink: EventSink | None = None,
      memory_service: Any | None = None,
      learning_writer: Any | None = None,
  ) -> RoundOutcome: ...
  ```
- [ ] 在 `kernel/deliberate.py` 识别 `observation.input.seed_tool_calls`，如果有就跳过模型调用，直接走工具执行路径。
- [ ] 在 `kernel/deliberate.py` 入口先 `cancel_token.raise_if_cancelled()`（或等价检查）；provider 流式输出期间把 `cancel_token` 透传到 provider 层，支持 abort。
- [ ] 在 `kernel/act.py` 每次 tool call 前检查 cancel；把 `cancel_token` 透传到 tool 执行接口，允许 tool 实现自行翻译为 abort 信号。
- [ ] 在 `kernel/update_memory.py` 对被 cancel 的 round（`status == "cancelled"`）**跳过** memory 写入。
- [ ] 在 `kernel/guard.py` 把 `confirmation_gate` 改为通过 `plugin_host.run_guard_checks(...)`，Assistant 专用的确认规则在 Assistant Driver 装配时通过 `plugin_host.register_guard_check("assistant_confirmation", ...)` 注册，不作为 Kernel 参数。
- [ ] 在 `kernel/evaluate.py` 统一产出 `RoundOutcome` 并计算 `gate_signal`：
  - 被 cancel → `status="cancelled"`, `gate_signal="paused"`。
  - 模型 `stop_reason == "end_turn"` 且无 `tool_calls` → `gate_signal = "goal_done"`。
  - Guard 要求确认 → `gate_signal = "wait_human"`。
  - 预算（round 内 tokens/tool-timeout）命中 → `gate_signal = "budget_exhausted"`。
  - 其他：`gate_signal = "continue"`。
- [ ] 删除 `AgentKernel.run_tick` 与 `AgentKernel.run_turn` 两个方法的全部残留代码，包括 `_assistant_confirmation_gate`。

### 2.5 最小测试

- [ ] `tests/kernel/test_run_round.py`：
  - [ ] Autonomous 场景：无 input，走模型→工具→最终输出路径，断言 `gate_signal` 正确。
  - [ ] Assistant 场景：通过 `Observation.input` 注入 history+message，断言和原 `run_turn` 行为等价。
  - [ ] Guard 拦截：断言返回 `gate_signal == "wait_human"`，`escalate_reason` 有值。
  - [ ] seed_tool_calls：断言跳过模型调用，直接执行工具。
- [ ] `tests/kernel/test_run_round_cancel.py`：
  - [ ] 进入 `run_round` 前 cancel：断言立即返回 `status="cancelled"`，`gate_signal="paused"`，模型**未被调用**。
  - [ ] tool call 之间 cancel：第一个 tool 执行完 → 触发 cancel → 第二个 tool **未被调用**；返回的 `RoundOutcome.tool_results` 只包含第一个 tool。
  - [ ] cancel 后 memory 不写：断言 `memory_updates` 为空或未调用底层 write 接口。

---

## 3. 限额拆分：RoundLimits vs TurnLimits

### 3.1 拆分原则

- `RoundLimits`（Kernel 持有）：**单次 round 内**的约束——单次模型调用 token 上限、单次 tool 调用 timeout、单次 round 内的工具并发。
- `TurnLimits`（Driver 持有）：**一个 turn 跨 round** 的约束——`max_rounds_per_turn`、turn 总 wall-clock timeout、turn 内总 token 预算、turn 级 cooldown。

### 3.2 任务

- [ ] 把当前 `runtime/limits.py` 的 `RuntimeLimits` 拆成两类：`RoundLimits`、`TurnLimits`。
- [ ] `RoundLimits` 保留与单次调用相关的字段（token 上限、tool timeout 等）；`TurnLimits` 新增 `max_rounds_per_turn`、`turn_timeout_seconds` 等。
- [ ] Kernel 只接受 `RoundLimits`；Driver 在本地构造 `TurnLimits`，并在 `while` 循环里自行检查。
- [ ] 如果有 `turn_idx` / `max_turns_per_*` 命名残留，一次性改为 `round_idx` / `max_rounds_per_turn`。

### 3.3 最小测试

- [ ] `tests/runtime/test_limits_split.py`：断言 `RoundLimits` 不含 `max_rounds_per_turn`，`TurnLimits` 不含 round 级字段。

---

## 4. Driver 持有 turn 生命周期

### 4.1 AutonomousAgent 改造

- [ ] 把 `run_tick_from_envelope` 改名为 `run_turn_from_envelope`。
- [ ] 在方法体内引入 `while` 循环，每轮调用 `self.kernel.run_round(...)`；每轮后：
  - 将 round 结果通过 `AgentRuntimeEvent(event_type="round.completed")` 写入事件流（round 不独立落表）。
  - 检查 `outcome.gate_signal`：非 `None` / `"continue"` 则跳出循环。
  - 检查 `cancel_token.is_cancelled()`：是则跳出并把 turn 标记为 cancelled。
  - 检查 `TurnLimits.max_rounds_per_turn` / wall-clock：命中则跳出并标记为 budget_exhausted。
- [ ] turn 起止记录落到 `AgentTurnRecord`（即原 tick 表改名）。
- [ ] round 级不落独立表；每 round 完成后通过 `AgentRuntimeEvent(event_type="round.completed", payload={"round_seq": n, ...})` 写入事件流。
- [ ] `AgentRuntimeEvent` 发 `turn.started` / `turn.completed` / `turn.waiting_human`。
- [ ] **调用点同步改名**：`services/backend/src/scene_pilot/agents/heartbeat.py:31` 目前调用 `self.autonomous_agent.run_tick_from_envelope(...)`，改名完成后必须同步改为 `run_turn_from_envelope(...)`。心跳任务的 payload 结构不变，只是方法名改。
  - 同时检查 `services/backend/tests/agent/integration/test_heartbeat.py` 里的断言与调用点，一并改名。

### 4.2 AssistantAgent 改造

- [ ] 移除 Assistant 自己绕过 Kernel 直接调 `provider.generate` 的残留路径（如果 cutover plan 后还有的话）。
- [ ] 在 `run_turn(conversation_id, message)` 内部引入同样的 `while` 循环，每轮调用 `self.kernel.run_round(...)`，`Observation.input` 用 conversation history + new message 装配。
- [ ] 退出条件：
  - `gate_signal == "goal_done"`：turn 完成，产生 assistant reply。
  - `gate_signal == "wait_human"`：turn 在需要确认处停止，向 SSE 发 `turn.waiting_human`，等待 `/confirm` 触发**新的 recovery turn**（recovery 是**新 turn 而非同 turn 续跑**）。
  - `cancel_token.is_cancelled()`：立刻跳出，向 SSE 发 `turn.cancelled`。
- [ ] SSE 流：每次 round 完成都 flush 本 round 的 `AssistantMessage` 内容；不要等整 turn 结束再一次吐出。

### 4.3 最小测试

- [ ] `tests/agents/test_autonomous_turn_loop.py`：
  - [ ] 多 round turn：第 1 round 返回 `continue` + 工具调用，第 2 round 返回 `goal_done`；断言 Kernel 被调用 2 次。
  - [ ] wait_human：第 1 round 返回 `wait_human`，断言立即停止，turn 状态为 `waiting_human`。
  - [ ] budget_exhausted：`TurnLimits.max_rounds_per_turn = 2` 但模型每 round 都返回 `continue`，断言第 2 round 后跳出并标记 budget_exhausted。
- [ ] `tests/agents/test_assistant_turn_loop.py`：
  - [ ] 多 round turn：断言 SSE 在每个 round 边界都 flush 了内容。
  - [ ] cancel：启动 turn 后在可观察点触发 cancel，断言跳出且状态为 cancelled。
  - [ ] confirm：wait_human 后调用 `/confirm` 产生新 turn（不是旧 turn 续跑）。

---

## 5. 数据库改造（直接改模型，不做迁移）

### 5.0 前提：无历史包袱

本项目是 local-first，SQLite 文件按 workspace 存储、每台机器独立，**没有线上库需要迁移**。所以本节**不写 Alembic migration**，直接改 ORM 模型和 `create_all` 逻辑，开发环境删除旧 SQLite 文件即可重建。

**严禁：**
- 新建 Alembic revision。
- 写 `batch_op.rename_table` / `alter_column` 这类迁移逻辑。
- 保留旧表/旧列作为兼容。
- 用 `_v2` 后缀新建表并留旧表共存。
- 任何"先双写，再读旧删新"的分阶段方案。

**直接做：**
- 改 ORM 类名、表名、列名；旧的 ORM 类直接删除。
- 启动时 `Base.metadata.create_all(engine)` 会按新模型建表。
- 开发环境如果已有旧 SQLite 文件，human 在实施完成后手动删除即可（README 或 commit message 里提醒一句）。

### 5.1 ORM 模型改造

全部在 `services/backend/src/scene_pilot/models/domain.py` 里直接改：

- [ ] **先删除**旧的 `AgentTurnRecord`（内层、`__tablename__ = "agent_turn_records"`、`tick_pk` FK）ORM 类。
- [ ] **再改名** `AgentTickRecord` → `AgentTurnRecord`，`__tablename__` 从 `"agent_tick_records"` 改为 `"agent_turn_records"`。
- [ ] 改列：`tick_id` → `turn_id`，`tick_pk` / `tick_seq`（如有）同步改名。
- [ ] `AgentRun.ticks_count` 改名为 `turns_count`；**删除**旧的 `AgentRun.turns_count`（不保留 `rounds_count`）。
- [ ] `AgentRuntimeEvent.tick_id` 改名为 `turn_id`；**删除** `AgentRuntimeEvent.turn_id` 列（原来指向内层 turn，不再需要）。
- [ ] 所有跨模型的 `ForeignKey` 字符串同步更新。

### 5.2 导出更新

- [ ] `services/backend/src/scene_pilot/models/__init__.py`：把导出从 `AgentTickRecord` 改为 `AgentTurnRecord`，旧的内层 `AgentTurnRecord` 导出直接删除。
- [ ] `services/backend/src/scene_pilot/runtime/__init__.py`：`TickOutcome` 导出改为 `RoundOutcome`。
- [ ] 其他 `from ... import AgentTickRecord` / `TickOutcome` 的调用点全部同步。

### 5.3 开发环境清理提示

- [ ] 在本 plan 实施完成的 commit message 或 `README.md` 开发说明里加一行：
  > 本次改造直接重命名了数据库表与字段，无兼容层。升级后请删除本地 SQLite 文件（默认位置 `~/.recruit-agent/*.db`），重启后端会按新模型重建。

### 5.4 最小测试

- [ ] `tests/db/test_schema_terminology.py`：
  - [ ] 启动 in-memory SQLite，`create_all` 后断言表 `agent_turn_records` 存在、`agent_tick_records` 不存在。
  - [ ] 断言任何表的列名里都不出现 `tick_id` / `tick_pk` / `tick_seq` / `ticks_count`。
  - [ ] 断言 `agent_runtime_events` 表列里有 `turn_id`，不含旧的内层 `turn_id`（原来指向内层 turn 的那一列已删除）。

---

## 6. API / Envelope / SSE 改造

- [ ] `api/routers/agent.py` 中所有 `/ticks` 路径改为 `/turns`，函数名 `*tick*` → `*turn*`。
- [ ] Envelope JSON 字段 `tick_id` → `turn_id`；若有 `tick_seq` → `turn_seq`。
- [ ] SSE 事件名按 §1.6 全量替换。
- [ ] Desktop (`apps/desktop/src/lib/api.ts` 等) 同步更新类型定义；运行 `npm run desktop:typecheck` 确保通过。
- [ ] 如果 desktop 代码里任何组件引用了 `tick*` API 或字段，全部改名；但 CSS `sticky` 等无关 token 不要动。

### 6.1 最小测试

- [ ] `tests/api/test_turn_routes.py`：断言 `/api/runs/{run_id}/turns` 可用，`/ticks` 返回 404。
- [ ] `tests/api/test_sse_events.py`：断言 SSE 流里事件名是 `turn.*`，不出现 `tick.*`。

---

## 7. 文档更新

### 7.1 `docs/agent-v2-design-summary.md` 与 `docs/agent-v2-implementation-spec.md`

- [ ] 全文搜索替换 `tick` → `turn`（注意 `ticks` 表名场景要对应 `turns`）。
- [ ] 搜索 `turn_idx`、`max_turns_per_tick`、`max_turns_per_turn` 等内层变量名，一次性改为 `round_idx` / `max_rounds_per_turn`。
- [ ] 搜索 `TickOutcome` → `RoundOutcome`。
- [ ] 在两份文档开头加入**术语锚定段**（文案与 `README.md` 中的 Terminology anchor 一致，中文版）：
  > **术语锚定**：本项目 `turn` 采用 Codex 语义——一次从触发（用户消息 / 调度唤醒 / run 续跑）到下次需要人类介入为止的完整 LLM 驱动循环。`round` 表示 turn 内部一次 `model → tool → observe` 往返，对应 Claude Agent SDK 文档里的 `turn`。本项目不使用 `tick` 一词。
- [ ] 在 `docs/agent-v2-design-summary.md` 的架构图部分替换为与 `README.md` 一致的三层图。
- [ ] 在 `docs/agent-v2-implementation-spec.md` 的节点/契约章节补一段"Kernel 只跑 round，turn 是 Driver 层概念"的子节，内容与本计划 §2 + §4 对齐。

### 7.2 `README.md`

- [ ] 本计划执行完成后，验证 `README.md` 中 "Agent Runtime Architecture" 章节已经存在（是在术语收敛讨论时提前加进去的），不需要重新写，但要确认与实际代码符号一致（方法名 `run_round`、字段名 `turn_id` 等）。

### 7.3 CLAUDE.md / agent-plan 里其他文档

- [ ] 全仓库 `docs/` 下搜索 `tick`，确认除了明确的"术语锚定反例说明"之外，其他地方不再出现。
- [ ] `CLAUDE.md`：如出现 `tick` 一律清除或改名。

---

## 8. 全量回归与收尾

- [ ] 全仓库 ripgrep `\btick\b`（大小写不敏感）：
  - 仅允许出现在：
    - 前端 CSS `sticky`（不匹配 `\btick\b`，应无命中）；
    - 文档中明确的"本项目不使用 tick"术语锚定段；
    - 任何 ORM migration 历史文件（Alembic 旧 revision 不应倒退修改，但新 revision 应使用新命名）。
  - 除上述豁免之外**不允许任何命中**。任何一处命中都必须消除。
- [ ] 全仓库 ripgrep `TickOutcome`、`run_tick`、`AgentTickRecord`、`same_scope_ticks`、`max_turns_per_tick`、`tick_id`、`tick_completed`：**0 命中**。
- [ ] 全量 backend 测试：
  ```bash
  python3 -m pytest services/backend/tests -q
  ```
  全绿。
- [ ] `npm run desktop:typecheck` 通过。
- [ ] 向 review 阶段提交一份简短 changelog（commit message 体），说明：
  - 废弃 tick；统一 turn / round 命名。
  - Kernel API 合并为 run_round；Driver 持有 turn 循环。
  - RoundOutcome 携带 gate_signal。
  - RoundLimits / TurnLimits 拆分。
  - 数据库 / API / SSE 同步改名。
  - 文档加入术语锚定段。

---

## 9. 验收 checklist（给 human 在 review 阶段对表用）

- [ ] 全仓库没有 `tick` 残留（术语锚定段除外）。
- [ ] `AgentKernel` 只有 `run_round` 一个核心方法，没有 `run_tick` / `run_turn`。
- [ ] `AutonomousAgent` 和 `AssistantAgent` 都通过 `while not gate` 循环调用 `run_round`。
- [ ] `RoundOutcome.gate_signal` 被 Driver 正确读取并用于退出循环。
- [ ] `RoundLimits`（Kernel）与 `TurnLimits`（Driver）已拆分。
- [ ] 数据库表：`agent_turn_records` 存在，`agent_tick_records` 不存在。
- [ ] API：`/api/runs/{run_id}/turns` 可用，`/ticks` 404。
- [ ] SSE 事件名都是 `turn.*`。
- [ ] `docs/agent-v2-design-summary.md`、`docs/agent-v2-implementation-spec.md`、`README.md` 术语一致并含锚定段。
- [ ] 全量测试绿色。
