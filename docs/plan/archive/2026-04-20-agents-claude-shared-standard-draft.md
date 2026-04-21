# AGENTS.md / CLAUDE.md 共享协作标准（候选规范草案）

> Status: candidate draft
> Scope: `AGENTS.md`、`CLAUDE.md`、`CLAUDE_cn.md`
> Note: 本文档是候选规范草案，只有在用户确认后，才可转为正式 canonical 标准并被 `AGENTS.md` / `CLAUDE.md` 共同索引。

## 1. 文档定位

本文件的目标，是为仓库内的多代理协作入口提供**同一套共享标准**，避免 `AGENTS.md` 与 `CLAUDE.md` 长期各写一套规则、逐渐分叉。

本文件一旦被确认，应成为：

- `AGENTS.md` 的共享规则来源
- `CLAUDE.md` 的共享规则来源
- `CLAUDE_cn.md` 的翻译参考来源

这三个文件本身不再各自维护一套完整仓库规则正文，而只保留：

- 面向各自工具的最小说明
- 必要的工具特定补充
- 指向本共享标准的统一入口

## 2. 权威顺序

涉及仓库长期规则时，使用以下顺序：

1. `docs/specs/` 中已确认的规范
2. 本共享标准（确认后）
3. `docs/plan/active/` 中同主题最新 plan
4. `docs/plan/completed/` 与 `docs/plan/archive/` 中的历史材料
5. 当前实现细节

补充约束：

- 新生成的规范文档必须先给用户确认，确认后才能成为正式事实来源。
- 代码只能用于验证主线是否落地、识别漂移点；不能因为当前实现有漂移，就反向修改规范口径。
- `docs/specs/` 只承载长期稳定的骨架、设计思想、边界、约束与对象模型；不承载迁移步骤、handoff、阶段状态和实施细节。

## 3. 产品方向

仓库当前服务的产品是 **Recruit Agent**，一个 local-first 的招聘工作台。

当前产品主线：

- 两个内置 agent：`Assistant` 与 `Autonomous`
- 候选人进度管理
- 候选人 / JD / 全局 memory
- 候选人沟通审核与人工确认
- playbook 演进与 skill 治理
- `home / candidates / settings` 加 `Agents` overlay 的用户入口

不是当前主线：

- 通用 execution console
- 以 runtime 机械结构为中心的产品表面
- 站点特化工具链的主程序内置化

## 4. 仓库结构

- `apps/desktop`：Electron + React 桌面端
- `packages/shared`：前后端共享契约
- `services/backend`：FastAPI 后端、runtime、memory、scheduler、MCP、sync
- `docs/`：规范、计划、handoff、发布与参考文档

文档目录约束：

- `docs/specs/`：长期规范
- `docs/plan/active/`：当前实施计划
- `docs/plan/completed/`：已完成但仍保留的计划
- `docs/plan/archive/`：被覆盖或仅作历史参考的计划

旧路径（如原 `docs/superpowers/plans/`）只保留历史来源意义，不再作为正式入口。

## 5. 共享工作规则

### 5.1 桌面端规则

- 修改 `apps/desktop` 前，先读 `apps/desktop/DESIGN_GUIDELINES.md`
- 新的终端用户桌面表面应通过 `ChatOverlay` 承载；除保留的 `home / candidates / settings` 外，不新增新的顶层 tab
- 桌面端与后端如果确实共享同一份契约，应优先沉到 `packages/shared`

### 5.2 Prompt / Runtime / Tool 边界

- 面向 LLM 的自然语言行为约束默认放在 `services/backend/src/recruit_agent/prompts/`
- 优先通过 prompt、结构化上下文、tool contract、skill 修复能力缺口，而不是往 core runtime 里补业务硬编码
- 不在 core runtime / agent 主路径里硬编码站点规则、页面词表、选择器或一次性 workflow

### 5.3 共享能力暴露方式

- 共享招聘能力（如同步 JD、发现候选人、AI 评分）应通过通用 `plugin / toolkit / MCP / tool surface` 暴露
- 不应把共享业务能力建模成某个 Agent 私有动作目录
- `Assistant` 与 `Autonomous` 的差异应体现在目标、记忆、生命周期与执行策略，而不是能力是否被单独挂载

### 5.4 外部开发代理边界

- 主程序 UI 验收时，外部开发代理只能通过 `chrome-devtools` 操作主程序页面
- `browser-mcp` 只保留给主程序内部 Agent 驱动外部网站，不作为外部开发代理的主程序 UI 控制器

### 5.5 文档整理规则

- 规范沉淀的是稳定骨架、设计思想、设计规范
- 识别到代码漂移时，应在 plan / follow-up 中记录，不把漂移实现写进规范
- 每次梳理出新的规范文档，都必须先提交给用户确认，再更新正式索引与入口文件

## 6. 常用命令基线

### 前端

```bash
npm install --ignore-scripts
npm run desktop:dev
npm run desktop:build
npm run desktop:typecheck
npm run shared:build
```

### 后端

```bash
cd services/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn recruit_agent.server:create_app --reload --factory
```

### 测试

```bash
npm run backend:test
python3 -m pytest services/backend/tests -q
python3 -m pytest services/backend/tests/test_api_app.py -q
python3 -m pytest services/backend/tests/test_api_app.py -k health -q
```

## 7. 最低验证要求

在没有更强专项验证要求时，最小验证基线是：

- 后端相关改动：相关 `pytest`
- 桌面端相关改动：`npm run desktop:typecheck`
- 同时改前后端契约：至少同时覆盖 `pytest` 与 `npm run desktop:typecheck`

## 8. 三个入口文件的最终角色

### `AGENTS.md`

保留内容：

- 仓库协作入口说明
- 阅读顺序
- 指向本共享标准与 `docs/specs/` / `docs/plan/`
- 如有必要，保留极少量 agent-runner 特定补充

### `CLAUDE.md`

保留内容：

- `Claude Code` 使用说明的最小壳
- 阅读顺序
- 指向本共享标准与 `docs/specs/` / `docs/plan/`
- 如有必要，保留极少量 Claude Code 特定补充

### `CLAUDE_cn.md`

保留内容：

- `CLAUDE.md` 的中文对照说明
- 不单独作为新的规则来源
- 不能脱离共享标准与 `CLAUDE.md` 单独演进

## 9. 需要用户确认的点

在把本草案转为正式规范前，需要用户确认至少以下几点：

1. 本共享标准是否放入 `docs/specs/` 作为正式 canonical 文档
2. `AGENTS.md` / `CLAUDE.md` 是否收缩成薄入口壳
3. `CLAUDE_cn.md` 是否明确降级为翻译参考，而不是独立规则源
4. 本文中的共享工作规则是否完整覆盖你希望两套入口共同遵守的最低标准
