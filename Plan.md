# Recruit Agent 重构 Plan

## 目标

把当前项目从“早期执行控制台”收束为“招聘场景优先的 `Recruit Agent`”。

系统仍可保留未来扩展多个内置 agent 的能力，但当前版本只把招聘 agent 做深做透，不再以通用 workflow/runtime 产品叙事主导信息架构、数据模型和页面设计。

## 当前产品方向

新的产品主语是：

- `Recruit Agent`
- 候选人进度管理
- 候选人沟通与人工确认
- 招聘 agent 的 workflow、memory、skill、自学习与演进治理

不是：

- 通用 task compiler 产品
- 以编排为中心的控制台
- 以执行实例为中心的工作台
- 固定站点集成 backlog

## 核心原则

1. 顶层产品对象是 `招聘 Agent`，不是 `工作流`。
2. 工作流仍然存在，但它是招聘 agent 的内部执行编排，不再是顶层导航中心。
3. 不再对用户暴露“执行实例”概念；底层可保留执行记录，但用户看到的是 agent 的执行结果和候选人进度。
4. `Candidate Memory` 必须按候选人严格隔离，读写时只允许访问当前候选人的记忆，防止串人。
5. `Job / JD Memory` 必须按 JD 严格隔离，不能跨岗位混用筛选偏好、总结和上下文。
6. `Agent Global Memory` 允许跨候选人、跨 JD 存在，但只能保存全局策略、经验、压缩总结和通用经验，不能反向污染单个候选人事实。
7. 记忆、提示词、角色定位、职责、口吻、边界、成功标准、禁止事项、上下文压缩策略、memory 压缩策略、skill 配置都必须对用户外露且可编辑。
8. memory 与 skill 使用标准化结构，不允许仅依赖自由文本。
9. 运行时的“审批”应轻量化为 `IM 内联确认 / 介入 / 接管 / 教学 + 可读操作记录`，而不是厚重的审批流：
   - 运行时交互：候选人沟通、待回复、待人工确认、纠偏、人工接管
   - 演进治理：skill 失效、workflow patch、prompt patch、memory policy patch 的采纳与应用
   - 默认应优先在 `Agent IM` 或 `Candidate IM` 中就地完成确认，不要求用户频繁跳转到独立审批中心
10. 候选人运行时确认界面必须是会话化、聊天式的操作台，按候选人维度严格隔离。
11. 本地数据库是当前阶段的事实源；内网上传暂不作为主链路，后续可以通过 MCP 或固定 skill/API 在特定节点执行。
12. 自动压缩必须支持：
   - 手动触发
   - 按策略触发
   - 上下文长度超过 `1m` 自动 compact

## 顶层对象模型

### 1. RecruitAgentProfile

招聘 agent 的外露配置对象，包含：

- 名称、身份、定位
- 职责、边界、禁止事项
- 成功标准、失败定义
- system prompt
- few-shot / prompt assets
- 语气与沟通风格
- 审批策略
- 上下文压缩策略
- memory 压缩策略
- 默认 workflow 绑定
- 默认 dashboard 配置

### 2. RecruitAgentWorkflow

招聘 agent 的内部执行编排图。

初始预设节点采用当前自适应执行阶段：

- `candidate_discovery`
- `candidate_probe`
- `candidate_outreach`
- `resume_collection`
- `candidate_scoring`
- `strategy_distill`
- `scale_execution`
- `candidate_archive`

这套 workflow 可以：

- 可视化查看
- 人工编辑
- 由 LLM 提议 patch
- 在审批后进化

### 3. Candidate

候选人主档案，属于结构化事实源。包含：

- 基本资料
- 来源平台
- 当前阶段
- 简历与评分
- 沟通状态
- 最近动作
- 负责 agent
- 关联 JD

### 4. Candidate Memory

严格按候选人隔离的长期记忆对象。

要求：

- 候选人一人一份主 memory
- 每次处理某候选人时，只能装载该候选人的 memory
- 不允许跨候选人共享候选人级事实
- 支持压缩历史和版本记录

建议结构：

- `identity_summary`
- `facts`
- `interaction_summary`
- `risk_flags`
- `open_questions`
- `recommended_next_actions`
- `evidence_refs`
- `memory_policy_version`

### 5. Job / JD Memory

严格按 JD 隔离的长期记忆对象。

建议结构：

- `screening_preferences`
- `strong_positive_signals`
- `common_reject_reasons`
- `communication_notes`
- `quality_thresholds`
- `historical_patterns`
- `memory_policy_version`

### 6. Agent Global Memory

招聘 agent 的全局经验记忆。

允许保存：

- 通用筛选经验
- 常见失误与风险
- 高效检索和评分策略
- 沟通模板优化建议
- 记忆压缩经验

不允许保存：

- 某个具体候选人的专属事实
- 某个 JD 的专属筛选结论

### 7. Skill

skill 是招聘 agent 的可复用能力单元，必须标准化并支持用户管理。

要求：

