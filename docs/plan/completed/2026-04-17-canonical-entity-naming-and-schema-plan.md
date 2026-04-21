# Canonical Entity Naming and Schema Cleanup Implementation Plan

> Status: completed
> Supersedes: docs/plan/archive/2026-04-16-candidate-target-model-unification.md
> Superseded by: -
> Distilled into: docs/specs/2026-04-20-candidate-target-data-model-spec.md
> Last reviewed against code: 2026-04-20
> Historical source path: docs/superpowers/plans/2026-04-17-canonical-entity-naming-and-schema-plan.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify candidate person / candidate application / job description naming, table structure, keys, timestamps, and application-scoped auxiliary tables across the backend, API, shared types, and desktop client, while keeping the current functional behavior intact.

**Architecture:** This cleanup is a strict canonicalization pass over the already-running target-model implementation. The system should use one naming system end-to-end: explicit business IDs (`candidate_person_id`, `candidate_application_id`, `job_description_id`), auto-increment technical primary keys (`id`), and second-level int64 timestamps for all time fields. Workflow data remains application-scoped; person records remain identity-scoped. `candidate_application_assessments` stores stage-bound assessment outcomes from both AI and human evaluators, while `candidate_application_scorecards` stores rubric/dimension-style scoring payloads only.

**Tech Stack:** FastAPI, SQLAlchemy ORM, SQLite migrations, Pydantic schemas, TypeScript desktop client, shared protocol types.

**Status Snapshot (2026-04-17):**
- 已完成 canonical schema 收口：application-centric API / shared types / desktop surface 统一消费 `applicationId` / `personId` / `jobDescriptionId`。
- 已完成双 ID 规则落地：数据库内部保留技术主键 `id`，代码层与 API 层统一使用 business id，不再把内部主键作为业务主语透出。
- 已完成时间字段统一：canonical schema、API read model 与前端消费统一按秒级 int64 处理时间字段。
- 最终验证已通过：`python3 -m pytest services/backend/tests -q`、`npm --workspace packages/shared run build`、`npm run desktop:typecheck`。

---

## 文件结构

### 规范与计划文件
- Modify: `docs/superpowers/specs/2026-04-16-candidate-target-data-model-spec.md`
  - 用最新统一命名和表结构更新 target spec
- Modify: `docs/superpowers/plans/2026-04-16-candidate-target-model-unification.md`
  - 标记这次 canonical cleanup 的完成项或后续链接
- Create: `docs/superpowers/plans/2026-04-17-canonical-entity-naming-and-schema-plan.md`
  - 当前这份实施计划

### 后端 schema / ORM / repository
- Modify: `services/backend/src/recruit_agent/db/migrations.py`
- Modify: `services/backend/src/recruit_agent/models/domain.py`
- Modify: `services/backend/src/recruit_agent/repositories/domain.py`
- Modify: `services/backend/src/recruit_agent/schemas/domain.py`
- Modify: `services/backend/src/recruit_agent/services/application_window.py`
- Modify: `services/backend/src/recruit_agent/services/application_subjects.py`
- Modify: `services/backend/src/recruit_agent/services/candidate_identity.py`

### API / runtime / service layer
- Modify: `services/backend/src/recruit_agent/api/routers/candidate_persons.py`
- Modify: `services/backend/src/recruit_agent/api/routers/candidate_applications.py`
- Modify: `services/backend/src/recruit_agent/api/routers/job_descriptions.py`
- Modify: `services/backend/src/recruit_agent/api/routers/recruit_agent.py`
- Modify: `services/backend/src/recruit_agent/api/routers/agent.py`
- Modify: `services/backend/src/recruit_agent/services/agent.py`
- Modify: `services/backend/src/recruit_agent/services/state_machine.py`
- Modify: `services/backend/src/recruit_agent/services/runtime_control.py`
- Modify: `services/backend/src/recruit_agent/services/dashboard.py`
- Modify: `services/backend/src/recruit_agent/services/context_assembler.py`
- Modify: `services/backend/src/recruit_agent/services/recruit_agent.py`
- Modify: `services/backend/src/recruit_agent/playbooks/engine.py`

