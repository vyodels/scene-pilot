# Agent Runtime 技术设计

## 0. 文档状态

本文是 Agent Runtime 的唯一设计源，合并并取代原 `agent-runtime-protocol.md`。后续 runtime 架构、协议边界、核心类型、实施步骤都在本文维护，避免 design/protocol 双文档漂移。

本文目标是为 `/Users/vyodels/AgentProjects/recruit-agent` 的 agent 重构提供可实现方案。方案参考 Claude Code 和 Codex 的设计思想，但不直接复制任一方协议：

- `InteractionEngine` 采用 Claude Code `QueryEngine` 的 conversation-scoped engine 思想，不做字段级复制。
- Turn 状态机、active turn、history replace、tool/item lifecycle 参考 Codex。
- 用户输入、permission、MCP、agent、tool payload 细节优先参考 Claude Code，同时保持中性命名。

本文不再使用以下概念作为核心设计：`SubmissionDispatcher`、`ToolInvocation`、`HistoryEntry`、`ConversationStore`、`ConversationPersistence`、`ConversationSnapshot`、`ConversationRecord`、`LLMLoop`、`UserTurn`、`respond_control`、`steer` 核心 API、`enqueue` 核心 API、Codex `Op/EventMsg` 原样协议。

## 1. 源码依据

核心依据如下，后续实现可以按这些文件回看细节。

```text
Claude Code
  QueryEngine conversation owner:
    collection-claude-code-source-code/claude-code-source-code/src/QueryEngine.ts:175
  QueryEngine.submitMessage / interrupt:
    collection-claude-code-source-code/claude-code-source-code/src/QueryEngine.ts:209
    collection-claude-code-source-code/claude-code-source-code/src/QueryEngine.ts:1158
  QueryEngineConfig / mutableMessages / initialMessages:
    collection-claude-code-source-code/claude-code-source-code/src/QueryEngine.ts:130
    collection-claude-code-source-code/claude-code-source-code/src/QueryEngine.ts:186
  ToolUseContext:
    collection-claude-code-source-code/claude-code-source-code/src/Tool.ts:158
  PermissionDecision:
    collection-claude-code-source-code/claude-code-source-code/src/types/permissions.ts:241
  Claude Code `agent` tool:
    collection-claude-code-source-code/claude-code-source-code/src/tools.ts:195
    collection-claude-code-source-code/claude-code-source-code/src/tools/AgentTool/AgentTool.tsx:196

Codex
  TurnStatus:
    openai-codex/codex-rs/app-server-protocol/src/protocol/v2.rs:5159
  EventMsg / Turn events / tool events:
    openai-codex/codex-rs/protocol/src/protocol.rs:1307
  Session history / replace_history:
    openai-codex/codex-rs/core/src/state/session.rs:65
    openai-codex/codex-rs/core/src/session/mod.rs:2440
  run_turn / pending input / history snapshot:
    openai-codex/codex-rs/core/src/session/turn.rs:322
    openai-codex/codex-rs/core/src/session/turn.rs:369
    openai-codex/codex-rs/core/src/session/turn.rs:431
  Codex agent management tools:
    openai-codex/codex-rs/tools/src/agent_tool.rs:29
    openai-codex/codex-rs/core/src/tools/spec.rs:98
```

## 2. 设计原则

1. `InteractionEngine` 是 conversation 级 runtime owner，不是单次 LLM call，也不是 protocol dispatcher。
2. `InteractionEngine` 对外保持 Claude Code 风格的简洁 API：`submitMessage(...)` 和 `interrupt()`。
3. Turn 是一次 `submitMessage(UserInput)` 触发的完整 agent loop。Turn 内可以包含多次 `LLMInvocation` 和多次 `ToolCall`。
4. Turn 状态只保留 Codex 风格四态：`in_progress`、`completed`、`interrupted`、`failed`。
5. `ConversationHistory` 是 LLMRequest 的直接上下文来源；`Transcript` 是 ConversationHistory 的持久化来源和落盘目标。第一版只承诺 materialized history 的保存/恢复，不声称等价 Codex 完整 rollout/event replay。
6. `LLMStreamEvent` 和 `InteractionOutput` 不是同一层。Turn 消费 `LLMStreamEvent*` 和 `LLMResponse`，再产出对外 `InteractionOutput`。
7. Tool 系统统一为 `ToolDefinition / ToolSchema / ToolUse / ToolCall / ToolResult`。不使用 `ToolInvocation`。
8. Permission 是 ToolCall 执行前的授权流程，核心 follow Claude Code `canUseTool`，不作为 Engine 主 API。
9. MCP 是工具和资源来源；MCP tool 进入 ToolDefinition/ToolCall/ToolResult 主链路。
10. Agent 通过普通工具暴露给模型。第一版对齐 Claude Code 的 `agent` 工具；需要 Codex parity 时再增加 `spawn_agent` / `send_input` / `wait_agent` / `close_agent` / `resume_agent`。
11. queue、mid-turn input、approval response、dynamic tool response 属于内部调度，不进入第一版核心 API；是否进入当前 Turn 需要经过 acceptance/filtering。
12. compact、rollback、resume 进入核心能力，但通过 `ConversationHistory` 和 `Transcript` 表达，不额外造持久化领域类型。

## 3. 核心架构

```text
Client / SDK / UI
  -> InteractionEngine.submitMessage(UserInput)
  -> InteractionEngine.interrupt()
  <- InteractionOutput*

InteractionEngine
  - config: InteractionEngineConfig
  - history: ConversationHistory
  - transcript?: Transcript
  - active_turn?: Turn

Turn
  - status: TurnStatus
  - context: TurnContext
  -> LLMInvocation*
  -> ToolCall*

LLMInvocation
  -> LLMRequest
  -> LLMProvider
  <- LLMStreamEvent*
  <- LLMResponse

Tool system
  ToolDefinition -> ToolSchema
  ToolUse -> ToolCall -> ToolResult
```

