# 统一 Agent 架构设计

**状态**: 草稿  
**日期**: 2026-04-20  
**背景**: 基于对当前架构的分析与 Codex / Claude Code 对比研究，重新定义 Agent 核心执行模型。

---

## 一、核心设计原则

### 1.1 统一 Agent 模型，支持多实例并发

当前架构将 AssistantAgent 和 AutonomousAgent 作为两个独立类维护，导致两套执行路径、两套历史管理、两套 wait_human 处理。

**新架构结论**：Assistant 和 Autonomous 本质相同——都是接收一段 prompt，执行任务，产出结果。应统一为**一个 Agent 模型（一个类）**，支持多个实例并发运行（例如同时跑候选人发现任务和 JD 同步任务）。

实例之间的区别只体现在各自的 prompt 和配置上，执行逻辑完全一致。任务的终止条件：

- 快速任务：LLM 完成后自然停止（`finish_reason == "stop"`）
- 持续任务：循环执行直到目标达成或触发人工介入插槽

是否持续运行由 **prompt 决定**，不由系统编排决定。

### 1.2 LLM 驱动，Runtime 不做假设

- **目标达成**：LLM 根据 prompt 判断，完成时自然停止调用工具（无需 `complete()` 工具、无需 `gate_signal`、无需 `evaluate()` 阶段）
- **任务类型**：LLM 读懂 prompt 后决定是否需要循环，系统不判断"这是不是自主任务"
- **工具选择**：LLM 根据分类理解决定调用哪个工具，系统不做路由

### 1.3 人工介入是预留插槽

人工介入点在**任务创建时声明**，不在运行时动态生成。LLM 执行到对应节点时调用插槽工具（`wait_human`），runtime 暂停等待人工处理后恢复。

当前的 `ApprovalItem + AgentRunCheckpoint + OperatorInteraction` 三层动态审批链应简化为预声明的插槽机制。

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────┐
│                      Agent                          │
│                                                     │
│  ┌─────────────┐    ┌──────────────────────────┐   │
│  │   Prompt    │    │     Execution Engine      │   │
│  │   Manager   │───▶│     （执行引擎）           │   │
│  │ （提示词管理）│    └────────────┬─────────────┘   │
│  └──────┬──────┘                 │                  │
│         │              ┌─────────▼──────────┐       │
│  ┌──────▼──────┐       │   Context Manager  │       │
│  │   Memory    │◀─────▶│   （上下文管理）    │       │
│  │   Service   │       └─────────┬──────────┘       │
│  │ （记忆服务） │                 │                  │
│  └─────────────┘       ┌─────────▼──────────┐       │
│                        │    Tool Registry    │       │
│  ┌─────────────┐       │  （工具注册表）     │       │
│  │  Execution  │◀──────│                    │       │
│  │    Units    │       └────────────────────┘       │
│  │（隔离执行器）│                                    │
│  └─────────────┘                                    │
└─────────────────────────────────────────────────────┘
```

---

## 三、执行引擎：核心 while 循环

```
输入：prompt + slots（预声明的人工介入插槽）

Turn Start：
  1. Memory.read(scope)          读当前作用域记忆（候选人 / JD / 全局）
  2. Skills.load(relevant)       加载相关 skill 文本
  3. Context.init(               初始化本 Turn 上下文
       system_prompt,
       memory_summary,
       user_prompt
     )

while True:
  ┌─ LLM Call ──────────────────────────────┐
  │  input:  messages                        │
  │  output: finish_reason / content /       │
  │          tool_calls                      │
  └──────────────────────────────────────────┘
          │
  finish_reason == "stop"  ──→  break（任务自然完成）
          │
  tool_calls 存在
          │
  tool == "wait_human"?
    yes ──→  suspend，等待人工处理后 resume，continue
    no  ──→  Tool Registry.execute(tool_calls)
                    │
             bounded result     工具只返回摘要字段，不返回原始内容
                    │
             append to messages
                    │
             [next iteration]

Turn End：
  1. LLM final content = 本轮摘要（LLM 自然产出，非 hardcode）
  2. Memory.write(summary)       跨 Turn 只持久化这条摘要
  3. Context.discard(tool_history)  丢弃本 Turn 原始 tool call 细节