### 前端类型 / API / 页面
- Modify: `apps/desktop/src/lib/types.ts`
- Modify: `apps/desktop/src/lib/api.ts`
- Modify: `apps/desktop/src/features/kanban-shared/kanbanUtils.ts`
- Modify: `apps/desktop/src/features/funnel-kanban/FunnelKanbanView.tsx`
- Modify: `apps/desktop/src/features/status-kanban/StatusKanbanView.tsx`
- Modify: `apps/desktop/src/features/candidates/CandidatesKanbanView.tsx`
- Modify: `apps/desktop/src/features/workspace/DesktopWorkspace.tsx`
- Modify: `apps/desktop/src/features/recruit-agent/RecruitAgentView.tsx`
- Modify: `apps/desktop/src/features/evolution/EvolutionView.tsx`
- Modify: `apps/desktop/src/features/dashboard/DashboardView.tsx`
- Modify: `apps/desktop/src/features/workbench/WorkbenchView.tsx`

### 测试
- Modify: `services/backend/tests/test_api_candidates.py`
- Modify: `services/backend/tests/test_api_recruit_agent.py`
- Modify: `services/backend/tests/test_api_playbook_runtime.py`
- Modify: `services/backend/tests/test_autonomy_loop.py`
- Modify: `services/backend/tests/test_db_migrations.py`
- Create or modify: `services/backend/tests/test_canonical_schema_naming.py`
- Create or modify: `services/backend/tests/test_application_assessment_boundaries.py`

---

## 目标结构与边界（Codex 必须先按这个执行）

### 一、核心主表命名

必须统一成：

- `candidate_persons`
- `candidate_person_platform_idx`
- `candidate_applications`
- `job_descriptions`
- `job_description_platform_idx`

### 二、主键与业务 ID 规则

每张表同时包含：

1. 技术主键：

```sql
id BIGINT PRIMARY KEY AUTO_INCREMENT
```

2. 显式业务主语 ID：

- `candidate_person_id`
- `candidate_person_platform_idx_id`
- `candidate_application_id`
- `candidate_application_assessment_id`
- `candidate_application_scorecard_id`
- `job_description_id`
- `job_description_platform_idx_id`

### 三、时间字段规则

所有时间类字段必须统一为：

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
- `last_synced_at`

### 四、`candidate_persons` 必须只保留人的稳定信息

必须保留：
- `id`
- `candidate_person_id`
- `display_name`
- `normalized_phone`
- `normalized_wechat`
- `extra_contact`
- `merged_from_candidate_person_ids`
- `created_at`
- `updated_at`

必须删除或移出：
- `platform`
- `platform_candidate_id`
- `resume_path`
- `online_resume_text`
- `current_status`
- `current_stage_key`
- `deepest_milestone`
- `ai_scores`
- `ai_reasoning`
- `cooldown_until`
- `last_contacted_at`

### 五、`candidate_person_platform_idx` 字段必须明确使用 `platform_candidate_person_id`

必须包含：
- `candidate_person_platform_idx_id`
- `candidate_person_id`
- `platform`
- `platform_candidate_person_id`
- `profile_url`
- `raw_profile`
- `first_seen_at`
- `last_seen_at`
- `created_at`
- `updated_at`

### 六、`candidate_applications` 字段规则

必须包含：
- `candidate_application_id`
- `candidate_person_id`
- `job_description_id`
- `source_platform`
- `source_platform_candidate_person_id`
- `application_window`
- `current_status`
- `current_stage_key`
- `deepest_milestone`
- `contact_snapshot`
- `resume_snapshot`
- `cooldown_until`
- `last_contacted_at`
- `active_assessment_summary`
- `application_metadata`
- `created_at`
- `updated_at`

明确不要再保留：
- `status`

### 七、assessment 与 scorecard 的边界

#### `candidate_application_assessments`
这张表表示“某次评估动作的结论记录”。

它必须能承载：
- AI 在线评估
- AI 线下评估
- 人工初筛评估
- 面试评价
- 同阶段多次重评