- 可查看
- 可修改
- 可删除
- 可审批
- 可健康检查
- 可绑定 workflow 节点或能力类别

建议结构：

- `skill_id`
- `name`
- `description`
- `category`
- `version`
- `status`
- `input_schema`
- `output_schema`
- `strategy`
- `execution_hints`
- `applicability`
- `risk_level`
- `health_check_config`
- `metadata`

### 8. Candidate Thread / Runtime Inbox

运行时沟通与待确认的会话对象，按候选人隔离。

建议结构：

- 候选人标识
- 会话 tab
- 消息流
- 草拟回复
- 待确认动作
- 已发送/待发送状态
- 人工接管记录

### 9. Agent Run

底层执行记录对象。

它是实现层概念，不在产品顶层强调为“执行实例”，但技术上必须存在，用于：

- 审计
- 回放
- 结果归档
- 学习产物挂载
- 失败恢复

### 10. Evolution Artifacts

自学习与演进的产物：

- `SkillDraft`
- `WorkflowPatch`
- `PromptPatch`
- `MemoryPolicyPatch`

这类产物统一进入“演进审批”界面。

## 记忆与压缩策略

### 记忆分层

1. `Candidate Memory`
2. `Job / JD Memory`
3. `Agent Global Memory`

### 压缩原则

- 使用 LLM 进行压缩，但输出必须为结构化 JSON
- 原始对话、原始日志、原始审计不覆盖，只新增压缩层
- 压缩策略外露为 agent 配置
- 每次压缩都保留版本号、来源、触发原因、摘要时间

### 自动压缩触发条件

- 达到用户设定阈值
- 进入阶段切换
- 完成一次候选人处理
- 人工确认后
- 上下文长度超过 `1m`

### 压缩结果标准字段

- `facts`
- `decisions`
- `open_questions`
- `next_actions`
- `risk_flags`
- `evidence_refs`
- `confidence`

## 工作进度管理

工作进度管理是产品核心，不附属于通用 runtime。

事实源建议以结构化数据库落地：

- `Candidates`
- `CandidateStageEvents`
- `CandidateAssignments`
- `CommunicationThreads`
- `ResumeArtifacts`
- `Scorecards`
- `ReviewDecisions`
- `TalentPoolSyncRecords`

候选人的当前状态由事件流和结构化字段共同驱动，而不是靠 LLM memory 反推。

## 审批模型

### A. 运行时审批 / 候选人沟通确认

用于：

- 外联消息确认
- 回复草稿确认
- 候选人阶段决策确认
- 人工接管沟通

UI 形态：

- 类似聊天框
- 候选人 tab 隔离
- 每个候选人独立消息流和待处理动作

### B. 演进审批 / Agent 自学习治理

用于：

- skill draft 审批
- workflow patch 审批
- prompt patch 审批
- memory policy patch 审批
- skill 失效 / 健康问题处理

UI 形态：

- 独立的“自学习 / 演进”界面
- 不与候选人聊天确认混在一起

## UI 信息架构

新的 sidebar 建议调整为：

- `概览`
- `招聘 Agent`
- `工作台`
- `沟通中心`
- `演进治理`
- `设置`

### 招聘 Agent

展示并编辑：

- agent 身份设定
- 提示词与职责
- workflow 图
- memory 策略
- skill 列表
- skill 元数据
- 压缩策略

### 工作台

展示：

- 候选人进度总览
- 当前阻塞项
- 最近执行结果
- JD 维度工作状态
- 待同步动作

### 沟通中心

展示：

- 候选人 tab
- 聊天记录
- 草拟回复
- 待人工确认
- 已发送 / 待发送状态

### 演进治理

展示：

- skill 审批
- skill 健康
- workflow patch
- prompt patch
- memory policy patch

## 对现有代码的处理原则

### 保留作为实现内核的部分

- 现有 `AgentLoop`
- 审批基础设施
- sync/backlog
- skill 生命周期与健康检查
- 现有招聘 workflow 节点定义
- 候选人结构化数据模型基础

### 收敛或下沉的部分

- `TaskSpec / ExecutionPlan / ExecutionEpisode`
  - 保留为内部实现层
  - 不再作为产品主语
- `workflow management`
  - 重命名为招聘 agent 配置与 workflow 管理
- `workbench`
  - 改为候选人进度与 agent 执行结果面板

### 需要逐步清理的旧方向

- 通用 runtime 叙事
- 以执行实例为中心的 UI
- hardcode 的 recruiting 旧文案和多余兼容逻辑
- 把通用 runtime 页面直接暴露给用户的做法

## 当前实施顺序

截至 `2026-04-15`，当前这六个阶段已经全部落地，后续如有新工作将进入下一轮增量迭代，而不是继续沿用这一轮的重构任务单。

### Phase 1: Product Direction Reset

- 重写 README 与 Plan
- 把产品叙事改为 `Recruit Agent`
- 调整 sidebar 和页面命名

### Phase 2: Recruit Agent Core Config

