# Autonomous Agent 运行时约束规范

## 文档目标与适用范围
本文档定义 Autonomous / Assistant 相关运行时的长期约束，用于约束主程序在生命周期、记忆、提示词、工具暴露、站点接入、UI 验收与共享业务能力建模上的边界。

本文档适用于所有通过 `prompts/`、memory schema、tool surface、plugin、skill、runtime、UI、API 等入口影响 Agent 行为的实现与验收工作。

本文档记录的是项目应长期遵守的约束，不是某一时点的实现现状、迁移计划、handoff、复盘或 memory dump。实现若与本文档冲突，应优先修正实现，或先更新本文档后再变更实现。

## 核心术语
- `主 Agent`：指一个 Autonomous Agent 实体，其生命周期由主程序托管，具有持续存在的身份、记忆和目标上下文。
- `主 conversation`：指与某个主 Agent 绑定的长期主会话。该会话承载目标演进、历史 run 结果和长期上下文，不因单次 goal 执行而重建。
- `run`：指主 Agent 在某个时间段内围绕当前目标发起的一次执行实例。run 可以结束、失败、等待审批或被取消，但它属于主 conversation 的历史。
- `open run`：指尚未进入终态的 run。凡是仍会继续消耗执行机会、等待外部输入、等待审批或仍可恢复执行的 run，均视为 open run。
- `Global Memory`：指跨 run、跨阶段可复用的长期记忆，只承载业务层抽象、稳定偏好和可复用约束。
- `子上下文`：指 subagent、网页执行器、单次页面操作链路或其它 run 内部临时上下文。其内容不自动提升为 Global Memory。
- `外部开发代理`：指 Codex 或其它在仓库外部观察并修改主程序的开发代理，不等同于主程序内部真正运行的 Agent。

## 运行时与会话模型规范
### 1. 生命周期主模型
Autonomous 的主生命周期必须建模为“一个主 Agent 对应一个主 conversation 的持续演进模型”。

同一主 Agent 的目标、run 历史、长期记忆和状态演进必须挂载在同一个主 conversation 上。`goal` 的含义是该主 conversation 上持续累积的 runs 历史与当前目标语义，不得建模为“一个 goal 对应一个全新独立会话”。

创建新 goal、重试、继续执行、补充输入、恢复执行等行为，默认都应追加到既有主 conversation / 主 Agent 的生命周期中，而不是为每个 goal 新建一个彼此割裂的独立 Agent 会话。

### 2. 并发约束
默认情况下，同一 Autonomous Agent 在同一时刻最多只能存在 `1` 个 open run。

除非用户明确提出更高并发要求，主程序不得因为存在多个候选目标、多个待办事项或内部实现便利而自行把同一 Autonomous Agent 扩展为多 open run 并发执行。

若要支持高于 `1` 的同 Agent 并发，必须同时满足以下约束：
- 并发来自用户的明确要求，而不是系统自行推断。
- 并发 run 之间的状态、审批、可见性和结果归属仍然清晰挂载在同一个主 Agent 生命周期下。
- 新并发能力的引入不得破坏本文档对主 conversation、Global Memory 与工具边界的其它约束。

## 记忆与提示词规范
### 1. Global Memory 口径
Global Memory 必须只记录业务层抽象、稳定用户偏好、跨 run 可复用的任务约束、领域事实和经过沉淀后仍有复用价值的经验。

Global Memory 不得记录网页执行细节或页面瞬时状态，包括但不限于 tab 数量、URL、DOM 结构、当前页标题、具体按钮文案、页面临时布局、一次性抓取路径、局部浏览器句柄或其它网页操作细节。

网页执行细节属于 subagent 或其它子上下文，只能保留在对应 run 内部上下文、执行日志、临时观察结果或站点链路局部状态中，不得直接上升为 Global Memory 的长期口径。

