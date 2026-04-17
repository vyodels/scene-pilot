# 候选人目标模型统一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前混合的候选人数据结构统一为单一目标模型规范，并直接按目标模型实施后端/数据层改造，让系统正式把“人、平台身份、投递实例、JD”作为独立一等实体处理，不保留迁移/兼容层。

**Architecture:** 只保留一份规范文件：`docs/superpowers/specs/2026-04-16-candidate-target-data-model-spec.md`。target spec 继续保持“纯目标态”，不回写实施现状、差距分析或交付笔记；这些实施性内容统一写在本 plan 中。由于数据库没有历史正式数据，这次直接按目标 schema 落地，不做兼容或回填。核心架构变化是把当前混合语义拆成 candidate person、candidate application、job description 三套一等实体，并把状态机历史、聊天、会话、评估、评分卡、评审决定、简历制品、同步记录全部重新挂到 `candidate_application_id` 上。

**Tech Stack:** FastAPI、SQLAlchemy ORM、SQLite migrations、Pydantic schemas、TypeScript 桌面端、shared protocol types。

---

## 文件结构

### 规范与规划文件
- 修改：`docs/superpowers/plans/2026-04-16-candidate-target-model-unification.md`
  - 承载实施边界、交付阶段、验收标准与执行顺序
- 保持不动：`docs/superpowers/specs/2026-04-16-candidate-target-data-model-spec.md`
  - 继续作为唯一 target spec，不写入实施现状和迁移笔记

### 后端 schema 与持久化层
- 修改：`services/backend/src/scene_pilot/db/migrations.py`
  - 新增目标表，并把外键锚点改到 application；不加入迁移/回填逻辑
- 修改：`services/backend/src/scene_pilot/models/domain.py`
  - 新增 `CandidatePlatformIdx`、`JobDescription`、`JobDescriptionPlatformIdx`、`CandidateApplication`
  - 把依赖模型中的 `candidate_id` 迁到 `candidate_application_id`
- 修改：`services/backend/src/scene_pilot/repositories/domain.py`
  - 按“人 / application”拆仓储职责
- 修改：`services/backend/src/scene_pilot/schemas/domain.py`
  - 新增人 / application / JD schemas，并更新读写模型

### 后端服务与 API 层
- 修改：`services/backend/src/scene_pilot/services/state_machine.py`
  - 把状态流转对象从 person 切到 application
- 修改：`services/backend/src/scene_pilot/services/agent.py`
  - discovery、状态流转、聊天落库、简历采集、重试、回退、skill draft 写入全部改为基于 application
- 修改：`services/backend/src/scene_pilot/services/context_assembler.py`
  - 上下文读取改为 application session / messages
- 修改：`services/backend/src/scene_pilot/services/dashboard.py`
  - 漏斗 / 状态 / autonomy 计数改为基于 application
- 删除：`services/backend/src/scene_pilot/api/routers/candidates.py`
  - 不保留混合语义的 `/api/candidates`
- 新增：`services/backend/src/scene_pilot/api/routers/candidate_persons.py`
  - person CRUD surface，主键统一用 `personId`
- 新增：`services/backend/src/scene_pilot/api/routers/candidate_applications.py`
  - application CRUD / thread / transitions / workflow surface，主键统一用 `applicationId`
- 新增：`services/backend/src/scene_pilot/api/routers/job_descriptions.py`
  - JD CRUD surface，主键统一用 `jobDescriptionId`
- 修改：`services/backend/src/scene_pilot/api/routers/recruit_agent.py`
  - candidate thread、transitions、resume artifacts、assessments、assignments、scorecards、review decisions、sync records 必须基于 application；必要时把旧 recruit-agent surface 收敛到 application 读模型
- 修改：`services/backend/src/scene_pilot/api/routers/state_machine.py`
  - 确保状态机读写继续与 application 绑定后的 transitions 一致

### 前端数据 / client 层
- 修改：`apps/desktop/src/lib/types.ts`
  - 新增面向 person / application / JD 的客户端类型