必须包含：
- `candidate_application_assessment_id`
- `candidate_application_id`
- `assessment_actor_type`（至少支持 `ai` / `human`）
- `assessment_stage_key`
- `assessment_stage_label`
- `assessment_round`
- `decision`
- `score`
- `summary`
- `criteria_snapshot`
- `evidence_snapshot`
- `result_payload`
- `assessment_metadata`
- `assessed_at`
- `created_at`
- `updated_at`

#### `candidate_application_scorecards`
这张表只表达“结构化打分卡”。

它必须只承载：
- rubric / 维度分数
- score total
- verdict
- 证据引用

它不负责承载：
- 面试流程安排
- 评估轮次管理
- 一次完整评估动作的多来源结论

必须包含：
- `candidate_application_scorecard_id`
- `candidate_application_id`
- `assessment_stage_key`
- `scorecard_source`
- `rubric_version`
- `score_total`
- `verdict`
- `summary`
- `dimension_scores`
- `evidence_snapshot`
- `scorecard_metadata`
- `created_at`
- `updated_at`

### 八、消息层规则

`candidate_application_messages` 只保留：
- 原始消息
- 少量核心结构化信号

不要做过度提取。

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

---

### Task 1：先用测试钉住 canonical 表名、字段名、时间类型

**当前状态：** canonical 物理表名、双 ID 规则和 int64 时间字段已按计划落地，以下步骤保留为已完成收口记录。

**Files:**
- Modify: `services/backend/tests/test_db_migrations.py`
- Create: `services/backend/tests/test_canonical_schema_naming.py`
- Modify: `services/backend/src/recruit_agent/db/migrations.py`
- Modify: `services/backend/src/recruit_agent/models/domain.py`

- [x] **Step 1: 写失败测试，明确最终表名和关键字段名**

新增测试，至少断言这些表必须存在：

```python
def test_canonical_core_tables_exist():
    expected_tables = {
        "candidate_persons",
        "candidate_person_platform_idx",
        "candidate_applications",
        "job_descriptions",
        "job_description_platform_idx",
        "candidate_application_assessments",
        "candidate_application_scorecards",
        "candidate_application_messages",
        "candidate_application_transitions",
    }
```

并且断言这些字段必须存在：

```python
def test_canonical_business_ids_and_timestamp_columns_exist():
    # candidate_persons.candidate_person_id
    # candidate_applications.candidate_application_id
    # candidate_person_platform_idx.platform_candidate_person_id
    # candidate_applications.source_platform_candidate_person_id
    # created_at/updated_at are BIGINT-like columns
```

- [x] **Step 2: 跑测试确认失败**

Run:

```bash
python3 -m pytest services/backend/tests/test_canonical_schema_naming.py -q
```

Expected: FAIL。

- [x] **Step 3: 重写 migration，统一表名/字段名/时间类型**

在 `services/backend/src/recruit_agent/db/migrations.py` 中：
- 把现有混用表名统一到本计划的 canonical 名称
- 所有业务主语列改成显式命名
- 所有时间列改成秒级 int64 存储
- 每张表都保留：

```sql
id BIGINT PRIMARY KEY AUTOINCREMENT
```

- [x] **Step 4: 重写 ORM 模型字段，严格跟随 canonical 名称**

在 `services/backend/src/recruit_agent/models/domain.py` 中：
- 所有主表与附属表字段名必须严格对齐本计划
- 不要保留 `candidate_id` 这种在主线里语义模糊的列名
- `Candidate` 类如继续保留，也必须只表达 `candidate_persons`

- [x] **Step 5: 跑测试确认通过**

Run:

```bash
python3 -m pytest services/backend/tests/test_db_migrations.py services/backend/tests/test_canonical_schema_naming.py -q
```

Expected: PASS。

- [x] **Step 6: Commit**

```bash
git add services/backend/src/recruit_agent/db/migrations.py services/backend/src/recruit_agent/models/domain.py services/backend/tests/test_db_migrations.py services/backend/tests/test_canonical_schema_naming.py
git commit -m "feat: canonicalize core entity table and field names"
```

### Task 2：重构 `candidate_persons` 与平台身份索引，删除非身份字段

**当前状态：** `candidate_persons`、`candidate_person_platform_idx` 与相关 person/JD surface 已按 canonical schema 收口，测试链路已完成验证。

