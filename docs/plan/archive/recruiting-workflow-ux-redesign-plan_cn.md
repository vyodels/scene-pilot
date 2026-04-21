# 招聘工作流 UX 重设计方案

> Status: archived
> Supersedes: -
> Superseded by: docs/plan/archive/recruiting-workflow-ux-redesign-plan.md
> Distilled into: -
> Last reviewed against code: 2026-04-20
> Legacy path retained: docs/recruiting-workflow-ux-redesign-plan_cn.md

> 本文是针对当前 Recruit Agent 代码库的产品与 UX 方案。  
> 它并不是要团队移除 runtime 内核，而是要**把实现层语言藏到招聘业务友好的工作流背后**，让产品更像招聘工作台，而不是 agent 运维控制台。

## 为什么要写这份文档

这个仓库其实已经具备不少招聘产品的强基础能力：

- 候选人维度的结构化记录与隔离 memory
- JD 维度 memory
- 结构化 assessment、scorecard、review decision、stage event
- runtime checkpoint、approval、operator interaction
- 通过 MCP 接入真实环境，支持 Boss 类招聘站点的 sourcing 流程

但是当前桌面端产品仍然让人觉得别扭，因为 UI 表面更接近**内部 runtime 模型**，而不是**真实招聘工作流**。

结果就是产品虽然强大，但认知成本偏高：

- 用户脑子里想的是*候选人、岗位、待办队列、跟进、录用决策*
- 产品却仍然暴露了*goal、trace、graph、run、evolution artifact、compact action、MCP health*

这个错位就是当前 UX 的核心问题。

## 当前真实情况

### 已经做得不错的地方

1. **数据模型其实比产品表面更强。**
   后端已经把候选人生命周期数据建模得比较完整：`Candidate`、`CandidateStageEvent`、`CandidateAssessment`、`ResumeArtifact`、`CandidateScorecard`、`CandidateReviewDecision`、`TalentPoolSyncRecord`。
2. **候选人隔离是当前产品的真实优势。**
   Candidate memory、candidate thread、candidate state 都已经有清晰隔离。
3. **系统已经有一条真实的 sourcing -> evaluation -> follow-up 主骨架。**
   Boss 已经不再是硬编码 adapter，但 runtime 仍然可以通过 Browser MCP 和真实工具完成 sourcing 与资料查看。
4. **人工 checkpoint 已存在。**
   这对招聘场景是好事，因为沟通、淘汰、推进等动作本来就常常需要人工 review。

### 当前让人感觉不对劲的地方

1. **实现层概念泄漏到了默认 UI。**
   像 `goal`、`trace`、`graph`、`artifact`、`compact`、`operator interaction`、`adaptive runtime`、`MCP health` 这些词出现得太早。
2. **工作流被拆散到了太多一级页面。**
   候选人相关工作被分散在 `Dashboard`、`Workbench`、`Communications`、`Agent IM`、`Evolution`、`Recruit Agent` 多个页面。
3. **产品入口从配置和 runtime 控制出发，而不是从招聘待办出发。**
   招聘用户应该首先看到“我现在要处理什么”，而不是“run agent once”或者“start adaptive goal”。
4. **沟通页承载了过多职责。**
   Chat、状态流转、评估录入、简历事实、同步事实、审批都塞在一个页面里。
5. **阶段模型对日常操作来说太细了。**
   后端细颗粒度 stage 很有用，但 UI 应该优先呈现更简单的 macro-stage。
6. **视觉语言仍然像暗色技术控制台。**
   这和你希望的招聘方、Boss 风格的操作体验不匹配。

## 从当前实现中看到的证据

以下文件可以直接说明，为什么当前产品更像 runtime-first，而不是 recruiter-first：

- `apps/desktop/src/features/workspace/DesktopWorkspace.tsx` 在启动时几乎加载了所有领域对象，并把它们变成顶层 tab。
- `apps/desktop/src/features/workbench/WorkbenchView.tsx` 把 candidate progress、`run once`、`goal`、`replay`、`diagnostics`、`adaptive runtime`、queue depth、sync backlog 混在一起。
- `apps/desktop/src/features/communications/CommunicationsView.tsx` 把 chat、state transition、assessment、structured facts、runtime confirmation 混在一起。
- `apps/desktop/src/features/recruit-agent/RecruitAgentView.tsx` 把 blueprint、context policy、memory policy、原始编辑面板暴露得过于靠前。
- `services/backend/src/recruit_agent/api/routers/recruit_agent.py` 明明已经有很完整的 recruiting CRUD 能力，但它们在产品表面仍与 runtime 和治理接口混在一起。
- `apps/desktop/src/styles.css` 与 `apps/desktop/src/lib/theme.ts` 仍然保留暗色 console 风格，这与新的桌面设计规范相冲突。

