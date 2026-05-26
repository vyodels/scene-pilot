---
name: user-guidelines-index
description: 用户级规范类 memory 索引，覆盖开发规范、编码规范、设计规范、review 规范、测试规范和协作节奏。
load_when: 需要查找、添加、调整或应用用户级规范类长期记忆时加载；包括开发执行、代码风格、设计准则、测试策略、review 节奏和 agent/subagent 协作规范。
not_for: 项目级规则、当前任务状态、产品运行状态、临时 handoff、凭证、或不属于规范类的长期领域知识。
---

# User Guidelines Index

`guidelines/` 存放用户级规范类长期记忆。它定义默认偏好和执行节奏，但不替代当前用户指令、项目级 `AGENTS.md`、项目 spec、测试说明或安全边界。

## Progressive Disclosure

先读本索引和目标文件 metadata。只有 `load_when` 匹配当前任务时，才继续读取具体规范正文。

## Guideline Types

- 开发规范：任务拆分、执行批次、review / fix / verify 节奏、subagent 协作方式。
- 编码规范：跨项目代码风格、抽象边界、错误处理、可维护性偏好。
- 设计规范：UI/UX、信息架构、交互、视觉和设计系统偏好。
- 测试规范：focused checks、负向扫描、回归 gate、验收声明。
- 协作规范：汇报节奏、handoff、coordinator / worker 分工。

## Current Guidelines

- [development-execution-guidelines.md](development-execution-guidelines.md): 复杂编码任务的批次粒度、集中 review、批量修复、focused checks、负向扫描和 coordinator/subagent 执行节奏规范。
- [generic-goal-contract.md](generic-goal-contract.md): 可复用的通用 goal contract，用于 plan 文档或 Plan mode 中定义 goal 的执行驱动、完成语义、效率语义和停止条件。
- [plan-design-execution-guidelines.md](plan-design-execution-guidelines.md): 大型 plan 设计、任务拆解、语义收敛、事实源唯一、legacy 退役、负向验收和上下文控制规范。

## Placement Rules

- 新规范文件必须带 metadata：`name`、`description`、`load_when`、`not_for`。
- 文件名使用小写 kebab-case。
- 单个规范文件尽量不超过 500 行；超过时优先精简、拆分或改为索引加渐进式加载。
- 只放用户级、跨项目可复用的规范；项目专属规则应放在项目自己的文档或 `AGENTS.md`。
- 不存放 secret、token、private key、passphrase、完整签名材料或临时任务状态。