```

---

## 四、提示词管理（Prompt Manager）

### System Prompt 组成（每 Turn 重新组装）

```
1. Identity        身份定义          静态，来自 Agent 配置
2. Behavior Rules  行为规则          静态，来自 Agent 配置
3. Task Prompt     任务专属提示词    动态，按 goal_kind 加载对应文件
4. Skills          可用经验规则      动态，从 SkillRegistry 注入文本块
5. Memory Summary  上次的摘要        动态，从 Memory Service 读取
6. Recent Events   近期关键事件      动态，最近 N 条运行时事件
7. Current Goal    当前目标          来自本次 prompt
```

### User Message

每 Turn 只包含本次触发独有的信息：

```
触发方式：scheduled / resume / manual
当前进度：已完成 N / M
上次停止原因（如有）
本轮特殊约束（如有）
```

不重复 system prompt 中已有的内容。

### Skill 注入方式

Skill 以文本块形式注入 system prompt，LLM 自主决定是否引用：

```
# 可用 Skill
- candidate_scoring_v2: 前端候选人评分规则，重点考察 React/Vue 深度...
- outreach_template_frontend: 已验证的前端岗位首联话术模板...
```

Skill 是给 LLM 读的上下文，不是需要结构化传递的对象。

---

## 五、上下文管理（Context Manager）

### 两层上下文，生命周期不同

```
外层（跨 Turn）
  载体：Memory Service
  内容：LLM 在 Turn 结束时产出的自然语言摘要
  生命周期：持久化，下一 Turn 读取后注入 System Prompt
  谁决定内容：LLM（final output 即摘要，非 hardcode 提取）

内层（Turn 内）
  载体：messages 数组
  内容：system + history + tool_calls + tool_results
  生命周期：Turn 结束即丢弃
```

### Token 压缩策略

Turn 内 messages 接近 token 上限时：

1. 优先清除最早的 tool result（保留 LLM assistant 消息）
2. 保留最近 N 条 tool call 轮次的完整记录
3. System prompt 始终保留

Turn 边界是主要的上下文清洗点，不依赖运行时压缩。

### 对比当前实现的变化

| 维度 | 当前实现 | 新架构 |
|---|---|---|
| 跨 Turn 历史 | round_history 仅 Turn 内有效，跨 Turn 无历史 | Memory 写摘要，下 Turn 读入 system prompt |
| Turn 内上下文 | 同样的 messages 累积 | 同，Turn 结束时主动 discard |
| 压缩机制 | 无 | Turn 边界清洗 + 运行时 token 限制清理 |

---

## 六、工具分类体系（Tool Registry）

### 三类工具

**业务工具（Business Tools）**：直接操作业务对象，产出业务结果。

```
save_candidate          保存候选人到系统
send_outreach           发送外联消息
update_candidate_status 更新候选人阶段
upsert_job_description  创建/更新 JD
record_communication    记录沟通内容
```

**执行工具（Execution Tools）**：完成任务过程中需要的外部能力，不直接产出业务结果。

```
browse_and_extract      浏览页面并提取内容（返回摘要，非原始 HTML）
search_platform         在招聘平台搜索候选人列表
read_candidate_profile  读取候选人详细简历
call_external_api       调用外部 API
```

**Agent 工具（Agent Tools）**：控制 Agent 自身行为，与业务逻辑无关。

```
wait_human              触发预声明的人工介入插槽
read_memory             读取历史记忆
write_memory            写入需要持久化的关键信息
invoke_skill            调用预沉淀的经验规则
schedule_wakeup         安排下次唤醒
```

### 注入 System Prompt 的方式

```
# 可用工具

## 业务工具（Business Tools）
用于直接产出业务结果，优先使用这类工具推进目标。
- save_candidate: 将符合条件的候选人保存到系统
- send_outreach: 向候选人发送招募消息
...

## 执行工具（Execution Tools）
用于获取信息或执行操作，为业务工具提供支撑。
- browse_and_extract: 浏览网页并提取关键内容（返回摘要）
- search_platform: 在招聘平台搜索候选人列表
...