## 产品北极星

产品应该给人的感觉是：

**一个面向招聘方的操作工作台，帮助用户把候选人从 sourcing 推进到决策，过程中有 AI 辅助、人工 checkpoint 和强结构化记录。**

而不是：

- 通用 agent 实验室
- runtime 调试器
- workflow 编译器 UI
- 一个顺便塞了候选人的治理控制台

## 建议的信息架构

保留当前顶层页面名称。**不要**在这轮方案里要求修改既有产品命名，除非后续有单独的命名决策。

这一轮重设计应聚焦于：

- 改页面职责
- 改信息密度与默认入口
- 改哪些内容是 primary、哪些是 advanced
- 在必要时增加缺失的业务页面

### 保留现有顶层名称，但重定义页面职责

| 当前页面 | 重设计后的建议职责 | 原因 |
|---|---|---|
| Dashboard | 面向今日待办的总览页 | 入口应从今日待办出发，而不是抽象指标 |
| Workbench | 主候选人 pipeline 工作台 | 主工作单元应该是候选人队列，而不是 runtime 操作 |
| Communications | 候选人 thread/cockpit 工作面 | 把沟通、简历、评估、下一步建议收束成一个招聘工作流页面 |
| Recruit Agent | 高级 agent 配置与策略区 | blueprint/context/memory 编辑不该处于日常默认流里 |
| Agent IM + Evolution | 高级 review 与治理区 | 把非候选人审批、skill 异常、演进提案合并成一个高级治理层 |
| Settings | 运营/管理设置页 | 保留，但明确它是运营/管理设置 |
| — | Import Center（新页面或内嵌模块） | 增加明确的 Boss/import intake 页面 |
| — | JD Workspace（新页面或内嵌模块） | 增加以岗位/JD 为中心的工作视角 |

### 导航原则

保留当前产品名称，如果这些名称已经定下，就不要强行改一级 tab 名。

更合理的做法是：

- `Dashboard` 的行为应当像 Today view
- `Workbench` 的行为应当像主 candidate pipeline
- `Communications` 的行为应当像 candidate cockpit
- `Recruit Agent` 应被视为高级配置区
- `Agent IM` 与 `Evolution` 在视觉和交互上应被下沉到高级治理工作区

`runtime diagnostics`、`MCP registry`、`trace/graph`、`memory editing` 等内容应该放在高级区域，不要作为默认日常主工作面。

## 建议的端到端招聘工作流

整个用户旅程要围绕真实招聘闭环重做。

### Step 1. Source 或导入候选人

**用户体验：**

- 打开 `Import Center`
- 选择 `Capture current Boss page`、`Import selected candidates` 或 `Import resume files`
- 在真正写入前，先看一个 staging 列表做确认

**系统职责：**

- 标准化原始来源数据
- 候选人去重
- 检测缺失字段
- 创建 import batch 与 import error
- 写入或更新 `Candidate`

### Step 2. AI 初筛与评分

**用户体验：**

- 新导入候选人进入 `Needs review`
- 每张候选人卡片直接展示：
  - AI fit score
  - top positive signals
  - top risks
  - missing information
  - recommended next action
- 用户可以批量通过、批量淘汰、批量推进到外联

**系统职责：**

- 创建 assessment
- 生成 scorecard 和决策支持信息
- 暴露 confidence 与 evidence
- 不要强迫用户去打开原始 diagnostics

### Step 3. 外联与简历获取

**用户体验：**

- 候选人进入 `Needs outreach` 或 `Waiting for resume`
- 系统提供按渠道感知的消息草稿和变量
- 首条消息或敏感消息仍然可以要求 review

**系统职责：**

- 生成草稿文案
- 在联系方式缺失时给出提醒
- 存储沟通历史
- 在发送/请求/回复后自动更新候选人状态

### Step 4. Candidate cockpit 审阅

**用户体验：**

每个候选人有一个固定的 cockpit 页面，分三块：

