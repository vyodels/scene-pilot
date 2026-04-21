# 候选人 / JD / 投递记录 · 目标数据模型规范

## 文档目标与适用范围
本文档定义 recruit-agent 在招聘业务对象建模上的长期目标数据模型，用于约束 CandidatePerson、CandidateApplication、JobDescription 及其附属对象的命名、主键规则、字段边界、挂载原则与读写路径。

本文档记录的是长期稳定的目标规范，不讨论迁移策略、兼容层、旧字段保留、历史数据回填或实施计划。若实现与本文档冲突，应优先修正实现，或先更新本文档后再继续变更。

## 与现有规范的关系
- 本文档负责定义招聘业务对象层的 canonical 数据模型。
- 运行时、memory、prompt、tool、MCP、双 Agent 架构与能力演进等问题，仍以 `docs/specs/` 下对应规范为准。
- 与数据模型收敛相关的实施过程，仍以 `docs/plan/completed/2026-04-17-canonical-entity-naming-and-schema-plan.md` 等计划文档作为历史参考，而不是作为长期真相来源。

## 1. 文档定位

本规范只回答一个问题：

> 系统最终应该长成什么样。

它用于统一以下目标：

- 明确系统维护的业务实体是什么
- 明确人、平台身份、投递实例、JD 各自回答什么问题
- 明确状态机、聊天、评估、看板应该挂在哪个实体上
- 明确全系统 canonical 命名、双 ID 规则与时间字段规则

本文件不讨论：

- 旧表如何迁移
- 旧 API 如何兼容
- 历史数据如何桥接
- 当前实现进度如何

---

## 2. 核心业务抽象

系统最终拆成三层核心主语：

```text
CandidatePerson（候选人这个人）
  └── CandidateApplication（候选人围绕某个 JD 的一次投递记录）
        ├── 状态机流转
        ├── 聊天记录
        ├── 评估 / 评分卡 / 评审决定
        ├── 简历制品
        ├── 分配与同步记录
        └── 漏斗 / 看板统计

JobDescription（职位描述）
  └── CandidateApplication 的目标对象
```

### 2.1 CandidatePerson 回答的问题

`candidate_persons` 表示“这个人是谁”。

它回答的问题是：

- 这个人的稳定身份是什么
- 这个人的已知联系方式是什么
- 这个人在不同平台上的身份是否已经被统一到同一个人

### 2.2 CandidateApplication 回答的问题

`candidate_applications` 表示“一次投递记录”。

它回答的问题是：

- 这个人投了哪个 JD
- 这次投递来自哪个平台
- 这次投递当前处于哪个 workflow 状态
- 这次投递的聊天、评估、简历、状态历史是什么

### 2.2.1 CandidateApplication 的对外语义与跟进粒度

尽管技术命名保留 `CandidateApplication`，但在产品、prompt、tool、UI/API 与运行时讨论中，凡是涉及：

- 跟进
- 沟通
- 消息同步
- 状态推进
- AI 评分
- 上下文隔离
- subagent / 子上下文绑定对象

默认都必须理解为“某候选人围绕某个 JD 的一次投递记录”，而不是 `CandidatePerson` 这个人本身。

同一个人可以在不同 JD、不同时间窗口下同时存在多条 `candidate_applications`。因此，系统不得把真正的执行主语偷换成“候选人跟进”这种会模糊 JD 边界的说法；若讨论的是实际流程推进对象，应优先表述为“一次投递记录的跟进”。

### 2.3 JobDescription 回答的问题

`job_descriptions` 表示“一个正式 JD”。

它回答的问题是：

- 这个 JD 的标题、地点、要求、职责是什么
- 这个 JD 当前是否有效
- 这个 JD 在不同来源平台上的外部标识是什么

---

## 3. Canonical 命名

最终主表命名统一如下：

| 含义 | 表名 |
|---|---|
| 候选人主实体 | `candidate_persons` |
| 候选人在各平台的身份索引 | `candidate_person_platform_idx` |
| 候选人投递实例 | `candidate_applications` |
| 职位描述主表 | `job_descriptions` |
| JD 平台索引 | `job_description_platform_idx` |

