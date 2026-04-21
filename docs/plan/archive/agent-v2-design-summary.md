# Agent v2 设计摘要（给决策者看）

> Status: archived
> Supersedes: docs/plan/archive/agent架构设计.md
> Superseded by: docs/plan/completed/2026-04-19-agent-v2-direct-cutover-plan.md
> Distilled into: partial: docs/specs/2026-04-20-dual-agent-product-architecture.md
> Last reviewed against code: 2026-04-20
> Legacy path retained: docs/agent-v2-design-summary.md

> 本文档是 recruit-agent Agent 系统升级的**设计总览**。
> 目标：把当前规则驱动、实现耦合的 agent 基础设施，升级为两个真正自主、可长期运行、自进化的 agent —
> **Autonomous Agent**（自主招聘）与 **Assistant Agent**（对话助手）。
>
> 配套实施细节见 `[agent-v2-implementation-spec.md](./agent-v2-implementation-spec.md)`。
> 上下文/记忆基础见 `[agent-context-memory-design-reference.md](./agent-context-memory-design-reference.md)`。

> **术语锚定**：本项目 `turn` 采用 Codex 语义，表示一次从触发（用户消息 / 调度唤醒 / run 续跑）到下一次需要人类介入为止的完整 LLM 驱动循环。`round` 表示 turn 内部一次 `model → tool → observe` 往返，对应 Claude Agent SDK 文档里的 `turn`。本项目不使用 `tick` 一词。

---

## 0. 一句话愿景

> 一个 **Kernel**、两种 **Assembly**、多层 **Memory**、可自演化的 **Skill 体系**——
> 让 agent 能 24/7 跑招聘，也能随叫随到帮你查一条候选人信息。

---

## 1. 核心设计原则


| #   | 原则                   | 一句话解释                                                                                        |
| --- | -------------------- | -------------------------------------------------------------------------------------------- |
| 1   | **同内核、异装配**          | Autonomous 与 Assistant **共用 AgentKernel**，差异在 Trigger / Memory 策略 / Context 组装 / Guard 宽严    |
| 2   | **运行装配独立解析**         | 每个 run 都解析一份 `AutonomousAssembly` runtime contract；招聘场景当前把它实现成 `JobAssembly`，但 Kernel 不依赖这个物理形态 |
| 3   | **五原语托住主线**         | Autonomous 主线连续性由 Goal / State / Checkpoint / Log / Memory 保证，而不是靠长上下文硬记住历史 |
| 4   | **State 以事实查询为主**    | 主程序优先提供事实查询型 tools；主线 agent 每个 turn 只拿固定快照 contract 的概览，其余按需查询详情 |
| 5   | **LLM 决定下一步，runtime 只做薄约束**  | 业务推进顺序主要由 LLM 基于 Goal + State 自主决定；程序只提供预算、人审、切换公平性、回访时间上下限等薄约束 |
| 6   | **执行层显式下沉**   | 高噪音网页动作不在主线上堆 turns，由主线显式创建临时执行单元；执行单元完成动作后只回流结构化结果、必要副作用、可沉淀经验和分析日志引用 |
| 7   | **Observation 不是记忆** | 每 turn 现拉真实世界快照（DB/外部），不在 agent 进程内累积、不打缓存                                                   |
| 8   | **自进化优先于手写规则**       | LLM 通过执行单元产物和 `record_learning` 沉淀 skill / memory；先 trial，连续成功才长期可用，失效后重新升级新的执行单元 |
| 9   | **场景能力包下沉业务语义**     | Kernel 只提供插槽与通用原语；招聘等业务语义通过轻量 Scenario Capability Pack（plugin）注册，而不是写死在内核里 |


---

## 2. 总体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                             入口层                                     │
│   Heartbeat Daemon        REST/WS API        CLI / Desktop            │
│   （触发 Autonomous turn）  （用户对话/管理）  （人工干预）                │
└───────────────┬─────────────────────┬────────────────────────────────┘
                │                     │
                ▼                     ▼