- 左：队列与候选人切换
- 中：沟通与时间线与最近动作
- 右：候选人 dossier、简历、评分摘要、下一步建议

这样就能替代现在那种在 workbench、communications、approvals、evaluation 之间来回跳转的体验。

### Step 5. 面试与决策处理

**用户体验：**

- 宏观阶段应当简化为：`New`、`Review`、`Outreach`、`Resume`、`Interview`、`Decision`、`Archived`
- 内部细 stage 仍可查看，但应退居二级
- reviewer 可以记录结构化 note 和明确 decision

**系统职责：**

- 将后端 micro-stage 映射到 macro-stage
- 保留 stage event 与结构化事实
- 让 AI 与人工决策在同一个叙事视图中可见

### Step 6. Sync、人才库与归档

**用户体验：**

- 导出与同步在业务上应该被展示为交付状态，而不是基础设施 backlog
- 用户应该看到的是“已发送 / 失败 / 重试中 / 目标位置”，而不是技术队列细节

**系统职责：**

- 把业务 sync record 与基础设施 retry queue 区分开
- 技术 backlog 默认只放在高级视图里

## 页面重设计建议

### 1. Dashboard

这个页面应该成为每日工作入口。

只展示：

- 待 review 的候选人
- 待回复的消息
- 新收到的简历
- 今天要处理的面试动作
- 被阻塞的事项
- 影响业务结果的 sync failure

不要默认展示：

- 原始 trace
- graph
- adaptive goal creation
- replay diagnostics
- MCP health

### 2. Workbench

它应当替代当前 `Workbench` 成为主工作面。

核心布局：

- 顶部：按 JD、source、stage、owner、score band 做筛选
- 中部：高密度候选人列表，可卡片可表格
- 右侧抽屉：快速预览与 next actions
- 批量操作：`Score`、`Move to outreach`、`Request resume`、`Reject`、`Assign`

关键原则：

**默认工作流必须是 queue-first、batch-friendly。**

### 3. Communications

这个页面应当吸收今天 `Communications` 页的大部分职责，但以更清晰的结构组织。

三栏布局：

- 左：候选人队列 / 当前列表
- 中：沟通流与活动时间线
- 右：候选人 dossier

右侧 dossier 应包含：

- summary
- source 与 JD
- contact state
- latest resume
- AI fit summary
- human review summary
- next recommended actions

状态流转和人工评估不应该继续以长面板散落出现，而应该改成结构化 action module。

### 4. Import Center

这是当前缺失的一等业务页面。

它应该承载：

- Boss 页面 capture
- import batch
- dedupe review
- parse failure
- incomplete profile
- 缺失联系方式或简历的数据提示

这个页面能让“从 sourcing 到写库”的链路对操作员清晰可见。

### 5. JD Workspace

当前系统很候选人中心，但招聘方也需要岗位中心视角。

每个 JD 页面应该能看见：

- hiring target 与进展
- 该 JD 的候选人 funnel
- calibration notes
- 针对该 JD 学到的 strong/weak signals
- 推荐的 sourcing gap

这也是把 JD memory 用业务语言重新包装的合适位置。

### 6. Agent IM + Evolution（高级区域）

把今天的 `Agent IM` 和 `Evolution` 合并成一个高级治理区。

保留在这里：

- 非候选人审批
- skill degradation
- prompt/playbook/memory policy patch
- MCP 或 provider 问题
- diagnostics 和 runtime health

把这些从默认招聘流程中移走。

### 7. Recruit Agent（高级区域）

当前的 `Recruit Agent` 页面应该被重新定义为高级管理页。

保留在这里：

- agent profile
- playbook editing
- context policy
- memory policy
- skill registry

默认用户不应该频繁进入这个页面。

## 术语使用建议

优先使用业务语言，其次才是实现语言。

这里的建议主要用于**描述文案、辅助提示、面板标题、空状态、CTA 文案、解释性文本**，不是要求强制修改已经定下的产品页面名。

| 当前术语 | 更好的默认解释性文案 |
|---|---|
| Goal | Task / Automation request |
| Run / Episode | AI activity / Processing record |
| Trace | Execution notes |
| Graph projection | Reasoning path |
| Evolution artifact | AI change proposal |
| Operator interaction | Review request |
| Compact memory | Refresh AI summary |
| Talent pool sync record | Export status |
| Workbench | candidate pipeline workspace |
| Communications | candidate cockpit / thread workspace |
| Recruit Agent | advanced agent strategy/configuration area |
| Agent IM | advanced review center / operator review area |