- 新增 `RecruitAgentProfile`
- 新增 agent 配置 API
- 外露 agent 身份、prompt、职责、边界、压缩策略

### Phase 3: Isolated Memory

- 新增 `Candidate Memory`
- 新增 `Job / JD Memory`
- 新增 `Agent Global Memory`
- 增加严格隔离读取逻辑
- 增加手动与自动 compact
- 保留 `raw_content`，新增 `preview / operator / model` 多层披露
- compact 后不覆盖原始信息，保留渐进式摘要层

### Phase 4: Candidate Operations

- 工作台围绕候选人进度重构
- 增加聊天式沟通中心
- 工作台和概览中的核心统计支持直接下钻到候选人队列
- 运行时审批与候选人沟通确认 UI 落地
- 新增 `CandidateStageEvents` 和 `CandidateAssessment`
- 支持联系方式节点、AI/人工评估、多轮面试节点和手动状态流转
- 候选人时间流、评估记录和沟通记录统一挂到候选人名下

### Phase 5: Skill & Evolution Governance

- skill 标准化元数据落地
- skill 可查看/编辑/删除
- 新增 `EvolutionArtifact`，承载 `workflow / prompt / memory policy / skill draft` 等演进产物
- 配置页从 JSON 主导改成结构化外露，JSON 退到高级区
- 新增 `Agent IM`，支持在主会话面内联处理非候选人审批和阻塞项
- `Evolution` 升级为高密度治理中心，统一管理 skills / memory / prompts / playbook / approvals / history

### Phase 6: Legacy Cleanup

- 收缩旧 workflow 实例语义
- 清理多余通用 runtime 文案
- 逐步清理 recruiting hardcode 的旧兼容分支

## 当前阶段完成状态

- `Phase 1` 已完成
- `Phase 2` 已完成
- `Phase 3` 已完成
- `Phase 4` 已完成
- `Phase 5` 已完成
- `Phase 6` 已完成

## 本轮补充完成项

在 Phase 1-6 完成之后，本轮又继续把未暂缓的深化项补齐：

- 候选人结构化事实层继续拆细并落库：
  - `CandidateAssignments`
  - `ResumeArtifacts`
  - `Scorecards`
  - `ReviewDecisions`
  - `TalentPoolSyncRecords`
- `CandidateThread` 聚合结果已包含上述结构化对象，不再只停留在 `CandidateAssessment / CandidateStageEvents / CommunicationLog`
- 演进产物从纯泛型约束收紧为强类型治理：
  - `skill_draft`
  - `prompt_patch`
  - `memory_policy_patch`
  - `playbook_patch`
  - `workflow_patch`
- 演进产物创建和更新时增加了必填 schema 校验，不再接受任意形状的弱约束 JSON
- `Recruit Agent` 的 playbook 编辑已从纯 JSON 文本框提升为结构化可视编辑：
  - 可直接编辑阶段组
  - 可直接编辑阶段 key / label
  - 可直接编辑多轮面试默认轮次
  - 可直接查看 workflow node 与 transition 概览
  - 原始 JSON 退回高级区
- 候选人沟通中心已外露新的结构化事实：
  - 负责人
  - 简历产物
  - 评分卡
  - 评审结论
  - 同步记录

这部分同样属于当前这一轮 `Recruit Agent` 收口范围，已完成，不再额外拆成新 phase。

## 暂缓执行项

- 内部工程标识整体迁移暂缓：
  - Python 包路径 `scene_pilot`
  - 仓库目录名 `scene-pilot`
  - npm workspace 包名 `@scene-pilot/shared`
- 这类改动属于工程级迁移，不再计入当前这轮 `Recruit Agent` 产品收口任务。
- 当前要求是：
  - 对外 CLI、环境变量前缀、桌面启动入口、API 路径、产品文案已经统一到 `Recruit Agent`
  - 内部实现层路径和仓库物理命名暂时保持现状，后续如需统一再单独开一轮迁移

## 后续 Todo

这部分不是当前轮次的阻塞项，也不属于已明确延期的工程迁移；作为下一轮能力增强 backlog 保留：

- `Runtime Productization`
  - 把当前偏单次执行的 `AgentLoop` 继续增强为更稳定的长会话 / 可恢复 / 可中断 / 可续跑 runtime
  - 明确 session continuity、失败恢复、长任务执行与状态恢复机制
- `Provider & Auth Layer`
  - 在现有 `baseUrl + apiKey` 基础上，补更完整的 provider routing
  - 评估是否需要 credential pool、同 provider 多 key 轮转、跨 provider failover、凭证健康状态
  - 当前优先级下调，暂不进入本轮实现
- `Dynamic Context Assembler`
  - 将当前偏静态的 `context_slots` 演进为按任务动态装配的上下文系统
  - 支持按候选人阶段、当前目标、历史事件、评分卡、记忆层级、skill 相关性做裁剪与优先级排序
