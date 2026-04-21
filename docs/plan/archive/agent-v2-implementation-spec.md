# Agent v2 Implementation Spec（给 Codex 做落地）

> Status: archived
> Supersedes: docs/plan/archive/autonomous-agent-improvement-plan.md
> Superseded by: docs/plan/completed/2026-04-19-agent-v2-direct-cutover-plan.md
> Distilled into: partial: docs/specs/2026-04-20-autonomous-agent-runtime-constraints.md
> Last reviewed against code: 2026-04-20
> Legacy path retained: docs/agent-v2-implementation-spec.md

> 本文档是 recruit-agent agent 系统重构的**可执行实施规格**，配合
> `[agent-v2-design-summary.md](./agent-v2-design-summary.md)` 使用。
>
> 预期读者：Codex（或任何编码 agent）。格式是可读可照做的规格，不是叙事文档。
>
> 读取顺序：Part 1（背景与边界）→ Part 2（模块清单与文件映射）→ Part 3（数据模型）
> → Part 4（核心接口）→ Part 5（8 节点契约）→ Part 6-9（关键子系统）
> → Part 10（API）→ Part 11（迁移策略）→ Part 12（分阶段实施 & 验收）
> → Part 13（测试要求）。

> **术语锚定**：本项目 `turn` 采用 Codex 语义，表示一次从触发（用户消息 / 调度唤醒 / run 续跑）到下一次需要人类介入为止的完整 LLM 驱动循环。`round` 表示 turn 内部一次 `model → tool → observe` 往返，对应 Claude Agent SDK 文档里的 `turn`。本项目不使用 `tick` 一词。

---

## 目录

