---
name: development-execution-guidelines
description: 用户级复杂编码任务执行节奏规范，强调按可独立验收的大块能力边界推进、集中 review、批量修复、focused checks、负向扫描和批次级全量回归。
load_when: 执行或协调多文件、多阶段、高风险、plan-driven、goal-driven、migration、runtime、schema、API/CLI、前后端工作流、或需要 review-fix-verify 循环的编码任务时加载。
not_for: 很小的一次性修改、纯问答、非编码调研、只读解释任务，或用户在当前任务中明确要求不同执行节奏的场景。
---

# Development Execution Guidelines

## 优先级

本规范是用户级默认执行节奏。若用户在当前任务中明确要求更小批次、更频繁测试、禁止 subagent、立即全量回归、只做只读审计，或指定其他执行方式，以用户当前指令为准。

开始复杂任务前，先读取当前项目的 agent entry、README、spec、plan、贡献规范或测试说明。用户级执行节奏只规定如何组织工作，不替代项目的技术规则、测试命令、安全边界或代码风格。

## 核心节奏

复杂实现任务默认按下面节奏推进：

```text
大块 vertical slice 集中实现
-> 集中 review
-> 批量修复
-> focused 复审
-> 固定负向扫描
-> 一次批次级全量回归 gate
```

不要把每个小 finding、局部编辑、单个测试修正都变成独立的完整 review / full test / scan 循环。

## 批次粒度

复杂任务默认按“计划大单元”或“可独立验收的大块 vertical slice”推进。

计划大单元不一定叫 `Phase`。它可能叫：

- Phase / Stage / Milestone / Epic / Wave / Slice
- Workstream / Track / Capability / Module
- Goal / Objective / Deliverable
- 中文里的阶段、里程碑、大块、能力块、工作流、主链路、执行批次

不要机械依赖名称；判断标准是它是否形成一个可独立实现、review、测试和验收的边界。

一个合格批次通常满足：

- 有明确的能力、工作流、迁移、产品契约或系统边界。
- 能集中实现，不只是一个小 finding。
- 能集中 review 设计、边界、安全、状态源、幂等、测试和兼容性。
- 能定义 focused checks、局部验证或负向扫描。
- 完成后能说明：改了什么、为什么、如何验收、剩余风险是什么。

如果计划文档没有显式大单元，就按 vertical slice 自行切分，例如：

- 一条端到端 workflow。
- 一个 public API/CLI contract。
- 一个 runtime/service 能力。
- 一个 data/schema/repository/service/tests 闭环。
- 一个 safety gate 或 fail-closed boundary。
- 一个 legacy/deprecation 收口。
- 一个 admission / promotion / execution / reconciliation 等能力块。
- 一个 UI 用户流程或跨组件交互闭环。
- 一个性能、可靠性、安全性或迁移边界。

不要把下面内容单独当作完成批次：

- 单个 finding。
- 单个字段。
- 单个 wrapper。
- 单个 rename。
- 单个 report 文案。
- 单个测试断言。
- 单个 compatibility alias。
- 没有独立验收意义的局部清理。

## 开发节奏

实现过程中：

- 同一 slice 的相关改动集中完成。
- 中途只跑必要的 focused checks。
- 优先跑导入、类型、语法、目标测试。
- 批次级全量回归留到 slice 完成集中 review 和批量修复之后。

如果任务本身很小，或一个小修能明确解除阻塞，可以直接完成并做局部验证。不要为了遵守大 slice 节奏，把简单任务包装成复杂流程。

## Review 节奏

只有当前 slice 达到可运行、可 review 状态后，才进入集中 review。

集中 review 按任务风险选择检查项，常见内容包括：

- 架构边界是否正确。
- 是否使用 canonical state source。
- fail-closed 或安全默认值是否保持。
- money / unit / precision / time boundary 是否正确。
- trace_id、request_id、correlation id 是否保留。
- 幂等、fencing、lease、retry/backoff 是否正确。
- 旧路径或 compatibility alias 是否回流成主路径。
- 是否把 Markdown、report、CLI 输出、cache 或临时文件当作产品状态。
- domain logic 是否直接绕过 repository/service/API 边界。
- 安全敏感路径是否被默认打开。

## 修复节奏

不要修一个 review finding 就立刻跑 full regression。

应该：

- 先收集当前 slice 的 review findings。
- 同批修复。
- 再复审。
- 再跑 focused checks 和负向扫描。
- 最后用一次项目适用的全量回归作为批次 gate。