- `Memory Platformization`
  - 保持当前 `Candidate / Job / Global Memory` 严格隔离
  - 在此基础上补更明确的 session memory、长期记忆刷新、压缩层级与检索装配策略
- `Skill Platformization`
  - 在现有 skill 治理和健康检查之上，继续补充 skill 的运行时装载、按需披露、版本化启停、作用域选择与组合执行能力
  - 让 skill 不只是“可治理对象”，也成为“可动态装配的执行资产”

## 下一轮专项计划：MCP Registry 与真实环境执行

这一轮的目标不是继续加 Boss 专用逻辑，而是把当前 runtime 从“硬编码平台动作 + 本地 fallback”重构到“动态 MCP 工具接入 + 真实环境执行”。

### 2026-04-15 实施进度

这一轮的第一版已经完成：

- `BossPlatformAdapter`、Boss 专用 browser 桥和 `boss_*` runtime 工具已移除
- Browser MCP 已改为通过 `McpPresetTemplate + McpServer + McpTool` 注册，不再在容器初始化时写死为唯一网页桥
- runtime 工具注册已收敛为：
  - 执行控制工具
  - 系统命令工具
  - 已注册 MCP 的动态工具
- 外部能力缺失时会直接阻塞或失败，不再退回本地候选人库或桌面 mock 继续“伪执行”
- 桌面端已新增 MCP 管理面板，放在 `Settings` 内部，支持：
  - 查看预置模板
  - 安装模板
  - 查看/编辑/删除已注册 MCP 服务
  - 创建自定义 MCP 服务
  - 手动触发健康检查
- 桌面端 mock 数据、mock transport 和本地 fallback 逻辑已全部删除
- 当前校验已通过：
  - `npm run desktop:typecheck`
  - `python3 -m pytest services/backend/tests -q`

### 背景调整

当前实现里还保留了几类不符合目标方向的能力：

- `BossPlatformAdapter` 这种预制平台动作
- 把 `browser-mcp` 写死在代码里作为唯一网页桥
- Browser MCP 不可用时退回本地候选人数据继续执行
- 桌面端在后端不可用时退回本地 mock client / mock data

这些都会导致系统看起来像在“自主执行”，但实际已经脱离真实外部环境，容易产生误导。

因此这一轮明确调整为：

- 不再 hardcode 任何 Boss 平台动作
- 不再 hardcode Browser MCP 为唯一网页桥
- 引入 MCP 注册与管理机制
- runtime 工具来自已注册 MCP 的动态桥接
- 页面读写只允许通过真实外部能力完成
- MCP 缺失时直接 fail fast，不再退回本地伪执行
- 招聘场景依赖 `skill / strategy / memory`
- Boss 作为默认环境预置与 skill bundle 的来源，而不是执行底层
- 完全删除桌面 mock 数据逻辑，避免错误心智

### 本轮核心对象

- `McpServer`
  - 一个已注册的 MCP 服务实例
  - 保存名称、传输方式、连接地址、启用状态、认证与元信息
- `McpTool`
  - 某个 MCP 暴露给 runtime 的工具定义
  - 保存 schema、capabilities、风险标签、启用状态、远端调用映射
- `McpPresetTemplate`
  - 预置模板
  - 例如浏览器类 MCP、通用 HTTP 工具桥等
  - 作用是帮助初始化，不参与底层执行决策
- `McpHealthSnapshot`
  - 最近一次连通性与工具发现结果

### 运行原则

1. runtime 不再直接注册 `boss_*` 工具
2. runtime 只注册：
   - 执行控制工具
   - 系统命令工具
   - 已注册 MCP 的动态工具
3. LLM 通过动态工具集合完成页面观察与动作执行
4. 招聘环境知识下沉到：
   - skill
   - strategy fragment
   - memory
5. 真实外部能力缺失时，run 必须进入：
   - `blocked`
   - `needs_intervention`
   - 或明确失败
6. 不允许用本地候选人库或前端 mock 数据“补演”真实网页执行

### 前端与产品面调整

- 新增 MCP 注册与管理页面
  - 放在合适的系统配置区，不作为随意散落的新入口
- 页面需要支持：
  - 注册 MCP server
  - 配置连接参数
  - 查看已发现工具
  - 启用 / 停用工具
  - 查看健康状态
  - 从预置模板快速创建
- 删除桌面端 mock fallback
  - 后端不可用时直接显示真实错误与阻塞状态
  - 不再切到本地 mock 工作区

### 后端替换范围

- 删除 `BossPlatformAdapter` 及其配套硬编码动作桥
- 删除 browser-mcp 的 Boss 专用读写封装
- 删除“真实浏览器失败 -> 本地候选人存储 fallback”逻辑
- 新增 MCP registry、tool bridge 与健康检查
- 调整 `AgentLoop` 的工具压缩与候选人提取逻辑，不再写死 `boss_*` 工具名
- 调整 runtime 能力驱动，不再预设任何站点专用发现/检查动作

### 验收标准