1. [背景与边界](#1-背景与边界)
2. [模块清单与文件映射](#2-模块清单与文件映射)
3. [数据模型（DDL）](#3-数据模型ddl)
4. [核心接口（Python 契约）](#4-核心接口python-契约)
5. [Round Cycle 8 节点契约](#5-turn-cycle-8-节点契约)
6. [Memory 子系统](#6-memory-子系统)
7. [Compact 子系统](#7-compact-子系统)
8. [扩展生态（Tools / Skills / Plugins / MCP）](#8-扩展生态tools--skills--plugins--mcp)
9. [运行时安全（Guard / Limits / Circuit Breaker）](#9-运行时安全guard--limits--circuit-breaker)
10. [HTTP / WS API](#10-http--ws-api)
11. [与现状代码的迁移](#11-与现状代码的迁移)
12. [分阶段实施 & 验收](#12-分阶段实施--验收)
13. [测试要求](#13-测试要求)

---

## 1. 背景与边界

### 1.1 目标

- 打造两个共享 Kernel 的 agent：**AutonomousAgent**（Driver 持有 `turn` 循环）、**AssistantAgent**（Driver 持有 `turn` 循环）
- Autonomous 主线采用 **能力驱动 + 薄 runtime 约束**：业务推进顺序由 LLM 基于 Goal + State 自主决定，程序只提供预算、人审、公平切换、回访时间等边界
- JD 级独立装配（prompt / memory / 评分 / 工具 / policy）
- 三层记忆 + 三级压缩 + 索引+LLM 检索
- 自主学习与自我进化闭环
- Tool / Skill / Plugin / MCP 完整生态
- 运行时可观测、可恢复、可熔断

### 1.2 非目标（本次不做）

- 多 agent 并发调度（目前 `SerialScheduler` 已满足，不引入 Celery/Dramatiq）
- 移除 SQLite（仍是本地优先）
- 模型微调 / LoRA（所有演化都是 prompt/memory/skill 级）
- 向量数据库基础设施（embedding 可选启用，底层用 sqlite-vss 即可）

### 1.3 全局约束

- 后端 Python `>=3.14`
- DB 主键：auto-increment `id BIGINT`；业务主键另设 `UUID / business_id`（见 memory 规则）
- 时间戳：全部存 `BIGINT`（Unix 秒）；对外 JSON 输出也用秒级 int
- 外部 JSON 字段（tags / metadata 等）存 `JSON` 列；不用 BLOB
- 不把招聘主线 hardcode 成固定状态机 / 大量 agenda/work item；主线连续性由 `Goal / State / Checkpoint / Log / Memory` 五原语保证
- 主程序 tool 以**事实查询型**为主；业务语义判断交给 LLM，自主网页执行下沉到显式临时执行单元

---

## 2. 模块清单与文件映射

### 2.1 新增目录

```
services/backend/src/recruit_agent/
├── agents/                            ← NEW, agent-level 装配与 agent 实现
│   ├── __init__.py
│   ├── autonomous.py                  AutonomousAgent
│   ├── assistant.py                   AssistantAgent
│   ├── assembly.py                    AgentAssembly / JobAssembly 合并逻辑
│   └── heartbeat.py                   Heartbeat daemon 主循环
├── kernel/                            ← NEW, 内核与 8 节点
│   ├── __init__.py
│   ├── kernel.py                      AgentKernel 主体
│   ├── sense.py                       Sense 实现
│   ├── assemble.py                    Assemble 实现（三书签）
│   ├── deliberate.py                  Deliberate（原 agent_loop）
│   ├── guard.py                       GuardPolicy 评估
│   ├── act.py                         Act 执行器
│   ├── update_memory.py               LearningWriter 入口
│   └── evaluate.py                    Evaluate -> RoundOutcome
├── memory/                            ← NEW, 记忆子系统
│   ├── __init__.py
│   ├── service.py                     MemoryService（L/M/S 统一门面）
│   ├── long_term.py                   GlobalMemory/JobMemory/CandidateMemory 读写
│   ├── medium_term.py                 SessionSummary / RunContext / RecentEventLog
│   ├── short_term.py                  短期 messages 构造（无持久化，仅工具）
│   ├── index.py                       MEMORY.md 风格索引构造
│   ├── retrieve.py                    index+LLM 检索；embedding 检索
│   └── compact/                       压缩
│       ├── __init__.py
│       ├── turn.py                    Turn-level compact
│       ├── session.py                 Session-level compact
│       └── memory.py                  Memory-level consolidation
├── runtime/                        ← NEW, 运行时基础设施（与 existing runtime/ 并存）
│   ├── __init__.py
│   ├── models.py                      AgentRun / AgentTurnRecord / RoundOutcome 等
│   ├── limits.py                      RoundLimits / TurnLimits 定义
│   ├── circuit_breaker.py             熔断器
│   ├── retry.py                       工具重试策略
│   └── events.py                      事件结构
├── evolution/                         ← NEW, 学习与进化
│   ├── __init__.py
│   ├── learning_writer.py             record_learning 入口
│   ├── promotion.py                   PromotionEngine
│   ├── queue.py                       EvolutionQueue
│   └── prompt_evolution.py            Prompt 版本管理与 A/B
├── skills/                            ← NEW, Skill 注册/执行
│   ├── __init__.py
│   ├── registry.py                    SkillRegistry
│   ├── executor.py                    Skill 执行器（实质是二级 LLM 调用）
│   └── sandbox.py                     Trial 沙箱
├── plugins/                           ← NEW, Plugin 生命周期
│   ├── __init__.py
│   ├── host.py                        PluginHost + 6 个 hook
│   ├── manifest.py                    PluginManifest
│   └── loader.py                      动态加载与隔离
├── mcp/                            ← NEW, MCP 接入（与 existing mcp/ 互补）
│   ├── __init__.py
│   ├── registry.py                    MCPRegistry
│   ├── bridge.py                      把 MCP tools 注入 ToolBus
│   └── health.py                      健康检查 cron
├── tools/                          ← NEW, 新内置工具（在 existing tools/ 基础上扩）
│   ├── __init__.py
│   ├── enqueue_follow_up.py
│   ├── schedule_self_wakeup.py
│   ├── read_memory.py
│   ├── record_learning.py
│   └── invoke_skill.py
├── execution_units/                   ← NEW, 高噪音网页动作的显式执行单元
│   ├── __init__.py
│   ├── models.py                      ExecutionUnitRequest / Handle / Result
│   ├── runner.py                      ExecutionUnitRunner
│   ├── store.py                       unit 状态与日志引用
│   └── browser_worker.py              browser MCP / 页面解析 / 解阻单元
└── assistant/                         ← NEW, Assistant Agent 专属（会话等）
    ├── __init__.py
    ├── conversation.py                ConversationSession CRUD
    ├── stream.py                      SSE streaming 助手
    └── session_store.py               jsonl 持久化
```

### 2.2 改动目录

```
services/agent.py                      → 拆空，仅保留迁移期 shim（指向新实现）
services/context_assembler.py          → 新增 build_layered_request()；保留 build() 作为兼容
runtime/agent_loop.py                  → 继续存在，被 kernel/deliberate.py 封装调用
runtime/prompts.py                     → 拆 Persona/Profile/Memory 三段构造函数
scheduler/*                            → 保持；新增 heartbeat.py 包装
api/routers/*                          → 新增 assistant.py；扩 recruit_agent.py
```

### 2.3 新增独立进程

```
bin/heartbeat_daemon.py                → python -m recruit_agent.agents.heartbeat
bin/evolution_worker.py                → 异步 promotion/compact worker
bin/mcp_health.py                      → MCP 健康检查 cron
```

---

## 3. 数据模型（DDL）

> 本次实现**不采用并行 `v2_`* 表，也不讨论迁移 / 双写 / backfill**。
> 规则只有两条：
>
> 1. **已有相近表就直接扩旧表**；
> 2. **只有真正全新的概念才新增新表**。
>
> 因此本节全部使用**最终表名 / 现有表名**。若后续实现发现字段不足，优先继续扩现有表，而不是再造平行表。

### 3.1 Agent & Assembly

> **Layer: Kernel contract + current recruit implementation mapping**

> Kernel 只要求两类装配入口：
>
> - `AutonomousAssembly`：Autonomous Agent 在一个 run / scope 上运行时使用的装配
> - `AssistantAssembly`：Assistant Agent 在一个 conversation / workspace / user scope 上运行时使用的装配
>
> 两者共享同一个 Kernel，但 context、policy、tool merge、memory 读取范围不同。
>
> **重要**：`AutonomousAssembly` 是 Kernel 抽象名，不等于某个具体场景的数据表名。招聘场景当前把它实现为 `job_assemblies`；未来其他场景可以用别的表或别的装配来源，只要能解析成同一份 runtime contract。

```sql
-- base profile 已存在 recruit_agent_profiles，此处不重复
-- 当前招聘场景把 AutonomousAssembly 物理实现为 job_assemblies；这是场景实现，不是 Kernel 命名约束
CREATE TABLE job_assemblies (
  id                BIGINT PRIMARY KEY AUTOINCREMENT,
  job_description_id TEXT NOT NULL,                -- business ID
  agent_profile_id  TEXT NOT NULL,                 -- RecruitAgentProfile.business_id
  version           INT NOT NULL DEFAULT 1,
  status            TEXT NOT NULL DEFAULT 'active', -- active / archived / trial
  prompt_overlay    JSON NOT NULL,                 -- overrides on base prompt
  scoring_rubric    JSON NOT NULL,                 -- 结构化评分标准
  tool_allowlist    JSON NOT NULL,                 -- {"tools": [...], "skills": [...]}
  guard_override    JSON NOT NULL,                 -- policy overrides
  context_policy    JSON NOT NULL,
  kernel_tuning     JSON NOT NULL,                 -- turn_limits / round_limits / token_budget
  created_at        BIGINT NOT NULL,
  updated_at        BIGINT NOT NULL,
  UNIQUE (job_description_id, version)
);
CREATE INDEX job_assemblies_active ON job_assemblies(job_description_id, status);

-- Prompt 版本历史：当前招聘场景的 AutonomousAssembly overlay revision
CREATE TABLE prompt_overlay_revisions (
  id                BIGINT PRIMARY KEY AUTOINCREMENT,
  job_description_id TEXT NOT NULL,
  version           INT NOT NULL,
  content           JSON NOT NULL,
  status            TEXT NOT NULL DEFAULT 'draft', -- draft / trial / active / archived
  baseline_metrics  JSON,
  trial_metrics     JSON,
  metrics_schema_version TEXT NOT NULL DEFAULT 'prompt-trial-v1',
  activated_at      BIGINT,
  archived_at       BIGINT,
  created_by        TEXT NOT NULL,
  created_at        BIGINT NOT NULL
);

-- Goal 原语复用 goal_specs，不新建平行表
-- 约定：
--   goal_specs.goal_text            = 自然语言 Goal 正文
--   goal_specs.context_hints        = Goal 激活范围（scope/filter/hints），具体字段语义由场景定义
--   goal_specs.run_preferences      = 开始条件 / 终止条件 / 运行开关 / 调度偏好
--   goal_specs.active_plan_id       = 当前有效 plan/version 指针

-- AssistantAssembly：当前无同类表，新增 assistant_assemblies
CREATE TABLE assistant_assemblies (
  id                    BIGINT PRIMARY KEY AUTOINCREMENT,
  assistant_assembly_id TEXT UNIQUE NOT NULL,   -- 该条 assembly 的业务键，供 conversation 固定绑定
  assistant_id          TEXT NOT NULL,          -- 逻辑 assistant 身份标识，可对应多版本 assembly
  assistant_key         TEXT NOT NULL,
  agent_profile_id      TEXT NOT NULL,
  version               INT NOT NULL DEFAULT 1,
  status                TEXT NOT NULL DEFAULT 'active',
  prompt_overlay        JSON NOT NULL,
  tool_policy           JSON NOT NULL,         -- assistant 允许的 tool/skill/plugin/mcp 组合
  memory_policy         JSON NOT NULL,         -- 会话摘要读取、长期记忆范围、是否可读 operator notes
  guard_override        JSON NOT NULL,
  context_policy        JSON NOT NULL,
  kernel_tuning         JSON NOT NULL,
  created_at            BIGINT NOT NULL,
  updated_at            BIGINT NOT NULL,
  UNIQUE (assistant_id, version),
  UNIQUE (assistant_key, version)
);
CREATE INDEX assistant_assemblies_active ON assistant_assemblies(assistant_id, status, version);

-- 全局 Autonomous 控制开关（单行表，Kernel 通用）
-- 设计原则：纯机械开关；Heartbeat 起 turn 前读一次；任何 autonomous 风格 agent 都通用
-- 业务语义（如何决定是否要 pause / 哪些工具受其影响）由场景能力包通过 Guard check 决定
CREATE TABLE agent_global_state (
  id                    BIGINT PRIMARY KEY AUTOINCREMENT,
  autonomous_paused     BOOLEAN NOT NULL DEFAULT FALSE,
  paused_at             BIGINT,
  paused_by             TEXT,
  paused_reason         TEXT,
  updated_at            BIGINT NOT NULL
);
-- 约定：仅一行（id=1），由迁移种子写入；后续 UPDATE，不 INSERT
```

> 场景特化的 DDL（如招聘场景的候选人接管锁）请见 §3.7。

### 3.2 Run / Turn / Round

> 主键 / 业务键合同（强约束）：
>
> - 所有**物理主键**统一使用现有 `id BIGINT`
> - 所有**物理外键**统一使用 `*_pk BIGINT` 指向对方 `id BIGINT`
> - 所有**业务键**统一使用 `*_id TEXT`，仅用于 API、日志、跨系统引用，并且必须显式 `UNIQUE`
> - 新增执行记录表一律同时保留 `id BIGINT` + `*_id TEXT UNIQUE`
> - 禁止出现 `TEXT REFERENCES <table>.id(BIGINT)` 这种混用写法
> - 若现有旧表主键暂时不是 `id BIGINT`，实现前必须先统一到该约束，然后再落下游外键；本 spec 不接受“双主键并存”的中间态写法。

```sql
-- 复用现有 agent_runs，直接扩字段，不新建平行 run 表
ALTER TABLE agent_runs ADD COLUMN run_id TEXT UNIQUE; -- 业务键
ALTER TABLE agent_runs ADD COLUMN agent_kind TEXT DEFAULT 'autonomous';
ALTER TABLE agent_runs ADD COLUMN turns_count INT NOT NULL DEFAULT 0;
ALTER TABLE agent_runs ADD COLUMN prompt_tokens BIGINT NOT NULL DEFAULT 0;
ALTER TABLE agent_runs ADD COLUMN completion_tokens BIGINT NOT NULL DEFAULT 0;
ALTER TABLE agent_runs ADD COLUMN cache_hit_tokens BIGINT NOT NULL DEFAULT 0;
ALTER TABLE agent_runs ADD COLUMN escalate_reason TEXT;
ALTER TABLE agent_runs ADD COLUMN lock_scope JSON;
ALTER TABLE agent_runs ADD COLUMN idempotency_key TEXT;
ALTER TABLE agent_runs ADD COLUMN wakeup_state JSON NOT NULL DEFAULT '{}';
CREATE INDEX ix_agent_runs_status_started ON agent_runs(status, started_at);

-- Turn / ToolInvocation 是现有模型里没有的精细执行记录，允许新增表
CREATE TABLE agent_turn_records (
  id                BIGINT PRIMARY KEY AUTOINCREMENT,
  turn_id           TEXT UNIQUE NOT NULL,
  run_pk            BIGINT NOT NULL,
  seq               INT NOT NULL,
  phase             TEXT NOT NULL,
  outcome_kind      TEXT NOT NULL,
  outcome_metadata  JSON,
  observation_hash  TEXT,
  request_meta      JSON,
  started_at        BIGINT NOT NULL,
  ended_at          BIGINT NOT NULL,
  FOREIGN KEY (run_pk) REFERENCES agent_runs(id)
);
CREATE INDEX ix_agent_turn_records_run_seq ON agent_turn_records(run_pk, seq);

-- round 级细节当前通过 agent_runtime_events / debug replay 暴露，不单独建 round_records 表
-- 约定：
--   event_type = 'round.completed'
--   payload = {round_seq, status, gate_signal, tool_calls, tool_results, ...}

CREATE TABLE tool_invocations (
  id                BIGINT PRIMARY KEY AUTOINCREMENT,
  turn_pk           BIGINT NOT NULL,
  tool_name         TEXT NOT NULL,
  args_digest       TEXT,
  is_error          BOOLEAN NOT NULL,
  error_kind        TEXT,
  retries           INT NOT NULL DEFAULT 0,
  latency_ms        INT,
  output_tokens     INT,
  started_at        BIGINT NOT NULL,
  ended_at          BIGINT,
  FOREIGN KEY (turn_pk) REFERENCES agent_turn_records(id)
);
CREATE INDEX ix_tool_invocations_turn ON tool_invocations(turn_pk);

-- 复用现有 approval_items，直接扩为可恢复的审批实体
ALTER TABLE approval_items ADD COLUMN run_pk BIGINT;
ALTER TABLE approval_items ADD COLUMN turn_pk BIGINT;
ALTER TABLE approval_items ADD COLUMN conversation_pk BIGINT;
ALTER TABLE approval_items ADD COLUMN source_kind TEXT DEFAULT 'autonomous';
ALTER TABLE approval_items ADD COLUMN tool_name TEXT;
ALTER TABLE approval_items ADD COLUMN args_digest TEXT;
ALTER TABLE approval_items ADD COLUMN expires_at BIGINT;
ALTER TABLE approval_items ADD COLUMN executed_at BIGINT;
ALTER TABLE approval_items ADD COLUMN idempotency_key TEXT;
CREATE UNIQUE INDEX ix_approval_items_idempotency ON approval_items(idempotency_key);
CREATE INDEX ix_approval_items_status_created ON approval_items(status, created_at);

-- Checkpoint 原语复用 agent_run_checkpoints，不新建平行表
-- 约定：
--   checkpoint_kind in ('wait_human','blocked','budget_cutoff','resume_hint')
--   summary         = action summary
--   payload         = {goal_ref, scope_ref, blocked_reason, resume_hint, last_known_fact}
--   run_pk          = 所属主线 run

-- FairnessState 不单独建表；存于 agent_runs.runtime_metadata['fairness_state']
-- 最小结构：
--   {
--     "last_scope_ref": str | null,
--     "same_scope_turns": int,
--     "soft_limit": int,
--     "hard_limit": int,
--     "cooldown_until": {"scope_ref": unix_ts}
--   }
-- 具体把什么对象视为公平性 scope，由场景包定义
```

-- NotificationDraft 复用 operator_interactions 表，不新增同类消息表
-- 约定：
--   operator_interactions.interaction_type = 'notification_draft'
--   operator_interactions.status in ('pending','surfaced','dismissed','accepted')
--   operator_interactions.interaction_metadata = {source_run_id, source_turn_id, category, delivery_hint, ...}

-- wakeup 不新建独立表；直接复用 agent_work_items + task_queue
-- 约定：
--   agent_work_items.item_type = 'scheduled_wakeup'
--   agent_work_items.scheduled_for = 唤醒时间
--   agent_work_items.dedupe_key = wakeup idempotency key
--   agent_work_items.payload = {run_id, reason, trigger_type, not_before, ...}

```

### 3.3 Memory

> 说明：
> - 不引入统一 `memory_items` 平行表；
> - 继续使用 `candidate_person_memories` / `job_description_memories` / `agent_global_memories` 三张表；
> - 逻辑上统一抽象为 `MemoryItem`，物理上仍按 candidate/job/global 分表；
> - `RecentEventLog` 不是单独存储表，而是 `agent_runtime_events` 在 run/session 维度上的读取视图。

```sql
-- candidate_person_memories / job_description_memories / agent_global_memories
-- 都扩成 item-row 模式；每一行表示一个 memory item，而不是每个 scope 只有一行大 JSON
ALTER TABLE candidate_person_memories ADD COLUMN memory_item_id TEXT UNIQUE; -- 业务键，供 read_memory / embedding 返回
ALTER TABLE candidate_person_memories ADD COLUMN kind TEXT DEFAULT 'fact';
ALTER TABLE candidate_person_memories ADD COLUMN index_name TEXT;
ALTER TABLE candidate_person_memories ADD COLUMN index_description TEXT;
ALTER TABLE candidate_person_memories ADD COLUMN confidence REAL NOT NULL DEFAULT 0.5;
ALTER TABLE candidate_person_memories ADD COLUMN evidence_refs JSON;
ALTER TABLE candidate_person_memories ADD COLUMN trust_level TEXT NOT NULL DEFAULT 'unverified';
ALTER TABLE candidate_person_memories ADD COLUMN version INT NOT NULL DEFAULT 1;
ALTER TABLE candidate_person_memories ADD COLUMN supersedes_id TEXT;
ALTER TABLE candidate_person_memories ADD COLUMN expires_at BIGINT;
ALTER TABLE candidate_person_memories ADD COLUMN item_metadata JSON NOT NULL DEFAULT '{}';

ALTER TABLE job_description_memories ADD COLUMN memory_item_id TEXT UNIQUE;
ALTER TABLE job_description_memories ADD COLUMN kind TEXT DEFAULT 'pattern';
ALTER TABLE job_description_memories ADD COLUMN index_name TEXT;
ALTER TABLE job_description_memories ADD COLUMN index_description TEXT;
ALTER TABLE job_description_memories ADD COLUMN confidence REAL NOT NULL DEFAULT 0.5;
ALTER TABLE job_description_memories ADD COLUMN evidence_refs JSON;
ALTER TABLE job_description_memories ADD COLUMN trust_level TEXT NOT NULL DEFAULT 'unverified';
ALTER TABLE job_description_memories ADD COLUMN version INT NOT NULL DEFAULT 1;
ALTER TABLE job_description_memories ADD COLUMN supersedes_id TEXT;
ALTER TABLE job_description_memories ADD COLUMN expires_at BIGINT;
ALTER TABLE job_description_memories ADD COLUMN item_metadata JSON NOT NULL DEFAULT '{}';

ALTER TABLE agent_global_memories ADD COLUMN memory_item_id TEXT UNIQUE;
ALTER TABLE agent_global_memories ADD COLUMN kind TEXT DEFAULT 'lesson';
ALTER TABLE agent_global_memories ADD COLUMN index_name TEXT;
ALTER TABLE agent_global_memories ADD COLUMN index_description TEXT;
ALTER TABLE agent_global_memories ADD COLUMN confidence REAL NOT NULL DEFAULT 0.5;
ALTER TABLE agent_global_memories ADD COLUMN evidence_refs JSON;
ALTER TABLE agent_global_memories ADD COLUMN trust_level TEXT NOT NULL DEFAULT 'unverified';
ALTER TABLE agent_global_memories ADD COLUMN version INT NOT NULL DEFAULT 1;
ALTER TABLE agent_global_memories ADD COLUMN supersedes_id TEXT;
ALTER TABLE agent_global_memories ADD COLUMN expires_at BIGINT;
ALTER TABLE agent_global_memories ADD COLUMN item_metadata JSON NOT NULL DEFAULT '{}';

-- 中期记忆不单独建 session_summary / run_context 表：
--   candidate session summary → candidate_sessions.context_summary
--   assistant conversation summary → conversation_sessions.context_summary
--   run context → agent_runs.runtime_metadata['run_context']
```

### 3.4 Compaction / Learning / Evolution

```sql
-- CompactionEvent 当前无同类表，新增 compaction_events
CREATE TABLE compaction_events (
  id                BIGINT PRIMARY KEY AUTOINCREMENT,
  level             TEXT NOT NULL,
  target_ref        TEXT NOT NULL,
  tokens_before     INT,
  tokens_after      INT,
  items_before      INT,
  items_after       INT,
  summary_digest    TEXT,
  triggered_by      TEXT NOT NULL,
  created_at        BIGINT NOT NULL
);
CREATE INDEX ix_compaction_events_target ON compaction_events(target_ref, created_at);

-- 复用 agent_learnings，直接扩为 LearningLog
ALTER TABLE agent_learnings ADD COLUMN turn_id TEXT;
ALTER TABLE agent_learnings ADD COLUMN kind TEXT DEFAULT 'global_lesson';
ALTER TABLE agent_learnings ADD COLUMN content_json JSON;
ALTER TABLE agent_learnings ADD COLUMN promote_requested BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE agent_learnings ADD COLUMN promotion_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE agent_learnings ADD COLUMN target_memory_ref TEXT;
ALTER TABLE agent_learnings ADD COLUMN target_skill_id TEXT;
CREATE INDEX ix_agent_learnings_tick ON agent_learnings(turn_id);

-- 复用 evolution_artifacts，直接扩为 EvolutionQueue
ALTER TABLE evolution_artifacts ADD COLUMN artifact_kind TEXT;
ALTER TABLE evolution_artifacts ADD COLUMN artifact_ref TEXT;
ALTER TABLE evolution_artifacts ADD COLUMN scene_refs JSON;
ALTER TABLE evolution_artifacts ADD COLUMN reviewed_by TEXT;
ALTER TABLE evolution_artifacts ADD COLUMN reviewed_at BIGINT;
ALTER TABLE evolution_artifacts ADD COLUMN review_notes TEXT;
```

### 3.5 Skills / Plugins / MCP

```sql
-- 复用 skills，直接扩字段
ALTER TABLE skills ADD COLUMN trigger_hint TEXT;
ALTER TABLE skills ADD COLUMN body JSON;
ALTER TABLE skills ADD COLUMN trial_metrics JSON;
ALTER TABLE skills ADD COLUMN requires_human_gate BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE skills ADD COLUMN human_gate_policy JSON NOT NULL DEFAULT '{}';

-- ToolMetrics 当前无同类表，新增 tool_metrics
CREATE TABLE tool_metrics (
  id                BIGINT PRIMARY KEY AUTOINCREMENT,
  tool_name         TEXT NOT NULL,
  window_start      BIGINT NOT NULL,
  window_end        BIGINT NOT NULL,
  success_count     INT NOT NULL DEFAULT 0,
  failure_count     INT NOT NULL DEFAULT 0,
  timeout_count     INT NOT NULL DEFAULT 0,
  approval_required_count INT NOT NULL DEFAULT 0,
  reliability_score REAL NOT NULL DEFAULT 1.0,
  metrics_metadata  JSON NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_tool_metrics_tool_window ON tool_metrics(tool_name, window_start, window_end);

-- plugin 当前无同类表，新增 plugins
CREATE TABLE plugins (
  id                BIGINT PRIMARY KEY AUTOINCREMENT,
  plugin_id         TEXT UNIQUE NOT NULL,
  manifest          JSON NOT NULL,
  status            TEXT NOT NULL DEFAULT 'active',
  installed_at      BIGINT NOT NULL,
  health            JSON
);
CREATE INDEX ix_plugins_status ON plugins(status);

-- 复用 mcp_servers，扩健康与熔断信息
ALTER TABLE mcp_servers ADD COLUMN capabilities JSON;
ALTER TABLE mcp_servers ADD COLUMN circuit_state TEXT NOT NULL DEFAULT 'closed';
ALTER TABLE mcp_servers ADD COLUMN circuit_until BIGINT;
ALTER TABLE mcp_servers ADD COLUMN last_health_at BIGINT;
ALTER TABLE mcp_servers ADD COLUMN last_error TEXT;
```

### 3.6 Conversation（Assistant Agent 专属）

```sql
-- 当前无同类表，新增 conversation_sessions / conversation_turns
CREATE TABLE conversation_sessions (
  id                BIGINT PRIMARY KEY AUTOINCREMENT,
  conversation_id   TEXT UNIQUE NOT NULL,
  user_id           TEXT NOT NULL,
  assistant_id      TEXT NOT NULL,
  assistant_assembly_id TEXT NOT NULL,
  assistant_assembly_version INT NOT NULL,
  title             TEXT,
  status            TEXT NOT NULL DEFAULT 'active',
  jsonl_path        TEXT NOT NULL,
  context_summary   TEXT,
  messages_token_count INT NOT NULL DEFAULT 0,
  last_compact_at   BIGINT,
  started_at        BIGINT NOT NULL,
  last_active_at    BIGINT NOT NULL,
  closed_at         BIGINT
);
CREATE INDEX ix_conversation_sessions_user_status ON conversation_sessions(user_id, status);

CREATE TABLE conversation_turns (
  id                BIGINT PRIMARY KEY AUTOINCREMENT,
  conversation_pk    BIGINT NOT NULL,
  turn_id           TEXT UNIQUE NOT NULL,            -- 业务键，cancel API 命中目标
  seq               INT NOT NULL,
  role              TEXT NOT NULL,
  content           JSON NOT NULL,
  tool_calls        JSON,                            -- 已派发的（含已执行 / 已取消未执行）
  tool_results      JSON,
  status            TEXT NOT NULL DEFAULT 'completed', -- 'completed' | 'cancelled'
  cancel_reason     TEXT,
  cancelled_at      BIGINT,
  created_at        BIGINT NOT NULL,
  FOREIGN KEY (conversation_pk) REFERENCES conversation_sessions(id),
  UNIQUE (conversation_pk, seq)
);
CREATE INDEX ix_conversation_turns_conversation_seq ON conversation_turns(conversation_pk, seq);

-- 复用 agent_runtime_events，扩到 autonomous + assistant 统一事件真相源
ALTER TABLE agent_runtime_events ADD COLUMN turn_id TEXT;
ALTER TABLE agent_runtime_events ADD COLUMN turn_id TEXT;
ALTER TABLE agent_runtime_events ADD COLUMN conversation_id TEXT;
ALTER TABLE agent_runtime_events ADD COLUMN seq INT NOT NULL DEFAULT 0;
```

### 3.7 场景能力包 DDL（招聘场景）

> 本节是**招聘场景能力包**所拥有的表，不属于 Kernel。
> 未来其他场景包（如分析工具）应在自己的子节加 DDL，命名建议带 `<scenario>_` 前缀，避免与 Kernel 表与其他场景表冲突。
> 场景包注册机制见 §8.6。

```sql
-- 招聘场景：per-候选人接管锁 + 可选交接说明
-- 设计原则（强约束）：
--   - 仅承载状态，不承载逻辑；过滤/续接是否注入由 LLM 在 prompt 中判断，不在 Sense/Guard 内硬编码 TTL
--   - 一段锁 = 一行；release 不删除，置 released_at；天然审计与多次接管串味隔离
--   - handover_note / handover_next_hint 与 Checkpoint 语义不同：Checkpoint 是 Autonomous 自己中断写的恢复提示，handover_note 是人接管完归还时的事件性说明
CREATE TABLE candidate_autonomous_locks (
  id                    BIGINT PRIMARY KEY AUTOINCREMENT,
  candidate_person_id   TEXT NOT NULL,                 -- 业务键
  locked_at             BIGINT NOT NULL,               -- 秒级
  locked_by             TEXT NOT NULL,                 -- 'user' | 'assistant' | operator_id
  reason                TEXT,
  expires_at            BIGINT,                        -- 可选自动失效；NULL 表示无 TTL
  released_at           BIGINT,                        -- NULL = 当前生效
  released_by           TEXT,
  handover_note         TEXT,                          -- 释放时可选写入：本段接管做了什么
  handover_next_hint    TEXT                           -- 释放时可选写入：下一步建议
);
CREATE INDEX ix_candidate_autonomous_locks_active
  ON candidate_autonomous_locks(candidate_person_id, released_at, expires_at);
```

---

## 4. 核心接口（Python 契约）

### 4.0 主线原语合同

在不把业务状态机写死的前提下，Autonomous 主线必须始终围绕这 5 个原语运转：

- `Goal`：长期任务文档 + 少量强约束运行插槽（scope / 开始条件 / 终止条件 / 开关）
- `State`：外部世界当前真实状态，主要通过业务表和事实查询型 tool 获取
- `Checkpoint`：只在阻塞 / 人审 / 预算打断时写的最小恢复提示
- `Log`：执行留痕，只用于回放、分析、同类阻塞按需检索
- `Memory`：长期/中期经验沉淀

铁律：
- 主线每个 turn 都重新从 `Goal + State + Memory + Recent Log` 现算下一步，不维护显式 agenda
- 细粒度业务对象默认不进入固定快照，只通过 facts tool 或场景包提供的 Observation enricher 按需暴露
- 高噪音网页动作由主线**显式创建执行单元**完成，而不是在主线上连续背 browser turns
- 执行单元不恢复旧现场；失效时重新升级一个新的执行单元


### 4.1 Kernel

```python
# kernel/kernel.py
@dataclass
class AgentKernel:
    provider: LLMProvider
    tool_bus: ToolBus
    memory_service: MemoryService
    context_assembler: ContextAssembler
    guard: GuardPolicy
    learning_writer: LearningWriter
    compact_service: CompactService
    skill_registry: SkillRegistry
    plugin_host: PluginHost
    limits: RoundLimits
    event_sink: EventSink

    def run_round(
        self,
        *,
        goal: GoalRef,
        observation: Observation,
        limits: RoundLimits | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> RoundOutcome: ...
```

### 4.2 八个节点的标准签名

```python
# kernel/sense.py
def sense(ctx: RoundContext) -> Observation: ...

# kernel/assemble.py
def assemble(ctx: RoundContext, obs: Observation) -> LLMRequest: ...

# kernel/deliberate.py
def deliberate(ctx: RoundContext, request: LLMRequest) -> Deliberation: ...

# kernel/guard.py
def guard(ctx: RoundContext, deliberation: Deliberation) -> GuardVerdict: ...

# kernel/act.py
def act(ctx: RoundContext, deliberation: Deliberation) -> Effects: ...

# kernel/update_memory.py
def update_memory(ctx: RoundContext, deliberation: Deliberation, effects: Effects) -> list[LearningLogId]: ...

# kernel/evaluate.py
def evaluate(ctx: RoundContext, deliberation: Deliberation, effects: Effects) -> RoundOutcome: ...
```

`RoundContext` 是 Kernel 注入的运行时对象，持有 `run / assembly / limits / session_factory / observation_hash / plugin_host / goal_ref / fairness_state / runtime_budget`。

### 4.3 主要 DTO

```python
@dataclass
class GoalRef:
    goal_id: str
    version: int | str | None

@dataclass
class CheckpointRef:
    checkpoint_id: str
    checkpoint_kind: str
    summary: str
    payload: dict[str, Any]

@dataclass
class FairnessState:
    last_scope_ref: str | None
    same_scope_turns: int
    soft_limit: int
    hard_limit: int
    cooldown_until: dict[str, int]

@dataclass
class Observation:
    world_snapshot: dict[str, Any]        # 固定快照 contract 的概览：Goal 激活范围、系统级关键事实、最近少量事件、能力健康状态
    scope_ref: str | None                  # 本 turn 当前聚焦的主 scope，由场景定义其含义
    scope_kind: str | None                 # 例如 'job' / 'candidate' / 'doc' / 'ticket'；core 不解释其业务含义
    recent_events: list[RuntimeEvent]      # 来自 agent_runtime_events 的最近事件视图
    available_tools: list[str]
    available_skills: list[str]
    available_mcps: list[str]
    hash: str                              # 用于去重

@dataclass
class LLMRequest:
    system_blocks: list[CacheBlock]        # 最多 4 个书签
    messages: list[Message]
    tools: list[ToolSpec]
    tool_choice: str | dict | None = None
    response_format: str | None = None

@dataclass
class CacheBlock:
    text: str
    cache_control: Literal["ephemeral", None]
    bookmark_label: str                    # debug 用

@dataclass
class Deliberation:
    final_content: str | None
    tool_calls: list[ToolCall]             # 最后一轮 LLM 产出的待执行动作；此前各轮 tool_call 已在本节点内执行并回灌
    raw_messages: list[Message]
    stop_reason: str
    usage: LLMUsage
    cache_hit_ratio: float

@dataclass
class GuardVerdict:
    approved: bool
    reason: str | None
    require_confirmation: list[ToolCall]   # 需要人工确认的原始 tool_call，后续会持久化为 ApprovalItem
    rejected_tool_calls: list[ToolCall]

@dataclass
class WakeupRequest:
    delay_seconds: int
    reason: str
    idempotency_key: str

class CancellationToken:
    """Assistant turn 级取消信号；类似 Claude Code 的 ESC 行为。
    生命周期 = 单个 turn；turn 结束后丢弃。
    Autonomous turn 不持有此 token，turn 是原子单位（见 §5.9）。
    """
    def cancel(self, reason: str = "user") -> None: ...
    def is_cancelled(self) -> bool: ...
    def raise_if_cancelled(self) -> None: ...      # 同步代码用
    async def wait_cancelled(self) -> None: ...    # 协程等待

@dataclass
class ExecutionUnitResult:
    business_result: dict[str, Any]
    side_effects: list[DBWrite]
    learnable_artifacts: list[dict[str, Any]]
    log_refs: list[str]
    progress_signals: dict[str, Any]

@dataclass
class Effects:
    tool_results: list[ToolResult]
    execution_unit_results: list[ExecutionUnitResult]
    db_writes: list[DBWrite]
    enqueued_tasks: list[TaskEnvelope]
    scheduled_wakeups: list[WakeupRequest]
    emitted_events: list[RuntimeEvent]
    created_approvals: list[ApprovalItem]

class RoundOutcome(TypedDict):
    kind: Literal["continue", "sleep", "wait_human", "complete", "escalate"]
    next_delay_seconds: int | None
    message: str | None
    metadata: dict[str, Any]
```

### 4.4 AutonomousAgent

```python
# agents/autonomous.py
@dataclass
class AutonomousAgent:
    kernel: AgentKernel
    run_store: RunStore
    task_queue: SqlAlchemyQueue
    assembly_service: AssemblyService

    def run_turn_from_envelope(self, envelope: TaskEnvelope) -> RoundOutcome:
        run = self.run_store.ensure_for_envelope(envelope)
        assembly = self.assembly_service.resolve(run)
        round_history: list[Message] = []
        for _round_seq in range(self.turn_limits.max_rounds_per_turn):
            observation = self._build_observation(run, envelope, round_history)
            outcome = self.kernel.run_round(
                goal=self._goal_for(run, assembly),
                observation=observation,
                limits=self.kernel.limits,
            )
            round_history = list(outcome.metadata.get("history_messages") or [])
            if outcome.gate_signal not in {None, "continue"}:
                return outcome
        return RoundOutcome(status="continue", gate_signal="budget_exhausted")

    def run_self_audit_turn(self) -> RoundOutcome:
        """空队列时调用；生成一个特殊的 'self_audit' envelope 触发自检 turn。"""
        ...
```

### 4.5 AssistantAgent

```python
# agents/assistant.py
@dataclass
class AssistantAgent:
    kernel: AgentKernel
    session_store: AssistantSessionStore
    turn_limits: TurnLimits
    active_turns: dict[str, ActiveTurn]

    def run_turn_stream(
        self,
        conversation_id: str,
        message: str,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """启动一个 assistant turn，并在内部复用 shared-kernel turn loop。"""
        ...

    def cancel_active_turn(self, conversation_id: str, *, reason: str = "user") -> bool:
        """由 POST /conversations/{id}/cancel 触发；返回是否成功命中活跃 turn"""
        ...
```

**AssistantAssembly 绑定合同（强约束）**：

- `assistant_id` 表示逻辑 assistant 身份；`assistant_assembly_id` 表示某个具体 assembly 版本实例
- `conversation_sessions.assistant_assembly_id` 必须直接落 `assistant_assemblies.assistant_assembly_id`
- conversation 创建时必须确定 `assistant_id + assistant_assembly_id + assistant_assembly_version`
- `resolve_assistant()` 的查找顺序固定为：先按 `assistant_assembly_id` 精确命中，再校验 `assistant_id` 与 `assistant_assembly_version`
- 一次 conversation 生命周期内默认**固定 pinned version**，不得因为后端发布新 assembly 自动漂移
- 只有显式的 `rebind assistant assembly` 管理动作，才允许后续会话切到新版本

**Conversation 恢复合同（强约束）**：

- `conversation_sessions.jsonl_path` 是 **原始消息历史的权威追加日志**；默认路径约定为：`<data_dir>/conversations/{conversation_id}.jsonl`。
- `conversation_turns` 是 **结构化查询投影**，便于 API 分页、最近历史读取和管理后台使用；缺失时可以从 jsonl 重建。
- `conversation_sessions.context_summary` 是 **压缩摘要缓存**，不是事实源；恢复时始终以 jsonl 为准。
- `conversation_sessions` 是 Assistant 自身的 conversation 容器，不等于任何具体业务对象集合。
- 进程重启后，`ConversationStore.get()` 的恢复顺序必须是：
  1. 读 `conversation_sessions` 元数据
  2. 读取 `jsonl_path` 重建完整 messages[]
  3. 若 messages 超阈值，保留最近窗口并把 `context_summary` 作为 compacted prefix 注回
  4. 对 `conversation_turns` 做缺失补投影，而不是反向作为事实源
- `agent_runtime_events` 是会话事件真相源，描述运行过程；**不是** message history 真相源。
- `jsonl_path` 所在目录需要具备：按 conversation 归档、按关闭时间清理、可导出备份三种运维能力。

### 4.6 Heartbeat

```python
# agents/heartbeat.py
@dataclass
class Heartbeat:
    agent: AutonomousAgent
    global_state: AgentGlobalStateService
    interval: int = 30

    async def run_forever(self) -> None:
        while True:
            # 全局 Autonomous 开关：起 turn 前读一次；paused 时本轮不取任务、不跑 self_audit、不消费队列
            # 已在跑的 turn 不被打断；落到 Checkpoint 由 Autonomous 自己决定
            if self.global_state.is_autonomous_paused():
                await asyncio.sleep(self.interval)
                continue
            envelope = self.agent.task_queue.get()
            if envelope is None:
                envelope = make_self_audit_envelope()
            try:
                outcome = self.agent.run_turn_from_envelope(envelope)
            except Exception as exc:
                self._handle_unexpected(envelope, exc)
                continue
            self._apply_outcome(outcome)
            sleep_s = self._resolve_sleep(outcome)
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
```

### 4.7 Persona Fragment 组装契约

> Prompt 片段的具体文案不属于 Kernel。Kernel 只负责收集并拼装 persona fragments；具体业务文案由场景能力包注册。

`Assemble` 在构造书签 1（`Persona + BehaviorRules + ToolsUsagePolicy`）时，必须调用：

```python
plugin_host.collect_persona_fragments(assembly) -> list[tuple[label, text]]
```

约定：
- Kernel 先放 base persona，再按注册顺序追加各场景包的 fragment
- fragment 是**自然语言行为约定**，不是程序逻辑；适合承载"看到某类 State 时怎么判断"、"某类 Guard 拒绝后如何向用户解释"这类规则
- Autonomous / Assistant 的 assembly overlay 可以追加 fragment，但不应覆盖已注册的场景 fragment 语义
- 招聘场景的"人工接管行为约定"由 `recruit` 包在 §8.6.2 注册，不写死在 core spec

---

## 5. Round Cycle 8 节点契约

每个节点的**输入 / 输出 / 副作用 / 失败行为 / 观测**都要符合本节契约。

### 5.1 Trigger

- **输入**：`TaskEnvelope` 或 "self_audit" 信号
- **输出**：`RoundContext` 初始化（run、assembly、limits、event 开端）
- **副作用**：创建 `agent_turn_records`（phase=`trigger`, seq=run.turns_count+1）
- **失败**：envelope 格式不合法 → 进 DeadLetter

### 5.2 Sense

> **Layer: Kernel contract**

- **输入**：`RoundContext`
- **输出**：`Observation`
- **规则**：
  - 调用 `MemoryService.fetch_recent_events(run.session_id, limit=N)`
  - 调用 `WorldSnapshotBuilder.build_summary_contract(goal_ref, fairness_state)`，只拉固定快照 contract 的概览
  - 固定快照只承载 coarse-grained 状态；更细的业务对象与场景字段由后续 facts tool 或场景包 Observation enricher 按需提供
  - 调用 `MCPBridge.list_healthy_mcps()`
  - 调用 `plugin_host.run_observation_enrichers(obs, ctx)` 让所有已注册的场景能力包注入特化 State 字段（见 §8.3 / §8.6）
  - 计算 `observation.hash = sha256(world_snapshot_canonical_json)`
- **场景扩展强约束**：
  - Sense 自身**不感知任何业务概念**（不知道"候选人"、"JD"、"工单"是什么）；任何特化的 State 字段（如招聘包的 `human_locked` `recent_handover`）由对应能力包通过 `register_observation_enricher` 提供
  - **暴露 ≠ 过滤**：enricher 只在 Observation 上标注事实，是否跳过/续接由 LLM 在 prompt 约定中决定（见各场景包的 persona fragment）；最终硬墙在 §5.5 Guard preflight 通过场景包注册的 guard check 实现
- **失败**：DB 不可用 → 抛 `SensingError`，外层 turn 进 `escalate`；单个 enricher 抛异常 → 记录 event 后用上一步的 `obs` 继续，避免拖崩整个 Sense
- **观测**：写 event `sense_completed{hash, snapshot_tokens, enrichers_applied: list[namespace]}`

### 5.3 Assemble

> **Layer: Kernel contract**

- **输入**：`RoundContext`, `Observation`
- **输出**：`LLMRequest`（至少 2 个书签；场景包可追加更多 fragment，最多 4 个）
- **规则**：
  - 书签 1：`Persona + BehaviorRules + ToolsUsagePolicy + plugin_host.collect_persona_fragments(assembly)`
  - 书签 2：`assembly.prompt_overlay + GlobalMemoryIndex + scenario-defined context fragments`
  - 书签 3（可选）：`scope-local memory / recent event fragments`，由 assembly.context_policy 与场景包共同决定是否注入
  - user 消息：`Observation.serialize()` + 本 turn 累积的 tool_use/tool_result
  - tools：ToolBus 给出的"可用工具描述"，**已排除**熔断的 MCP 工具
- **缓存约定**：`cache_control=ephemeral` 打在每个书签末尾；超过 4 个书签合并
- **失败**：prompt 超出 `max_system_tokens` → 降级（丢弃书签 3 的最低分条目再试，≤2 次）
- **观测**：`assemble_completed{bookmarks_count, system_tokens, user_tokens}`

### 5.4 Deliberate

- **输入**：`RoundContext`, `LLMRequest`
- **输出**：`Deliberation`
- **内部循环**（agent loop）：
  ```
  response = provider.generate(request)
  log_round_response(response)
  for tool_idx, call in enumerate(response.tool_calls[: limits.max_tool_roundtrips]):
      guarded_call = guard.preflight_tool_calls(ctx, [call])
      if guarded_call.should_pause:
          return Deliberation(stop_reason="wait_human", tool_calls=guarded_call.pending, ...)
      if guarded_call.blocked:
          persist ApprovalItem / rejected event
          continue
      result = tool_bus.execute(call)  # 含 retry / circuit breaker
      append tool_result to request.messages
  return Deliberation(...)
  ```
- **执行语义（强约束）**：
  - `Deliberate` 是 **唯一允许执行 LLM 内联 tool_call** 的节点；工具结果必须回灌到 `request.messages` 才能进入下一轮推理。
  - 主程序提供的 tool 以**事实查询型**为主：优先返回结构化业务事实，而不是预先下业务结论。
  - 对于高噪音网页动作（browser MCP / 页面解析 / 解阻 / selector 试错 / 多轮 skill 推理），主线不应在本层连续堆 browser turns，而应显式创建新的执行单元。
  - 执行单元可以完整完成一个网页业务动作，但返回给主线的只应是 `ExecutionUnitResult` 四类内容，不回流完整网页细节。
  - `Guard` 在本节点内对每一轮 tool_call 做 preflight，拦截/确认后才允许真正执行工具。
- **context 膨胀处理**：
  - 每个 turn 开头计算 `request.messages_tokens`
  - 若超过软阈值 → 可调 `CompactService.turn_compact(request)`，原地改 messages
  - 若超过硬窗口阈值 → 结束 Deliberate，返回 `stop_reason="context_overflow"`
- **失败**：预算耗尽 / `context_overflow` 都以 `Deliberation(stop_reason=...)` 返回，不抛异常

### 5.5 Guard

> **Layer: Kernel contract**

- **输入**：`RoundContext`, `Deliberation`
- **输出**：`GuardVerdict`
- **两层职责（强约束）**：
  1. `preflight_tool_calls(ctx, tool_calls)`：在 Deliberate 内逐轮执行前检查工具调用
  2. `guard(ctx, deliberation)`：在 Deliberate 结束后检查最终输出是否需要升级/阻断
- **检查顺序**：
  1. `assembly.tool_allowlist`：tool_call 名字必须在白名单
  2. 工具级 rate_limit / circuit 状态
  3. **场景包注册的 guard checks（强约束，不可跳过）**：调 `plugin_host.run_guard_checks(call, ctx)`，按注册顺序执行所有场景包注册的检查；任一返回 `reject` 则整体拒绝，任一返回 `require_confirmation` 则升级为人审
     - Kernel 自身**不知道**这些检查的业务语义；场景包可通过此机制注册自己的硬墙（见 §8.6）
     - 未来不同场景包可各自定义自己的 guard policy，而不修改 core
  4. 敏感动作（外联/上传/覆盖）：查 `assembly.guard_override.sensitive_actions` → 标记 `require_confirmation`
  5. content safety（PII / 违禁词）
- **拒绝**：`approved=False, reason=...` → 外层 turn outcome 走 `escalate`
- **确认**：`require_confirmation` 非空 → 创建 `ApprovalItem`（落在 `approval_items` 表），当前 turn 立即结束并在 `Evaluate` 产出 `wait_human`
- **幂等合同**：
  - `ApprovalItem.idempotency_key = sha256(run_id + turn_id + tool_name + canonical_json(tool_args))`
  - 同一个 `idempotency_key` 重复 confirm 只能命中同一条审批记录，不得产生第二次执行
  - 若系统崩溃在“工具已执行但 ApprovalItem 未回写 executed”之间，恢复逻辑必须先检查业务侧副作用是否已存在；存在则只补写 executed，不得重放工具
- **恢复语义**：
  - `/confirm` 只修改 `ApprovalItem.status`
  - 每次 human confirm **都必须触发一个新的 turn / recovery turn**；不允许在原 turn 内原地继续
  - Autonomous：Heartbeat 在下一次新的 turn 中消费已 `approved` 的 `ApprovalItem`，执行对应动作，并将该 `ApprovalItem` 标记为 `executed`
  - Assistant：`/confirm` 触发同一 conversation 的一次新的 recovery turn；恢复 turn 读取已批准的 `ApprovalItem` 后继续执行
- **观测**：`guard_checked{approved, rejected_tools, require_confirm_count}`

### 5.6 Act

- **输入**：`RoundContext`, `Deliberation`, （经 Guard 放行）
- **输出**：`Effects`
- **规则**：
  - 只处理 **Deliberate 结束后的持久化副作用**，不再执行新的 tool_call
  - 将执行结果拆分为：`business_result / side_effects / learnable_artifacts / log_refs / progress_signals`
  - 主线只落业务结果、副作用、通知、人审、wakeup、事件；高噪音网页细节仅落分析日志引用
  - `enqueued_tasks` 通过 `SqlAlchemyQueue.put()`
  - `scheduled_wakeups` 写入 `agent_work_items(item_type='scheduled_wakeup')`
  - `created_approvals` 写入 `approval_items`
  - `emitted_events` 写入 `agent_runtime_events`
- **失败**：
  - 单个执行单元或工具在本 turn 内无有效业务推进时，允许由 LLM 建议暂停并由程序裁决是否切换到别的 scope / 场景路径
  - 单个工具连续失败达到 runtime policy 阈值 → `Effects` 携带 `replan_request=True`
  - 整体无法写 DB → 抛 `ActError`，外层回滚并 `escalate`
- **观测**：`act_completed{db_write_count, enqueued_count, wakeup_count, approval_count}`

### 5.7 UpdateMemory

- **输入**：`RoundContext`, `Deliberation`, `Effects`
- **输出**：`list[LearningLogId]`
- **规则**：
  - 若 `Effects` 标记 `fatal=true`，则跳过 `UpdateMemory`，避免 fatal turn 继续写学习产物
  - 否则扫描 `Effects.tool_results` 中所有 `record_learning` 调用的结果
  - 每条经 `LearningWriter.write(log)`：
    - 写 `agent_learnings`
    - 根据 `PromotionEngine.evaluate(log)` 决定：立即落地 / 排队
  - 扫描 `Deliberation.raw_messages` 中是否有"隐式学习信号"（工具错误累积、场景新事实）
- **失败**：single log 失败不阻塞其他；汇总写 `learning_errors` 事件
- **观测**：`memory_updated{logs_count, auto_promoted, queued}`

### 5.8 Evaluate

- **输入**：`RoundContext`, `Deliberation`, `Effects`
- **输出**：`RoundOutcome`
- **规则树**：
  ```
  if Guard.rejected or Act.fatal → escalate
  if Guard.require_confirmation → wait_human  # 当前 turn 结束；后续只能由新的 turn / recovery turn 恢复
  if Deliberation.stop_reason == "context_overflow" → sleep(60, reason="context_overflow")
  if turn budget exhausted and no valid progress -> llm suggests next step; runtime decides sleep / switch / spawn new execution unit
  if Effects.scheduled_wakeups → sleep(min(delay))
  if Deliberation.final_content 暗示完成 → complete
  else → continue
  ```
- 说明：`run.turns_count` 由 Driver 在 turn 边界维护；run 级 turn 上限若要实施，应放在 Driver，而不是 `kernel.evaluate()`。
- **业务推进判定（强约束）**：
  - 一个 turn 是否成功，不由固定状态机决定，而由两层共同判定：
    1. tool / execution unit 返回 `progress_signals`
    2. LLM 基于这些事实做最终业务语义判断
  - Kernel 不规定"一个 turn 应围绕什么业务对象推进"；主 scope 的选取、是否允许同一 scope 连续推进、何时切 scope，均由场景包 policy + assembly.context_policy 决定
  - runtime 只保留薄约束：预算、审批、人审恢复、可选公平性冷却；公平性作用在哪类 scope 上由场景定义
- **副作用**：更新 `agent_runs.status / turns_count / tokens`；写 `agent_turn_records.outcome_`*

### 5.9 Turn 模式契约（Assistant）

- `AssistantAgent.run_turn_stream()` / `_run_shared_kernel_turn_loop()` 复用 `Sense -> Assemble -> Deliberate -> Guard -> Act -> UpdateMemory -> Evaluate` 的主骨架，但 round 仍然是通过 `kernel.run_round()` 驱动；差异如下：
  1. `Trigger` 来自用户消息，而不是队列/Heartbeat
  2. `Sense` 读取 conversation history / recent tool results / conversation summary，而不是 autonomous run 的 world snapshot
  3. `Deliberate` 以流式事件输出为主
  4. `Guard` 默认只有 preflight；用户在线场景下不再单独执行一层节点级 Guard
  5. 需要确认的动作不直接写“待下一次 turn 的审批挂起逻辑”，而是先向前端发 `confirmation_required` 事件；确认后开启新的 recovery turn
  6. `Act` 仍然只做持久化副作用，不重复执行新的 tool_call
  7. `Evaluate` 只决定：继续流式回复 / wait_user / recovery turn / complete，不负责 Heartbeat 调度
- Turn 模式的强约束：
  - 不允许把 `conversation_turns` 当成 message history 真相源
  - 不允许在原 turn 内等待 human confirm 后继续；confirm 后必须开启新的 recovery turn

**Turn 取消语义（强约束，向 Claude Code 看齐）**：

- 每个 turn 持有一个 `CancellationToken`（见 §4.3），由 `AssistantAgent.handle_turn` 创建并注册到 `cancel_registry`
- 取消触发源：
  - `POST /api/assistant/conversations/{id}/cancel` 显式调用
  - 客户端关闭 SSE 连接 → 服务端检测到 → 自动调 `cancel_active_turn(reason="sse_disconnect")`
- Kernel 必须在三个位点检查 token，确保取消延迟 ≤ 1 个 LLM chunk：
  1. LLM stream 每个 chunk 之间（`provider.generate_stream` 透传 token）
  2. 每次 tool_call 派发前
  3. tool 执行中：tool 接口要求 `async def execute(args, cancel_token)`，长 tool 主动 await
- 取消后行为：
  - 当前 turn 立即结束，向 SSE 推送 `turn_cancelled{reason}` 事件后关闭流
  - **不回滚已写的 DB 副作用**（已发出的对外消息、已落地的业务状态变更不可逆）
  - **不再执行尚未派发的 tool_call**；当前正在执行的 tool 由 token 自行决定是否优雅退出
  - 写入 jsonl `{"type":"turn_cancelled","turn_id":..,"reason":..,"partial_outputs":[...],"executed_tool_calls":[...],"cancelled_at":...}`
  - 写入 `agent_runtime_events(event_type='turn_cancelled')`，便于 Debug 回放
  - `conversation_turns` 当前 turn 行的 `tool_calls` / `tool_results` 字段保留已执行部分；新增 `metadata.cancelled = true`
- 用户后续发新消息 → 正常开启新 turn，conversation history 包含被取消 turn 的 partial outputs（LLM 自行判断是否复用 / 重做）

**Autonomous turn 不可取消（对照说明）**：

- Autonomous turn 是原子单位；要停只能用：①全局 `agent_global_state.autonomous_paused`（停掉新 turn）②场景包定义的 takeover / handover 机制（若存在）③Guard 在 turn 内 reject（拒掉违规 tool）
- 不暴露 "kill 当前 turn" 接口，避免主线半完成动作泄漏；对应需求请用全局暂停或对应场景包提供的干预机制

---

## 6. Memory 子系统

### 6.1 MemoryService 接口

```python
class MemoryService:
    def index_for_scope(self, scope: MemoryScope) -> list[MemoryIndexEntry]: ...

    def read(self, item_business_id: str) -> MemoryItem: ...

    def write(
        self,
        scope: MemoryScope,
        entry: MemoryWriteRequest,
        *,
        expected_version: int | None = None,
    ) -> MemoryItem: ...

    def search_semantic(self, scope: MemoryScope, query: str, top_k: int = 5) -> list[MemoryItem]:
        """仅当 Assembly.context_policy.enable_embedding=True 时可用"""

    def fetch_session_summary(self, session_id: str) -> SessionSummary | None: ...

    def fetch_run_context(self, run_id: str, key: str) -> Any: ...
    def set_run_context(self, run_id: str, key: str, value: Any) -> None: ...

    def fetch_recent_events(self, session_id: str, limit: int) -> list[Event]: ...
```

**embedding 合同（强约束）**：

- `enable_embedding` 只是 per-assembly 开关；真正启用时还必须指定：
  - `embedding_provider`
  - `embedding_model`
  - `embedding_dimensions`
  - `index_version`
- embedding 索引不进入主 memory 表；使用独立索引存储（可用 sqlite-vss 或等价实现），但 item 主记录仍留在现有 memory 表。
- 任一 provider/model/version 变化都必须触发该 scope 的索引重建；重建期间 `search_semantic` 自动降级为索引 + `read_memory` 路径。
- `search_semantic` 的返回永远是现有 memory item 的业务 id，不能返回裸向量行 id。

### 6.2 MemoryIndexEntry 格式

```python
@dataclass
class MemoryIndexEntry:
    business_id: str
    label: str                # 索引行显示
    description: str          # 一句话，≤200 字
    kind: str
    confidence: float
    trust_level: str
    tokens_if_fetched: int    # 估算
```

### 6.3 MEMORY.md 风格序列化

```
# Memory Index (scope: job:jd_android_senior)
- [scoring_preference](memitem_001) — Android 岗偏好 3+ 年 Kotlin 实战
- [blacklist_signal](memitem_002)  — 简历自述"求稳"→ 匹配率低
- [outreach_tone](memitem_003)     — 该 JD 对直接外联反感
...
```

### 6.4 读取合约

- 启动 turn 时**只注入索引**（lightweight）
- LLM 在 Deliberate 阶段调 `read_memory(business_id)` 拿详情
- `read_memory` 工具实现：`return self.memory.read(id)`

### 6.5 写入合约

`record_learning` 工具入口：

```
record_learning({
  "kind": "candidate_fact",
  "scope_ref": "cand:person_xxx",
  "index_name": "有北京 offer",
  "index_description": "候选人已有北京某 A 厂 offer，截止日期 5/1",
  "content": { ... },
  "confidence": 0.8,
  "evidence_refs": ["turn:<current>"],
  "promote": false
})
```

LearningWriter：

1. 检查冲突：同 scope + 同 index_name 是否已有 → 若有，做 `supersedes` 版本化
2. 使用 `expected_version` 做乐观锁；版本不匹配时，Autonomous 重读后再写，Assistant 向用户提示“该对象刚被更新，请确认是否覆盖”
3. 评估 promotion（见 §8.2）
4. 写现有 memory 表 item 行 + `agent_learnings`

---

## 7. Compact 子系统

### 7.1 Turn-level compact（Deliberate 内触发）

```python
def turn_compact(request: LLMRequest) -> LLMRequest:
    messages = request.messages
    if token_count(messages) < soft_compact_threshold:
        return request
    # 保留策略
    keep_head = messages[:1]        # 第一条 user（原始任务）
    keep_tail = [m for m in messages[-6:] if m.role == "tool"] + messages[-2:]
    middle = messages[len(keep_head):-len(keep_tail)]
    summary = llm_summarize(middle, style="agent_trace")
    new_messages = keep_head + [Message(role="user", content=f"[Compacted]\n{summary}")] + keep_tail
    log_compaction("turn", tokens_before=..., tokens_after=...)
    return LLMRequest(..., messages=new_messages)
```

### 7.2 Session-level compact（会话收尾）

- 触发：`candidate_sessions.status` → closed / idle_too_long；`conversation_sessions` 同理
- 动作：把 session 内所有事件 + 现有 `context_summary` 喂给 LLM，输出固定 schema 的 `SessionSummary`
- 落地：写 `candidate_sessions.context_summary` 或 `conversation_sessions.context_summary`

### 7.3 Memory-level consolidation（异步 worker）

- 触发：现有 memory 表中某一 scope 的活跃 item 数量 > threshold，或每周 cron
- 动作：
  - 读该 scope 全部 items
  - 按 `kind` + `index_name` 聚类
  - LLM 合并相似条目；冲突条目标 `contradicted`
  - 过期条目（`expires_at < now`）→ `archived`
- 产物：版本 bump；旧版本设 `supersedes_id`

---

## 8. 扩展生态（Tools / Skills / Plugins / MCP）

### 8.1 ToolBus 统一门面

```python
class ToolBus:
    def list_available(self, assembly: Assembly, healthy_mcps: list[str]) -> list[ToolSpec]: ...
    async def execute(self, call: ToolCall, *, cancel_token: CancellationToken | None = None) -> ToolResult: ...

    # 内部
    def _select_backend(self, tool_name: str) -> ToolBackend:
        # 依次查：内置 -> plugin -> skill -> mcp
```

**Tool 实现约定（强约束）**：

- 所有 tool 实现签名为 `async def execute(args, cancel_token: CancellationToken | None = None)`
- 长时间运行的 tool（>200ms 或包含网络/子进程/MCP 调用）必须在合适检查点 `await cancel_token.wait_cancelled()` 或调 `cancel_token.raise_if_cancelled()`，让 Assistant turn cancel 能尽快生效
- Autonomous turn 调用时 `cancel_token=None`，tool 跑到完成（turn 是原子单位，不可中途取消）

| 类别 | 定义 | external_target | 典型例子 | 约束 |
|---|---|---|---|---|
| fact_query | 返回事实，不直接下业务结论 | false | `read_memory`, 查询池子人数、查询回复状态、查询是否已收到简历 | 主线优先使用 |
| action (internal) | 操作站内数据，无对外副作用 | false | 录入记录、写内部备注、修改业务状态、Assistant 内部草稿 | 两类 agent 都可用 |
| action (external) | 触达外部系统 / 对外发送消息 | **true** | browser MCP、外发邮件/IM、第三方站点操作 | 是否允许由场景包 Guard 决定 |
| meta | 改变调度/学习/运行控制 | false | `record_learning`, `schedule_self_wakeup`, `enqueue_follow_up`, `create_execution_unit`, `wait_unit`, `unit_result` | 不直接代表业务事实 |

**ToolSpec 新增字段**：

```python
@dataclass
class ToolSpec:
    name: str
    category: Literal['fact_query', 'action', 'meta']
    external_target: bool = False           # action 类工具是否触达外部系统
    resource_target_kind: str | None = None # 可选资源类型提示；如 'candidate' / 'ticket' / 'doc'，供场景包 guard check 解析使用
    ...
```

**AssistantAssembly 默认装配规则（core 级）**：

- `tool_policy.tool_allowlist` 可以按 `ToolSpec` 元数据过滤（例如 `external_target=false`）；是否这么做由具体场景包与 assembly 策略决定
- 若用户场景需要临时放开一类工具，应由对应场景包的 Guard check + persona fragment 共同约束；Kernel 不写死具体业务流程

> 招聘场景的接管工具、候选人锁判定、`external_target` 的具体放行逻辑都放在 §8.6 `recruit` 包中，不属于 core ToolBus 契约。

### 8.2 SkillRegistry

```python
class SkillRegistry:
    def list_for_assembly(self, assembly: Assembly) -> list[SkillSpec]: ...
    def invoke(self, skill_id: str, args: dict) -> SkillResult: ...
    def propose_draft(self, draft: SkillDraft) -> SkillId: ...
    def promote(self, skill_id: str, to_status: str) -> None: ...
```

SkillExecutor 的实现：把 skill 视为"带 schema 的 LLM subroutine"——内部调 LLM 一次，返回 `output_schema` 对应的 JSON。

**执行单元合同（强约束）**：
- 对 Autonomous 主线而言，高噪音网页动作通过“显式创建执行单元”的方式运行；执行单元可以由 skill 封装，但语义上是独立运行单元
- 执行单元内部可以多轮 turns、自行重试、自行 compact、自行产生分析日志
- 执行单元默认不要求现场续命；失效时重新升级一个新的执行单元，而不是恢复旧现场
- 产物默认先存档，不直接长期可用；由主 agent 判断是否有复用价值
- 平台/JD 维度的能力按 scope 独立试用：连续成功 5 次才长期可用，连续失败 5 次则重新升级新的执行单元

**可用性 merge 合同（强约束）**：

- base-level 可用能力的**权威 schema** 固定为 `AgentProfile.capability_profile`（当前招聘实现落在 `RecruitAgentProfile`；未来其他场景只要满足同一 schema 即可）
- `capability_profile` 最小结构：
  - `enabled_tools: list[str]`
  - `enabled_skills: list[str]`
  - `enabled_plugins: list[str]`
  - `enabled_mcps: list[str]`
  - `denied_tools: list[str]`
  - `denied_skills: list[str]`
  - `denied_plugins: list[str]`
  - `denied_mcps: list[str]`
- `channel_config` 只描述业务通道策略，不再承担能力白名单职责
- `prompt_config` 只描述 prompt / context / response policy，不再承担能力白名单职责
- `AutonomousAssembly` / `AssistantAssembly` 只做 overlay，不直接绕过 base-level 禁用项
- precedence：
  1. profile base enable/deny list
  2. assembly add/remove overlay
  3. runtime health filter（circuit breaker / rate limit / auth）
  4. Guard 最终裁决
- 任一层显式 deny 都优先于下游 allow

### 8.3 PluginHost

> **Layer: Kernel extension surface**

```python
class PluginHost:
    # 通用 plugin 生命周期（已存在）
    def load(self, manifest_path: str) -> PluginHandle: ...
    def call_hook(self, hook: str, ctx: HookContext) -> HookResult: ...

    # 场景能力包注册位（新增；为 §8.6 服务）
    def register_tools(self, namespace: str, toolkit: list[ToolSpec]) -> None: ...
    def register_observation_enricher(
        self,
        namespace: str,
        fn: Callable[[Observation, RoundContext], Observation],
    ) -> None: ...
    def register_guard_check(
        self,
        namespace: str,
        fn: Callable[[ToolCall, RoundContext], GuardCheckOutcome],
    ) -> None: ...
    def register_persona_fragment(
        self,
        namespace: str,
        label: str,
        text: str,
    ) -> None: ...
    def register_router(self, namespace: str, router: APIRouter) -> None: ...

    # 节点回调（被 Sense / Guard / Assemble 调用，按注册顺序执行）
    def run_observation_enrichers(self, obs: Observation, ctx: RoundContext) -> Observation: ...
    def run_guard_checks(self, call: ToolCall, ctx: RoundContext) -> list[GuardCheckOutcome]: ...
    def collect_persona_fragments(self, assembly: Assembly) -> list[tuple[str, str]]: ...
```

Plugin 以 Python 包形式发布；`manifest.json` 声明 hooks 与 tools。加载时用 subprocess 隔离（必要时）或 async task 沙箱。

**场景能力包注册约定（强约束）**：

- `namespace` 必填，作用域命名空间；同 namespace 下重名注册视为覆盖；不同 namespace 下重名工具按 `<namespace>:<tool_name>` 暴露给 LLM
- 顺序：`register_*` 在进程启动期由 `manifest.install(host)` 调用；运行期不动态注册
- `GuardCheckOutcome` 三态：`approve` / `reject(reason)` / `require_confirmation(reason)`；任一注册项 reject → 整体 reject
- `register_router` 的 router 挂载路径强制 `/api/<namespace>/...`，避免与 Kernel 自带路由冲突
- 全部场景包构成的总能力 = Kernel 内置 ∪ 各 namespace 场景包；缺包等价于"该场景能力不可用"，Kernel 仍可运行

### 8.3.1 ToolFeedback / ToolMetrics / Skill Human Gate

- `tool_feedback` 的消费目标固定为 `tool_metrics` 表，最小字段：
  - `tool_name`
  - `scope_key`              # 平台/文档/页面类型/业务对象等 LessonScope 维度
  - `window_start`
  - `window_end`
  - `success_count`
  - `failure_count`
  - `timeout_count`
  - `approval_required_count`
  - `reliability_score`
- `PromotionEngine` 可读取 `tool_metrics.reliability_score` 参与是否推荐 tool / skill 的决策，但不能直接覆盖 Guard。
- 敏感 skill 必须有 `requires_human_gate=true` 字段；
`SkillRegistry.invoke()` 在命中该条件时必须走与 `ApprovalItem` 相同的人审链路，而不是直接 trial/promote。
- lesson / skill / prompt 演化的冲突判断以 `LessonScope = platform + jd_id + topic` 为最小作用域；同 scope 下出现冲突时强制进入人工审核，不允许自动晋升。
- `trial gate` 解决“好不好用”，`human gate` 解决“能不能直接放给系统用”；两者不可互相替代。

### 8.4 MCPBridge

```python
class MCPBridge:
    def list_healthy(self) -> list[MCPServer]: ...
    def tools_from(self, server: MCPServer) -> list[ToolSpec]: ...
    def execute(self, server: MCPServer, tool: str, args: dict) -> ToolResult: ...
```

每次调用被 `CircuitBreaker` 包裹；连续失败触发熔断。

### 8.5 ExecutionUnit 子系统

```python
@dataclass
class ExecutionUnitRequest:
    unit_kind: str                 # browser_skill / page_parse / unblock / site_action
    goal_ref: GoalRef
    scope_ref: str                 # scenario-defined scope reference
    instruction: str
    allowed_tools: list[str]
    budget_ms: int
    resume_hint: str | None = None

@dataclass
class ExecutionUnitHandle:
    unit_id: str
    status: Literal['queued','running','blocked_human','blocked_environment','succeeded','failed','timed_out','cancelled']
    created_at: int

class ExecutionUnitRunner:
    def create_execution_unit(self, req: ExecutionUnitRequest) -> ExecutionUnitHandle: ...
    def wait_unit(self, unit_id: str, timeout_ms: int) -> ExecutionUnitHandle: ...
    def unit_result(self, unit_id: str) -> ExecutionUnitResult | None: ...
```

状态机：
```text
queued -> running -> succeeded
                ├-> blocked_human
                ├-> blocked_environment
                ├-> failed
                ├-> timed_out
                └-> cancelled
```

规则：
- 创建入口：主线在 Deliberate 中通过 meta tool `create_execution_unit` 显式创建执行单元
- `wait_unit` 允许当前 turn 在预算内等待一个执行单元完成；超时则由 Evaluate 决定 sleep / switch / checkpoint
- `unit_result` 是主线拿回 `ExecutionUnitResult` 的唯一入口
- 执行单元可同步完成，也可跨 turn 异步完成；从主线视角统一通过 `ExecutionUnitHandle/Result` 交互
- 若执行单元返回 `blocked_environment` / `failed` / `timed_out`，主线必须为该 `scope_ref` 写一条短期抑制记录（可落在 Checkpoint 或短期 Memory / runtime_metadata 中），在 cooldown 窗口内避免重复派发同类执行单元
- cooldown 到期前，主线下一 turn 仍可读取该 scope 的 State，但不得对同一 `scope_ref + action_type` 立即重派；只能切换到其他 scope / 场景路径，或等待新的外部事件触发重试

### 8.6 场景能力包（Scenario Capability Pack）

> **Layer: Scenario-pack contract + recruit pack example**

> Kernel 不知道"招聘"是什么；招聘所有的特化语义（候选人、接管、handover、外部触达约束）由**场景能力包**通过 §8.3 PluginHost 注册位提供。
> 短期内只有招聘一个包；预留 namespace 机制以便后续接入分析工具等其他场景。

#### 8.6.1 通用契约

场景包 = 一个 Python 模块 + 一个 `install(host: PluginHost)` 入口：

```python
# plugins/<scenario>/manifest.py
SCENARIO_NAMESPACE = "<scenario>"   # e.g. "recruit", "analysis"

def install(host: PluginHost) -> None:
    host.register_tools(SCENARIO_NAMESPACE, list_toolkit())
    host.register_observation_enricher(SCENARIO_NAMESPACE, observation_enricher_fn)
    host.register_guard_check(SCENARIO_NAMESPACE, guard_check_fn)
    host.register_persona_fragment(SCENARIO_NAMESPACE, label="...", text="...")
    host.register_router(SCENARIO_NAMESPACE, scenario_router)
```

注册时机：进程启动期由 `AppContainer` 调 `install_scenario_packs(host, settings.scenario_packs)`；运行期不变。
场景包 DDL 由 alembic 迁移时按 `scenario_packs` 配置串行 upgrade，命名建议 `<scenario>_<...>` 前缀。

#### 8.6.2 招聘场景包清单（namespace = `recruit`）

提供给主线和 Assistant 的能力如下；与 Kernel 内置能力共同构成完整可用工具集。

**注册的工具**（meta 类，落到 §8.1 三分类的 meta，`external_target=false`）：

```python
# plugins/recruit/toolkit.py
take_over_candidate(
    candidate_person_id: str,
    reason: str | None = None,
    ttl_seconds: int | None = None,
) -> {"lock_id": int, "locked_at": int}

release_candidate(
    candidate_person_id: str,
    note: str | None = None,
    next_hint: str | None = None,
) -> {"released_at": int}

list_locked_candidates(
    active_only: bool = True,
) -> list[{"candidate_person_id": str, "locked_at": int, "locked_by": str, "reason": str | None, "expires_at": int | None}]
```

**注册的 Observation enricher**：在 `Observation.world_snapshot.candidates[*]` 上注入：
- `human_locked: bool`
- `lock_meta: {locked_at, locked_by, reason, expires_at} | null`
- `recent_handover: {released_at, released_by, note, next_hint, lock_lifecycle_seconds} | null`，仅当存在「`released_at > 该候选人最近一次 Autonomous Act 时间`」的释放记录时填充

**注册的 Guard checks**（按顺序执行；任一 reject 则整体 reject）：
1. 候选人接管硬墙：若 `tool.requires_candidate_target == True` 且解析出的 `candidate_person_id` 当前存在生效中的 lock → reject(`candidate_under_human_takeover`)
2. 外部触达 + Autonomous 硬墙：若 `tool.external_target == True` 且当前 agent 不是 Autonomous → 仅在 `agent_global_state.autonomous_paused == True` 时 approve，否则 reject(`external_action_requires_autonomous_paused`)

**注册的 persona fragment**（label = `human_takeover`），写入 base persona 书签：

```text
【人工接管行为约定】
- 你看到的每个候选人都会附带 `human_locked` 与 `recent_handover` 两个字段。
- 当 `human_locked=true` 时：该候选人正在被人接管，本 turn 不要对其执行任何动作（包括草稿、跟进、外联）；可以在思考中提及，但不要触发任何工具调用以其为目标。
- 当 `recent_handover` 存在时：表示这是上一段人工接管刚释放的候选人。先读 `note` 与 `next_hint`，结合当前 State 判断：
    - 是否需要跳过本轮（人已经处理到一个稳定点）；
    - 是否直接续接 `next_hint` 给的下一步；
    - 是否改换路径（例如人已经决定不再跟进）。
  相关性窗口由你判断，不要机械地按时间裁剪；如果 handover 已被业务表中后续状态覆盖，应优先信任业务表。
- 若你需要执行外部触达类工具但被 Guard 拒绝（提示 `external_target` 限制），说明你不是 Autonomous 或 Autonomous 未暂停；请向用户清晰说明，不要重复尝试。
- 不要把 handover 当成你的长期记忆来源；如果其中含有可复用的候选人事实或经验，请显式调用 `record_learning` 沉淀。
```

**注册的 router**（挂在 `/api/recruit/...`）：

```
POST   /api/recruit/candidates/{candidate_person_id}/lock     # body: {reason?, ttl_seconds?, locked_by}
POST   /api/recruit/candidates/{candidate_person_id}/release  # body: {released_by, note?, next_hint?}
GET    /api/recruit/candidates/locks                          # ?active_only=true
```

**所属 DDL**：见 §3.7（`candidate_autonomous_locks`）。

> Kernel 通用、与场景无关的开关 API（如 `/api/agent/autonomous/pause` `/resume` `/state`）仍在 §10.1，不属于本场景包。

#### 8.6.3 未来场景包预留

- 命名空间举例：`analysis`、`growth`、`internal_ops`
- 同 namespace 下表名应带 namespace 前缀，避免与 Kernel 表 / 其他场景表冲突
- 工具暴露给 LLM 时使用 `<namespace>:<tool_name>` 完整名（招聘包内部工具如对场景外暴露则同样规则），LLM 由 prompt 自然知晓 namespace 含义

---

## 9. 运行时安全（Guard / Limits / Circuit Breaker）

### 9.1 `RoundLimits` / `TurnLimits`（每 Assembly 或 Driver 可覆盖）

```python
@dataclass
class RoundLimits:
    token_budget: int = 12_000
    max_tool_roundtrips: int = 8
    tool_timeout_seconds: int = 30
    min_wakeup_delay_seconds: int = 60
    max_wakeup_delay_seconds: int = 86_400


@dataclass
class TurnLimits:
    max_rounds_per_turn: int = 8
    turn_timeout_seconds: int = 120
    token_budget: int = 24_000
    cooldown_seconds: int = 0
```

### 9.2 CircuitBreaker

```python
@dataclass
class CircuitBreaker:
    failure_rate_threshold: float = 0.5
    window_seconds: int = 60
    cooldown_seconds: int = 300

    def record(self, success: bool) -> None: ...
    def should_allow(self) -> bool: ...  # closed -> True; open -> False; half_open -> probe
```

应用位置：

- 每个工具一个
- 每个 MCP server 一个
- 每个 LLM provider 一个

### 9.3 DeadLetter

`task_queue` 新增字段：`failure_count`, `last_error`, `dead`. 连续失败 ≥ `max_attempts` → `dead=true`，从 pending 列表排除；写通知。

### 9.4 Stale 恢复

`SqlAlchemyQueue.recover_stale` 保留；Heartbeat 启动时调用；条件：`locked_at < now - stale_after` 且 `status=running`。

---

## 10. HTTP / WS API

### 10.1 Autonomous 相关（扩 existing `recruit_agent.py`）

```
GET    /api/agent/runs?status=...
GET    /api/agent/runs/{run_id}
GET    /api/agent/runs/{run_id}/turns

# round 级细节通过 debug replay / runtime events 暴露，不单独提供 /rounds endpoint

POST   /api/agent/assemblies/{jd_id}            # 创建/更新 JobAssembly
GET    /api/agent/assemblies/{jd_id}/versions

POST   /api/agent/heartbeat/pause
POST   /api/agent/heartbeat/resume
GET    /api/agent/heartbeat/status

# Autonomous 全局开关：控制整个 Autonomous 是否参与新 turn
# 与 heartbeat/pause 不同：heartbeat/pause 是停掉守护进程；autonomous/pause 是让守护进程跑但 skip turn
POST   /api/agent/autonomous/pause                # body: {reason?, paused_by}
POST   /api/agent/autonomous/resume               # body: {released_by}
GET    /api/agent/autonomous/state                # {autonomous_paused, paused_at, paused_by, paused_reason}
```

### 10.2 Assistant 相关（新 `assistant.py` router）

```
POST   /api/assistant/conversations             # {user_id, title?}
GET    /api/assistant/conversations?user_id=...
GET    /api/assistant/conversations/{id}
DELETE /api/assistant/conversations/{id}

POST   /api/assistant/conversations/{id}/turn   # SSE; body: {content}
  events:
    - turn_started
    - llm_delta (partial content)
    - tool_call (with confirmation_required flag)
    - tool_result
    - llm_final
    - turn_completed
    - turn_cancelled  (用户中断；payload: {reason, partial_outputs, executed_tool_calls})
    - compacted

POST   /api/assistant/conversations/{id}/confirm  # 确认待确认的 tool_call
POST   /api/assistant/conversations/{id}/cancel   # 取消当前活跃 turn；body: {reason?}; 200 = 命中并已发取消信号；404 = 当前无活跃 turn
```

### 10.3 Evolution 相关

```
GET    /api/evolution/queue?status=pending
POST   /api/evolution/queue/{id}/approve
POST   /api/evolution/queue/{id}/reject
GET    /api/evolution/skills?status=trial
POST   /api/evolution/skills/{id}/promote
```

### 10.4 Debug / Observability

```
GET    /api/debug/runs/{run_id}/replay          # 完整 turn/round/tool 回放
GET    /api/debug/cache/stats                   # cache hit 率
GET    /api/debug/mcp/health
GET    /api/debug/circuit-breakers
GET    /api/debug/alerts                        # runtime 告警视图
```

**observability 合同（强约束）**：

- `LLMCallLog` 在实现上等价为：`agent_turn_records` + `agent_runtime_events(event_type in {'llm_request','llm_response','llm_compacted'})`
- `ToolInvocationLog` 在实现上等价为：`tool_invocations`
- `AgentRuntimeEvent.payload` 最小字段：`kind`, `phase`, `message`, `severity`, `refs`, `metrics`
- 告警来源不单独建表；从 `agent_runtime_events` 中筛 severity in (`warn`,`error`,`critical`) 且 `requires_attention=true` 形成 `/api/debug/alerts` 视图

---

## 11. 与现状代码的迁移

### 11.1 逐文件去向


| 现有文件                                                                     | 处理                                                                                                                                                                                     |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `services/agent.py`                                                      | 先拆三层：runner 逻辑去 `agents/autonomous.py`；context manifest 去 `kernel/assemble.py`；`_next_tasks_for_result` 完全删除；学习/进化相关去 `evolution/`。迁移完毕后仅保留 `AgentControlService` 作为 HTTP router 入口薄封装 |
| `services/context_assembler.py`                                          | 新增 `build_layered_request()`；老的 `build()` 标记 deprecated，迁移期仍供旧 runner 用                                                                                                                |
| `runtime/agent_loop.py`                                                  | 改名为 `kernel/deliberate.py`（保持 `AgentLoop` 类名以兼容）；删掉 `execution_contract` 特判，把这部分配置改从 assembly 传入                                                                                       |
| `runtime/prompts.py`                                                     | 拆三个函数：`build_persona_block()`、`build_profile_block()`、`build_memory_index_block()`；由 `kernel/assemble.py` 组合                                                                           |
| `runtime/tools.py`                                                       | 保留；`tools/`* 新增工具注册到同一 registry                                                                                                                                                     |
| `scheduler/scheduler.py`                                                 | 保留；被 `agents/heartbeat.py` 调用                                                                                                                                                          |
| `scheduler/queue.py`                                                     | 保留；扩 `failure_count / dead` 字段（alembic migration）                                                                                                                                      |
| `models/domain.py` 的 `AgentRun` / `ApprovalItem` / `AgentRuntimeEvent` 等 | 保留并直接扩字段；不再引入并行同类表                                                                                                                                                                     |
| `services/recruit_agent.py`                                              | 保留；`default_recruit_agent_profile()` 新增 `kernel_tuning` 字段；新增 `JobAssemblyService`                                                                                                     |
| `api/routers/recruit_agent.py`                                           | 保留；新增 assembly 相关路由                                                                                                                                                                    |


### 11.2 数据结构调整

- 用 alembic revision 直接扩现有表字段，并新增真正缺失的新表（如 `job_assemblies`、`prompt_overlay_revisions`、`agent_turn_records`、`agent_turn_records`、`conversation_sessions`、`conversation_turns`、`plugins`、`compaction_events`）
- `agent_runs` / `approval_items` / `agent_runtime_events` / `skills` / `mcp_servers` / `agent_learnings` / `evolution_artifacts` 统一走 `ALTER TABLE` 扩字段
- memory 相关不引入统一新表，直接扩 `candidate_person_memories` / `job_description_memories` / `agent_global_memories`，逐步把每条 memory 拆成 item-row 语义
- 不讨论双写、回填、并行读写；实现时直接以最终结构为准

### 11.3 进程部署

- `backend` 进程：API + Kernel + Memory 子系统（主进程）
- `heartbeat` 进程：`bin/heartbeat_daemon.py`（单实例；通过 systemd 或 supervisord）
- `evolution_worker` 进程：`bin/evolution_worker.py`（处理 promotion / memory consolidation / session summary）
- `mcp_health` 进程：`bin/mcp_health.py`（分钟级 cron）

本地开发期：用 `concurrently` 或 `honcho` 一起起。

---

## 12. 分阶段实施 & 验收

> 每阶段 = 一个独立 PR，需要通过该阶段"验收清单"。
> Phase 编号是逻辑分组，不等于实际实施顺序；实际执行顺序以 §14 为准。

### Phase 0：脚手架（2 天）

**改动**：建目录、Alembic 初始 revision（扩旧表 + 建缺失新表）、空 stub 类、CI 加新目录的 mypy 检查。

**验收**：

- `alembic upgrade head` 成功扩完既有表并建出缺失新表
- 新目录 `mypy --strict` 通过（允许空 stub）
- 单元测试占位 `pytest services/backend/tests/agent/` 收集到骨架测试

### Phase 1：Kernel 骨架（7 天）

> 从本 Phase 起，按“能力驱动主线 + 薄 runtime 约束”实现：不先做大而全状态机，不先做显式 agenda；优先落 Goal / State / Checkpoint / Log / Memory 五原语及其 contract。 

**改动**：

- `kernel/kernel.py` + 8 节点 stub
- `kernel/assemble.py` 完整实现（三书签）
- `kernel/deliberate.py` 包装现有 `AgentLoop`
- `agents/autonomous.py` 最简实现
- `runtime/limits.py` + `events.py` + `models.py`

**验收**：

- 给定一个 fixture run，能跑完 `trigger→sense→assemble→deliberate→guard→act→update_memory→evaluate`，每个节点有事件落库
- 三书签结构化体现在 LLMRequest 上；`cache_control` 打在正确位置
- cache_hit 率通过 provider mock 验证 ≥ 70%（连续 5 次同 prefix）
- 单 turn 不写 memory item 行（UpdateMemory 留空），但写 `agent_turn_records` / `agent_turn_records`
- `pytest services/backend/tests/agent/test_kernel_happy_path.py` 通过

### Phase 2：JobAssembly（5 天）

**改动**：

- `job_assemblies` 表 CRUD
- `agents/assembly.py`：base profile + overlay 合并
- `api/routers/recruit_agent.py` 新增 assembly 端点
- `kernel/assemble.py` 接入 assembly

**验收**：

- 同一候选人走 JD-A 和 JD-B 时，Deliberate 的 prompt 不同、tool_allowlist 不同
- 评分标准（scoring_rubric）在 prompt 里可见
- `GET /api/agent/assemblies/:jd_id/versions` 返回历史版本
- `pytest services/backend/tests/agent/test_assembly_overlay.py` 通过（含冲突字段的 merge 规则）

### Phase 3：Memory 子系统（7 天）

> 重点不是让主线记住全部执行细节，而是：主线靠 Goal/State/Checkpoint/Recent Log 恢复，执行层网页噪音只沉淀成可复用经验。 

**改动**：

- `memory/`* 全套
- 现有 memory 表扩字段并支持 item-row 读写语义
- `tools/read_memory.py` + `tools/record_learning.py`
- `kernel/update_memory.py` 接入 LearningWriter

**验收**：

- `MemoryService.index_for_scope()` 返回 MEMORY.md 风格索引（≤200 字/条）
- LLM 调 `read_memory(id)` 能取到详情
- `record_learning` 冲突处理正确（新版本 supersedes 旧版本）
- 跨 JD / 跨 candidate 无记忆泄露（专门测）
- 现有 memory 表扩字段后，item-row 读写不丢原有信息
- `pytest services/backend/tests/agent/test_memory_isolation.py` + `test_memory_conflict.py` 通过

### Phase 4：Compact 子系统（5 天）

**改动**：

- `memory/compact/`* 三级
- `evolution_worker` 进程骨架（含 memory consolidation cron）
- `kernel/deliberate.py` 接入 turn compact

**验收**：

- Deliberate 中人为撑大 messages 到 85% 能触发 turn compact，压缩后继续跑不报错
- Session 收尾能产出 `candidate_sessions.context_summary` 或 `conversation_sessions.context_summary` 更新
- Memory consolidation 能把 "同 JD + 同 index_name" 的 5 条合成 1 条并归档旧版
- 压缩前后同问答测试集一致率 ≥ 90%（给定固定 Q&A 集合跑 before/after）
- `pytest services/backend/tests/agent/test_compact_*.py` 通过

### Phase 5：Runtime 安全（4 天）

**改动**：

- `runtime/circuit_breaker.py` / `retry.py`
- `kernel/guard.py` 完整
- `kernel/act.py` 接入 retry + circuit breaker
- 工具级 rate_limit

**验收**：

- 一个工具人为注入 60% 失败率，能被 circuit breaker 在 1 分钟内熔断并从 available_tools 剔除
- Deliberate 超过 `max_tool_roundtrips` 时停止继续 tool 往返，且 round 状态正确
- Guard 对黑名单工具调用返回 `approved=False`
- 敏感动作（outreach_send）走 `wait_human` 且生成 `ApprovalItem`
- `pytest services/backend/tests/agent/test_guard_*.py` + `test_circuit_breaker.py` 通过

### Phase 6：Heartbeat & Self-wakeup（3 天）

**改动**：

- `agents/heartbeat.py` + `bin/heartbeat_daemon.py`
- `tools/schedule_self_wakeup.py`
- `tools/enqueue_follow_up.py`

**验收**：

- 空队列下 Heartbeat 能生成 `self_audit` turn 并跑完
- LLM 调 `schedule_self_wakeup(120, ...)` 后 Heartbeat 在 120s 左右醒来处理
- `enqueue_follow_up` 能让下一 turn 看到任务
- 杀进程重启后，未完成 run 能被 stale recovery 重启
- `pytest services/backend/tests/agent/test_heartbeat.py` 通过

### Phase 7：Assistant Agent（7 天）

**改动**：

- `agents/assistant.py` + `assistant/`*
- `conversation_sessions / conversation_turns`
- SSE 路由
- 对话级 compact

**验收**：

- SSE 流式返回 `llm_delta / tool_call / tool_result / llm_final / turn_completed`
- 长对话能触发压缩，压缩后对话继续正常
- 工具需要 confirmation 时，前端能收到 `tool_call{require_confirmation:true}`；调用 `/confirm` 后不会在原 turn 内继续，而是触发一次新的 recovery turn
- Assistant 调 `enqueue_follow_up` 能让 Autonomous 看到
- `pytest services/backend/tests/agent/test_assistant_*.py` 通过

### Phase 8：自进化闭环（5 天）

**改动**：

- `evolution/`* 全套
- `evolution_worker` 完整实现
- `api/routers/evolution.py`
- SkillRegistry 的 trial gate

**验收**：

- `record_learning(promote=true)` 且满足阈值能自动晋升，无需人审
- 不满足阈值的进 `evolution_artifacts`，人审后生效
- 一个 trial Skill 能在 sandbox 跑 N 次，达到成功率阈值后自动进 active
- `prompt_overlay_revisions` 的 trial/baseline 指标对比工作
- `pytest services/backend/tests/agent/test_evolution_*.py` 通过

### Phase 9：Plugins / MCP / Skills 生态（5 天）

> 本阶段要重点落“显式执行单元”能力：高噪音网页动作可独立运行、独立 trial、独立失效、独立重升，但只向主线回流结构化结果与经验。 

**改动**：

- `plugins/`* + `mcp/`* + `skills/*` 完整
- `bin/mcp_health.py`
- PluginManifest loader

**验收**：

- 注册一个外部 MCP 后，其 tools 能出现在 ToolBus.list_available
- MCP 故意注入 60% 失败率时被熔断，期间不进 tools 列表
- 装一个示例 Plugin（含 pre_tool hook），hook 被调用且能改写工具 args
- Skill trial → active 全流程
- `pytest services/backend/tests/agent/test_mcp_*.py` + `test_plugin_*.py` + `test_skill_*.py` 通过

### Phase 10：可观测性 & 收尾（4 天）

**改动**：

- `/api/debug/`* 路由
- 前端 runtime debug 视图（与桌面端对接，本 spec 不含 UI 代码但留接口）
- 完整删掉 old 代码的死分支
- 更新 `CLAUDE.md` 与本 spec 的状态栏

**验收**：

- 任一 run 可在 `/api/debug/runs/:id/replay` 完整回放
- cache_hit、circuit_breaker、mcp_health 各有 API 返回真实指标
- `services/agent.py` 文件行数 < 500（已被拆空）
- `pytest services/backend/tests/ -q` 全绿
- `mypy --strict services/backend/src/recruit_agent/{agents,kernel,memory,evolution,skills,plugins,mcp,assistant}` 通过

---

## 13. 测试要求

### 13.1 测试层级

```
tests/agent/
├── unit/                       每个节点 / 每个接口的纯单测（mock LLM / DB）
│   ├── test_kernel_*.py
│   ├── test_memory_*.py
│   ├── test_compact_*.py
│   ├── test_guard_*.py
│   ├── test_circuit_breaker.py
│   ├── test_assembly_overlay.py
│   └── ...
├── integration/                跨模块，用真 SQLite + mock LLM
│   ├── test_turn_end_to_end.py
│   ├── test_heartbeat.py
│   ├── test_assistant_conversation.py
│   └── test_evolution_pipeline.py
├── contracts/                  LLM provider 契约测试（可选跑真实模型）
│   └── test_anthropic_cache.py
└── fixtures/
    ├── profiles/               sample RecruitAgentProfile / JobAssembly
    ├── candidates/
    └── golden_llm_responses/   记录的 LLM 回复，用于重放
```

### 13.2 关键测试用例（必须存在）

- `test_turn_end_to_end_autonomous`：一个完整 turn 从 trigger 到 evaluate
- `test_turn_cache_hit_rate`：连续 5 turn 同 JD 同候选人，system 前缀 cache 命中率 ≥ 70%
- `test_jd_isolation`：同一候选人在两个 JD 下的 prompt 不相交
- `test_memory_no_leak`：跨候选人 / 跨 JD 取 index 不会出现对方数据
- `test_turn_compact_preserves_decision`：压缩前后同一 observation 的决策一致
- `test_guard_confirmation_flow`：敏感动作被拦 → wait_human（当前 turn 结束）→ `ApprovalItem` confirmed → 新的 turn / recovery turn 恢复
- `test_circuit_breaker_mcp`：MCP 故意失败 → 熔断 → 恢复
- `test_heartbeat_self_audit`：空队列也跑
- `test_self_wakeup`：LLM 要求 60s 后自唤醒，Heartbeat 按时执行
- `test_record_learning_auto_promote`：满足阈值直接晋升
- `test_record_learning_to_queue`：不满足阈值进人审
- `test_conversation_sse_compact`：长对话触发压缩不破坏对话
- `test_prompt_trial_ab`：新 prompt 先试跑再晋升

### 13.3 性能基线

- 单 turn p50 ≤ 2s、p95 ≤ 5s（不含 LLM 调用时间）
- system prompt 前缀 cache 命中率 ≥ 70%
- Heartbeat daemon 内存占用稳态 ≤ 200MB
- MemoryService.index_for_scope(top=50) 查询 ≤ 50ms

### 13.4 灰度 / 回滚

- 每个 Phase PR 必须带 feature flag（`RECRUIT_AGENT_V2_ENABLED=false` 默认）
- 开关打开后，新 runner 生效；关闭时回到老 `build_runner()` 路径
- 新老 runner 统一读现有 memory 表，避免再引入平行 memory 存储

---

## 14. 实施顺序（可照做）

```
1. Phase 0  → 脚手架（不可跳过，提供 DDL）
2. Phase 1  → Kernel 骨架（核心先能跑 happy path）
3. Phase 3  → Memory 子系统（在 Phase 2 之前做，Assembly 依赖 memory index）
4. Phase 2  → JobAssembly（此时 memory 已可用）
5. Phase 4  → Compact
6. Phase 5  → Runtime 安全
7. Phase 6  → Heartbeat & Self-wakeup → 此时 Autonomous Agent 可用
8. Phase 7  → Assistant Agent
9. Phase 8  → 自进化
10. Phase 9 → Plugins / MCP / Skills
11. Phase 10 → 可观测性 + 清理
```

> ⚠️ Phase 2/3 顺序被我手动调整：**Phase 3 先于 Phase 2**，因为 JobAssembly 的
> prompt_overlay 里会引用 JobMemory 的索引条目，memory 不先落地 assembly 没东西可装。

---

## 15. 术语引用

- **Agent Assembly / Kernel / Execution Cycle**：见 `autonomous-agent-improvement-plan.md` Part 1
- **Turn / Round / Run / Session**：见 `agent-context-memory-design-reference.md` Part 8
- **Observation / 三书签 / cache_control**：同上 Part 6 + Part 8
- **MEMORY.md 风格索引**：同上 Part 4

---

## 16. 文档维护

本 spec 的权威实现标准版本在此文件。实施过程中若发现设计缺陷，**先改 spec、再改代码**，避免文档与代码分叉。每个 Phase PR 的 description 要写明"本 Phase 完成了 Part X / Phase Y 的哪些验收项"。