┌──────────────────────────────────────────────────────────────────────┐
│                            Agent 层                                    │
│   ┌────────────────────┐     ┌────────────────────┐                   │
│   │ Autonomous Agent   │     │ Assistant Agent    │                   │
│   │ turn()             │     │ turn() (streaming) │                   │
│   └─────────┬──────────┘     └─────────┬──────────┘                   │
│             └───────────┬───────────────┘                             │
│                         ▼                                             │
│            ┌─────────────────────────────┐                            │
│            │    Agent Kernel (shared)    │                            │
│            │  Sense → Assemble →          │                            │
│            │  Deliberate → Guard →        │                            │
│            │  Act → UpdateMemory → Eval   │                            │
│            └─────────────────────────────┘                            │
└───────────────┬──────────────────────────┬───────────────────────────┘
                │                          │
                ▼                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                           能力层                                        │
│  ContextAssembler   MemoryService     ToolBus       SkillRegistry      │
│  (3 书签缓存)        (L/M/S 三层)      (统一调度)    (Skill 注册/版本)    │
│                                                                       │
│  CompactService     GuardPolicy       PluginHost    MCPBridge         │
│  (turn/session/     (risk/rate/       (生命周期      (MCP server       │
│   memory 三级压缩)    rollout 守卫)     hook)        接入/隔离)           │
│                                                                       │
│  LearningWriter     EvolutionQueue    PromotionEngine                 │
│  (学习沉淀出口)       (人审队列)         (自动晋升引擎)                    │
└───────────────┬──────────────────────────┬───────────────────────────┘
                │                          │
                ▼                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          持久化层                                       │
│  Session / Run / Turn / Round 事件流 + jsonl                           │
│  Memory 表（Global / Job / Candidate）                                 │
│  PromptLibrary / SkillLibrary / PluginRegistry / MCPRegistry           │
│  CompactionLog / LearningLog / EvolutionArtifact                       │
└───────────────┬──────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          Provider 层                                    │
│  LLM (Anthropic / OpenAI 兼容)     Embedding (可选)     MCP servers    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Autonomous Agent 设计

### 3.1 三段结构

```
Goal + Assembly  ←  进程启动后加载；Goal 是自然语言目标文档 + 少量强约束插槽，Assembly 决定 prompt/tools/memory/policy
                   ↓
Agent Kernel     ←  常驻单例；封装 turn()
                   ↓
Execution Cycle  ←  一个 Run 围绕长期 Goal 持续运行；每个 turn 重新读取 State 概览并自主选择推进哪个 scope / 场景路径
```

**五原语（在这里先给定义）**：
- `Goal`：长期任务文档 + 运行插槽
- `State`：外部世界真实状态
- `Checkpoint`：半完成动作的最小恢复提示
- `Log`：运行留痕
- `Memory`：长期/中期经验沉淀

### 3.2 Assembly（核心升级点）

Kernel 只要求一份 **AutonomousAssembly runtime contract**，不要求它必须长成某个业务表。
当前招聘场景把它实现成 `JobAssembly`，但那只是第一个场景包的物理落地。

```text
AutonomousAssembly (runtime contract)
├── prompt_overlay
├── scenario_policy
├── tool_allowlist
├── guard_policy_override
├── context_policy
└── kernel_tuning
```

**Assembly 过程**：turn 开始时，Kernel 根据当前 run / scope 解析一份 AutonomousAssembly，
与 base profile 合并，得到"本 turn 实际使用的"prompt / tools / memory / policy。

招聘场景里的 `JobAssembly` 只是该 runtime contract 的一个实现：它额外携带 JD 评分标准、JobMemory 绑定等招聘特有字段，这些都不属于 Kernel 原语。

### 3.3 Turn Cycle（8 节点）

