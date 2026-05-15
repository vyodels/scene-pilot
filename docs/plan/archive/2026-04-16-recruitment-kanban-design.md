# 招聘工作台 · 系统架构与设计全文档

> Status: archived
> Supersedes: -
> Superseded by: current long-term specs under docs/specs/ and archived follow-up plans.
> Distilled into: partial historical extraction; current constraints live under docs/specs/
> Last reviewed against code: 2026-04-20
> Historical source path: docs/superpowers/specs/2026-04-16-recruitment-kanban-design.md

**版本**：v2.0  
**日期**：2026-04-16  
**状态**：待实施  
**作者**：设计评审（人机协作）

---

## 目录

0. [Agent 定位与平台架构](#0-agent-定位与平台架构)
1. [背景与目标](#1-背景与目标)
2. [核心概念澄清](#2-核心概念澄清)
3. [状态机设计](#3-状态机设计)
4. [漏斗里程碑设计](#4-漏斗里程碑设计)
5. [状态机编排能力](#5-状态机编排能力)
6. [候选人状态历史与人工干预](#6-候选人状态历史与人工干预)
7. [页面设计：漏斗转化看板](#7-页面设计漏斗转化看板)
8. [页面设计：工作台看板](#8-页面设计工作台看板)
9. [页面设计：候选人沟通综合面板](#9-页面设计候选人沟通综合面板)
10. [页面设计：候选人详情面板](#10-页面设计候选人详情面板)
11. [页面设计：状态机编辑器](#11-页面设计状态机编辑器)
12. [实施 Plan](#12-实施-plan)

---

## 0. Agent 定位与平台架构

> 本节是整个系统的设计前提。所有后续章节——状态机、看板、API 设计——都服务于这个架构。

### 0.1 一句话定位

**Main Agent 是一个代人操作招聘平台的自主程序员**，具备业务理解能力，利用平台提供的操作框架（状态机 + func tools + Skill 库）自主完成数据抓取、候选人推进、异常处理和自我进化。

### 0.2 两层分工

```
┌─────────────────────────────────────────────────────────────────┐
│                    招聘员（人类）                                 │
│                                                                 │
│  · 配置状态机（哪些节点需要我介入 / 哪些交给 AI）               │
│  · 在人工介入点审批、覆盖 Agent 决策                            │
│  · 查看看板、分析漏斗转化、监控 Agent 行为                      │
│  · 制定策略方向（岗位要求、评分标准、沟通风格）                  │
└────────────────────────┬────────────────────────────────────────┘
                         │ 配置 / 审批 / 监控
┌────────────────────────▼────────────────────────────────────────┐
│                    Platform（本系统）                             │
│                        操作框架层                                │
│                                                                 │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │   状态机配置     │  │  Func Tools  │  │    Skill 库        │ │
│  │                 │  │              │  │                    │ │
│  │ · 合法状态节点  │  │ · 读写候选人 │  │ · 评分 Skill       │ │
│  │ · 转换规则      │  │ · 转换状态   │  │ · 沟通话术 Skill   │ │
│  │ · 执行方式配置  │  │ · 写入消息   │  │ · 筛选规则 Skill   │ │
│  │ · 人工介入点    │  │ · 触发审批   │  │ · Agent 自沉淀     │ │
│  └─────────────────┘  └──────────────┘  └────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              候选人数据库 + 状态历史 + 消息记录            │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │ 调用 func tools / 读配置 / 写结果
┌────────────────────────▼────────────────────────────────────────┐
│                    Main Agent                                    │
│                    自主招聘操作员                                 │
│                                                                 │
│  外部能力                      内部能力                          │
│  ┌──────────────────┐          ┌───────────────────────────┐   │
│  │ browser-mcp      │          │ 业务理解                   │   │
│  │ 其他平台 MCP     │          │ · 理解招聘上下文           │   │
│  │ 搜索 / 邮件 MCP  │          │ · 判断候选人质量           │   │
│  └──────────────────┘          │ · 分析沟通时机             │   │
│                                └───────────────────────────┘   │
│  ┌──────────────────┐          ┌───────────────────────────┐   │
│  │ Platform Tools   │          │ 自主编排                   │   │
│  │ · GET /state-machine        │ · 决定操作顺序             │   │
│  │ · POST /transition │        │ · 处理异常 / 状态回退      │   │
│  │ · POST /message  │          │ · 跨候选人优先级调度       │   │
│  │ · POST /interaction│        └───────────────────────────┘   │
│  └──────────────────┘          ┌───────────────────────────┐   │
│                                │ 自主学习                   │   │
│                                │ · 沉淀有效 Skill           │   │
│                                │ · 更新评估标准             │   │
│                                │ · 改进话术模板             │   │
│                                └───────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 0.3 Agent 的四项自主能力

#### 自主抓取数据

Agent 不等招聘员手动导入候选人，而是主动在招聘平台（BOSS直聘等）上扫描目标候选人，通过 browser-mcp 抓取公开主页信息，写入系统作为 `discovered` 状态的候选人。

触发时机由 Agent 自主判断：
- 当前漏斗候选人数量不足时主动补充
- 招聘员设置了搜索条件后自动循环扫描
- 检测到候选人已回复/更新信息时主动同步

#### 自主推进流程

Agent 持续循环检查候选人队列，对每个非终止态候选人：
1. 读状态机配置 → 知道当前节点的执行方式
2. 若 `ai_auto` → 调用对应 Skill/Prompt 决策，执行转换
3. 若 `human_required` → 创建人工介入请求，挂起等待
4. 若 CANDIDATE 等待 → 检查是否超时，决定是否重试或升级

Agent 不需要招聘员"开始"某个任务，它持续运行，自主推进所有候选人到终止节点。

#### 自主编排异常

状态机定义了"正常路径"，Agent 的业务智能处理"偏离路径"：

```
场景：候选人在沟通中透露已接受其他 Offer
Agent 行为：
  · 不继续走正常流程
  · 调用 POST /candidates/:id/transition，toStatus=candidate_withdrew
  · 附上理由："候选人在消息中明确表示已接受其他 Offer"
  · 写入状态历史，标注 actor=agent，trigger=conversation_signal

场景：AI 线下评分结果低于阈值，但 Agent 发现候选人是内推
Agent 行为：
  · 不直接走 offline_score_rejected
  · 创建 OperatorInteraction（人工介入请求）
  · 附上分析："评分 58/100 低于阈值，但候选人来自内推渠道，建议人工复核"
  · 等待招聘员决策
```

#### 自主学习沉淀

每次成功推进候选人后，Agent 将有效的决策过程提取为 Skill：

```
输入：候选人特征 × 处理过程 × 结果（是否推进到面试/录用）
输出：新的 Skill 条目 或 更新已有 Skill 的 criteriaRef

例：
· 发现"5年以上 Go 经验 + 有大厂背景"的候选人 AI 评分虽然 72 分但面试通过率达 80%
  → 更新 resume_scoring_v1 Skill 的权重，提高该特征组合的通过阈值
· 发现某类消息模板回复率明显更高
  → 将该模板沉淀到 outreach_template Skill
```

### 0.4 平台对 Agent 的约束边界

平台约束的是**操作路径的规范性**，不约束 Agent 的判断和智能：

| 约束项 | 说明 |
|---|---|
| 所有状态变更通过 `POST /transition` 写入 | 保证数据可审计，Agent 不直接改数据库 |
| 状态转换须在状态机合法路径内（或附覆盖理由） | 保证状态历史完整，异常操作有记录 |
| `human_required` 节点不得自动跳过 | 保证人工介入点真实生效 |
| `locked` 节点不得 AI 自行操作 | 高风险操作（如发 Offer）必须人工确认 |

**约束以外，Agent 完全自主**：什么时候抓数据、用什么 Skill 评估、如何措辞、是否主动升级给人工、如何调整策略——这些都由 Agent 自己判断。

### 0.5 现有实现的差距与改造方向

| 能力项 | 现状 | 目标 | 改造优先级 |
|---|---|---|---|
| 状态机 | 隐式（散落在 UI 正则里） | 显式 JSON 配置，Agent 可读 | P0 |
| 状态流转工具 | 存在但无校验 | 校验合法转换 + 结构化历史记录 | P0 |
| Skill 与节点关联 | 无（Skill 靠 Goal 提示词引用） | `criteriaRef` 将节点与 Skill 绑定 | P1 |
| Agent 自主学习写回 | 部分（EvolutionArtifact） | 标准化 Skill 更新路径 | P1 |
| 人工介入与节点映射 | 存在但松散 | `humanActions` 配置驱动按钮渲染 | P1 |
| Agent 自主抓取触发 | 靠招聘员手动创建 Goal | Agent 主动判断抓取时机 | P2 |
| 跨候选人调度优先级 | 无 | Agent 自主排队优先推进高潜力候选人 | P2 |

---

## 1. 背景与目标

### 现状

当前 `WorkbenchView`（candidates tab）是一个基于队列的工作台，候选人按分类（待审查、待跟进、待简历等）归组展示，没有明确的漏斗转化视角，也没有清晰的状态流转链路。

### 目标

新增两个互补的招聘看板视图：

| 视图 | 视角 | 核心问题 |
|---|---|---|
| **漏斗转化看板** | 历史 + 统计 | 在某时间段内，候选人从发现到录用的转化率是多少？ |
| **工作台看板** | 当前快照 | 现在有多少人卡在哪个操作节点上？ |

同时需要：
- **状态机可编排**：状态节点、顺序、转换规则可通过 UI 和代码配置，Agent 可读取并执行流转
- **状态历史可追溯**：每个候选人都有完整的状态流转记录
- **人工可干预**：招聘员可在任意节点手动修改候选人状态，含从淘汰中捞回
- **候选人沟通综合面板**：在两个看板内均可内联打开，聊天窗口 + 候选人简介 + 状态时间线三合一，同一组件两处复用

---

## 2. 核心概念澄清

### 2.1 两层数据结构

```
候选人记录
├── currentStatus: string         // 当前操作状态（工作台看板的维度）
├── deepestMilestone: string      // 曾经到达的最深里程碑（漏斗看板的维度）
├── statusHistory: Transition[]   // 状态流转历史
└── ...其他字段
```

### 2.2 操作状态 vs 里程碑

- **操作状态 (Status)**：候选人当前在哪个操作节点上，等谁做什么。可以来回变动（如从"对话进行中"退回到"等待回复"）。
- **里程碑 (Milestone)**：候选人曾经到达过的最深节点。**单调递增，不随状态回退而回退**。用于漏斗转化分析。

### 2.3 等待方三类

每个操作状态都明确标注"等待方"，决定谁负责推动：

| 标记 | 等待方 | 含义 |
|---|---|---|
| `[AI]` | AI Agent | Agent 自动处理，无需人工介入 |
| `[CANDIDATE]` | 候选人 | 等待对方回复/发送材料 |
| `[HUMAN]` | 招聘员 | 需要人工判断或操作 |

---

## 3. 状态机设计

### 3.1 完整状态图

```
━━━ PHASE A：发现与 AI 在线评估 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [A1] discovered              [AI]
       已发现·待评估
       └─ Agent 在平台扫描到候选人，进入评估队列

  [A2] ai_online_screening     [AI]
       AI 在线评估中
       └─ AI 读取在线简历/主页，生成匹配分与摘要

  [A3] ai_online_passed        [AI → 自动流转 B1]
       AI 在线评估通过
       └─ 过渡状态，短暂停留，自动进入 B1

  [A4] ai_online_rejected      [终止]
       AI 在线评估未通过
       └─ 候选人不符合岗位要求，归档或冷却

  转换规则：
  A1 → A2  自动（Agent 触发评估任务）
  A2 → A3  AI 评分 ≥ 阈值
  A2 → A4  AI 评分 < 阈值
  A3 → B1  自动


━━━ PHASE B：发起沟通与建立对话 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [B1] outreach_pending        [AI]
       待发起沟通
       └─ 评估通过，排队等待 Agent 发出第一条消息

  [B2] outreach_sent           [CANDIDATE]
       已发消息·等候选人回复
       └─ AI 已发出打招呼消息，等候选人响应

  [B2a] no_response            [CANDIDATE / HUMAN]
       无回复·可重试
       └─ 超时未回复（软终止），可由 AI 重试或人工决定归档
          · 可配置重试次数与间隔

  [B3] in_conversation         [AI + CANDIDATE]
       对话进行中
       └─ 候选人已回复，AI 持续沟通推进兴趣

  转换规则：
  B1 → B2  Agent 发送第一条消息后
  B2 → B3  候选人回复
  B2 → B2a 超时无回复（可配置天数）
  B2a → B2 重试（Agent 或人工触发）
  B2a → [归档] 人工决定放弃


━━━ PHASE C：获取线下简历 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [C1] resume_requested        [CANDIDATE]
       沟通中·待获取简历
       └─ AI 已请求简历，等候选人发送 PDF/Word 文件

  [C2] resume_received         [AI → 自动流转 D1]
       已收到简历·待 AI 评分
       └─ 简历文件已入库，自动触发 AI 评分

  转换规则：
  B3 → C1  AI 在对话中请求简历后
  C1 → C2  候选人发送简历文件，Agent 完成入库


━━━ PHASE D：AI 线下简历评分 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [D1] offline_scoring         [AI]
       AI 线下评分中
       └─ AI 解析简历内容，生成结构化评分报告

  [D2] offline_score_passed    [AI → 自动流转 E1]
       AI 线下评分通过

  [D3] offline_score_rejected  [终止]
       AI 线下评分未通过

  转换规则：
  C2 → D1  自动
  D1 → D2  AI 评分 ≥ 阈值
  D1 → D3  AI 评分 < 阈值


━━━ PHASE E：人工初筛 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ⚙ 本阶段行为由 StateNode.executionConfig.mode 控制（见 5.2 节）：
     · mode = "human_required"（默认）→ 必须招聘员手动操作才能推进
     · mode = "ai_auto"          → AI 依据 criteriaRef（Skill/Prompt/Rule）
                                    自动判断并直接流转，跳过人工等待

  [E1] pending_human_review    [defaultWaitingParty: HUMAN]
       待人工初筛
       └─ AI 线下评分通过后进入本节点
          · human_required：候选人进入工作台"⚡ 等待你操作"列表，
            UI 展示 humanActions：[通过] [淘汰] [暂缓]
          · ai_auto：AI 调用 criteriaRef 中的 Skill/Prompt 自动决策，
            直接流转 E2 或 E3，结果记录在状态历史，招聘员可事后覆盖

  [E2] human_review_passed     [AI → 自动流转 F1]
       人工初筛通过

  [E3] human_review_rejected   [终止]
       人工初筛未通过

  转换规则：
  D2  → E1  自动
  E1  → E2  human_required：招聘员点击"通过" / ai_auto：AI 自动执行
  E1  → E3  human_required：招聘员点击"淘汰" / ai_auto：AI 自动执行
  E1  → E1  仅 human_required：招聘员点击"暂缓"（状态不变，强制填备注）


━━━ PHASE F：获取联系方式 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [F1] contact_requested       [CANDIDATE]
       沟通中·待获取联系方式
       └─ 人工通过后，AI 在对话中索取电话/微信

  [F2] contact_acquired        [AI → 自动流转 G1]
       已获取联系方式
       └─ 电话/微信已入库，触发预约面试流程

  转换规则：
  E2 → F1  自动
  F1 → F2  Agent 成功提取联系方式并入库


━━━ PHASE G：面试 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [G1] interview_pending       [HUMAN + AI]
       待预约面试
       └─ 已有联系方式，待协调面试时间
          · AI 可尝试在对话中询问候选人方便时间
          · 最终确认需人工操作

  [G2] interview_scheduled     [CANDIDATE]
       面试已预约
       └─ 时间/形式/地点已确认，等待面试

  [G3] interview_completed     [HUMAN]  ⚡ 人工介入点
       面试已完成·待录入结果
       └─ 面试结束，招聘员录入面试评价

  [G4] interview_passed        [AI → 自动流转 H1 / 或人工决定多轮]
       面试通过
       └─ 若多轮面试，可循环回 G1

  [G5] interview_rejected      [终止]
       面试未通过

  转换规则：
  F2 → G1  自动
  G1 → G2  面试时间确认
  G2 → G3  面试时间到达（或人工标记完成）
  G3 → G4  招聘员录入"通过"
  G3 → G5  招聘员录入"未通过"
  G4 → G1  多轮面试（下一轮）
  G4 → H1  最终轮通过，进入 Offer


━━━ PHASE H：Offer ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [H1] offer_pending           [HUMAN]  ⚡ 人工介入点
       待发 Offer
       └─ 招聘员准备 Offer 内容（薪资/职级/入职日期）

  [H2] offer_sent              [CANDIDATE]
       Offer 已发出·等候选人回复

  [H3] offer_accepted          [成功终止]
       Offer 已接受
       └─ 进入入职流程（超出本系统范围）

  [H4] offer_rejected          [终止]
       Offer 被拒

  转换规则：
  H1 → H2  招聘员确认发出 Offer
  H2 → H3  候选人接受
  H2 → H4  候选人拒绝（可了解原因，决定是否重新谈）


━━━ 全局终止态 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [Z1] archived                任何阶段均可转入
       已归档
       └─ 主动归档，无后续计划

  [Z2] cooldown                任何阶段均可转入
       冷却中
       └─ 平台规则（如 BOSS直聘拒绝后冷却 N 天），到期自动恢复为 discovered

  [Z3] candidate_withdrew      任何阶段均可转入
       候选人主动放弃
       └─ 候选人表明不感兴趣或已接受其他 Offer
```

### 3.2 状态汇总表

| 状态 ID | 状态名 | 阶段 | 等待方 | 是否终止 |
|---|---|---|---|---|
| `discovered` | 已发现·待评估 | A | AI | 否 |
| `ai_online_screening` | AI 在线评估中 | A | AI | 否 |
| `ai_online_passed` | AI 在线评估通过 | A | AI | 否（过渡） |
| `ai_online_rejected` | AI 在线评估未通过 | A | — | 是 |
| `outreach_pending` | 待发起沟通 | B | AI | 否 |
| `outreach_sent` | 已发消息·等回复 | B | CANDIDATE | 否 |
| `no_response` | 无回复·可重试 | B | CANDIDATE/HUMAN | 软终止 |
| `in_conversation` | 对话进行中 | B | AI+CANDIDATE | 否 |
| `resume_requested` | 待获取简历 | C | CANDIDATE | 否 |
| `resume_received` | 已收到简历 | C | AI | 否（过渡） |
| `offline_scoring` | AI 线下评分中 | D | AI | 否 |
| `offline_score_passed` | AI 线下评分通过 | D | AI | 否（过渡） |
| `offline_score_rejected` | AI 线下评分未通过 | D | — | 是 |
| `pending_human_review` | 待人工初筛 | E | HUMAN | 否 |
| `human_review_passed` | 人工初筛通过 | E | AI | 否（过渡） |
| `human_review_rejected` | 人工初筛未通过 | E | — | 是 |
| `contact_requested` | 待获取联系方式 | F | CANDIDATE | 否 |
| `contact_acquired` | 已获取联系方式 | F | AI | 否（过渡） |
| `interview_pending` | 待预约面试 | G | HUMAN+AI | 否 |
| `interview_scheduled` | 面试已预约 | G | CANDIDATE | 否 |
| `interview_completed` | 面试完成·待录入 | G | HUMAN | 否 |
| `interview_passed` | 面试通过 | G | AI/HUMAN | 否 |
| `interview_rejected` | 面试未通过 | G | — | 是 |
| `offer_pending` | 待发 Offer | H | HUMAN | 否 |
| `offer_sent` | Offer 已发出 | H | CANDIDATE | 否 |
| `offer_accepted` | Offer 已接受 | H | — | 成功终止 |
| `offer_rejected` | Offer 被拒 | H | — | 是 |
| `archived` | 已归档 | Z | — | 是 |
| `cooldown` | 冷却中 | Z | — | 软终止 |
| `candidate_withdrew` | 候选人主动放弃 | Z | — | 是 |

---

## 4. 漏斗里程碑设计

### 4.1 里程碑定义

里程碑代表候选人**曾经到达过的最深程度**，单调递增，不随操作状态回退。
每个里程碑对应"首次进入某状态"时自动打标。

```
里程碑 ID              名称                    触发条件（首次进入）
─────────────────────────────────────────────────────────────────
M01  discovered         已发现                 status = discovered
M02  ai_evaluated       AI 在线评估完成         status = ai_online_passed OR ai_online_rejected
M03  ai_screen_passed   AI 在线评估通过         status = ai_online_passed
M04  outreach_started   已发起沟通              status = outreach_sent
M05  conversation_built 已建立对话              status = in_conversation
M06  resume_obtained    已获取线下简历           status = resume_received
M07  offline_scored     AI 线下评分完成         status = offline_score_passed OR offline_score_rejected
M08  offline_passed     AI 线下评分通过         status = offline_score_passed
M09  human_screened     人工初筛完成            status = human_review_passed OR human_review_rejected
M10  human_passed       人工初筛通过            status = human_review_passed
M11  contact_obtained   已获取联系方式           status = contact_acquired
M12  interview_booked   面试已预约              status = interview_scheduled
M13  interview_passed   面试通过               status = interview_passed
M14  offer_accepted     Offer 已接受            status = offer_accepted
```

### 4.2 漏斗看板展示的阶段集合

漏斗看板展示"通过型"里程碑（不展示淘汰里程碑，淘汰数字以注释形式在对应节点旁展示）：

```
已发现 ──› AI评估通过 ──› 已建立对话 ──› 已获简历 ──› AI线下评分通过
 M01         M03            M05           M06             M08

──› 人工初筛通过 ──› 已获联系方式 ──› 面试已预约 ──› 面试通过 ──› Offer接受
      M10             M11             M12           M13          M14
```

转化率 = 当前里程碑人数 / 上一里程碑人数（在所选时间窗内首次到达该里程碑的人）

### 4.3 淘汰注释展示方式

```
AI评估通过                     AI线下评分通过
 860人                           240人
  (-380 评估未通过)               (-72 评分未通过)
```

---

## 5. 状态机编排能力

### 5.1 设计目标

状态机不硬编码在业务逻辑中，而是以**声明式配置**存储，满足：
- UI 可视化编辑（节点增删、顺序调整、转换规则修改）
- Agent 可读取配置，判断合法转换并执行
- **每个可配置节点均可独立设置执行方式**：AI 自动（提供评估标准/Skill）或人工介入（招聘员确认后推进）
- 版本化管理（每次编辑留历史，可回滚）

### 5.2 节点执行方式：`executionConfig`

#### 适用范围

从 **AI 在线评估完成（A2）之后**，所有 `waitingParty` 为 `"AI"` 或 `"HUMAN"` 的非过渡节点，均支持 `executionConfig`。

`waitingParty = "CANDIDATE"` 的节点（等候选人回复/发材料）不适用——这类节点的推进取决于候选人行为，不受此配置控制。

| 节点 | 默认 mode | 可切换 |
|---|---|---|
| B1 `outreach_pending` | `ai_auto` | ✓ 可切为 human_required（招聘员审批首条消息后发出） |
| B3 `in_conversation` | `ai_auto` | ✓ 可切为 human_required（每条 AI 回复须人工确认） |
| D1 `offline_scoring` | `ai_auto` | ✓ 可切为 human_required（人工审阅评分后才能推进） |
| E1 `pending_human_review` | `human_required` | ✓ 可切为 ai_auto（AI 根据标准直接判断通过/淘汰） |
| G1 `interview_pending` | `human_required` | ✓ 可切为 ai_auto（AI 负责协调面试时间） |
| G3 `interview_completed` | `human_required` | ✓ 可切为 ai_auto（AI 根据面试记录自动判断结果） |
| H1 `offer_pending` | `human_required` | ✗ 固定人工（发 Offer 涉及薪资承诺，不允许 AI 独立操作） |

#### 数据结构

```typescript
// packages/shared/src/types/stateMachine.ts

export interface StateNode {
  id: string;                  // 唯一标识，如 "pending_human_review"
  label: string;               // 显示名称，如 "待人工初筛"
  phase: string;               // 所属阶段，如 "E"
  phaseLabel: string;          // 阶段名称，如 "人工初筛"
  defaultWaitingParty: "AI" | "CANDIDATE" | "HUMAN" | "AUTO";
  // 节点的原始设计等待方，供理解语义用；
  // 实际执行方式由 executionConfig.mode 决定
  isTerminal: boolean;
  isSuccess: boolean;
  isSoftTerminal: boolean;
  isTransient: boolean;        // 过渡态：不展示在看板，不支持 executionConfig
  milestoneId?: string;
  sortOrder: number;
  description?: string;        // 状态说明（供 Agent 理解当前节点的业务含义）

  /**
   * 节点执行方式配置
   * 适用于 defaultWaitingParty 为 AI 或 HUMAN、且非过渡态的节点
   * 在状态机编辑器 UI 中配置；Agent 每次到达该节点前读取此字段
   */
  executionConfig?: {
    mode: "ai_auto" | "human_required";

    /**
     * mode = "ai_auto" 时：AI 使用什么标准来决策
     * 可引用已有 Skill、内联 Prompt，或简单规则表达式
     */
    criteriaRef?: {
      type: "skill" | "prompt" | "rule";
      skillId?: string;         // type=skill：引用已定义的 Skill ID（如简历评分 Skill）
      promptText?: string;      // type=prompt：内联决策 Prompt（自然语言，支持占位符）
      ruleExpression?: string;  // type=rule：简单规则（如 "score >= 70 AND years >= 3"）
      passThreshold?: number;   // 评分类 Skill 的通过阈值
    };

    /**
     * mode = "human_required" 时：看板 UI 展示的操作按钮
     * 每个 action 对应一个状态转换
     * 若为空，则使用该节点所有合法 transitions 的 label 自动生成按钮
     */
    humanActions?: Array<{
      label: string;             // 按钮文字，如"通过"、"淘汰"、"暂缓"
      toStatus: string;          // 点击后目标状态 ID
      style: "primary" | "default" | "danger";
      requiresNote?: boolean;    // 是否强制填写备注才能提交
    }>;

    /**
     * 固定不可配置的节点（如 H1 offer_pending）
     * locked=true 时编辑器中显示为只读，不允许切换 mode
     */
    locked?: boolean;
  };

  uiConfig?: {
    color?: "default" | "warning" | "success" | "danger" | "info";
    showInKanban?: boolean;
    showInFunnel?: boolean;
  };
}

export interface StateTransition {
  id: string;
  fromState: string;           // 源状态 ID（"*" 表示任意状态）
  toState: string;             // 目标状态 ID
  trigger: "auto" | "agent" | "human" | "system";
  condition?: string;          // 条件描述（自然语言，供 Agent 理解）
  requiresNote?: boolean;
  label?: string;              // 转换动作名称，如 "标记通过"
  allowedActors?: Array<"agent" | "recruiter" | "system">;
}

export interface RecruitmentStateMachine {
  version: number;
  updatedAt: string;
  updatedBy: string;
  nodes: StateNode[];
  transitions: StateTransition[];
  globalTransitions: StateTransition[];
}
```

#### 默认配置示例（seed 文件片段）

```json
{
  "id": "pending_human_review",
  "label": "待人工初筛",
  "phase": "E",
  "defaultWaitingParty": "HUMAN",
  "executionConfig": {
    "mode": "human_required",
    "humanActions": [
      { "label": "通过",  "toStatus": "human_review_passed",   "style": "primary"  },
      { "label": "淘汰",  "toStatus": "human_review_rejected",  "style": "danger"   },
      { "label": "暂缓",  "toStatus": "pending_human_review",   "style": "default", "requiresNote": true }
    ]
  }
},
{
  "id": "offline_scoring",
  "label": "AI 线下评分中",
  "phase": "D",
  "defaultWaitingParty": "AI",
  "executionConfig": {
    "mode": "ai_auto",
    "criteriaRef": {
      "type": "skill",
      "skillId": "resume_scoring_v1",
      "passThreshold": 70
    },
    "humanActions": [
      { "label": "确认评分通过", "toStatus": "offline_score_passed",   "style": "primary" },
      { "label": "标记未通过",   "toStatus": "offline_score_rejected",  "style": "danger"  }
    ]
  }
}
```

> `humanActions` 在 ai_auto 节点上同样需要填写，以备招聘员将该节点切换为 human_required 时直接复用，无需再手动配置按钮。

### 5.3 Agent 执行流程

```
Agent 到达某节点时的执行路径：

1. 读取当前 StateMachine 配置（版本号检查，变更时重新加载）
2. 获取候选人 currentStatus → 找到对应 StateNode
3. 若 node.isTransient → 直接执行 auto 转换，跳到步骤 7
4. 若 node 无 executionConfig（CANDIDATE 等待节点）→ 停止，等候选人行为
5. 读取 node.executionConfig.mode：
   ├─ "ai_auto"
   │   ├─ 读取 criteriaRef，调用对应 Skill / Prompt / Rule
   │   ├─ 根据结果选择目标转换（通过 / 未通过）
   │   └─ 执行流转 → 步骤 7
   └─ "human_required"
       ├─ 候选人进入工作台"等待你操作"列表（⚡ 标记）
       ├─ UI 展示 humanActions 按钮
       ├─ 等待招聘员点击按钮 → 系统调用 POST /candidates/:id/transition
       └─ 执行流转 → 步骤 7
6. 任何 executionConfig.locked=true 的节点：
   若 mode=human_required → Agent 不得自动执行，无论如何等待人工
7. 执行状态变更：
   · 写入 CandidateStatusTransition（含 actor、criteriaRef 快照、决策依据摘要）
   · 若目标状态有 milestoneId → 更新 deepestMilestone（只增不减）
```

### 5.4 人工介入节点的 UI 规则

当 `executionConfig.mode === "human_required"` 时，无论该节点的 `defaultWaitingParty` 是 AI 还是 HUMAN，UI 表现完全一致：

```
候选人表格行：
  状态列  → [当前状态 Tag]  ⚡ 等待你操作
  操作列  → humanActions 中的按钮，按 style 渲染：
            · primary → Primary 按钮（--brand-primary 底）
            · default → Default 按钮（1px border）
            · danger  → Danger 按钮（--danger 文字/边框）
            所有按钮后接 [详情] Text 按钮

沟通综合面板右列（快捷操作区）：
  同样渲染 humanActions 按钮，点击效果相同

提交后：
  · requiresNote=true 的 action → 点击先弹出备注输入浮层，填写后提交
  · requiresNote=false → 直接提交，无确认弹窗（操作轻量）
  · 提交成功 → Toast 提示，候选人行自动刷新状态，⚡ 消失
```

### 5.5 人工覆盖（Override）规则

```
招聘员可在任意节点执行任意转换（超出 humanActions 的范围），但须满足：
· 必须填写 overrideReason（强制）
· statusHistory 中标记 actor = "recruiter_override"
· 里程碑只增不减：目标状态里程碑 sortOrder 若高于当前，则补打中间里程碑

典型场景：
· 从 offline_score_rejected 捞回 → 直接设为 interview_pending
  里程碑前跳至 M12，跳过的中间里程碑一并补打
```

---

## 6. 候选人状态历史与人工干预

### 6.1 状态流转记录（`CandidateStatusTransition`）

```typescript
export interface CandidateStatusTransition {
  id: string;
  candidateId: string;
  fromStatus: string;                // 转换前状态 ID
  toStatus: string;                  // 转换后状态 ID
  fromStatusLabel: string;           // 转换前状态名（快照，防止状态机改名后丢失）
  toStatusLabel: string;
  actor: "agent" | "system" | "recruiter" | "recruiter_override";
  actorId?: string;                  // 操作者 ID（recruiter 时使用）
  trigger: string;                   // 触发原因/事件名
  note?: string;                     // 备注（人工操作时必填）
  overrideReason?: string;           // 仅 recruiter_override 时填写
  isOverride: boolean;
  milestoneUpdated?: string;         // 若同时更新了里程碑，记录新里程碑 ID
  metadata?: Record<string, unknown>;// 扩展信息（AI 评分值、面试轮次等）
  createdAt: string;                 // ISO 时间戳
}
```

### 6.2 历史面板交互设计（文字草图）

```
/* 候选人详情面板右侧：状态历史 Tab */

┌─ 状态历史 ────────────────────────────────────────────┐
│                                                        │
│  2026-04-16 14:32  面试已预约              [招聘员覆盖] │
│  └─ 备注：候选人线下沟通后直接确认，跳过线下评分环节   │
│     覆盖理由：HR 总监推荐，直接安排面试               │
│                                                        │
│  ─────────────────────────────────────────────────── │
│  2026-04-15 09:10  AI 线下评分未通过       [Agent]    │
│  └─ AI 评分 42/100，低于阈值 60，自动流转至淘汰状态   │
│                                                        │
│  ─────────────────────────────────────────────────── │
│  2026-04-14 18:05  已收到线下简历          [Agent]    │
│                                                        │
│  ─────────────────────────────────────────────────── │
│  2026-04-13 11:22  对话进行中              [Agent]    │
│                                                        │
│  ─────────────────────────────────────────────────── │
│  ... 展开更多                                          │
│                                                        │
│  [人工修改状态]                                        │
└────────────────────────────────────────────────────────┘
```

### 6.3 人工修改状态 · 操作面板（Drawer）

```
┌─ 手动调整状态 ────────────────────────── 560px Drawer ──┐
│                                                          │
│  候选人：张三  当前状态：AI 线下评分未通过               │
│                                                          │
│  目标状态                                                │
│  ┌─────────────────────────────────────────────────┐   │
│  │  选择目标状态  ▾                                  │   │
│  │  ─ 主流程状态 ─────────────────────────          │   │
│  │  · 待预约面试                                     │   │
│  │  · 面试已预约                                     │   │
│  │  · 待人工初筛                                     │   │
│  │  · 对话进行中                                     │   │
│  │  ─ 终止态 ─────────────────────────              │   │
│  │  · 已归档                                        │   │
│  │  · 冷却中                                        │   │
│  └─────────────────────────────────────────────────┘   │
│                                                          │
│  覆盖理由  *必填                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  例：候选人通过其他渠道验证，决定跳过线下评分…   │   │
│  │                                                   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                          │
│  ⚠ 此操作将：                                           │
│  · 跳过中间状态 D→E→F，直接设为"待预约面试"            │
│  · 里程碑同步更新至 M12（面试已预约）                   │
│  · 操作将被记录在状态历史中，标注为【招聘员覆盖】       │
│                                                          │
│                        [取消]  [确认修改]                │
└──────────────────────────────────────────────────────────┘
```

---

## 7. 页面设计：漏斗转化看板

**骨架**：`DashboardPage` 变体 · 套用 `AppLayout`（SideNav + TopNav）  
**进入路径**：候选人 Tab → 页内 SectionTabs → 漏斗看板  
**沟通面板**：两个看板页面均支持内联展开候选人沟通综合面板（见第 9 节），复用同一个 `CandidateCommunicationPanel` 组件

### 7.1 整体布局草图

```
┌─ TopNav 56px · 白底 · 下 1px border ──────────────────────────────────┐
│ 左：候选人    漏斗看板 ════  状态看板              右：刷新○  头像      │
│              ——————（2px主色下划线）                                    │
└────────────────────────────────────────────────────────────────────────┘
│
│  /* ── 筛选行 ── 内联文字，无卡片，高约 40px，上下 padding 各 10px */
│
│  岗位  [全部 ▾]    时间段  [近 7 天]  [近 30 天]  [近 90 天]  [自定义 ▾]
│  ────────────────────────────────────────────────────────────────────────
│  /* 分割线 1px --border-line */
│
│  /* ── 漏斗阶段条 ── 水平排列，两行自动换行，纯文字节点，无卡片 */
│  /* 选中节点：文字 --text-primary 加重，底部 2px --brand-primary 线 */
│  /* 未选中：--text-secondary */
│
│  ← 第一行 →
│
│  已发现          AI评估通过        已建立对话        已获简历
│  1,240           860               540               312
│                  (-380未通过)       (-320无回复)
│    │                │                │                │
│    └────────────────┴────────────────┴────────────────┘
│    箭头用 › 字符或细线，--text-placeholder 颜色
│
│  ← 第二行（续） →
│
│  AI线下评分通过   人工初筛通过      已获联系方式      面试已预约     面试通过    Offer接受
│  240              180               140               89             52          24
│  (-72未通过)       (-60未通过)
│
│  ────────────────────────────────────────────────────────────────────────
│  /* 分割线 */
│
│  /* ── 候选人列表区 ── 点击阶段节点后展示该阶段的候选人 */
│
│  AI评估通过阶段  ·  860 人          [导出]
│
│  /* 表格：表头 #FAFBFC，行高 48px，行 hover --bg-hover，无竖线 */
│  /* "打开沟通"对所有候选人可见（含尚未沟通的），点击后内联展开综合面板（见第 9 节）*/
│  姓名 ↕   当前职位        应聘岗位    在线简历  线下简历  联系方式          当前状态         操作
│  ────────────────────────────────────────────────────────────────────────────────────────────
│  张三     高级后端工程师  后端工程师  查看      查看      138xxxx xxxx      沟通中·待简历    详情 | 打开沟通
│  李四     产品经理        产品经理    查看      —         —                 待发起沟通       详情 | 打开沟通
│  王五     前端工程师      全栈工程师  查看      查看      微信: wxid_xxx    已预约面试       详情 | 打开沟通
│  ...
│
│  /* 空态：居中说明文字 + 无插画（保持极简） */
│  当前筛选条件下该阶段没有候选人
│
│  [加载更多]  或分页  第 1/12 页  [‹] [1] [2] ... [›]
```

### 7.2 筛选行样式细节

```css
/* 筛选行整体 */
display: flex;
align-items: center;
gap: var(--space-4);
padding: var(--space-2) 0 var(--space-3);
font-size: 14px;          /* --font-size-base */
color: var(--text-regular);

/* 筛选标签（如"岗位"） */
color: var(--text-secondary);
font-size: 13px;          /* --font-size-sm */

/* 时间段按钮（非选中） */
background: transparent;
border: none;
color: var(--text-secondary);
padding: var(--space-1) var(--space-2);
border-radius: var(--radius-xs);
cursor: pointer;

/* 时间段按钮（选中） */
color: var(--brand-primary);
background: var(--brand-primary-soft);
```

### 7.3 漏斗节点样式细节

```css
/* 节点容器 */
display: inline-flex;
flex-direction: column;
gap: 2px;
padding-bottom: var(--space-2);
border-bottom: 2px solid transparent;  /* 未选中 */
cursor: pointer;

/* 节点（选中态） */
border-bottom-color: var(--brand-primary);

/* 节点名称文字 */
font-size: 13px;           /* --font-size-sm */
font-weight: 400;
color: var(--text-secondary);   /* 未选中 */
/* 选中 */
color: var(--text-primary);
font-weight: 500;

/* 节点数字 */
font-size: 18px;
font-weight: 600;
color: var(--text-primary);
line-height: 1.3;

/* 淘汰注释（如 -380未通过） */
font-size: 12px;
color: var(--text-placeholder);

/* 节点间箭头 › */
color: var(--border-line);
font-size: 12px;
align-self: flex-start;
margin-top: 22px;          /* 与数字行对齐 */
```

---

## 8. 页面设计：工作台看板

**骨架**：自定义状态链 + 列表分区  
**进入路径**：候选人 Tab → 页内 SectionTabs → 状态看板  
**沟通面板**：同漏斗看板，表格行均有"打开沟通"，触发同一个 `CandidateCommunicationPanel` 内联展开

### 8.1 整体布局草图

```
┌─ TopNav 56px ──────────────────────────────────────────────────────────┐
│ 左：候选人    漏斗看板    状态看板 ════              右：刷新○  头像     │
│                           ——————（2px主色下划线）                       │
└────────────────────────────────────────────────────────────────────────┘
│
│  /* ── 筛选行 ── 内联文字，无卡片 */
│
│  显示  [全部 ✓]  [只看未淘汰]  [只看等待人工]      岗位  [全部 ▾]
│  ────────────────────────────────────────────────────────────────────────
│
│  /* ── 状态链 ── 两行自动换行，纯文字节点，节点间用 › 连接 */
│  /* 主流程节点：--text-primary；淘汰/旁路：--text-secondary 降调 */
│  /* 选中节点：底部 2px --brand-primary 线 */
│
│  ← 第一行（发现 → 评估 → 沟通） →
│
│  全部         已发现        AI评估中      AI评估通过    已发消息     对话进行中
│  1,240   ›   340    ›    89     ›     280    ›    156   ›    244
│  [选中]
│                              ↓（旁路，向下错落）
│                           AI评估未通过    无回复·可重试
│                              380               28
│                           [--danger 色]    [--warning 色]
│
│  /* 换行 · 第二行（简历 → 评分 → 人工） */
│  /* 行首用一个小箭头或缩进表示承接关系 */
│
│     待获取简历    已收到简历    AI线下评分中    AI线下评分通过    待人工初筛
│  ›     68     ›     12      ›      9       ›       28         ›     15
│
│                                                  ↓（旁路）
│                                             AI线下评分未通过    人工初筛未通过
│                                                   72                  60
│
│  /* 换行 · 第三行（联系 → 面试 → Offer） */
│
│     待获取联系    已获联系方式    待预约面试    面试已预约    面试完成·待录入    面试通过    Offer接受
│  ›     18      ›      12      ›     11      ›     7       ›       3         ›     5    ›    2
│
│                                                              ↓（旁路）
│                                                          面试未通过    Offer被拒
│                                                              52           4
│
│  /* ── 全局淘汰汇总行 ── 始终可见，折叠式 */
│
│  已归档  34人 · 冷却中  12人 · 候选人主动放弃  8人      [展开明细 ▾]
│  ────────────────────────────────────────────────────────────────────────
│
│  /* ── 候选人列表区 ── 点击节点后展示 */
│
│  全部候选人  ·  1,240 人          [导出]  [批量操作 ▾]
│
│  /* 同漏斗看板表格，增加"人工操作"列（等待人工的节点高亮这一列） */
│  姓名     当前职位       应聘岗位   在线简历  线下简历  联系方式      当前状态       操作
│  ─────────────────────────────────────────────────────────────────────────────────────
│  张三     高级后端工程师  后端岗    查看      查看      138xxxx      待人工初筛      初筛 | 详情
│                                                                    [⚡ 等待你操作]
│  李四     产品经理        产品岗    查看      —         —            已发消息·等回复  详情
│  ...
│
│  [加载更多]
```

### 8.2 状态节点样式细节

```css
/* 状态链行容器 */
display: flex;
align-items: flex-start;
flex-wrap: wrap;
gap: var(--space-3);
padding: var(--space-4) 0;

/* 单个节点 wrapper（含节点 + 可能的旁路） */
display: flex;
flex-direction: column;
gap: var(--space-2);

/* 节点本体 */
display: inline-flex;
flex-direction: column;
gap: 2px;
padding-bottom: var(--space-2);
border-bottom: 2px solid transparent;
cursor: pointer;

/* 节点标签 */
font-size: 13px;
color: var(--text-secondary);
white-space: nowrap;
/* 选中 */
color: var(--text-primary);
font-weight: 500;
border-bottom-color: var(--brand-primary);

/* 节点数字 */
font-size: 20px;
font-weight: 600;
color: var(--text-primary);

/* 等待人工的节点数字色 */
color: var(--warning);  /* 醒目提示有人工待办 */

/* 旁路节点（淘汰） */
font-size: 12px;
color: var(--text-placeholder);
/* 含 [终止] 的旁路名 */
color: var(--danger);

/* 换行第二行的起始缩进（视觉上承接上一行末尾） */
padding-left: var(--space-6);  /* 或者加一个 › 前缀 */
```

### 8.3 表格中"等待人工"高亮规则

判断依据：`node.executionConfig.mode === "human_required"`（而非硬编码 waitingParty）。任何节点，无论其 `defaultWaitingParty` 是 AI 还是 HUMAN，只要当前配置为 human_required，候选人行都进入"等你操作"状态。

```
executionConfig.mode === "human_required" 的候选人行：
  状态列  → [当前状态 Tag]  ⚡（--warning 色，表示需要人工介入）
  操作列  → 渲染 executionConfig.humanActions 中定义的按钮
            · style=primary  → Primary 按钮
            · style=default  → Default 按钮
            · style=danger   → Danger 样式
            + [详情] Text 按钮（始终显示）

示例（human_required 节点）：
  pending_human_review  → [通过]主   [淘汰]危   [暂缓]默   [详情]
  offline_scoring（切换为human后）
                        → [确认评分通过]主   [标记未通过]危   [详情]
  interview_completed   → [录入面试结果]主   [详情]
  interview_pending     → [确认面试时间]主   [详情]

executionConfig.mode === "ai_auto" 的候选人行：
  状态列  → [当前状态 Tag]（无 ⚡）
  操作列  → 仅显示 [详情] Text 按钮，AI 自动处理无需人工操作

requiresNote=true 的 action 点击后：
  弹出单行文本输入浮层（Popover，非 Modal）→ 填写后确认提交
```

---

## 9. 页面设计：候选人沟通综合面板

### 9.1 概述

**组件名**：`CandidateCommunicationPanel`  
**复用范围**：漏斗看板 + 工作台看板，两处使用同一个组件，Props 相同  
**触发方式**：点击任意候选人行的"打开沟通"按钮  
**展开形态**：内联展开，不弹 Drawer，页面内容区从全宽表格变为三列布局  
**动效**：`grid-template-columns` 过渡，150ms ease-out

### 9.2 布局变化：默认状态 → 展开状态

```
/* 默认：全宽表格 */
筛选行
漏斗条 / 状态链
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
候选人列表（全宽表格）
  张三  ...  [打开沟通]
  李四  ...  [打开沟通]

/* 点击"打开沟通"后：三列内联展开 */
筛选行                            ← 保持不动
漏斗条 / 状态链                   ← 保持不动
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│ 精简候选人列表  │  聊天窗口（弹性宽）  │  候选人简介 + 时间线  │
│     280px      │      flex-1         │       320px           │
```

### 9.3 三列结构草图

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│                    │                                  │               │
│  /* 左列 280px */  │  /* 中列 flex-1 */               │  /* 右列 320px*/
│                    │                                  │               │
│  [🔍 搜索候选人]   │  ── 平台工具条 ──────────────    │  张三          │
│                    │  BOSS直聘  最后同步3分钟前  [↺]  │  高级后端工程师│
│  /* 精简列表项     │  ─────────────────────────────── │  北京 · 在职   │
│     h:64px        │                                  │               │
│     头像+姓名      │  /* 消息流（有沟通记录时）*/      │  应聘：后端岗  │
│     +状态Tag */    │                                  │               │
│                    │     ╌╌╌ 2026-04-13 ╌╌╌           │  ── AI 评分 ──│
│  ┌──────────────┐  │     /* 居中灰色胶囊 */            │  在线  86/100  │
│  │● 张三 (选中)  │  │                                  │  ████████░░   │
│  │ 对话进行中 ⚡ │  │  [头像] 张三                     │  线下  待评分  │
│  └──────────────┘  │  ╔──────────────────────────╗   │               │
│  /* 选中态：       │  │ 您好，想了解下贵司后端岗  │   │  ── 标签 ──   │
│   --brand-primary  │  │ 位的技术要求              │09:22│  [Go][微服务] │
│   -soft bg,        │  ╚──────────────────────────╝   │  [5年][在职]  │
│   左3px主色竖条 */ │                  [Agent 头像]     │               │
│                    │  ╔────────────────────────────╗ │  ── 联系方式 ──│
│  ┌──────────────┐  │  │ 您好张三，您的 Go 微服务   │ │  电话 138xxxx  │
│  │○ 李四         │  │  │ 背景非常符合，来介绍下...  │09:25│  微信  待获取  │
│  │ 待发起沟通   │  │  ╚────────────────────────────╝ │               │
│  └──────────────┘  │  /* 右对齐·主色底·白字·--radius-lg */│  ── 快捷操作 ──│
│                    │  /* 右下角"Agent发送" 12px */      │  [初筛通过]    │
│  ┌──────────────┐  │                                  │  [人工修改…]   │
│  │○ 王五         │  │  /* 无沟通记录时（空态）*/        │               │
│  │ 待预约面试 ⚡ │  │  /* ─────────────────────── */   │  ─────────── │
│  └──────────────┘  │  /*                             */│               │
│                    │  /*     候选人简介卡              */│  /* 状态时间线 */
│  ┌──────────────┐  │  /*  （见 9.4 空态设计）          */│               │
│  │○ 赵六         │  │                                  │  ● 对话进行中  │
│  │ AI评估中     │  │                                  │  │ 04-14 Agent│
│  └──────────────┘  │                                  │  │            │
│                    │                                  │  ● 已发消息   │
│  ...（滚动）       │  ──────────────────────────────  │  │ 04-13 Agent│
│                    │  /* 输入区 min-height:160px */    │  │            │
│  ──────────────    │                                  │  ★ M03里程碑  │
│  [关闭面板 ×]      │  📎附件  🔁模板                   │  AI评估通过   │
│                    │  ─  ─  ─  ─  ─  ─  ─  ─  ─  ─   │  04-12       │
│                    │  输入消息（Agent 代你在平台发送）  │              │
│                    │  ⚠ 发出后不可撤回                 │  ● AI评估中   │
│                    │                   [Enter 发送]    │  │ 04-12 AI  │
│                    │  /* 聚焦时输入区顶边→主色线 */     │              │
│                    │                                  │  ● 已发现     │
│                    │                                  │  04-12 Agent  │
│                    │                                  │               │
│                    │                                  │  [查看完整历史]│
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 9.4 空态：尚未沟通的候选人

当候选人处于 A 阶段（发现/评估中）或 B1（待发起沟通），尚无任何聊天记录时，聊天区中列展示"候选人核心信息卡"代替消息流：

```
│  /* 中列：无聊天记录时 */                                │
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │                                                   │   │
│  │  张三  ·  高级后端工程师  ·  北京                │   │
│  │                                                   │   │
│  │  在线简历摘要（AI 生成）                          │   │
│  │  拥有 5 年 Go 微服务开发经验，主导过多个高并发    │   │
│  │  系统架构，熟悉 K8s 和分布式存储。               │   │
│  │                                                   │   │
│  │  AI 在线评分  86/100  ·  强匹配                  │   │
│  │  ████████░░  主要优势：技术栈吻合度高，履历稳定  │   │
│  │                                                   │   │
│  │  当前所在公司：xx科技（在职）                    │   │
│  │  期望薪资：面谈                                   │   │
│  │  工作年限：5年                                    │   │
│  │  所在地：北京                                    │   │
│  │                                                   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                          │
│  当前状态：AI 在线评估通过·待发起沟通                   │
│                                                          │
│  ──────────────────────────────────────────────────── │
│  /* 输入区（AI 代发第一条消息）*/                        │
│                                                          │
│  📋 模板  🔁 建议话术                                   │
│  ─  ─  ─  ─  ─  ─  ─  ─  ─  ─  ─  ─  ─  ─  ─  ─      │
│  输入打招呼消息...                                       │
│  Agent 将在 BOSS直聘 上以你的身份发出第一条消息          │
│                                  [发送并开始沟通]        │
```

### 9.5 样式规范

```css
/* 三列容器 */
display: grid;
grid-template-columns: 280px 1fr 320px;
transition: grid-template-columns 150ms ease-out;
border-top: 1px solid var(--border-line);

/* 列间分割 */
border-right: 1px solid var(--border-line);

/* 左列精简列表项 h:64px */
display: flex;
align-items: center;
gap: var(--space-3);
padding: var(--space-3) var(--space-4);
border-bottom: 1px solid var(--border-line);
cursor: pointer;

/* 选中态 */
background: var(--brand-primary-soft);
border-left: 3px solid var(--brand-primary);

/* ⚡ 等待人工图标 */
color: var(--warning);
font-size: 12px;

/* 中列聊天气泡 - 候选人（inbound） */
max-width: 60%;
justify-self: start;
background: var(--bg-card);
border: 1px solid var(--border-line);
border-radius: var(--radius-lg);
padding: var(--space-3);

/* 中列聊天气泡 - Agent（outbound） */
max-width: 60%;
justify-self: end;
background: var(--brand-primary);
color: var(--text-inverse);
border-radius: var(--radius-lg);
padding: var(--space-3);
/* Agent 角标 */
font-size: 12px;
opacity: 0.7;  /* "Agent 发送" 标注 */

/* 日期胶囊（居中） */
justify-self: center;
background: var(--bg-page);
color: var(--text-placeholder);
border-radius: var(--radius-full);
font-size: 12px;
padding: 2px var(--space-3);

/* 气泡间距 */
同发送方相邻：gap: var(--space-1);
切换发送方：  gap: var(--space-4);

/* 中列输入区 */
min-height: 160px;
border-top: 1px solid var(--border-line);
/* 聚焦时 */
border-top-color: var(--border-focus);
border-top-width: 2px;

/* 右列 */
overflow-y: auto;
padding: var(--space-4);
display: flex;
flex-direction: column;
gap: var(--space-4);

/* 右列时间线竖线 */
border-left: 2px solid var(--border-line);
padding-left: var(--space-4);

/* 时间线圆点 */
普通节点：  8px  background: var(--border-line)  → 当前节点用 --brand-primary
里程碑节点：8px  background: var(--success)        ★ 角标
人工覆盖：  8px  background: var(--warning)        ⚡ 角标

/* 覆盖节点展示块 */
background: color-mix(in srgb, var(--warning) 10%, white);
border-left: 3px solid var(--warning);
border-radius: var(--radius-sm);
padding: var(--space-3);
font-size: 13px;
```

### 9.6 与 CommunicationsView（候选人舱）的关系

| 场景 | 使用哪个 |
|---|---|
| 快速查看单个候选人的聊天 + 简介 + 时间线，不离开看板 | `CandidateCommunicationPanel`（本节） |
| 同时管理多个候选人、跨候选人切换、完整操作历史 | `CommunicationsView`（候选人舱 Tab） |

两者桥接：面板右列底部提供"在候选人舱中完整打开 ↗"入口，点击跳转至 CommunicationsView 并预选当前候选人。

---

## 10. 页面设计：候选人详情面板

点击表格行中的"详情"后，在页面右侧弹出 Drawer（宽 560px），包含：

> 注：状态历史的完整时间线设计见第 9 节"候选人沟通综合面板"右列，详情面板的"状态历史 Tab"复用同一个 `StatusTimeline` 子组件。

```
┌─ 候选人详情 · 张三 ─────────────────────────────── ×  560px Drawer ──┐
│                                                                        │
│  张三  ·  高级后端工程师  ·  北京                   当前状态 Tag       │
│  应聘：后端工程师  ·  来源：BOSS直聘                [待人工初筛] ⚡    │
│                                                                        │
│  ┌─ Tab 切换 ──────────────────────────────────────────────────────┐  │
│  │  基本信息    简历    AI 评分    状态历史    联系方式              │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  /* Tab: 状态历史 */                                                   │
│                                                                        │
│  2026-04-16 14:32  → 面试已预约          [招聘员覆盖] ⚠               │
│  覆盖理由：HR 总监推荐，跳过线下评分直接安排面试                      │
│                                                                        │
│  ──────────────────────────────────────────────────────────────────    │
│  2026-04-15 09:10  → AI 线下评分未通过   [Agent]                      │
│  AI 评分 42/100（阈值 60），自动流转淘汰                              │
│                                                                        │
│  ──────────────────────────────────────────────────────────────────    │
│  2026-04-14 18:05  → 已收到简历          [Agent]                      │
│                                                                        │
│  ──────────────────────────────────────────────────────────────────    │
│  2026-04-13 11:22  → 对话进行中          [Agent]                      │
│                                                                        │
│  ──────────────────────────────────────────────────────────────────    │
│  [展开更多历史]                                                        │
│                                                                        │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━    │
│  /* 底部操作区（根据当前状态动态显示） */                              │
│                                                                        │
│  当前：待人工初筛                                                      │
│  [初筛通过]  [标记淘汰]  [人工修改状态…]                               │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 11. 页面设计：状态机编辑器

入口：设置 Tab → AI 策略 → 状态机配置  
（或：工作台看板右上角 [状态机配置] 入口）

```
┌─ 状态机配置 ──────────────────────────────────────────────────────────┐
│  当前版本 v7 · 上次编辑 2026-04-15 by xudaoyang        [查看历史版本]  │
│                                                                        │
│  /* 左侧：节点列表（可拖拽排序） */       /* 右侧：节点详情编辑 */     │
│  ┌─────────────────────────┐  ┌─────────────────────────────────────────────────┐ │
│  │ [+ 新增状态]            │  │ 编辑节点：pending_human_review                   │ │
│  │ ─────────────────────── │  │                                                 │ │
│  │ ≡  A · 已发现·待评估    │  │ ID（不可改）  pending_human_review              │ │
│  │ ≡  A · AI在线评估中     │  │ 显示名称      [待人工初筛               ]       │ │
│  │ ≡  A · AI评估通过  ↝   │  │ 阶段          [E · 人工初筛             ▾]      │ │
│  │ ≡  A · AI评估未通过 ×   │  │                                                 │ │
│  │ ≡  B · 待发起沟通  ⚙   │  │ 基础属性                                        │ │
│  │ ≡  B · 已发消息·等回复  │  │  是否终止态  □   是否软终止  □   是否过渡态  □  │ │
│  │ ≡  B · 无回复·可重试 ~  │  │  在工作台看板显示  ☑   在漏斗看板计数  □       │ │
│  │ ≡  B · 对话进行中  ⚙   │  │  触发里程碑  [M09 · 人工初筛完成  ▾]           │ │
│  │ ... （可折叠 by 阶段）  │  │  说明（供 Agent 理解）                          │ │
│  │                         │  │  [AI 评分通过后，等招聘员确认是否继续推进   ]   │ │
│  │ × 终止态                │  │                                                 │ │
│  │ ~ 软终止态              │  │ ─────────────────────────────────────────────── │ │
│  │ ↝ 过渡态（自动跳转）    │  │ ⚙ 执行方式                                      │ │
│  │ ⚙ 可配置执行方式        │  │                                                 │ │
│  │                         │  │  ● 人工介入（human_required）                   │ │
│  │                         │  │  ○ AI 自动（ai_auto）                           │ │
│  │                         │  │                                                 │ │
│  │                         │  │  /* 当前选中：人工介入 */                        │ │
│  │                         │  │                                                 │ │
│  │                         │  │  操作按钮配置                                   │ │
│  │                         │  │  ┌──────────────────────────────────────────┐  │ │
│  │                         │  │  │ 文字      目标状态          样式  必填备注 │  │ │
│  │                         │  │  │ 通过    → human_passed      主色   □      │  │ │
│  │                         │  │  │ 淘汰    → human_rejected    危险   □      │  │ │
│  │                         │  │  │ 暂缓    → pending_human...  默认   ☑      │  │ │
│  │                         │  │  │ [+ 添加操作]                              │  │ │
│  │                         │  │  └──────────────────────────────────────────┘  │ │
│  │                         │  │                                                 │ │
│  │                         │  │  /* 若切换为 AI 自动，则隐藏按钮配置，展示 */   │ │
│  │                         │  │  /* AI 评估标准配置区 ↓ */                      │ │
│  │                         │  │                                                 │ │
│  │                         │  │  AI 评估标准（criteriaRef）                     │ │
│  │                         │  │  类型  ● Skill  ○ Prompt  ○ 规则表达式        │ │
│  │                         │  │  Skill [resume_scoring_v1  ▾]                  │ │
│  │                         │  │  通过阈值  [70        ]  分                     │ │
│  │                         │  │  /* type=Prompt 时展示多行文本框 */             │ │
│  │                         │  │  /* type=规则 时展示单行表达式输入框 */         │ │
│  │                         │  │                                                 │ │
│  │                         │  │ ─────────────────────────────────────────────── │ │
│  │                         │  │ 合法转换                                        │ │
│  │                         │  │  ← 来自：offline_score_passed                   │ │
│  │                         │  │  → 去往：human_review_passed                    │ │
│  │                         │  │          human_review_rejected                  │ │
│  │                         │  │  [+ 添加转换规则]                               │ │
│  └─────────────────────────┘  └─────────────────────────────────────────────────┘ │
│                                                                        │
│  [取消]                                           [保存并发布 v8]      │
│  ⚠ 保存后，Agent 下次执行将使用新版状态机                              │
└────────────────────────────────────────────────────────────────────────┘
```

**编辑器图例说明**

```
节点列表标记：
  × 终止态
  ~ 软终止态
  ↝ 过渡态（不展示在看板，不可配置执行方式）
  ⚙ 可配置执行方式（ai_auto / human_required 均可切换）
  无标记 = CANDIDATE 等待节点（执行方式不可配置）

执行方式切换规则：
  · 切换时若目标 mode 对应的配置区为空，自动从 transitions 生成默认按钮/标准
  · locked=true 的节点（如 H1 offer_pending）不展示切换控件，只读显示
  · 改变 mode 后，旧配置保留在另一 mode 的字段中，不删除（方便来回切换）
```

---

## 12. 实施 Plan

> 优先级对照第 0.5 节差距分析。P0 是解锁后续一切的基础，P1 是核心看板与 Agent 感知，P2 是 Agent 自主能力升级。

---

### P0 · 状态机协议层（基础，无 UI，解锁一切后续）

**目标**：把隐式在代码里的状态分类正则，变成 Agent 和 UI 都能读的显式配置。完成后，状态机成为系统的唯一事实来源。

| 步骤 | 内容 | 涉及位置 |
|---|---|---|
| P0-1 | 在 `packages/shared` 定义完整类型：`StateNode`（含 `executionConfig`）/ `StateTransition` / `RecruitmentStateMachine` / `CandidateStatusTransition` / `FunnelMilestone` | `packages/shared/src/types/stateMachine.ts` |
| P0-2 | 写入初始状态机 seed 文件（按第 3 节 30 个节点），含每个可配置节点的默认 `executionConfig`（`mode` / `humanActions` / `criteriaRef`） | `packages/shared/src/data/defaultStateMachine.json` |
| P0-3 | 定义里程碑常量与 `deepestMilestone` 推进函数（只增不减，跨节点补打逻辑） | `packages/shared/src/types/milestone.ts` |
| P0-4 | 后端新增 API：`GET /state-machine`、`PUT /state-machine`（版本化存储）、`POST /candidates/:id/transition`（含合法性校验 + override 路径 + 历史写入）、`GET /candidates/:id/transitions`（历史记录） | 后端路由层 |
| P0-5 | `apiClient` 新增对应方法，替换现有 `transitionCandidateState`（保持接口兼容但内部走新路径） | `apps/desktop/src/lib/api.ts` |
| P0-6 | **迁移现有候选人数据**：将 `candidate.status` / `candidate.stageKey` 字符串映射到状态机节点 ID，写入 `currentStatus`；同时计算并写入 `deepestMilestone` | 数据迁移脚本 |

---

### P1-A · Agent 状态机感知与规范化执行

**目标**：Agent 从读状态机配置驱动行为，替代靠 Goal 自然语言猜测下一步。

| 步骤 | 内容 | 涉及位置 |
|---|---|---|
| P1-A-1 | Agent 启动时读 `GET /state-machine`，缓存版本号；每轮 run 开始检查版本，变更时重新加载 | Agent runtime |
| P1-A-2 | Agent 处理候选人时，根据 `currentStatus` 查 `executionConfig.mode`：`ai_auto` → 调 criteriaRef 决策；`human_required` → 创建 `OperatorInteraction` 并挂起 | Agent runtime |
| P1-A-3 | Agent 所有状态流转统一通过 `POST /candidates/:id/transition`，附带 `actor=agent`、`trigger`（决策依据）、`criteriaRef` 快照 | Agent runtime |
| P1-A-4 | Agent 异常处理路径：识别需要回退的场景（见 0.3 节示例）→ 调用带 `overrideReason` 的 transition API，标注 `actor=agent_override` | Agent runtime |
| P1-A-5 | Agent 遇到 `human_required` + `locked=true` 节点时，创建 OperatorInteraction 并附上决策建议摘要（而非直接操作） | Agent runtime |

---

### P1-B · 看板 UI（两个看板页面）

**目标**：看板从状态机配置渲染，替代 UI 硬编码的状态分类。

| 步骤 | 内容 | 涉及位置 |
|---|---|---|
| P1-B-1 | `DesktopWorkspace` candidates tab 增加 `SectionTabs`（漏斗看板 / 状态看板） | `features/workspace/DesktopWorkspace.tsx` |
| P1-B-2 | 新建 `FunnelKanbanView`：筛选行 + `FunnelStageBar`（读里程碑配置渲染节点条）+ `CandidateTable` | `features/funnel-kanban/` |
| P1-B-3 | 新建 `StatusKanbanView`：筛选行 + `StatusChain`（读状态机节点渲染两行链条 + 旁路）+ `CandidateTable` | `features/status-kanban/` |
| P1-B-4 | `CandidateTable` 操作列改为从 `executionConfig.humanActions` 动态渲染按钮（替代硬编码），`mode=ai_auto` 时只显示 [详情] | `features/kanban-shared/CandidateTable.tsx` |
| P1-B-5 | 提取 `FunnelStageBar` / `StatusChain` 两个无状态纯展示组件 | `features/kanban-shared/` |

---

### P1-C · 候选人沟通综合面板

**目标**：内联三列面板，聊天 + 简介 + 状态时间线，两个看板复用。

| 步骤 | 内容 | 涉及位置 |
|---|---|---|
| P1-C-1 | `StatusTimeline` 组件（时间线：普通节点 / 里程碑 ★ / 人工覆盖 ⚡ / Agent覆盖 ⚡） | `features/kanban-shared/StatusTimeline.tsx` |
| P1-C-2 | `CandidateCommunicationPanel`（三列内联展开：精简列表 + 聊天窗口 + 简介&时间线） | `features/kanban-shared/CandidateCommunicationPanel.tsx` |
| P1-C-3 | `ChatMessageFeed`（气泡渲染、日期胶囊、Agent 角标）+ 空态（未沟通时展示候选人核心信息卡） | `features/kanban-shared/ChatMessageFeed.tsx` |
| P1-C-4 | `ChatInputArea`（textarea + 工具栏 + Agent 代发提示）；写入消息后触发 Agent 同步到招聘平台 | `features/kanban-shared/ChatInputArea.tsx` |
| P1-C-5 | 集成至 `FunnelKanbanView` 和 `StatusKanbanView`；"打开沟通"触发三列展开，`grid-template-columns` 过渡动效 | 步骤 P1-B-2、P1-B-3 文件 |
| P1-C-6 | `CandidateDetailDrawer`（560px，Tab：基本信息 / 简历 / AI评分 / 状态历史 / 联系方式），状态历史 Tab 复用 `StatusTimeline` | `features/kanban-shared/CandidateDetailDrawer.tsx` |
| P1-C-7 | `ManualStatusOverrideDrawer`（人工修改状态：目标状态选择 + 影响预览 + 覆盖理由） | `features/kanban-shared/ManualStatusOverrideDrawer.tsx` |

---

### P1-D · 状态机编辑器 UI

**目标**：招聘员可视化配置每个节点的执行方式（ai_auto ↔ human_required）和对应的 criteriaRef / humanActions。

| 步骤 | 内容 | 涉及位置 |
|---|---|---|
| P1-D-1 | `StateMachineEditor` 页面（入口：AI 策略 Tab 内新增子 Tab） | `features/state-machine/StateMachineEditor.tsx` |
| P1-D-2 | 左侧节点列表（拖拽排序，图例标记：⚙ 可配置 / ↝ 过渡 / × 终止 等） | — |
| P1-D-3 | 右侧节点详情面板：基础属性 + ⚙ 执行方式区块（mode 切换 + criteriaRef 配置 + humanActions 编辑） | — |
| P1-D-4 | 版本历史查看（只读，可对比两个版本 diff） | — |
| P1-D-5 | 保存时递增版本号，Agent 下次 run 自动感知（P1-A-1 已实现轮询检查） | — |

---

### P2 · Agent 自主能力升级

**目标**：从"被动响应 Goal"升级到"主动判断、自主学习、跨候选人编排"。

| 步骤 | 内容 | 优先级 | 依赖 |
|---|---|---|---|
| P2-1 | **自主抓取触发**：Agent 监控漏斗候选人数量，低于阈值时主动启动 browser-mcp 扫描补充；招聘员可在设置中配置最小候选人数 | P2 | P1-A |
| P2-2 | **跨候选人调度优先级**：Agent 每轮 run 按综合评分（AI 评分 × 阶段深度 × 等待时长）排序候选人队列，优先推进高潜力候选人 | P2 | P1-A |
| P2-3 | **Skill 自动沉淀**：Agent 完成一次候选人推进后，将决策过程（候选人特征 × 操作 × 结果）写入 `EvolutionArtifact`，经招聘员审批后合并为新 Skill 版本 | P2 | P0、P1-A |
| P2-4 | **criteriaRef 自优化**：Agent 统计每个节点的 `ai_auto` 决策准确率（后续人工覆盖率作为反馈信号），建议调整阈值或更换 Skill；招聘员在状态机编辑器中审批 | P2 | P2-3 |
| P2-5 | **主动状态回退识别**：Agent 在沟通消息解析时识别特定信号（"已接受其他 Offer"/"暂时不考虑换工作"等）→ 主动触发状态流转（candidate_withdrew / cooldown），无需人工触发 | P2 | P1-A |
| P2-6 | **超时重试机制**：Agent 监控 `outreach_sent` / `resume_requested` 等等待候选人的节点，超过配置天数未收到回应时，自动按 retryPolicy 重试或升级人工介入 | P2 | P0 |

---

### 各阶段交付物与验收标准

```
P0 完成后验收：
  · candidate.currentStatus 能映射到状态机节点 ID
  · POST /candidates/:id/transition 拒绝非法转换，返回 400 + 错误说明
  · GET /candidates/:id/transitions 返回结构化历史记录

P1-A 完成后验收：
  · Agent 不再出现 resolveMacroStage 类的正则分类代码
  · Agent 每次状态流转在历史记录中有完整的 actor/trigger/criteriaRef 快照
  · human_required 节点 Agent 确实挂起，不自动流转

P1-B/C/D 完成后验收：
  · 看板两个 Tab 正常展示，节点数据来自状态机配置而非硬编码
  · 人工介入按钮文字来自 humanActions 配置，改配置后 UI 实时反映
  · 沟通面板三列展开正常，聊天消息同步

P2 完成后验收：
  · Agent 在无 Goal 触发的情况下，发现候选人数量不足时自动启动扫描
  · Skill 建议经审批后能被后续候选人的评估直接引用
  · 状态回退由 Agent 自主触发的记录在历史中标注正确
```

---

## 附录：当前状态机 vs 修订状态机对照

| 用户原始设计 | 修订版 | 说明 |
|---|---|---|
| 已发现 | M01 discovered | 一致 |
| AI已生成在线简历评估 | ai_online_screening + ai_online_passed | 拆分"评估中"和"评估通过"两个状态 |
| AI在线简历通过 | M03 ai_screen_passed（里程碑） | 里程碑保留，状态合并到 ai_online_passed |
| AI已沟通 | outreach_sent + in_conversation | 拆分"已发消息"和"对话建立"，增加"无回复"软终止 |
| AI已拿到线下简历 | resume_received（M06） | 一致，补充了"待获取简历"前置状态 |
| AI已生成线下简历评分 | offline_scoring + offline_score_passed | 拆分评分中和评分通过 |
| （待定）人工评估 | pending_human_review（E 阶段）| 明确化，放在线下评分通过之后、联系方式之前 |
| 已拿到联系方式 | contact_requested + contact_acquired（M11） | 增加"待获取"前置状态 |
| 已人工初步评估通过 | human_review_passed | 调整位置：在拿联系方式之前（更合理） |
| 已预约面试人数 | interview_scheduled（M12） | 一致，补全面试后续状态 |
| （缺失） | interview_completed / passed / rejected | 新增 |
| （缺失） | offer_pending / sent / accepted / rejected | 新增 |
| （缺失） | no_response / archived / cooldown / candidate_withdrew | 新增全局/软终止态 |
