# 通用自动化运行时重构 Plan

## 目标

把当前项目从“招聘 Agent”提升为“通用自然语言自动化执行系统”。招聘保留为第一个 domain pack，但不再作为产品核心模型。

本次 Plan 明确这 7 个产品原则：

1. 招聘只是一个 domain pack，不是产品本体。
2. Boss、GitHub、内网系统、桌面应用、第三方工具以及其他网站都属于运行时环境场景，不是预设产品流程。
3. 任何具体网站的“接入”都不是开发期固定交付项，而是运行时在 supervised trial + learning loop 中逐步学习、修正和沉淀的结果。
4. `Task Compiler` 是 `LLM-first structured semantic compiler`，负责把自然语言任务编译成结构化任务合同，不是关键词匹配或规则路由器。
5. 新工作流先由自然语言编译成 `TaskSpec` / `ExecutionPlan`，再通过 supervised trial run 验证，最后沉淀为可复用模板与 skill。
6. 运行时发现执行偏差后，可以提出 `WorkflowPatch`，但必须经过人工确认后才能生效。
7. Skill 是本地稳定能力单元，必须具备版本、健康检查、失效检测和可停用能力。

进一步明确：

- Boss、GitHub、内网系统、桌面应用、第三方工具以及其他网站都应被视为 runtime scenes，而不是开发期要逐个“接好”的固定集成清单。
- capability + environment model + supervised trial + learning loop 才是系统接触新场景的主路径。
- 文档或代码中如果出现 Boss、GitHub、新闻站等名称，应优先理解为示例场景或兼容命名，而不是产品架构对固定平台的绑定。

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
- `Planner / Replanner`
- `Supervised Trial & Learning`
- `ReAct-like Executor`

这四层是当前目标分层：

- `Task Compiler`：`LLM-first structured semantic compiler`，把自然语言任务编译成 `TaskSpec`，并补全目标、输入、约束、成功标准、审批点与能力偏好。
- `Planner / Replanner`：基于 `TaskSpec + EnvironmentSnapshot` 生成或修正 `ExecutionPlan`，负责运行时补步、分支、回退和局部重规划。
- `Supervised Trial & Learning`：承接试跑监督、episode 回放、patch 提议、skill/template 提炼、确认与治理。
- `ReAct-like Executor`：在能力边界内循环执行观察、推理、动作与结果提交；它是执行器，不是产品业务流程定义层。

当前实现约束：

- `Task Compiler` 必须优先走 LLM 结构化编译；启发式规则只能作为 provider 不可用、超时或输出非法时的兜底。
- `Planner / Replanner` 应优先消费 compiler 产出的 `step_outline`、`environment_requirements`、`checkpoints` 等结构化信号，而不是只依赖静态 domain seed。
- `ReAct-like Executor` 只负责执行期的 observe / reason / act loop，不承担自然语言任务理解和产品级流程定义职责。

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

这一层的职责不是为某个站点预写固定流程，而是让 runtime 在执行时回答：

- 当前环境是什么
- 当前可执行动作是什么
- 当前阻塞点和风险点是什么
- 当前是否需要进入 supervised trial、人工确认或 patch 提议

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

### Phase 2: Task Compiler + Planner / Replanner

- 新增自然语言任务入口
- 将用户输入经 `LLM-first structured semantic compiler` 编译为 `TaskSpec`
- compiler 失败时走启发式 fallback，但必须留下明确 compiler notes 与原因
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
- 让 recruiting 网站场景只作为 runtime environment example，而不是开发期固定集成目标
- 明确任何新网站、新系统、新工具的进入方式都是运行时试跑、观察、修正、沉淀，而不是开发期预设接入流程
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
- 不把任何具体网站作为开发期固定接入目标
- 不把“平台接入完成度”作为这一波的交付标准，交付标准聚焦在 runtime 能否学习、试跑、纠偏和沉淀

## 当前代码中的过渡实现

当前仓库里仍然存在一些为了兼容历史实现而保留的过渡形态。它们不代表最终架构边界：

- 仍保留的 recruiting 专用命名、页面、接口或兼容入口，只能理解为首个 domain pack 的遗留兼容层。
- 现有 workflow / scheduler / agent 相关实现中，仍有部分以固定流程或预定义节点为中心的执行链，这些属于向 `Planner / Replanner + ReAct-like Executor` 过渡中的中间状态。
- 部分站点名、平台名、兼容 tool 名称如果仍存在，也应理解为示例场景、兼容命名或 seed，而不是未来架构要求继续新增固定集成。
- 当前的 `TaskSpec`、trial、patch、skill 生命周期虽然已经落地，但 compiler / planner / learning loop 仍处于收敛期。
- 当前代码里仍允许存在 domain seed、兼容 tool 名称、历史字段名；这些只能作为过渡兼容层，不得再反向主导产品边界定义。

## 验收标准

第一波完成后，应满足：

- 仓库文档清楚说明“产品核心 vs domain pack”的边界
- 后端可以创建和读取 `TaskSpec`、`ExecutionPlan`、`ExecutionEpisode`、`WorkflowTemplate`、`WorkflowPatch`、`EnvironmentSnapshot`
- `Task Compiler` 在有 provider 时优先走 LLM 结构化编译，在无可用结果时回退启发式，并显式记录 fallback
- 可以标记 episode 为 `trial`
- 可以提交 workflow patch 并经过 approve/reject 流程
- 现有 recruiting 相关测试仍然通过

## 后续讨论项

- Browser capability 的统一抽象层
- Task compiler 的 prompt contract
- trial replay 的桌面端可视化
- skill health check 的主动执行器
- workflow template 与 domain pack 的版本治理
