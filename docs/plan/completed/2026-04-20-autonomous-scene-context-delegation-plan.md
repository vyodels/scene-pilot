# Autonomous Scene Context Delegation（网页子上下文隔离）实施计划

> Status: completed
> Supersedes: docs/plan/draft/2026-04-20-subcontext-closure-and-business-elevation.md
> Superseded by: -
> Distilled into: -
> Last reviewed against code: 2026-04-21
> Historical source path: -

> **For agentic workers:** 推荐按本计划逐项实施，保留 checkbox 状态；不要跳过“工具面隔离”和“skill 蒸馏边界”两节。

## 1. 目标

把 Autonomous 在网页数据采集、网页观察、网页取证类任务中的低层执行，从主 Agent 业务历史里隔离出来，收口为一个**通用 scene context（子上下文）**。

本次实施的目标不是引入完整多 `SubAgent` 体系，而是在不破坏现有 Agent 边界、不过度改动主控制面的前提下，做到以下几点：

1. 主 `AutonomousAgent` 不再直接暴露 raw browser / MCP scene 工具。
2. 网页执行细节只落在隔离的 scene context 容器中，不直接上浮到主 Agent 历史或 Global Memory。
3. 主 Agent 只消费 scene context 返回的业务级摘要、阻塞和结构化结果。
4. skill 蒸馏职责仍由主 `AutonomousAgent -> Learning / Evolution` 负责，不下放给 scene context。

## 2. 非目标

- [ ] 不引入新的 `SubAgent` / `ChildAgent` 数据模型。
- [ ] 不放开同一 Autonomous Agent 多 open run 并发。
- [ ] 不新增站点专用工具、站点专用 worker、站点专用 fallback。
- [ ] 不把网页采集流程封装成黑盒“完整招聘流程工具”。
- [ ] 不改写当前主 skill 蒸馏主链的归属，只允许补充 scene 级证据摘要。

## 3. 当前代码真相

### 3.1 现有可复用对象

当前仓库已经存在一套可复用但未接入主链的 runtime scene 骨架：

- `TaskSpec`：任务规格 / 任务合同，定义“要做什么”。见 [models/domain.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/models/domain.py:1103)
- `ExecutionPlan`：执行方案，定义“准备怎么试跑、怎么验收”。见 [models/domain.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/models/domain.py:1125)
- `ExecutionEpisode`：某次真实执行实例，适合作为通用环境子上下文容器。见 [models/domain.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/models/domain.py:1142)
- `EnvironmentSnapshot`：执行过程中的环境快照，适合承载 `environment_kind / display_label / resource_locator / observed_entities / action_hints`。见 [models/domain.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/models/domain.py:1213)

### 3.2 现有主链

当前 Autonomous 主链仍然是：

- `POST /api/agents/autonomous/goals`
- `TaskQueueItem`
- `Heartbeat.run_once()`
- `AutonomousAgent.run_turn_from_envelope()`
- `AgentKernel.run_round()`
- `AgentTurnRecord / AgentRuntimeEvent / ApprovalItem / AgentRunCheckpoint`

scene context 相关对象目前没有真正接进这条主链。

### 3.3 当前 skill 蒸馏职责

当前 skill 蒸馏链是：

- `AutonomousAgent._maybe_record_trial_skill()`
- `build_skill_distill_review_payload()`
- `distill_skill_contract_from_run()`
- `LearningWriter.record_skill_draft()`

触发方和归属方都是主 `AutonomousAgent`，不是 `AgentKernel`，也不是 `ExecutionEpisode`。

## 4. 设计约束

本计划必须同时满足以下长期约束：

1. 主程序提供环境，不替 Agent 写死站点流程或业务状态机。见 [docs/specs/2026-04-20-agent-intelligence-boundary-and-capability-evolution.md](/Users/didi/AgentProjects/recruit-agent/docs/specs/2026-04-20-agent-intelligence-boundary-and-capability-evolution.md:19)
2. 网页执行细节属于子上下文 / 工具执行链路内部状态，不得直接上浮为主 Agent 历史自然语言。见 [docs/specs/2026-04-20-agent-intelligence-boundary-and-capability-evolution.md](/Users/didi/AgentProjects/recruit-agent/docs/specs/2026-04-20-agent-intelligence-boundary-and-capability-evolution.md:59)
3. Global Memory 不得记录 URL、DOM、按钮文案、临时页面布局等网页细节。见 [docs/specs/2026-04-20-autonomous-agent-runtime-constraints.md](/Users/didi/AgentProjects/recruit-agent/docs/specs/2026-04-20-autonomous-agent-runtime-constraints.md:38)
4. 网站不是固定集成，应被建模为 runtime scene。见 [.recruit-agent/prompts/tasks/runtime_task_compiler.md](/Users/didi/AgentProjects/recruit-agent/.recruit-agent/prompts/tasks/runtime_task_compiler.md:9)