- 修改：`apps/desktop/src/lib/api.ts`
  - 候选人相关 API client 改为读取 application-centric payload
- 修改：`apps/desktop/src/features/kanban-shared/kanbanUtils.ts`
  - 视图模型从 applications 构建，而不是 person rows
- 修改：`apps/desktop/src/features/funnel-kanban/FunnelKanbanView.tsx`
- 修改：`apps/desktop/src/features/status-kanban/StatusKanbanView.tsx`
- 修改：`apps/desktop/src/features/candidates/CandidatesKanbanView.tsx`
- 修改：`apps/desktop/src/features/workspace/DesktopWorkspace.tsx`
  - 候选人页面和 summary 一律以 application 为主行对象

### 测试
- 修改：`services/backend/tests/test_api_recruit_agent.py`
- 修改：`services/backend/tests/test_api_playbook_runtime.py`
- 修改：`services/backend/tests/test_autonomy_loop.py`
- 修改：`services/backend/tests/test_candidate_progression_selector.py`
- 按需新增或修改聚焦 repository/schema/API 行为的测试到 `services/backend/tests/`

## 实施边界

- 不改写 target spec，所有“当前现状 / 差距 / 执行阶段 / 验收”只写在 plan。
- 不做兼容层，不保留混合语义的 `/api/candidates`。
- API 主语一步到位拆清：
  - `/api/candidate-persons`
  - `/api/candidate-applications`
  - `/api/job-descriptions`
- 所有流程、聊天、状态历史、看板明细接口统一使用 `applicationId`。
- 只有候选人主实体管理接口才使用 `personId`。
- `/api/dashboard` 可以继续保留聚合视图，但其候选人主列表、漏斗、状态链涉及的行对象必须是 application-centric。
- 不要求历史数据迁移、回填或旧字段桥接。

---

### Task 1：收敛文档边界，保持 target spec 纯粹

**Files:**
- 修改：`docs/superpowers/plans/2026-04-16-candidate-target-model-unification.md`
- 验证：`docs/superpowers/specs/2026-04-16-candidate-target-data-model-spec.md`

- [x] **Step 1: 删除 plan 中所有“把实施现状回写到 target spec”的步骤**

从本 plan 中删掉这类要求：

```text
把当前实现现状、差距摘要、交付阶段、验收清单补进 target spec
```

预期结果：target spec 保持纯目标态，实施性信息只存在于 plan。

- [x] **Step 2: 在 plan 中写清楚实施边界与验收**

至少明确：

- 不保留 `/api/candidates`
- 直接切 `person / application / JD` 三套主语
- 所有流程 / 聊天 / 状态历史 / 看板明细统一使用 `applicationId`
- `/api/dashboard` 继续保留聚合视图，但行对象必须 application-centric
- 不做兼容层、迁移回填或旧字段桥接

- [x] **Step 3: 验证 target spec 未被污染**

Run:

```bash
test -f docs/superpowers/specs/2026-04-16-candidate-target-data-model-spec.md
```

Expected: 命令成功退出。

- [x] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-04-16-candidate-target-model-unification.md
git commit -m "docs: refine candidate target model implementation plan"
```

### Task 2：新增 JD 和平台身份实体

**Files:**
- 修改：`services/backend/src/scene_pilot/db/migrations.py`
- 修改：`services/backend/src/scene_pilot/models/domain.py`
- 修改：`services/backend/src/scene_pilot/repositories/domain.py`
- 修改：`services/backend/src/scene_pilot/schemas/domain.py`
- 测试：`services/backend/tests/test_api_recruit_agent.py`

- [x] **Step 1: 先写失败测试，定义 JD 和平台身份的目标行为**

新增测试，至少覆盖：

```python
def test_can_create_job_description_and_platform_index(...):
    ...

def test_can_create_candidate_person_and_platform_identity(...):
    ...
```

断言要求：
- JD 实体可以创建和读取
- JD 平台索引对 `(platform, external_id)` 唯一
- person 实体可以独立存在，不依赖 application workflow
- candidate 平台索引对 `(platform, platform_candidate_id)` 唯一

- [x] **Step 2: 跑测试确认当前必然失败**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py -k "job_description or platform_identity" -q
```