**Files:**
- Modify: `services/backend/src/recruit_agent/models/domain.py`
- Modify: `services/backend/src/recruit_agent/repositories/domain.py`
- Modify: `services/backend/src/recruit_agent/schemas/domain.py`
- Modify: `services/backend/src/recruit_agent/api/routers/candidate_persons.py`
- Test: `services/backend/tests/test_api_candidates.py`
- Test: `services/backend/tests/test_api_recruit_agent.py`

- [x] **Step 1: 写失败测试，明确 person 表只保留身份层字段**

新增测试断言：

```python
def test_candidate_person_does_not_expose_workflow_fields(...):
    ...
```

必须检查 `/api/candidate-persons` 返回中不再出现：
- `current_status`
- `current_stage_key`
- `deepest_milestone`
- `ai_scores`
- `ai_reasoning`
- `cooldown_until`
- `last_contacted_at`

- [x] **Step 2: 跑测试确认失败**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_candidates.py -q
```

Expected: FAIL。

- [x] **Step 3: 重构 `candidate_persons` 模型和 schema**

必须保留：
- `candidate_person_id`
- `display_name`
- `normalized_phone`
- `normalized_wechat`
- `extra_contact`
- `merged_from_candidate_person_ids`
- `created_at`
- `updated_at`

必须删除 workflow 字段。

- [x] **Step 4: 重构 `candidate_person_platform_idx` 字段名**

把：
- `platform_candidate_id`

统一改成：
- `platform_candidate_person_id`

对应同步修改：
- ORM
- repository
- schema
- route payload
- 测试断言

- [x] **Step 5: 跑测试确认通过**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_candidates.py services/backend/tests/test_api_recruit_agent.py -q
```

Expected: PASS。

- [x] **Step 6: Commit**

```bash
git add services/backend/src/recruit_agent/models/domain.py services/backend/src/recruit_agent/repositories/domain.py services/backend/src/recruit_agent/schemas/domain.py services/backend/src/recruit_agent/api/routers/candidate_persons.py services/backend/tests/test_api_candidates.py services/backend/tests/test_api_recruit_agent.py
git commit -m "feat: restrict candidate persons to identity fields only"
```

### Task 3：重构 `candidate_applications` 为唯一流程主锚点

**当前状态：** `/api/candidate-applications` CRUD 与 application-centric thread / entries / transitions surface 已按 canonical schema 完成闭环，`application_window` 也已走服务端 canonical 生成与校验。

**Files:**
- Modify: `services/backend/src/recruit_agent/models/domain.py`
- Modify: `services/backend/src/recruit_agent/repositories/domain.py`
- Modify: `services/backend/src/recruit_agent/schemas/domain.py`
- Modify: `services/backend/src/recruit_agent/services/application_window.py`
- Modify: `services/backend/src/recruit_agent/api/routers/candidate_applications.py`
- Test: `services/backend/tests/test_api_recruit_agent.py`

- [x] **Step 1: 写失败测试，明确 application 字段集**

新增测试断言 `/api/candidate-applications` 返回中必须包含：
- `applicationId`
- `personId`
- `jobDescriptionId`
- `sourcePlatform`
- `sourcePlatformPersonId`
- `applicationWindow`
- `currentStatus`
- `currentStageKey`
- `deepestMilestone`
- `contactSnapshot`
- `resumeSnapshot`
- `cooldownUntil`
- `lastContactedAt`
- `activeAssessmentSummary`
- `applicationMetadata`

并断言不再包含：
- `status`

- [x] **Step 2: 跑测试确认失败**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py -k "candidate_application" -q
```

Expected: FAIL。

- [x] **Step 3: 重构 application 模型字段名**

统一成：
- `candidate_application_id`
- `candidate_person_id`
- `job_description_id`
- `source_platform`
- `source_platform_candidate_person_id`
- `application_window`
- `current_status`
- `current_stage_key`
- `deepest_milestone`
- `contact_snapshot`
- `resume_snapshot`
- `cooldown_until`
- `last_contacted_at`
- `active_assessment_summary`
- `application_metadata`

- [x] **Step 4: 修改 `application_window` canonical 生成逻辑**

在 `services/backend/src/recruit_agent/services/application_window.py` 中，把主语参数改清楚：

```python
def make_application_window(candidate_person_id: str, job_description_id: str, at: int) -> str:
    ...