最终 application-scoped 附属表统一如下：

| 含义 | 表名 |
|---|---|
| 投递消息 | `candidate_application_messages` |
| 投递状态流转 | `candidate_application_transitions` |
| 投递评估记录 | `candidate_application_assessments` |
| 投递评分卡 | `candidate_application_scorecards` |
| 投递评审决定 | `candidate_application_review_decisions` |
| 投递简历制品 | `candidate_application_resume_artifacts` |
| 投递分配记录 | `candidate_application_assignments` |
| 投递同步记录 | `candidate_application_sync_records` |

---

## 4. 双 ID 规则

每张业务表同时包含两类 ID：

### 4.1 技术主键

统一保留：

```sql
id BIGINT PRIMARY KEY AUTOINCREMENT
```

它只用于数据库内部主键与关联，不直接承载业务语义。

### 4.2 显式业务主语 ID

每张表都必须有稳定、可读、可跨层传递的业务 ID，例如：

- `candidate_person_id`
- `candidate_person_platform_idx_id`
- `candidate_application_id`
- `candidate_application_message_id`
- `candidate_application_transition_id`
- `candidate_application_assessment_id`
- `candidate_application_scorecard_id`
- `candidate_application_review_decision_id`
- `candidate_application_resume_artifact_id`
- `candidate_application_assignment_id`
- `candidate_application_sync_record_id`
- `job_description_id`
- `job_description_platform_idx_id`

业务 API、前端协议、日志、状态图、外部引用都应优先使用这些业务 ID。

---

## 5. 时间字段规则

所有时间字段统一为：

```sql
BIGINT
```

语义统一为：

> 秒级 Unix 时间戳（int64）

包括但不限于：

- `created_at`
- `updated_at`
- `first_seen_at`
- `last_seen_at`
- `last_contacted_at`
- `cooldown_until`
- `occurred_at`
- `captured_at`
- `decided_at`
- `assessed_at`
- `assigned_at`
- `released_at`
- `last_synced_at`

目标模型中不使用 `TEXT datetime` 作为正式时间存储格式。

---

## 6. 核心业务约束

### 6.1 状态机挂在 `candidate_applications`

状态机推进的是“一次投递”的进度，不是“这个人”的身份状态。

因此这些信息都必须挂在 `candidate_applications` 或其 application-scoped 附属表上：

- `current_status`
- `current_stage_key`
- `deepest_milestone`
- `cooldown_until`
- `last_contacted_at`
- `state_snapshot`
- transitions / messages / assessments / review decisions

### 6.2 聊天主体挂在 `candidate_applications`

聊天窗口、消息流、等待重试、沟通状态都围绕一次投递记录存在。

同一个人可以同时存在多条 application，因此聊天不能挂在 person 层。

### 6.3 漏斗和状态看板按 `candidate_applications` 统计

漏斗、状态看板、工作台主行对象都统计“投递实例”，不是“去重后的人数”。

### 6.4 联系方式获取前，不做跨平台隐式合并

在没有稳定联系方式前：

- 不根据姓名自动合并
- 不根据岗位或公司自动合并
- 不根据头像、简介做隐式合并

平台身份先独立存在于 `candidate_person_platform_idx`。

### 6.5 获取稳定联系方式后，建立 CandidatePerson 关联

拿到手机号 / 微信号后：

- 先标准化联系方式
- 再基于稳定联系方式查重
- 命中则关联或合并到同一个 `candidate_person_id`
- 未命中则保留为新的 person

### 6.6 同一 person 同一 JD 同一自然月只允许一条 application

通过 `application_window` 强制约束。

表达式含义：

```text
{candidate_person_id}_{job_description_id}_{YYYY-MM}
```

只要三者相同，该自然月内就不允许创建第二条 application。

### 6.7 JD 是正式实体，不是自由字符串

系统最终不允许把 JD 仅当作一个自由字符串 `jd_id` 使用。

JD 必须：

- 有正式主表 `job_descriptions`
- 有正式平台索引表 `job_description_platform_idx`
- 被 `candidate_applications.job_description_id` 正式引用

---

## 7. 目标表结构

下面只描述业务结构与字段边界，不讨论 ORM 写法或迁移方式。