```
     Trigger
        │  cron / queue / self-wakeup / event
        ▼
     Sense          ← 拉 Observation（固定快照概览 + 场景包 enrichers）
        │
        ▼
     Assemble       ← 书签 1：Persona + Tools + persona fragments
        │              书签 2：assembly.prompt_overlay + GlobalMemory 索引 + scenario fragments
        │              书签 3：scope-local memory / recent events（可选）
        │              user：Observation 序列化
        ▼
     Deliberate     ← LLM ←→ Tool 反复（这一层才叫 "agent loop"）
        │              含 Tool Call / Observe / Reflect / Conclude 子阶段
        │              tool_call 前先做 Guard preflight
        │              受 `max_tool_roundtrips` / `RoundLimits.token_budget` 约束
        ├────────────► Guard(preflight) ─► tool execute ─► tool_result ─┐
        │                                                                │
        └──────────────────────────── final_content / stop_reason ────────┘
                                         │
                                         ▼
                                     Guard(final)
                                         │
                                         ▼
     Act            ← 持久化副作用（DB 写入 / follow-up 入队 / 自唤醒调度）
        │
        ▼
     UpdateMemory   ← record_learning 落地：candidate_fact / job_pattern /
        │              global_lesson / skill_draft / prompt_lesson
        ▼
     Evaluate       ← continue / sleep / wait_human / complete / escalate
                      （若 wait_human，则当前 turn 结束，确认后只能由新的 turn / recovery turn 恢复）
```

### 3.4 Self-continuation（持续性来源）

Agent 的"持续运行"**不靠 cron 定死**，靠这两条机制：

1. **Heartbeat daemon** 每 `interval` 秒跑一次：有外部任务就取任务做，没任务就跑"自检 turn"（固定快照 contract + Goal，让 LLM 判断是否有值得推进的业务动作）
2. **LLM 在 turn 末尾**可以调 `schedule_self_wakeup(delay_seconds, reason)` 指定下次自己什么时候再醒 —— LLM 给建议，程序施加上下限和最终调度约束

### 3.5 主线层 vs 执行层

```text
主线层（Autonomous Agent）
  Goal + State + Memory + Recent Log
  -> 决定下一步推进哪个 scope / 场景路径
  -> 必要时显式创建临时执行单元

执行层（临时执行单元）
  browser MCP / 页面解析 / 解阻 / skill 内多轮 turns
  -> 自己消化高噪音上下文
  -> 完成一个网页业务动作
  -> 分开回流：业务结果 / 必要副作用 / learnable artifacts / 分析日志引用
```

原则：
- 主线 agent 每个 turn 都重新从 `Goal + State + Memory + Recent Log` 现算，不维护显式 agenda
- 细粒度业务对象默认不进固定快照，只通过事实查询型 tools 或场景包 enrichers 按需暴露
- 高噪音网页动作默认下沉到显式执行单元，而不是让主线连续背 browser turns
- 执行单元不追求现场续命；失效时重新升级新的执行单元，而不是恢复旧现场

### 3.6 人工干预与接管粒度

> **分层提示**：Kernel 只提供插槽与通用原语；下面的 recruit 内容是第一个 Scenario Capability Pack 的实现示例。

这层现在明确拆成两部分：
- **Kernel** 只提供通用原语与插槽
- **招聘场景包（Scenario Capability Pack）** 提供候选人接管、handover、外部触达约束等具体实现

```text
Kernel 通用原语
  全局 Autonomous 暂停（agent_global_state.autonomous_paused）
    -> Heartbeat 起 turn 前读一次，paused 时 skip
  Persona fragment 插槽
  Observation enricher 插槽
  Guard check 插槽
  Tool / Router 注册插槽
  turn 内单点审批（approval_items）

recruit 场景包（通过 PluginHost 注册）
  per-候选人接管锁（candidate_autonomous_locks）
    -> Observation enricher 暴露 human_locked / recent_handover
    -> LLM 自己判断是否跳过 / 续接
    -> Guard check 兜底拒绝任何指向被锁候选人的工具
  external action 约束
    -> 若 Assistant 想临时做外部动作，由 recruit guard check 决定是否必须先 pause Autonomous
  handover prompt fragment
    -> 告诉 LLM 如何理解 recent_handover，而不是在 Kernel 节点里写死逻辑
```

边界提示：
- `handover_note` ≠ `Checkpoint`：Checkpoint 是 Autonomous 自己中断写的恢复提示；handover_note 是人接管完归还时的事件性说明。两者由不同主体在不同时机写，不可互换、不互相覆盖。
- 系统层不做"过滤逻辑"，只做"暴露 + 安全网"：State 暴露给 LLM 判断，Guard preflight 拒绝越界。
- 未来若新增分析类工具，也应做成新的场景包，挂在自己的 namespace 下，而不是改 Kernel。