### 3.1 运行时主流程

```text
1. Client 调用 submitMessage(UserInput)。

2. InteractionEngine:
   - UserInput -> UserMessage
   - ConversationHistory.append(UserMessage)
   - Transcript.record(UserMessage)
   - 创建 Turn

3. Turn:
   - ConversationHistory.snapshot()
   - 构建 LLMRequest
   - 发起 LLMInvocation

4. LLMProvider:
   - 返回 LLMStreamEvent*
   - 返回 LLMResponse

5. Turn:
   - LLMStreamEvent -> InteractionOutput
   - LLMResponse.assistant_message -> ConversationHistory.append(AssistantMessage)
   - LLMResponse.tool_uses -> ToolUse[]

6. 如果没有 ToolUse:
   - TurnCompleted
   - Turn 结束

7. 如果存在 ToolUse:
   - ToolUse -> ToolCall
   - canUseTool(...)
   - ToolHandler.handle(ToolCall, TurnContext)
   - ToolResult -> ToolResultMessage
   - ConversationHistory.append(ToolResultMessage)
   - 回到步骤 3，发起下一次 LLMInvocation

8. 直到 Turn completed / interrupted / failed。
```

## 4. InteractionEngine

### 4.1 API

```text
InteractionEngine.submitMessage(
  input: UserInput,
  options?: SubmitMessageOptions
): AsyncIterable<InteractionOutput>

InteractionEngine.interrupt(): void
```

第一版不暴露：

```text
submit(Submission)
respond_control(...)
steer(...)
enqueue(...)
active_turn_ids
SubmissionDispatcher
```

如果后续需要跨进程 transport，可以在 adapter 层把外部 request 映射到 `submitMessage` / `interrupt` / permission callback，而不是让 transport protocol 主导 runtime 内部结构。

### 4.2 字段

```text
InteractionEngine {
  config: InteractionEngineConfig
  history: ConversationHistory
  transcript?: Transcript
  active_turn?: Turn
}
```

`InteractionEngine` 拥有 conversation 级历史和 active Turn。Turn 执行过程中实时读写 `ConversationHistory`，不是 Turn 完成后再统一合并消息。

## 5. InteractionEngineConfig

`InteractionEngineConfig` 参考 Claude Code `QueryEngineConfig` 的 conversation owner 配置形态，但不做字段级复制。Claude Code 把 `getAppState/setAppState/readFileCache/mcpClients/agents/orphanedPermission` 等 runtime bridge 直接放在 QueryEngineConfig 和 ToolUseContext 里；本设计只保留运行 Turn 必需的中性配置。

```text
InteractionEngineConfig {
  cwd: string

  model: ModelConfig
  provider: LLMProvider
  max_tokens?: number
  temperature?: number
  top_p?: number
  stop_sequences?: string[]
  tool_choice?: ToolChoice
  thinking?: ThinkingConfig
  reasoning?: ReasoningConfig
  text_format?: TextFormatConfig
  parallel_tool_calls?: boolean
  max_tool_calls?: number
  store?: boolean
  truncation?: string

  tools: ToolDefinition[]
  agent_definitions?: AgentDefinition[]
  commands?: CommandDefinition[]

  can_use_tool: CanUseToolFn
  tool_permission_context: ToolPermissionContext
  permission_mode?: PermissionMode

  system_prompt?: string | (() => string)
  append_system_prompt?: string | (() => string)
  initial_messages?: LLMMessage[]

  conversation_id?: ConversationId
  transcript?: Transcript

  max_llm_invocations?: number
  max_budget_usd?: number

  hooks?: HookConfig
  runtime?: RuntimeBridge
  telemetry?: TelemetryConfig

  debug?: boolean
  verbose?: boolean
}
```

`RuntimeBridge` 只覆盖实现桥接职责，不定义新的能力来源类型：

```text
RuntimeBridge {
  app_state?: AppStateBridge
  file_cache?: FileStateCache
  output_sink?: InteractionOutputSink
  pending_permissions?: PendingPermissionStore
  clock?: Clock
  id_generator?: IdGenerator
}
```

这些字段是实现桥，不是模型协议的一部分。后续如果 recruit-agent 已有存储、审批、事件总线能力，应在 adapter 层接入，不要把现有 DB record 反向提升为核心 runtime 类型。

不放入 Config 的内容：

```text
queue
steer
respond_control
SubmissionDispatcher
Op/EventMsg 原样协议
LLMInvocation 状态缓存
active_turn_ids
```

## 6. UserInput 与 LLMMessage

### 6.1 UserInput

`UserInput` 是 `submitMessage` 的输入。第一版保持简单：

```text
UserInput =
  | string
  | ContentBlock[]
```

`SubmitMessageOptions`：

```text
SubmitMessageOptions {
  uuid?: string
  isMeta?: boolean
}
```

Skill、memory、mention、attachment 不作为基础 `UserInput` 变体。它们属于 input processing / context loading / command system。

### 6.2 LLMMessage

`LLMMessage` 是 runtime 内部的 provider-neutral 模型消息，不直接等同 Claude Code SDKMessage，也不等同 Codex ResponseItem。

```text
LLMMessage =
  | SystemMessage
  | UserMessage
  | AssistantMessage
  | ToolResultMessage
```

```text
SystemMessage {
  role: "system"
  content: ContentBlock[]
}

UserMessage {
  role: "user"
  content: ContentBlock[]
}

AssistantMessage {
  role: "assistant"
  content: ContentBlock[]
  tool_uses?: ToolUse[]
  reasoning?: ReasoningOutput
}

ToolResultMessage {
  role: "tool"
  tool_use_id: ToolUseId
  content: ContentBlock[]
  is_error?: boolean
}
```