```

并且 repository create/update 必须强校验 canonical window。

- [x] **Step 5: 跑测试确认通过**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py -k "candidate_application" -q
```

Expected: PASS。

- [x] **Step 6: Commit**

```bash
git add services/backend/src/recruit_agent/models/domain.py services/backend/src/recruit_agent/repositories/domain.py services/backend/src/recruit_agent/schemas/domain.py services/backend/src/recruit_agent/services/application_window.py services/backend/src/recruit_agent/api/routers/candidate_applications.py services/backend/tests/test_api_recruit_agent.py
git commit -m "feat: canonicalize candidate application schema"
```

### Task 4：明确 assessment vs scorecard 的边界并重构两张表

**当前状态：** application-scoped assessments / scorecards surface 已按目标边界完成收口，独立验证与 API 验证均已通过。

**Files:**
- Modify: `services/backend/src/recruit_agent/models/domain.py`
- Modify: `services/backend/src/recruit_agent/repositories/domain.py`
- Modify: `services/backend/src/recruit_agent/schemas/domain.py`
- Modify: `services/backend/src/recruit_agent/api/routers/candidate_applications.py`
- Test: `services/backend/tests/test_application_assessment_boundaries.py`
- Test: `services/backend/tests/test_api_recruit_agent.py`

- [x] **Step 1: 写失败测试，明确两张表的边界**

新增测试至少覆盖：

```python
def test_application_assessment_accepts_ai_and_human_stage_bound_results(...):
    ...

def test_application_scorecard_only_stores_rubric_style_scoring_payload(...):
    ...
```

断言 `candidate_application_assessments` 必须支持：
- `assessment_actor_type` = `ai` / `human`
- `assessment_stage_key`
- `assessment_stage_label`
- `assessment_round`
- `decision`
- `score`
- `summary`
- `criteria_snapshot`
- `evidence_snapshot`
- `result_payload`

断言 `candidate_application_scorecards` 只保留：
- rubric/dimension scoring
- score total
- verdict
- evidence snapshot
- scorecard metadata

- [x] **Step 2: 跑测试确认失败**

Run:

```bash
python3 -m pytest services/backend/tests/test_application_assessment_boundaries.py -q
```

Expected: FAIL。

- [x] **Step 3: 重命名并重构两张表**

在 ORM/migration/schema/repository 中，把现有：
- `application_assessments`
- `application_scorecards`

统一重构成：
- `candidate_application_assessments`
- `candidate_application_scorecards`

字段严格按本计划口径落地。

- [x] **Step 4: 让 application routes 按新边界读写**

在 `services/backend/src/recruit_agent/api/routers/candidate_applications.py`：
- assessment routes 返回 stage-bound evaluation records
- scorecard routes 返回 rubric-scoring records
- 不要让两条 surface 混着表达同一种东西

- [x] **Step 5: 跑测试确认通过**

Run:

```bash
python3 -m pytest services/backend/tests/test_application_assessment_boundaries.py services/backend/tests/test_api_recruit_agent.py -q
```

Expected: PASS。

- [x] **Step 6: Commit**

```bash
git add services/backend/src/recruit_agent/models/domain.py services/backend/src/recruit_agent/repositories/domain.py services/backend/src/recruit_agent/schemas/domain.py services/backend/src/recruit_agent/api/routers/candidate_applications.py services/backend/tests/test_application_assessment_boundaries.py services/backend/tests/test_api_recruit_agent.py
git commit -m "feat: clarify application assessment and scorecard boundaries"
```

### Task 5：把消息 / transitions / resume artifacts / assignments / sync records 统一成 canonical 附属表

**当前状态：** application-centric API surface 与 runtime 写入路径已全部切到 canonical 附属表，物理表名、显式业务 ID 与 int64 时间字段均已验证通过。