run / goal / round 的业务动作实例、最近一次业务状态摘要、当前阻塞原因、当前待办推进建议、当前外部平台通断状态等“正在发生的运行态信息”，默认属于 `run context`、`recent events`、`checkpoints`、`logs`、`workspace summary` 或其它运行态投影层，不属于 Global Memory。

因此，主程序不得把最近一次 run 的业务摘要直接投影为 `business_snapshot`、`blocked_business_actions`、`external_platforms` 或其它等价结构后，再落入 `agent_global_memory`。这类信息若需要展示给 human，应通过 run / workspace 相关投影链路提供；若未来被证明具有跨 run 的长期复用价值，应先被提炼为稳定知识后，才允许进入 Global Memory。

任何 human-facing 的 `memory` 视图、卡片、详情页或 overlay 面板，也必须遵守同样边界：记忆区域只能展示 memory 层对象本身，不得在记忆区域头部、摘要区或统计区混入当前 goal / run 的标题、状态、阻塞说明、当前任务描述或其它运行态业务动作信息。

### 2. Prompt 落点
凡是面向 LLM 的自然语言行为约束、步骤指引、完成标准说明、共享任务描述或可复用场景提示词，默认都应落在仓库级资源目录 `.recruit-agent/prompts/` 下的 prompt 文件中。

这些自然语言约束不应散落在 `runtime/`、`services/`、工具描述、主流程字符串、桌面端 UI 文案、API 临时拼接文本或注释中。主程序可以传递结构化上下文，但不得用结构化字段替代或夹带新的提示词正文。

### 3. 招聘平台页面访问约束的规范落点
涉及 `zhipin.com` 或其它外部招聘平台页面访问的自然语言约束、任务描述和场景提示词，必须与本文“招聘平台页面打开与复用规则”保持一致。

这类约束的长期事实来源是本文档，而不是会话记忆、单次 run 备注或某个业务场景中的零散提示词。prompt 可以复述该规则，但不得把它缩窄成只适用于“同步 JD”的局部说明，也不得遗漏“发现候选人”等同类招聘场景。

## 工具 / MCP / 站点接入边界
### 1. Agent 与系统边界
Codex 或其它外部开发代理只能通过修改主程序来影响内部 Agent 行为，可修改的入口包括 prompts、memory schema、tool surface、plugins、skills、runtime、UI、API 等主程序资产。

外部开发代理不得直接跨越边界去扮演主程序内部 Agent，也不得直接占用内部 Agent 的 memory、tools、plugins、skills 或运行时身份去完成任务。开发代理修改的是主程序能力边界，不是替代内部 Agent 执行其生命周期。

### 2. MCP 标准接入原则
主程序接入任何 MCP server 时，必须优先走 MCP 标准协议与标准 transport，不得在主程序中手写或长期维护某个上游 MCP 的本地桥接副本。

这里的“手写或长期维护桥接副本”包括但不限于：
- 在主程序里硬编码某个 MCP server 的工具目录、工具 schema、`tools/list` 返回值或 `tools/call` 兼容包装。
- 在主程序里为某个上游 MCP server 复制一份本地 tool catalog，并依赖人工同步维护。
- 在主程序里为某个特定 MCP server 重写一套等价的 JSON-RPC/MCP server 外壳，只为把其工具再包装一遍给内部 Agent 使用。

若上游已经提供标准 MCP server，主程序必须直接连接或启动该标准 MCP server，并通过上游真实的 `tools/list` / `tools/call` 动态发现与调用工具。

若上游尚未提供标准 MCP server，应优先在上游工具仓库或其正式分发物中补齐标准 MCP 支持，而不是在 `recruit-agent` 主程序仓库内临时硬写一个私有 bridge 来模拟上游。

主程序允许实现通用的 MCP transport 支持（例如 `stdio`、`unix_socket` 等）与标准协议会话管理，但这些能力必须是对任意标准 MCP server 通用的基础设施，不能退化为某个单独 Browser MCP / 站点 MCP 的专属硬编码适配层。

