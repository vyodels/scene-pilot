# 候选人 / JD / 投递记录 · 目标数据模型规范

**版本**：v1.1  
**日期**：2026-04-16  
**状态**：目标规范（不讨论迁移）  
**说明**：本文件只描述目标世界里的最终数据模型、实体边界、约束与写读路径。**不讨论迁移策略、兼容层、旧字段保留、历史数据回填或实施计划。**

---

## 目录

1. [文档定位](#1-文档定位)
2. [核心业务抽象](#2-核心业务抽象)
3. [命名与实体边界](#3-命名与实体边界)
4. [核心业务约束](#4-核心业务约束)
5. [目标表结构](#5-目标表结构)
6. [状态机、聊天、看板的挂载原则](#6-状态机聊天看板的挂载原则)
7. [Agent 的目标写入路径](#7-agent-的目标写入路径)
8. [联系方式与跨平台关联规则](#8-联系方式与跨平台关联规则)
9. [JD 同步规则](#9-jd-同步规则)
10. [目标读取路径](#10-目标读取路径)
11. [数据库约束与索引](#11-数据库约束与索引)
12. [非目标与边界](#12-非目标与边界)
13. [结论](#13-结论)

---

## 1. 文档定位

本文件是一份**目标数据模型规范**，用于统一以下问题：

- 系统最终维护的业务实体是什么
- 每个实体回答什么问题
- 状态机应该挂在哪个实体上
- 聊天记录、状态历史、漏斗、状态看板应该围绕谁建立
- 候选人在多平台出现时，如何建立统一候选人身份
- JD（职位描述）如何作为正式实体存在，并支持内网 / BOSS 等外部来源同步

本文件**不讨论**：

- 旧表如何拆分或迁移
- 旧字段如何兼容
- 历史数据如何回填
- 临时桥接层如何设计

换句话说，这份文档只回答：

> **系统最终应该长成什么样。**

---

## 2. 核心业务抽象

系统最终应拆成三层核心实体：

```text
Candidate（候选人 / 人）
  └── CandidateApplication（候选人投递记录 / 一次投递实例）
        ├── 状态机流转
        ├── 聊天记录
        ├── 状态历史
        ├── 简历与评分
        ├── 漏斗统计
        └── 状态看板统计

JobDescription（职位描述 / JD）
  └── 候选人投递的目标对象
```

### 4.1 Candidate（候选人）回答的问题

`candidates` 这张表表示的是**一个人**。

它回答的问题是：

- 这个人是谁
- 这个人已知的联系方式是什么
- 这个人在不同平台上有哪些身份
- 这个人是否和其他平台身份已经建立统一关联

### 4.2 CandidateApplication（候选人投递记录）回答的问题

`candidates_applications` 这张表表示的是**一次投递实例**。

它回答的问题是：

- 这个候选人投了哪个 JD
- 这次投递来自哪个平台
- 这次投递当前处于状态机的哪个节点
- 这次投递的聊天记录是什么
- 这次投递的状态历史是什么
- 这次投递有没有拿到简历 / 联系方式 / 面试安排

### 4.3 JobDescription（职位描述）回答的问题

`job_descriptions` 这张表表示的是**一个 JD**。

它回答的问题是：

- 这个职位描述是什么
- 这个职位描述的标题、部门、地点、要求、职责是什么
- 这个 JD 当前是否有效
- 这个 JD 在内网或 BOSS 等平台上的外部 ID 分别是什么

---

## 3. 命名与实体边界

最终表命名统一如下：

| 含义 | 表名 |
|---|---|
| 候选人主表（人的实体） | `candidates` |
| 候选人在各平台的身份索引 | `candidates_platform_idx` |
| 候选人投递记录 | `candidates_applications` |
| 职位描述主表 | `job_descriptions` |
| JD 在各平台的索引 | `job_descriptions_platform_idx` |

### 5.1 为什么候选人表仍叫 `candidates`

这里的 `candidates` 代表的是“候选人这个人”，而不是一次投递记录。这个命名在招聘业务里自然、稳定，也最容易理解。

### 5.2 为什么投递记录表叫 `candidates_applications`

你已经明确：

- 人可以合并
- 流转的是一次投递记录实例
- 聊天主体是一次投递记录实例
- 漏斗和看板维护的是一次投递记录实例

所以“application”是整个流程挂载的正确对象。

### 5.3 为什么 JD 表叫 `job_descriptions`

这里要强调的是“职位描述”的概念，而不是泛泛的 job / position。业务里你已经习惯用 JD，这里用 `job_descriptions` 最准确。

---

## 4. 核心业务约束

下面这些约束是这套模型的核心，不依赖任何具体实现方式。

### 6.1 约束一：状态机挂在 `candidates_applications`

状态机推进的是“这次投递”的进度，不是“这个人”的状态。

因此：

- `current_status`
- `deepest_milestone`
- `state_snapshot`
- `candidate_status_transitions`（或其目标重命名形态）

都应该挂在 `candidates_applications` 上。

### 6.2 约束二：聊天主体挂在 `candidates_applications`

聊天窗口、消息流、对话状态，都围绕“一次投递”存在。

因为同一个人可以：

- 在不同平台对不同 JD 同时沟通
- 对同一 JD 在不同时间有不同投递实例

所以聊天主体不能挂在 Candidate（人）层，而必须挂在 CandidateApplication（投递记录）层。

### 6.3 约束三：漏斗和状态看板都按 `candidates_applications` 统计

漏斗看板和状态看板统计的是“投递实例”的推进，不是“去重后的候选人数”。

也就是说：

- 一个候选人有两条投递记录 → 看板上是两条独立记录
- 一个候选人在两个平台分别投递同一 JD → 若落成两个独立 application，则看板上是两条记录
- Candidate 的合并不会自动合并 Application

### 6.4 约束四：拿到联系方式前，不做跨平台合并

在没有稳定联系方式之前：

- 不根据姓名去自动合并
- 不根据职位或公司去自动合并
- 不根据头像、简介做隐式合并

每个平台的候选人都先独立存在。

### 6.5 约束五：拿到手机号 / 微信号后，才建立 Candidate 层关联

当 Agent 获取到稳定联系方式时：

- 标准化手机号
- 标准化微信号
- 用这两个标准化字段在 `candidates` 表中查重
- 命中则建立关联或执行合并
- 未命中则继续沿用当前 candidate

### 6.6 约束六：同一 Candidate 同一 JD 同一自然月只允许一条投递记录

通过 `application_window` 强制约束。

表达式含义：

```text
{candidate_id}_{job_description_id}_{YYYY-MM}
```

只要三者相同，该月内就不允许再创建第二条 Application。

这是数据库强约束，不依赖应用层 if 判断。

### 6.7 约束七：JD 是正式实体，不是自由字符串

系统最终不允许把 JD 仅仅当作一个自由字符串 `jd_id` 看待。

JD 必须：

- 有正式主表 `job_descriptions`
- 有正式平台索引表 `job_descriptions_platform_idx`
- 被 `candidates_applications.job_description_id` 正式引用

---

## 5. 目标表结构

下面给出目标 schema。这里写的是业务结构，不强调具体 ORM 写法。

### 7.1 `candidates`

```sql
CREATE TABLE candidates (
    id                 TEXT PRIMARY KEY NOT NULL,
    display_name       TEXT NOT NULL,
    normalized_phone   TEXT UNIQUE,
    normalized_wechat  TEXT UNIQUE,
    extra_contact      TEXT NOT NULL DEFAULT '{}',
    merged_from_ids    TEXT NOT NULL DEFAULT '[]',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
```

#### 字段语义

- `id`
  - 候选人主键
  - 表示“人”的 ID
- `display_name`
  - 当前展示名称
  - 可更新
  - 不作为唯一键
- `normalized_phone`
  - 标准化手机号
  - 推荐 E.164 格式，如 `+8613800138000`
- `normalized_wechat`
  - 标准化微信号
  - 用于跨平台候选人自动关联
- `extra_contact`
  - JSON
  - 用于保存邮箱、LinkedIn profile、Telegram、备注联系方式等
- `merged_from_ids`
  - JSON 数组
  - 保存被合并进当前 candidate 的历史 candidate.id
  - 用于审计和回溯

### 7.2 `candidates_platform_idx`

```sql
CREATE TABLE candidates_platform_idx (
    id                    TEXT PRIMARY KEY NOT NULL,
    candidate_id          TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    platform              TEXT NOT NULL,
    platform_candidate_id TEXT NOT NULL,
    profile_url           TEXT,
    raw_profile           TEXT NOT NULL DEFAULT '{}',
    first_seen_at         TEXT NOT NULL,
    last_seen_at          TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(platform, platform_candidate_id)
);
```

#### 字段语义

- `candidate_id`
  - 这个平台身份对应的候选人主实体
- `platform`
  - 平台标识，如 `zhipin` / `linkedin` / `intranet`
- `platform_candidate_id`
  - 平台上的候选人唯一 ID
  - 在没有联系方式前，这是平台内唯一识别依据
- `profile_url`
  - 平台主页链接
- `raw_profile`
  - 原始抓取画像 JSON
  - 用于审计、追溯、重新解析
- `first_seen_at` / `last_seen_at`
  - 首次发现 / 最近同步时间

### 7.3 `job_descriptions`

```sql
CREATE TABLE job_descriptions (
    id            TEXT PRIMARY KEY NOT NULL,
    title         TEXT NOT NULL,
    department    TEXT,
    location      TEXT,
    headcount     INTEGER NOT NULL DEFAULT 1,
    salary_min    INTEGER,
    salary_max    INTEGER,
    description   TEXT,
    requirements  TEXT,
    status        TEXT NOT NULL DEFAULT 'active',
    source        TEXT NOT NULL DEFAULT 'manual',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
```

#### 字段语义

- `title`
  - 岗位名称
- `department`
  - 部门
- `location`
  - 工作地点
- `headcount`
  - HC 数量
- `salary_min` / `salary_max`
  - 薪资区间
- `description`
  - 职位描述正文
- `requirements`
  - 任职要求正文
- `status`
  - 推荐取值：`draft` / `active` / `paused` / `closed`
- `source`
  - 该 JD 主来源：`manual` / `intranet` / `zhipin`

### 7.4 `job_descriptions_platform_idx`

```sql
CREATE TABLE job_descriptions_platform_idx (
    id              TEXT PRIMARY KEY NOT NULL,
    job_id          TEXT NOT NULL REFERENCES job_descriptions(id) ON DELETE CASCADE,
    platform        TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    external_url    TEXT,
    sync_status     TEXT NOT NULL DEFAULT 'synced',
    sync_metadata   TEXT NOT NULL DEFAULT '{}',
    last_synced_at  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(platform, external_id)
);
```

#### 字段语义

- `job_id`
  - 关联到主 JD
- `platform`
  - 来源平台，如 `intranet` / `zhipin`
- `external_id`
  - 外部平台的 JD ID
- `external_url`
  - 外部平台上的 JD 页面地址
- `sync_status`
  - 推荐取值：`synced` / `pending` / `failed`
- `sync_metadata`
  - 原始同步快照

### 7.5 `candidates_applications`

```sql
CREATE TABLE candidates_applications (
    id                    TEXT PRIMARY KEY NOT NULL,
    candidate_id          TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    platform              TEXT NOT NULL,
    platform_candidate_id TEXT,
    job_description_id    TEXT NOT NULL REFERENCES job_descriptions(id),
    application_window    TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'discovered',
    current_status        TEXT NOT NULL DEFAULT 'discovered',
    current_stage_key     TEXT,
    deepest_milestone     TEXT,
    contact_info          TEXT NOT NULL DEFAULT '{}',
    state_snapshot        TEXT NOT NULL DEFAULT '{}',
    resume_path           TEXT,
    online_resume_text    TEXT,
    ai_scores             TEXT NOT NULL DEFAULT '{}',
    ai_reasoning          TEXT,
    cooldown_until        TEXT,
    last_contacted_at     TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(application_window)
);
```

#### 字段语义

- `candidate_id`
  - 关联到候选人实体（人）
- `platform`
  - 本次投递来自哪个平台
- `platform_candidate_id`
  - 本次投递在该平台上的候选人 ID 快照
- `job_description_id`
  - 本次投递对应哪个 JD
- `application_window`
  - 同 candidate + 同 JD + 同自然月的唯一键
- `status`
  - 兼容业务整体状态摘要字段
  - 最终应与 `current_status` 保持同义或可被弱化
- `current_status`
  - 状态机当前节点
- `current_stage_key`
  - 当前阶段 key
- `deepest_milestone`
  - 当前已达到的最深漏斗里程碑
- `contact_info`
  - 当前投递实例下可见的联系方式快照
  - Candidate 主表保存的是人的稳定联系方式；这里是本次投递维度的使用快照
- `state_snapshot`
  - 本次投递的状态机快照
- `resume_path` / `online_resume_text`
  - 与本次投递相关的简历材料
- `ai_scores` / `ai_reasoning`
  - 与本次投递相关的 AI 评估结果
- `cooldown_until`
  - 本次投递级别的冷却截止时间
- `last_contacted_at`
  - 本次投递最后一次联系时间

---

## 6. 状态机、聊天、看板的挂载原则

这是本规范里最重要的挂载原则。

### 8.1 状态机挂 `candidates_applications`

状态机推进、合法流转校验、里程碑推进，全部围绕 `candidates_applications.id`。

最终形态应当是：

- `candidate_application_transitions`（建议目标命名）挂 `candidate_application_id`
- 不是挂 `candidate_id`

### 8.2 聊天记录挂 `candidates_applications`

聊天主体是一次投递，不是一个人。

因此最终推荐形态：

- `candidate_application_messages`
- 或至少 `communication_logs` 中外键应是 `candidate_application_id`

不能最终停留在“聊天挂 candidate（人）”的结构上。

### 8.3 会话上下文挂 `candidates_applications`

CandidateSession 也应该围绕投递实例，而不是围绕人。

因为：

- 同一个人对不同 JD 的上下文完全不同
- 同一个人在不同平台的聊天上下文也不同

最终推荐：

- `candidate_application_sessions`
- 或 `candidate_sessions` 外键改为 `candidate_application_id`

### 8.4 漏斗和状态看板按 `candidates_applications` 统计

所有漏斗、状态链、列表页、聊天入口，都以 Application 为基础查询对象。

**不是按去重 Candidate 统计。**

---

## 7. Agent 的目标写入路径

下面定义的是 Agent 在最终模型下的标准写入流程。

### 9.1 Agent 发现候选人

输入信息通常包括：

- `platform`
- `platform_candidate_id`
- `profile_url`
- `display_name`
- 候选人主页原始信息
- 目标 `job_description_id`

标准流程：

1. 在 `candidates_platform_idx` 中查 `(platform, platform_candidate_id)`
2. 若命中：
   - 取出 `candidate_id`
   - 更新 `last_seen_at`
   - 更新 `raw_profile`
3. 若未命中：
   - 创建 `candidates`
   - 创建 `candidates_platform_idx`
4. 生成 `application_window`
5. 查询是否已存在相同 `application_window` 的 `candidates_applications`
6. 若不存在：
   - 新建 `candidates_applications`
   - `current_status = discovered`
   - `deepest_milestone = M01`

### 9.2 `application_window` 的生成规则

推荐：

```text
{candidate_id}_{job_description_id}_{YYYY-MM}
```

示例：

```text
cand_001_jd_045_2026-04
```

这表示：

- 同一个 candidate
- 同一个 JD
- 同一个自然月

只能存在一条 application。

### 9.3 Agent 推进状态机

所有状态机推进统一作用于 `candidates_applications`：

- 更新 `current_status`
- 更新 `deepest_milestone`
- 更新 `state_snapshot`
- 写状态历史

Agent 不直接改 Candidate（人）的主信息，除非：

- 新发现了手机号
- 新发现了微信号
- 新发现了要合并的平台身份

### 9.4 Agent 写入聊天消息

Agent 所有发送 / 接收的消息，都写入当前 `candidates_applications` 对应的消息表。

消息写入主体不是 Candidate（人），而是 CandidateApplication（投递）。

### 9.5 Agent 写入联系方式

当 Agent 从聊天中拿到手机号或微信时：

1. 标准化联系方式
2. 尝试更新 `candidates`
3. 执行碰撞检测
4. 若命中已有 candidate，则建立或合并 Candidate 层关联
5. 不合并 Application，仅让多个 Application 指向同一个 Candidate

---

## 8. 联系方式与跨平台关联规则

### 10.1 原则

- 没拿到联系方式前，不做跨平台自动合并
- 拿到稳定联系方式后，再建立 Candidate 层统一身份
- 合并的是 Candidate，不是 Application

### 10.2 手机号标准化

系统应统一存储为 E.164 格式：

- `13800138000` → `+8613800138000`
- 已带国家码则保留
- 无法标准化则不写入 `normalized_phone`

### 10.3 微信号标准化

建议规则：

- 去首尾空格
- 统一大小写策略（推荐 lower）
- 去明显的显示前缀（若平台有）

### 10.4 合并规则

若候选人 A 和候选人 B 被判断为同一人：

- 两者的 `candidates_platform_idx` 都归到主 `candidates.id`
- 所有 `candidates_applications.candidate_id` 也指向主 candidate
- `merged_from_ids` 记录被并入的旧 ID
- 不合并投递记录，不合并聊天记录，不合并状态机历史

### 10.5 为什么不合并 Application

因为 Application 是一次业务动作实例：

- 不同 JD 是不同投递
- 同平台不同时间是不同投递
- 不同平台同一 JD 在同月若被拒绝创建，则根本不会出现第二条记录
- 已存在的两条历史 Application，即使最后归属同一 Candidate，也仍然是两次独立投递过程

---

## 9. JD 同步规则

系统应支持至少两个来源：

- 公司内网服务
- BOSS 平台

### 11.1 内网同步

内网是强结构化来源。推荐行为：

1. 调内网服务接口拉取 JD 列表
2. 用 `job_descriptions_platform_idx(platform='intranet', external_id=...)` 进行匹配
3. 命中则更新主 JD
4. 未命中则创建新 JD 和平台索引

### 11.2 BOSS 同步

BOSS 通过 browser-mcp 或平台接口抓取。

推荐行为：

1. 获取平台 JD ID
2. 查 `job_descriptions_platform_idx(platform='zhipin', external_id=...)`
3. 若命中，则更新平台索引和同步快照
4. 若未命中，则：
   - 尝试按 `title + department + location` 做高置信匹配
   - 高置信时可挂到已有 JD
   - 否则创建新 JD

### 11.3 单 JD 多平台关联

同一个 JD 可以在多个平台都有发布。

正确结构是：

- `job_descriptions` 一条
- `job_descriptions_platform_idx` 多条

也就是说，平台只是索引，不是主实体。

---

## 10. 目标读取路径

### 10.1 候选人看板

候选人看板的基础查询对象是：

- `candidates_applications`

筛选项可包括：

- `job_description_id`
- `platform`
- `current_status`
- `deepest_milestone`
- `last_contacted_at`

### 10.2 漏斗看板

漏斗看板按 `candidates_applications.deepest_milestone` 与状态历史统计。

### 10.3 状态看板

状态看板按 `candidates_applications.current_status` 统计。

### 10.4 聊天窗口

聊天窗口按 `candidate_application_id` 读取：

- 消息流
- 状态历史
- 当前投递上下文
- 当前 JD 信息

### 10.5 Candidate 聚合视图

如果需要展示“这个人的总览页”，应由聚合查询构成：

- 主体：`candidates`
- 平台身份：`candidates_platform_idx`
- 所有投递：`candidates_applications`

它是聚合页，不是状态机主视图。

---

## 11. 数据库约束与索引

这是最终必须由数据库保证的约束。

### 11.1 候选人平台唯一性

```sql
UNIQUE(platform, platform_candidate_id)
```

作用对象：`candidates_platform_idx`

### 11.2 JD 平台唯一性

```sql
UNIQUE(platform, external_id)
```

作用对象：`job_descriptions_platform_idx`

### 11.3 同月投递唯一性

```sql
UNIQUE(application_window)
```

作用对象：`candidates_applications`

### 11.4 联系方式唯一性

```sql
UNIQUE(normalized_phone)
UNIQUE(normalized_wechat)
```

作用对象：`candidates`

### 11.5 推荐索引

#### `candidates`

- `normalized_phone`
- `normalized_wechat`

#### `candidates_platform_idx`

- `candidate_id`
- `platform`
- `(platform, platform_candidate_id)` 唯一索引

#### `job_descriptions`

- `status`
- `source`

#### `job_descriptions_platform_idx`

- `job_id`
- `sync_status`
- `(platform, external_id)` 唯一索引

#### `candidates_applications`

- `candidate_id`
- `job_description_id`
- `current_status`
- `deepest_milestone`
- `last_contacted_at`
- `application_window` 唯一索引

---

## 12. 非目标与边界

本规范明确不覆盖以下内容：

### 12.1 不讨论迁移

不讨论旧数据如何迁移到新模型。

### 12.2 不讨论兼容

不讨论旧 API、旧表、旧字段如何兼容或共存。

### 12.3 不讨论 UI 临时适配

不讨论看板页面如何临时桥接老数据结构。

### 12.4 不讨论当前代码命名是否已经对齐

这里只定义最终应该是什么，不以当前实现为约束。

---

## 13. 结论

最终系统应当遵循下面这组稳定规则：

1. `candidates` 表示一个人
2. `candidates_platform_idx` 表示这个人在各平台的身份
3. `candidates_applications` 表示这个人的一次投递记录
4. 状态机、聊天、看板、漏斗全部围绕 `candidates_applications`
5. `job_descriptions` 是正式 JD 实体，不是自由字符串
6. 没有联系方式前不跨平台合并
7. 有手机号 / 微信号后再自动建立 Candidate 层关联
8. 同一 Candidate、同一 JD、同一自然月只允许一条 Application

这组规则就是后续代码实现、API 设计、Agent 写入路径和看板查询路径的统一目标。