---

## 4. Assistant Agent 设计

> Assistant 不是“无装配”的特例，而是通过 `AssistantAssembly` 装配出来的第二种 agent。 
> 区别在于：它按用户/工作空间/会话策略装配，而不是按 autonomous run 的 scope 装配。

### 4.1 与 Autonomous 的共用与差异

```
┌────────────────────────────────────────────┐
│  共用：AgentKernel + ToolBus + MemoryService │
│        + GuardPolicy + LearningWriter + MCP │
│        + PluginHost（场景能力包挂载点）       │
└────────────────────────────────────────────┘
           │                       │
           ▼                       ▼
  Autonomous                 Assistant
  ─────────                  ─────────
  Trigger = Heartbeat        Trigger = 用户消息
  Context = DB 拉 Observation  /  Context = conversation history + recent tool results
  Memory 回写 = 每 turn       Memory 回写 = 每 turn
  Output = 状态/队列/通知       Output = SSE 流式回用户
  Guard 结构 = preflight + 节点级   Guard 结构 = 仅 preflight，由用户实时把关
  场景能力 = 可加载对应 pack        场景能力 = 可加载对应 pack
  中途取消 = 不可（turn 原子）  中途取消 = 可（CancellationToken，仿 Claude Code ESC）
  max_rounds_per_turn = 8    max_rounds_per_turn = 8（可按 Assembly 覆盖）
  Compact = session 级         Compact = 对话级（仿 Claude Code）
```

### 4.2 会话生命周期

```
POST /assistant/conversations              ← 开会话
   ↓
ConversationSession created (id, user_id, messages=[], jsonl 路径)
   ↓
POST /assistant/conversations/{id}/turn    ← 用户发消息 (SSE)
   ├── append user msg → messages
   ├── Kernel.assemble(conv) → LLMRequest
   ├── Kernel.deliberate_streaming(request)
   │     ├── LLM → tool_call → Guard preflight → tool execute → tool_result → LLM ...
   │     └── stream every event back
   ├── append assistant final → messages
   ├── Kernel.persist_learning(turn)
   └── compact_if_needed(messages)
   ↓
DELETE or GET /assistant/conversations/{id}  ← 关闭/查询
```

### 4.3 协作

- Assistant 可以 **派活给 Autonomous**：调 `enqueue_follow_up` 工具，Autonomous 下一 turn 看到并处理
- Autonomous 可以 **留言给 Assistant**：写 `approval_items` / `NotificationDraft`，Assistant 在下一次会话开头主动提示
- `NotificationDraft` 在实现上复用 `operator_interactions`：`interaction_type='notification_draft'`，用于承接待展示通知，而不是再建一张独立消息表

### 4.4 Assistant Turn 取消（仿 Claude Code）

- 每个 turn 持有一个 `CancellationToken`；用户可在执行中途任意取消
- 触发源：`POST /assistant/conversations/{id}/cancel` 或客户端关闭 SSE 连接
- Kernel 在三处检查 token：LLM stream chunk 之间、tool_call 派发前、tool 执行中
- 取消后：当前 turn 结束 → 推 `turn_cancelled` 事件 → jsonl 落档 → 不回滚已写副作用、不再派发后续 tool
- 用户后续发新消息正常开 turn，被取消 turn 的 partial outputs 留在历史中，由 LLM 自行判断是否复用

对照 Autonomous：turn 是原子单位，**不暴露中途取消接口**。要停 Autonomous 的方式只有 §3.6 三层（全局 pause / 场景包 takeover 机制 / Guard reject），不通过"杀 turn"实现。


---

## 5. 记忆架构

### 5.1 三层记忆边界

在三层记忆之上，Autonomous 主线还有 5 个持久化原语：
- `Goal`：长期任务文档 + 强约束运行插槽
- `State`：外部世界事实（主要来自业务表和事实查询 tool）
- `Checkpoint`：只在阻塞/人审/预算打断时写的最小恢复提示
- `Log`：运行留痕，用于分析/回放/同类阻塞按需检索
- `Memory`：长期/中期经验沉淀

