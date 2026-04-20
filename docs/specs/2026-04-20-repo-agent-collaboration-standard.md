# 仓库多代理协作入口规范

## 文档目标与适用范围
本文档定义本仓库在多代理协作场景下的统一入口规范，用于约束 `AGENTS.md`、`CLAUDE.md`、`CLAUDE_cn.md` 这三类协作入口文件的职责、权威顺序、共享工作规则与文档治理方式。

本文档记录的是长期稳定的入口与协作约束，不是实施计划、handoff、阶段进度、临时草案或当前实现快照。若入口文件、实现习惯或历史文档与本文档冲突，应优先修正入口文件与实现，或先更新本文档后再变更相关入口。

## 与现有规范的关系
- 本文档定义的是**仓库协作入口规则**，解决“多个代理入口文件如何共用同一套标准”的问题。
- 产品方向、Agent 产品设计原则、运行时边界、双 Agent 架构、智能边界与能力演进，仍分别以 `docs/specs/` 下对应规范为准。
- 当前实施与迁移安排，以 `docs/plan/active/` 中同主题最新 plan 为准；但 plan 不是长期真相，不能覆盖本规范和其它已确认的规范文档。

## 权威顺序
涉及仓库长期规则时，使用以下顺序：

1. `docs/specs/` 中已确认的规范
2. 本文档
3. `docs/plan/active/` 中同主题最新 plan
4. `docs/plan/completed/` 与 `docs/plan/archive/` 中的历史材料
5. 当前实现细节

补充约束：
- 新生成的规范文档必须先经用户确认，确认后才能成为正式事实来源。
- 代码只能用于验证主线是否已经落地、识别实现漂移与未收敛细节；不能因为当前实现存在漂移，就反向改变规范口径。
- `docs/specs/` 只承载长期稳定的骨架、设计思想、边界、约束与对象模型，不承载迁移步骤、阶段状态、handoff 或实施细节。

## 入口文件职责
### 1. `AGENTS.md`
`AGENTS.md` 是仓库协作入口壳之一。

它的职责只包括：
- 告诉代理应优先阅读哪些规范和计划目录
- 指向本文档与 `docs/specs/`、`docs/plan/`
- 在确有必要时承载极少量 agent-runner 特定补充

它不应再维护一套独立、完整、长期演进的仓库规则正文。

### 2. `CLAUDE.md`
`CLAUDE.md` 是 `Claude Code` 使用的仓库协作入口壳。

它的职责只包括：
- 为 `Claude Code` 提供最小入口说明
- 指向本文档与 `docs/specs/`、`docs/plan/`
- 在确有必要时承载极少量 Claude Code 特定补充

它不应与 `AGENTS.md` 长期并行维护两套仓库规则正文。

### 3. `CLAUDE_cn.md`
`CLAUDE_cn.md` 只作为 `CLAUDE.md` 的中文对照和阅读辅助。

它的职责只包括：
- 帮助中文读者理解 `CLAUDE.md` 与共享规范
- 指向本文档与正式规范目录

它不是独立规则源，不应脱离 `CLAUDE.md` 与本文档单独演进。

## 共享阅读顺序
所有入口文件应统一引导读者按以下顺序理解仓库：

1. 先读本文档，理解共享协作入口规则
2. 再读 `docs/specs/` 下与当前任务相关的长期规范
3. 如任务涉及实施、迁移或收敛工作，再读 `docs/plan/active/` 中同主题最新 plan
4. `docs/plan/completed/` 与 `docs/plan/archive/` 仅作为历史背景与提炼来源使用

## 产品方向与仓库结构的共享事实
入口文件共享的最低事实口径如下：

### 1. 产品方向
本仓库服务的产品是 **Recruit Agent**，一个 local-first 的招聘工作台。

当前产品主线包括：
- 两个内置 agent：`Assistant` 与 `Autonomous`
- 候选人进度管理
- 候选人 / JD / 全局 memory
- 候选人沟通审核与人工确认
- playbook 演进与 skill 治理
- `home / candidates / settings` 加 `Agents` overlay 的用户入口

以下内容不是当前产品主线：
- 通用 execution console
- 以 runtime 机械结构为中心的产品表面
- 站点特化工具链的主程序内置化

