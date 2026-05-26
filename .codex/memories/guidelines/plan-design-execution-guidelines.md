---
name: plan-design-execution-guidelines
description: 用户级大型 plan 设计与实施规范，确保 plan 可落地、语义稳定、事实源唯一、旧逻辑不回流、完成审计可靠。
load_when: 设计、审查、执行或接手大型 plan、migration、multi-phase goal、跨模块重构、生产化闭环、架构收口、legacy 退役、agent/subagent 协作任务，或需要确保 plan 指哪打哪时加载。
not_for: 很小的一次性修改、纯问答、单文件低风险修复、无需计划的探索，或用户当前明确要求临时跳过 plan 设计/治理的场景。
---

# Plan Design And Execution Guidelines

本规范定义大型 plan 如何设计、拆解、执行和验收。它只保留 plan 层规则：

- goal 的通用执行合同见 `generic-goal-contract.md`。
- 实现批次、集中 review、批量修复、focused checks 和回归节奏见 `development-execution-guidelines.md`。

目标：让 plan 足够清晰、可落地、可审计；执行时不偏离目标、不保留不该兼容的旧逻辑、不把局部 green 误报为完成。

## Core Contract

大型 plan 必须回答：

- 要解决什么问题，当前真实状态是什么。
- 目标主链路是什么，哪些边界不可绕过。
- 哪些语义、状态、事实源、入口是 canonical。
- 哪些旧逻辑必须迁移、围栏、降级或删除。
- 如何拆成少数可独立验收的大块执行单元。
- plan 的 implementation-readiness evidence：关键文件/模块、接口、数据流、依赖、风险边界，以及适用的命令、操作入口和验证入口是否已核对。
- 如何验证实现完整、方向正确、风险可控。
- 什么证据才允许声明 phase/slice/goal complete。

如果 plan 只列任务，不定义完成证据和防偏差规则，先补 plan，再扩大实现。不能把 plan-level 自洽当成可落地；没有 evidence-backed implementation readiness 的部分必须显式列为 discovery / validation，不得伪装成可直接执行的步骤。

## Multi-Agent Adversarial Plan Gate

大型 plan、技术方案设计、产品方案设计、migration、multi-phase goal、架构收口或高风险执行方案，在进入实施或声明设计通过前，默认必须启动多个 agent 做对抗式设计和 review。

最低硬门槛：所有非小范围 plan、task、implementation 或 document-governance change，在进入执行、声明通过、提交为 accepted/passed/done/complete，或交付给用户前，如果 subagent 工具可用，必须至少启动一个独立 subagent reviewer 做事实驱动的对抗式审查。本地双角色 review 可以作为预审，但不能替代独立 subagent review。

该 gate 的目标不是制造更多流程，而是防止单一视角凭空假设、遗漏关键约束、把表面计划误判为可执行方案。

### Scope

适用本文件 `load_when` 覆盖的计划和方案类工作，以及会改变执行规范、完成语义、review 规则、subagent 协作方式或用户级 memory 的治理变更。小型一次性修改、纯问答、单文件低风险修复、无需计划的探索，或用户当前明确要求跳过 plan 治理 / 禁止 subagent / 采用其他节奏的场景，不强制启动多 agent。

以下默认不是小范围：正式用户级 plan/design doc、跨阶段或多 task 工作、跨模块实现、runtime/scheduler/worker/CLI/API/schema/repository/service/state machine/data integrity/accounting/reconciliation/promotion/admission/gate/live execution/risk control 变更、影响资金/价格/份额/fee/PnL/ROI/coverage/evidence/权限/安全/secret/外部副作用/生产写入/交易行为的变更，以及用户明确要求 subagent review、对抗式 review、平级 review、argue、coordinator 或 complex-task execution 的任务。

小范围例外只限局部拼写、格式、注释、无行为变化 README 修正，或单文件低风险修复且不改变 architecture、runtime、business semantics、state machine、DB/API contract、安全边界、资金/交易/验证证据或用户级规范。