```text
主线连续性 = Goal + State + Checkpoint + Log + Memory

其中：
- Goal 决定长期任务边界
- State 决定当前真实世界状态
- Checkpoint 决定新的 turn 如何接回半完成动作
- Log 决定事后分析与同类阻塞检索
- Memory 决定长期复用知识
```

```text
长期 Long-term
  GlobalMemory / JobMemory / CandidateMemory / SkillLibrary / PromptLibrary
  -> 跨 run 复用的经验与事实

中期 Medium-term
  SessionSummary / RunContext / RecentEventLog
  -> 当前 run 内跨 turn 的轻量摘要与最近事件

短期 Short-term
  messages[] / tool_outputs
  -> 只在本 turn 或执行单元内存在的临时上下文
```

关键边界：
- 主线不靠长 messages 记住“刚才做到哪”，而靠 Goal/State/Checkpoint 接回
- browser MCP / 页面试错 / selector 噪音只留在执行层短期上下文或分析日志中，不直接进入主线记忆
- learnable artifacts 先进入 trial/分析留档，再由主 agent 判断是否升级为长期 skill / memory

### 5.2 Compact 机制（三级）


| 级别                | 触发                          | 动作                                                      | 产物                              |
| ----------------- | --------------------------- | ------------------------------------------------------- | ------------------------------- |
| **Turn-level**    | messages tokens > 80% 上下文   | LLM 摘要中间部分，保留 system/首 user/末 3 tool_result             | 新的 messages + `CompactionEvent` |
| **Session-level** | autonomous / assistant 会话结束或长时无活动 | 提炼成 session_summary，写入对应 session 的 context_summary | DB 行更新 + jsonl 追加               |
| **Memory-level**  | Memory.items > N / 每周 cron  | 合并相似事实、清理过期条目、输出 consolidated 版本                        | Memory 版本 bump，旧版本归档            |


每次 compact 生成 `CompactionEvent`（可回放、可审计）。

### 5.3 记忆检索

**默认模式：索引 + LLM 判断**

```
Assemble 阶段：
  注入 system 书签 2 的是"索引列表"：
    - [scoring_preference](jobmem_001) — Android 岗偏好 3+ 年 Kotlin
    - [blacklist_signal](jobmem_002)   — 简历提到"求稳"→ 大概率不匹配
    - [outreach_tone](jobmem_003)      — 该 JD 对直接外联反感
    ...
  LLM 看到索引 → 判断是否需要详情
    ├── 不需要：直接决策（零额外成本）
    └── 需要：调工具 read_memory(id) 拿详情
```

**备选模式：embedding 检索**

仅在这些场景启用：

- 简历全文语义搜索（CandidatePool 几千份简历）
- 历史沟通记录召回（按语义找"以前有没有人问过类似问题"）

默认关闭。每个 AutonomousAssembly runtime contract 都可声明 `enable_embedding: true` 并指定 embedding provider；招聘场景当前由 JobAssembly 承载该配置。

---

## 6. 工具生态（Tools / Skills / Plugins / MCP）

### 6.1 四类扩展点的定位

原则：
- 主程序优先提供**事实查询型 tools**，返回真实业务事实，而不是替 LLM 预先下业务结论
- 业务语义判断由 LLM 基于 Goal + State + Memory 自己完成
- 高噪音网页动作不直接在主线堆 turns，而是通过显式执行单元调用 skill / MCP / tool 去完成


| 扩展类型       | 谁提供         | 注册方式                      | 执行位置                         | 典型例子                                   |
| ---------- | ----------- | ------------------------- | ---------------------------- | -------------------------------------- |
| **Tool**   | 内置代码        | ToolRegistry (代码)         | 本地进程                         | `read_fact` / `enqueue_follow_up` |
| **Skill**  | LLM 学习或人工定义 | SkillLibrary (DB)         | 调 skill 实际上是调 LLM subroutine | `skill.analyze_document`   |
| **Plugin** | 第三方或内部包     | PluginRegistry (manifest) | 本地进程（沙箱）                     | 某个 boss 站点的适配器                         |
| **MCP**    | 远程 MCP 服务   | MCPRegistry (URL+auth)    | 远程进程                         | 邮件 / 日历 / IM MCP server                |