Expected: FAIL，因为 schema/model/API 还不存在。

- [x] **Step 3: 在 migration 中增加三张目标表**

在 `services/backend/src/scene_pilot/db/migrations.py` 中新增 DDL：

```sql
job_descriptions
job_descriptions_platform_idx
candidates_platform_idx
```

字段按 canonical spec 严格落：
- `job_descriptions`：`id`, `title`, `department`, `location`, `headcount`, `salary_min`, `salary_max`, `description`, `requirements`, `status`, `source`, timestamps
- `job_descriptions_platform_idx`：`job_id`, `platform`, `external_id`, `external_url`, `sync_status`, `sync_metadata`, `last_synced_at`, timestamps, unique `(platform, external_id)`
- `candidates_platform_idx`：`candidate_id`, `platform`, `platform_candidate_id`, `profile_url`, `raw_profile`, `first_seen_at`, `last_seen_at`, timestamps, unique `(platform, platform_candidate_id)`

- [x] **Step 4: 在 ORM 模型中加入这三张表**

在 `services/backend/src/scene_pilot/models/domain.py` 增加：

```python
class CandidatePlatformIdx(Base, TimestampMixin):
    __tablename__ = "candidates_platform_idx"
    ...

class JobDescription(Base, TimestampMixin):
    __tablename__ = "job_descriptions"
    ...

class JobDescriptionPlatformIdx(Base, TimestampMixin):
    __tablename__ = "job_descriptions_platform_idx"
    ...
```

字段名必须与目标规范一致。

- [x] **Step 5: 加 repository 和 schema**

在 `services/backend/src/scene_pilot/repositories/domain.py` 与 `services/backend/src/scene_pilot/schemas/domain.py` 中补齐：
- `JobDescription`
- `JobDescriptionPlatformIdx`
- `CandidatePlatformIdx`

命名沿用现有 create/read/update 风格。

- [x] **Step 6: 加最小后端接口**

在 backend routing 层直接增加目标接口：

- `GET/POST /api/job-descriptions`
- `GET/PATCH /api/job-descriptions/{jobDescriptionId}`
- `GET/POST /api/candidate-persons`
- `GET/PATCH /api/candidate-persons/{personId}`

不新增兼容旧 `/api/candidates` 的桥接接口。

- [x] **Step 7: 跑测试确认通过**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py -k "job_description or platform_identity" -q
```

Expected: PASS.

- [x] **Step 8: Commit**

```bash
git add services/backend/src/scene_pilot/db/migrations.py services/backend/src/scene_pilot/models/domain.py services/backend/src/scene_pilot/repositories/domain.py services/backend/src/scene_pilot/schemas/domain.py services/backend/tests/test_api_recruit_agent.py
git commit -m "feat: add target jd and platform identity tables"
```

### Task 3：引入 `candidates_applications` 作为流程主锚点

**Files:**
- 修改：`services/backend/src/scene_pilot/db/migrations.py`
- 修改：`services/backend/src/scene_pilot/models/domain.py`
- 修改：`services/backend/src/scene_pilot/repositories/domain.py`
- 修改：`services/backend/src/scene_pilot/schemas/domain.py`
- 新增：`services/backend/src/scene_pilot/api/routers/candidate_applications.py`
- 测试：`services/backend/tests/test_api_recruit_agent.py`

- [x] **Step 1: 先写失败测试，定义 application 才是流程实体**

新增测试覆盖：

```python
def test_application_row_carries_status_machine_fields(...):
    ...

def test_application_window_is_unique_for_candidate_jd_month(...):
    ...
```

断言：
- `current_status`, `deepest_milestone`, `state_snapshot`, `cooldown_until`, `last_contacted_at` 都落在 application row 上
- `application_window` 唯一约束生效

- [x] **Step 2: 跑测试确认当前失败**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py -k "application_window or status_machine_fields" -q
```

Expected: FAIL。