如果 subagent 工具不可用、没有空闲 reviewer slot、预算或上下文不足、无法安全隔离任务，不能假装完成多 agent review。必须先释放已完成 subagent 并重试启动独立 reviewer；仍不可用时，把结论标为 `blocked_subagent_review_unavailable`、`not_assessed`、`blocked`、`draft`、`fail_pending_fix`、`pending_independent_re_review` 或请求用户决策，并说明缺失的审查能力。不可用时不能把本地双角色 review 当作替代，不能将该 task、plan、implementation 或 governance change 标记、提交或 commit 为 `passed` / `accepted` / `accepted_for_execution` / `done` / `complete`，除非用户在当前任务中明确临时降级这条硬门槛。

### Required Roles

默认至少需要：

- 一个 coordinator：负责定义问题、事实源、success criteria、审查边界、分歧仲裁和最终验收。
- 两个或以上独立 reviewer / agent：从不同角度对 plan、技术方案或产品方案做只读对抗式 review。

方案设计阶段的 reviewer 默认只读。涉及写入时，遵守 `development-execution-guidelines.md` 的 coordinator/subagent 规则，避免多个 agent 写同一组文件。

### Fact Standard

所有 review finding、反对意见和通过结论都必须基于可核验事实。可用事实包括：

- 当前用户明确指令。
- 项目 agent entry、spec、architecture、API/schema/design contract。
- 当前 plan 的 goal、success criteria、hard constraints、canonical sources、forbidden paths。
- 代码、测试、运行日志、迁移、接口、schema、配置、文档行号。
- 可复现的外部事实或明确引用的来源。

禁止把猜测、偏好、未核验记忆、历史 handoff、Markdown/report/JSON export、截图或“看起来应该是”当作阻断事实。无法核验的内容只能标为 `assumption`、`question` 或 `needs evidence`，不能直接用来否决方案。

### Review Dimensions

多 agent 对抗式 review 至少覆盖：

- 需求和 success criteria 是否完整、可验收。
- 技术方案是否闭合主链路，而不是 wrapper、rename、report 或局部 gate。
- 产品方案是否有清晰用户路径、状态变化、边界条件和非目标。
- canonical source、single source、状态语义、legacy 退役是否清楚。
- 安全、权限、资金/外部副作用、数据、并发、幂等、回滚或补偿是否可控。
- 测试、负向扫描、completion evidence、上线/回滚/运营边界是否足够。
- 成本、复杂度、上下文负担是否与目标风险匹配。

### Review Ledger

对抗式 review 必须留下压缩后的 ledger，便于接手和审计：

- reviewer / agent
- finding
- evidence
- severity：`blocker` / `high` / `medium` / `low`
- scope：`in-scope blocker` / `in-scope fix` / `deferred follow-up` / `out-of-scope` / `question`
- decision
- owner
- status

ledger 是审查记录，不是产品事实源、任务状态源或验证证据。最终仍必须回到 goal、spec、代码和 tests 核验。

### Consensus Semantics

“多方一致通过”只表示：

- 所有 reviewer 的 in-scope finding，不论 severity 是 `blocker`、`high`、`medium` 还是 `low`，都已修复并复审、被事实驳回、明确移出当前 scope，或由用户在当前任务中显式接受为 deferred/out-of-scope。
- 所有 success criteria、hard constraints、canonical sources、acceptance、stop conditions、completion evidence 都有对应证据或明确缺口。
- 剩余分歧已按 closure rule 分类，不再阻断当前 scope。

一致通过不是多数票，也不是所有偏好建议都必须采纳。若 reviewer 分歧，coordinator 必须回到 authority hierarchy、canonical source、success criteria 和 evidence 仲裁；不能用资历、猜测或投票压过事实。

Severity 不是跳过权限。`low` 和“小问题”必须进入同一个 closure 机制：凡属于当前 scope 的 finding 都要修复并复审，或被事实驳回；只有明确不属于当前 scope、或用户在当前任务中显式接受为 deferred/out-of-scope，才能保留为非完成项。不得把“non-blocking residual”“future hardening”“可以之后做”当作 goal complete 的默认豁免。

默认轮次为：

```text
initial adversarial review -> plan/design fix -> focused re-review
```

升级给用户决策的 in-scope finding，只有在用户裁决后被关闭、事实驳回、明确移出当前 scope，或由用户显式接受为 deferred/out-of-scope，才算不再阻断通过。

最多进行两轮集中复审。两轮后仍无法基于事实达成一致时，停止扩张，输出 `blocked`，并在原因里标明 `decision-needed`：列出阻断事实、分歧点、已验证证据、需要用户裁决的问题和可选方案。

