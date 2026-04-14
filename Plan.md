# 通用自动化运行时重构 Plan

## 目标

把当前项目从“招聘 Agent”提升为“通用自然语言自动化执行系统”。招聘保留为第一个 domain pack，但不再作为产品核心模型。

本次 Plan 明确这 5 个产品原则：

1. 招聘只是一个 domain pack，不是产品本体。
2. Boss 之类的网站接入是运行时环境状态与 capability，不是预设产品流程。
3. 新工作流先由自然语言编译成 `TaskSpec` / `ExecutionPlan`，再通过 supervised trial run 验证，最后沉淀为可复用模板与 skill。
4. 运行时发现执行偏差后，可以提出 `WorkflowPatch`，但必须经过人工确认后才能生效。
5. Skill 是本地稳定能力单元，必须具备版本、健康检查、失效检测和可停用能力。

## 新系统边界

产品核心负责：

- 任务理解与结构化编译
- 运行时环境理解
- 动态计划生成与执行
- supervised trial run 与回放
- 审批、确认、恢复与重规划
- 自学习产物沉淀与治理

domain pack 负责：

- 某类任务的 prompt、模板、策略偏好
- 某类网站或工具的环境识别规则
- 某些可复用 skill 的初始种子

Recruiting、market news、web research、GitHub trend 等都属于 domain pack。

## 目标架构

### 1. Core Runtime

- `Task Compiler`
- `Execution Planner`
- `Plan Runner`
- `Episode Recorder`
- `Patch Proposal Engine`
- `Learning Loop`

### 2. Capability Drivers

- Browser
- Search
- HTTP/API
- Filesystem
- Document
- Local Command

### 3. Environment Model

- `EnvironmentSnapshot`
- `ObservedEntity`
- `ActionAffordance`
- 页面/网站/应用状态识别

### 4. Knowledge and Reuse

- `Skill`
- `WorkflowTemplate`
- `WorkflowPatch`
- `AgentLearning`

### 5. Desktop Control Plane

- task authoring
- trial supervision
- approvals
- replay and diagnostics
- skill/template governance

## 分阶段落地

### Phase 1: Runtime Foundation

- 新增通用 runtime 数据实体：
  - `TaskSpec`
  - `ExecutionPlan`
  - `ExecutionEpisode`
  - `WorkflowTemplate`
  - `WorkflowPatch`
  - `EnvironmentSnapshot`
- 保留现有 recruiting 数据模型与 API
- 将 recruiting 视为首个 domain pack，而不是主架构

### Phase 2: Task Compiler + Plan Runner

- 新增自然语言任务入口
- 将用户输入编译为 `TaskSpec`
- 根据 `TaskSpec + EnvironmentSnapshot` 生成 `ExecutionPlan`
- 把现有 workflow engine 升级为 plan runner
- 支持 `trial` / `production` / `recovery` 执行模式

### Phase 3: Supervised Trial Run

- 新工作流默认进入 supervised trial run
- 记录完整 episode、观察、动作、失败点、人工确认点
- 提供一次试跑后的结果评估
- 允许用户确认“这个 workflow 可以正式使用”

### Phase 4: Learning Loop

- 从 episode 中提炼 skill draft
- 从稳定执行模式中提炼 workflow template
- 当执行偏离时产出 workflow patch
- 审批通过后激活模板或 patch
- 持续更新 skill 健康状态

### Phase 5: Capability Generalization

- 把平台适配层改造成 capability + environment adapter
- recruiting/Boss 迁移为 runtime capability 的一个实例
- 增加更多 domain pack 示例：
  - 市场新闻
  - 全网工具研究
  - GitHub 热点抓取

### Phase 6: Production Hardening

- 持久化队列与恢复
- 更完整的 replay / observability
- 打包与发布链路收口
- 可选内网同步协议稳定化

## 第一波重构范围

当前开发波次只做下面这些：

- 新增通用 runtime 持久化实体和 schema
- 提供最小可用 runtime API：
  - task definitions
  - trial episodes
  - workflow patch review scaffolding
- 重写 README 和架构文档
- 不移除现有 recruiting API 和运行链
- 不立即实现 Boss 真实线上接入

## 验收标准

第一波完成后，应满足：

- 仓库文档清楚说明“产品核心 vs domain pack”的边界
- 后端可以创建和读取 `TaskSpec`、`ExecutionPlan`、`ExecutionEpisode`、`WorkflowTemplate`、`WorkflowPatch`、`EnvironmentSnapshot`
- 可以标记 episode 为 `trial`
- 可以提交 workflow patch 并经过 approve/reject 流程
- 现有 recruiting 相关测试仍然通过

## 后续讨论项

- Browser capability 的统一抽象层
- Task compiler 的 prompt contract
- trial replay 的桌面端可视化
- skill health check 的主动执行器
- workflow template 与 domain pack 的版本治理