`SystemMessage` 是模型输入消息。它不同于 `RuntimeEvent`，后者是对外运行时事件，默认不进入模型上下文。

## 7. ConversationHistory 与 Transcript

### 7.1 关系

```text
Transcript 是 ConversationHistory 的持久化来源和落盘目标。
ConversationHistory 是 LLMRequest 的直接上下文来源。
```

```text
InteractionEngine
  ├─ ConversationHistory   // runtime conversation state
  └─ Transcript?           // persistence / resume / replay
```

`ConversationHistory` 不是 Agent file memory，也不是业务 context/knowledge。它只保存模型可见的 materialized conversation state，并负责为下一次 `LLMRequest` 提供 messages。候选人、JD、投递、沟通摘要、评分偏好等业务 context/knowledge 由 product adapter 或业务服务管理，只能通过 context/message、tool result、skill context 或 MCP resource/tool 的结果进入 runtime。

### 7.2 ConversationHistory

```text
ConversationHistory {
  messages: LLMMessage[]

  append(messages: LLMMessage[]): void
  snapshot(options?: SnapshotOptions): LLMMessage[]
  replace(messages: LLMMessage[]): void
}
```

语义：

- `append`：Turn 执行中实时追加 UserMessage、AssistantMessage、ToolResultMessage。
- `snapshot`：每次 LLMInvocation 前构造 LLMRequest 的模型上下文。
- `replace`：compact、rollback、clear、resume 后替换运行时历史。

### 7.3 Transcript

`Transcript` 保留已定关系：它是 `ConversationHistory` 的持久化来源和落盘目标。但实现上不能只写裸 `LLMMessage[]`，否则无法恢复 permission、tool state、event seq、interrupted marker。

第一版采用两层语义：

```text
materialized messages:
  直接用于初始化 ConversationHistory，并作为 LLMRequest.messages 的来源。

transcript entries:
  用于持久化可恢复 runtime 状态，包括 output seq、tool call state、permission pending、compact/rollback marker。
```

```text
Transcript {
  load(conversation_id: ConversationId): Promise<TranscriptState | null>
  record_messages(conversation_id: ConversationId, messages: LLMMessage[]): Promise<void>
  record_output(conversation_id: ConversationId, output: InteractionOutput): Promise<void>
  record_tool_state(conversation_id: ConversationId, state: ToolCallState): Promise<void>
  record_permission_state(conversation_id: ConversationId, state: PendingPermission): Promise<void>
  replace_messages(conversation_id: ConversationId, messages: LLMMessage[]): Promise<void>
}

TranscriptState {
  messages: LLMMessage[]
  next_seq: number
  pending_permissions: PendingPermission[]
  tool_states: ToolCallState[]
}
```

初始化优先级：

```text
1. 如果 initial_messages 存在，使用 initial_messages 初始化 ConversationHistory。
2. 否则如果 transcript + conversation_id 存在，调用 transcript.load(conversation_id).messages。
3. 否则使用空 ConversationHistory。
```

写入时机：

```text
ConversationHistory.append(messages)
  -> Transcript.record_messages(conversation_id, messages)

ConversationHistory.replace(messages)
  -> Transcript.replace_messages(conversation_id, messages)

InteractionOutput emit
  -> Transcript.record_output(conversation_id, output)
```

compact：

```text
compacted_messages
  -> ConversationHistory.replace(compacted_messages)
  -> Transcript.replace_messages(conversation_id, compacted_messages)
  -> RuntimeEvent(kind = "context_compacted")
```

rollback：

```text
rolled_back_messages
  -> ConversationHistory.replace(rolled_back_messages)
  -> Transcript.replace_messages(conversation_id, rolled_back_messages)
  -> RuntimeEvent(kind = "thread_updated")
```

rollback 必须在没有 active Turn 时执行。第一版不把 rollback 放入 `InteractionEngine` 主 API，可以作为管理能力或 admin API。

注意：如果第一版不实现 Codex rollout/event replay，只能支持“当前 materialized history 的保存/恢复”。Codex 等价的 rollback/resume 需要持久化更多事件和 marker，不应在第一版承诺。

## 8. Turn

### 8.1 定义

```text
Turn = 一次 submitMessage(UserInput) 触发的完整 agent loop
```

`Turn` 不是 `UserTurn`，也不是一次 LLM call。一次 Turn 内可能包含多次 `LLMInvocation`。

### 8.2 TurnStatus

参考 Codex `TurnStatus` 四态：

```text
TurnStatus =
  | "in_progress"
  | "completed"
  | "interrupted"
  | "failed"
```

不把以下状态放入 `TurnStatus`：

```text
waiting_permission
waiting_tool
waiting_llm
waiting_user_input
```

这些是 Turn 内部过程或输出事件，Turn 仍然是 `in_progress`。

### 8.3 TurnContext

`TurnContext` 采用 Codex 风格，是本轮执行的配置和依赖快照。它不是 Claude Code `ToolUseContext` 的照搬。工具执行时直接接收 `ToolCall + TurnContext`，不再引入 `ToolExecutionContext`。

```text
TurnContext {
  turn_id: TurnId
  conversation_id: ConversationId

  cwd: string
  model: ModelConfig
  provider: LLMProvider
  reasoning?: ReasoningConfig

  history: ConversationHistory
  transcript?: Transcript

  tools: ToolDefinition[]
  tool_schemas: ToolSchema[]
  agent_definitions?: AgentDefinition[]

  permission_context: ToolPermissionContext
  can_use_tool: CanUseToolFn

  abort_signal: AbortSignal

  features?: FeatureConfig
  runtime?: RuntimeBridge
  telemetry?: Telemetry
}
```

