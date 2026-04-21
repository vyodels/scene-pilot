# Agent 运行时概念审查与术语收敛草稿

**状态**: 草稿  
**日期**: 2026-04-22  
**背景**: 基于当前对 `recruit-agent` 内部 Agent 运行时概念的审查，以及与 Anthropic Claude API / Managed Agents、Claude Code、OpenAI Agents、Codex 的术语对照。

---

## 0. 结论先行

最高层判断是：

- `Agent` 必须保持为一个**通用、足够 agentic 的执行体**。
- 特质化差异应主要来自**装配进去的 prompt、context、tools、memory、permissions 与 lifecycle**，而不是来自硬编码的业务特化 Agent 物种。
- `Autonomous` 不应因为类本身“知道招聘跟进该怎么做”而变得特殊。它应因为被装配了不同的角色提示词、不同的生命周期、不同的预算/策略，以及 browser MCP 等能力而变得特殊。

在这个原则下，当前代码库里存在两种不同情况：

- 一条**相对健康的核心运行时主链**，应大体保留。
- 一圈围绕隔离执行、策略蒸馏和图投影长出来的**项目自造概念层**，应重新审查并收缩。

其中最明显的“硬造概念”例子，就是 `SceneContext`。

---

## 1. 本文定位

本文记录当前对内部 Agent 概念的判断：哪些概念是健康的，哪些概念是硬造过度的，哪些概念应降级、重命名，或从主产品/运行时叙事中移除。

本文还不是正式规范，不覆盖 `docs/specs/`。如果后续团队决定正式收敛术语，结果应再提升到对应的长期规范中。

---

## 2. 上位原则：Agent 必须保持通用且 agentic

项目应稳定保持下列原则：

- `Agent` 是通用执行体。
- `Assistant`、`Autonomous` 以及未来任何 specialist role，主要应因为**装配方式**不同而不同，而不是因为 core runtime 长出了新的业务物种。
- 系统应为 Agent 提供环境、工具、记忆边界、权限和提示词，再让模型在这些边界内自主决定如何行动。
- 系统应避免把 Agent 退化成一个硬编码工作流执行器。

这意味着系统应优先采用：

- `profile / prompt / context / tool policy / memory policy / lifecycle policy`

而不是：

- 把 `FollowUpAgent / OutreachAgent / BrowserAgent / RecruitingAgent` 做成不同的 core runtime 物种。

---

## 3. 外部参考口径摘要

### 3.1 Anthropic Claude Managed Agents

Anthropic 的 Managed Agents 文档主语主要围绕：

- `Agent`
- `Environment`
- `Session`
- `Events`

这里最重要的启发是：Agent 是由 model + system prompt + tools + MCP + skills 定义出来的，而不是由某个业务特化物种定义出来的。

### 3.2 Claude Code

Claude Code 的官方描述主语围绕 `agentic loop`：

- gather context
- take action
- verify results

它更稳定的运行时词汇是：

- `session`
- `conversation`
- `tools`
- `permissions`
- `skills`
- `subagents`
- `hooks`

它并不会把产品架构中心放在某个特殊业务 Agent 类型上。

### 3.3 OpenAI Agents 与 Codex

OpenAI 近年的 agent / process 词汇更接近：

- `conversation`
- `run`
- `turn`
- `tool call`
- `handoff`
- `approval`

这组词的好处是，它直接描述执行与治理阶段，而不需要再发明一层额外的业务型运行时物种。

### 3.4 对本项目的直接启发

本项目更稳的术语骨架应贴近：

- `Agent`
- `Profile`
- `Conversation` 或 `Session`
- `Goal`
- `Run`
- `Turn`
- `Tool Call`
- `Approval`
- `Handoff`
- `Memory`

超出这套骨架的概念，只有在它确实表达了一个真实的一等边界时，才值得保留。

---

## 4. 审查内部概念的判断标准

当一个概念满足下列情况之一时，应被视为可疑：