- 后端不存在 `BossPlatformAdapter`
- runtime 不再注册任何 `boss_*` 硬编码工具
- browser-mcp 通过注册模板接入，而不是在容器初始化时写死
- 外部能力缺失时，系统直接阻塞，不再退回本地伪执行
- 桌面端不再存在 mock transport / mock data fallback
- 已注册 MCP 的工具能被 runtime 动态暴露给模型使用

## 下一轮专项计划：Runtime 与 Context

这一轮不再继续扩散产品范围，而是围绕 `Recruit Agent` 的长期运行能力，补齐 `runtime` 和 `context` 两条底层主线。

### 2026-04-15 实施进度

已完成当前最小可用闭环：

- `AgentSession / AgentRun / WorkItem / Checkpoint / RuntimeEvent` 已落库并接入执行主链
- 调度器已接入 `AgentRun` 并发上限控制，当前支持全局 `max_concurrent_runs`
- `waiting_human` 已生成 checkpoint，审批后会回到原 run 恢复，不再只是逻辑层面的“重新排队”
- 每次执行前都会生成 `context_manifest`，并写入 `AgentRun.context_manifest`
- `Context Assembler Policy` 已支持“代码硬边界 + 用户可配权重/预算 + 可选 LLM rerank”的三层模型
- `Context Policy` 配置页已放入 `Recruit Agent` 内部二级页，而不是单独新增功能区
- 已开放运行态查询接口：
  - `/api/recruit-agent/runtime/session`
  - `/api/recruit-agent/runtime/runs`
  - `/api/recruit-agent/runtime/checkpoints`
  - `/api/recruit-agent/runtime/events`
- 桌面端设置页已支持编辑并持久化平台并发限制
- 启动恢复已补齐到 runtime 层：
  - 程序异常关闭后，重启会立即回收遗留的 running queue task，而不再等待默认 stale 窗口
  - 对应 `AgentRun / WorkItem` 会一并恢复到 `queued / resumable`，不再只标记为 `interrupted`
  - 在存在可恢复任务快照时，会自动重建 queue task 并继续从任务边界恢复执行
  - 恢复过程会写入 `runtime event` 和 `run.runtime_metadata.recovery_history`

当前仍未做的是更深一层的 `Orchestrator` 能力，例如 work item 合并、复杂抢占策略、按动作类型限流，以及更强的片段相关性排序与检索增强。

目标不是做“更通用的平台”，而是让招聘 Agent 具备：

- 长会话、可挂起、可恢复的执行能力
- 候选人维度严格隔离的上下文装配能力
- 非候选人治理事项与候选人沟通事项分 lane 运行
- 在保持结构化事实源不失真的前提下，尽量减少无关上下文进入模型

### Runtime 目标形态

当前执行模型偏 `run-centered`；下一轮目标改为 `session-centered`：

- `AgentSession`
  - 招聘 Agent 的长期会话
  - 持久存在，重启后可恢复
- `AgentRun`
  - 一次实际执行，来源可以是人工触发、候选人新消息、状态变更、定时巡检、审批恢复
- `WorkItem`
  - 更细粒度的待办单位，用于进入调度器排队、合并和去重
- `Checkpoint`
  - 运行时挂起点，用于 `waiting_human / waiting_candidate / skill_blocked / permission_blocked` 等可恢复场景
- `RuntimeEvent`
  - 持久化事件日志，替换当前偏内存化的事件流视图

### Runtime 分层

下一轮 runtime 按 4 层收敛：

1. `Trigger Layer`
   - 把新消息、候选人状态切换、待办恢复、定时巡检等外部信号转换为 `WorkItem`
2. `Orchestrator`
   - 负责 work item 去重、优先级、候选人级串行锁、抢占和恢复决策
3. `Executor`
   - 继续复用现有 `AgentLoop`，不推翻现有执行内核
4. `Persistence`
   - 落库保存 session、run、checkpoint、runtime event、恢复所需上下文快照

### Runtime 本轮实现重点

- 引入 `AgentSession / AgentRun / WorkItem / Checkpoint / RuntimeEvent` 数据模型
- 同一候选人同一时刻只允许一个 active run，避免状态竞争和记忆串扰
- 引入 `AgentRun` 并发上限控制，避免在 Boss 等外部站点上同时处理过多候选人而触发风控
  - 支持配置全局 `max_concurrent_runs`
  - 后续可扩展为按环境配置更细粒度限制，例如 `environment_concurrency_limits`
  - 调度器达到上限时只能排队，不允许继续拉起新 run
  - 后续可扩展为按动作类型限流，例如“浏览/查看简历”和“主动沟通”分别限流
- `waiting_human`、候选人待回复、skill 失效、权限待确认等场景必须生成 checkpoint，而不是只能整段重跑
- `Agent IM` 与候选人 IM 分成两条 lane：
  - `Agent Lane`
    - skill 失效
    - prompt / playbook / memory policy 审批
    - 运行时阻塞与权限确认
  - `Candidate Lane`
    - 候选人沟通
    - 候选人状态推进
    - 人工评估与去留决策
