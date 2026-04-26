# Agent 上下文与记忆架构设计参考

> 本文档汇总 Claude Code 在 coding 场景中的上下文管理、三层记忆架构、记忆检索机制、
> LLM API 协议设计等关键设计点，作为 recruit-agent 中 Autonomous Agent / Assistant Agent
> 设计的参考资料。

> **术语约定**：文中 **Observation** 指一次 turn 从 DB / 外部系统实时拉取的"真实世界快照"
> （候选人数、待审队列长度、最近事件等），对应 ReAct 论文里的 observation 语义。
> Observation 永远活在 user 消息里、每 turn 重新生成；不进 system，不打缓存。

## 目录

- [Part 1：编码 + 调试场景的上下文流转](#part-1编码--调试场景的上下文流转)
  - [场景设定](#场景设定)
  - [全流程图](#全流程图)
  - [每次 LLM 调用携带的内容](#每次-llm-调用携带的内容)
  - [压缩时刻的内部动作](#压缩时刻的内部动作)
  - [关键差异对比表](#关键差异对比表)
  - [三个关键洞察](#三个关键洞察)
- [Part 2：三层记忆架构](#part-2三层记忆架构)
  - [完整视图](#完整视图)
  - [三层读写策略对比](#三层读写策略对比)
  - [三层在 coding 例子中的对应](#三层在-coding-例子中的对应)
  - [三层之间的迁移机制](#三层之间的迁移机制)
- [Part 3：实际配置 path 速查](#part-3实际配置-path-速查)
- [Part 4：记忆索引格式（MEMORY.md）](#part-4记忆索引格式memorymd)
  - [一行索引的格式](#一行索引的格式)
  - [三种典型条目示例](#三种典型条目示例)
  - [为什么这种格式有效](#为什么这种格式有效)
- [Part 5：记忆检索机制（不是 RAG）](#part-5记忆检索机制不是-rag)
  - [Claude Code 的实际机制](#claude-code-的实际机制)
  - [什么是 Embedding](#什么是-embedding)
  - [完整 RAG 流程（对比参考）](#完整-rag-流程对比参考)
  - [Embedding 的优劣](#embedding-的优劣)
  - [为什么 Claude Code 不用 Embedding 处理记忆](#为什么-claude-code-不用-embedding-处理记忆)
  - [三种检索方式选型矩阵](#三种检索方式选型矩阵)
  - [元数据 + 详情分离的设计模式](#元数据--详情分离的设计模式)
- [Part 6：LLM API 角色协议（System / User / Assistant / Tool）](#part-6llm-api-角色协议system--user--assistant--tool)
  - [四个角色的定位](#四个角色的定位)
  - [各种内容应该放哪](#各种内容应该放哪)
  - [OpenAI vs Anthropic 完整对比](#openai-vs-anthropic-完整对比)
  - [两家的关键差异](#两家的关键差异)
  - [容易漏掉的几个东西](#容易漏掉的几个东西)
  - [System vs User 的设计决策](#system-vs-user-的设计决策)
- [Part 7：映射到 recruit-agent 的 Autonomous Agent 设计](#part-7映射到-recruit-agent-的-loop-agent-设计)
- [Part 8：术语表与 cache_control 深入](#part-8术语表与-cache_control-深入)
  - [术语：Turn / Round / Run / Session](#术语turn--round--run--session)
  - [cache_control 深入：标记 ≠ 命令](#cache_control-深入标记--命令)
  - [Autonomous Agent 的缓存策略](#loop-agent-的缓存策略)

---

# Part 1：编码 + 调试场景的上下文流转

## 场景设定

> 用户：「给 User 类加邮箱格式验证，并修好失败的 test_invalid_email」

涉及的步骤：读文件 → 改代码 → 跑测试 → 测试失败 → 调试循环 → context 满 → 压缩 → 继续。

## 全流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                      Claude Code 进程内                          │
│                                                                  │
│  启动时加载：                                                     │
│    · System Prompt（固定，~5K tokens，含工具定义）                │
│    · CLAUDE.md（项目规则，~1K tokens）                            │
│    · messages[] = []  ← 对话历史，初始为空                        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                    用户输入："给 User 加邮箱验证..."
                                │
                                ▼
                       追加到 messages[]
```

## 每次 LLM 调用携带的内容

每次调用 LLM 都带**完整累积历史**，不是增量。下面是关键 6 次调用的对比：

### Call #1 — 初次决策

```
发送给 LLM：
┌───────────────────────────────────┐
│ system: 工具定义 + 行为规则         │  ← 永远固定
│ system: CLAUDE.md 内容             │  ← 永远固定
│ user: "给 User 加邮箱验证..."      │
└───────────────────────────────────┘
约 7K tokens

LLM 返回：
"我先读一下 User 类和测试"
+ tool_call: Read(src/user.py)
+ tool_call: Read(tests/test_user.py)
```

### Call #2 — 拿到文件内容后决策

```
发送给 LLM：
┌───────────────────────────────────┐
│ system: 工具定义                   │
│ system: CLAUDE.md                  │
│ user: "给 User 加邮箱验证..."      │
│ assistant: "我先读一下..."          │
│ tool_result: <user.py 200 行>      │  ← 新增
│ tool_result: <test_user.py 50 行>  │  ← 新增
└───────────────────────────────────┘
约 12K tokens

LLM 返回：
"加 validate 方法"
+ tool_call: Edit(src/user.py, ...)
```

### Call #3 — 改完跑测试

```
发送给 LLM：
┌───────────────────────────────────┐
│ system: 工具定义                   │
│ system: CLAUDE.md                  │
│ user: "给 User 加邮箱验证..."      │
│ assistant: "我先读一下..."          │
│ tool_result: <user.py>             │
│ tool_result: <test_user.py>        │
│ assistant: "加 validate"            │
│ tool_result: "Edit applied"        │  ← 新增
└───────────────────────────────────┘
约 13K tokens

LLM 返回：
"跑测试"
+ tool_call: Bash("pytest")
```

### Call #4 — 测试失败，进入调试

```
发送给 LLM：
┌───────────────────────────────────┐
│ ... 之前所有内容 ...                │
│ tool_result: ❌ FAILED              │  ← 新增
│   AssertionError: expected         │
│   ValidationError, got TypeError   │
│   <50 行 stack trace>              │
└───────────────────────────────────┘
约 16K tokens

LLM 返回：
"错误类型不对，找 ValidationError 定义"
+ tool_call: Grep("class ValidationError")
```

### Call #5-#10 — 调试螺旋（context 暴涨）

```
每一次都累积：
  · 多次 Grep 结果
  · 多次 Read 不同文件
  · 多次 Edit 尝试
  · 多次 Bash 跑测试
  · 多次失败的错误堆栈

context 从 16K 涨到 ~150K
                ↓
        ⚠️ 接近窗口上限（200K）
                ↓
        触发自动压缩
```

## 压缩时刻的内部动作

```
┌──────────────────────────────────────────────────────────┐
│             AUTO-COMPACT 触发                             │
│                                                           │
│  压缩策略（按顺序）：                                      │
│                                                           │
│  ① 丢弃最老的 tool_results                                │
│     · src/user.py 的原始内容（已经改过了，没用了）         │
│     · test_user.py 的原始内容                             │
│     · 早期的 Bash 输出                                    │
│                                                           │
│  ② 保留：                                                 │
│     · system prompt（不动）                               │
│     · CLAUDE.md（不动）                                   │
│     · 最早的 user message（任务描述）                     │
│     · 最近 2-3 次 tool_result（最新 Observation）         │
│                                                           │
│  ③ 中间消息压成一段 SUMMARY：                              │
│     "已进展：                                              │
│      - User.validate 方法已添加                            │
│      - 测试失败原因：ValidationError 类型不匹配            │
│      - 已定位 ValidationError 在 src/exceptions.py        │
│      - 尝试了 3 种 import 方式，最近一次还是失败"          │
│                                                           │
│  压缩前 150K → 压缩后 ~25K                                │
└──────────────────────────────────────────────────────────┘
```

### Call #11 — 压缩后继续

```
发送给 LLM：
┌───────────────────────────────────┐
│ system: 工具定义                   │  ← 永远在
│ system: CLAUDE.md                  │  ← 永远在
│ user: "给 User 加邮箱验证..."      │  ← 保留
│ ┌─────────────────────────────┐   │
│ │ [Compacted Summary]:         │   │  ← 中间 7 次调用被压成这一段
│ │ "已添加 validate，           │   │
│ │  测试失败因 ValidationError   │   │
│ │  类型问题，已定位..."          │   │
│ └─────────────────────────────┘   │
│ tool_result: <最近一次测试输出>    │  ← 保留最新的几个
│ tool_result: <最近一次 Read 结果>  │
└───────────────────────────────────┘
约 25K tokens

LLM 返回：
"我重新读一下 User 类确认当前状态"
+ tool_call: Read(src/user.py)
       ↑
   关键行为：不依赖被压缩的「记忆」，重新读文件
```

## 关键差异对比表


| Call # | 增量内容         | 累积大小      | LLM 决策的依据       |
| ------ | ------------ | --------- | --------------- |
| 1      | 用户原始消息       | 7K        | 任务描述            |
| 2      | 2 个文件内容      | 12K       | 看到的源代码          |
| 3      | Edit 结果      | 13K       | 改动确认            |
| 4      | 测试失败堆栈       | 16K       | 错误信息            |
| 5-10   | 多次调试动作       | 150K      | 累积的尝试和反馈        |
| **压缩** | (压成 summary) | **25K**   | **摘要 + 最近状态**   |
| 11+    | 重新读取的文件      | 30K → ... | **文件本身 = 真实状态** |


## 三个关键洞察

**1. LLM 是无状态的，每次都重传所有上下文**
Claude Code 进程本身维护 messages[]，每次调用 API 都把完整历史发过去。LLM 不「记得」上次说了什么，全靠传过去的内容。

**2. 文件 = 真实状态，messages[] = 工作记忆**
压缩会丢工作记忆，但文件不会。所以压缩后的策略是**重新读文件**，而不是相信 summary 里的描述。

**3. 永远不丢的东西**

- System prompt + CLAUDE.md（每次都完整带上）
- 最早的 user message（任务描述，压缩时被概括但不删）
- 最近 N 个 tool 结果（保持「Observation」感知）

---

# Part 2：三层记忆架构

## 完整视图

```
┌─────────────────────────────────────────────────────────────┐
│  长期记忆 (Long-term)                                         │
│  ─────────────────────────                                   │
│  存储位置：磁盘                                                │
│    · CLAUDE.md（项目级 / 用户级 / 企业级层叠）                │
│    · ~/.claude/projects/<proj>/memory/*.md（自动记忆）       │
│  生命周期：跨 session，永久                                    │
│  写入方式：Edit 工具 / 自动记忆机制（Write 工具 + MEMORY.md） │
│  读取方式：session 启动时加载（CLAUDE.md），按需 Read（memory）│
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ 偶尔写入（重要规则、用户偏好）
                            │
┌─────────────────────────────────────────────────────────────┐
│  中期记忆 (Medium-term)                                       │
│  ─────────────────────────                                   │
│  存储位置：session.jsonl（磁盘）+ 进程内压缩摘要               │
│    · 完整对话历史持久化（可回溯）                              │
│    · 压缩后的 summary（替代被丢弃的早期消息）                  │
│  生命周期：单个 session 内                                    │
│  写入方式：自动追加 / 压缩时生成 summary                       │
│  读取方式：压缩后注入 messages[]，--continue 恢复 session     │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ context 满时自动触发
                            │
┌─────────────────────────────────────────────────────────────┐
│  短期记忆 (Short-term)                                        │
│  ─────────────────────────                                   │
│  存储位置：进程内存（messages[]）                              │
│    · 当前 user/assistant/tool 消息                            │
│    · 最近的 tool_results                                      │
│  生命周期：到下一次压缩 / session 结束                         │
│  写入方式：每次 LLM 响应、每次 tool 执行自动追加               │
│  读取方式：每次 LLM 调用完整传入                               │
└─────────────────────────────────────────────────────────────┘
```

## 三层读写策略对比


| 维度        | 短期                 | 中期                         | 长期                   |
| --------- | ------------------ | -------------------------- | -------------------- |
| **存储**    | 进程内存 `messages[]`  | session.jsonl + 压缩 summary | 磁盘 .md 文件            |
| **写入触发**  | 每次对话/工具自动          | 压缩时 / 每条消息持久化              | 显式 Edit / 自动记忆       |
| **读取方式**  | 每次 LLM 调用全量传       | 压缩后注入 / `--continue`       | 启动加载 + 按需 Read       |
| **可见性**   | LLM 直接看到           | 被压缩成摘要后 LLM 看到             | system prompt 注入     |
| **大小限制**  | 几 K~几十 K           | 不限（jsonl）/ 几 K（summary）    | 几 K（CLAUDE.md 200 行） |
| **被覆盖风险** | 高（压缩时被 summary 替换） | 中（持久化但不重读）                 | 低（手动修改才会变）           |
| **适合存什么** | 当前任务推理过程           | 阶段性进展摘要                    | 不变的规则、长期偏好           |


## 三层在 coding 例子中的对应

```
Call #1                Call #2-#10           压缩事件          Call #11+
   │                        │                    │                  │
   ▼                        ▼                    ▼                  ▼

[长期] CLAUDE.md  ────────────────永远在 system prompt 里───────────────►

[短期] messages = []   messages 累积到 150K   ──────► messages 重置为 25K
                                                  ↓
[中期]                                       生成 summary
                                            写入 messages
                                                  │
[中期] session.jsonl 同时被持续追加（完整原始历史）
       ↑
       --continue 时可以恢复

[长期] memory/*.md   ←── 如果 Claude 学到了「该项目的导入方式特殊」
                          可能写入 memory，下次 session 还在
```

## 三层之间的迁移机制

```
短期 ──压缩──► 中期 (summary)
   │
   │ 被丢弃的内容仍在 jsonl
   ▼
session.jsonl (中期持久化)

中期 ──手动/自动记忆──► 长期 (CLAUDE.md / memory/*.md)
   ↑
   只有「值得跨 session 记住」的才升级
```

**关键原则**：

- 短期 → 中期：自动（压缩触发）
- 中期 → 长期：**几乎不自动**（需要主动判断或手动）

这就是为什么 Claude Code 经常「上次说过了，这次又问一遍」——除非显式让它写入 CLAUDE.md，否则中期记忆不会升级。

---

# Part 3：实际配置 path 速查

```
长期记忆相关
  ~/.claude/                              ← 用户级根目录
  ├── settings.json                       ← 用户级配置
  ├── CLAUDE.md（如果存在）                ← 用户级全局规则
  ├── skills/                             ← 用户安装的 skills
  ├── plugins/                            ← 插件目录
  └── projects/<encoded-path>/memory/     ← 自动记忆目录
      ├── MEMORY.md                       ← 索引（永远加载）
      └── *.md                            ← 单个记忆文件（按需读）

  示例（recruit-agent 项目）:
    /Users/didi/.claude/projects/-Users-didi-AgentProjects-recruit-agent/memory/
    ├── MEMORY.md                         ← 索引文件
    └── feedback_simple_responses.md      ← 单个记忆文件

  项目级
  <project_root>/
  ├── CLAUDE.md  或  AGENTS.md            ← 项目级规则（每次 session 加载）
  └── .claude/
      ├── settings.json                   ← 项目级配置（可入库）
      └── settings.local.json             ← 项目本地配置（gitignore）

中期记忆相关
  ~/.claude/projects/<encoded-path>/
  ├── <session-id>.jsonl                  ← 完整对话历史（中期，可 --continue 恢复）
  └── <session-id>/                       ← 该 session 的工作目录

  ~/.claude/history.jsonl                 ← 全局命令历史
  ~/.claude/tasks/                        ← subagent 任务输出
  ~/.claude/plans/                        ← 计划模式产物

短期记忆
  无文件，活在进程内存里
```

## 路径编码规则

项目路径转 encoded-path 时，`/` 替换为 `-`：

```
/Users/didi/AgentProjects/recruit-agent
        ↓
-Users-didi-AgentProjects-recruit-agent
```

---

# Part 4：记忆索引格式（MEMORY.md）

`MEMORY.md` 是自动记忆的**索引文件**，每次 session 启动时被加载到 system prompt。
它本身不存储内容，只列出有哪些记忆文件可读。

## 一行索引的格式

```
- [Simple responses](feedback_simple_responses.md) — User prefers short answers...
  ↑       ↑                  ↑                      ↑
  列表    标题             文件名                    描述（hook）
  符号  （给人看）       （Read 时用）            （给 LLM 判断）
```

格式：`- [标题](文件名) — 一句话描述`


| 字段      | 作用        | 谁读           |
| ------- | --------- | ------------ |
| `[标题]`  | 人类可读的简短标签 | 用户浏览索引时      |
| `(文件名)` | 实际记忆文件名   | LLM 调 Read 时 |
| `— 描述`  | 触发性 hook  | LLM 判断是否需要读  |


## 三种典型条目示例

```
- [Simple responses](feedback_simple_responses.md) — User prefers short answers...
                                  ↑
                          类型：feedback（用户偏好/反馈）
                          作用：当我准备长篇回复时，LLM 看到这条 → 想到要简洁

- [Project goals](project_goals.md) — Q2 priorities and ownership
                              ↑
                      类型：project（项目状态）
                      作用：当你问「这个季度要做什么」时 → LLM 想到读这个

- [API quirks](reference_api_notes.md) — Internal API gotchas
                              ↑
                      类型：reference（参考资料）
                      作用：当你调用某个内部 API 出问题时 → LLM 想到看这个
```

记忆有四种标准类型（见自动记忆机制设计）：

- `user`：用户身份、角色、知识背景
- `feedback`：用户对你工作方式的反馈和指导
- `project`：项目当前状态、决策、动机
- `reference`：外部资源指针（Linear、Slack、监控面板等）

## 单个记忆文件的实际内容

```markdown
---
name: prefer_simple_responses
description: User prefers short, direct answers...
type: feedback
originSessionId: 5f0c7d28-5d4a-4093-b133-3f2427dbe344
---
Keep responses concise and directly answer the question; avoid long explanations unless the user explicitly asks for detail.

**Why:** The user explicitly said "太啰嗦了，简单点。"
**How to apply:** For plan checks, scope judgments, and conceptual clarifications, lead with the answer in 1-3 short bullets and only expand if asked.
```

`frontmatter` 里：

- `name`：唯一标识
- `description`：跟索引里的描述对齐
- `type`：上述四种之一
- `originSessionId`：哪个 session 产生的（可追溯）

正文：规则 + **Why** + **How to apply**，让未来的 LLM 能判断边界情况。

## 为什么这种格式有效

```
LLM 启动时看到 system prompt 里有这一行：
- [Simple responses](feedback_simple_responses.md) — User prefers short answers

你问了一个问题
   │
   ▼
LLM 判断：「我准备给一个长篇回复 → 描述里说 user prefers short → 我应该缩短」
   │
   ▼
不需要读整个 feedback_simple_responses.md，描述本身就够指导行为了
```

**「描述」是核心**——好的描述让 LLM 不用读文件就能调整行为；不够的时候才会去 Read 完整内容。

---

# Part 5：记忆检索机制（不是 RAG）

**结论：纯靠 LLM 判断 + 索引文件，没有 embedding，没有向量检索。**

## Claude Code 的实际机制

```
session 启动
   │
   ▼
加载 MEMORY.md（整个文件，~150 行内）注入到 system prompt
   │
   ▼
LLM 看到索引，知道有哪些记忆可用，但只看到描述
   │
   ▼
对话过程中，LLM 自己判断「这条描述跟当前问题相关吗？」
   │
   ├── 不相关 → 不读
   └── 相关   → 调 Read 工具读具体文件
```

## 什么是 Embedding

**一句话定义**：把任意文字变成一组数字（向量），让「意思相近」的文字得到「相近的向量」。

### 具体例子

```
文字              →   embedding（简化展示，实际是 768 或 1536 维）
"猫"              →   [0.21, -0.45, 0.83, ...]
"小猫"            →   [0.23, -0.41, 0.85, ...]   ← 跟「猫」很近
"狗"              →   [0.18, -0.39, 0.79, ...]   ← 跟「猫」也比较近（都是宠物）
"汽车"            →   [-0.65, 0.72, -0.11, ...]  ← 跟「猫」差很远
```

「相近」用**余弦相似度**算——两个向量的夹角越小，相似度越高（最大 1，最小 -1）。

### 用来做什么：语义搜索

```
传统关键词搜索：
  搜「猫」→ 只能找到包含「猫」字的文档
  搜不到「小喵咪很可爱」（没有「猫」字）

Embedding 搜索：
  搜「猫」→ 把「猫」转成向量
       ├── 跟所有文档的向量比相似度
       └── 找出最相似的几篇
  能找到「小喵咪很可爱」（语义相近）
```

## 完整 RAG 流程（对比参考）

RAG = Retrieval Augmented Generation，「检索增强生成」。Cursor 索引代码库用的就是这套：

```
1. 索引阶段（一次）
   ┌──────────────┐
   │  代码库      │
   │  10000 文件  │
   └──────┬───────┘
          │ 每个文件 → embedding 模型 → 向量
          ▼
   ┌──────────────┐
   │ 向量数据库    │   存 10000 个向量
   │              │
   └──────────────┘

2. 查询阶段（每次提问）
   你的问题：「怎么处理用户登录失败」
          │
          │ → embedding 模型 → 问题的向量
          ▼
   跟 10000 个向量算相似度 → 取 top 5
          │
          ▼
   把这 5 个文件内容塞进 LLM 的 context
          │
          ▼
   LLM 基于这些内容回答
```

## Embedding 的优劣

```
✅ 优点：
  · 能跨词汇匹配（猫 ≈ 喵咪 ≈ kitten）
  · 处理大规模文档（百万级也能秒查）
  · 不需要关键词精确匹配

❌ 缺点：
  · 需要模型生成 embedding（OpenAI/Cohere 等收费 API）
  · 需要向量数据库基础设施（Pinecone/Weaviate/pgvector 等）
  · 经常召回「语义近但实际无关」的内容（搜「登录失败」可能召回「支付失败」）
  · 不透明：你不知道为什么这一条被排第一
```

## 为什么 Claude Code 不用 Embedding 处理记忆

```
Claude Code 的记忆典型规模：
  · 几十到几百条
  · 每条都是精心写的描述（一句话讲清是什么）

→ 让 LLM 直接读这几百行索引描述，比 embedding 检索更精准
→ 因为 LLM 能做更细的语义判断（不只是「相似」，还能推理）

对比 Cursor 的代码库：
  · 几万个文件
  · 没人手写描述

→ 必须用 embedding，否则塞不进 context
```

## 三种检索方式选型矩阵


| 数据特征         | 应该用                   | 例子                     |
| ------------ | --------------------- | ---------------------- |
| 量小、有人工描述     | 索引 + LLM 判断           | Claude Code 的记忆        |
| 量大、原始文本、半结构化 | embedding + 向量检索（RAG） | Cursor 的代码库索引          |
| 量大、强结构化      | SQL 查询 / 表索引          | Autonomous Agent 的候选人池 |


## 元数据 + 详情分离的设计模式

`MEMORY.md` 是元数据索引，`memory/*.md` 是详情。这是个经典两阶段设计：


| 系统             | 元数据                     | 详情                |
| -------------- | ----------------------- | ----------------- |
| 文件系统           | inode（文件名、大小、权限）        | 实际数据块             |
| HTTP           | HEAD 请求（headers）        | GET 请求（body）      |
| 数据库            | 表结构、索引                  | 行数据               |
| Git            | tree object（文件名 + hash） | blob object（文件内容） |
| Claude Code 记忆 | MEMORY.md               | memory/*.md       |


### 对 LLM 特别有效的原因

```
全部塞进 context（不分元数据/详情）：
  100 条记忆 × 每条 500 tokens = 50K tokens 浪费在不相关内容上

只塞元数据：
  100 条记忆 × 每条描述 30 tokens = 3K tokens
  + LLM 判断后读 1-2 条详情 = 1K tokens
  ─────────────────────────────────
  总共 4K tokens，96% 节省
```

**前提是元数据写得好**——一句描述如果写得模糊（比如「用户偏好」），LLM 没法判断；
写得精准（「短回复偏好，避免长篇解释」），LLM 不读详情都能调整行为。

## 写入机制对比

```
Claude Code 的记忆写入：
  学到一个用户偏好/项目事实
     │
     ▼
  用 Write 工具创建一个新 .md 文件（带 frontmatter）
     │
     ▼
  用 Edit 工具往 MEMORY.md 加一行索引
     │
     ▼
  下次 session 启动时，新索引就在 system prompt 里

完全是人类可读、可编辑的 markdown，没有任何二进制存储。
```

---

# Part 6：LLM API 角色协议（System / User / Assistant / Tool）

理解 LLM API 的角色协议，是设计 agent 的基础。每种内容应该放在哪个角色里，
直接影响 token 成本、缓存效率和模型行为。

## 四个角色的定位

```
┌─────────────────────────────────────────────────────────────┐
│ system    │ 「你是谁」「规则是什么」「能用什么工具」          │
│           │ → 跨整个对话稳定的内容                            │
├───────────┼──────────────────────────────────────────────────┤
│ user      │ 「我要你做什么」「这是工具执行结果」              │
│           │ → 来自外部世界（人类/工具/环境）                  │
├───────────┼──────────────────────────────────────────────────┤
│ assistant │ 「我的回复」「我要调这个工具」                    │
│           │ → 来自 LLM 自己                                   │
├───────────┼──────────────────────────────────────────────────┤
│ tool      │ 「工具执行的具体输出」（OpenAI 单独一类）         │
│           │ → Anthropic 把这个放在 user 消息里                │
└───────────┴──────────────────────────────────────────────────┘
```

## 各种内容应该放哪


| 内容                      | 放在哪个角色                           | 理由       |
| ----------------------- | -------------------------------- | -------- |
| Persona / 行为规则          | system                           | 永远稳定     |
| 工具定义                    | tools 字段（不是 messages）            | 独立协议     |
| CLAUDE.md / 项目规则        | system                           | 长期记忆     |
| MEMORY.md 索引            | system                           | 元数据，启动注入 |
| 用户的原始任务                 | user（第一条）                        | 任务来源     |
| LLM 的文字回复               | assistant                        | LLM 输出   |
| LLM 决定调工具               | assistant（带 tool_use/tool_calls） | LLM 的动作  |
| 工具执行结果                  | OpenAI: tool；Anthropic: user     | 工具反馈     |
| 压缩 summary              | system 或 user（注入）                | 看实现策略    |
| 候选人/JD 的 memory（你的场景）   | system 或 user                    | 取决于稳定度   |
| 实时 Observation（DB 查询结果） | user（每次注入）                       | 动态变化     |


## OpenAI vs Anthropic 完整对比

同一段对话，「读文件 → 看到结果 → 回答」三轮：

### OpenAI 格式

```json
{
  "model": "gpt-4o",
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "read_file",
        "description": "Read a file from disk",
        "parameters": {
          "type": "object",
          "properties": {"path": {"type": "string"}},
          "required": ["path"]
        }
      }
    }
  ],
  "messages": [
    {
      "role": "system",
      "content": "你是 Claude Code 助手。\n\n# CLAUDE.md\n项目用 pnpm...\n\n# MEMORY.md\n- [偏好](pref.md) — 简洁回复"
    },
    {
      "role": "user",
      "content": "读一下 user.py 看看实现"
    },
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": {
            "name": "read_file",
            "arguments": "{\"path\": \"src/user.py\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_abc123",
      "content": "class User:\n    def __init__(self, email):\n        ..."
    },
    {
      "role": "assistant",
      "content": "User 类只有构造函数，缺 validate。我加上。"
    }
  ]
}
```

### Anthropic 格式

```json
{
  "model": "claude-sonnet-4-6",
  "max_tokens": 4096,
  "system": [
    {
      "type": "text",
      "text": "你是 Claude Code 助手。\n\n# CLAUDE.md\n项目用 pnpm...\n\n# MEMORY.md\n- [偏好](pref.md) — 简洁回复",
      "cache_control": {"type": "ephemeral"}
    }
  ],
  "tools": [
    {
      "name": "read_file",
      "description": "Read a file from disk",
      "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"]
      }
    }
  ],
  "messages": [
    {
      "role": "user",
      "content": "读一下 user.py 看看实现"
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "tool_use",
          "id": "toolu_abc123",
          "name": "read_file",
          "input": {"path": "src/user.py"}
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "toolu_abc123",
          "content": "class User:\n    def __init__(self, email):\n        ..."
        }
      ]
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "text",
          "text": "User 类只有构造函数，缺 validate。我加上。"
        }
      ]
    }
  ]
}
```

## 两家的关键差异


| 维度           | OpenAI                  | Anthropic                              |
| ------------ | ----------------------- | -------------------------------------- |
| system 位置    | messages 数组里第一条         | 顶层 `system` 字段                         |
| system 是否可多段 | 单字符串                    | 可以多个 content block                     |
| tool 调用      | assistant.tool_calls 字段 | assistant.content 里 type=tool_use      |
| tool 结果      | 单独 role: "tool"         | role: "user" + type=tool_result        |
| 缓存控制         | 自动（前缀缓存）                | 显式 `cache_control` 标记                  |
| content 类型   | 多数是字符串                  | 强制结构化（text/tool_use/tool_result/image） |
| 多模态          | content 数组里 image_url   | content 数组里 type=image                 |


## 容易漏掉的几个东西

### 1. Tool 定义不在 messages 里

```
tools: [...]      ← 独立顶层字段
messages: [...]   ← 对话内容
```

很多人以为工具定义要写进 system prompt 里描述，其实有专门的 `tools` 字段，模型会自动理解格式。

### 2. Anthropic 的缓存控制（**省钱的关键**）

```json
{
  "system": [
    {"type": "text", "text": "大段稳定的 prompt..."},
    {"type": "text", "text": "MEMORY.md 索引...", "cache_control": {"type": "ephemeral"}}
  ]
}
```

打了 `cache_control` 标记的部分会被 5 分钟缓存，下次同样前缀只收 10% 的费用。
**对长 system prompt 节省巨大。**

### 3. Prefill（Anthropic 独有）

可以让 assistant 消息只写一半，让模型「续写」：

```json
{
  "role": "assistant",
  "content": "{"
}
```

模型会从 `{` 开始续写，强制它输出 JSON。这是控制输出格式的利器。

### 4. stop_reason / finish_reason

```
OpenAI: "stop" | "length" | "tool_calls" | "content_filter"
Anthropic: "end_turn" | "max_tokens" | "tool_use" | "stop_sequence"
```

agent loop 必须根据这个判断「是模型主动停了」还是「需要执行工具后再继续」。

### 5. 多轮 tool_use 的关键约束

```
assistant 消息有 tool_use → 下一条必须是 tool_result
不能跳过，不能合并
否则 API 报错
```

这是设计 agent loop 时最容易踩坑的地方。

## System vs User 的设计决策

```
放 system 的特征：
  · 跨整个 session 稳定不变
  · 是「规则」「身份」「能力」类的内容
  · 不是「数据」
  · 例：persona、工具说明（如果不用 tools 字段）、长期偏好

放 user 的特征：
  · 这次对话才相关
  · 是「数据」「事实」「上下文」
  · 可能动态变化
  · 例：当前候选人信息、实时 DB 查询结果、用户的具体问题

灰色地带（Memory）：
  · MEMORY.md 索引 → system（稳定）
  · 当前候选人的 CandidateMemory → 应该是 user 注入（动态）
  · GlobalMemory → 看更新频率：低频用 system，高频用 user
```

---

# Part 7：映射到 recruit-agent 的 Autonomous Agent 设计

## 各层对应关系


| Claude Code      | Autonomous Agent                                                             | 现有代码状态            |
| ---------------- | ---------------------------------------------------------------------------- | ----------------- |
| 短期：messages[]    | turn 内各 round 的临时上下文                                                         | ❌ 不做跨 turn 累积；每个 turn 起点重组装 |
| 中期：压缩 summary    | `CandidateSession.context_summary` / `conversation_sessions.context_summary` | ✅ 已有              |
| 中期：session.jsonl | `conversation_sessions.jsonl_path`（原始消息历史）                                   | ✅ Assistant 已定义   |
| 事件流              | `AgentRuntimeEvent`（运行事件真相源，不承载 message history）                             | ✅ 已有              |
| 长期：CLAUDE.md     | `prompt_config`                                                              | ✅ 已有              |
| 长期：memory/*.md   | `AgentGlobalMemory` / `CandidateMemory` / `JobMemory`                        | ✅ 已有，分多层          |


## 比 Claude Code 更有优势的地方

每个候选人有独立 memory（`CandidateMemory`），每个 JD 有独立 memory（`JobMemory`）。
这是 Claude Code 没有的「按实体分片的长期记忆」——本质上是因为你的领域有清晰的实体边界，
而 Claude Code 的领域（任意代码库）没有。

## 应该简化的

- **不要**学 Claude Code 的短期 messages[] 跨 turn 累积。Autonomous Agent 每个 turn 都独立从最新 Observation 出发，不需要长期「连续叙事」。
- **不要**学 Claude Code 的压缩机制。中期记忆是 DB 实时查询，不需要压缩。

## 应该学的

1. **长期 → 短期的注入方式**：每个 turn 把 GlobalMemory + 当前候选人的 CandidateMemory 注入到 LLM context。
2. **「中期 → 长期」的升级机制**：当 Skill 学到通用规律时，写入 GlobalMemory（现在用 EvolutionArtifact 做这个，需要更顺畅的自动通道）。
3. **记忆检索方式**：跟 Claude Code 一样用「索引 + LLM 判断」，**不要上 RAG**——候选人池规模够小、描述够精炼时，索引判断比向量检索更准。
4. **MEMORY.md 风格的索引设计**：给每条 GlobalMemory 写一行精炼描述，让 Orchestrator LLM 不用读全文就能判断相关性。
5. **元数据 + 详情分离**：`disclosure.preview` 当元数据，`disclosure.model_context` 当详情。每个 turn 只注入元数据，按需读详情。

## Autonomous Agent 一次 turn 的 LLM 调用结构

按本文 Part 6 的协议，建议这样组织：

```
system: [
  ┌────────────────────────────────┐
  │ Persona: "你是招聘助理..."        │  ← 永远稳定
  ├────────────────────────────────┤
  │ prompt_config（用户的 prompt）   │  ← session 级稳定
  ├────────────────────────────────┤
  │ GlobalMemory 索引                │  ← 元数据，让 LLM 判断要不要详读
  └────────────────────────────────┘
  cache_control: ephemeral  ← 整个 system 打缓存

tools: [
  search_candidates,
  score_candidate,
  sync_resume,
  request_contact,
  ...
]

messages: [
  {
    role: "user",
    content: "## 当前 Observation\n候选人池：18人（低于阈值20）\n待评分：5人\n..."
  }
  ↑ 每个 round 现拼；Observation 属于当前 turn 的动态输入，不打缓存
]
```

**关键设计**：

1. 把 system 设计得**尽量稳定**（拿满缓存折扣）
2. 把每个 turn 变化的「Observation」放 user
3. GlobalMemory 用元数据 + 详情分离的方式注入，避免每个 turn 全量塞进去

## 核心结论

Claude Code 之所以靠 messages[] 累积，是因为代码 coding 是**线性叙事**——每步都依赖前一步的中间推理。
Autonomous Agent 是**周期性决策**——每次只需要看「当前 Observation」，根本不需要 messages[] 历史。

这是 Autonomous Agent 比 Claude Code 更幸运的地方：

- 真相状态在 DB 里（结构化，可 SQL 查，Observation 靠 SQL 拉出来即可）
- 长期判断在 Memory 表里（按实体分片）
- 不需要短期 messages[]，可以彻底跳过 context 管理这个难题

---

# Part 8：术语表与 cache_control 深入

## 术语：Turn / Round / Run / Session

这几个词在 agent 设计里很容易混。统一定义：


| 术语          | 含义                                                               | 时间尺度  | 例子                                                                                      |
| ----------- | ---------------------------------------------------------------- | ----- | --------------------------------------------------------------------------------------- |
| **Turn**    | Driver 处理一次触发后的完整 LLM 驱动循环，直到遇到 `wait_human` / `complete` / `escalate` 等边界 | 秒级~分钟级 | Heartbeat 取到一个任务后，围绕它跑完若干次 `run_round()`，最终结束当前 turn                                   |
| **Round**   | `AgentKernel.run_round()` 的一次 `model → tool → observe` 往返       | 毫秒~秒级 | 一个 turn 内可以持续跑多个 round；默认不因 round 数、turn 墙钟时间或 token 消耗中断，只有显式配置的运行安全预算才会限制。                                  |
| **Run**     | 围绕**一个具体任务/目标**的完整执行（含多个 turn），对应数据库里的 `AgentRun`                | 分钟~小时 | "评估候选人 X" 这个任务从 queued → running → completed 是一个 run                                    |
| **Session** | 一段连续的人机/agent 上下文边界，对应 `CandidateSession`、`Claude Code session`  | 小时~天  | 一个候选人从初次接触到最终结案是一个 candidate session；用户在 Claude Code 里 `--continue` 恢复同一上下文也是同一 session |


**Autonomous Agent 的层级关系：**

```
Session (CandidateSession)
  └─ Run (AgentRun, 围绕一个 GoalSpec / TaskEnvelope)
       └─ Turn (一次触发后的完整执行壳)
            └─ Round (`AgentKernel.run_round()`)
                 └─ Tool call (单个工具执行)
```

Driver / 调度器视角：外层只关心 **Run** 和 **Turn**；Kernel 只关心 **Round**；Tool call 是 Round 内的具体动作。

## cache_control 深入：标记 ≠ 命令

### 常见误解

`cache_control` 字面看起来像"使用缓存"，但**它不是命令，而是标记**。
准确理解：

> "我承诺这一段（含其前面所有内容）在多次请求里是稳定的，请把它当成可缓存的前缀。"

### 工作原理（前缀缓存）

Anthropic 的缓存是**前缀匹配**的：

```
请求 1：
  system: [A][B][C, cache_control]   user: U1
        └── 缓存到 [A][B][C] 这个前缀点 ──┘

请求 2（5 分钟内）：
  system: [A][B][C, cache_control]   user: U2
        └── 命中缓存（前缀完全一致）─┘
        新内容只有 user: U2 → 按完整价格收费

请求 3：
  system: [A][B][C', cache_control]   user: U3
                ↑ 改了一个字
        前缀不再完全匹配 → 缓存失效，全部按完整价格

请求 4（5 分钟外）：
  system: [A][B][C, cache_control]   user: U4
        └── TTL 过期，缓存失效，全部按完整价格 ─┘
```

### 关键性质

1. **必须从头匹配**：只要中间任何 token 变了，整个缓存就废了
2. **TTL = 5 分钟**（`ephemeral` 类型）：5 分钟内同一前缀的请求才算命中
3. **命中折扣 = 90%**：缓存命中部分按 10% 价格收费
4. **写入有溢价**：第一次打缓存的请求成本比正常贵 25%（但通常很快回本）
5. **打几个 breakpoint 都行，但最多 4 个**：可以打多层"书签"，让不同稳定度的内容用不同缓存

### 把它当成"书签"

```
system: [
  ┌─────────────────────────────┐
  │ Persona + 行为规则           │  ← 永远不变
  │ 工具说明（如有）             │
  └─────────────────────────────┘ ← 书签 1（cache_control）
  ┌─────────────────────────────┐
  │ CLAUDE.md / prompt_config   │  ← session 内不变
  │ MEMORY.md 索引              │
  └─────────────────────────────┘ ← 书签 2（cache_control）
  ┌─────────────────────────────┐
  │ 当前 candidate 的 memory     │  ← run 内不变
  └─────────────────────────────┘ ← 书签 3（cache_control）
]
messages: [
  user: "## 当前 Observation\n候选人池 18 人\n..."   ← 每 turn 变，不打书签
]
```

请求时 Anthropic 从前往后匹配，碰到的最深书签就是命中点。

### 经济学

```
设 system prompt = 20K tokens（持续稳定）
   user / messages = 5K tokens（每次变）
   假设主线每个 round 一次请求，每分钟 2 次

不用缓存（按 input $3/M tokens 估算）：
  每次：25K × $3/M = $0.075
  每天：$0.075 × 60 × 24 = $108

用缓存（5 分钟 TTL，写入溢价 25%，命中折扣 90%）：
  写入次数：每 5 分钟 1 次（第一次请求）
  命中次数：剩余 9 次
  平均成本：(20K×$3/M×1.25 + 9×20K×$3/M×0.1) / 10 + 5K×$3/M
         = (0.075 + 0.054) / 10 + 0.015
         ≈ $0.028
  每天：$0.028 × 60 × 24 ≈ $40

  → 节省约 63%（system prompt 越稳定越长，节省越大）
```

## Autonomous Agent 的缓存策略

按本文 Part 7 的结构组织 system prompt 时，建议分**三层书签**：


| 书签层        | 内容                                | 稳定度                 | 缓存命中率            |
| ---------- | --------------------------------- | ------------------- | ---------------- |
| 书签 1（最稳定）  | Persona + 工具说明 + 行为规则             | 改 prompt 配置才变       | 极高               |
| 书签 2（次稳定）  | `prompt_config` + GlobalMemory 索引 | profile 更新或全局记忆增减时变 | 高                |
| 书签 3（动态稳定） | 当前 candidate / job 的 memory（按需）   | 切到下一个候选人就变          | 中（同一候选人 run 内复用） |
| 不打书签       | 每 turn 的 Observation（DB 查询结果）     | 每 turn 都变           | —                |


**实操检查清单：**

1. 同一个 run 内连续多次 LLM 调用应该命中书签 3
2. 切换候选人时书签 1、2 仍命中，只有书签 3 失效
3. **避免在 system 里塞每 turn 都变的内容**（比如时间戳、当前任务序号）——一塞就把整段缓存打废
4. **避免书签后又插入更稳定的内容**——前缀匹配是从前往后的，新插的"稳定"内容前面有不稳定段会污染缓存