## 5. 架构结论

### 5.1 本次采用 scene context，不先做完整 subagent

本次不引入新的 child agent 身份，而是将网页类低层执行收口为：

```text
AutonomousAgent（主 Agent）
  -> delegate_scene_context（通用委派）
  -> TaskSpec / ExecutionPlan（子上下文任务合同与方案）
  -> ExecutionEpisode（一次通用环境子上下文执行）
  -> EnvironmentSnapshot（若干环境快照）
  -> structured scene result（业务级摘要）
  -> AutonomousAgent（继续业务决策）
```

### 5.2 这 4 个对象的职责

- `TaskSpec`：scene 任务合同。它只定义“本次环境子任务要完成什么、成功标准是什么、需要哪些能力和审批”。
- `ExecutionPlan`：scene 执行方案。它只定义“这类 scene 任务如何试跑、有哪些检查点、依赖什么环境”。
- `ExecutionEpisode`：scene 子上下文执行容器。它承载这一次通用环境执行的 `observations / actions / result_summary / metrics / last_error`。
- `EnvironmentSnapshot`：scene 观察快照。它承载环境级结构化观察，不直接进入主 Agent 历史。

### 5.3 skill 蒸馏职责不变

scene context 只负责：

- 执行
- 留证
- 产出业务级摘要

主 skill 蒸馏继续由主 `AutonomousAgent -> Learning / Evolution` 负责；scene context 不自动蒸馏主 skill。

## 6. 实施步骤

### 6.1 Phase A：新增 SceneContextService

- [x] 新增 [services/backend/src/recruit_agent/services/scene_context.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/scene_context.py)
- [x] 在该 service 中定义一个通用 scene 请求合同，最小字段包括：
  - `instruction`
  - `success_criteria`
  - `output_contract`
  - `preferred_capabilities`
  - `environment_requirements`
  - `approval_policy`
- [x] SceneContextService 负责创建：
  - `TaskSpec`
  - `ExecutionPlan`
  - `ExecutionEpisode`
- [x] scene 执行过程中，负责写：
  - `ExecutionEpisode.observations`
  - `ExecutionEpisode.actions`
  - `ExecutionEpisode.result_summary`
  - `ExecutionEpisode.metrics`
  - `EnvironmentSnapshot`
- [x] SceneContextService 返回统一 `scene_result`，最小字段包括：
  - `status`
  - `summary`
  - `blockers`
  - `artifacts`
  - `metrics`
  - `episode_id`

### 6.2 Phase B：拆分主 Agent 与 scene context 的工具面

- [x] 在 [services/backend/src/recruit_agent/services/container.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/container.py:88) 中拆出两套 ToolRegistry：
  - `parent_agent_tool_registry`
  - `scene_context_tool_registry`
- [x] 主 Agent 只能看到：
  - 业务工具
  - memory / learning / queue 工具
  - `delegate_scene_context`
- [x] scene context 才能看到：
  - browser / browser-mcp / scene 观察类工具
  - 必要的审批相关工具
- [x] scene context 不得直接看到：
  - `read_memory`
  - `record_learning`
  - `invoke_skill`
  - `delegate_scene_context`
- [x] 不允许主 Agent 继续直接持有 raw browser 工具；这是“确保主 Agent 不亲自下场”的硬约束。

### 6.3 Phase C：新增通用委派工具

- [x] 在 [runtime/tools.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/runtime/tools.py:184) 新增 `delegate_scene_context`
- [x] 工具参数必须是 capability / contract 导向，不能是站点导向
- [x] `delegate_scene_context` 内部调用 `SceneContextService`
- [x] `MVP` 先同步执行并返回结构化 `scene_result`
- [ ] 本阶段不额外引入 `await_scene_context` / `read_scene_context_result`，避免扩大改动面

### 6.4 Phase D：scene context 复用现有 Kernel，但关闭长期记忆沉淀

- [x] scene context 复用现有 `AgentKernel`
- [x] 但必须传入独立：
  - `Observation`
  - `InputEnvelope`
  - `history_messages`
  - `ToolRegistry`
