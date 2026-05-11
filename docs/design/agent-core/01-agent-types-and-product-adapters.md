# Agent Type 与 Product Adapter 设计

## 结论

Recruit Agent 只有一套业务无关的 Agent runtime。`assistant` 与 `autonomous` 是 Agent type，用来决定产品层配置、触发方式、生命周期、状态治理和 UI/API 表达，不是两套 runtime，也不是新的执行单位。

```text
Agent runtime
  InteractionEngine / turn / tool loop / transcript / context compaction / permission output

Agent type
  assistant   -> 临时任务型产品适配
  autonomous  -> 常态化复杂任务型产品适配

Business tools
  recruit 业务读取、创建、流转、处置能力通过 ToolDefinition 暴露
```

## Runtime 边界

Agent runtime 只接收现有执行输入并产出现有 output protocol：

- `InteractionEngine.submitMessage(...)`
- `InteractionEngine.resolvePermission(...)`
- `LLMMessage`
- `ToolDefinition`
- `ToolUse` / `ToolCall` / `ToolResult`
- `InteractionOutput`

Runtime 不感知 `assistant`、`autonomous`、招聘业务、MCP registry、skill catalog 或 memory store。MCP、skill、memory、业务数据都必须在产品 adapter 层转换成现有的 messages、tools、tool results 或 metadata。memory follow Claude Code 的文件型口径：显式记住/忘记可以通过受限 memory file tools 在主 Turn 内更新 markdown memory；自动提炼、压缩由 Turn 外产品 pipeline 选择性启动。

不要新增独立的执行层、能力来源 provider、skill runtime 类型、MCP runtime 类型、memory runtime 类型，或第二套 tool-result continuation API。tool result 已经属于 runtime 的 output protocol。LLM provider 是模型调用协议，不属于这里禁止的能力来源抽象。

## Agent Type

Agent type 是产品配置字段，不是 runtime type。

```text
Agent
  id
  type: assistant | autonomous
  prompt/profile
  memory scope
  skill/context policy
  tool policy
  execution config
```

### assistant

`assistant` 用于临时性任务：

- 用户打开聊天窗口后运行。
- 用户消息是主触发源。
- conversation/session 是主要隔离单元。
- 输出面向聊天 UI/SSE。
- 人通常在线，可以即时确认、取消、补充信息或纠偏。

### autonomous

`autonomous` 用于常态化复杂任务：

- 用户打开配置窗口或运行控制台后管理。
- 长期 profile/prompt/policy 描述它负责的招聘工作流。
- 可以由用户、定时器、业务事件或人工恢复动作触发。
- 每次触发仍进入同一套 `InteractionEngine.submitMessage(...)`。
- 产品 adapter 负责 durable run、checkpoint、approval、运行中用户干预、状态投影和通知。

Autonomous 不是 workflow engine。完整招聘工作流由 prompt、business tools、business events、memory、skill/context policy 和 human intervention 共同表达，不写入 Agent runtime。

## Agent Instance / Session 隔离

这里的 Agent 隔离指具体实例、配置、conversation 或 session，不指 `assistant/autonomous` 类型。

必须隔离：

- prompt/profile
- memory scope
- context/history/transcript
- skill selection
- tool permission policy
- run/session status

`assistant` 和 `autonomous` 不能作为 memory scope 的替代，也不能让 runtime 根据这两个 type 分支。

## Product Adapter 职责

Product adapter 是产品层入口，不是 runtime 组成部分。

Assistant adapter 负责：

- conversation/session 生命周期
- 用户消息进入现有 runtime
- SSE/chat projection
- confirm/cancel 的产品状态映射；confirm 只把 permission decision 交回当前等待中的 runtime

Autonomous adapter 负责：

- profile/policy 读取
- trigger/event ingestion
- durable run/checkpoint 状态
- approval/intervention 的产品记录
- runtime event 到 run state / UI/API 的投影
- approval 只把 permission decision 交回当前等待中的 runtime
- Turn 后按配置化 gate 选择性启动 memory extraction/compaction pipeline；不能每个 completed Turn 默认调用 memory LLM

两个 adapter 进入 runtime 前都要归一到现有执行输入：

- prompt / system context
- user message、objective 或业务事件摘要
- history / context
- memory snippets
- skill instructions
- tool definitions
- permission policy metadata
- budget

Adapter 不持有 provider 对话细节，不手工构造 assistant/tool 对话来模拟工具结果，不重放 runtime 内部 tool loop。审批通过或拒绝时，adapter 只把 permission decision 交回当前等待中的 `InteractionEngine`，由 runtime 执行原 `ToolCall`、写入 `ToolResult` message 并继续同一个 Turn。

## 业务 Tool

招聘业务能力必须通过业务 tool 暴露给 Agent：

- 读取：JD、候选人、application thread、goal progress。
- 创建/更新：JD、候选人、application、scorecard、review decision、resume artifact、sync record。
- 流转：application state transition、archive、takeover/release。
- 沟通：outbound message draft/sent record。
- 审批：request human approval。

业务 tool 属于 business capability layer。runtime 只看到 tool name、schema、metadata、tool call 和 tool result。

业务 tool metadata 至少应能表达：

- `business_tool`
- `business_domain`
- `resource_target_kind`
- `capabilities`
- `requires_confirmation` 或其他 permission policy 标记

## 验收

1. `agent_runtime/**` 不导入 `agents/**`、业务 service、repository、model 或 API。
2. `assistant/autonomous` 只影响产品配置、触发、生命周期、状态治理和 UI/API 投影。
3. Assistant / Autonomous 都使用现有 `InteractionEngine.submitMessage(...)` 与现有 `InteractionOutput` protocol。
4. 招聘业务只能通过 business tools、skill/context injection、memory projection 或 product adapter context 进入 Agent。
5. 业务写入和外部副作用必须能被 permission/approval 策略治理。