- [x] **Step 3: 直接创建 `candidates_applications` 表**

在 `services/backend/src/scene_pilot/db/migrations.py` 中新增目标表：

```sql
id
candidate_id
platform
platform_candidate_id
job_description_id
application_window
status
current_status
current_stage_key
deepest_milestone
contact_info
state_snapshot
resume_path
online_resume_text
ai_scores
ai_reasoning
cooldown_until
last_contacted_at
created_at
updated_at
```

不要加入迁移/回填/兼容逻辑。

- [x] **Step 4: 增加 `CandidateApplication` 模型和仓储**

在 `services/backend/src/scene_pilot/models/domain.py` 加：

```python
class CandidateApplication(Base, TimestampMixin):
    __tablename__ = "candidates_applications"
    ...
```

在 `services/backend/src/scene_pilot/repositories/domain.py` 加：

```python
class CandidateApplicationRepository(BaseRepository[CandidateApplication]):
    ...
```

- [x] **Step 5: 补 application schemas，并新增 application CRUD / detail API**

在 `services/backend/src/scene_pilot/schemas/domain.py` 新增 application 的 read/create/update models；在 `services/backend/src/scene_pilot/api/routers/candidate_applications.py` 中提供至少这些接口：

- `GET /api/candidate-applications`
- `POST /api/candidate-applications`
- `GET /api/candidate-applications/{applicationId}`
- `PATCH /api/candidate-applications/{applicationId}`

- [x] **Step 6: 实现 `application_window` helper**

创建 helper，形式如下：

```python
def make_application_window(candidate_id: str, job_description_id: str, at: datetime) -> str:
    month = at.strftime("%Y-%m")
    return f"{candidate_id}_{job_description_id}_{month}"
```

- [x] **Step 7: 跑测试确认通过**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py -k "application_window or status_machine_fields" -q
```

Expected: PASS。

- [x] **Step 8: Commit**

```bash
git add services/backend/src/scene_pilot/db/migrations.py services/backend/src/scene_pilot/models/domain.py services/backend/src/scene_pilot/repositories/domain.py services/backend/src/scene_pilot/schemas/domain.py services/backend/src/scene_pilot/api/routers/candidate_applications.py services/backend/tests/test_api_recruit_agent.py
git commit -m "feat: add candidate application workflow anchor"
```

### Task 4：把 workflow/history/chat 表全部重挂到 `candidate_application_id`

**Files:**
- 修改：`services/backend/src/scene_pilot/models/domain.py`
- 修改：`services/backend/src/scene_pilot/repositories/domain.py`
- 修改：`services/backend/src/scene_pilot/schemas/domain.py`
- 修改：`services/backend/src/scene_pilot/api/routers/recruit_agent.py`
- 测试：`services/backend/tests/test_api_recruit_agent.py`
- 测试：`services/backend/tests/test_api_playbook_runtime.py`

- [x] **Step 1: 先写失败测试，定义所有流程记录都应该挂 application**

新增测试覆盖：

```python
def test_candidate_thread_is_bound_to_application(...):
    ...

def test_status_transitions_are_bound_to_application(...):
    ...

def test_resume_artifacts_and_assessments_are_bound_to_application(...):
    ...
```

必须覆盖：
- thread/session 按 application 查
- message logs 按 application 查
- transition history 按 application 查
- assessments / assignments / scorecards / review decisions / sync records 按 application 查

- [x] **Step 2: 跑测试确认失败**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py services/backend/tests/test_api_playbook_runtime.py -k "application" -q
```

Expected: FAIL。

- [x] **Step 3: 改 dependent SQLAlchemy models 的外键锚点**

在 `services/backend/src/scene_pilot/models/domain.py` 中，把下面这些模型里的 `candidate_id` FK 改为 `candidate_application_id`：
- `CandidateSession`
- `CommunicationLog`
- `CandidateStatusTransition`
- `CandidateAssessment`
- `CandidateAssignment`
- `ResumeArtifact`
- `CandidateScorecard`
- `CandidateReviewDecision`
- `TalentPoolSyncRecord`