### 3. 招聘站点接入原则
在 core runtime / 主程序中，不得 hardcode `zhipin.com`、`BOSS` 或其它外部招聘站点的专属工具名、专属流程分支、专属适配器、专属下载链路、专属抓取/沟通代码路径，或其它等价的站点特化接入。

主程序只允许提供通用的招聘流程语义、通用 Browser MCP / MCP 协议桥接、通用持久化、审批、记忆、插件与技能装配能力。

具体站点接入必须由 Agent 在运行时基于通用工具完成，或通过运行时生成的 skill、以及经批准的学习产物来沉淀；不得在主程序 core 中预先把某个站点写死为一等公民。

### 4. 招聘平台页面打开与复用规则
对于 `zhipin.com` 或其它外部招聘平台页面，凡是 Agent 需要借助 human 当前正在使用的普通浏览器推进任务时，都必须先检查该普通浏览器中是否已经存在可复用的可执行页面。

这里的“普通浏览器”指非 AI 模式浏览器、非由主程序代持会话的特殊浏览器上下文；“可执行页面”指已经处于目标招聘平台上，且足以继续当前任务的活跃页面，例如 JD 列表页、JD 详情页、候选人列表页、候选人详情页或其它能直接承接后续动作的页面。

若普通浏览器中已存在可复用的可执行页面，Agent 必须优先复用该页面继续执行，不得无故切换到 AI 模式浏览器、额外创建特殊浏览器上下文，也不得把“先打开招聘平台页面”外包给 human 或外部开发代理。

若普通浏览器中不存在可复用页面，Agent 必须自行在普通浏览器中打开目标招聘平台并进入可执行页面，然后再继续后续任务，而不是默认要求 human 预先打开站点或代为导航。

若当前可用浏览器工具对 tab / page 的可见范围仅覆盖“当前窗口”而非整个普通浏览器，则该工具返回的“未发现目标页”只构成窗口级别证据，不构成“普通浏览器里完全没有目标页”的全局结论。在这种能力边界下，Agent 不得把“当前窗口未见目标页”直接等价为“可以新开一个招聘页”；应先把该限制视为浏览器工具作用域不足，并避免绕过可能已经打开的可复用页面。

只有在登录、验证码、权限、设备绑定或其它明确属于 human-only blocker 的情形下，Agent 才可以请求 human 协助。human 的职责是解除阻塞条件，而不是代替 Agent 完成本应由 Agent 自行完成的页面打开、站点进入或任务导航动作。

该规则适用于所有需要访问招聘平台页面的共享招聘场景，包括但不限于 `同步 JD`、`发现候选人` 及其后续页面内操作。主程序与 prompt 资产都不得把这条规则误写成只针对单一 JD 同步场景的特例。

### 5. browser-mcp 的保留边界
`browser-mcp` 在本项目中只保留给主程序内部 Agent 用于驱动外部网站的链路。

它不得被外部开发代理当作主程序 UI 的通用验收控制器，也不得被当作用来绕过主程序边界、直接代替内部 Agent 操作网页的开发捷径。

## 外部开发代理与 UI 验收边界
外部开发代理在验收主程序 UI 时，只能通过 `chrome-devtools` 操作主程序页面，包括桌面端窗口中的主程序 UI 或其等价浏览器承载页面。

外部开发代理不得直接使用 `browser-mcp` 操作主程序 UI，不得把 `browser-mcp` 当作桌面端验收、冒烟测试或组件联调的通用浏览器控制器。

如需验证主程序如何驱动外部网站，应通过主程序自身暴露的链路、状态和可见结果进行验收，而不是由外部开发代理直接拿 `browser-mcp` 越过主程序边界去模拟内部 Agent。

## 业务信息分层规范

Agent 运行过程中产生的信息，必须按以下三层归位，不得混用：

