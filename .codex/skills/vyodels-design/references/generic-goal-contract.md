---
name: generic-goal-contract
description: 可复用的通用 goal contract，用于 plan 文档或 Plan mode 中定义“如何驱动任务完成、如何判断完成、如何避免提前中断”，不包含具体业务动作。
load_when: 创建、审查或执行 plan 的 goal 部分；进入 Plan mode；接手 goal-driven、multi-phase、migration、复杂实现、长上下文协作或 agent/subagent 编排任务时加载。
not_for: 替代具体业务目标、替代项目 spec、记录当前任务状态、保存 handoff、或作为任何产品事实源。
---

# Generic Goal Contract

本文件定义一个可复用的通用 goal contract。它不描述具体业务动作，只定义 goal 必须具备的执行能力和完成判断能力。

使用方式：在 plan 文档或 Plan mode 中，把具体业务目标填入 `objective`、`scope`、`success_criteria`、`constraints` 等部分；本 contract 的通用规则保持不变，用来驱动任务持续推进到真实完成。

## Goal Purpose

Goal 的作用是驱动任务完成，而不是生成一个待办列表。

一个有效 goal 必须让执行者能够：

- 知道最终要交付什么结果。
- 知道哪些内容属于范围内，哪些不属于。
- 知道哪些约束不可违反。
- 知道什么证据才能证明完成。
- 知道什么时候应该继续推进，什么时候必须暂停请求决策。
- 知道局部完成、focused check 通过、单个 finding 修复、或 fail-closed blocker 都不等于 goal complete。

## Generic Goal

当用户要求执行一个复杂任务、计划、迁移、重构、生产化闭环或多阶段目标时，默认 goal 是：

```text
在当前用户指令和项目约束下，持续推进本任务，直到目标范围内的可交付结果真实完成；完成必须由明确验收标准、必要实现、集中 review、批量修复、复审、相关验证和残余风险说明共同证明。不得因为局部测试通过、单个 finding 修复、文档更新、wrapper/stub 存在、fail-closed 阻断、上下文变大或遇到可处理问题而提前把 goal 标为完成。
```

这段 goal 是通用执行合同。它必须和具体任务目标一起使用，不能单独替代业务目标。

## Required Goal Content

具体 goal 必须补齐以下内容，但不要求使用固定字段名：

- `objective`：最终要达成的结果，描述用户可感知或系统可验证的 outcome，不写成一串底层动作。
- `scope`：范围内的模块、流程、用户路径、接口、数据、文档、迁移或交付物。
- `non_goals`：明确不做的内容，防止范围膨胀。
- `success_criteria`：可验证完成标准，必须能通过 review、测试、扫描、运行结果、人工验收或交付物证明。
- `constraints`：不可违反的技术、业务、安全、合规、性能、兼容、设计或数据约束。
- `canonical_sources`：必须遵守的权威事实源、状态源、设计源、配置源、spec 或 API。
- `forbidden_paths`：禁止恢复、依赖、兼容或绕过的旧路径、临时路径或错误入口。
- `execution_boundary`：允许如何拆批推进，以及哪些局部结果不能误报为 goal complete。
- `stop_conditions`：必须暂停并请求用户决策的条件。
- `completion_evidence`：最终报告必须提供的证据类型。

## Completion Semantics

Goal 完成必须满足：

- 所有 `success_criteria` 都有结论。
- 范围内事项被标记为 `done`、`partial`、`missing`、`deferred` 或 `not_applicable`。
- `partial`、`missing`、`deferred` 说明原因、影响、风险和是否阻断 goal。
- 所有 review finding 都必须有 closure，不得因为 severity 是 `low`、问题很小、容易解释、或不影响当前测试而默认忽略。closure 只能是：已修复并复审、被事实驳回、明确不属于当前用户 scope、或由用户在当前任务中显式接受为 deferred/out-of-scope。
- blocker、high、medium、low finding 中凡属于当前 scope 的问题都必须修复并复审后，才能声明对应 slice/phase/goal complete。`low` 只表示风险等级，不表示可以跳过。
- 已完成 code-review 式 completion audit，确认实现是否彻底、是否符合 goal、是否存在安全/资金/数据/权限/架构/工程化/测试/迁移等阻断风险。
- 必要的 focused checks、负向扫描、回归 gate 或人工验收已完成；无法执行时说明原因和影响。
- 旧逻辑、兼容层、adapter、migration-only 代码、临时 fallback 的保留状态和退出计划已说明。
- 最终回答明确区分：已完成、未完成、阻塞、延期、残余风险和下一步。

以下情况不得声明 goal complete：

- 只完成一个子任务、单个 finding、单个文件、单个测试或单个 wrapper。
- 只是 fail closed，没有实现对应能力。
- 只是文档、报告、CLI 输出、截图、JSON/Markdown 导出发生变化。
- 仍存在未解释的第二事实源、第二状态源、平行逻辑或旧路径主路径回流。
- 完成标准仍不清楚。
- review 尚未进行，或任何当前 scope 内的 review finding 未关闭，包括 `low` 和小问题。
- 将已发现的 `low`、小问题、文档漂移、测试建议、边界歧义或 reviewer residual 只解释为“non-blocking”，但没有修复、事实驳回、用户显式 defer，或明确移出当前 scope。
- completion audit 只做了表面确认，没有追踪 success criteria、风险边界、旧路径和实现完整性。

## Efficiency Semantics

Goal 应推动“一次性尽量完成”，但不要求每个小改动都立刻进入完整 review / full regression。

默认节奏：

- goal 保持最终目标和完成标准稳定。
- plan 把 goal 拆成少数可独立验收的大块 execution batch。
- 每个 batch 先集中实现，中途只做必要 focused checks。
- batch 到达可 review 状态后，再集中 review、批量修复、复审、负向扫描和批次级验证。
- 只有 batch 或整个 goal 达到验收边界时，才声明对应完成状态。

如果出现小问题，先归类为当前 batch finding、跨 batch blocker、scope change、或需要用户决策的问题。不要因为它存在就遗忘 goal，也不要把每个小问题提升成新的独立 goal；但只要它属于当前 scope，就必须在本 batch/goal closure 前解决或获得用户显式 defer。

## Stop Conditions

默认只有以下情况应暂停并请求用户决策：

- 用户目标、项目约束、业务语义或安全边界互相冲突。
- 继续执行可能造成不可逆数据丢失、资金损失、真实生产事故、权限/隐私/secret 风险。
- 需要选择互斥方案，且本地上下文无法可靠判断用户偏好。
- 任务范围必须扩大或缩小，否则原 goal 无法真实完成。
- 关键依赖缺失，且无法通过合理局部实现、mock、adapter、迁移或 deferred blocker 继续推进。

一般代码 bug、测试失败、review finding、局部缺口、旧路径命中、上下文变大，不应自动导致停止；应优先按 goal 和 plan 继续修复或拆成可管理 batch。

## Handoff Semantics

长任务发生上下文压缩、agent 切换或子任务协作时，handoff 必须保留：

- 当前 goal 的 objective、scope、success criteria 和 constraints。
- 当前执行 batch/card。
- 已完成项、未完成项、blocked/deferred 项。
- canonical sources 和 forbidden paths。
- 关键 decisions。
- review findings 和修复状态。
- 已跑验证和未跑验证。
- 下一步具体行动。

handoff 只是协作记录。接手者必须回到 goal、plan、spec 和代码核验，不能把 handoff 当完成证明或产品状态源。
