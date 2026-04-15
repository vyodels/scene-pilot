# 仓库指南

## 项目结构与模块组织
`apps/desktop` 是 Electron + React 桌面端。可复用 UI 放在 `src/components`，按功能划分的页面放在 `src/features`，Electron 主进程与预加载代码放在 `electron/`。`packages/shared` 存放桌面端共用的 TypeScript 类型契约。`services/backend/src/scene_pilot` 是 FastAPI 后端，按 `api/`、`runtime/`、`services/`、`playbooks/`、`db/`、`scheduler/` 等模块组织。后端测试位于 `services/backend/tests`。架构说明和发布文档集中在 `docs/` 与 [Plan.md](./Plan.md)。

## 构建、测试与开发命令
前端依赖使用 `npm install --ignore-scripts` 安装；仓库中的 `.npmrc` 默认关闭安装脚本。启动桌面端使用 `npm run desktop:dev`，构建使用 `npm run desktop:build`，严格类型检查使用 `npm run desktop:typecheck`。

后端建议在 `services/backend` 目录下开发：`python3 -m pip install -e .[dev]` 安装 FastAPI 与 pytest 依赖，`uvicorn recruit_agent.server:create_app --reload --factory` 启动本地 API（默认 `127.0.0.1:8741`）。运行后端测试可在仓库根目录执行 `npm run backend:test`，或直接执行 `python3 -m pytest services/backend/tests -q`。

## 桌面端 UI 设计规范
涉及 `apps/desktop` 任何界面改动（新页面、新组件、样式调整）时，必须先阅读并遵守 [`apps/desktop/DESIGN_GUIDELINES.md`](./apps/desktop/DESIGN_GUIDELINES.md)。该文件是视觉与交互的事实来源：token、骨架、组件形态、动效节奏均以它为准。注意它只提供**风格模板**，文中出现的字段/文案仅为填充示意，**不要照抄到其它业务页面**；真实业务字段以当前需求和 `packages/shared` 的类型为准。若业务需求与规范冲突，请先在 PR 中指出并更新规范，再修改代码。

## 编码风格与命名约定
遵循现有代码风格：TypeScript 使用严格模式、2 空格缩进，React 组件文件使用 `PascalCase`，工具函数与普通变量使用 `camelCase`。Python 使用 4 空格缩进，模块和函数使用 `snake_case`，并保持类型注解。若桌面端与后端共享同一数据结构，优先把契约放进 `packages/shared`。

## Agent 提示词边界
当 agent/LLM 在真实环境里缺少能力、识别失败，或没有学会某个站点/场景时，禁止通过主程序 hardcode 站点规则、页面词表、能力识别分支、下载策略或站点特化流程来替它补能力。优先修改提示词、执行合同、工具边界和技能学习路径，让模型自行完成识别、规划与执行。站点特定流程只能沉淀到 skill 或经批准的学习产物里，不能直接写进 core runtime / agent 主流程。

凡是面向 LLM 的自然语言行为约束、步骤指引、完成标准说明，默认应落在 `services/backend/src/scene_pilot/prompts/` 下的 prompt 文件中，而不是写进 `runtime/`、`services/`、工具描述、主流程代码字符串或临时代码注释里。主程序允许传递结构化上下文，例如约束、成功标准、工具可用性、执行计划状态，但不要借此在代码里继续追加新的提示词正文。

修复 agent 能力缺口时，先检查并完善 prompt，再考虑是否存在真正的通用运行时缺陷。只有通用的工具暴露、协议兼容、结构化上下文透传、结果持久化等问题适合改主程序；任何针对单一站点、单一页面、单一下载链路的识别或补偿逻辑都不应进入 core。

当前仓库没有统一的 ESLint、Prettier 或 Ruff 配置。提交前至少通过 `tsc` 与 `pytest`，并保持与相邻文件一致的写法。

## 测试规范
后端测试基于 `pytest`，文件命名遵循 `test_*.py`。优先沿用现有模式，通过 `FastAPI TestClient` 和临时数据目录覆盖 API、运行时和调度相关行为。涉及 UI 或共享契约调整时，至少运行 `npm run desktop:typecheck`，并补跑相关后端测试。

## 提交与 Pull Request 规范
最近提交历史采用 `feat:`、`fix:`、`docs:` 等前缀，并使用简短的祈使句摘要。每次提交应只聚焦一个变更主题。PR 需说明用户可见影响、列出实际验证命令、在有对应事项时关联 issue 或计划项；桌面端界面改动附截图，API 行为改动附请求或响应示例。

## 安全与配置提示
后端配置通过 `.env` 加载，环境变量前缀使用 `RECRUIT_AGENT_`。不要提交密钥、本地 `.env` 文件，或 `data/`、`services/backend/data/` 下生成的 SQLite 数据。