- [x] scene context 默认 `persist_memory=False`
- [x] scene context 默认不传 `MemoryService`，如需主 Agent 提供上下文，只允许通过结构化 request / contract 字段显式下发
- [x] scene context 默认不传 `learning_writer`
- [x] scene context 默认不写 Global Memory
- [x] scene context 默认不写 `summary_learning` / `record_learning`
- [x] scene context 默认不把原始网页轨迹写入主 `AgentRuntimeEvent` 自然语言历史

### 6.5 Phase E：把 scene result 接回 Autonomous 主链

- [x] 主 `AutonomousAgent` 保持当前主 turn / run / queue 控制面不变
- [x] 模型在合适时机通过 `delegate_scene_context` 发起 scene 子上下文
- [x] scene 返回后，主 Agent 只消费：
  - `summary`
  - `blockers`
  - `artifacts`
  - `metrics`
  - `episode_id`
- [x] 主 Agent 历史只记录业务级摘要，不记录 URL、DOM、按钮文案、selector、tab 轨迹

### 6.6 Phase F：保持并收紧 skill 蒸馏边界

- [x] 保持 [agents/autonomous.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/agents/autonomous.py:355) 的 `_maybe_record_trial_skill()` 为主 skill 蒸馏唯一触发入口
- [x] 不让 `ExecutionEpisode` 自动触发主 skill 蒸馏
- [ ] 可选增强：在 [services/evolution.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/evolution.py:52) 中补入 scene 级证据摘要，但只允许补：
  - `episode result_summary`
  - `episode metrics`
  - `blockers`
  - `artifacts`
- [ ] 禁止把以下字段直接喂给主 skill 蒸馏：
  - `resource_locator`
  - `display_label`
  - `observed_entities`
  - `action_hints`
  - 原始 DOM / 页面结构细节

### 6.7 Phase G：测试与验收

- [x] 为 `SceneContextService` 补单元测试
- [x] 为 `delegate_scene_context` 补工具层单元测试
- [x] 验证主 Agent 上下文不可见 raw browser 工具
- [x] 验证一次 scene 执行至少创建：
  - `TaskSpec`
  - `ExecutionPlan`
  - `ExecutionEpisode`
  - `EnvironmentSnapshot`
- [x] 验证主 Agent 历史不出现网页细节
- [x] 验证 Global Memory 不写入 scene 细节
- [x] 验证 skill 蒸馏仍由主 Autonomous run 成功后触发，而不是由 episode 自动触发

## 7. 允许修改的文件范围

本计划的最小建议改动范围如下：

- [x] 新增 [services/backend/src/recruit_agent/services/scene_context.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/scene_context.py)
- [x] 修改 [services/backend/src/recruit_agent/services/container.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/container.py:88)
- [x] 修改 [services/backend/src/recruit_agent/runtime/tools.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/runtime/tools.py:184)
- [x] 轻量修改 [services/backend/src/recruit_agent/agents/autonomous.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/agents/autonomous.py:47)
- [ ] 可选修改 [services/backend/src/recruit_agent/services/evolution.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/evolution.py:52)

以下对象本次只复用，不建议大改模型：

- [ ] [models/domain.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/models/domain.py:1103) 中的 `TaskSpec`
- [ ] [models/domain.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/models/domain.py:1125) 中的 `ExecutionPlan`
- [ ] [models/domain.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/models/domain.py:1142) 中的 `ExecutionEpisode`
- [ ] [models/domain.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/models/domain.py:1213) 中的 `EnvironmentSnapshot`

## 8. 完成判据

满足以下条件时，本计划可视为首轮完成：

1. Autonomous 主 Agent 不能再直接使用 raw browser / scene 工具。
2. 主 Agent 可以通过一个通用委派入口发起网页 scene 执行。
3. 一次 scene 执行能够在隔离容器中留下 `TaskSpec / ExecutionPlan / ExecutionEpisode / EnvironmentSnapshot`。
4. 主 Agent 最终拿到的是业务级摘要，而不是网页执行细节。
5. 主 Agent 历史与 Global Memory 不被 scene 细节污染。
6. 主 skill 蒸馏职责保持在 `AutonomousAgent -> Learning / Evolution`，未被下放到 scene context。

## 9. 后续扩展（不在本次范围）

以下能力明确留作后续阶段，不在本次 `MVP` 内：

- 真正一等公民的 `SubAgent` 身份与 child run / child turn 生命周期
- `await_scene_context` / `read_scene_context_result` 异步委派链
- scene context 自身的长期 scene skill 蒸馏
- 多 scene context 并行与 supervisor 汇总
- 更细粒度的 capability driver / runtime task compiler 接线
