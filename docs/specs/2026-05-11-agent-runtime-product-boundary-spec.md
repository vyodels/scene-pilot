# Agent Runtime 与产品边界规范

## 范围

本文是 Agent runtime、产品 adapter、Assistant / Autonomous、能力演进和审批治理的合并规范。具体 runtime 类型和协议细节以 [`../design/agent-core/00-agent-runtime-technical-design.md`](../design/agent-core/00-agent-runtime-technical-design.md) 为唯一设计源；Agent type、product adapter 与业务 tool 边界以 [`../design/agent-core/01-agent-types-and-product-adapters.md`](../design/agent-core/01-agent-types-and-product-adapters.md) 为落地设计。

## 核心原则

`services/backend/src/recruit_agent/agent_runtime/**` 必须保持业务无关。

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
- 认识 `Assistant`、`Autonomous`、`GoalSpec`、`AgentRun`、`AgentTurnRecord`
- 把产品 run 状态或业务状态写成 runtime 状态

### Product adapter

允许：

- 管理 Assistant / Autonomous 产品身份
- 管理 `GoalSpec`、`AgentRun`、`AgentTurnRecord`
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
- memory：follow Claude Code 的文件型 memory 口径。读 memory 可以通过 memory context、`read_memory` 或受限 memory file tools 暴露给模型；用户显式要求记住/忘记时，模型可在主 Turn 内使用受限 memory file tools 更新 memory 文件；自动提炼、压缩由 Turn 外 memory pipeline 负责。runtime 只维护 history/transcript，不认识 memory store。
- business context：由 adapter 读取业务状态、UI state、run state 后构造为 messages/context，runtime 不定义业务 context 类型。

### Context / memory 管理边界

runtime、adapter、Agent file memory、业务 context/knowledge 的职责必须分开：

- runtime history：`ConversationHistory` 是模型上下文的 materialized history。compact / rollback / context replacement 只能替换 `ConversationHistory` 并同步 `Transcript`，不得读写候选人、JD、投递、沟通、评分或全局业务 context/knowledge。
- product adapter context construction：adapter 在 Turn 前读取 `GoalSpec`、`AgentRun`、UI state、skill metadata/content、business context/knowledge references、MCP resource、allowed tools 和权限策略，构造 `UserInput`、system context、run context 与 `ToolDefinition[]`。
- memory file update：用户显式要求记住/忘记时，模型在主 Turn 内通过受限 memory file tools 写入 memory scope；工具事件由 adapter/UI 投影为“记忆已更新”。这不是业务 tool，也不是 runtime primitive。
- memory extraction / compaction：后台 memory pipeline 可在 Turn 后从 `InteractionOutput`、`ToolResult`、最终 assistant message 和业务服务结果中抽取稳定事实，按产品策略做去重、冲突检测、审批或写回 memory 文件；这不是 runtime 能力，也不是 final answer 隐式 JSON 协议。
- skill context injection：adapter 选择 relevant skills，并把 skill name、description、trigger hint、instructions、schemas 等压缩成模型可见 context；runtime 只看到普通 message/input。

Agent runtime 不定义 skill catalog、memory store、MCP registry 或 capability source 的专用抽象。上述来源在 runtime 内都只能表现为 messages、`ToolDefinition`、tool result、permission context、metadata 或 transcript/output 记录。

### 能力闭环清单

以下清单定义方案层面的完整性边界。某项能力“完整”不表示它进入 Agent runtime 类型系统，而表示产品层、adapter 层、业务服务层或基础设施层已经有从加载到治理的闭环。

#### Memory

Memory 是产品状态和业务策略，不是 runtime state。

必须具备：

- 读取 / 加载：按 agent、scope、scope ref 读取候选人、JD、全局或会话摘要；可按语义检索筛选。
- 上下文投射：adapter 按 context policy、memory policy、token 预算和 disclosure 策略，把必要 memory 投射成 system/user context 或 structured payload。
- 显式更新 / 删除：当用户要求记住或忘记时，主 Turn 内可使用受限 memory file tools 直接更新 memory scope 下的 markdown 文件，UI 按 memory tool event 展示。
- 自动提炼 / 写回：Turn 后由后台 memory pipeline 先用配置化资源 gate 判断是否需要启动 memory job，再由独立 LLM/策略判断是否存在稳定事实，最后写入 memory 文件。不能每个 completed Turn 默认调用一次 memory LLM。
- 压缩：长期 memory 超过策略阈值后由产品 memory compactor 生成 summary、facts、decisions、open questions、next actions、risk flags、evidence refs 等结构化内容；压缩结果仍写回 memory 文件。
- 治理：长期 memory 只保存跨 run 可复用的稳定事实；临时页面状态、当前 blocker、一次性 tool payload 或 UI 状态不得进入长期 memory。

当前实现状态：

- `MemoryFileStore` 以 markdown 文件保存 Agent file memory，并按 agent profile、scope、scope ref 隔离。
- `read_memory`、`list_memory_files`、`read_memory_file`、`write_memory_file`、`delete_memory_file` 是 memory subsystem tools，不是业务工具，也不是 runtime primitive；runtime 只看到普通 ToolDefinition / ToolCall / ToolResult。
- Assistant 与 Autonomous adapter 使用同一套 file-memory 读写模型；差异只来自 agent profile、conversation/session 和 adapter 配置隔离。
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

- Turn 前加载：adapter 汇总 GoalSpec、AgentRun、UI state、allowed tools、skill injections、business context/knowledge refs、memory file refs、MCP resource、权限策略。
- 历史管理：runtime 只管理 `ConversationHistory` / `Transcript` 的 materialized messages，可执行 history compaction、replace、resume。
- 预算管理：adapter 和 runtime config 共同控制 token/message 预算；业务 context 超预算时按 context policy drop 或压缩。
- 压缩事件：runtime history 压缩只产出 context_compacted runtime event；Agent file memory 压缩由 memory pipeline / file tools 处理；业务 context/knowledge 压缩不得冒充 runtime memory。

当前实现状态：

- `InteractionEngine` 支持 `max_history_messages` 和 deterministic history compaction，并同步 transcript。
- Assistant 默认配置 `max_history_messages`，并通过 runtime history compaction 控制模型可见历史。
- Assistant session store 有会话摘要与 compaction event。
- Recruit agent profile 提供 context policy / memory policy，Autonomous adapter 在 Turn 前构造 goal/world/memory/skill context。

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

## Agent type 与 Assistant / Autonomous

Assistant 与 Autonomous 是 Agent type，用来决定 Agent 的配置方式和执行机制，不是两套 runtime。

- Assistant：interactive human-facing product adapter，负责临时任务、conversation/session、confirm/cancel、UI/SSE 映射。
- Autonomous：long-running human-facing product adapter，负责长期配置、业务事件/定时/用户触发、durable run、checkpoint、approval、运行中用户干预和状态投影。

二者共享同一个业务无关的 Agent runtime。差异只在 product adapter、记忆策略、触发方式、权限策略和状态表达。

进入 runtime 前，两个 adapter 都必须归一为现有执行输入：

- prompt / system context
- user message、objective 或业务事件摘要
- history / context
- memory snippets
- skill instructions
- tool definitions
- permission policy metadata
- budget

`assistant/autonomous` 不得作为 runtime 分支条件，不得作为 memory scope 的替代，也不得被用来引入两套 tool loop、context、permission 或 transcript 实现。

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
- `AgentRun` 是产品执行历史。
- `AgentTurnRecord` 是产品审计记录。
- `GoalSpec` 是产品目标规格。

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
- `GoalRef`
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
