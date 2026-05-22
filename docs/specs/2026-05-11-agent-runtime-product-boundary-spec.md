# Agent Runtime 与产品边界规范

## 范围

本文是 Agent runtime、AgentDefinition、产品 adapter、Assistant / Autonomous、能力演进和审批治理的合并规范，也是这些主题的唯一长期规则来源。历史 design 文档已合并进本文并移除，避免 design / specs 双源漂移。

## 核心原则

`services/backend/src/recruit_station/agent_runtime/**` 必须保持业务无关。

核心系统约束：

- `Turn` 是唯一的 runtime 执行完成 / 中断 / 失败单位；`turn_completed`、`turn_interrupted`、`turn_failed` 不表达 conversation / session / run 容器生命周期。
- Assistant conversation 与 Autonomous `AgentRun` 都是可复用的 product container / projection。除归档、删除、显式取消或中断这类产品生命周期动作外，普通 Turn 完成后容器必须保持可继续状态。
- `completed` 可以用于 Turn、objective、workflow artifact、business event 或审计记录；不得作为可复用 conversation / session / run 容器的默认生命周期状态。
- 如果产品需要表达“目标已完成”，必须写入明确的 objective / workflow / business artifact 或最终消息 / 事件，不得通过 `turn_completed -> AgentRun.status=completed` 隐式推导。
- `cancelled` / `interrupted` 是不可重入中断态，product adapter 必须阻止迟到 queue envelope、tool result 或 model result 把它们写回 `running`、`waiting_human`、`idle` 或其他可继续状态。

Agent runtime 只负责 Agent 本身的职责：

- `InteractionEngine`
- `Turn`
- `LLMInvocation`
- `LLMRequest` / `LLMResponse` / `LLMStreamEvent`
- `ConversationHistory` / `Transcript`
- `ToolDefinition` / `ToolSchema` / `ToolUse` / `ToolCall` / `ToolResult`
- `InteractionOutput`
- model backend contract
- 通用 tool loop、permission check、MCP tool/resource 接入规则

Agent runtime 不负责招聘业务、产品状态、UI、API、数据库模型、业务 projection 或站点接入。

## AgentDefinition 契约

`AgentDefinition` 是底层唯一的 Agent 定义契约。它描述一个 Agent 实例进入 runtime 前需要被装配的定义内容，但不引入产品分支或业务对象。

允许表达的定义内容包括：

- identity / persona / prompt
- duties / boundaries / success criteria
- business strategy / domain policy
- tool scope / allowed tool policy
- permission policy / output policy / budget policy
- memory / skill / MCP policy
- model and runtime assembly metadata

不同 `AgentDefinition` 可以有不同的 prompt、身份、职责、边界、工具范围和治理策略。差异来自定义内容，不来自 duplicated runtime class、Assistant/Autonomous 专用 runtime 或多套 tool loop。

`AgentDefinition` 不是 Assistant / Autonomous 的同义词。Assistant 与 Autonomous 是产品类型和 product adapter，负责用户入口、生命周期、状态投影和持久化记录；它们可以各自装配不同的 `AgentDefinition`，但进入 runtime 后必须使用同一套 assembly、runner、permission、status、tool loop、transcript 和 output 语义。

核心约束：