**Files:**
- Modify: `services/backend/src/recruit_agent/models/domain.py`
- Modify: `services/backend/src/recruit_agent/repositories/domain.py`
- Modify: `services/backend/src/recruit_agent/schemas/domain.py`
- Modify: `services/backend/src/recruit_agent/api/routers/candidate_applications.py`
- Modify: `services/backend/src/recruit_agent/services/agent.py`
- Modify: `services/backend/src/recruit_agent/services/state_machine.py`
- Test: `services/backend/tests/test_api_playbook_runtime.py`
- Test: `services/backend/tests/test_api_recruit_agent.py`

- [x] **Step 1: 写失败测试，确认附属表全部 application-scoped 且字段名 canonical**

必须覆盖：
- `candidate_application_messages`
- `candidate_application_transitions`
- `candidate_application_resume_artifacts`
- `candidate_application_assignments`
- `candidate_application_sync_records`

要求检查：
- 所有外键都叫 `candidate_application_id`
- 所有业务主语 ID 都显式命名
- 所有时间字段都是 int64 秒级语义

- [x] **Step 2: 跑测试确认失败**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_playbook_runtime.py services/backend/tests/test_api_recruit_agent.py -q
```

Expected: FAIL。

- [x] **Step 3: 统一附属表命名和字段**

把现有：
- `application_sessions`
- `application_communication_logs`
- `application_status_transitions`
- `resume_artifacts`
- `application_assignments`
- `application_sync_records`

统一重构到本计划的 canonical 名称，并统一显式业务 id / 时间字段。

- [x] **Step 4: 同步修改 runtime 写入路径**

在：
- `services/backend/src/recruit_agent/services/agent.py`
- `services/backend/src/recruit_agent/services/state_machine.py`

把消息、流转、简历制品、分配、sync 记录的写入改到 canonical 表/字段上。

- [x] **Step 5: 跑测试确认通过**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_playbook_runtime.py services/backend/tests/test_api_recruit_agent.py -q
```

Expected: PASS。  
Status: 已确认通过。

- [x] **Step 6: Commit**

```bash
git add services/backend/src/recruit_agent/models/domain.py services/backend/src/recruit_agent/repositories/domain.py services/backend/src/recruit_agent/schemas/domain.py services/backend/src/recruit_agent/api/routers/candidate_applications.py services/backend/src/recruit_agent/services/agent.py services/backend/src/recruit_agent/services/state_machine.py services/backend/tests/test_api_playbook_runtime.py services/backend/tests/test_api_recruit_agent.py
git commit -m "feat: canonicalize application-scoped auxiliary tables"
```

### Task 6：同步 API / 前端字段命名，彻底去掉混合主语

**当前状态：** shared types、API normalizer 与桌面端页面消费已全部切到 `applicationId` / `personId` / `jobDescriptionId`，完整 typecheck 已通过。

**Files:**
- Modify: `apps/desktop/src/lib/types.ts`
- Modify: `apps/desktop/src/lib/api.ts`
- Modify: `apps/desktop/src/features/kanban-shared/kanbanUtils.ts`
- Modify: `apps/desktop/src/features/funnel-kanban/FunnelKanbanView.tsx`
- Modify: `apps/desktop/src/features/status-kanban/StatusKanbanView.tsx`
- Modify: `apps/desktop/src/features/candidates/CandidatesKanbanView.tsx`
- Modify: `apps/desktop/src/features/workspace/DesktopWorkspace.tsx`
- Modify: `apps/desktop/src/features/recruit-agent/RecruitAgentView.tsx`
- Modify: `apps/desktop/src/features/evolution/EvolutionView.tsx`
- Modify: `apps/desktop/src/features/dashboard/DashboardView.tsx`
- Modify: `apps/desktop/src/features/workbench/WorkbenchView.tsx`

- [x] **Step 1: 写失败前的类型检查目标**

定义前端必须统一用：
- `personId`
- `applicationId`
- `jobDescriptionId`

不要继续依赖：
- 模糊 `id`
- `candidateId`（如果实际指 application）
- 旧扁平 candidate 字段

- [x] **Step 2: 跑 typecheck，确认切换前后断点**

Run:

```bash
npm run desktop:typecheck
```