## 后端与 API 对齐建议

后端模型其实已经足够强，但 UI 需要更好的聚合接口和业务包装。

### 建议增加的 API 能力

1. 增加一个**candidate cockpit 聚合接口**。
   前端不应该再零散拼装 thread、assessment、scorecard、review decision、assignment、resume artifact、sync record；应由后端给一个 recruiter-facing aggregate payload。
2. 增加一个**基于队列的 home summary 接口**。
   直接返回 `needs_review`、`needs_reply`、`needs_resume`、`needs_schedule`、`blocked`、`export_failures`。
3. 增加**import batch 模型与 import queue 接口**。
   sourcing 步骤必须拥有一等可见性。
4. 在 API 层增加**macro-stage 映射**。
   后端保留 micro-stage，但 UI 获取更简单的宏观阶段。
5. 为每个 candidate 增加**next_action** 或 **action queue** 汇总。
   UI 不应该每次都靠一堆底层字段反推出可操作性。
6. 在默认 UI payload 里分离**业务 sync 状态**与**技术 retry backlog**。

### 建议的前端数据加载方式调整

1. 不要再在 workspace 启动时加载几乎所有领域对象。
2. 从一个全局 polling-heavy workspace，改为 page-scoped data queries。
3. 使用 aggregate endpoint，减少产品层对存储细节的耦合。
4. diagnostics 一律 lazy-load，并限制在高级视图中。

## UI 与交互建议

这轮改造应与 `apps/desktop/DESIGN_GUIDELINES.md` 对齐。

### 视觉方向

- 从暗色 operator console，切到浅色 recruiter workspace
- 以 list/detail 与 queue/cockpit 为主布局
- 弱化基础设施、JSON、原始控制面板的视觉存在感
- 让主操作一眼可见：review、message、request resume、progress、reject、assign

### 交互方向

- 默认支持批量操作
- 优先用侧栏抽屉与局部面板，减少整页切换
- 候选人相关审批尽量内联到业务流里
- 技术治理统一进高级区域
- 每个主页面都明确展示“下一步该做什么”

## Agent 提示词架构重设计

下一层重设计不应该只改 UI，也应该重定义 **agent 的 prompt 契约**。

从当前实现看，prompt 链路仍然明显偏向执行器视角：

- `PromptBuilder` 会拼接 `base/identity.md`、`base/behavior_rules.md`、`base/output_format.md`，以及像 `tasks/scale_execution.md` 这样的 task prompt
- `ContextAssemblerService` 会注入 candidate progress、recent messages、candidate memory、job memory、global memory、assessments、scorecards、review decisions、approval context、platform context
- `AgentLoop` 再通过 `record_observation`、`advance_plan_step`、`request_replan`、`request_human_checkpoint`、`submit_result` 这些工具执行一步步循环

这在技术上没问题，但它把模型框定得更像一个 **runtime executor**，而不是一个 **持续存在的招聘操作员**。

### Prompt 重设计目标

目标 prompt 应该默认假设：系统里存在一个长期运行的招聘 agent，会持续处理招聘工作。

这个 agent 不是单纯的：

- tool caller
- browser scene executor
- goal runner

它首先应该被定义为：

- recruiting operator
- candidate progression manager
- JD-aware evaluator
- communication drafter
- human-review-aware automation layer
- 能沉淀招聘启发式经验的 learning system

### 推荐的 prompt 分层

这一节刻意先不考虑当前 `system / user / assistant` 的消息拼装细节，而是把它视为一个逻辑上的 prompt 包。

#### Layer 1 — 持续性的招聘 charter

这是 agent 的长期身份层。

应该定义：

- agent 的存在目的，是帮助招聘方持续推进候选人直至形成招聘决策
- 产品的主单位是 **candidate workflow**，不是 runtime task
- agent 需要优化 recruiter throughput、candidate quality、低认知负担
- agent 应优先写入 durable state，而不是只生成临时对话
- agent 必须保持 candidate isolation 与 JD isolation

#### Layer 2 — 招聘 operating model

这一层解释业务闭环。

agent 应该理解，标准招聘流程是：

1. source 或 import candidate
2. inspect profile 并收集 evidence
3. triage 或评分
4. 决定下一步动作
5. 必要时 draft outreach 或 request resume
6. 处理 reply 与 resume
7. 推荐 progression、rejection、cooldown 或 interview
8. 持续写入 structured facts，并保持 queues 最新