如果确实有 person-level concern，才保留 person 绑定；workflow path 不允许继续挂 person。

- [x] **Step 4: 改 repositories，按 application 查询**

为受影响的 repository 增加或替换成：

```python
def by_application(self, candidate_application_id: str, ...):
    ...
```

不要让 workflow path 里继续使用面向 person 的查询 helper。

- [x] **Step 5: 改 schemas 和 thread 构建逻辑**

重构 `services/backend/src/scene_pilot/api/routers/recruit_agent.py` 中的 `_build_candidate_thread(...)` 和相关 endpoint，让它们全部基于 application ID 读写。

- [x] **Step 6: 跑测试确认通过**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py services/backend/tests/test_api_playbook_runtime.py -k "application" -q
```

Expected: PASS。

- [x] **Step 7: Commit**

```bash
git add services/backend/src/scene_pilot/models/domain.py services/backend/src/scene_pilot/repositories/domain.py services/backend/src/scene_pilot/schemas/domain.py services/backend/src/scene_pilot/api/routers/recruit_agent.py services/backend/tests/test_api_recruit_agent.py services/backend/tests/test_api_playbook_runtime.py
git commit -m "feat: bind workflow records to candidate applications"
```

### Task 5：把状态机、dashboard、autonomy、runtime 写入全部切到 application

**Files:**
- 修改：`services/backend/src/scene_pilot/services/state_machine.py`
- 修改：`services/backend/src/scene_pilot/services/dashboard.py`
- 修改：`services/backend/src/scene_pilot/services/agent.py`
- 修改：`services/backend/src/scene_pilot/services/context_assembler.py`
- 修改：`services/backend/src/scene_pilot/services/runtime_control.py`
- 测试：`services/backend/tests/test_autonomy_loop.py`
- 测试：`services/backend/tests/test_candidate_progression_selector.py`
- 测试：`services/backend/tests/test_api_playbook_runtime.py`

- [x] **Step 1: 先写失败测试，定义 runtime 也必须 application-centric**

新增测试：

```python
def test_state_machine_transition_updates_application_not_person(...):
    ...

def test_autonomy_selection_operates_on_applications(...):
    ...

def test_context_assembly_reads_application_session_and_messages(...):
    ...
```

- [x] **Step 2: 跑测试确认失败**

Run:

```bash
python3 -m pytest services/backend/tests/test_autonomy_loop.py services/backend/tests/test_candidate_progression_selector.py services/backend/tests/test_api_playbook_runtime.py -q
```

Expected: FAIL。

- [x] **Step 3: 重构状态机服务，改为操作 `CandidateApplication`**

在 `services/backend/src/scene_pilot/services/state_machine.py` 中，把状态变更、里程碑推进、快照更新、transition history 写入全部改成针对 application row。

- [x] **Step 4: 重构 agent runtime 写入路径**

在 `services/backend/src/scene_pilot/services/agent.py` 中更新：
- discovery 写入
- 正常状态推进
- rollback 写入
- retry 写入
- outbound/inbound message 写入
- skill draft / evolution artifact 关联字段

要求：runtime 只在 identity/contact 层才回写 person。

- [x] **Step 5: 重构 dashboard / selector 计数，统一按 application**

在 `services/backend/src/scene_pilot/services/dashboard.py` 和相关 selector 服务中，把漏斗/状态/autonomy 计数全部改成基于 application，而不是 person。

- [x] **Step 6: 重构 context/session 组装，改为 application sessions**

在 `services/backend/src/scene_pilot/services/context_assembler.py` 中，读取 application-scoped 的 recent messages、transitions、session context。

- [x] **Step 7: 跑测试确认通过**

Run:

```bash
python3 -m pytest services/backend/tests/test_autonomy_loop.py services/backend/tests/test_candidate_progression_selector.py services/backend/tests/test_api_playbook_runtime.py -q
```

Expected: PASS。

- [x] **Step 8: Commit**

```bash
git add services/backend/src/scene_pilot/services/state_machine.py services/backend/src/scene_pilot/services/dashboard.py services/backend/src/scene_pilot/services/agent.py services/backend/src/scene_pilot/services/context_assembler.py services/backend/src/scene_pilot/services/runtime_control.py services/backend/tests/test_autonomy_loop.py services/backend/tests/test_candidate_progression_selector.py services/backend/tests/test_api_playbook_runtime.py
git commit -m "feat: run workflow and autonomy on candidate applications"
```

### Task 6：补联系方式驱动的 Candidate 关联 / 合并逻辑

**Files:**
- 修改：`services/backend/src/scene_pilot/services/state_machine.py`
- 修改：`services/backend/src/scene_pilot/services/agent.py`
- 修改：`services/backend/src/scene_pilot/repositories/domain.py`
- 修改：`services/backend/src/scene_pilot/api/routers/recruit_agent.py`
- 测试：`services/backend/tests/test_api_recruit_agent.py`

- [x] **Step 1: 先写失败测试，定义联系人获取后的关联行为**

新增测试：

```python
def test_contact_acquisition_links_application_to_existing_candidate_person(...):
    ...