`TurnContext` 可以被 ToolHandler 读取，但不应作为全局可变状态容器滥用。Conversation 历史修改通过 `ConversationHistory.append/replace` 完成。

## 9. LLMInvocation

`LLMLoop` 不是核心概念。Turn 自身执行 agent loop；一次模型调用叫 `LLMInvocation`。

```text
LLMInvocation {
  id: LLMInvocationId
  turn_id: TurnId
  index: number
  status: LLMInvocationStatus
  request: LLMRequest
  response?: LLMResponse
  error?: LLMError
}
```

```text
LLMInvocationStatus =
  | "in_progress"
  | "completed"
  | "failed"
  | "cancelled"
```

`LLMProvider`：

```text
LLMProvider {
  invoke(request: LLMRequest, options?: LLMInvocationOptions): LLMInvocationResult
}

LLMInvocationResult {
  events: AsyncIterable<LLMStreamEvent>
  response: Promise<LLMResponse>
}
```

第一版不引入 blocking provider 或旧 `generate(...)` adapter。LLM 层直接实现原生 LLM backend：

```text
OpenAI LLM backend implements LLMProvider
Anthropic LLM backend implements LLMProvider
```

二者都必须从真实 streaming 协议映射 `LLMStreamEvent*`，并聚合最终 `LLMResponse`。

`LLMRequest`：

```text
LLMRequest {
  id: LLMRequestId
  turn_id: TurnId
  invocation_id: LLMInvocationId

  messages: LLMMessage[]
  tools: ToolSchema[]

  model: ModelConfig
  reasoning?: ReasoningConfig

  system_prompt?: string
  max_tokens?: number
  temperature?: number
  top_p?: number
  stop_sequences?: string[]
  tool_choice?: ToolChoice
  thinking?: ThinkingConfig
  reasoning?: ReasoningConfig
  text_format?: TextFormatConfig
  parallel_tool_calls?: boolean
  max_tool_calls?: number
  previous_response_id?: string
  store?: boolean
  truncation?: string
  openai_payload_overrides?: object
  anthropic_payload_overrides?: object
  metadata?: LLMRequestMetadata
}
```

`LLMRequest` 以 Anthropic Messages 的消息/工具结构作为中性基准：`system` 独立、assistant tool use 是 assistant 内容块、tool result 是 user/tool_result 语义。LLM backend 只映射自身支持的字段；OpenAI 支持而 Anthropic 不支持的字段由 Anthropic backend 忽略，Anthropic 支持而 OpenAI 不支持的字段由 OpenAI backend 忽略。backend 私有扩展必须使用 backend-scoped override，例如 `openai_payload_overrides` / `anthropic_payload_overrides`，不允许 unscoped `payload_overrides` 进入生产路径。

`LLMStreamEvent`：

```text
LLMStreamEvent =
  | { type: "assistant_delta"; message_id: MessageId; delta: string }
  | { type: "reasoning_delta"; reasoning_id: ReasoningId; delta: string }
  | { type: "tool_use_delta"; tool_use_id: ToolUseId; name?: string; input_delta?: unknown }
  | { type: "tool_use_completed"; tool_use: ToolUse }
  | { type: "usage_delta"; usage: TokenUsage }
  | { type: "raw"; raw: unknown }
  | { type: "error"; error: LLMError }
```

`LLMResponse`：

```text
LLMResponse {
  id: LLMResponseId
  request_id: LLMRequestId
  invocation_id: LLMInvocationId

  assistant_message?: AssistantMessage
  reasoning?: ReasoningOutput
  tool_uses: ToolUse[]

  stop_reason?: StopReason
  usage?: TokenUsage

  raw?: unknown
}
```

Turn 监听 `LLMInvocation` 的 `LLMStreamEvent*` 生成实时 `InteractionOutput`，并在 `LLMResponse` 完成后，根据完整响应驱动 ToolCall、下一次 LLMInvocation 或 Turn 结束。

## 10. Tool 系统

### 10.1 核心类型

```text
ToolDefinition
ToolSchema
ToolUse
ToolCall
ToolResult
```

定义：

- `ToolDefinition`：运行时工具注册定义。
- `ToolSchema`：暴露给模型的工具 schema。
- `ToolUse`：LLMResponse 中模型请求使用工具的协议对象。
- `ToolCall`：Turn 根据 ToolUse 构造出的运行时执行请求。
- `ToolResult`：ToolHandler 执行 ToolCall 后产出的结果。

不使用 `ToolInvocation`。

### 10.2 字段

```text
ToolDefinition {
  name: string
  description: string
  schema: ToolSchema
  handler: ToolHandler
  permission?: ToolPermissionPolicy
  metadata?: ToolMetadata
}

ToolSchema {
  name: string
  description: string
  input_schema: JsonSchema
}

ToolUse {
  id: ToolUseId
  name: string
  input: unknown
  raw?: unknown
}

ToolCall {
  id: ToolCallId
  turn_id: TurnId
  llm_invocation_id: LLMInvocationId
  tool_use_id: ToolUseId
  name: string
  input: unknown
  state?: ToolCallState
}

ToolCallState =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "denied"
  | "cancelled"

ToolResult {
  id: ToolResultId
  tool_call_id: ToolCallId
  tool_use_id: ToolUseId
  name: string
  content: ToolResultContent
  is_error: boolean
  metadata?: ToolResultMetadata
}
```

`ToolCallState` 是内部观测和 Transcript 恢复字段，不是对外核心 API，也不是 Claude Code / Codex 的原样类型。对外 tool 生命周期通过 `ToolEvent` 表达。