1. 它没有映射到真实的一等边界。
2. 它主要是为了包装某个实现层 workaround。
3. 它在悄悄把业务行为硬编码进 Agent 本体。
4. 业内已经有更标准、更清晰的术语可以表达同一件事。
5. 它让产品叙事开始围绕内部机械结构，而不是围绕业务对象与执行状态展开。

一个自定义名词并不天然错误。真正的问题不是“这个词是不是我们发明的”，而是“这个词是否代表一个稳定且必要的边界”。

---

## 5. 当前概念审查结果

## 5.1 应大体保留的概念

| 概念 | 当前职责 | 判断 | 建议 |
|---|---|---|---|
| `AgentKernel` | 通用机制层，负责 `sense -> assemble -> deliberate -> act -> evaluate -> update_memory` | 合理的内部运行时术语 | 作为实现层概念保留，但不要让它成为产品主语言 |
| `GoalSpec` | 持久化目标定义 | 与运行时 goal ref 的工程性拆分合理 | 保留 |
| `AgentSession` | Autonomous 的长期 session 容器 | 合理，但有一定歧义 | 暂时保留，但在对外语言里要谨慎 |
| `AgentRun` | 围绕某个 goal 的一次执行实例 | 健康且与行业口径对齐 | 保留 |
| `turn` / `round` | Driver 外层单位与 model/tool 内层循环 | 一组很健康的术语 | 保留 |
| `AgentRuntimeEvent` | 运行时事件日志 | 清晰且有用 | 保留 |
| `AgentRunCheckpoint` | 恢复 / 续跑边界 | 清晰且与治理语义对齐 | 保留 |
| `EnvironmentSnapshot` | 执行环境的结构化证据快照 | 清晰的数据对象 | 保留 |

### 5.2 应重新审查或降级的概念

| 概念 | 当前职责 | 问题点 | 建议 |
|---|---|---|---|
| `SceneContext` | 承载隔离 delegated execution 的总括概念 | 过于抽象、不是行业主词，并且把执行隔离和 scoped context 语言混在一起 | 从主产品/运行时叙事中移除；降级或替换成更清晰的词 |
| `ExecutionEpisode` | 一次隔离执行实例 | 勉强可懂，但不如 `run`、`attempt`、`execution run` 直观 | 建议考虑重命名 |
| `StrategyFragment` | 被蒸馏出来的局部策略单元 | 更像一层项目自造智能概念，而不是必要的一等对象 | 保留前需重新论证 |
| `ExecutionGraphProjection` | 执行过程的图投影对象 | 更像可视化 artifact，而不像运行时主概念 | 降级到 artifact/projection 层 |
| `JobAssembly` | job 级装配对象 | 更偏实现侧，而不是产品/runtime 主概念 | 不要提升到主概念层 |
| `PromptOverlayRevision` | 版本化 prompt overlay 对象 | 对实现有用，但不是主运行时概念 | 只保留在实现层 |

---

## 6. 为什么 `SceneContext` 是最明显的硬造概念

`SceneContext` 是当前最明显不应进入长期主叙事的概念。

问题不只是它的名字新。更大的问题是，它把多种不同职责混进了一个标签里：

- delegated execution
- isolated execution environment
- local execution evidence
- scoped context language

因此，很多基础设计问题都很难回答清楚：

- 它到底是不是 subagent？
- 它到底是不是 run？
- 它到底是不是 context container？
- 它到底是不是可恢复线程？
- 它到底只是一个 execution sandbox？

而系统真正需要的一等边界其实更简单：

1. **执行隔离**
2. **作用域化持久上下文**

通常，直接命名这两个真实边界，会比继续维持一个总括性的 `SceneContext` 更清楚。

---

## 7. 对核心运行时主链的判断

当前主 Agent 运行时主链相对健康：

- `AgentKernel`
- `GoalSpec`
- `AgentSession`
- `AgentRun`
- `turn`
- `round`
- `AgentRuntimeEvent`
- `ApprovalItem`
- `AgentRunCheckpoint`

这条主链主要在表达：