| 层 | 载体 | 职责 | 存什么 |
|----|------|------|--------|
| **任务定义层** | `scene_template`（`prompts/scene_templates/*.md`） | 定义目标模板 | `goal_kind`、title、goal_text、constraints、success_criteria、context_hints |
| **运行过程层** | `AgentRuntimeEvent.event_type` | 记录执行过程事件 | turn started、tool returned、model completed、waiting_human 等过程性事件 |
| **业务结果层** | `GoalSpec` / `AgentRun` 上的结构化字段 | 承载 human 关心的业务展示信息 | 当前目标、run 状态（blocked / running / completed）、本次业务类型（sync_jd / candidate_discovery / …）、created / updated / skipped 计数、当前 blocker、下一步建议 |

### 分层约束

- **展示层**读取业务状态，数据来源必须是 `GoalSpec` / `AgentRun` 的结构化结果字段，不得直接解析 `AgentRuntimeEvent` 事件流来拼凑业务摘要，也不得从 `scene_template` 定义直接推断运行中状态。
- **`AgentRuntimeEvent`** 只记录"发生了什么过程"，不承载"业务结果是什么"——`created=3`、`blocker=xxx`、`next_step=xxx` 这类业务结论不属于过程事件，应写入 `AgentRun` 的结构化结果字段。
- **`scene_template`** 是静态任务定义，不随运行状态变化——不得把运行时动态产生的结果（候选人数、阻塞原因、进度）写回 `scene_template`。

## 投递记录跟进粒度约束

### 1. 跟进、沟通与状态推进的执行主语
在招聘流程中，凡是涉及：

- 跟进
- 沟通
- 消息同步
- 阶段判断
- AI 评分
- 索要简历 / 联系方式
- 上下文隔离
- 子上下文 / subagent 绑定对象

默认都必须落在 `candidate_applications` 这一 application-scoped 投递记录粒度上，而不是 `CandidatePerson`。

`CandidatePerson` 只回答“这个人是谁”，不承载单次投递的 workflow 状态、消息线程、阶段判断与局部跟进历史。

### 2. 子上下文 / subagent 的绑定对象
若未来引入投递记录沟通 subagent、独立沟通线程、局部跟进子上下文或其它等价机制，其绑定对象必须是一条明确的 `candidate_application` 记录。

主程序不得把“某候选人名下所有 JD / 所有沟通 / 所有历史消息”混装进同一个跟进上下文里；真正被隔离和被推进的，必须是一条投递记录。

### 3. 对外语言口径
产品、prompt、评审、实现说明与 UI/API 文案中，若在讨论实际流程推进对象，应优先使用“某次投递记录的跟进”“该投递记录的沟通线程”“该投递记录状态”等表达。

不得用“候选人跟进”去指代真正的执行对象，再由读者自行脑补 JD 归属或 application 边界。

## Scene Context 运行时对象约束

### 1. `ExecutionEpisode` 的语义边界
`ExecutionEpisode` 必须被建模为一次**通用环境执行实例**，而不是“网页 episode”“浏览器 episode”或某种站点专用执行对象。

它承载的是某次隔离环境执行的 `observations / actions / result_summary / metrics / last_error`，并通过显式 execution contract 约束该次执行的边界，例如：
- `execution_kind`
- `summary_scope`
- `evidence_scope`
- `memory_policy`
- `learning_policy`

其中，scene context 默认必须是：
- `execution_kind = generic_environment_execution`
- `summary_scope = business_summary_only`
- `evidence_scope = episode_scoped`
- `memory_policy = disabled`
- `learning_policy = disabled`

主程序不得把 `ExecutionEpisode` 的核心语义写窄成“只适用于浏览器抓取”的容器；未来即便环境来源变成图片、Excel、文档、终端或其它外部环境，该对象语义也必须保持成立。

### 2. `EnvironmentSnapshot` 的语义边界
`EnvironmentSnapshot` 必须被建模为**通用环境证据快照**，而不是“页面快照”专属对象。