### 7.1 `candidate_persons`

```sql
CREATE TABLE candidate_persons (
    id                                BIGINT PRIMARY KEY AUTOINCREMENT,
    candidate_person_id               TEXT NOT NULL UNIQUE,
    display_name                      TEXT NOT NULL,
    normalized_phone                  TEXT,
    normalized_wechat                 TEXT,
    extra_contact                     JSON NOT NULL DEFAULT '{}',
    merged_from_candidate_person_ids  JSON NOT NULL DEFAULT '[]',
    created_at                        BIGINT NOT NULL,
    updated_at                        BIGINT NOT NULL
);
```

只保留人的稳定身份信息。

不在 person 表保留：

- workflow 状态
- 当前阶段
- 简历正文
- AI 评分
- 冷却时间
- 最近联系时间

### 7.2 `candidate_person_platform_idx`

```sql
CREATE TABLE candidate_person_platform_idx (
    id                               BIGINT PRIMARY KEY AUTOINCREMENT,
    candidate_person_platform_idx_id TEXT NOT NULL UNIQUE,
    candidate_person_id              TEXT NOT NULL,
    platform                         TEXT NOT NULL,
    platform_candidate_person_id     TEXT NOT NULL,
    profile_url                      TEXT,
    raw_profile                      JSON NOT NULL DEFAULT '{}',
    first_seen_at                    BIGINT NOT NULL,
    last_seen_at                     BIGINT NOT NULL,
    created_at                       BIGINT NOT NULL,
    updated_at                       BIGINT NOT NULL,
    UNIQUE(platform, platform_candidate_person_id)
);
```

### 7.3 `job_descriptions`

```sql
CREATE TABLE job_descriptions (
    id                 BIGINT PRIMARY KEY AUTOINCREMENT,
    job_description_id TEXT NOT NULL UNIQUE,
    title              TEXT NOT NULL,
    team               TEXT,
    location           TEXT,
    employment_type    TEXT,
    description_text   TEXT,
    requirements_text  TEXT,
    status             TEXT NOT NULL DEFAULT 'active',
    source             TEXT NOT NULL DEFAULT 'manual',
    created_at         BIGINT NOT NULL,
    updated_at         BIGINT NOT NULL
);
```

### 7.4 `job_description_platform_idx`

```sql
CREATE TABLE job_description_platform_idx (
    id                            BIGINT PRIMARY KEY AUTOINCREMENT,
    job_description_platform_idx_id TEXT NOT NULL UNIQUE,
    job_description_id            TEXT NOT NULL,
    platform                      TEXT NOT NULL,
    external_id                   TEXT NOT NULL,
    external_url                  TEXT,
    sync_status                   TEXT NOT NULL DEFAULT 'pending',
    sync_metadata                 JSON NOT NULL DEFAULT '{}',
    last_synced_at                BIGINT,
    created_at                    BIGINT NOT NULL,
    updated_at                    BIGINT NOT NULL,
    UNIQUE(platform, external_id)
);
```

### 7.5 `candidate_applications`

```sql
CREATE TABLE candidate_applications (
    id                                 BIGINT PRIMARY KEY AUTOINCREMENT,
    candidate_application_id           TEXT NOT NULL UNIQUE,
    candidate_person_id                TEXT NOT NULL,
    job_description_id                 TEXT,
    source_platform                    TEXT NOT NULL,
    source_platform_candidate_person_id TEXT,
    application_window                 TEXT NOT NULL,
    current_status                     TEXT NOT NULL,
    current_stage_key                  TEXT,
    deepest_milestone                  TEXT,
    contact_snapshot                   JSON NOT NULL DEFAULT '{}',
    resume_snapshot                    JSON NOT NULL DEFAULT '{}',
    state_snapshot                     JSON NOT NULL DEFAULT '{}',
    cooldown_until                     BIGINT,
    last_contacted_at                  BIGINT,
    active_assessment_summary          JSON NOT NULL DEFAULT '{}',
    application_metadata               JSON NOT NULL DEFAULT '{}',
    created_at                         BIGINT NOT NULL,
    updated_at                         BIGINT NOT NULL,
    UNIQUE(application_window)
);
```