#### Layer 3 — Scope contract

prompt 里必须明确什么能共享、什么不能共享。

规则：

- 候选人事实只能是 candidate-local
- JD 偏好只能是 JD-local
- global memory 可以保存可复用 heuristics，但不能保存候选人私有事实
- candidate communication thread 是一个 scoped working surface，不是一个能跨候选人得出结论的地方

#### Layer 4 — Work selection contract

因为这是一个持续性 agent，它需要知道如何选择工作。

默认优先级应为：

1. 被阻塞、需要人工 review 或回复的 candidate
2. 新进入队列、需要 triage 的 candidate
3. waiting for outreach 的 candidate
4. waiting for resume follow-up 的 candidate
5. waiting for evaluation 或 progression 的 candidate
6. strategy distillation 与 learning task
7. 非业务类 runtime / governance 任务，仅在它们阻塞业务时才处理

#### Layer 5 — Action policy contract

agent 必须区分哪些动作可以直接做，哪些必须 review。

默认直接允许：

- 读页面和文件
- inspect candidate details
- summarize evidence
- create draft recommendation
- 在策略允许下更新结构化内部状态

必须 review 或 confirm：

- outbound candidate communication
- destructive status change
- export 与 upload
- 证据不足时的推进动作
- 会影响多个 candidate 或外部系统的动作

#### Layer 6 — Candidate thread contract

当 agent 进入某个 candidate thread 时，它应从全局招聘姿态切换到 **单候选人执行姿态**。

也就是说：

- 只聚焦这一个 candidate
- 只使用该 candidate 的 thread、memory、stage history、resume artifact、assessment 与 JD context
- 始终维护清晰的 current status、missing facts、risks、next recommended action
- 不要把 thread 当成一个独立员工，也不要把它视为一个独立长期 agent

#### Layer 7 — Learning 与 distillation contract

agent 应该持续沉淀招聘经验，但必须写到正确层级。

- candidate-specific learning -> candidate memory
- JD-specific screening pattern -> job memory
- reusable heuristic -> global memory 或 strategy artifact
- prompt/playbook change -> reviewable AI change proposal

#### Layer 8 — Output contract

每一轮 agent cycle 都应该产出业务可理解的结果，而不是 runtime 原生结果。

推荐输出结构：

- what changed
- what evidence matters
- what the candidate/JD status is now
- what next action is recommended
- whether human review is required
- what was recorded to structured state

### 推荐的主招聘 agent prompt

长期存在的 agent prompt 建议围绕下面这个契约设计。

**Identity：**
一个持续存在的 recruiting operator，会不断处理 candidate work、保持队列最新、并通过结构化证据与 review-aware action 与招聘方协作。

**Primary objective：**
以高信号质量、清晰 next action、最小认知负担，把 candidate 推过 hiring workflow。

**Operating principles：**

1. 用 candidate workflow 思考，不用 runtime machinery 思考。
2. 优先写 durable structured update，而不是自由叙述。
3. 保持 candidate fact 隔离。
4. 保持 JD preference 隔离。
5. 在 risky communication、export、uncertain progression 前先升级 review。
6. 如果 evidence 不足，要明确标记 uncertainty，而不是伪造 confidence。
7. 让 recruiter 的 next action 永远清晰。
8. 只有在证据足够时才沉淀 reusable heuristic。

**Default decision loop：**

1. 识别当前最需要处理的 queue 或 candidate
2. 检查当前 structured state 与最新 evidence
3. 判断问题属于 sourcing、evaluation、communication、progression 还是 exception handling
4. 执行最小且有价值的动作
5. 写回 structured facts、decision、next action
6. 如果策略要求，则请求 review
7. 只有在结果 durable 时才推进 candidate

**Success definition：**

- 更多 qualified candidate 被顺畅推进
- 更少 candidate 因 owner 不清晰而卡住
- recruiter 用更少点击理解发生了什么
- 业务状态比对话文本更准确

### 推荐的 candidate thread prompt

每个 candidate thread 也应该有自己单独的 scoped operating contract。

**Thread purpose：**
代表某个 candidate 的局部工作上下文，用于 communication、resume handling、evaluation 与 progression。

**Thread rules：**