- 执行生命周期
- 执行作用域
- 事件留痕
- 恢复能力
- 治理边界

它**并不会天然把业务特化 Agent 物种写死进模型里**。

因此，当前术语问题的主矛盾并不在 `Kernel / Run / Turn` 这条主链上，而更在于围绕它们额外长出来的那圈概念层。

---

## 8. 这对 `Autonomous` 的含义

`Autonomous` 应被视为一种**profile + lifecycle + policy assembly**，而不是一个业务型 runtime 物种。

这意味着：

- 它可以有不同的 prompt
- 它可以有不同的 permissions
- 它可以有不同的 scheduling 和 wake-up 行为
- 它可以拥有 browser MCP 或其他外部工具访问能力
- 它可以有不同的 memory scope 和 budget policy

但它**不应因为类里内建了招聘工作流知识而变得特殊**。

换句话说：

- runtime 应保持通用
- specialization 应来自 assembly
- model 应在这些边界内保持足够 agentic

---

## 9. 建议采用的术语分层

### 9.1 产品 / runtime 主层

更推荐的主词汇应为：

- `Agent`
- `Profile`
- `Conversation` / `Session`
- `Goal`
- `Run`
- `Turn`
- `Tool Call`
- `Approval`
- `Handoff`
- `Memory`

### 9.2 执行隔离层

当系统确实需要一个单独的执行隔离概念时，更清晰的名字通常会是：

- `delegated execution`
- `isolated execution`
- `environment execution`
- `execution run`
- `execution attempt`

### 9.3 application-scoped 跟进层

当系统需要一个挂在单条 `CandidateApplication` 上的持久上下文时，更清晰的名字通常会是：

- `ApplicationContext`
- `ApplicationThreadContext`
- 如果作用域表达得足够清楚，也可继续使用 `ApplicationSession`

这一层应和执行隔离层保持明确区分。

---

## 10. 当前建议

### 10.1 保留

保留核心运行时术语：

- `AgentKernel`
- `GoalSpec`
- `AgentRun`
- `turn`
- `round`
- `AgentRuntimeEvent`
- `AgentRunCheckpoint`
- `EnvironmentSnapshot`

### 10.2 降级或重命名

优先审查下列概念：

- `SceneContext`
- `ExecutionEpisode`
- `StrategyFragment`
- `ExecutionGraphProjection`
- `JobAssembly`
- `PromptOverlayRevision`

### 10.3 面向未来设计的 guardrail

以后每次引入新的 runtime / product 概念前，都应先问：

1. 这个词是否表达了一个真实边界？
2. 这个词是否比现有标准术语更精确？
3. 这个词是否让 Agent 保持通用？
4. 这个词是否把 specialization 放在 assembly，而不是放在 Agent 物种本体上？

如果答案是否定的，这个概念大概率就不该引入。

---

## 11. 待决问题

以下问题在进入实现重构前，仍需要显式收敛：

1. `AgentSession` 是否继续保留为长期运行时术语，还是对外产品叙事应更稳定地使用 `conversation`？
2. `ExecutionEpisode` 是否应改成更清晰的执行术语，例如 `ExecutionRun` 或 `ExecutionAttempt`？
3. `ApplicationSession` 是否应升级成一个更明确的 application-scoped context 模型？
4. 如果 `SceneContext` 退出主叙事，当前 delegated execution 路径最干净的替代表达是什么？

---

## 12. 当前最终判断

当前判断是：

- 项目应保留一个**通用的 Agent runtime**。
- `Agent` 应保持为通用执行体。
- 特质化差异应来自**装配进去的 prompt、context、tools、memory、permissions 与 lifecycle**。
- 以 `Kernel / Goal / Session / Run / Turn / Approval / Checkpoint` 为中心的主运行时主链总体是合理的。
- 最像“硬造概念”的对象，主要集中在 `SceneContext`、执行投影层和策略碎片层周围。

这份 draft 应被视为后续规范收敛的当前方向，而不是正式长期规范本身。