- `AgentDefinition` 表达 Agent 的身份、职责、边界、system prompt、业务策略、tool scope、memory / skill / MCP policy。不同 Agent 的这些定义内容可以不同。
- Assistant / Autonomous 不能作为第二套 Agent 定义来源；它们只能提供 adapter context、lifecycle config、IO projection、trigger / wakeup / resume / writeback 配置。
- Product mode 可以注入运行提示，例如 chat response style 或 durable run output contract，但不能覆盖 `AgentDefinition` 中的 identity、duties、boundaries 或 tool governance。
- Shared assembly 必须统一处理 system prompt placement、history、turn input、product context、memory、skills、MCP resources、tool registry、permission metadata 和 limits。
- Shared runner 必须统一输出 final output、status、gate signal、tool calls / results、permission request 和 runtime events。
- Prompt / instruction 只能表达角色、边界、完成标准、恢复规则和输出合同这类稳定规则；运行中观察到的数量、职位名、候选人名、页面摘要、推断进度、上一轮局部结果等动态数据必须进入结构化 context / result_data / tool result，不得拼回 system prompt、续跑 instruction 或 scene instruction。
- 续跑 / 恢复 prompt 必须是规则化的，不得写成“已完成 1/5、剩余 4 个、继续打开某几个职位”这类由历史摘要推断出的具体事实。具体进度只能由最新工具观察或结构化状态字段提供，并且必须可被证据重新验证。

禁止：

- 新增 `AssistantDefinition`、`AutonomousDefinition` 或其他产品专用 Agent 定义契约
- 在 `agent_runtime/**` 中用 Assistant / Autonomous 作为分支条件
- 把产品类型、run 状态、业务状态或 UI 状态写入 `AgentDefinition`
- 为不同产品类型复制 runner、permission、status、tool loop、transcript 或 output 语义

## 分层

```text
Product / UI / API
  -> product adapter
  -> business capability layer
  -> business-agnostic Agent runtime
  -> model / tool / MCP infrastructure
```

### Agent runtime core

允许：

- 管理 conversation-scoped engine
- 创建和运行 Turn
- 发起 LLMInvocation
- 执行 ToolCall
- 产出 InteractionOutput
- 维护 history 和 transcript

禁止：

- 导入 candidate、application、JD、resume、interview、score、outreach 等业务对象
- 硬编码招聘 workflow、站点规则、selector、页面结构或业务策略
- 直接读写业务数据库、memory、projection、API route
- 认识 `Assistant`、`Autonomous`、`AgentRun`、`AgentTurnRecord`
- 把产品 run 状态或业务状态写成 runtime 状态

### Product adapter

允许：

- 管理 Assistant / Autonomous 产品身份
- 管理 `AgentRun`、`AgentTurnRecord`
- 接收、校验并持久化 Autonomous run 的 canonical `instruction`
- 构造 UserInput、system context、run context、memory references、allowed tools
- 调用 `InteractionEngine.submitMessage(...)`
- 将 `InteractionOutput` 映射到 SSE、runtime event、approval、run state、business projection
- 在边界层处理旧 API 兼容；兼容字段不得进入 runtime core

### Business capability layer

允许：

- prompt / skill / plugin / MCP / tool
- 招聘业务 service / repository / projection
- 业务审批、业务结果、业务数据治理

这些能力可以包含招聘业务语义，但必须通过 adapter-built context、tool schema、tool result、prompt、skill、plugin 或 MCP 进入 Agent 执行。

### 能力接入口

Agent runtime 不为 MCP、skill、memory、业务 context 定义新的 runtime primitive，也不把它们列为核心 Agent 能力。这个边界 follow Claude Code / Codex：skill 由外层发现、选择、加载、注入上下文；MCP tool/resource 通过 tool/resource 机制接入；memory 是产品状态和策略，不是 runtime state。

- MCP tool：发现后注册为普通 `ToolDefinition`，执行时走 `ToolCall` / `ToolResult`。
- MCP resource：通过 context 构造或 `list/read resource` 普通工具访问，不把每个 resource 展开成工具。
- skill：由 adapter 选择并渲染进 context / structured input；需要 fork 执行时由产品 adapter 或 command layer 启动 isolated engine，但不向模型暴露通用 skill execution 工具，runtime 不认识 `skill` 类型。
- memory：follow Claude Code 的文件型 memory 口径。读 memory 可以通过 memory context、`read_memory` 或受限 memory tools 暴露给模型；用户显式要求记住/忘记时，模型可在主 Turn 内使用受限 memory tools 更新 memory 文件；自动提炼、压缩由 Turn 外 memory pipeline 负责。runtime 只维护 history/transcript，不认识 memory store。
- business context：由 adapter 读取业务状态、UI state、run state 后构造为 messages/context，runtime 不定义业务 context 类型。