recruit-agent 现有工具字段需要落到 `ToolDefinition.metadata` 或 `ToolSchema` policy 上，避免把站点语义写入 core runtime：

```text
ToolMetadata {
  category?: string
  source?: "builtin" | "mcp" | "agent" | "scene"
  capabilities?: string[]
  risk?: ToolRiskLevel
  external_target?: string
  resource_target_kind?: string
  scene_contract?: unknown
}
```

### 10.3 ToolHandler

按 Codex 风格收敛，不单独引入 `ToolExecutionContext`。

```text
ToolHandler {
  handle(call: ToolCall, context: TurnContext): Promise<ToolResult>
}
```

### 10.4 工具流

```text
ToolDefinition
  -> ToolSchema
  -> LLMRequest.tools

LLMResponse.tool_uses
  -> ToolUse[]

Turn
  -> ToolUse -> ToolCall
  -> canUseTool(...)
  -> ToolHandler.handle(ToolCall, TurnContext)
  -> ToolResult
  -> ToolResultMessage
  -> ConversationHistory.append(...)
  -> next LLMInvocation
```

## 11. Permission

Permission 参考 Claude Code `canUseTool` 语义，但这里定义的是 adapter 后的中性最小抽象，不复制 Claude Code 的完整函数签名。实现时不能丢掉 `tool_use_id`、父 assistant message、updated input、ask/passthrough、decision reason 等信息。

```text
CanUseToolFn = (
  tool_call: ToolCall,
  context: ToolPermissionContext,
  options?: PermissionCheckOptions
) => Promise<PermissionDecision>
```

```text
PermissionCheckOptions {
  tool_use_id: ToolUseId
  assistant_message?: AssistantMessage
  force_decision?: PermissionDecision
}

PermissionDecision =
  | { behavior: "allow"; updated_input?: unknown }
  | { behavior: "ask"; request: PermissionRequest }
  | { behavior: "deny"; message?: string }
  | { behavior: "passthrough"; message: string; suggestions?: PermissionUpdate[] }
```

运行语义：

```text
ToolUse
  -> ToolCall
  -> canUseTool(ToolCall, ToolPermissionContext)
      -> allow: 执行 ToolHandler
      -> deny: 生成 ToolResult(is_error = true)
      -> passthrough: 生成可见 RuntimeEvent 或 ToolResult，由 adapter 决定是否继续等待用户
      -> ask: 对外发 PermissionRequested，等待 adapter 返回决策
  -> ToolResult
  -> next LLMRequest
```

`PermissionRequested` 是 `InteractionOutput`，不是新的 Engine API。approval response 不启动新 Turn。

内部需要保存 pending permission state，用于把用户审批结果关联回当前 ToolCall；不单独定义新的 public broker API：

```text
PendingPermission {
  permission_request_id: PermissionRequestId
  turn_id: TurnId
  tool_call_id: ToolCallId
  tool_use_id: ToolUseId
  status: "pending" | "resolved" | "denied" | "cancelled" | "expired"
}

PendingPermissionStore {
  record(permission: PendingPermission): void
  resolve(permission_request_id: PermissionRequestId, decision: PermissionDecision): void
  cancel_by_turn(turn_id: TurnId, reason: string): void
}
```

`PendingPermissionStore` 是内部状态桥，不是 `InteractionEngine` 的公开主 API。UI / SDK / HTTP adapter 可以用自己的 endpoint 或 callback 写入审批结果，但核心 Engine 仍只暴露 `submitMessage(...)` 和 `interrupt()`。

默认规则：

- active Turn interrupt 时，所有 pending permission 标记为 `cancelled`，对应 ToolCall 返回 `ToolResult(is_error = true)` 或直接结束 Turn。
- adapter 断开连接时，permission 继续 pending 还是自动 deny 由产品层配置决定。
- timeout 后默认 deny，除非工具 policy 明确允许继续等待。

## 12. MCP

MCP 是工具和资源来源，不是独立 Engine，也不是 `InteractionEngine` 的配置类型。MCP client、server registry、auth、startup 都归 adapter / infrastructure 层；进入 runtime 时已经被转换为 `ToolDefinition[]`、resource context messages，或 list/read resource 普通工具。

```text
adapter / MCP infrastructure
  -> discover tools/resources
  -> build ToolDefinition[]
  -> merge into tools registry
  -> LLMRequest.tools
```

MCP tool 执行：

```text
ToolUse(name = "mcp__server__tool")
  -> ToolCall
  -> ToolHandler.handle(ToolCall, TurnContext)
  -> ToolResult
  -> ToolResultMessage
```

MCP resource 不应被理解为“每个 resource 都是一个 callable tool”。第一版支持两种方式：

```text
1. 通过 context building 策略注入 LLMMessage。
2. 通过 list/read resource 工具访问，例如 list_mcp_resources / read_mcp_resource。
```

不要在核心架构里单独开 `McpResourceFlow` / `MCPServerConnection` runtime type，也不要把 resource 枚举直接膨胀成大量 ToolDefinition。

MCP startup/auth 状态由 adapter / infrastructure 映射为普通 status output 或产品事件；runtime 不持有 MCP client 状态。

## 13. Skill / Memory / Context

Skill、memory、业务 context 不作为 runtime 类型，也不是 Agent runtime 的内建能力。这个边界来自 Claude Code 和 Codex：

```text
Claude Code
  skills / slash commands
  -> disk/plugin discovery
  -> metadata or content loaded into prompt/context
  -> context: fork 时由外层启动 forked sub-agent
  -> 不把 skill 做成 runtime primitive

Codex
  UserInput::Skill + core-skills injection
  -> collect_explicit_skill_mentions(...)
  -> build_skill_injections(...)
  -> 注入 turn context
  -> agent 管理才使用 spawn_agent/send_input/wait_agent 等 function tools
```

