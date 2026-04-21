# Recruit Agent Runtime 与 Hermes 对照说明

更新时间：2026-04-15

这份文档用于记录当前 `Recruit Agent` runtime 的实现状态、运行模型、memory/context 管理方式，以及它与 `Hermes Agent` 的差异，方便后续回看和继续演进。

## 当前 Runtime 处于什么阶段

当前仓库的 runtime 已经不是“一次任务跑完就结束”的临时执行器，而是一个**带持久化状态的招聘 Agent 运行时基础**：

- 已有长期存在的主会话：`AgentSession`
- 已有每次执行记录：`AgentRun`
- 已有待办单位：`AgentWorkItem`
- 已有挂起恢复点：`AgentRunCheckpoint`
- 已有持久化事件流：`AgentRuntimeEvent`
- 已有执行前上下文装配：`context_manifest`
- 已有候选人级串行锁和平台并发限制

这意味着系统已经具备：

- 主 agent 长期存在
- 每次 run 可审计、可追踪
- 审批后可回到原 run 继续
- 候选人上下文可严格隔离

但它还没有达到 Hermes 那种“通用常驻 agent OS”的阶段。当前仍缺少更深层的 orchestrator 能力，例如：

- work item 合并与更强去重
- 更复杂的抢占与恢复策略
- scheduled tasks / subagent delegation
- provider credential pool 与更复杂的路由策略

## 当前 Runtime 的实际运行模型

### 1. 主 Agent

系统中有一个主 `Recruit Agent`，它不是每次执行时临时创建的，而是长期存在的顶层主体。它持有：

- profile / role / prompt
- playbook
- context policy
- skill 配置
- global memory
- primary `AgentSession`

### 2. AgentSession

`AgentSession` 是主 agent 的长期运行会话。目前默认是一个 `primary` session。重启后：

- session 记录仍然存在
- 如果丢失，会自动补建

所以从“主 agent 是否还在”这个角度看，当前系统是**持久化的**。

### 3. AgentRun

`AgentRun` 表示一次具体执行，不是一个新的长期 agent 身份。一个 run 会绑定：

- lane：`agent` 或 `candidate`
- candidate_id
- jd_id
- platform
- run_type
- context_manifest
- status / checkpoint_status

一个候选人的 run 更像“主 agent 针对该候选人的一次隔离执行事务”，而不是一个独立子 agent。

### 4. Checkpoint

当执行中遇到需要人工确认、权限审批、skill 失效、候选人待回复等情况时，会生成 `Checkpoint`：

- run 进入 `waiting_human` 或 `blocked`
- 审批后回到原 run 继续

当前已做到“恢复到原 run”，但还不是“进程重启后无缝从内存位置继续”。

### 5. RuntimeEvent

所有关键运行事件都会持久化到 `AgentRuntimeEvent`，因此 runtime 已不是只有前端临时看到的内存事件流，而是带审计能力的事件日志。

## 主 Agent 与候选人 Run 的关系

当前架构下：

- 主 agent：统一治理、统一配置、统一长期记忆
- candidate run：按候选人隔离的一次执行单元

它们不是“父子 agent”关系，而是：

- 一个主 agent
- 多个隶属于该主 agent 的 run

### 关键边界

- 同一候选人同一时刻只能有一个 active run
- 不同候选人的 run 不共享候选人私有 memory
- run 可以读取：
  - 当前候选人的 Candidate Memory
  - 当前 JD 的 Job Memory
  - 少量 Agent Global Memory
- run 不拥有独立长期身份，不会成为新的持久 agent

如果后续真的要做“子 agent / worker-agent”，那会是下一阶段的架构升级，不是当前实现。

## Memory 是怎么管理的

当前 memory 已经是**持久记忆**，但不是 Hermes 那种更通用的 memory platform。

### 1. Candidate Memory

按 `agent_profile_id + candidate_id` 唯一存储，严格候选人隔离。

### 2. Job / JD Memory

按 `agent_profile_id + jd_id` 唯一存储，严格 JD 隔离。

### 3. Agent Global Memory

主 agent 的全局长期记忆。

