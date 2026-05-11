# 仓库指南

本文件是仓库协作入口壳之一。

共享协作标准与入口规则，以 [`docs/specs/2026-04-20-repo-agent-collaboration-standard.md`](./docs/specs/2026-04-20-repo-agent-collaboration-standard.md) 为准。

## 阅读顺序
1. 先读共享入口规范：[`docs/specs/2026-04-20-repo-agent-collaboration-standard.md`](./docs/specs/2026-04-20-repo-agent-collaboration-standard.md)
2. 再按任务主题阅读 `docs/specs/` 下相关长期规范
3. 如任务涉及实施、迁移或收敛，再看 `docs/plan/active/`
4. `docs/plan/completed/` 与 `docs/plan/archive/` 仅作历史背景使用

## 必读规范索引
涉及 Autonomous 生命周期、主 conversation 与 run 关系、同 Agent 并发上限、Global Memory 口径、prompt 落点、共享招聘能力暴露方式、MCP 标准接入约束、招聘站点接入边界、共享场景模板定位，或主程序 UI 验收边界时，必须先阅读 [`docs/specs/2026-04-20-autonomous-agent-runtime-constraints.md`](./docs/specs/2026-04-20-autonomous-agent-runtime-constraints.md)。

涉及 Agent 智能边界、能力缺口修复顺序、skill 沉淀归属、审批治理与“不要替 Agent 编排”的约束时，必须阅读 [`docs/specs/2026-04-20-agent-intelligence-boundary-and-capability-evolution.md`](./docs/specs/2026-04-20-agent-intelligence-boundary-and-capability-evolution.md)。

涉及 Assistant / Autonomous 的角色边界、共享能力底座、配置隔离、状态可观测性、场景级 handoff 与双 Agent UI/API 表达时，必须阅读 [`docs/specs/2026-04-20-dual-agent-product-architecture.md`](./docs/specs/2026-04-20-dual-agent-product-architecture.md)。

涉及 Agent 产品层设计原则、主能力暴露方式与业务口径时，应同时参考 [`docs/specs/2026-04-20-agent-product-design-principles.md`](./docs/specs/2026-04-20-agent-product-design-principles.md)。

涉及招聘业务 skill 蒸馏、业务语义 skill 设计、Python 代码级 skill 资产，或项目内 skill-creator 标准接入时，必须阅读 [`docs/specs/2026-04-20-recruiting-skill-distillation-standard.md`](./docs/specs/2026-04-20-recruiting-skill-distillation-standard.md)。

涉及前后端业务字段契约、投递记录 / 投递人 / JD 字段、分页、筛选、搜索、统计、评分、简历结构化、话术模板、头像、时间线或“前端不得 mock / 硬编码业务字段”约束时，必须阅读 [`docs/specs/2026-04-29-business-fact-contract-governance.md`](./docs/specs/2026-04-29-business-fact-contract-governance.md)。

本文件只提供阅读顺序与入口索引；长期规则以 `docs/specs/` 中对应规范为准，不在 `AGENTS.md` 重复展开正文。