### Context / memory 管理边界

runtime、adapter、Agent file memory、业务 context/knowledge 的职责必须分开：

- runtime history：`ConversationHistory` 是模型上下文的 materialized history。compact / rollback / context replacement 只能替换 `ConversationHistory` 并同步 `Transcript`，不得读写候选人、JD、投递、沟通、评分或全局业务 context/knowledge。
- product adapter context construction：adapter 在 Turn 前读取 `AgentRun`、canonical run `instruction`、UI state、skill metadata/content、business context/knowledge references、MCP resource、allowed tools 和权限策略，构造 `UserInput`、system context、run context 与 `ToolDefinition[]`。
- memory update：用户显式要求记住/忘记时，模型在主 Turn 内通过受限 memory tools 写入 memory scope；工具事件由 adapter/UI 投影为“记忆已更新”。这不是业务 tool，也不是 runtime primitive。
- memory extraction / compaction：后台 memory pipeline 可在 Turn 后从 `InteractionOutput`、`ToolResult`、最终 assistant message 和业务服务结果中抽取稳定事实，按产品策略做去重、冲突检测、审批或写回 memory 文件；这不是 runtime 能力，也不是 final answer 隐式 JSON 协议。
- skill context injection：adapter 选择 relevant skills，并把 skill name、description、trigger hint、instructions、schemas 等压缩成模型可见 context；runtime 只看到普通 message/input。
- scene / sub-context isolation：外部网页和 HID 这类复杂执行必须通过 scene tool 的 output contract 与 result_data 隔离。父 Agent 看到的是结构化结果、blocker、evidence refs 和必要状态，不应把 scene 的自然语言摘要作为下一轮规则来源。

Agent runtime 不定义 skill catalog、memory store、MCP registry 或 capability source 的专用抽象。上述来源在 runtime 内都只能表现为 messages、`ToolDefinition`、tool result、permission context、metadata 或 transcript/output 记录。

### 能力闭环清单

以下清单定义方案层面的完整性边界。某项能力“完整”不表示它进入 Agent runtime 类型系统，而表示产品层、adapter 层、业务服务层或基础设施层已经有从加载到治理的闭环。

#### Memory

Memory 是产品状态和业务策略，不是 runtime state。

必须具备：

- 读取 / 加载：按 agent、scope、scope ref 读取候选人、JD、全局或会话摘要；可按语义检索筛选。
- 上下文投射：adapter 按 context policy、memory policy、token 预算和 disclosure 策略，把必要 memory 投射成 system/user context 或 structured payload。
- 显式更新 / 删除：当用户要求记住或忘记时，主 Turn 内可使用受限 memory tools 直接更新 memory scope 下的 markdown 文件，UI 按 memory tool event 展示。
- 自动提炼 / 写回：Turn 后由后台 memory pipeline 先用配置化资源 gate 判断是否需要启动 memory job，再由独立 LLM/策略判断是否存在稳定事实，最后写入 memory 文件。不能每个 completed Turn 默认调用一次 memory LLM。
- 压缩：长期 memory 超过策略阈值后由产品 memory compactor 生成 summary、facts、decisions、open questions、next actions、risk flags、evidence refs 等结构化内容；压缩结果仍写回 memory 文件。
- 治理：长期 memory 只保存跨 run 可复用的稳定事实；临时页面状态、当前 blocker、一次性 tool payload 或 UI 状态不得进入长期 memory。

当前实现状态：