### 2. 仓库结构
- `apps/desktop`：Electron + React 桌面端
- `packages/shared`：前后端共享契约
- `services/backend`：FastAPI 后端、runtime、memory、scheduler、MCP、sync 等基础设施
- `docs/`：规范、计划、handoff、发布与参考文档

### 3. 文档目录约束
- `docs/specs/`：长期规范
- `docs/plan/active/`：当前实施计划
- `docs/plan/completed/`：已完成但仍保留的计划
- `docs/plan/archive/`：被覆盖或仅作历史参考的计划

旧路径（如原 `docs/superpowers/plans/`、`docs/superpowers/specs/`）只应被视为历史来源，不再作为正式入口，也不应再被当作新增文档的落点。

## 共享工作规则
### 1. 桌面端规则
- 修改 `apps/desktop` 前，先阅读 `apps/desktop/DESIGN_GUIDELINES.md`
- 新的终端用户桌面表面应通过 `ChatOverlay` 承载；除保留的 `home / candidates / settings` 外，不新增新的顶层 tab
- 桌面端与后端如果确实共享同一份契约，应优先沉到 `packages/shared`

### 2. Prompt / Runtime / Tool 边界
- `.recruit-agent/` 是项目级 Agent 资源统一根目录；`prompts/`、`skills/` 与 `plugins/` 资产/配置/元数据默认都收口到这里
- 面向 LLM 的自然语言行为约束默认放在仓库级资源目录 `.recruit-agent/prompts/`
- `services/backend/src/scene_pilot/plugins/**` 只保留 backend 可 import 的薄运行时 shell / mount code，用于读取 `.recruit-agent/plugins/` 资产并挂到共享能力底座
- 优先通过 prompt、结构化上下文、tool contract、skill 修复能力缺口，而不是往 core runtime 里补业务硬编码
- 不在 core runtime / agent 主路径里硬编码站点规则、页面词表、选择器或一次性 workflow

### 3. 共享能力暴露方式
- 共享招聘能力（如同步 JD、发现候选人、AI 评分）应通过通用 `plugin / toolkit / MCP / tool surface` 暴露
- 不应把共享业务能力建模成某个 Agent 私有动作目录
- `Assistant` 与 `Autonomous` 的差异应体现在目标、记忆、生命周期与执行策略，而不是能力是否被单独挂载

### 4. 外部开发代理边界
- 主程序 UI 验收时，外部开发代理只能通过 `chrome-devtools` 操作主程序页面
- `browser-mcp` 只保留给主程序内部 Agent 驱动外部网站，不作为外部开发代理的主程序 UI 控制器

### 5. 文档整理规则
- 规范沉淀的是稳定骨架、设计思想与设计规范
- 识别到代码漂移时，应在 plan / follow-up 中记录，不把漂移实现写进规范
- 每次梳理出新的规范文档，都必须先提交给用户确认，再更新正式索引与入口文件

## 共享开发命令基线
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

## 最低验证要求
在没有更强专项验证要求时，最小验证基线是：
- 后端相关改动：相关 `pytest`
- 桌面端相关改动：`npm run desktop:typecheck`
- 同时改前后端契约：至少同时覆盖 `pytest` 与 `npm run desktop:typecheck`

## 变更原则
### 1. 入口文件只做薄壳，不再重复维护长期规则正文
当共享规则已经能写入本文档或其它 `docs/specs/` 规范时，应优先沉到底层规范，而不是再次复制到 `AGENTS.md`、`CLAUDE.md` 或 `CLAUDE_cn.md`。

### 2. 共享规则变更优先更新规范，再更新入口壳
若共享规则发生变化，应先更新本文档或相关上位规范，再同步更新三个入口文件中的链接与阅读顺序，避免入口文件先漂移、规范后补写。

### 3. 翻译文件不得成为独立真相来源
`CLAUDE_cn.md` 的更新应以 `CLAUDE.md` 与本文档为依据，不得独立追加新的长期规则。

### 4. 历史路径保留不等于继续扩散旧入口
迁移期间保留旧路径，只是为了兼容现有使用方；新的规范、计划与入口索引必须落到新的正式目录中。