- 事件流从“仅供前端观察”演进为“可回放、可审计、可恢复”的 runtime event log

### Context 目标形态

下一轮上下文系统不再只依赖固定 `context_slots`，而是引入 `Context Assembler`：

- 输入：
  - `run_type`
  - `lane`
  - `candidate_id`
  - `job_id`
  - `current_stage`
  - `token_budget`
  - `risk_level`
  - `requires_human_confirmation`
- 输出：
  - `context_manifest`
  - 最终送入模型的上下文切片集合
  - 每个切片的来源、层级、token 估算、选择理由

### Context Assembler 分层

1. `Scope Resolver`
   - 确定本轮上下文作用域：候选人、JD、治理事项、候选人阶段
2. `Collectors`
   - 从以下来源提取候选上下文片段：
     - `candidate_progress`
     - `candidate_thread`
     - `candidate_memory`
     - `job_memory`
     - `agent_global_memory`
     - `assessments / scorecards / review_decisions`
     - `skills`
     - `approvals / blocking items`
3. `Rank & Budget`
   - 依据相关性、时效性、风险、证据价值、token 成本对片段排序
4. `Pack`
   - 依据预算组装最终 prompt，并记录丢弃与降级决策

### Context 组装规则

- 保持当前三层披露能力：
  - `preview`
  - `operator_summary`
  - `model_context`
- 上下文选择必须从“整块加载”改为“片段级加载”
- 候选人上下文包只允许包含：
  - 当前候选人事实
  - 当前候选人消息历史
  - 当前候选人 memory
  - 关联 JD memory
  - 当前阶段相关评估、评分卡、结论
  - 本轮所需的 skill 摘要
- 治理上下文包只允许包含：
  - 当前审批项
  - 相关 diff / 演进产物
  - 相关失败证据
  - 相关 skill / prompt / memory policy 摘要
- 超预算时按固定顺序降级：
  - 先降级 `global memory`
  - 再降级 `job memory`
  - 再压缩候选人旧消息和旧阶段事件
  - 原始事实记录始终保留在库中，不做覆盖式删除

### Runtime 与 Context 的联动

这两部分必须一起设计，但分阶段落地：

#### Phase A: Runtime Foundation

- 建立 session / run / checkpoint / runtime event 基础模型
- 候选人级串行锁
- 建立 `AgentRun` 最大并发数控制与排队机制
- `waiting_human` 与候选人待回复场景的 checkpoint 恢复机制
- 把当前内存事件流升级为可持久化事件日志

#### Phase B: Minimal Context Assembler

- 先只支持两种装配路径：
  - `candidate lane`
  - `agent lane`
- 实现最小片段模型、collector、排序与预算裁剪
- 先不做复杂检索，只做结构化筛选 + relevance 排序 + tier 降级

#### Phase C: Runtime-Context Integration

- 每个 run 在执行前自动生成 `context_manifest`
- 将本次上下文选择写入 runtime event，便于调试和审计
- 将 checkpoint 恢复与 context re-assembly 串起来，避免从头整段重跑

### 本专项的验收标准

完成这一轮后，至少满足：

- `AgentSession` 可持久化并在重启后恢复
- `AgentRun` 与 `Checkpoint` 可以表示挂起和恢复过程
- 同一候选人不会并发进入多个 active run
- 系统可配置 `AgentRun` 最大并发数量，达到上限时会排队而不是继续并发执行
- 对高风控渠道可单独配置更严格的并发上限
- `Agent IM` 的审批恢复与候选人 IM 的沟通恢复都能从 checkpoint 继续
- 每次执行前都会生成结构化 `context_manifest`
- 上下文进入模型前会经过片段级选择，而不是整块静态拼接
- `Candidate / Job / Global Memory` 继续严格隔离，不因动态装配被打破
- 超预算时可以稳定降级，不需要依赖人工手动删上下文
- skill 默认只按需披露，不整包注入模型

## 验收标准

完成当前波次后，至少满足：

- 顶层产品表述已切换为 `Recruit Agent`
- 招聘 agent 配置可查看、可修改
- Candidate Memory 严格按候选人隔离
- Job / JD Memory 严格按 JD 隔离
- Agent Global Memory 独立存在
- 支持自动 compact，且超过 `1m` 上下文时自动触发
- skill 使用标准化结构，支持查看、编辑、删除
- 运行时交互与演进治理分离
- 非候选人类确认/介入默认可在 `Agent IM` 内联完成，必要时再进入 `Evolution` 做长期资产治理
- 候选人沟通中心为会话式 UI
- `Evolution` 为集中治理台，支持管理 skills、memory、prompts 和 playbook
- 工作台以候选人进度和 agent 结果为中心

## 当前结论

这一轮不是继续把系统做成“更通用的 runtime”，而是：

- 用现有执行内核服务 `Recruit Agent`
- 围绕招聘场景把 agent、memory、skill、候选人进度、沟通确认、演进治理做完整
- 未来如需增加其他内置 agent，再在这一套 agent-first、场景-first 的架构上扩展