它记录的是对当前执行环境的结构化观察结果，最小稳定口径应围绕：
- `environment_kind`
- `display_label`
- `resource_locator`
- `observed_entities`
- `action_hints`

`EnvironmentSnapshot` 可以承载来自浏览器页面、图片、文档、表格、终端会话或其它环境的证据，但主程序不得再把它的核心字段命名、schema 或摘要逻辑固化为 URL / 页面标题 / 页面类型 / affordances 这类浏览器专属表述。

浏览器只是 `EnvironmentSnapshot` 的一种来源，不得成为该对象的定义中心。

## 共享业务能力与场景模板规范
### 1. 共享招聘能力暴露方式
`同步 JD`、`发现候选人`、`AI 评分` 等共享招聘业务能力，必须通过通用 `plugin / toolkit / MCP / tool surface` 暴露给 Agent。

这些能力不应建模成某个 Agent 私有的“业务动作目录”、私有能力清单或需要单独注入给特定 Agent 的特殊挂载层。`Assistant` 与 `Autonomous` 的差异应体现在目标、记忆、生命周期与执行策略上，而不应体现在是否单独拥有某项共享招聘能力。

### 2. 共享场景模板与任务描述定位
共享场景模板、任务描述页面或跨 Agent 复用的业务规范，应被建模为 `Autonomous`、`Assistant` 等 Agent 可复用的任务描述提示词、规范页面或 prompt 资产。

它们的职责是描述任务语义、上下文要求、完成标准与交互边界，而不是伪装成抽象工具项混入工具区语义。

凡是本质上属于“任务如何做、在什么前提下做、何时算完成”的共享描述，应进入 prompt / 规范资产，而不是被错误包装为工具定义、工具名或工具枚举项。

## Goal / Run / Session 契约约束

### 1. GoalSpec 与 AgentRun 的关系
一个 GoalSpec 可以对应多个 AgentRun（重试、续跑、阶段性补充执行）。GoalSpec 通过 `latest_run_id` 跟踪最近一次执行，不限制历史 run 数量。

run 是执行历史记录，不是 goal 的等价替换体。每次重试或续跑应创建新 run，不得复用同一 run 记录以覆盖历史。

### 2. conversationId 的语义约束
对外暴露的 `conversationId`（无论在 API 响应、前端状态、context_manifest 还是 runtime_metadata 中）必须是 `AgentSession.id`（主 conversation / 主 session 的 ID），不得使用 `GoalSpec.id`。

`GoalSpec.id` 应作为独立字段（`goalId`）单独暴露，语义是"这次 run 对应的目标"，而不是"这次会话的身份"。

### 3. workspace API 的 conversation 粒度
workspace API 中 Autonomous 的 conversations 列表，每个 Autonomous Agent profile 最多返回一条 conversation 记录，对应其唯一主 session。

goals 应作为该 conversation 的 nested 结构（如 `goals: [...]` 子字段）返回，而不是被展开为多条独立 conversation 条目。每条 goal 条目内可含 `latest_run`、`status`、`last_activity_at` 等摘要。

## 变更原则
对 Autonomous 生命周期、主 conversation、run 并发、Global Memory 口径、prompt 落点、站点接入、UI 验收边界和共享能力建模的任何变更，都应把本文档视为先行约束。

若实现需要偏离本文档，必须先明确变更的是哪条约束，再同步更新本文档与相关索引，而不是让实现先行漂移、事后再补说明。

新增规范时，应优先补充长期稳定、跨实现复用的约束；不要把临时故障、一次性 workaround、环境现状或阶段性执行细节写入本文档。

涉及核心产品语义、对象边界、UI/API 口径或文档主叙事时，默认不得凭空引入新的概念名词。应优先复用项目里已经存在并经确认的概念；若确实需要新增概念，必须先与用户确认，并说明其必要性、影响范围与引入价值后，才允许进入实现与规范。