Expected: 在中途字段切换时先看到 breakage。

- [x] **Step 3: 改客户端类型与 normalizer**

在：
- `apps/desktop/src/lib/types.ts`
- `apps/desktop/src/lib/api.ts`

统一 application/person/JD 三套字段命名。

- [x] **Step 4: 改页面层消费字段**

更新：
- funnel
- status
- candidate workspace
- dashboard
- evolution
- recruit-agent
- workbench

确保都消费 canonical 字段。

- [x] **Step 5: 跑 typecheck 确认通过**

Run:

```bash
npm run desktop:typecheck
```

Expected: PASS。

- [x] **Step 6: Commit**

```bash
git add apps/desktop/src/lib/types.ts apps/desktop/src/lib/api.ts apps/desktop/src/features/kanban-shared/kanbanUtils.ts apps/desktop/src/features/funnel-kanban/FunnelKanbanView.tsx apps/desktop/src/features/status-kanban/StatusKanbanView.tsx apps/desktop/src/features/candidates/CandidatesKanbanView.tsx apps/desktop/src/features/workspace/DesktopWorkspace.tsx apps/desktop/src/features/recruit-agent/RecruitAgentView.tsx apps/desktop/src/features/evolution/EvolutionView.tsx apps/desktop/src/features/dashboard/DashboardView.tsx apps/desktop/src/features/workbench/WorkbenchView.tsx
git commit -m "feat: canonicalize application-centric frontend naming"
```

### Task 7：更新 target spec 与最终验收

**Files:**
- Modify: `docs/superpowers/specs/2026-04-16-candidate-target-data-model-spec.md`
- Modify: `docs/superpowers/plans/2026-04-16-candidate-target-model-unification.md`

**当前状态：** target spec 与相关 plan 已回写到 canonical 目标态，并补充旧 unification plan 与本计划之间的状态关联；最终全量验证已完成。

- [x] **Step 1: 把最新 canonical 表名 / 字段名 / assessment-scorecard 边界写回 target spec**

必须更新：
- `candidate_persons`
- `candidate_person_platform_idx`
- `candidate_applications`
- `candidate_application_assessments`
- `candidate_application_scorecards`
- 所有时间字段统一秒级 int64
- 所有表同时拥有技术主键 `id` 与显式业务主语 ID

- [x] **Step 2: 在 plan 中补充验收结果与完成标准**

在 `docs/superpowers/plans/2026-04-16-candidate-target-model-unification.md` 中，把新的 canonical 清理计划引用进去或标注完成条件。

- [x] **Step 3: 跑最终验证**

Run:

```bash
python3 -m pytest services/backend/tests -q && npm --workspace packages/shared run build && npm run desktop:typecheck
```

Expected: PASS。

Status: 已确认 `python3 -m pytest services/backend/tests -q`、`npm --workspace packages/shared run build` 与 `npm run desktop:typecheck` 全量通过。

- [x] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-16-candidate-target-data-model-spec.md docs/superpowers/plans/2026-04-16-candidate-target-model-unification.md docs/superpowers/plans/2026-04-17-canonical-entity-naming-and-schema-plan.md
git commit -m "docs: finalize canonical entity naming and schema plan"
```

---

## Self-review

### Spec coverage
- 已覆盖最新要求的 canonical 表名。
- 已覆盖技术主键 + 显式业务 ID 双轨规则。
- 已覆盖全部时间字段统一为秒级 int64。
- 已明确 assessment 与 scorecard 的职责边界。
- 已要求附属流程表全部 application-scoped。
- 已覆盖 API / 前端字段命名统一。

### Placeholder scan
- 没有 TBD/TODO 占位。
- 每个任务都包含具体文件、测试命令和预期结果。
- 没有把未定义的方法或结构偷渡到后面任务里。

### Type consistency
- 全文统一使用：
  - `candidate_persons`
  - `candidate_person_platform_idx`
  - `candidate_applications`
  - `candidate_application_assessments`
  - `candidate_application_scorecards`
  - `job_descriptions`
  - `job_description_platform_idx`
- 主语 ID 统一使用：
  - `candidate_person_id`
  - `candidate_application_id`
  - `job_description_id`