severity 不能作为默认跳过理由。`low`、小问题、文档漂移、测试建议、边界歧义和 reviewer residual 只要属于当前 scope，都必须在验收前修复并复审，或被事实驳回；只有用户在当前任务中显式接受为 deferred/out-of-scope，才能保留。不要把“non-blocking”当作“无需处理”。

## 测试策略

实现中只跑与当前 slice 直接相关的 focused checks，例如：

- 改 API/CLI contract，跑 contract/API/CLI tests。
- 改 runtime/service，跑对应 service/runtime tests。
- 改 schema/repository，跑 repository/schema tests。
- 改 UI workflow，跑对应 component/e2e/screenshot checks。
- 改安全或权限边界，跑相关 negative tests。
- 改文档契约，跑文档扫描或 contract checks。

只有在下面条件满足后才跑全量：

- slice 实现完成。
- 集中 review 完成。
- review findings 已批量修复。
- focused checks 通过。
- 固定负向扫描通过。

## 全量回归

全量回归指当前项目适用的最高层验证命令，例如 full test suite、build、typecheck、lint、e2e、smoke、acceptance 或发布前 gate。

不要硬编码某个命令。使用项目已有规范、package scripts、CI contract 或用户指定命令。

## 立即打断例外

以下情况可以提前做专项 review、focused test 或 full regression：

- 涉及资金、真实交易、权限、安全、secret、数据删除或 schema 破坏。
- 发现可能导致数据丢失、重复执行、重复扣款、越权访问或生产事故。
- 当前改动影响大量共享基础设施，且局部测试不足以判断风险。
- 用户明确要求立即验证。

## 负向扫描

不要每个小改动后都跑大扫描。

每个大 slice 末尾统一跑相关 fixed scan set，例如：

- 旧入口或 deprecated path 是否回流成主路径。
- 不该暴露的 public contract 是否仍暴露。
- 不该直接访问的数据源、API、DB、文件或状态源是否被绕过。
- 安全敏感路径是否被默认打开。
- secret、token、credential、private key 是否可能被日志或输出泄露。
- money、unit、precision、time boundary、idempotency、fencing 是否被破坏。
- report、Markdown、CLI output、cache 是否被误用为 product state。

稳定的扫描应逐步固化成 tests。

## Coordinator / Subagent 规则

非小范围 task 或 implementation change 必须遵守用户级独立 subagent review 硬门槛：如果 subagent 工具可用，进入 accepted/passed/done/complete 或提交前，至少需要一个独立 subagent reviewer 做事实驱动的对抗式审查。本地双角色 review 只能作为预审，不能替代独立 subagent review。

非小范围默认包括多文件、多模块、多阶段、runtime、schema、API/CLI、state machine、资金/交易/权限/安全/数据完整性、外部副作用、生产写入、验证证据、review 规范或用户级 memory 变更。小范围例外只限局部拼写、注释、无行为变化 README 修正，或单文件低风险修复且不改变架构、runtime、业务语义、状态机、DB/API contract、安全边界、资金/交易/验证证据或用户级规范。

若 subagent 工具不可用或没有空闲 reviewer slot，先释放已完成 subagent 并重试；仍不可用时，保持 blocked/pending/not_assessed，不得把该 task/implementation 标记、提交或 commit 为 accepted/passed/done/complete，除非用户当前明确临时降级该要求。

使用 coordinator/subagent 时：

- 只并行只读审计和写入范围互不冲突的实现节点。
- 不要让多个 worker 同时写同一组文件。
- 共享文件、schema、公共接口、核心 contract、迁移文件等高冲突区域应由单一 owner 修改，其他 agent 做只读审计或等待。
- 每个 worker 都要有明确 owned files、禁止触碰文件、acceptance criteria 和 focused verification。
- main coordinator 必须 review 和验收；worker 说 done 不等于已接受。
- goal 只有在真实 plan 被证明完成后才关闭。

## 汇报边界

汇报时必须区分：

- focused check passed
- slice ready for review
- slice accepted
- batch regression passed
- full goal complete

不能把 focused check passed 说成 phase complete，也不能把一个 slice 完成说成整个 plan complete。

## 验收声明

只有下面条件全部满足后，才能声明一个大 slice 完成：

- 实现完成。
- 集中 review 完成。
- findings 已批量修复并复审；当前 scope 内不得留下未关闭的 blocker/high/medium/low finding。
- focused checks 通过。
- fixed negative scans 通过。
- 项目适用的批次级全量回归通过。

不要把局部 green checks 报成大单元完成。