- 不要跨 candidate 推理
- 不要引入无关 JD preference
- 动作前先总结这个 candidate 当前已知状态
- 明确追踪：contact state、resume state、evaluation state、decision state、next action、blocker
- draft communication 时，优先考虑 recruiter intent、candidate clarity 与可 review 性
- evidence 不完整时，要标记缺失字段，不要过早推进

**Thread output preference：**

- candidate status now
- evidence added
- drafted message or proposed action
- blocker or review requirement
- next recommended step

### 当前代码里的 agent 工作流

当前实现其实已经形成了一条完整 runtime loop，只是它更偏 runtime-centric，而不是 recruiter-centric。

#### 当前循环

1. 任务通过 `AgentControlService.enqueue_task` 入队
2. scheduler 取任务并调用 agent runner
3. 构建 runtime session：
   - 如果是 candidate-scoped task，就加载 candidate session
   - 根据 adaptive stage 选择 skill context
   - 挂载 platform context
4. `ContextAssemblerService` 构建 `context_manifest`
5. `PromptBuilder` 为当前 task 或 managed execution step 构建 prompt 包
6. `AgentLoop` 带工具执行模型循环
7. 模型可以记录 observation、推进 step、请求 replan、请求 human checkpoint、或者提交 result
8. result artifact 会被持久化：
   - candidate session update
   - communication log
   - stage event
   - assessment 或 learning artifact
   - blocked 时生成 operator interaction
9. runtime 还可能自动排一个 follow-up stage，通常最后走到 `strategy_distill`

#### 当前 adaptive stages

当前 adaptive stage 集合是：

- `goal_intake`
- `exploration_trial`
- `candidate_discovery`
- `candidate_probe`
- `candidate_outreach`
- `resume_collection`
- `candidate_scoring`
- `strategy_distill`
- `scale_execution`
- `candidate_archive`

#### 当前默认 playbook 形状

当前默认招聘 blueprint 的逻辑大致是：

- `candidate_discovery` -> `candidate_probe`
- `candidate_probe` -> `candidate_outreach` 或 `strategy_distill`
- `candidate_outreach` -> `resume_collection`
- `resume_collection` -> `candidate_scoring`
- `candidate_scoring` -> `scale_execution` 或 `strategy_distill`

这作为技术骨架已经足够好，但产品层仍然需要进一步简化包装。

### 工作流草图

```text
[Recruit Agent Profile / Playbook / Policy]
[招聘 Agent 配置 / Playbook / 策略]
                  |
                  v
        [Primary Agent Session]
        [主 Agent 会话]
                  |
                  v
          [Task Queue / Scheduler]
          [任务队列 / 调度器]
                  |
                  v
 [Agent Run: agent lane or candidate lane]
 [一次执行单元：全局 lane 或候选人 lane]
                  |
                  v
 [Context Assembler builds context_manifest]
 [上下文装配器生成 context_manifest]
                  |
                  v
[AgentLoop + Tools + Scene Evidence + Skill Context]
[AgentLoop + 工具 + 场景证据 + Skill 上下文]
                  |
      +-----------+-----------+
      |                       |
      v                       v
 [structured result]     [human checkpoint]
 [结构化结果]            [人工检查点 / 待确认]
      |                       |
      v                       v
[persist business state] [approval / operator interaction]
[写回业务状态]           [审批 / 操作员介入]
      |
      v
[follow-up stage or thread update]
[后续阶段任务 / 线程状态更新]
      |
      v
[queues refreshed for next recruiting action]
[刷新队列，进入下一轮招聘动作]
```

**中文说明：**

- `Primary Agent Session`：长期存在的主 Agent 会话，不是一次性 task。
- `Task Queue / Scheduler`：决定当前先处理哪个任务、哪个候选人。
- `agent lane`：处理全局治理、审批、非候选人类任务。
- `candidate lane`：处理单个候选人的 sourcing / 沟通 / 简历 / 评估 / 推进。
- `context_manifest`：本轮执行真正喂给模型的上下文切片，不等于把所有 memory 全塞进去。
- `human checkpoint`：需要人工确认、接管、纠偏时的暂停点。
- `follow-up stage`：当前阶段完成后自动衍生出的下一阶段任务。

### Agent 与 candidate thread 的关系

这里最重要的一点是：

**candidate thread 不是 child agent。**

它只是一个 **candidate-scoped operating surface 和 record aggregate**。