## 后续计划：Goal-Driven Adaptive Runtime

当前状态：

- 已完成从旧 workflow-first 主链到 E 主链的切换
- `GoalSpec / ExecutionTrace / StrategyFragment / ExecutionGraphProjection` 已落库并接入 API
- `Workbench` 已支持直接创建目标驱动任务
- 运行结果会自动沉淀 trace、策略片段和面向用户的执行图投影
- `goal_intake / exploration_trial / candidate_probe / candidate_outreach / resume_collection / candidate_scoring / strategy_distill / scale_execution` 已成为主执行阶段
- 旧 workflow 引擎已退出主执行链路，不再作为运行时骨架或 follow-up 生成依据
- 旧流程中可复用的阶段知识，已改写为默认执行蓝图和自适应阶段配置，而不是继续驱动 runtime

开始这一轮前，先在当前稳定分支上做一次备份分支或 tag，避免探索式改动跨度过大时难以快速回退。

当前这一步已经按该原则执行过，备份分支：

- `backup-goal-driven-cutover-20260415`

当前 runtime 已不再把“预先编排完整 workflow”作为主要执行依据，而是转向：

- 用户描述目标与约束
- LLM 自主探索完成路径
- 运行时将有效路径沉淀为 skill / memory / strategy fragment / policy patch
- 面向用户展示的图更多作为解释层，而不是执行真相

### 方向定义

从：

- `workflow-first runtime`

切换为：

- `goal-driven adaptive runtime`

核心原则：

- 图是给用户看的解释层，不是模型唯一依赖的执行蓝图
- 事实层保持结构化稳定
- 策略层、skill、memory summary、执行图允许演进
- 学到的内容优先沉淀成结构化资产，而不是只停留在一次 trace 里

### 新的核心对象

- `GoalSpec`
  - 用户目标、约束、成功标准、禁止事项
- `ExecutionTrace`
  - 一次 run 的原始执行轨迹，作为后续提炼真相
- `StrategyFragment`
  - 从多次 trace 中提炼出的可复用策略片段
- `ExecutionGraphProjection`
  - 面向用户展示的执行图 / 学习图 / 策略图
- `TrialOutcome`
  - 探索阶段的结果摘要，用于判断是否扩大执行

### 运行模型

建议将执行过程收敛成 6 步：

1. `Goal Intake`
   - 用户只表达目标、约束、成功标准，不要求手工写完整 workflow
2. `Exploration Planning`
   - LLM 提出若干候选策略，决定从哪些入口和路径开始试探
3. `Trial Execution`
   - 先小规模尝试，避免一开始就大范围执行
4. `Trace Distillation`
   - 将成功模式、失败模式、新发现入口和关键判断从 trace 中提炼出来
5. `Asset Update`
   - 更新 skill、memory、strategy fragment、policy patch、graph projection
6. `Scaled Execution`
   - 使用验证过的策略放大执行

### 图的定位调整

图不再等同于“执行工作流图”，而是作为运行时投影存在，建议统一收敛为：

- `Execution Graph`
- `Strategy Graph`
- `Learning Graph`

展示内容包括：

- 实际走过的路径
- 新发现的平台入口和筛选器
- 成功与失败的分叉
- 调用过的 skill
- memory / policy 的更新痕迹
- 人工干预发生的位置和结果

### 资产沉淀原则

后续执行后的学习结果优先沉淀为：

- `Skill`
- `StrategyFragment`
- `Memory Update`
- `Context Policy Adjustment`
- `Playbook / Policy Patch`

不建议把“学习结果”只留在面向用户的图里。

### 事实层与策略层边界

必须继续保持：

- 候选人事实
- 候选人状态流转
- 评分卡
- 评审结论
- 联系方式状态
- 面试轮次状态

这些属于结构化事实层，只允许新增、修正和审计，不允许被自由生成式策略覆盖。

可进化的部分包括：

- strategy
- skill
- memory summaries
- graph projection
- context policy

## 后续计划：Operator Intervention Layer

当前状态：

- 已完成第一轮最小闭环
- `OperatorInteraction` 已作为新的运行时交互对象接入
- `Agent IM` 已优先展示确认/介入项，而不是只看旧审批对象
- 用户可直接在 IM 中执行 `confirm / retry / correct / teach / handoff / stop` 等动作
- 后台会保留结构化记录，前台展示为自然语言交互与操作结果
- 当前仍保留 `ApprovalItem` 作为兼容层，后续再继续下沉旧审批语义

开始这一轮前，沿用同一条原则：先对当前稳定分支做备份，再进入大范围交互模型改造。

如果 runtime 不再强依赖预设 workflow，而是更自主地探索和执行，就必须补上人工干预层，避免：

- 同一路径重复尝试
- 持续失败
- token 浪费
- 平台风控
- agent 在错误策略上死循环

### 目标

建立一个独立的 `Operator Intervention Layer`，让用户能在执行过程中：