def test_same_person_keeps_multiple_applications_after_merge(...):
    ...
```

断言：
- 没拿到稳定联系方式前，不发生 merge
- 命中 normalized phone / wechat 后，建立关联或 merge
- merge 后 applications 仍然独立存在

- [x] **Step 2: 跑测试确认失败**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py -k "contact_acquisition or merge" -q
```

Expected: FAIL。

- [x] **Step 3: 新建联系方式标准化 helper**

创建小工具模块，例如：

```python
# services/backend/src/scene_pilot/services/contact_identity.py

def normalize_phone(raw: str) -> str | None:
    ...

def normalize_wechat(raw: str) -> str | None:
    ...
```

规则严格按 canonical spec 落。

- [x] **Step 4: 实现 link / merge 逻辑**

补 repository/service 逻辑，实现：
- 联系方式标准化查重
- 命中已有 person 时，platform identity 归到已有 person
- 如需 merge，更新 `merged_from_ids`
- 不合并 application，不合并其聊天/历史

- [x] **Step 5: 跑测试确认通过**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py -k "contact_acquisition or merge" -q
```

Expected: PASS。

- [x] **Step 6: Commit**

```bash
git add services/backend/src/scene_pilot/services/contact_identity.py services/backend/src/scene_pilot/services/state_machine.py services/backend/src/scene_pilot/services/agent.py services/backend/src/scene_pilot/repositories/domain.py services/backend/src/scene_pilot/api/routers/recruit_agent.py services/backend/tests/test_api_recruit_agent.py
git commit -m "feat: link candidate identities after contact acquisition"
```

### Task 7：桌面端彻底切到 application-centric 读取

**Files:**
- 修改：`apps/desktop/src/lib/types.ts`
- 修改：`apps/desktop/src/lib/api.ts`
- 修改：`apps/desktop/src/features/kanban-shared/kanbanUtils.ts`
- 修改：`apps/desktop/src/features/funnel-kanban/FunnelKanbanView.tsx`
- 修改：`apps/desktop/src/features/status-kanban/StatusKanbanView.tsx`
- 修改：`apps/desktop/src/features/candidates/CandidatesKanbanView.tsx`
- 修改：`apps/desktop/src/features/workspace/DesktopWorkspace.tsx`

- [x] **Step 1: 先写/改失败前的类型预期**

让桌面端类型先表达清楚：候选人看板行对象应该是 application record，并带 person/JD summary，而不是继续假装主行对象是 person。

- [x] **Step 2: 跑 `desktop:typecheck`，确认改动前的断裂点**

Run:

```bash
npm run desktop:typecheck
```

Expected: 在后端/client 类型切换过程中先看到 breakage。

- [x] **Step 3: 改客户端类型**

在 `apps/desktop/src/lib/types.ts` 中定义 application-centric row type，至少包含：
- application ID
- person summary
- JD summary
- 当前 workflow state
- 当前 thread/history payloads

- [x] **Step 4: 改 API client normalization**

在 `apps/desktop/src/lib/api.ts` 中把候选人相关 payload 统一 normalize 成 application-centric 结构，不再把主 pipeline row 当 person。

- [x] **Step 5: 改 kanban view-model builder**

在 `apps/desktop/src/features/kanban-shared/kanbanUtils.ts` 中，把 `buildCandidateViewModels(...)` 改成基于 applications + nested person/JD 字段构建。

- [x] **Step 6: 改 funnel / status / workspace 面**

更新：
- `FunnelKanbanView.tsx`
- `StatusKanbanView.tsx`
- `CandidatesKanbanView.tsx`
- `DesktopWorkspace.tsx`

让这些页面全部按 application-centric shape 读取。

- [x] **Step 7: 跑 `desktop:typecheck` 确认通过**

Run:

```bash
npm run desktop:typecheck
```

Expected: PASS。

- [x] **Step 8: Commit**

```bash
git add apps/desktop/src/lib/types.ts apps/desktop/src/lib/api.ts apps/desktop/src/features/kanban-shared/kanbanUtils.ts apps/desktop/src/features/funnel-kanban/FunnelKanbanView.tsx apps/desktop/src/features/status-kanban/StatusKanbanView.tsx apps/desktop/src/features/candidates/CandidatesKanbanView.tsx apps/desktop/src/features/workspace/DesktopWorkspace.tsx
git commit -m "feat: switch desktop boards to application-centric data"
```

### Task 8：全量验证并清掉旧模型假设

**Files:**
- 修改：Tasks 2-7 里所有触及文件
- 测试：`services/backend/tests/**/*.py`

- [x] **Step 1: 跑 focused backend verification suite**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_recruit_agent.py -q
```