- `MemoryFileStore` 以 markdown 文件保存 Agent file memory，并按 AgentDefinition、scope、scope ref 隔离。
- `read_memory`、`list_memory_files`、`read_memory_file`、`write_memory_file`、`delete_memory_file` 是 memory tools，不是业务工具，也不是 runtime primitive；runtime 只看到普通 ToolDefinition / ToolCall / ToolResult。
- Assistant 与 Autonomous adapter 使用同一套 file-memory 读写模型；差异只来自 AgentDefinition、conversation/session 和 adapter 配置隔离。
- Autonomous adapter 可在 Turn 后按配置化 gate 选择性触发 memory extraction/compaction pipeline；该 pipeline 独立判断是否产生 stable facts，不能把 final answer 当作隐藏 `memory_patch` 协议。

当前方案缺口：

- 自动 memory 更新仍是产品层能力，默认不需要审批，review policy 可选开启；触发必须先经过配置化 gate，避免每个 completed Turn 默认调用 memory LLM。
- Assistant 的会话摘要有轻量 compaction，但不是业务 context/knowledge 更新流水线。

#### MCP

MCP 是工具和资源来源，不是 runtime 配置类型。

必须具备：

- 注册 / 配置：支持 preset、server CRUD、transport/protocol/auth metadata。
- 发现 / 同步：标准 MCP 通过 `tools/list` 发现工具并同步为产品 tool registry 项。
- 执行：MCP tool 进入 runtime 前已转换为普通 `ToolDefinition`；执行时只走 `ToolCall` / `ToolResult`。
- 健康 / 恢复：支持 health check、transient retry、失败标记和 runtime registry reload。
- Resource：resource 不按“每个 resource 一个 tool”展开；通过 adapter context 注入，或通过 list/read resource 普通工具读取。

当前实现状态：

- MCP registry 支持 preset install、server CRUD、tool discovery、runtime tool registration、tool invocation、health check 和 server reconcile。
- browser / HID 这类 MCP 工具的线性执行约束在 MCP bridge/registry 层完成，runtime 仍只看到普通 tool。
- 标准 MCP resource 通过固定 `list_mcp_resources` / `read_mcp_resource` 普通产品工具访问；不把每个 resource 展开成 runtime tool。

当前方案缺口：

- MCP resource context builder 可继续产品化；不能因此新增 MCP 能力来源 provider、MCP 专用 runtime tool 类型、MCP resource flow 或 runtime MCP 连接类型。

#### Context

Context 分为 runtime history、adapter context construction、Agent file memory context 和业务 context/knowledge，四者不能互相替代。

必须具备：

- Turn 前加载：adapter 汇总 `AgentRun`、canonical run `instruction`、UI state、allowed tools、skill injections、business context/knowledge refs、memory file refs、MCP resource、权限策略。
- 历史管理：runtime 只管理 `ConversationHistory` / `Transcript` 的 materialized messages，可执行 history compaction、replace、resume。
- 预算管理：adapter 和 runtime config 共同控制 token/message 预算；业务 context 超预算时按 context policy drop 或压缩。
- 压缩事件：runtime history 压缩只产出 context_compacted runtime event；Agent file memory 压缩由 memory pipeline / file tools 处理；业务 context/knowledge 压缩不得冒充 runtime memory。

当前实现状态：

- `InteractionEngine` 支持 `max_history_messages` 和 deterministic history compaction，并同步 transcript。
- Assistant 默认配置 `max_history_messages`，并通过 runtime history compaction 控制模型可见历史。
- Assistant session store 有会话摘要与 compaction event。
- AgentDefinition 提供 context policy / memory policy，Autonomous adapter 在 Turn 前构造 instruction/world/memory/skill context。

当前方案缺口：

- context builder 仍分散在 Assistant/Autonomous/scene adapter 中，后续应收敛为 adapter 层 policy-driven construction，但不能变成 runtime capability source abstraction。

#### Skill

Skill 是可加载的能力说明、指令和资产，不是 runtime primitive。

必须具备：