### 6.2 PluginHost 扩展面

当前实现里，PluginHost 直接暴露的是注册面，而不是旧设计里的那套生命周期 hook：

```
register_tools                → 注册场景包提供的工具
register_observation_enricher → 扩展 Observation
register_guard_check          → 追加 Guard 裁决
register_persona_fragment     → 注入 persona 片段
register_router               → 暴露场景专属 API router
```

### 6.3 可用性控制

```
base level：       AgentProfile.capability_profile（唯一权威能力配置，当前招聘实现落在 RecruitAgentProfile）
AutonomousAssembly / AssistantAssembly 覆盖：   可添加 / 禁用 / 缩小范围
runtime health：    circuit breaker / auth / rate limit 先过滤
GuardPolicy：       最终再做一次白名单/黑名单校验
```

规则：**deny 优先于 allow**。assembly 不能绕过 profile base 的显式禁用项。


### 6.4 MCP 健壮性

- `MCPRegistry` 管 URL + auth + capabilities
- 每个 MCP server 有 circuit breaker（失败率 > 50%/1min 自动熔断 5 分钟）
- `mcp_health` cron 每分钟 ping
- turn 开始时加载"健康的 MCP"列表，熔断的 MCP 自动从本 turn tools 里剔除

---

## 7. Runtime 健壮性

### 7.1 Safeguards 清单


| 机制                         | 触发条件                                  | 动作 |
| -------------------------- | ------------------------------------- | --- |
| `max_rounds_per_turn`      | 单个 turn 内 round 超过 N 次                | Driver 停止追加 round，结束当前 turn |
| `turn_timeout_seconds`     | 单个 turn 墙钟超时                          | Driver 停止当前 turn，返回预算耗尽信号 |
| `TurnLimits.token_budget`  | 单个 turn 的 token 使用超过预算               | Driver 结束当前 turn |
| `RoundLimits.token_budget` | 单个 round 的 token 使用超过预算              | Kernel 结束当前 round |
| `max_tool_roundtrips`      | 单个 round 内 tool 往返超过 N 次             | Kernel 返回 `RoundOutcome`，交由 Driver 决定是否继续 |
| `tool_timeout_seconds`     | 工具调用超时                                | 当前 round 记失败并交由 Driver 裁决 |
| `tool_circuit_breaker`     | 某工具失败率 > 50% / 1min                  | 熔断 5 分钟；期间 Assemble 剔除该工具 |
| `rate_limit`               | 某工具每分钟超上限                            | sleep 到下一窗口 / 降级 |
| `stale_run_recovery`       | Run 处于 `running` 超过 `stale_after`    | scheduler 自动释放，重入队 |
| `poison_queue`             | 同一 `task_id` 失败超过 `max_attempts`     | 写 DeadLetter，通知人工 |


### 7.2 状态机

```
AgentRun:  queued → running → waiting_human → running → completed
                          ↘ failed
                          ↘ escalate
                          ↘ cancelled
CandidateSession: active → idle → closed
                        ↘ suspended
ConversationSession: active → idle → closed
```

### 7.3 可观测性

- `AgentRuntimeEvent` 流（结构化事件，作为 RecentEventLog / replay / SSE 的统一真相源）
- `LLMCallLog`（每次 LLM 调用的 request/response 摘要 + cache_hit）
- `ToolInvocationLog`（每次工具调用）
- `CompactionEvent`（压缩前后 token 数、摘要质量评估）
- `LearningLog`（每条自学习沉淀）
- 前端 `/runtime/debug/{run_id}` 可视化回放

---

## 8. 自主学习与自我进化

### 8.1 Learning pipeline