Expected: PASS。

- [x] **Step 2: 跑 runtime/autonomy verification suite**

Run:

```bash
python3 -m pytest services/backend/tests/test_api_playbook_runtime.py services/backend/tests/test_autonomy_loop.py services/backend/tests/test_candidate_progression_selector.py -q
```

Expected: PASS。

- [x] **Step 3: 跑整个 backend test suite**

Run:

```bash
python3 -m pytest services/backend/tests -q
```

Expected: PASS。

- [x] **Step 4: 跑 shared + desktop 验证**

Run:

```bash
npm --workspace packages/shared run build && npm run desktop:typecheck
```

Expected: PASS。

- [x] **Step 5: 搜索并清理残余的旧模型混合语义**

搜索这些关键词，清理仍把 pipeline row 当成混合 Candidate 的旧假设：

```bash
grep -R "platform_candidate_id\|jd_id\|candidate_id" services/backend/src/scene_pilot apps/desktop/src
```

Expected: 只剩有意保留的使用点；workflow path 不应再把单个混合 `Candidate` row 当成同时代表“人”和“投递”。

- [x] **Step 6: Commit**

```bash
git add services/backend/src/scene_pilot apps/desktop/src packages/shared/src docs/superpowers/specs/2026-04-16-candidate-target-data-model-spec.md
git commit -m "feat: align runtime and boards with target candidate data model"
```

---

## Self-review

### Spec coverage
- 已覆盖文档收敛。
- 已覆盖 JD 实体、人实体、平台身份实体、application workflow 实体。
- 已覆盖状态机 / 聊天 / 历史 / 评估 / review / sync records 重挂 application。
- 已覆盖 agent runtime 写路径与桌面端读路径改造。
- 已覆盖联系方式驱动的 Candidate 关联/合并。
- 已明确排除迁移、回填、兼容层。

### Placeholder scan
- 无 TODO/TBD 占位。
- 每个任务都给了明确文件和具体动作。
- 每一阶段都附了命令和预期结果。

### Type consistency
- 全文统一使用：
  - `candidates` = 人
  - `candidates_platform_idx` = 人的平台身份
  - `candidates_applications` = 投递实例
  - `job_descriptions` = JD
  - `job_descriptions_platform_idx` = JD 平台索引
- 后续任务统一使用 `candidate_application_id` 作为 workflow foreign key。