## Agent 工具（Agent Tools）
用于管理任务状态和上下文，不直接产出业务结果。
- wait_human: 当需要人工判断时暂停并等待
- write_memory: 将本轮关键发现写入持久记忆
...
```

### 工具调用的自然顺序

```
执行工具（获取信息）
    → 业务工具（产出结果）
    → Agent 工具（记录 / 控制）
```

### ToolDefinition 字段

```python
ToolDefinition(
    name="save_candidate",
    description="将符合条件的候选人保存到系统，标记为待跟进",
    category="business",        # business / execution / agent
    parameters={...},
    metadata={
        "requires_confirmation": False,   # 是否需要人工确认
    }
)
```

`category` 用于 system prompt 分组展示，也可用于权限控制（特定场景禁用某类工具）。

---

## 七、非主流程上下文隔离

### 7.1 Codex / Claude Code 的参考模型

理解上下文隔离前，需要先厘清两个不同系统的实际机制。

**Codex 的沙箱是 OS 级安全隔离，不是 LLM 上下文隔离。**

```
沙箱控制的是：
  ✓ 哪些文件路径可以被写入（writable_roots）
  ✓ 网络访问权限
  ✓ 进程可以执行哪些系统调用

沙箱不控制的是：
  ✗ LLM 看到什么
  ✗ tool result 是否进主 context
```

subprocess 在沙箱里执行，stdout / stderr **照常回到同一个 LLM context**。Codex 是单一 context 模型，靠 prompt reconstruction（每轮无状态重建）和 bounded output 控制膨胀，不做 LLM 上下文隔离。

**Claude Code 的隔离是显式委托，不是自动路由。**

普通工具（Bash、Read、Write）结果全部进主 context。只有 LLM 主动调用 `Agent` 工具时，子任务才在独立 context 中运行，最终结果以 tool result 形式返回父 Agent。隔离是 LLM 的主动选择，不是系统自动检测。

**核心结论：两者都没有"自动检测该不该隔离"的机制。隔离是显式委托，不是自动路由。**

### 7.2 上下文隔离的两层机制

上下文膨胀问题由两层机制分别负责，互不干扰：

```
第一层：工具自身负责 bounded output（无需 LLM 判断）
─────────────────────────────────────────────────────
工具返回什么，LLM 就看到什么。
工具在设计时就约定只返回摘要，不返回原始内容。

  curl(url)         → {status, headers, body_summary}   不是完整响应体
  bash("ls -la")    → {files: [...], truncated: true}   不是原始输出
  mcp.browse(url)   → {title, key_content, links}       不是原始 HTML

LLM 不需要判断"要不要隔离"，工具已经处理好边界。


第二层：LLM 判断是否需要 Execution Unit（显式委托）
─────────────────────────────────────────────────────
当一个操作需要多步骤协作，且中间过程对主线无意义时，
LLM 通过工具描述判断应委托给独立执行单元。

  比如："解析候选人页面并提取结构化信息"
  → 需要 navigate + wait + scroll + extract 多步
  → 中间步骤对主线 Agent 无意义
  → LLM 调用 browse_and_extract(url)
  → 工具内部走 Execution Unit
  → 主线只看到 {name, experience, skills}
```

### 7.3 LLM 如何知道该走哪层

**靠工具描述，不靠 hardcode 或运行时自动检测。**

```python
# 第一层：普通执行工具，结果有边界
ToolDefinition(
    name="curl_request",
    description="发送 HTTP 请求，返回状态码和响应摘要（非完整响应体）",
    category="execution",
)

# 第二层：委托型工具，内部走 Execution Unit
ToolDefinition(
    name="browse_and_extract",
    description="""
    在浏览器中打开页面并提取结构化内容。
    适用于需要页面交互、等待加载、多步操作的复杂解析场景。
    返回提取摘要，中间步骤不可见。
    """,
    category="execution",
)
```

System Prompt 行为规则中补充：
```
当工具描述说明"返回摘要"或"中间步骤不可见"时，
说明该操作已在隔离环境中执行，直接基于摘要结果继续推进。
```

LLM 的判断依据是工具描述 + 行为规则，隔离复杂度封装在工具实现里，对 LLM 透明。

### 7.4 Execution Unit 的定位

Execution Unit 解决的是**执行复杂度**问题，不是 LLM 上下文隔离问题：

```
主线 messages（LLM 可见）：
  [assistant: 调用 browse_and_extract(url)]
  [tool result: {title, key_fields, summary}]    ← 只有摘要

                    ↑ bounded result 向上透传