```
┌─────────────────────────────────────────────────────────────┐
│  UpdateMemory 节点（Turn 内第 7 步）                          │
│  ─────────────────────────────────────────────────           │
│  LLM 调用工具 record_learning(kind, content, promote=bool)    │
│                                                              │
│  kind ∈ {                                                    │
│    candidate_fact    → CandidateMemory.facts                 │
│    job_pattern       → JobMemory.historical_patterns         │
│    global_lesson     → GlobalMemory.runtime_lessons          │
│    prompt_lesson     → PromptEvolution draft                 │
│    skill_draft       → SkillDraft                            │
│    tool_feedback     → tool_metrics.reliability_score（影响 reliability） │
│  }                                                           │
└─────────────┬──────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│  PromotionEngine（异步）                                      │
│  ─────────────────────────────                               │
│  自动晋升规则：                                                │
│    · 相同 pattern 出现 ≥ N 次                                  │
│    · confidence ≥ threshold                                  │
│    · 人工标记 trust=confirmed                                  │
│    · 新 lesson 与已有 lesson 无冲突                             │
│  满足 → 直接生效                                                │
│  不满足 → EvolutionQueue 等人审                                │
└─────────────┬──────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│  EvolutionQueue（人审界面）                                    │
│  每条待审 artifact 显示：                                       │
│    · 原始 record_learning 内容                                 │
│    · 产生场景（哪个 run / candidate / JD）                      │
│    · 建议落地位置（哪个 Memory / Skill / Prompt）                │
│  人审：approve / reject / edit                                 │
└─────────────┬──────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│  生效：下一 turn 起，新 Memory / Skill / Prompt 被 Assembly 使用 │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 Prompt 的演化

Prompt（包括评分标准）是**可版本化的**：

- `PromptOverlay(jd_id, version, content, activated_at)` 一行一版
- 新 prompt 先以 **trial mode** 跑 N 个候选人，对比旧版本指标
- 超过 baseline → 自动晋升为 active；否则打回人审

### 8.3 Skill 的 gates

Skill 从 draft 到 active 有三道闸：

1. **语法 gate**：LLM 调 skill 时 schema 要对得上
2. **trial gate**：先在 sandbox 跑 N 次，成功率 > 阈值才候选
3. **human gate**：`requires_human_gate=true` 的敏感 skill 强制人审

---

## 9. 里程碑与验收标准

### 9.1 Milestones（不考虑升级成本，按"最终形态 → 中间态 → 过渡态"倒推）

```
M1（2-3 周）：Agent Kernel 骨架跑通
  目标：剥离 Kernel、三书签 Assemble、LLM 驱动 follow-up
  验收：一个最简 turn 能跑到 Evaluate，cache_hit 率可观测

M2（2 周）：JobAssembly + 三层 Memory 完整
  目标：每 JD 独立 prompt / 评分标准 / JobMemory
  验收：同一候选人在 JD-A 和 JD-B 下得到不同决策，Memory 隔离无泄露

M3（2 周）：Compact + 记忆检索完整
  目标：turn/session/memory 三级 compact；索引 + LLM 判断落地
  验收：压缩前后决策一致性测试；长记忆 500 条仍能秒查

M4（1 周）：Heartbeat + Self-wakeup
  目标：Autonomous 真正"持续运行"
  验收：空队列下 Agent 主动自检、自派活、自停

M5（2 周）：Assistant Agent 上线
  目标：SSE 会话、压缩、与 Autonomous 协作
  验收：用户可对话、派活、接到 Autonomous 通知

M6（2 周）：自进化闭环 + Runtime guardrails
  目标：LearningWriter + PromotionEngine + EvolutionQueue；全部 Runtime 安全项启用
  验收：从一个新 lesson 诞生到生效的全链路可追溯

M7（1 周）：MCP / Plugin / Skill 完整生态
  目标：三种扩展的注册、健康检查、沙箱
  验收：接入一个外部 MCP + 一个内部 Plugin + 一个 LLM 学到的 Skill，互不干扰

M8（持续）：可观测性 + SRE
  目标：完整可视化、告警、回放
  验收：任一 run 可在 UI 完整回放、任一异常有告警
