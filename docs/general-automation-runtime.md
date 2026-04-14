# 通用自动化运行时架构设计

## 1. 产品定义

这个项目的目标不是“招聘软件”，而是一个能够通过自然语言替用户完成复杂电脑操作的通用自动化运行时。

招聘只是一个 domain pack，是第一组被实现的自动化能力。它不是产品核心。

这意味着：

- recruiting 只是 runtime 上的一组任务模板、skills、站点启发式和审批策略
- Boss 之类的网站接入，只是运行时环境中的能力与状态，不是产品预设流程
- 同一套系统也可以支持市场新闻收集、工具研究、GitHub 热点抓取等任务

## 2. 核心设计原则

### Domain Packs, Not Product Flows

产品核心不直接定义“招聘流程”“Boss 流程”。  
产品核心只提供任务编译、环境理解、计划执行、试跑监督、学习闭环和治理能力。

domain pack 负责：

- 任务偏好与 prompt
- 初始模板
- 局部 skills
- 环境识别启发式

### Runtime State Over Fixed Integrations

Boss、GitHub、新闻站、工具网站等都属于运行时环境。

系统在执行时关心的是：

- 当前环境是什么
- 当前能做什么动作
- 当前离目标还有什么差距
- 当前是否发生了偏差或阻塞

所以“接入网站”不是固定工作流开发，而是为 runtime 提供 capability 和 environment observation。

### Natural Language First

新工作流的起点不是人工编排固定 DAG，而是自然语言任务。

系统先把自然语言编译为：

- `TaskSpec`
- `ExecutionPlan`

然后再进入试跑和收敛过程。

### Supervised Before Promotion

一个新工作流在第一次生成后，不应直接进入生产执行。

标准流程应该是：

1. 自然语言任务输入
2. 编译出 `TaskSpec`
3. 生成 `ExecutionPlan`
4. 运行 supervised trial run
5. 用户全程观察关键动作、结果和偏差
6. 用户确认后，才把结果提升为可复用模板与 skill

### Local Stable Skills

Skill 不是整条业务流程，而是本地稳定能力单元。

Skill 应该具备：

- 明确输入输出
- 版本与状态
- 适用环境
- 健康检查
- 失效检测
- 停用与降级能力

## 3. 核心运行时对象

### `TaskSpec`

自然语言任务编译后的标准化任务定义。

建议包含：

- `goal`
- `inputs`
- `constraints`
- `success_criteria`
- `approval_policy`
- `output_contract`
- `preferred_domains`
- `preferred_capabilities`

### `ExecutionPlan`

根据 `TaskSpec + EnvironmentSnapshot` 生成的运行时执行计划。

特点：

- 支持步骤动态补全
- 支持条件分支
- 支持人工确认点
- 支持失败回退与重规划
- 支持 `trial` / `production` / `recovery`

### `ExecutionEpisode`

一次执行过程的记录容器。

应记录：

- 运行模式
- 关联任务与计划
- 实际观察
- 实际动作
- 人工干预
- 结果状态
- 偏差与失败原因

Episode 是学习和回放的基础。

### `WorkflowTemplate`

经过验证、可复用的任务模板。

它不是最初输入，而是从试跑和正式执行中沉淀出来的产物。

### `WorkflowPatch`

当 runtime 发现“当前模板与实际环境不再一致”时，提出的更新建议。

关键原则：

- runtime 可以提议 patch
- patch 不能自动生效
- 必须进入审批或确认流
- 确认后才更新模板或 skill 绑定

### `EnvironmentSnapshot`

当前运行环境的结构化观测结果。

例如浏览器环境中可以包括：

- url
- title
- 页面类型推断
- 关键实体
- 可行动作
- 风控/验证码/空结果状态

## 4. 系统分层

### Core Runtime

- `Task Compiler`
- `Execution Planner`
- `Plan Runner`
- `Episode Recorder`
- `Patch Proposal Engine`
- `Learning Loop`

### Capability Drivers

- Browser capability
- Search capability
- HTTP/API capability
- Filesystem capability
- Document capability
- Local command capability

### Domain Packs

- recruiting
- market-news
- web-research
- github-trends

### Control Plane

- task authoring
- trial supervision
- approvals
- replay
- template/skill governance

## 5. 标准执行闭环

1. 用户输入自然语言任务
2. `Task Compiler` 生成 `TaskSpec`
3. runtime 观察环境，形成 `EnvironmentSnapshot`
4. `Execution Planner` 生成 `ExecutionPlan`
5. 系统以 supervised trial mode 运行一次
6. 用户确认结果和过程
7. 系统将稳定部分沉淀为 `WorkflowTemplate` / `Skill`
8. 正式执行时优先复用模板和 skill
9. 执行偏差出现时生成 `WorkflowPatch`
10. patch 经人工确认后更新模板
11. health check 持续淘汰失效 skill

## 6. Recruiting 在新架构中的位置

Recruiting 是首个 domain pack。

它可以提供：

- candidate sourcing / screening / scoring 相关 prompt
- candidate-specific templates
- recruiting-specific skill seeds
- Boss 等站点的环境识别启发式

但 recruiting 不再定义整个产品的数据模型和控制面。

## 7. 第一波重构重点

本次先做：

- 通用 runtime 数据模型
- 最小可用 runtime API
- 文档和定位重写

本次不做：

- Boss 真实线上接入
- 所有旧 recruiting 页面改名/迁移
- 完整 task compiler 与 browser capability 实战能力

## 8. 设计约束

- 本地优先：SQLite 仍是事实源
- 审批门控：patch、skill 激活、敏感动作都要过人
- 渐进重构：现有 recruiting domain pack 先兼容保留
- 先增量，后替换：先把通用 runtime 层加出来，再逐步把 recruiting 从核心层剥离