有未关闭的 in-scope finding 时，不论 severity 是 `blocker`、`high`、`medium` 还是 `low`，都不得声明 plan、技术方案、产品方案、phase、slice 或 goal `complete`。

## Design Checklist

### Metadata

长期 plan 必须带 metadata：`name`、`description`、`load_when`、`not_for`。先读 metadata，匹配任务后再读正文。

### Goal Section

plan 的 Goal 部分应引用 `generic-goal-contract.md`，并补充当前任务的：

- objective
- scope / non-goals
- success criteria
- hard constraints
- canonical sources
- forbidden paths
- stop conditions
- completion evidence

Goal 驱动最终完成；plan 设计完成路径；execution batch 控制实现节奏。不要把 goal 拆成小 finding，也不要让执行者猜完成标准。

### Problem Inventory

先列问题集合和当前状态，避免只修表面症状。至少区分：

- 已有 reusable 能力。
- 只是 wrapper / compatibility / diagnostic 的临时能力。
- 缺失的生产 workflow。
- 已退役、不能恢复、不能继续扩展的旧路径。
- 文档、service catalog、README 等可能误导实现的漂移点。

### Authority Hierarchy

明确权威优先级。默认：

1. 当前用户明确指令。
2. 项目 agent entry、spec、architecture、API/schema/design contract。
3. 当前 plan 的 goal、target chain、hard boundaries。
4. 代码中已有 canonical service/model/repository/schema。
5. 历史 plan、handoff、report、Markdown、JSON export、截图或人工笔记。

第 5 类通常只能作为线索，不能作为产品事实源、状态源、验证证据或恢复来源，除非 plan 明确把它定义为一次性迁移输入。

### Semantic Dictionary

提前固定业务语义，避免实施时来回改口径。写清：

- 核心实体是什么，不是什么。
- 状态字段分别表达什么。
- 哪些裸词禁止混用，例如含义不明的 `status`。
- 同名旧对象是 canonical、legacy、adapter、diagnostic、read model，还是 migration source。
- 必要的否定关系，例如 `snapshot != source of truth`、`trigger != fact`。

语义必须落到模型、schema、接口、输出和测试上；只写在文档里不算完成。

### Canonical Target Chain

画出目标主链路，明确每一步：

- 输入和输出。
- 谁创建权威事实或状态。
- 谁只是 read model/cache/report/view。
- 谁可以写，谁只能读。
- 哪个步骤必须先发生。
- 哪些失败必须 fail closed。
- 哪些信息必须携带 source refs、hash、trace/correlation id、time boundary、version、idempotency key。

`canonical` 是通用概念，表示当前 goal 下唯一权威主路径，不绑定具体技术栈。

### Single Source Rules

同一业务含义只能有一个 canonical 字段、表、模型、入口或服务边界。

plan 必须列出：

- canonical source
- allowed read model
- allowed adapter / compatibility wrapper
- forbidden source
- migration source
- deletion or downgrade point

兼容层允许短期存在，但必须只调用 canonical service，不重复实现规则，并有退出条件和负向扫描防回流。

### Anti-Surface Matrix

核心能力应有反表面实现矩阵：

```text
能力 | 表面实现 | 可接受实现 | 验收检查
```

用于防止只改名字、加 wrapper、写 report、让 gate fail closed，却没有闭合真实能力。任一核心能力只达到“表面实现”，不得声明对应阶段完成。

### Work Breakdown

执行单元可以叫 Phase、Stage、Wave、Milestone、Epic、Track、Capability、Slice、Workstream、Deliverable。不要依赖名称，依赖边界。

合格执行单元必须：

- 追溯到一个或多个 success criteria。
- 有可独立验收的主链路或能力边界。
- 有明确输入、输出、状态变化和依赖。
- 有文件/模块范围。
- 有 implementation-readiness evidence，而不是 plan-level confidence：关键文件/模块/API/数据流/依赖/风险边界，以及适用的命令、操作入口和验证入口已核对；规划时不可知或未核对项已转成明确的 discovery / validation 步骤。
- 有 acceptance、focused tests、negative scans。
- 有旧路径处理策略。

单个 rename、字段、wrapper、report、测试断言、compat alias、局部清理，不应作为独立完成单元。

### Critical Path

优先放在前面的通常是：