recruit-agent follow 这个边界：runtime 只认识 `ToolDefinition`、`ToolCall`、`ToolResult`、`LLMMessage`、`ConversationHistory`、`Transcript` 和 `InteractionOutput`。skill、memory、MCP resource、业务 context 都由 adapter 在 Turn 前选择并组装成 messages/context，或作为普通 tool/resource result 返回；runtime 不定义它们的专用抽象。

```text
skill
  -> discovery / selection / injection
  -> 渲染为 system/user context 或 structured user input
  -> 如需 fork，由产品 adapter/command layer 启动 isolated InteractionEngine
  -> 不给模型暴露通用 skill execution tool

memory
  -> adapter 在 Turn 前构造 context/messages
  -> read/list/search memory 可通过 memory tools 暴露给模型
  -> 用户显式要求记住/忘记时，主 Turn 内使用受限 memory tools 写入 markdown memory
  -> 自动提炼、压缩 memory 由 Turn 外产品 pipeline 按配置化 gate 选择性启动

MCP
  -> tool 进入 ToolDefinition / ToolCall / ToolResult
  -> resource 由 adapter 注入 context，或由 list/read resource 普通工具读取

business context
  -> adapter 读取业务状态、UI state、run state
  -> 构造成 LLMMessage / system prompt / user input
  -> runtime 不认识业务 context 类型
```

Runtime 不定义 skill、memory、MCP resource、business context 专用 primitive。Claude Code 的 forked skill/command 是外层调用策略；Codex 的 skill 是 input/injection 机制；二者都不是 runtime 内的 skill execution branch。recruit-agent 不保留通用 skill 调用工具。

### 13.1 Context 与 memory 管理

上下文管理分为三层，不互相替代：

```text
runtime history
  ConversationHistory.snapshot()
  -> LLMRequest.messages
  -> compact/rollback/resume 只改 ConversationHistory + Transcript

product adapter context
  GoalSpec / AgentRun / UI state / allowed tools / skill injections / business context/knowledge refs / memory file refs / MCP resources
  -> system_prompt、append_system_prompt、initial_messages 或本轮 UserMessage

memory file update / extraction, optional product policy
  InteractionOutput / ToolResult / final assistant message / product run result
  -> adapter / business service / memory pipeline 先按配置化 gate 判断是否启动后台 memory job
  -> 后台 memory job 判断候选人/JD/全局 stable facts
  -> 可选 human review、去重后写回 memory files，或完全不写回

```

runtime 只提供 history compaction：把当前模型上下文压缩为新的 `LLMMessage[]`，替换 `ConversationHistory` 并同步 `Transcript`。它不判断哪些招聘事实值得长期保存，也不直接写 candidate/JD/global scoped file memory。

product adapter 负责 Turn 前 context construction：读取产品 run 状态、skill metadata/content、业务 context/knowledge、Agent file memory refs、MCP resource、UI 选择和权限策略，形成模型可见的 system/user context 与可用 `ToolDefinition[]`。这些输入进入 runtime 后都只是 messages、tools、permission context 或 metadata。

memory update / extraction 是产品层策略，不是 Agent runtime 能力：用户显式要求记住或忘记时，模型可以在主 Turn 内调用受限 memory tools 更新当前 memory scope 下的 markdown 文件；自动提炼和压缩则由 adapter、业务服务或后台 memory pipeline 从 `InteractionOutput`、`ToolResult`、最终 assistant message 和业务服务结果中判断是否存在 stable facts。是否启动后台 memory job 必须先经过配置化资源 gate，不能每个 completed Turn 默认调用一次 memory LLM。runtime 可以把相关事件完整产出和落 transcript，但不定义 memory patch schema、不选择 memory store、不决定是否自动写回。

MCP、skill、memory、context 都不能扩展成 runtime primitive，也不能引入新的 capability source abstraction。MCP tool 是 `ToolDefinition`，MCP resource 通过 context 或 list/read 工具进入模型；skill 是 adapter 构造的 context injection；memory tools 是普通 `ToolDefinition`，但分类属于 memory，不属于业务工具；业务 context 是 adapter 输入，不是 runtime type。

禁止把 skill 扩展成 Turn 内特殊分支。

## 14. Agent

Agent 能力通过普通工具暴露，但不是一 agent 一个 tool。

```text
AgentDefinition[] -> agent tool schema/prompt 配置输入
agent tool        -> ToolDefinition
```

`AgentDefinition`：

```text
AgentDefinition {
  type: string
  description: string
  system_prompt?: string
  tools?: string[]
  mcp_requirements?: string[]
  model?: ModelConfig
  reasoning?: ReasoningConfig
}
```

第一版 follow Claude Code，暴露一个名为 `agent` 的普通工具：

```text
ToolDefinition {
  name: "agent"
  schema: ToolSchema
  handler: ToolHandler
}
```

后续如果需要 Codex 风格长期 agent 管理，再增加 `spawn_agent / send_input / wait_agent / close_agent / resume_agent` 等工具。

父 Turn 视角：

```text
ToolUse(name = "agent")
  -> ToolCall
  -> ToolHandler 启动/管理子 agent
  -> ToolResult
  -> ToolResultMessage
```

Subagent 内部可以有自己的 Turn/ConversationHistory。父 Turn 默认只接收 ToolResult，不自动并入 subagent 全部内部 history。

第一版 `agent` 工具覆盖的是短任务 / ephemeral subagent。recruit-agent 现有 Autonomous 长运行 run、checkpoint、approval 模型属于 product-level adapter，可以基于 `InteractionEngine` 实现，但不要被简化成一次普通 ToolCall 的内部细节。