```

### 9.2 总体验收标准


| 维度     | 指标                                   | 目标值     |
| ------ | ------------------------------------ | ------- |
| 自主性    | 空队列下 Autonomous 的自启动 turn 比例         | ≥ 30%   |
| 隔离性    | 跨 JD / 跨候选人记忆泄露案例                    | 0       |
| 健壮性    | 单次工具失败不导致 Run 崩溃                     | 100%    |
| 缓存率    | system 前缀 cache hit 率                | ≥ 70%   |
| 进化速度   | 从 record_learning 到生效（非紧急项）中位数       | ≤ 24 小时 |
| 可观测性   | Run 出错后 5 分钟内前端可定位到具体 Turn/Round/Tool | 100%    |
| 会话连续性  | Assistant `--continue` 能完整恢复         | 100%    |
| 记忆压缩质量 | 压缩前后在固定问题集上的答案一致率                    | ≥ 90%   |


---

## 10. 与现状的结合改造方向


| 现状                                                | 去向                                                  |
| ------------------------------------------------- | --------------------------------------------------- |
| `services/agent.py` 巨型类                           | 拆成 Kernel + ContextAssembler + LearningWriter 等独立服务 |
| `_next_tasks_for_result` 硬编码状态机                   | 由 LLM 工具 `enqueue_follow_up` 决定                     |
| `ContextAssemblerService.build()` 扁平拼装            | 改为 `build_layered_request()` 输出三书签结构                |
| `AgentLoop.run()` 内的 `execution_contract`         | 业务概念，从 Kernel 剥离，变成 Assemble 阶段的 JobAssembly input  |
| `AgentRun` 表                                      | 保留并扩展字段（`turns_count`、token usage、cache 指标、run_context 等） |
| `CandidateMemory / JobMemory / AgentGlobalMemory` | 保留，schema 扩展（索引描述字段必填）                              |
| `EvolutionArtifact`                               | 保留，改造为 EvolutionQueue 的底层存储                         |
| `SqlAlchemyQueue`                                 | 保留；外面包 Heartbeat daemon                             |
| `SerialScheduler`                                 | 保留；Heartbeat 调用它                                    |
| `RecruitAgentProfile.prompt_config`               | 保留 base；新增 `JobAssembly` 表存 overlay                 |


**方针**：优先扩现有表；只有真正不存在同类存储时才新增新表。对 `agent_runs` / `approval_items` / `agent_runtime_events` / memory 表，不再引入平行替代物。

---

## 11. 架构图：完整执行时序

Autonomous Agent 典型的一次"评估候选人"turn：

```
时间 →
 0ms      Heartbeat wake-up, pull task: "evaluate candidate X for JD Y"
 5ms      RunContext 建立；锁定 candidate X + JD Y；加载 JobAssembly[Y]
 10ms     Sense: SQL 查候选人池、近期事件、待审队列 → Observation
 20ms     Assemble: 三书签打包 system + Observation 放 user
 25ms     LLM call (book1+book2+book3 命中) → tool_call: read_memory(candidate_X)
 300ms    read_memory 返回 → 再发一轮 LLM
 800ms    LLM 决定: score + record_learning(candidate_fact) + next_action
 850ms    Guard check：评分在阈值内 → 放行
 870ms    Act: write CandidateProgress, enqueue follow-up "send_outreach"
 900ms    UpdateMemory: write CandidateMemory.facts, log LearningEvent
 920ms    Evaluate: status=continue (run 还有下一步); schedule_self_wakeup(60s)
 930ms    RoundOutcome 持久化，Heartbeat 返回
```

一次 turn 通常 < 2 秒，tokens ≈ 3-8K（system 大部分命中缓存）。

---

## 12. 总结

**不变的**：仍是招聘场景本地 agent，仍用 SQLite，仍以 Anthropic / OpenAI 兼容为主。

**变的**：

1. 从"规则驱动 + LLM 工具"升级为"**LLM 驱动 + 规则兜底**"
2. 从"单一 profile"升级为"**base + runtime assembly contract**"（招聘场景当前由 JobAssembly 承载）
3. 从"一种记忆写法"升级为"**三层记忆 + 索引检索 + 三级压缩**"
4. 从"一次性跑任务"升级为"**持续运行 + 自唤醒 + 自学习**"
5. 从"工具一把塞进去"升级为"**Tool/Skill/Plugin/MCP 分层管理**"
6. 从"agent 是代码里的函数"升级为"**agent 是带身份、带记忆、带能力边界的运行实体**"

配套的落地细节见 `[agent-v2-implementation-spec.md](./agent-v2-implementation-spec.md)`。
