# Autonomous Agent 改进计划 + Assistant Agent 设计说明

> Status: archived
> Supersedes: -
> Superseded by: docs/plan/archive/agent-v2-implementation-spec.md; docs/plan/completed/2026-04-19-agent-v2-direct-cutover-plan.md
> Distilled into: partial: docs/specs/2026-04-20-dual-agent-product-architecture.md; docs/specs/2026-04-20-autonomous-agent-runtime-constraints.md
> Last reviewed against code: 2026-04-20
> Legacy path retained: docs/autonomous-agent-improvement-plan.md

> 本文档基于 [agent-context-memory-design-reference.md](./agent-context-memory-design-reference.md)
> 的设计参考，给出 recruit-agent 现有 Autonomous Agent 的改进路径，以及尚未启动的
> Assistant Agent 的初步设计规范。
>
> 核心思路：把 Autonomous Agent 重构成一个**最小可复用的 round 级 LLM 内核**，外面包装清晰的
> Agent Assembly / Agent Kernel / Execution Cycle 三段结构。外层统一为 Driver 持有的 `turn`，
> 内层统一为 Kernel 只负责的 `run_round()`。Assistant Agent 复用同一个内核，但 Trigger 来自人。

---

## 目录

- [Part 0：现状盘点](#part-0现状盘点)
- [Part 1：核心抽象 — Agent Assembly / Kernel / Execution Cycle](#part-1核心抽象--agent-assembly--kernel--execution-cycle)
- [Part 2：最小 Turn Shell + Round Kernel 框架](#part-2最小-turn-shell--round-kernel-框架)
- [Part 3：Turn / Round 14 节点分析与最终建议](#part-3turn--round-14-节点分析与最终建议)
- Asistance
- [Part 5：Assistant Agent 设计规范](#part-5assistant-agent-设计规范)
- [Part 6：两个 Agent 的共用与差异](#part-6两个-agent-的共用与差异)

---

# Part 0：现状盘点

读完 `services/agent.py`、`scheduler/scheduler.py`、`runtime/agent_loop.py`、
`runtime/prompts.py`、`services/recruit_agent.py`、`services/context_assembler.py`
后，对当前 Autonomous Agent 的判断：

## 已经有的能力


| 模块                                    | 状态   | 评价                                       |
| ------------------------------------- | ---- | ---------------------------------------- |
| `SerialScheduler`                     | ✅ 完整 | TaskRunner + FollowUpFactory 模式干净，可直接复用  |
| `SqlAlchemyQueue`                     | ✅ 完整 | 持久化、stale recovery、状态流转都有                |
| `AgentLoop`                           | ✅ 跑通 | LLM + Tools + 多 turn 循环、waiting_human 支持 |
| `ContextAssemblerService`             | ✅ 完整 | fragment-based 上下文拼装，有 score/budget      |
| `PromptBuilder`                       | ✅ 可用 | 文件式 prompt + 模板渲染                        |
| `AgentRun / Checkpoint / Event`       | ✅ 完整 | runtime 状态、checkpoint、事件流齐全              |
| 三类 Memory 表                           | ✅ 完整 | Candidate / Job / Global 三层              |
| `prompt_config / RecruitAgentProfile` | ✅ 完整 | 长期 prompt 与 policy 都在表里                  |


## 当前的问题

### 问题 1：Run / Turn / Round 的边界不清

`build_runner()` 把"一个任务"展开成一次 `agent_loop.run()`，里面实际消耗的是受预算限制的多轮 round。
但调度层（`SerialScheduler.run_once`）也叫"一次执行"，再上面 `FollowUpFactory`
又派生"下一步任务"。三层循环的语义没有被命名，文档/代码里都不一致。

### 问题 2：Orchestrator 是规则机，不是 LLM

`_next_tasks_for_result()` 是硬编码的 stage 状态机：`exploration_trial → strategy_distill → ...`。Autonomous Agent 没有"自己决定下一步做什么"的能力——
所有跨任务的编排都是 if/else 写死的。这违背"持续性、自主"的目标。

### 问题 3：Autonomous turn 的"持续性触发"缺位

调度器只有 `run_once / run_until_empty`，没有真正的"心跳触发器"。
现在跑起来要靠外部 cron 或 API 推一个任务进队列。"持续找新简历、持续评分"
没有自己的节奏发动机。

### 问题 4：上下文组装重，但不针对 cache

`ContextAssemblerService.build()` 每个 fragment 一段，按 score 拼，
没有按"稳定度分书签"（Part 8）。每次 LLM 调用大概率把 cache 打废。

### 问题 5：Autonomous Agent 与执行框架强耦合

`agent_loop.run()` 里已经塞进了 `execution_contract`、`scene_assessment`、
`planner_guidance` 等概念。这些是更上层的"管理执行" 抽象，混在内核里
让"最小 LLM loop"难以剥离。

### 问题 6：Skill 沉淀路径单向

`EvolutionArtifact` 是产物表，但从 Autonomous Agent 写入 GlobalMemory / 升级 Skill
的路径要走多个服务、多次审核。没有一个"自学习闭环"在内核里跑通。

---

# Part 1：核心抽象 — Agent Assembly / Kernel / Execution Cycle

按 agent 启动到执行的时间顺序，分三段。**每个 Autonomous Agent 实例都跑这三段。**

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Agent Assembly  （启动一次，长期持有）                     │
│    把"Agent 是谁、能做什么"组装好                             │
│                                                              │
│    输入：RecruitAgentProfile + GlobalMemory 索引 +           │
│         Skill 注册表 + Tool 注册表                            │
│    产出：AgentDefinition（Persona、Tools、Long-term Memory   │
│         索引、Policies）                                      │
│    更新频率：profile 改动时；GlobalMemory 增减时              │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Agent Kernel  （常驻内存，单实例）                         │
│    封装"如何跑一个 round" — 即 minimal LLM loop              │
│                                                              │
│    职责：                                                    │
│      · 接收 Goal + Observation + 历史消息片段                 │
│      · 组装 messages（system / user / tool_results）          │
│      · 调一次 LLM，完成一轮 model → tool → observe           │
│      · 把工具调用分发给 Tool Bus                             │
│      · 把决策结果（行动 / 观察 / 状态变更）持久化            │
│                                                              │
│    内核不知道业务逻辑（评分、外联、改 JD），它只知道          │
│    "拿到上下文 → 让 LLM 决策 → 执行决策 → 写状态"            │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Execution Cycle  （Run + 多个 Turn）                       │
│    一个 Run 对应 GoalSpec / TaskEnvelope，由若干 Turn 组成   │
│                                                              │
│    Run 启动：从 queue 拿到 envelope → 创建 AgentRun 记录     │
│    Run 执行：Driver 反复发起 turn，并在每个 turn 内驱动多轮 round │
│    Run 结束：写 outcome、派生 follow-up、关闭 run            │
└─────────────────────────────────────────────────────────────┘
```

**关键性质**：

- **Assembly** 是"我是谁" — 静态、长期持有、稳定打缓存
- **Kernel** 是"我如何跑一轮 round" — 行为模板、纯框架、不可被业务侵入
- **Execution Cycle** 是"我现在在做什么" — 动态、围绕一个具体目标

把这三段分开后，Autonomous Agent 和 Assistant Agent 共用 Assembly + Kernel，
**只在 Trigger 与 Outcome 处理上不同**。

---

# Part 2：最小 Turn Shell + Round Kernel 框架

剥离一切业务概念后，应该先把**外层 turn 壳**和**内层 round 内核**分开：

```python
def run_turn(driver: AutonomousAgent, kernel: AgentKernel, run: Run) -> RoundOutcome:
    observation = driver.load_observation(run)
    round_history = []

    while driver.should_continue_turn(run, round_history):
        outcome = kernel.run_round(
            goal=driver.goal_for(run),
            observation=observation.with_history(round_history),
            limits=driver.round_limits,
        )
        round_history = driver.update_round_history(round_history, outcome)
        if outcome.gate_signal not in {None, "continue"}:
            return outcome

    return driver.finish_turn(run, round_history)
```

外层负责：
- 触发 turn
- 装配本次 Goal / Observation / turn budget
- 决定是否进入下一轮 round
- 持久化 turn 结果

内层负责：
- 只跑一次 `run_round()`
- 返回 `RoundOutcome`
- 不知道自己是否处在 Autonomous 还是 Assistant

## 5 个 round 级 Kernel 接口


| 接口                                 | 输入                       | 输出              | 职责                                    |
| ---------------------------------- | ------------------------ | --------------- | ------------------------------------- |
| `sense(run)`                       | 当前 Run                   | `Observation`   | 从 DB / 外部源拉取本 round 要看的 observation    |
| `assemble(run, observation)`       | Run + Observation        | `LLMRequest`    | 拼 system / messages / tools，分书签       |
| `deliberate(request)`              | LLMRequest               | `LLMDecision`   | 调 LLM、跑 tool_use 多 turn、产出 decision   |
| `act(decision, run)`               | Decision + Run           | `Effects`       | 执行决策（外部工具落地、写 DB、enqueue 后续 task）     |
| `evaluate(decision, effects, run)` | Decision + Effects + Run | `RoundOutcome`  | 决定 continue / wait_human / complete / escalate |


> Loop 这个词在 Driver 层只是 "turn 内反复跑 round"。LLM 内部的多轮 tool 往返在 `deliberate`
> 里完成；Driver 在 `evaluate` 之后决定要不要再发下一轮 `run_round()`。两层不要混。

## 上下文分书签的强制约定

`assemble` 必须按下表组织 system，否则 cache_control 失效：

```
system: [
  block 1: Persona + Behavior Rules + Tools usage policy   ← 书签 1
  block 2: prompt_config + GlobalMemory 索引                ← 书签 2
  block 3: 当前 Run 锁定的 Candidate/Job memory（如有）      ← 书签 3
]
messages: [
  user: Observation 序列化（每 turn 必变）
  ... 历次 tool_use / tool_result（仅本 turn 内累积）
]
```

**铁律**：

1. 任何"每 turn 变"的内容**绝不能进 system**
2. 时间戳、turn 序号、当前 candidate_id 都属于动态，统一在 user 里
3. 三个书签独立编辑，避免改一处波及更深的缓存层

---

# Part 3：Turn / Round 14 节点分析与最终建议

你给的 14 节点表覆盖很全，但需要按**外层 turn / 内层 round**重新分层。

## 你的原始 14 节点 → 我的最终建议

| #   | 原节点                                   | 我的处理                           | 理由 |
| --- | ------------------------------------- | -------------------------------- | --- |
| 1   | Trigger / Wakeup                      | ✅ 保留为 **turn 入口**               | 是 Driver 的入口，不可省 |
| 2   | Bootstrap                             | 🔀 移到 **Resolve Assembly**       | "组装我是谁"是 turn 起点做的事，不属于 round |
| 3   | Sense                                 | ✅ 保留为 **round 节点**              | `run_round()` 的第一步 |
| 4   | Update Context                        | 🔁 并入 Assemble                   | round 内不维护长期 in-memory context，直接组装请求 |
| 5   | Assemble Request                      | ✅ 保留                             | `assemble()` 接口 |
| 6   | Call LLM                              | 🔁 并入 Deliberate                 | 是 `deliberate()` 的内部动作 |
| 7   | Assistant Turn                        | 🔁 并入 Deliberate                 | 模型输出和 tool call 都是同一轮 deliberation 的产物 |
| 8   | Guard / Policy Check                  | ✅ 保留                             | round 内在 act 之前裁决 |
| 9   | Act                                   | ✅ 保留                             | `act()` 接口 |
| 10  | Observe                               | 🔀 作为 tool_result 回灌或下一轮输入     | 同步反馈留在当前 turn，异步反馈靠下一次 turn 再感知 |
| 11  | Re-enter Loop                         | 🔁 改成 Driver 决定是否继续下一轮 round    | 这是 turn shell 的控制流，不是独立节点 |
| 12  | Evaluate                              | ✅ 保留                             | `evaluate()` 返回 `RoundOutcome` |
| 13  | Update Memory                         | ✅ 保留                             | round 结束后的学习沉淀出口 |
| 14  | Continue / Sleep / Respond / Escalate | ✅ 作为 **turn 出口**                 | 由 Driver 根据 `RoundOutcome` 决定 |

## 我建议的最终模型

```text
0. Agent Assembly（turn 起点解析）
1. Trigger / Wakeup（Driver）
2. Resolve Assembly（Driver）
3. run_round():
   Sense
   → Assemble
   → Deliberate
   → Guard
   → Act
   → Update Memory
   → Evaluate
4. Driver decide:
   continue next round / stop turn / sleep / wait_human / complete / escalate
```

### 分层映射

| 层级 | 节点 | Owner | 数据落地 | 对应原节点 |
| --- | --- | --- | --- | --- |
| **Turn** | Trigger / Wakeup | Driver | `AgentRuntimeEvent("turn.started")` | Trigger / Wakeup |
| **Turn** | Resolve Assembly | Driver | 解析本 turn 的 profile / policy / tool scope | Bootstrap |
| **Round** | Sense | `kernel.run_round()` | 不写库，只返回 `Observation` | Sense |
| **Round** | Assemble | `kernel.run_round()` | 不写库，只返回 `LLMRequest` | Update Context + Assemble Request |
| **Round** | Deliberate | `kernel.run_round()` | `llm_call` 与 tool 回灌 | Call LLM + Assistant Turn |
| **Round** | Guard | `kernel.run_round()` | 拒绝时写审批或 escalate | Guard / Policy Check |
| **Round** | Act | `kernel.run_round()` | 持久化副作用 / DB 变更 / Effects | Act + Observe |
| **Round** | Update Memory | `kernel.run_round()` | 写 Memory / Learning / Artifact | Update Memory |
| **Round** | Evaluate | `kernel.run_round()` | 产出 `RoundOutcome` | Evaluate |
| **Turn** | Exit Decision | Driver | 根据 `RoundOutcome` 决定 turn 出口 | Continue / Sleep / Respond / Escalate |

### 被吸收的内容去哪了

- **Bootstrap** → `Resolve Assembly`
- **Update Context** → `Assemble`
- **Assistant Turn** → `Deliberate` 内部的模型输出阶段
- **Re-enter Loop** → Driver 决定是否继续下一轮 round
- **Observe** → 当前 round 的 tool_result 或下一次 turn 的 `Sense`

---

# Part 4：Autonomous Agent 改进路线图

按"先建骨架 → 再迁移业务 → 再做自学习"的顺序，分 4 个阶段。

## 阶段 1：剥离最小 Kernel（2 周）

### 1.1 新建 `runtime/kernel.py`

```python
@dataclass
class AgentKernel:
    profile: RecruitAgentProfile        # Assembly 阶段产物
    provider: LLMProvider               # 共享
    tools: ToolRegistry                 # 共享
    context_assembler: ContextAssembler # 改造后的版本（见 1.2）
    guard_policy: GuardPolicy           # 新增
    memory_writer: MemoryWriter         # 新增

    def run_round(self, goal: GoalRef, observation: Observation) -> RoundOutcome:
        request = self.assemble(goal, observation)
        decision = self.deliberate(request)
        if not self.guard(decision, observation):
            return RoundOutcome(status="escalate", gate_signal="escalate")
        effects = self.act(decision, goal)
        self.persist_learning(decision, effects, goal)
        return self.evaluate(decision, effects, goal)
```

### 1.2 改造 `ContextAssemblerService` → 三书签输出

**现状**：每个 fragment 拼一段，按 score 拼，没有 cache 边界。

**目标**：按"稳定度 → 书签层"拆分：

```python
def build_layered_request(self, ...) -> LLMRequest:
    return LLMRequest(
        system=[
            CacheBlock(persona + tools_doc + behavior_rules),       # 书签 1
            CacheBlock(prompt_config + global_memory_index),         # 书签 2
            CacheBlock(candidate_memory_view + job_memory_view),     # 书签 3（可选）
        ],
        messages=[
            Message(role="user", content=world_snapshot_serialized),
        ],
        tools=tool_registry.describe(...),
    )
```

每个 `CacheBlock` 序列化时打 `cache_control: ephemeral`。

### 1.3 把现有 `agent_loop.run()` 切成 `deliberate()`

`AgentLoop.run` 内部的多 turn 循环原样保留，包成 `kernel.deliberate(request)`。
**execution_contract / scene_assessment 等业务概念从内核剥离**——它们应该在
`assemble()` 阶段以"动态上下文"的形式注入，而不是在 loop 内特判。

### 1.4 单元测试

每个接口独立测：mock provider 验证 `deliberate`，mock tools 验证 `act`。
内核不接触业务，可以用纯 fixture 跑。

## 阶段 2：替换 Orchestrator（2 周）

**目标**：删掉 `_next_tasks_for_result` 的硬编码 stage 状态机，让 LLM 自己决定
"下一步做什么"。

### 2.1 把 follow-up 逻辑搬进 LLM tool

新增工具 `enqueue_follow_up`：

```
{
  "name": "enqueue_follow_up",
  "input_schema": {
    "task_type": str,
    "candidate_id": str | None,
    "priority": int,
    "delay_seconds": int | None,
    "reason": str
  }
}
```

LLM 在 `deliberate` 阶段决定要不要派生 follow-up；`act` 阶段调这个工具入队。

### 2.2 新增"自我触发"工具

`schedule_self_wakeup`：让 LLM 决定"我下一次 turn 应该在 X 秒后自己醒"。
没有它就是 sleep 直到外部 trigger。

这把"持续性"交给了 LLM——你的"持续找简历"不靠 cron，靠 LLM 在每个 turn
末尾决定"我评估完一波了，2 分钟后再来"。

### 2.3 删除 `_next_tasks_for_result` 与 `resolve_adaptive_stage`

老的 stage 流转规则当作"默认 prompt 提示"塞进 prompt_config，
而不是当作硬编码 if/else。LLM 看到 "通常的下一步是 X"，但可以违反。

## 阶段 3：心跳触发器（1 周）

### 3.1 新增 `services/heartbeat.py`

```python
class Heartbeat:
    def __init__(self, kernel: AgentKernel, queue: SqlAlchemyQueue, *, interval: int = 30):
        self.kernel = kernel
        self.queue = queue
        self.interval = interval

    async def run_forever(self):
        while True:
            envelope = self.queue.get()
            if envelope is None:
                # 没有外部任务，触发一个"自检 turn"
                envelope = self._build_self_audit_envelope()
            run = self._spawn_or_resume_run(envelope)
            outcome = self.agent.run_turn_from_envelope(envelope)
            self._handle_outcome(outcome, run)
            await asyncio.sleep(self.interval if outcome.kind != "continue" else 0)
```

**自检 turn** 的语义：没有外部任务时，给 LLM 一个固定的 prompt
"看看当前 Observation，决定要不要主动做点什么"。这是"持续性"的根基。

### 3.2 进程化部署

加一个 entrypoint `python -m recruit_agent.runtime.heartbeat`，独立进程跑。
API 进程只管收任务入队，心跳进程只管出队执行。

## 阶段 4：自学习闭环（2 周）

### 4.1 把 EvolutionArtifact 的写入路径搬进 `persist_learning`

每个 turn 结束，LLM 可以通过工具 `record_learning` 写入"我学到的东西"——
分三类：


| 类型               | 写到哪                                 | 触发场景                |
| ---------------- | ----------------------------------- | ------------------- |
| `candidate_fact` | `CandidateMemory.facts`             | 学到该候选人的一个新事实        |
| `job_pattern`    | `JobMemory.historical_patterns`     | 学到该 JD 的筛选规律        |
| `global_lesson`  | `AgentGlobalMemory.runtime_lessons` | 学到一条跨候选人/跨 JD 的通用经验 |


### 4.2 GlobalMemory 索引化（参考 MEMORY.md）

每条 GlobalMemory 写入时强制要求一个 `description`（≤ 100 字），
`assemble()` 阶段只把 `description` 列表注入书签 2，详情靠 LLM 调
`read_memory(id)` 工具按需取。

这样 GlobalMemory 长到 500 条也不会撑爆 system prompt。

### 4.3 升级 Skill 的"自动通道"

LLM 在 `record_learning` 时可以标记 `promote_to_skill: true`，
触发后台 job 把 lesson 包装成 SkillDraft 进 `EvolutionArtifact` 等待人工审核。

---

# Part 5：Assistant Agent 设计规范

> 类比：Hermes / Lobster — 用户主动开个对话，agent 用工具帮你查询、操作、回答。

## 与 Autonomous Agent 的关键差异


| 维度         | Autonomous Agent  | Assistant Agent                        |
| ---------- | ----------------- | -------------------------------------- |
| Trigger 来源 | 调度器 / cron / 自唤醒  | 用户消息                                   |
| Run 边界     | 围绕一个 GoalSpec     | 围绕一个 ConversationSession               |
| 上下文持续性     | 跨 turn 用 DB 状态做记忆 | 跨 turn 用 messages[] 做记忆（像 Claude Code） |
| Outcome 处理 | 写状态、入队 follow-up  | 流式输出回用户                                |
| Sense 的频度  | 每个 autonomous turn 起点必拉 | 用户 turn 触发时拉                           |
| 多 turn 工具  | 由 LLM 决定          | 由 LLM 决定                               |


## 复用的部分

- **Agent Assembly** 完全复用：同一个 RecruitAgentProfile + GlobalMemory 索引
- **Agent Kernel** 大部分复用：`assemble / deliberate / guard / act / persist_learning`
- **Tool Registry** 完全复用：所有工具（搜索候选人、读 memory、enqueue 任务）都能用

## 不一样的部分

### 1. 短期记忆改回 messages[]

Assistant Agent 是"线性叙事"（参考主文档 Part 1），需要保留对话连续性。
新增 `ConversationSession`：

```python
@dataclass
class ConversationSession:
    id: UUID
    user_id: str
    messages: list[Message]  # 持久化到 jsonl 像 Claude Code
    started_at: datetime
    last_active_at: datetime
    summary: str | None  # 压缩后的摘要
```

### 2. 加入压缩机制

当 `messages` 累积到阈值（比如 80% 上下文窗口），触发：

```
1. 保留：system / 第一条 user / 最近 N 个 tool_result
2. 中间消息合成 summary（再调一次 LLM）
3. 把 summary 替换中间消息
4. 持久化原始 jsonl，可 --continue
```

直接抄 Claude Code 的策略（主文档 Part 1）。

### 3. 入口接口

```
POST /api/assistant/conversations          # 开新会话
POST /api/assistant/conversations/{id}/turn  # 用户发一句话
GET  /api/assistant/conversations/{id}     # 取历史
DELETE /api/assistant/conversations/{id}    # 关会话
```

`/turn` 走 SSE 流式：每个 token / tool_call / tool_result 都推给前端。

### 4. Guard Policy 更宽松

Autonomous Agent 的 Guard 偏保守（自动跑的东西要管严）；Assistant Agent
是用户在线的，可以让 LLM 做更多事，遇到高风险动作弹窗确认而不是直接拒绝。

### 5. 与 Autonomous Agent 的协作

Assistant 可以**通过工具"派活"给 Autonomous Agent**：

```
用户："给候选人 X 安排一次电话沟通"
Assistant LLM：调 enqueue_follow_up(task_type="schedule_call", candidate_id="X")
              + 回用户："我已经把这件事派给后台了，结果会推到候选人时间线"
```

反过来 Autonomous Agent 也可以**通过推送给 Assistant 留言**：

```
Autonomous Agent 评估候选人 X 后觉得需要人工判断
  → 写 ApprovalItem
  → Assistant 在用户下次开会话时主动提示"有 3 件待审"
```

## Assistant Agent 的最小接口

```python
class AssistantAgent:
    def __init__(self, kernel: AgentKernel, conversations: ConversationRepository):
        ...

    async def handle_turn(
        self,
        conversation_id: UUID,
        user_message: str,
    ) -> AsyncIterator[StreamEvent]:
        conv = self.conversations.get(conversation_id)
        conv.messages.append(Message(role="user", content=user_message))

        # 复用 Kernel 的 assemble / deliberate / guard / act
        request = self.kernel.assemble_for_assistant(conv)
        async for event in self.kernel.deliberate_streaming(request):
            yield event
            if event.kind == "tool_call":
                guarded = self.kernel.guard(event.decision, conv)
                if not guarded:
                    yield StreamEvent.confirmation_required(event)
                    continue
                effects = self.kernel.act(event.decision, conv)
                yield StreamEvent.tool_result(effects)

        self.conversations.persist(conv)
```

---

# Part 6：两个 Agent 的共用与差异

```
┌──────────────────────────────────────────────────────────────────┐
│  Agent Assembly（共用）                                            │
│   RecruitAgentProfile + GlobalMemory 索引 + Skill + Tool 注册表   │
└─────────────────┬────────────────────────┬───────────────────────┘
                  │                        │
                  ▼                        ▼
         ┌───────────────┐         ┌───────────────┐
         │ Autonomous Kernel   │         │ Assistant     │
         │               │         │ Kernel        │
         │ turn() driven │         │ turn() driven │
         └───────┬───────┘         └───────┬───────┘
                 │                         │
                 ▼                         ▼
         Trigger: 调度器              Trigger: 用户消息
         Outcome: 状态/队列            Outcome: 流式回复
         Memory:  DB 实时查           Memory:  messages[] + summary
                 │                         │
                 └──────┬──────────────────┘
                        ▼
              ┌──────────────────┐
              │  Tool Bus（共用） │
              │  执行工具调用     │
              └──────────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │  Memory Writer   │
              │  （共用）          │
              │  写 Candidate /   │
              │  Job / Global     │
              └──────────────────┘
```

## 协作场景


| 场景     | Loop 做什么               | Assistant 做什么          |
| ------ | ---------------------- | ---------------------- |
| 持续筛选   | 每 30s 心跳，找新简历、评分、写状态   | 不参与                    |
| 临时查询   | 不参与                    | 用户问"今天评了几个"，调 SQL 工具   |
| 高风险动作  | 写 ApprovalItem         | 主动提示用户"有待审"，让用户在对话里批   |
| 长期偏好学习 | turn 中自动写 GlobalMemory | turn 中也可写（"以后这种邮件别发"）  |
| 紧急介入   | sleep / wait_human     | 用户对话里调 `pause_loop` 工具 |


## 实施优先级

1. **先做 Autonomous Agent 阶段 1+2**（4 周）：剥离 Kernel + 替换 Orchestrator
  → 拿到 minimal LLM loop，验证可跑
2. **再做阶段 3**（1 周）：上心跳，让 Loop 真正"持续运行"
3. **再做 Assistant Agent**（3 周）：复用 Kernel，加会话和压缩
4. **最后做阶段 4**（2 周）：把自学习闭环跑通，让 Loop 越跑越聪明

总计约 10 周。

---

# 附录：与现有代码的具体对应


| 现有文件                                                                | 改动                                                               |
| ------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `services/agent.py:797-813` `build_follow_up_factory`               | 删除；follow-up 由 LLM tool 决定                                       |
| `services/agent.py:4523-4584` `_next_tasks_for_result`              | 删除；硬编码 stage 流转改成 prompt 提示                                      |
| `services/agent.py:857-1050` `build_runner`                         | 拆分：`begin_run / run_turn / finalize_run`                         |
| `runtime/agent_loop.py`                                             | 改名为 `runtime/deliberate.py`，作为 Kernel 的子模块                       |
| `services/context_assembler.py`                                     | 新增 `build_layered_request()`，按三书签输出                              |
| `runtime/prompts.py`                                                | 拆出 `build_persona / build_prompt_config / build_memory_index` 三段 |
| `scheduler/scheduler.py`                                            | 保留；包一层 `Heartbeat` 作为常驻进程                                        |
| `services/recruit_agent.py:477-565` `default_recruit_agent_profile` | 增加 `kernel_config` 段（`turn_limits` / `round_limits` / `cache_strategy`） |
| 新建 `runtime/kernel.py`                                              | Kernel 主体                                                        |
| 新建 `runtime/guard.py`                                               | Guard policy 评估                                                  |
| 新建 `runtime/memory_writer.py`                                       | persist_learning 实现                                              |
| 新建 `services/heartbeat.py`                                          | 常驻心跳进程                                                           |
| 新建 `services/assistant.py`                                          | Assistant Agent                                                  |
| 新建 `models/conversation.py`                                         | ConversationSession 表                                            |