Execution Unit 内部（LLM 不可见）：
  navigate(url)
  wait_for_load()
  scroll() × N
  extract_elements()
  → 返回 {title, key_fields, summary}

  原始 HTML、中间步骤、重试细节 → 全部留在 Unit 内部丢弃
```

Execution Unit 的价值：
- 多步骤操作的生命周期管理（超时、取消、重试）
- 副作用操作的安全边界
- 返回值强制为摘要格式

### 7.5 与当前实现的差距

当前 `ExecutionUnitRunner` 已实例化但未接入工具层：

- 无任何工具的 handler 调用 runner
- `RecruitPluginManifest` 未接收 runner 依赖

接入路径：执行工具的 handler 在内部调用 `runner.create_execution_unit()` + `wait_unit()`，对 LLM 完全透明。runner 不需要注入 Agent 主流程，只需注入工具 handler。

---

## 八、各组件职责边界

| 组件 | 职责 | 不负责 |
|---|---|---|
| **Prompt Manager** | 组装 system prompt，注入 skill / memory / goal | 决定任务是否完成 |
| **Execution Engine** | while 循环，调用 LLM，路由工具执行 | 判断任务类型（是否自主） |
| **Context Manager** | 维护 messages 数组，Turn 边界清洗，token 压缩 | 决定什么是重要内容（由 LLM 产出） |
| **Memory Service** | 跨 Turn 状态持久化，按 scope 读写 | 决定摘要内容（LLM 产出） |
| **Tool Registry** | 工具注册、分类、执行、bounded output 约束 | 决定哪个工具被调用（LLM 决定） |
| **Execution Units** | 重型非 LLM 操作隔离执行，返回摘要 | 参与 LLM 推理过程 |

---

## 九、当前架构需要移除的内容

基于以上设计，当前实现中以下内容应被移除或替换：

| 当前概念 | 问题 | 替换方向 |
|---|---|---|
| `AssistantAgent` / `AutonomousAgent` 分离 | 两套执行路径，维护成本高 | 统一为一个 Agent |
| `GoalRef` + `constraints dict` | 目标用 JSON 注入 user 消息，非标准 | 目标写进 system prompt 文本 |
| `Observation` + `InputEnvelope` | 无必要的包装层 | 直接 `list[Message]` |
| `sense()` 阶段 | 可合并进 assemble | 在组装前准备上下文 |
| `Deliberation` 对象 | 中间对象臃肿 | tool results 直接追加进 messages |
| `gate_signal` 系统 | 重复造轮子，覆盖 LLM 原生 finish_reason | 直接用 `finish_reason == "stop"` |
| `PluginHost` guard_check | 过度抽象 | `tool.metadata["requires_confirmation"]` inline 判断 |
| User 消息为 JSON 序列化 payload | LLM 接收 JSON blob 作为 user 消息，语义不自然 | 结构化内容放 system prompt，user 消息为自然语言触发上下文 |
| 动态 `ApprovalItem + Checkpoint + Interaction` | 运行时动态生成审批链 | 任务创建时预声明插槽 |

---

## 十、待明确的问题

1. **Turn 边界的定义**：快速任务（一次 while 循环即结束）的"Turn"如何界定，与持续任务保持一致？
2. **Memory scope 设计**：candidate / job / global 三域是否保留，还是简化为 goal-scoped？
3. **Execution Units 触发时机**：哪些执行工具需要走 Execution Unit，哪些直接同步执行？判断标准是什么？
4. **历史消息上限**：Turn 内 messages 的 token 上限如何配置，压缩策略的具体触发阈值？
5. **Skill 生命周期**：trial skill 到 active skill 的晋升流程在新架构下如何保留？