`candidate_applications` 是唯一 workflow 主锚点。

---

## 8. Assessment 与 Scorecard 边界

### 8.1 `candidate_application_assessments`

这张表表示“一次评估动作的结论记录”。

它必须能承载：

- AI 在线评估
- AI 线下评估
- 人工初筛评估
- 面试评价
- 同阶段多次重评

```sql
candidate_application_assessment_id
candidate_application_id
assessment_actor_type
assessment_stage_key
assessment_stage_label
assessment_round
decision
score
summary
criteria_snapshot
evidence_snapshot
result_payload
assessment_metadata
assessed_at
created_at
updated_at
```

### 8.2 `candidate_application_scorecards`

这张表只表示“结构化打分卡”。

它只承载：

- rubric / 维度分数
- score total
- verdict
- evidence snapshot
- scorecard metadata

它不负责承载：

- 面试流程安排
- 评估轮次管理
- 一次评估动作的多来源完整结论

```sql
candidate_application_scorecard_id
candidate_application_id
assessment_stage_key
scorecard_source
rubric_version
score_total
verdict
summary
dimension_scores
evidence_snapshot
scorecard_metadata
created_at
updated_at
```

---

## 9. Application-scoped 附属表

下面这些表都必须用 `candidate_application_id` 作为外键主锚点：

- `candidate_application_messages`
- `candidate_application_transitions`
- `candidate_application_assessments`
- `candidate_application_scorecards`
- `candidate_application_review_decisions`
- `candidate_application_resume_artifacts`
- `candidate_application_assignments`
- `candidate_application_sync_records`

### 9.1 `candidate_application_messages`

只保留：

- 原始消息
- 少量核心结构化信号

核心字段：

- `candidate_application_message_id`
- `candidate_application_id`
- `direction`
- `message_type`
- `content`
- `signal_snapshot`
- `message_metadata`
- `occurred_at`
- `created_at`
- `updated_at`

### 9.2 `candidate_application_transitions`

核心字段：

- `candidate_application_transition_id`
- `candidate_application_id`
- `from_status`
- `to_status`
- `from_status_label`
- `to_status_label`
- `actor`
- `actor_id`
- `trigger`
- `note`
- `override_reason`
- `transition_metadata`
- `created_at`
- `updated_at`

---

## 10. 状态机、聊天、看板挂载原则

最终统一规则如下：

- 状态机推进挂在 `candidate_applications`
- 聊天主体挂在 `candidate_applications`
- 漏斗和状态看板按 `candidate_applications` 统计
- 人的合并不会自动合并 application
- `candidate_persons` 只承载身份，不承载 workflow

---

## 11. Agent 的目标写入路径

Agent 最终写入规则如下：

- discovery 创建或更新 `candidate_persons`、`candidate_person_platform_idx`
- JD 解析与同步创建或更新 `job_descriptions`、`job_description_platform_idx`
- 一旦形成正式投递实例，就创建或更新 `candidate_applications`
- 所有流程推进、副产物、聊天、评估、评分卡、review、resume artifact、assignment、sync record 全部写入 application-scoped 表

Agent 不应把 workflow 信息直接写回 `candidate_persons`。

---

## 12. 目标读取路径

最终读取规则如下：

- 候选人身份页读取 `candidate_persons`
- 平台身份与跨平台关联读取 `candidate_person_platform_idx`
- 看板、线程、状态历史、聊天、评估、resume、assignment、sync 统一读取 `candidate_applications` 及其附属表
- `/dashboard` 等聚合视图的主行对象必须是 application-centric

---

## 13. 非目标与边界

本规范不要求：

- 保留旧 `/api/candidates`
- 保留 person-scoped workflow 字段
- 在目标模型中保留混合语义 `candidate_id`
- 在目标模型中继续使用 `TEXT datetime`

---

## 14. 结论

系统最终只有一套 canonical 目标模型：

- `candidate_persons` 管“人”
- `candidate_applications` 管“投递实例与流程”
- `job_descriptions` 管“JD”

所有业务 API、看板、线程、聊天、状态历史和评估读写，都应围绕这个模型展开。