## 15. InteractionOutput

第一版对外输出采用中性事件，不直接复制 Claude Code `SDKMessage` 或 Codex `EventMsg`。所有输出共享最小 envelope，保证 SSE、resume、transcript replay 可以稳定关联。

```text
InteractionOutputEnvelope {
  id: OutputId
  seq: number
  conversation_id: ConversationId
  turn_id?: TurnId
  created_at: Timestamp
  correlation_id?: string
}
```

第一版输出变体：

```text
InteractionOutput =
  | TurnStarted
  | TurnCompleted
  | TurnInterrupted
  | TurnFailed

  | AssistantMessageDelta
  | AssistantMessageCompleted
  | ReasoningDelta
  | ReasoningCompleted

  | ToolEvent

  | PermissionRequested

  | RuntimeEvent
```

```text
TurnStarted {
  type: "turn_started"
  turn_id: TurnId
}

TurnCompleted {
  type: "turn_completed"
  turn_id: TurnId
  result: TurnResult
}

TurnInterrupted {
  type: "turn_interrupted"
  turn_id: TurnId
  reason?: string
}

TurnFailed {
  type: "turn_failed"
  turn_id: TurnId
  error: TurnError
}
```

```text
AssistantMessageDelta {
  type: "assistant_message_delta"
  turn_id: TurnId
  message_id: MessageId
  delta: string
}

AssistantMessageCompleted {
  type: "assistant_message_completed"
  turn_id: TurnId
  message: AssistantMessage
}

ReasoningDelta {
  type: "reasoning_delta"
  turn_id: TurnId
  reasoning_id: ReasoningId
  delta: string
}

ReasoningCompleted {
  type: "reasoning_completed"
  turn_id: TurnId
  reasoning: ReasoningOutput
}
```

```text
ToolEvent {
  type: "tool_event"
  turn_id: TurnId

  kind:
    | "tool_use_received"
    | "tool_call_started"
    | "tool_call_progress"
    | "tool_call_completed"
    | "tool_call_failed"
    | "tool_result_ready"

  tool_name: string
  tool_use_id?: ToolUseId
  tool_call_id?: ToolCallId
  data?: unknown
}
```

```text
PermissionRequested {
  type: "permission_requested"
  turn_id: TurnId
  request: PermissionRequest
}
```

```text
RuntimeEvent {
  type: "runtime_event"
  turn_id?: TurnId

  kind:
    | "status"
    | "warning"
    | "token_usage"
    | "model_reroute"
    | "context_compacted"
    | "mcp_startup"
    | "background"
    | "deprecation"
    | "thread_updated"
    | "raw_provider_event"
    | "raw_tool_event"

  data?: unknown
}
```

`LLMInvocation` 不作为默认 `InteractionOutput`。它是内部观测对象，调试时可通过 runtime/telemetry 打开。

为了避免 UI/SDK 后续只能从 `ToolEvent.data` 反解析源协议，可以保留 debug/raw passthrough：

```text
RuntimeEvent(kind = "raw_provider_event")
RuntimeEvent(kind = "raw_tool_event")
```

这些默认关闭，只用于调试、审计或迁移期兼容。

## 16. Queue、mid-turn input、interrupt

Engine API 仍保持：

```text
submitMessage(...)
interrupt()
```

内部可以有：

```text
ActiveTurnPendingInput
NextTurnQueue
```

语义：

1. 无 active Turn 时，`submitMessage` 创建新 Turn。
2. 有 active Turn 时，不创建并发 Turn。
3. mid-turn input 可以进入 active Turn pending input。
4. 无法并入当前 Turn 的输入进入 next-turn queue。
5. pending input 在 tool call 结束后、下一次 LLMRequest 前尝试 drain。
6. drain 前必须经过 acceptance/filtering；slash command、permission response、subagent notification、blocked input 不能混用同一规则。
7. approval / permission response 恢复当前等待中的 ToolCall，不创建新 Turn。

这些队列不作为公开 API。

`interrupt()`：

```text
interrupt():
  if active_turn exists:
    active_turn.abort()
    active_turn.status = "interrupted"
    emit TurnInterrupted
  else:
    no-op
```

参考 Codex，interrupt 后应记录一个模型可见的 interrupted marker 到 `ConversationHistory`，使后续模型知道上一轮被中断。具体格式不在第一版固定。

## 17. compact、rollback、resume

compact、rollback、resume 进入核心能力，但不扩展主 API。

compact：

```text
compact():
  compacted_messages = build_compacted_messages(history.snapshot())
  history.replace(compacted_messages)
  transcript.replace_messages(conversation_id, compacted_messages)
  emit RuntimeEvent(kind = "context_compacted")
```

rollback：

```text
rollback(n):
  require no active Turn
  rolled_back_messages = drop_last_n_user_turns(history.snapshot(), n)
  history.replace(rolled_back_messages)
  transcript.replace_messages(conversation_id, rolled_back_messages)
  emit RuntimeEvent(kind = "thread_updated")
```

resume：

```text
messages = initial_messages ?? transcript.load(conversation_id) ?? []
history = ConversationHistory(messages)
```

第一版不实现 Codex rollout marker/event replay；如后续需要完整审计和回放，Transcript 需要记录足够的 output、tool state、permission state、compact marker、rollback marker。

约束：

- compact 不得丢失 pending ToolCall / PendingPermission；如果存在 pending 状态，要先完成、取消或显式 checkpoint。
- rollback 必须在没有 active Turn 时执行。
- resume minimal 只恢复 `ConversationHistory.messages`；permission-safe resume 还要恢复 `PendingPermission` 和 `ToolCallState`。

## 18. Error

第一版错误分三层：

```text
TurnError
LLMError
ToolError
```

基础结构：