- 发现 / 管理：支持 skill CRUD、草稿、学习候选、审核、批准、激活、降级、禁用。
- 选择 / 加载：adapter 按显式提及、状态、trigger hint、任务类型或产品策略选择 relevant skills。
- 注入：将 name、description、trigger hint、instructions、schema、metadata 渲染成模型可见 context。
- 治理：skill 健康检查、人工审核、trial/active 状态和来源约束由产品层负责。
- Fork：如需独立 token budget / isolated context，只能由 command layer 或 product adapter 启动 isolated engine；不得给模型暴露通用 skill execution tool。

当前实现状态：

- skill API 支持 CRUD、learning draft、review/approve/activate、health check/sweep。
- skill context injection 会按 active/trial、显式 skill id、query/task text、category、trigger hint 和 metadata trigger examples 选择并渲染进 Autonomous context。
- 通用 skill execution API 已移除；runtime 不认识 skill 类型。

当前方案缺口：

- Skill selection 后续仍可增强 token budget 策略和更精细的显式提及解析。
- forked skill/command execution 如需恢复，应作为外层 command/adapter 能力设计，不作为 runtime 内 skill branch。

## 产品类型与 Assistant / Autonomous

Assistant 与 Autonomous 是产品类型和 product adapter，用来决定用户入口、触发方式、生命周期、状态投影、持久化记录和交互体验，不是两套 runtime，也不是两套 Agent 定义契约。

- Assistant：interactive human-facing product adapter，负责临时任务、conversation/session、confirm/cancel、UI/SSE 映射。
- Autonomous：long-running human-facing product adapter，负责长期配置、业务事件/定时/用户触发、durable run、checkpoint、approval、运行中用户干预和状态投影。

二者共享同一个业务无关的 Agent runtime。差异只在 product adapter、记忆策略、触发方式、权限策略和状态表达。

二者可以装配不同的 `AgentDefinition`。例如 prompt、identity、duties、boundaries、tool scope、permission policy 和 output policy 可以不同；但这些差异必须在定义内容和 adapter 装配层表达，不能演变成 Assistant runtime、Autonomous runtime 或产品专用 AgentDefinition class。

进入 runtime 前，两个 adapter 都必须归一为现有执行输入：

- prompt / system context
- user message、Autonomous run instruction 或业务事件摘要
- history / context
- memory snippets
- skill instructions
- tool definitions
- permission policy metadata
- budget

`assistant/autonomous` 不得作为 runtime 分支条件，不得作为 memory scope 的替代，也不得被用来引入两套 assembly、runner、tool loop、context、permission、status、transcript 或 output 实现。

### Product Adapter Core Parity Contract

Assistant 与 Autonomous 的 product adapter 可以在入口、触发方式、持久化 / projection、context construction 上不同；这些差异不得造成 runtime turn lifecycle 能力漂移。二者必须保持以下核心能力等价：

- 通过共享 `run_agent_turn` / `InteractionEngine` 进入同一套 Turn、tool loop、permission、transcript 和 output 语义。
- `engine_sink` 必须绑定当前 active engine，使 adapter 外层的取消、审批恢复和事件投影都回到同一个等待中的 `InteractionEngine`。
- 取消 / Esc 的 canonical primitive 是 `InteractionEngine.interrupt`；adapter 只能把产品入口事件映射到该 primitive，不得复制另一套取消状态机。
- permission resume 必须由当前等待中的 `InteractionEngine` 继续执行原 `ToolCall`、记录 `ToolResult`、追加 tool message 并续跑同一个 Turn；adapter 不得手工拼接 provider history 或伪造工具恢复语义。
- status、gate signal、tool call / result、runtime event 必须有明确且成对的 Assistant / Autonomous 映射；产品文案和投影可以不同，底层含义不得分叉。
- `turn_completed` 只能直接表示当前 Turn 完成；不得默认把可复用的 conversation / session / run 容器写成 `completed`。objective / workflow finalization 只能写入明确的 objective / workflow / business artifact、最终消息或事件，不得复用可继续容器的生命周期状态。
- 产品 adapter 定义的 hard-terminal state writeback 必须有 guard，避免已取消、已中断或其他不可重入状态被迟到事件重新写成 running、waiting 或其他非终态。若 adapter 允许同一个 run / session 承载连续 phase，必须明确哪些状态可重入，不能把可重入的 phase-complete 状态误当成硬终态。
- 涉及上述 lifecycle 能力的改动必须补 parity tests，覆盖 Assistant 与 Autonomous 两个 adapter 的同类行为。