- 语义和命名收口。
- canonical source / methodology alignment。
- schema / typed model / repository contract。
- gate / admission / fail-closed boundary。
- cursor / lease / idempotency / progress tracking。
- evidence refs/hash。
- migration inventory。

会扩大 fanout、自动执行、批量变更、真实资金、外部副作用、用户可见发布或不可逆迁移的能力，必须放在 gate、权限、幂等、限流、回滚或人工确认边界之后。

### Task Card Ledger

超大 plan 默认使用 task card ledger 管理进度。卡片让进度可见，但不能替代验收；`done` 只能在证据闭合后标记。

每张卡只保留必要信息：

- `id`
- `goal_ref`
- `outcome`
- `non_goals`
- `depends_on`
- `owned_files_or_modules`
- `canonical_sources`
- `forbidden_paths`
- `implementation_readiness_evidence`
- `discovery_validation_items`
- `acceptance`
- `tests`
- `negative_scans`
- `review_focus`
- `done_evidence`
- `audit_decision`
- `status`
- `blocker_reason`

状态语义：

- `todo`：未开始。
- `doing`：实现中。
- `review`：已到可审查状态，但未验收。
- `fixing`：review/audit finding 批量修复中。
- `blocked`：有阻断项，必须写 `blocker_reason`。
- `deferred`：明确延期，必须写影响和解除条件。
- `done`：acceptance、tests/scans、review findings、completion audit 都闭合。

任务卡是协作工具，不是完成证据。小 finding 挂在卡片下批量修复，不要无限细分成主卡。不要把“实现了大部分”“测试局部通过”“review 还会持续发现问题”的卡标为 done；这种卡应保持 `review`、`fixing`、`blocked` 或 `partial/deferred` 结论。

Closure rule：review/audit 新发现必须分类为 in-scope blocker、in-scope fix、deferred follow-up、out-of-scope。所有 in-scope finding 都必须关闭后才能声明当前卡完成；severity 只影响优先级和风险说明，不决定是否可以跳过。已 done 的卡只有在发现其完成证据不成立、scope 内问题未关闭、或用户要求重新审计时才 reopen。

### Context Control

大型 plan 必须支持上下文压缩和接手：

- 当前 goal 摘要。
- success criteria 状态：done / partial / missing / deferred。
- 当前 phase/slice/card。
- task card ledger：每张卡的 status、done_evidence、audit_decision。
- canonical chain。
- hard boundaries。
- open blockers。
- decisions log。
- adversarial review ledger。
- compatibility ledger。
- verification ledger。
- next actions。

handoff 只是协作记录；接手者必须回到 goal、plan、spec 和代码核验。

## Execution Checklist

### Start With Reconciliation

执行前先只读核对：

- goal contract、plan metadata、hard boundaries、当前 phase/slice/card。
- 当前代码是否仍符合 plan 假设。
- 哪些已完成、冲突、过期、新增风险。
- 当前 batch 对应哪些 success criteria。

不要只凭上轮记忆、handoff 或一句“继续”直接改代码。

### Implement Against The Target Chain

实现以 canonical target chain 为准，不以最容易通过测试的路径为准。

避免：

- 降低标准让 gate 通过。
- 保留长期双轨或隐藏 fallback。
- 让旧字段/旧状态/旧入口继续驱动新功能。
- 把业务规则塞进 CLI、report、test helper、migration script。
- 用 Markdown/JSON/report/截图恢复产品状态或验证结果。

### Batch Discipline

每个 execution batch 必须追溯到 goal，且不能把 batch 完成误报为 goal complete。具体实现节奏遵守 `development-execution-guidelines.md`。

### Review And Fix

批次 review 采用 code-review 风格：先列 findings，按严重程度排序，并尽量说明位置、触发条件、影响、修复建议和验证方式。

至少检查：

- goal 是否仍被满足。
- 是否出现第二事实源、第二状态源、平行逻辑、old/new 双写。
- 是否只是表面实现，没有闭合真实能力。
- 分层、依赖方向、复用和抽象是否合理。
- 错误路径、边界值、并发、重试、幂等、恢复是否可靠。
- 安全、权限、secret、资金或外部副作用是否安全。
- 测试、负向扫描和文档同步是否足够。

所有 in-scope finding 必须修复并复审，或明确列为阻断项；不要只记录建议、标成 low/non-blocking 后声明完成。