```text
ErrorLike {
  code: string
  message: string
  details?: unknown
  recoverable?: boolean
}
```

语义：

- `ToolError` 默认转成 `ToolResult(is_error = true)` 回灌给模型，不直接失败整个 Turn。
- `LLMError` 如果可恢复，由 Turn 内部重试或 fallback；无法恢复时变成 `TurnFailed`。
- `Permission denied` 是 `ToolResult(is_error = true)`，不一定是 `TurnError`。
- `interrupt` 不是 `TurnError`，而是 `TurnInterrupted`。

错误策略需要显式配置，不放任各层自行决定：

```text
ErrorPolicy {
  max_llm_retries: number
  allow_model_fallback: boolean
  max_tool_retries: number
  tool_error_mode: "return_to_model" | "fail_turn"
}
```

默认策略：

- LLM transient error 可以重试；auth、quota、invalid request 不重试。
- provider fallback 只能在请求幂等且没有产生 partial side effect 时执行。
- tool side effect 已经发生但返回失败时，不自动重试，除非 ToolDefinition 标记 idempotent。
- 多次工具失败后是否升级为 `TurnFailed` 由 `tool_error_mode` 和 max retry 决定。

## 19. 实施阶段

### Phase 1: 核心 loop

目标：最小可运行 agent loop。

- `InteractionEngine`
- `InteractionEngineConfig`
- `ConversationHistory`
- `Transcript`
- `Turn`
- `TurnContext`
- `LLMProvider`
- `LLMInvocation`
- `LLMRequest / LLMResponse / LLMStreamEvent`
- `InteractionOutput`

验收：

- `submitMessage("...")` 可以启动 Turn。
- OpenAI LLM backend 适配 OpenAI Responses API，可以输出 `AssistantMessageDelta`、ToolUse delta/completed、最终 `LLMResponse`。
- Anthropic LLM backend 适配 Anthropic Messages API，可以输出 `AssistantMessageDelta`、ToolUse delta/completed、ReasoningDelta、最终 `LLMResponse`。
- 能保存并 resume minimal materialized history。
- `interrupt()` 能中断 active Turn 并产生 `TurnInterrupted`。

### Phase 2: Tool loop

目标：支持 tool use -> tool call -> tool result -> next LLMInvocation。

- `ToolDefinition / ToolSchema`
- `ToolUse / ToolCall / ToolResult`
- `ToolHandler`
- `ToolEvent`
- `ToolResultMessage`

验收：

- 模型请求工具后能执行工具。
- ToolResult 能进入下一次 LLMRequest。
- ToolError 不默认失败 Turn。

### Phase 3: Permission / MCP / Agent

目标：接入真实 runtime 能力。

- `can_use_tool`
- `PermissionRequested`
- MCP tools/resources
- `agent` tool + AgentDefinition

验收：

- 权限 ask/allow/deny 可跑通。
- approval response 能恢复当前 pending ToolCall，不创建新 Turn。
- MCP tool 能作为普通 ToolCall 执行。
- `agent` 工具能作为 ToolCall 启动子 agent 并返回 ToolResult。
- Skill 通过 adapter 选择并注入 context；runtime 内没有 skill primitive 或通用 skill 执行工具。

### Phase 4: 管理能力

目标：完善长期运行体验。

- compact
- rollback
- mid-turn pending input
- next-turn queue
- permission-safe checkpoint resume
- advanced transcript replay

验收：

- compact 后 history 和 transcript 一致。
- rollback 禁止 active Turn 时执行。
- mid-turn input 经过 acceptance/filtering 后，才进入下一次 LLMRequest。
- pending permission / tool state 不会被 compact 或 resume 丢失。

## 20. recruit-agent 现有模型映射

核心 runtime 类型不要直接等同现有 persistence record。迁移时按 adapter 映射：

```text
InteractionEngine
  -> product service / SDK session owner

Turn
  -> 一次 submitMessage(UserInput) 的 runtime loop
  -> 可映射到现有 AgentRun / AgentTurnRecord / ConversationTurn 组合

ConversationHistory
  -> LLMRequest.messages 的 materialized context
  -> 可由现有 conversation turns 还原

Transcript
  -> ConversationHistory 的持久化来源和落盘目标
  -> 同时记录 InteractionOutput seq、ToolCallState、PendingPermission

InteractionOutput
  -> SSE / WebSocket / runtime event adapter

ToolDefinition.metadata
  -> 兼容现有 category、capabilities、external_target、resource_target_kind、scene_contract
```

规则：

- `ConversationTurn(role=user/assistant)` 是存储表现，不反向定义核心 `Turn`。
- `AgentRun` / `AgentTurnRecord` 是长期任务和审计模型，不反向定义 `InteractionEngine` API。
- `ApprovalItem` / operator interaction 映射到 `PendingPermission`，审批结果回填 active Turn，不创建新 Turn。
- `delegate_scene_context` 等浏览器/电脑合同工具映射为 `ToolDefinition`，站点语义留在 prompt、contract、fixture、test 或 tool metadata，不写进 core runtime 分支。

## 21. 最终核心类型索引

```text
InteractionEngine
InteractionEngineConfig
UserInput
SubmitMessageOptions
Turn
TurnStatus
TurnContext
ConversationHistory
Transcript
InteractionOutput
LLMProvider
LLMInvocation
LLMRequest
LLMStreamEvent
LLMResponse
LLMMessage
ToolDefinition
ToolSchema
ToolUse
ToolCall
ToolResult
ToolEvent
PermissionRequested
RuntimeEvent
AgentDefinition
```

内部实现支撑类型：

```text
RuntimeBridge
TranscriptState
PendingPermission
PendingPermissionStore
ToolCallState
ErrorPolicy
```