长期存在的 `Recruit Agent` 仍然是唯一的主 agent 身份。

#### 关系草图

```text
                    [Persistent Recruit Agent]
                    [持续存在的主招聘 Agent]
                              |
        +---------------------+---------------------+
        |                     |                     |
        v                     v                     v
 [Candidate A Thread]   [Candidate B Thread]  [Candidate C Thread]
 [候选人 A 线程]         [候选人 B 线程]        [候选人 C 线程]
        |                     |                     |
        v                     v                     v
   [local state only]    [local state only]   [local state only]
   [仅保存本候选人局部状态] [仅保存本候选人局部状态] [仅保存本候选人局部状态]
```

**中文说明：**

- `Persistent Recruit Agent`：系统里唯一长期存在的主 Agent 身份。
- `Candidate Thread`：某个候选人的局部工作面，不是独立子 Agent。
- `local state only`：线程内只允许持有该候选人的沟通、简历、评估、阶段与待办上下文。
- 主 Agent 可以跨候选人调度工作；单个 Thread 不可以跨候选人推理。
- Thread 更像“候选人 dossier + conversation + action surface”，不是“候选人专属员工”。

#### 职责边界

| Surface | Responsibilities | Must not do |
|---|---|---|
| Persistent Recruit Agent | 选工作、应用招聘策略、决定 next action、编排 sourcing/evaluation/outreach、请求 review、沉淀可复用经验 | 把 candidate-private fact 写进 global scope、把 runtime diagnostics 当成产品目标 |
| Candidate Thread | 持有单个 candidate 的 communication log、resume facts、stage events、assessments、sync records、pending review、next action context | 变成独立长期 agent、跨多个 candidate 推理、自主修改全局策略 |
| Recruiter / operator | 审批敏感动作、纠偏策略、处理边缘案例、决定何时 override、校准 hiring quality | 微操所有低风险只读步骤 |

### 这个边界对产品的意义

这个边界应该直接塑造 UI 和 prompt 设计：

1. **agent** 应该更像背景中的 operator 与 queue manager
2. **candidate thread** 应该更像 scoped dossier + conversation + action surface
3. 高级 runtime / governance 应该始终藏在业务流之后
4. 面向 recruiter 的文案应该谈 candidate progress 与 next step，而不是 traces 和 graphs

## 落地阶段建议

### Phase 1 — 页面职责与语言重置

- 保留现有一级 tab 名称
- 把高级 runtime / 治理页面收进 advanced mode 或高级分区
- 前端增加 macro-stage 标签
- 在默认页面里替换“run once / goal / replay”等文案

### Phase 2 — 可执行队列与 Workbench 聚焦

- 把 Dashboard 重做为 actionable queue 入口
- 把 Workbench 重做为主候选人 pipeline 工作台，但保留现有名称
- 增加 batch actions 与 role/JD filters
- 增加 recruiter-friendly 的 scoring cards

### Phase 3 — candidate cockpit 与沟通页重写

- 把 communications 重做成 cockpit
- 把 conversation、evaluation、dossier 统一到一个更顺畅的结构里
- 简化状态流转 UX
- 增加更好的 outreach composer 与 approval 流

### Phase 4 — import center 与 JD workspace

- 增加 sourcing/import center
- 增加 import batch 可见性、dedupe review、failure handling
- 增加 JD workspace 与岗位 calibration 页面

### Phase 5 — 高级 AI review center

- 合并 Agent IM 与 Evolution
- 把 runtime diagnostics、provider health、MCP management、AI change proposal 统一放到高级导航里

## 成功标准

如果满足以下条件，就说明这轮改造是成功的：

1. 用户打开应用 10 秒内就能判断“我现在该做什么”
2. sourcing -> scoring -> outreach -> resume handling 变成一条可见、可引导的流程
3. 候选人相关工作主要集中在 2-3 个页面，而不是 5-6 个
4. 高级 AI 控制面仍然存在，但不再主导日常工作流
5. 产品语言听起来像招聘运营，而不是 runtime 工程

## 非目标

这份方案**不建议**：

- 移除 runtime 内核
- 删除 trace、graph、checkpoint、governance 能力
- 把所有高级 AI 控制面压平成一个过于简单的产品

目标不是降低能力，而是**分层更合理**：

- 默认 recruiter-first
- 需要时再进入 AI governance
- runtime 细节只有在真正帮助当前任务时才出现
