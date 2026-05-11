# 仓库多代理协作入口规范

## 文档目标

本文定义本仓库的协作入口、阅读顺序、文档目录和最低工作规则。`AGENTS.md` 是唯一入口正文；`CLAUDE.md` 是指向 `AGENTS.md` 的软链接，不再单独维护内容。

## 权威顺序

涉及长期规则时，使用以下顺序：

1. `docs/specs/` 中已确认的规范
2. 本文档
3. `docs/plan/active/` 中同主题最新 plan
4. `docs/plan/completed/` 与 `docs/plan/archive/` 中的历史材料
5. 当前实现细节

`docs/specs/` 只承载长期稳定的骨架、设计思想、边界、约束与对象模型，不承载迁移步骤、阶段状态、handoff 或实施细节。

## 入口文件

- `AGENTS.md`：唯一协作入口正文。
- `CLAUDE.md`：软链接到 `AGENTS.md`，只为兼容 Claude Code 文件名约定。

不得新增第二套入口正文，不得恢复 `CLAUDE_cn.md`。

## 阅读顺序

1. 先读 `AGENTS.md`。
2. 再读 `docs/specs/README.md` 和任务相关规范。
3. 如任务涉及实施、迁移或收敛，再读 `docs/plan/active/` 中同主题最新 plan。
4. `docs/plan/completed/` 与 `docs/plan/archive/` 仅作为历史背景与提炼来源。

## 产品方向

本仓库服务的产品是 **Recruit Agent**，一个 local-first 的招聘工作台。

当前产品主线包括：

- 两个内置 Agent 产品形态：`Assistant` 与 `Autonomous`
- 候选人进度管理
- 候选人 / JD / 全局上下文与可复用业务知识；Agent file memory 是机制层能力，不是业务对象名
- 投递记录沟通审核与人工确认
- playbook 演进与 skill 治理
- `home / candidates / settings` 加 `Agents` overlay 的用户入口

以下内容不是当前产品主线：

- 通用 execution console
- 以 runtime 机械结构为中心的产品表面
- 站点特化工具链的主程序内置化

## 仓库结构

- `apps/desktop`：Electron + React 桌面端
- `packages/shared`：前后端共享契约
- `services/backend`：FastAPI 后端、Agent runtime、memory、scheduler、MCP、sync 等基础设施
- `docs/`：规范、计划、handoff、发布与参考文档

## 文档目录

- `docs/specs/`：长期规范，必须保持少量、稳定、主动维护
- `docs/plan/active/`：当前实施计划
- `docs/plan/completed/`：已完成但仍保留的计划
- `docs/plan/archive/`：被覆盖或仅作历史参考的计划

无效规范应直接删除；历史计划可归档。

## 工作规则

### 桌面端

- 修改 `apps/desktop` 前，先阅读 `apps/desktop/DESIGN_GUIDELINES.md`。
- 新的终端用户桌面表面应通过 `ChatOverlay` 承载；除保留的 `home / candidates / settings` 外，不新增新的顶层 tab。
- 桌面端与后端共享契约应优先沉到 `packages/shared`。

### Agent 与业务边界

- `services/backend/src/recruit_agent/agent_runtime/**` 必须保持业务无关。
- 招聘业务只能通过 product adapter、tool、skill、plugin、prompt、MCP 或 business service 接入。
- 优先通过 prompt、结构化上下文、tool contract、skill 修复能力缺口，而不是往 core runtime 里补业务硬编码。
- 不在 core runtime / Agent 主路径里硬编码站点规则、页面词表、selector 或一次性 workflow。

### 共享能力

- 共享招聘能力应通过通用 `plugin / toolkit / MCP / tool surface` 暴露。
- 不应把共享业务能力建模成某个 Agent 私有动作目录。
- `Assistant` 与 `Autonomous` 的差异应体现在目标、记忆、生命周期与执行策略上，而不是能力是否被单独挂载。

### 外部开发代理

- 外部开发代理可以用 UI 工具触发 goal、配置参数和查看状态。
- 外部开发代理不得用 Playwright、Chrome DevTools、页面 JS 或 `browser-mcp` 直接替内部 Autonomous type 操作招聘网站。
- `browser-mcp` 只保留给主程序内部 Agent 驱动外部 / mock 招聘网站。

## 开发命令基线

前端：

```bash
npm install --ignore-scripts
npm run desktop:dev
npm run desktop:build
npm run desktop:typecheck
npm run shared:build
```

后端：

```bash
cd services/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn recruit_agent.server:create_app --reload --factory
```

测试：

```bash
npm run backend:test
python3 -m pytest services/backend/tests -q
python3 -m pytest services/backend/tests/test_api_app.py -q
python3 -m pytest services/backend/tests/test_api_app.py -k health -q
```

## 最低验证要求

- 后端相关改动：相关 `pytest`
- 桌面端相关改动：`npm run desktop:typecheck`
- 同时改前后端契约：至少同时覆盖 `pytest` 与 `npm run desktop:typecheck`