### 4. 存储结构

三类 memory 都保留：

- `raw_content`
- `content`
- `disclosure`
- `summary`
- `token_estimate`
- `compacted_at`

这意味着系统不是直接覆盖原始信息，而是保留原始层、压缩层和披露层。当前默认支持自动 compact，阈值为 `1_000_000`。

## Context 是怎么管理的

当前上下文系统已经从“固定上下文槽位”升级到 `Context Assembler`。

每次 run 前，系统都会生成一个 `context_manifest`，并写入 `AgentRun.context_manifest`。

当前可选上下文来源包括：

- task brief
- candidate progress
- recent messages
- candidate memory
- job memory
- global memory
- assessments
- scorecards
- review decisions
- skill summary
- approval context
- platform context

### 当前装配原则

- `code` 决定硬边界和基础分
- `用户` 通过 `context_policy` 配预算、权重、drop order
- `LLM` 只做可选的小幅 rerank，默认关闭

所以当前不是把 memory 整块塞给模型，而是：

- memory 是长期存储层
- context 是每次执行前从存储层里挑选的片段集合

## 当前是否能在重启后恢复

### 能恢复的

- 主 agent profile
- primary session
- memory
- 候选人状态与沟通记录
- run / checkpoint / event 历史

### 不能无缝恢复的

- 重启前正在执行中的 run

当前启动时会把处于 `running` 的 run 标记为 `interrupted`，而不是自动从中间继续执行。因此当前能力是：

- 主 agent 可恢复
- 运行中 run 不会无缝续跑

## 和 Hermes 的主要差异

以下判断基于 Hermes 官方公开文档在 2026-04-15 的状态。

### Hermes 更强的部分

Hermes 更像通用 agent 平台，公开能力更偏向：

- 持久会话与跨入口使用
- API Server，对外暴露 OpenAI-compatible 接口
- Scheduled Tasks
- Delegation / Parallel Work
- Credential Pools
- 更完整的 provider routing
- Context Files / References
- Skills 的更强生态化和运行时装载

### 当前项目更强的部分

当前项目在招聘垂直场景里更强：

- Candidate / Job / Global Memory 严格隔离
- 候选人状态流更结构化
- 候选人沟通、评分、评审、阶段事件更贴业务
- Agent IM 与候选人 IM 已按 lane 拆开
- 审批、checkpoint、候选人推进与结构化事实强绑定

### 一句话比较

- Hermes：通用常驻 agent OS
- 当前项目：带持久化 runtime 的 Recruit Agent 执行系统

## 当前最大缺口

如果后续要继续逼近 Hermes 在 runtime/context 方面的成熟度，当前最值得补的仍是：

1. 更深的 `Orchestrator`
2. 更强的 work item 合并 / 恢复 / 抢占
3. 更完整的长会话恢复能力
4. 更强的 provider routing / credential pool
5. 更成熟的 skill 运行时装载与按需披露
6. 更强的 context relevance ranking / retrieval augmentation

## 结论

当前 runtime 可以定义为：

**一个持久化的主 Recruit Agent，下面挂很多按候选人隔离、按 run 执行、可 checkpoint 恢复的执行单元。**

它已经明显超过普通 workflow 执行器，但还没有发展成 Hermes 那种通用常驻 agent 平台。

## 参考

本地实现参考：

- [services/backend/src/recruit_agent/services/runtime_control.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/runtime_control.py)
- [services/backend/src/recruit_agent/services/agent.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/agent.py)
- [services/backend/src/recruit_agent/services/context_assembler.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/context_assembler.py)
- [services/backend/src/recruit_agent/services/recruit_agent.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/recruit_agent.py)
- [services/backend/src/recruit_agent/models/domain.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/models/domain.py)
- [Plan.md](/Users/didi/AgentProjects/recruit-agent/Plan.md)

Hermes 官方参考：

- https://hermes-agent.nousresearch.com/docs/user-guide/features/overview
- https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server
- https://hermes-agent.nousresearch.com/docs/user-guide/features/credential-pools
- https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files
- https://hermes-agent.nousresearch.com/docs/guides/delegation-patterns