- 确认
- 纠偏
- 接管
- 教学

并将这些交互以结构化方式回写到 runtime 和学习资产中。默认交互应以内联 IM 窗口完成，后台只保留结构化存储，前台展示为人能看懂的操作记录，而不是暴露原始 JSON 审批单。

### 干预类型

1. `confirm`
   - 确认是否继续、是否允许执行某动作、是否允许进入下一阶段
2. `correct`
   - 对当前路径进行纠偏，例如禁止继续某条失败策略
3. `retry`
   - 在用户确认后，允许 agent 使用当前或调整后的参数重新尝试
   - 需要明确区分：
     - 原路径重试
     - 带修正条件的重试
     - 更换入口后的重试
4. `handoff`
   - 将当前步骤交由用户亲自接管
5. `teach`
   - 用户直接教给 agent 一条可沉淀的经验或规则

### 交互形态

- 不默认建设厚重的“审批中心”作为主入口
- 优先使用 `Agent IM` / `Candidate IM` 的内联确认与自然语言介入
- 用户可以直接：
  - 通过 / 不通过
  - 再试一次
  - 按新的方式重试
  - 我来处理
  - 换个方式
  - 停止这条路径
  - 输入自然语言纠偏意见
- 系统后台记录结构化结果，前台渲染为可读的“操作记录 / 介入历史”

### LLM 动态选项能力

人工介入层不应只依赖预设按钮。需要保留足够的动态能力，让 LLM 在当前上下文下主动生成少量、真实可执行的候选选项。

约束如下：

- 选项必须来自当前 runtime 可执行动作，不能生成不可落地的空想建议
- 选项可以是：
  - 当前路径重试
  - 带调整参数的重试
  - 切换入口
  - 改变筛选策略
  - 进入人工接管
  - 请求补充信息
  - 降级为更保守的执行路径
- LLM 生成的选项必须带简短理由和预期影响
- LLM 生成的选项应尽量附带可执行参数或目标变更，而不是只给抽象建议
- 用户确认后，系统应能直接把这些选项落成真实可执行动作，而不是再让用户手工重新描述一遍
- 最终仍由代码校验“是否可执行”、由用户决定“是否采用”
- 用户也可以不选预设项，直接输入新的自然语言意见

### 触发条件

至少支持以下熔断触发：

- 同类 action 连续失败超限
- 多轮尝试没有产生新信息或新证据
- 即将执行高风险动作
- 模型置信度过低
- 平台出现风控或异常信号
- skill 连续失效

### 干预对象

建议新增：

- `InterventionRequest`
- `InterventionResolution`
- `OperatorActionLog`

最低需要记录：

- `run_id`
- `candidate_id`
- `intervention_type`
- `reason`
- `attempt_summary`
- `failed_actions`
- `blocking_scope`
- `operator_input`
- `resolution`
- `follow_up_patch`

前台展示要求：

- 不直接暴露底层 JSON
- 要渲染成自然语言可读日志
- 用户应能看懂：
  - agent 当时为什么停下来
  - 给了哪些可执行选项
  - 用户怎么处理
  - 结果影响了什么

### 干预入口

需要保留三个入口：

1. `Agent IM`
   - 非候选人沟通类的阻塞、权限、skill、patch、治理事项
   - 默认主入口，优先内联处理确认、介入和纠偏
2. `Candidate IM`
   - 某个候选人的沟通、状态推进、人工判断、人工接管
3. `Evolution`
   - 对可以沉淀为长期资产的交互结果进行版本化治理
   - 不作为所有运行时确认的默认入口

### 干预后的沉淀策略

每次干预后，系统都要判断其作用范围：

- `run_only`
- `candidate_scope`
- `agent_scope`

并决定是否要生成：

- strategy fragment
- memory update
- skill patch
- context policy adjustment

### 反死循环机制

runtime 必须有代码层硬熔断：

- 当同类动作连续失败达到阈值
- 且没有新证据、新上下文、新工具结果
- 自动进入 `needs_intervention`

并区分：

- `operator_recommended`
- `operator_required`

避免 agent 无限重试。

## 这两项后续计划的验收标准

后续真正开始开发时，至少满足：

- 用户不需要先手工写完整 workflow 才能启动目标执行
- runtime 能从 trace 中提炼策略并沉淀为结构化资产
- 图成为解释层，而不是唯一执行依据
- 运行时确认默认在 IM 内联完成，而不是要求跳转重审批流
- LLM 可以基于当前上下文动态生成少量、真实可执行的候选操作项
- 用户确认后的“重试 / 换路 / 切换策略 / 接管”可以直接落成实际执行动作
- 所有交互都有结构化记录，但前台展示为自然语言可读操作日志
- 出现持续失败时，系统会自动进入人工干预流程
- 用户的纠偏、接管、教学能回写到后续策略与资产里
- 人工干预不会只停留在一次 run，而是可以按作用域沉淀
- 事实层继续保持稳定和结构化，不被生成式策略污染