保持该契约时，runtime 仍必须业务无关：不得为了 parity 把产品入口、`AgentRun` / `AgentTurnRecord`、招聘对象、招聘 workflow、projection 或 UI 状态放入 `agent_runtime/**`。这些概念只能存在于 product adapter、business capability layer、tool、skill、plugin、MCP、prompt 或业务服务中。

## 业务 tool

招聘业务流转、业务数据创建、处置和读取必须通过 business tool 进入 Agent。

业务 tool 属于 business capability layer 或 plugin layer，可以包含 candidate、application、JD、resume、outreach、score、review、sync 等业务语义。Agent runtime 只看到普通 tool schema、tool call、tool result 和 metadata。

业务 tool 必须能表达：

- 所属业务域。
- 读写能力。
- 目标资源类型。
- 权限/审批要求。
- 返回结果契约。

不得把招聘 workflow、业务状态机、数据创建逻辑或外部副作用写入 `agent_runtime/**`。

## 语义边界

- `Turn` 是 runtime 执行单位。
- `LLMInvocation` 是 Turn 内模型调用。
- `ToolCall` 是 Turn 内工具调用。
- `InteractionOutput` 是 runtime 输出流/信封。
- `AgentRun` 是 Autonomous product container / projection，用于承载 run/session 级持久化视图、queue/checkpoint/event 聚合和 turn 审计关联；它不是 runtime 执行单位，也不得用普通 Turn 完成隐式写成 `completed`。
- `AgentTurnRecord` 是产品审计记录。

Autonomous run 的人类意图只使用 canonical `instruction` 表达。不得重新引入旧意图规格、独立工作项表、自动化指令别名或模板化指令字段作为产品或 runtime 契约。

这些概念不能互相替代。

## 能力演进顺序

Agent 表现不好时，按以下顺序修复：

1. 结构化上下文
2. prompt / instruction
3. tool schema / tool result contract
4. tool / plugin / MCP capability
5. skill
6. product adapter 的状态映射、审批或 memory 策略
7. 只有 runtime 抽象本身错误时，才修改 `agent_runtime/**`

不要通过 runtime 代码替 Agent 做业务决策。

## 审批治理

审批由 tool governance 和 product adapter 承担。

Runtime 可以产出通用 permission request；product adapter 创建审批记录、展示 human-facing 信息，并把 human 决策映射回 pending tool / run。

审批恢复必须回到当前等待中的 `InteractionEngine`。runtime 自己执行原 `ToolCall`、记录 `ToolResult`、追加 tool message，并继续同一个 Turn 的后续 LLM loop。product adapter 不得手工构造 provider assistant/tool history 来模拟已批准工具结果。

不得把招聘审批流程写成 runtime core 状态机。

## 禁止重新引入

以下概念不得作为有效架构重新出现：

- 历史 kernel 类抽象
- stage pipeline runtime
- `run_round`
- `RoundOutcome`
- legacy intent reference
- `Deliberation`
- standalone `Interaction` execution unit
- 额外 execution-unit runtime primitive
- `max_turns` 作为 LLM invocation budget

## 验收

涉及 Agent 架构的改动，至少检查：

1. `agent_runtime/**` 是否仍然业务无关。
2. 新业务规则是否落在 prompt、skill、plugin、tool、MCP、product adapter 或 business service。
3. `InteractionEngine`、`Turn`、`LLMInvocation`、`ToolCall`、`InteractionOutput` 的语义是否未被产品层反向改写。
4. Assistant / Autonomous 是否仍共享同一个 runtime。
5. 兼容字段是否在 adapter 层终止。