### Completion Audit

阶段、slice 或整个 goal 声明完成前必须执行 completion audit。

核心问题：

```text
本次 plan 是否彻底完成并符合预期？
实现是否闭合目标能力？
是否存在安全、资金/外部副作用、数据、权限、技术设计、工程化、实现偏差、测试缺口、旧逻辑回流或完成误报？
```

通用审计维度：

- Requirements：success criteria 是否都有证据。
- Completeness：核心 workflow 是否闭合，是否只是 wrapper/stub/report/rename。
- Semantics：业务语义、状态、单位、字段、生命周期是否一致。
- Architecture：分层、边界、依赖、single source、target chain 是否正确。
- Legacy：旧路径是否删除、围栏、降级或明确 adapter/migration-only。
- Safety：权限、secret、输入校验、敏感输出、默认开关是否安全。
- External impact：资金、支付、交易、消息、生产写入、批量变更、第三方副作用是否 fail closed、可确认、幂等、可回滚或可补偿。
- Data：schema、migration、backfill、lineage、并发写、丢失/重复风险。
- Correctness：错误路径、空数据、边界值、重试、超时、partial failure、stale/future data、时间因果。
- Engineering：是否复用已有能力，抽象是否必要，是否可维护、可测试、可观测。
- Operations：配置、feature flag、kill switch、日志、trace/correlation id、监控、runbook。
- Performance：复杂度、分页、fanout、资源占用、退化路径。
- API/UX：外部契约、用户路径、错误信息、兼容承诺。
- Tests：focused、negative、integration/e2e、contract、manual checks 是否覆盖风险。
- Docs：文档是否会误导后续实现。

结论只能是：

- `complete`
- `partial`
- `blocked`
- `deferred`
- `not_assessed`

有任何未关闭的 in-scope finding 时，不能声明 complete。

不要让 completion audit 无限扩张 scope。审计发现的真实问题必须记录；属于当前 goal/success criteria、影响安全/correctness/架构边界/完成语义，或用户明确要求处理的问题，必须修复并复审。只有不属于当前 scope 且不破坏安全或 correctness 的问题，才可在用户显式接受或 plan 明确授权时进入 deferred follow-up，而不是阻止当前 plan 收口。

### Negative Scans

plan 应定义固定负向扫描，常见目标：

- 旧入口、旧命令、旧表、旧字段、旧枚举。
- old/new fallback。
- legacy status 驱动新状态。
- report/Markdown/JSON/CLI output 被读取为产品状态。
- read model/snapshot/cache 反向驱动 facts。
- 策略或业务层直接访问不该访问的 DB/API/file/state。
- secret/token/key/passphrase/signing material 泄露到日志或输出。
- 裸 `status`、含义模糊字段、混用状态。

命中必须分类：allowed / must fix / deferred。

### Completion Report

完成声明必须包含：

- completion level：phase / slice / goal。
- audit decision：complete / partial / blocked / deferred / not_assessed。
- adversarial review：reviewers、ledger status、unclosed findings，或 not_assessed 原因。
- findings/blockers：按严重程度列出，或说明未发现未关闭的 in-scope issue。
- satisfied criteria。
- implementation readiness：已核对证据、仍开放的 discovery / validation 项及其处理状态。
- partial / missing / deferred / blocked 项。
- compatibility / adapter / deprecated path 及退出计划。
- verification：tests、negative scans、regression、manual checks，或未运行原因。
- residual risks。

不能把“没报错”“局部测试通过”“gate 阻断”“文档已更新”当完成证明。

## Self Review

plan 完成前自审：

- 是否覆盖全部用户方向。
- 是否定义 goal、success criteria、non-goals。
- 是否定义 semantic dictionary 和 canonical target chain。
- 是否定义 single source、forbidden paths、legacy 退出。
- 是否有 anti-surface matrix。
- 是否有合理拆解、依赖顺序和 task card ledger，且 `done` 不能被表面完成触发。
- 是否达到 implementation-level 可落地；未核对项是否已转为 discovery / validation，而不是直接执行步骤。
- 是否有 completion audit、negative scans、completion report。
- 是否支持 handoff/context compaction。
- 是否需要同步 docs/service catalog/runbook，避免旧方向误导。

发现问题直接修 plan，不把关键约束只留在聊天记录里。
