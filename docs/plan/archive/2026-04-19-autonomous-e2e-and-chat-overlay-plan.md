# Autonomous 端到端 + 双 Agent 对话悬浮窗（Claude Desktop 复刻）实施计划

> Status: archived
> Supersedes: docs/plan/archive/recruiting-workflow-ux-redesign-plan.md; docs/plan/archive/recruiting-workflow-ux-redesign-plan_cn.md
> Superseded by: /Users/vyodels/AgentProjects/cross-project-runtime-docs/final-mock-recruiting-validation-2026-04-25.md for the browser / HID mock recruiting execution chain; UI cleanup topics are not current active work.
> Distilled into: /Users/vyodels/AgentProjects/cross-project-runtime-docs/recruit-agent-browser-virtualhid-overview.md
> Last reviewed against code: 2026-04-25
> Historical source path: docs/superpowers/plans/2026-04-19-autonomous-e2e-and-chat-overlay-plan.md

> Archive note 2026-04-25: this plan mixed older real-site E2E assumptions with a separate chat-overlay UI cleanup scope. It no longer guides current browser / HID runtime work. The current accepted boundary is Autonomous Agent in a mock recruiting environment using `delegate_scene_context -> browser snapshot/navigation -> VirtualHID hid_action -> browser_locate_download -> attach_resume_artifact`, with real-site validation tracked separately outside this repo's old active plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**

1. **P0 — 跑通 Autonomous Agent 的通用外部招聘站点端到端工作流**：从设置 goal → 启动 → Agent 自驱完成 sourcing/拉取联系方式与简历 → 数据落到本地候选人库 → 主程序工作台看板可见。若 human 选择 Boss 直聘作为手工验收样例，仅视为本次运行样例，不构成主程序内置站点特化要求。
2. **P1 — 全局悬浮球 + 对话窗骨架**：在主程序所有页面叠加一个悬浮球，点开是 Claude Desktop 风格（浅色卡片、消息流、左侧会话列表、Inter/SF 字体）的对话窗，复刻视觉到"接近不可分辨"的程度。
3. **P2 — 双 Agent 生命周期统一在对话窗内管理**：对话窗左侧呈现 **Assistant Agent** 和 **Autonomous Agent** 两个**独立配置**的入口；点进各自后能管理 goal / 提示词 / run / approvals / 三类 memory / skills / MCP / provider。
4. **P3 — 删除被对话窗承接的冗余 UI**：按 §0.2 的清单（必须先经 human 确认）移除已无业务承接的页面，但**工作台看板**与**必要配置面板**保留。

**严格优先级：** Autonomous E2E（§1）一定要先于悬浮球 UI（§2/§3）跑通。如果时间不够，§2/§3 可以先出最小骨架（一个能调用后端 API 的对话框 + 配置面板），但 §1 的端到端必须真实可用。

**执行时机：** 本计划与 `2026-04-19-agent-v2-terminology-convergence-plan.md` 互不依赖，可并行实施。当前代码与文档真相统一使用 `run_turn_from_envelope` / `RoundOutcome` / `turn` / `round`；本计划中如出现旧术语，应以后续 terminology convergence 的收敛结果为准。

**Tech Stack:** FastAPI、SQLAlchemy、SQLite、Anthropic/OpenAI provider、SSE/WebSocket、Electron + React + TypeScript、Vite、Inter/SF Pro 字体。

**已确认暂缓项：**

- 本计划暂不收口“所有 LLM provider 统一走 stream、Kernel 按 token/增量流式消费”的能力差异。当前只要求 Assistant/Autonomous 对外事件流与 UI 主流程可用；provider 级统一 stream 与 Kernel 流式增量消费留作后续独立收口项，不作为本计划的 blocker，也不在本计划内引入半成品兼容层。

---

## 0. 范围、优先级与确认门

### 0.1 优先级


| 等级  | 范围                              | 完成判据                                                                                           |
| --- | ------------------------------- | ---------------------------------------------------------------------------------------------- |
| P0  | Autonomous 通用外部招聘站点端到端          | 在主程序里输入"从 JD-X 拉 N 名候选人并获取联系方式 / 简历" → Agent 自跑 → 候选人列表里能看到新候选人 + 联系方式字段 + 简历附件链接              |
| P1  | 悬浮球 + 对话窗骨架（Claude Desktop 风视觉） | 在所有页面右下角看到悬浮球；点开是浮窗对话；左侧能切换 Assistant / Autonomous；消息流能跑通至少一条 user → assistant 往返              |
| P2  | 两 Agent 独立配置 + 生命周期管理 UI        | 每个 Agent 都能编辑 prompt / goal、查看 run/turn 列表、处理 approvals、查看/编辑 memory、查看 skills、查看 MCP/provider |
| P3  | 冗余 UI 清理                        | §0.2 确认清单里勾选删除的全部移除，工作台看板与必要配置面板保留                                                             |


**实施顺序硬约束：**

- §0.2 确认门 **必须先过**（必须由 human 在 review 阶段勾出"删 / 留 / 改"），Codex 不得先动旧 UI。
- §1（P0）必须在 §3（P2 完整生命周期 UI）之前完成。
- §2（P1 骨架）可以与 §1 后半段并行。
- §4（P3 清理）必须最后做，且只删除 §0.2 已勾"删除"的项。

### 0.2 UI 改造清单（human 已确认 · Codex 可直接执行）

**确认状态：** human 已于 plan 提交时一次性确认下表全部"建议处置"——保留项一律保留、删除项一律删除、优化项按描述执行。Codex **不需要**在 §4 实施前再次暂停等待。下表保留作为 §4 删除范围的权威依据；如执行中发现某文件实际职责与下表描述不符，可在 commit message 里附带说明，但不得自行扩大删除范围。

每一项都是 `apps/desktop/src/features/<dir>/<file>.tsx` 或顶层 tab。


| 模块 / 文件                                                                                                               | 当前作用                                              | 建议处置                                                                                                  | 理由                                          |
| --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `features/dashboard/DashboardView.tsx`（顶层 tab `home`）                                                                 | 招聘待办 / 阻塞 / 今日动作总览                                | **保留**（工作台看板，硬约束）                                                                                     | 用户明确点名工作台看板不能动                              |
| `features/candidates/CandidatesKanbanView.tsx` + `kanban-shared/`*（顶层 tab `candidates`）                               | 候选人漏斗 / 状态跟进 / JD 管理三视图                           | **保留**（工作台看板核心）                                                                                       | Autonomous E2E 的输出落点就在这里，必须留                |
| `features/settings/SettingsView.tsx`（顶层 tab `settings`）                                                               | LLM provider / MCP / sync 设置                      | **保留**（必要配置面板，硬约束）                                                                                    | 用户明确点名 LLM API 配置不能删                        |
| `features/recruit-agent/RecruitAgentView.tsx`（顶层 tab `ai-strategy`）                                                   | profile / state-machine / skills / 三类 memory 集中编辑 | **建议删除**                                                                                              | 这些能力在 §3 全部归到对话窗 Agent 面板里，独立 tab 与对话窗重复    |
| `features/agent-inbox/AgentInboxView.tsx`（顶层 tab `ai-review` 之 queue）                                                 | 审批 / 人工介入 / 阻塞任务集中处理                              | **建议删除**                                                                                              | approvals 在 §3 进入对话窗内 Agent 面板，独立 tab 重复且割裂 |
| `features/evolution/EvolutionView.tsx`（顶层 tab `ai-review` 之 changes）                                                  | 演进产物 / Skill 健康 / Memory 刷新提案                     | **建议删除**                                                                                              | evolution 是 Agent 内部能力，应进对话窗 Agent 面板       |
| `features/workbench/WorkbenchView.tsx`                                                                                | 旧执行控制台残留                                          | **建议删除**                                                                                              | README 明确说不再是 execution-record-first 模型     |
| `features/state-machine/StateMachineEditor.tsx`                                                                       | 状态机可视化编辑器                                         | **建议删除**（能力下沉到 Agent 面板内的 playbook 子 tab）                                                             | 当前作为独立页面，未与 Agent 配置流程串起来                   |
| 顶层 tab `ai-review`、`ai-strategy`                                                                                      | DesktopWorkspace 路由项                              | **删除**（依赖上面 4 个 view 的删除）                                                                             | tab 失去内容后整体清掉                               |
| `components/Sidebar.tsx`                                                                                              | 主侧边栏                                              | **优化**：移除 `ai-review` / `ai-strategy` 入口；保留 `home` / `candidates` / `settings`，加一个"Agents"入口（点开就是悬浮窗） | 主导航收敛到 3 个 tab + 1 个 Agents 入口              |
| `components/TopBar.tsx` 中 agent 状态 / refresh 按钮                                                                       | 顶部条                                               | **优化**：保留刷新；agent 状态指示移到悬浮球本身上（红点/旋转环表示 Agent 在跑）                                                     | 让"Agent 状态"统一附着到悬浮球                         |
| 全部 `goals` / `executionTraces` / `executionGraphs` / `strategyFragments` / `operatorInteractions` / `approvals` 等接入逻辑 | DesktopWorkspace 里的 useState + loadWorkspace      | **优化**：从 DesktopWorkspace 上层卸下，下沉到对话窗内部按需加载                                                           | 主壳变薄，避免每 10 秒全量 fetch 拖累                    |


**Codex 行为约束：**

- §4 实施时按上表"建议处置"列直接执行，不再需要二次确认。
- "优化"项在 §2/§3 实施过程中顺手做。
- 若想超出本表删除其它文件，必须停下来询问 human。

### 0.3 强约束（Codex 不得自行发挥）

- 不新建 `_v2` 平行组件 / 平行 tab；改造直接在原文件上做。
- 不引入新的 UI 框架（不要 shadcn/Mantine/Chakra）。沿用当前 vanilla React + CSS Token 体系。但**允许新增 Tailwind 风格的设计 token**到 `apps/desktop/src/styles/`，前提是和现有 token 兼容，详见 §2.1。
- 复刻 Claude Desktop 视觉时不得复制 anthropic 仓库代码；只能参考公开截图重写。
- 外部招聘站点集成不得在 Agent 之外硬编码站点选择器；走 MCP/skill/工具路径，由 Agent 调度（见 §1）。如果 human 选用 Boss 直聘做本次验收，也只作为运行时样例。
- §1 的"端到端跑通"以**真实外部招聘站点账号 + 真实候选人样本**为准，不允许只跑 mock。如果本次验收选用 Boss 直聘，仅代表样例平台；若通用 Browser MCP 集成尚未完成，必须在 §1.1 调研结果中明确告知 human，再决定是补做还是降级到 mock 验收。
- 不为"演示效果"在前端伪造数据；所有展示数据必须来自后端真实 API。
- 不删除"工作台看板"和"LLM/MCP/sync 等必要配置面板"。

### 0.4 测试策略

每个改动都必须：

1. 先补/改最小测试。
2. 改实现。
3. 跑对应最小测试。
4. 阶段末跑 `python3 -m pytest services/backend/tests -q` 全绿、`npm run desktop:typecheck` 全绿。
5. **§1 端到端集成测试可以延后**：human 已确认先把 §1 实现 + §2/§3 UI 跑通，由 human 在主程序里手工验收"创建 goal → wait_human → approve → 候选人落库"全流程；UI 验收通过后再补 §1.5 集成测试。补测试这一步本身仍是 plan 的硬要求，只是时序后挪到 §6 全量回归之后。

### 0.5 唯一允许中途停止的情况

1. §1.1 调研发现通用外部站点集成根本没现成实现，需要 human 决定是补做还是降级。
2. 后端测试或 typecheck 暴露的是计划本身的内部矛盾。
3. 视觉复刻效果与 Claude Desktop 偏差过大且影响验收（这种情况附 screenshot 反馈给 human）。
4. 想超出 §0.2 表格删除其它 UI 文件。

除上述四类，必须一口气实施到底。

---

## 1. P0 — Autonomous Agent 的通用外部招聘站点端到端工作流

### 1.1 现状勘察（**Codex 第一步必须做**，结果写到 commit message）

- grep `boss` / `zhipin` / `直聘` 全仓库，列出所有命中位置，区分"文档提及"vs"代码实现"。
- 检查 `services/backend/src/recruit_agent/services/browser_mcp_bridge.py`、`services/backend/src/recruit_agent/execution_units/browser_worker.py`、`services/backend/src/recruit_agent/mcp/registry.py`、`services/backend/src/recruit_agent/plugins/recruit/toolkit.py`，判断：
  - 是否已存在通用 Browser MCP / 协议桥与通用招聘流程工具契约？
  - 是否已存在"拉取候选人列表 / 拉取联系方式 / 拉取简历"这三个工具的契约？
- 在 `services/backend/src/recruit_agent/models/domain.py` 里确认候选人 / 简历 / 联系方式的存储模型：
  - `Candidate` 表里是否已有 `phone` / `wechat` / `email` / `resume_url` 等字段？
  - 简历附件是落到本地文件系统、走 BLOB 存储、还是只存 URL？
- 在 `services/backend/src/recruit_agent/api/routers/` 里找候选人写入 API（POST/PATCH 候选人、上传简历），确认 Agent 工具有路径写入。
- 把以上四个调查结果以一段 200 字以内的总结写到本节末尾的 `调研结论` 子小节，并据此回答两个问题：
  - **通用外部站点集成现状是哪一档**：已有可用 / 部分可用（缺 X）/ 完全没有？
  - **如果"完全没有"或"部分可用"，是补做还是先 mock**？补做的范围有多大？
- 调研结论写完**暂停**，由 human 决定后再进入 §1.2。

#### 调研结论（2026-04-19）

现状属“部分可用，但通用 Browser MCP → Agent 主链未完全接通”：已有通用 Browser MCP 桥、候选人/联系方式/简历存储与 `resume-artifacts` 写入展示链路，但当前 Browser MCP 动态工具尚未稳定进入 Agent 主回路，`browser_worker` 仍是模拟 stub。后续应修通通用 MCP 接入、提示词与运行时能力暴露；**不得**补写任何站点专用工具链或站点 hardcode。

### 1.2 工具 / Skill 层准备

> 以下任务是"假设 §1.1 调查结论是'部分可用，需要补'"的最小化准备。如果调研结论是"已经齐全"，本节大半任务可以跳过。注意：这里补的是**通用招聘流程语义与通用 MCP 接入**，不是 Boss 专用工具。

- 修通 `services/backend/src/recruit_agent/services/mcp_registry.py` 与 `services/backend/src/recruit_agent/services/container.py`，确保已启用的 Browser MCP / 其它 MCP 动态工具能够真实进入 Agent 可见工具集，而不是只停留在配置层。
- 在 prompt / skill / 运行时合同里补齐通用招聘流程语义，让 Agent 能在运行时自行完成：
  - 候选人发现 / 列表筛选
  - 联系方式获取（需要触发 Guard，按"外部动作"上报 `gate_signal=wait_human`）
  - 简历抓取 / 归档
- 若需要新增主程序侧工具，只允许新增通用招聘语义工具；metadata 中标注 `external_target=True`、`requires_confirmation`，不得出现站点专用命名或站点专用选择器固化。
- 在 `models/domain.py` 上**只补必要字段**：如果 `Candidate` 缺联系方式或简历字段，按调研结论补；不要预添加未在 §1.4 happy path 用到的字段。
- 如果简历是文件，确认/创建 `~/.recruit-agent/resumes/<candidate_id>.<ext>` 落地路径，并在 `services/` 下建一个轻量 `ResumeStorageService` 负责写入与读取 URL 生成。

### 1.3 Autonomous goal → run 完整链路打通

- 在 `services/backend/src/recruit_agent/api/routers/agent.py` 里确认/补全以下 API：
  - `POST /api/agents/autonomous/goals`：入参 `{title, goal_text, jd_id, candidate_count_target, ...}` → 创建 `AgentRun` + `GoalSpec`，并 enqueue 到 scheduler。
  - `GET /api/agents/autonomous/runs/{run_id}`：返回 run + 最近 N 个 turn + 最近 M 个 round 事件。
  - `POST /api/agents/autonomous/runs/{run_id}/cancel`：发送 cancel signal。
  - `POST /api/agents/autonomous/runs/{run_id}/resume`：从 wait_human 状态恢复（生成新 turn）。
- `AutonomousAgent.run_turn_from_envelope` 必须在执行真实外部联系方式获取 / 简历抓取动作时正确产生 `gate_signal=wait_human` → 写 `OperatorInteraction` 待审批。
- approval 通过后，scheduler 必须能 re-enqueue 一次新 turn 让 Agent 续跑。
- 候选人字段写入：Agent 拿到 `ContactInfo` / `ResumeBlob` 后，必须通过 `repositories/domain.py` 的现有写入接口落库；如果接口缺失，本节补一个 `CandidateWriteService.upsert_contact(candidate_id, contact_info)` / `attach_resume(candidate_id, file_path)`。
- 工作台看板（`CandidatesKanbanView`）的数据加载必须能拿到新增的联系方式 / 简历字段并展示。如果 `apps/desktop/src/lib/types.ts` 的候选人类型缺字段，同步补。

### 1.4 主程序"看到候选人"的展示落点

- `CandidatesKanbanView` 候选人卡片增加：
  - 联系方式徽标（手机号/微信号/邮箱）——脱敏展示，点击复制。
  - 简历附件 chip——点击下载或在新窗口打开本地文件路径。
  - 来源标签：`{platform_label} · {jd_title}`；其中 `platform_label` 来自真实 `platform/source` 字段，无值时回退 `外部来源`。
- 候选人详情抽屉（`CandidateDetailDrawer.tsx`）增加"获取来源记录"小段，展示哪个 Autonomous run 的哪个 turn 拉来了这条候选。
- 工作台看板顶部增加"最近 1 小时新拉到 N 名候选"的徽章（不要做大数据可视化，只一行数字 + 时间戳）。

### 1.5 端到端测试（**延后到 §6 之后补**）

> human 已确认：本节集成测试**不在 §1 实施期内补**。先完成 §1 实现 + §2/§3 UI，由 human 在主程序里手工跑一遍"创建 goal → wait_human → approve → 候选人落库 + 简历落地"作为 P0 验收。手工验收通过之后再回头补本节集成测试，作为防回归保险。

- **（手工验收后再做）** `services/backend/tests/agent/integration/test_autonomous_browser_mcp_e2e.py`：
  - 启动 in-memory backend + 一个 mock 的通用 Browser MCP / 招聘流程 fixture（返回固定候选人列表与资料）。
  - 通过 API 创建 Autonomous goal，等待 run 完成。
  - 断言：
    - 至少 1 个 `Candidate` 记录被创建。
    - 该 Candidate 有 `phone` 或 `wechat` 或 `email` 字段。
    - 至少 1 条 `ResumeBlob` 落到 storage（mock 文件系统或临时目录）。
    - `OperatorInteraction` 至少出现过 1 次 `pending`，并能通过 API approve 让 run 继续。
    - 最终 run 状态为 `completed`。
- **（手工验收后再做）** 如果 Browser MCP 与真实外部站点联调可用，再补一个 `tests/agent/integration/test_autonomous_real_site.py` 标记为 `pytest.mark.skipif(not RECRUIT_AGENT_REAL_BROWSER_MCP)`，由 human 在本地真实浏览器登录状态下手动开。

**§1 期内的最低测试要求：** §1.2 / §1.3 / §1.4 涉及到的每个新增 service / writer / API endpoint 都要有相应的**单元测试**——只是不必须串成端到端集成测试。

---

## 2. P1 — 全局悬浮球 + Claude Desktop 风格对话窗骨架

### 2.1 视觉规范（复刻级，参考公开截图，不复制源码）

- 在 `apps/desktop/src/styles/styles.css` 增设一组 `--chat-`* token，但**不破坏现有 `--space-* / --color-`* 体系**。新 token 命名：
  - `--chat-bg`（白色 #FFFFFF / 极浅灰 #FAFAFA）
  - `--chat-surface`（消息卡片背景 #FFFFFF + 1px 极浅灰描边）
  - `--chat-text-primary` / `--chat-text-secondary`
  - `--chat-accent`（Anthropic 蓝紫调或我们自家品牌色，建议沿用现有 `--brand-primary`）
  - `--chat-radius-bubble`（消息气泡圆角，建议 `12px` 顶部 + 底部一角异形 4px 复刻 Claude）
  - `--chat-font-family`（首选 `"Inter", "SF Pro Text", system-ui, sans-serif`；中文 fallback 加 `"PingFang SC"`）
- 所有 Chat 组件统一用上述 token；不在组件 inline 写颜色和字体。
- 行高 / 字号：消息正文 `15px` / `1.6 line-height`；时间戳 `12px` 灰色；侧边栏会话名 `14px`。
- 视觉验收附图：human 在 review 阶段把 Claude Desktop 截图与本项目截图并排对比，差异范围在 **字距 ±2px、颜色 ±5% 灰度** 之内即视为通过。

### 2.2 悬浮球组件

- 新建 `apps/desktop/src/features/chat-overlay/FloatingBubble.tsx`：
  - position: fixed，默认右下角 `bottom: 24px; right: 24px`。
  - 直径 56px，圆形，阴影 `0 8px 24px rgba(0,0,0,0.16)`。
  - 内部图标：当前 Recruit Agent 头像（profile.avatar 或一个默认 icon）。
  - 状态指示：右上角小圆点——`idle` 灰、`running` 蓝色脉冲、`waiting_human` 黄色、`failed` 红色。
  - 可拖拽：mousedown + mousemove 改 fixed 位置；松手时位置写到 `localStorage.bubblePosition`。
  - 点击：dispatch 一个 React context 事件打开对话窗。
- 在 `App.tsx` / `DesktopWorkspace.tsx` 顶层挂载 FloatingBubble + ChatOverlay 容器，使其覆盖在所有页面之上。

### 2.3 对话窗容器 ChatOverlay

- 新建 `apps/desktop/src/features/chat-overlay/ChatOverlay.tsx`：
  - 浮窗模态：默认尺寸 `width: 960px; height: 720px;` 居中或贴右下；可拖拽 header 改位置；可右下角拽角改大小。
  - 三栏布局：
    - 左侧 240px：会话列表（顶部一个 "+ 新会话" 按钮，下方 Assistant Agent 与 Autonomous Agent 两组分类，每组下挂这个 Agent 的最近 N 条会话）。
    - 中间 ~520px：当前会话的消息流。
    - 右侧 200px（可折叠）：当前 Agent 的元信息卡片（goal / 状态 / 当前 run / 进度）。
  - 顶部 header：左上 logo（Recruit Agent），中间会话标题，右上 minimize / close。
- 与 FloatingBubble 通过 React context 通信：`useChatOverlay()` 暴露 `open() / close() / toggle() / focusAgent("assistant" | "autonomous")`。

### 2.4 消息流区域

- 新建 `apps/desktop/src/features/chat-overlay/ChatMessageStream.tsx`：
  - 消息顺序自上而下，最新在底部；用户消息右对齐、Agent 消息左对齐，Claude Desktop 实际是**统一左对齐**——按统一左对齐做，气泡颜色区分（user 浅灰、assistant 白底）。
  - 消息支持 markdown 渲染（沿用现有依赖；如没有，新增 `react-markdown`）。
  - 支持工具调用 inline 卡片：`tool_use` / `tool_result` 显示为可折叠的代码区块。
  - 流式渲染：订阅 `/ws/agent-stream` 或 `/api/agents/{kind}/stream/{conversation_id}` SSE，按 token 增量追加。
- 新建 `apps/desktop/src/features/chat-overlay/ChatComposer.tsx`：
  - 底部输入框 + 发送按钮 + 附件按钮（先做空壳，附件留作后续）。
  - 支持 Cmd/Ctrl+Enter 发送，Enter 换行。
  - Composer 顶部一行 chips：当前选中 Agent 名称、当前 model、当前是否已选 JD/候选人 context（context chips，可点击移除）。

### 2.5 与后端的连接

- `apps/desktop/src/lib/api.ts` 增加：
  - `sendAssistantMessage(conversationId, message) -> SSE stream`。
  - `startAutonomousGoal(payload) -> { run_id }`。
  - `subscribeAgentStream(agentKind, refId) -> EventSource`。
- 复用 §1.3 的后端 API；不为 Chat UI 单独造一套。

### 2.6 P1 测试

- `apps/desktop` 没有测试 runner，所以本节最低验收 = `npm run desktop:typecheck` 通过 + 手工开 dev 验证以下三步：
  - 打开主程序，所有页面（home / candidates / settings）右下角能看到悬浮球。
  - 点击悬浮球打开对话窗，左侧看到 Assistant 与 Autonomous 两个分类。
  - 在 Assistant 下发一条 user 消息，能收到至少一段 streamed assistant 文本。

---

## 3. P2 — 双 Agent 独立配置 + 生命周期统一管理

### 3.1 后端：两个独立的 AgentProfile

- `models/domain.py` 中确认 `AgentProfile`（或当前的 `RecruitAgentProfile`）能持有 **2 行**：一行 `kind=assistant`，一行 `kind=autonomous`。每行都有自己的：
  - `name` / `prompt_system` / `goal_template` / `tone` / `boundaries` / `forbidden_actions` / `compression_policy`。
  - `default_provider_id` / `default_model_id`。
  - `memory_scope_ref`（独立 memory 命名空间）。
- 数据迁移：在启动 `create_all` 后的 seed 阶段，如果两行不存在就插入默认两行（不要写 Alembic）。
- API：
  - `GET /api/agents` → 列出所有 Agent。
  - `GET /api/agents/{kind}` → 单 Agent 详情。
  - `PATCH /api/agents/{kind}` → 更新 prompt / goal / 边界等。
  - `GET /api/agents/{kind}/runs?limit=...` → run / turn 列表。
  - `GET /api/agents/{kind}/approvals` → 该 Agent 的待审批项。
  - `GET /api/agents/{kind}/memory/{scope}` → memory 列表（scope ∈ candidate / job / global）。
  - `GET /api/agents/{kind}/skills` → 该 Agent 可用的 skill。
  - `GET /api/agents/{kind}/mcp` → 该 Agent 启用的 MCP server。
- Memory 隔离：`MemoryService` 在写入 / 读取时按 `agent_profile_id` 限定 scope ref，不允许 Assistant 读到 Autonomous 的 candidate memory（除非 global）。

### 3.2 前端：每个 Agent 的操作面板（嵌在对话窗右侧或独立 tab）

- 在 ChatOverlay 顶部增加二级 tab：`对话` / `配置` / `运行` / `审批` / `记忆` / `技能` / `工具`（共 7 个）。
  - 默认 `对话` tab。
  - 切到非对话 tab 时三栏布局变两栏（左边会话列表保留，右边变成功能面板）。
- **配置 tab**：
  - prompt 编辑器（textarea + monospace）。
  - goal template 编辑器。
  - 边界 / 禁止动作 / 语气（form）。
  - provider / model 选择下拉。
  - "保存"按钮 → 调 PATCH `/api/agents/{kind}`。
- **运行 tab**：
  - run 列表（最近 30 条）：状态 / 起止 / turn 数。
  - 选中 run → 展开 turn 列表 + round 事件流。
  - Autonomous 专属：顶部 "+ 新建 goal" 按钮 → 弹出表单 → 调 §1.3 创建 goal API。
  - Assistant 专属：tab 内不显示"新建 goal"，因为 Assistant 由对话本身驱动。
- **审批 tab**：
  - 当前 Agent 的 `OperatorInteraction(status=pending)` 列表。
  - 每条带 approve / reject 按钮 + 备注。
  - approve / reject 调对应 API；成功后从列表里消失，并在对话流内插入一条系统消息。
- **记忆 tab**：
  - 三个子 tab：Candidate / Job / Global。
  - 列表 + 单条详情编辑（沿用 RecruitAgentView 里现有 memory 编辑组件，把组件抽到 `apps/desktop/src/features/chat-overlay/agent-panel/MemoryEditors.tsx`，**不要在多处复制**）。
  - 支持 manual compact 触发。
- **技能 tab**：
  - 列出该 Agent 可用 skill；展示 status / health / 最近调用次数。
  - 支持启停（PATCH skill enabled）。
- **工具 tab**：
  - MCP server 列表（按 enable 排序）；显示连接状态、工具列表。
  - 内联跳转到 `Settings → MCP` 编辑（不在这里重复 MCP 编辑表单，只做"查看 + 跳走"）。
- 对话区域顶部 chip 里显示当前 Agent 的 model / goal 摘要，点 chip 直接跳到对应 tab。

### 3.3 P2 测试

- 后端：`tests/api/test_agents_routes.py`：覆盖 §3.1 的 7 个 API（GET/PATCH/runs/approvals/memory/skills/mcp）。
- 后端：`tests/memory/test_memory_isolation.py`：断言 Assistant 写入的 candidate memory，Autonomous 读不到（反之亦然），但 global memory 都能读到。
- 前端：typecheck + 手工验收"7 个 tab 都能点开 + 配置编辑能保存 + 审批能批准"。

---

## 4. P3 — 冗余 UI 清理（按 §0.2 已确认清单）

> §0.2 已经被 human 一次性确认，Codex 直接按"建议处置"列执行即可，不需要二次确认。但 commit message 里仍要列明实际删除/优化了哪些文件，便于 review。

- 删除 §0.2 中标记"建议删除"的所有 view 文件 + 对应的 import / 路由项 / 类型字段。
- `DesktopWorkspace.tsx` 的 `tab` 联合类型同步收敛。
- `Sidebar.tsx` 删除对应入口；增加"Agents"入口（点击 = 调 `useChatOverlay().open()`）。
- `loadWorkspace` 函数里删除对应 API 调用，避免冗余 fetch。
- 全仓库搜索被删 view 的引用，清干净。
- `apps/desktop/src/lib/types.ts` 中只被被删 view 用到的类型一并删除。
- 跑 `npm run desktop:typecheck` 必须通过。
- 跑 `python3 -m pytest services/backend/tests -q` 必须全绿（不应该影响后端，但稳妥起见跑一遍）。

---

## 5. 文档更新

- `README.md` 的 "Product Focus" / "Current Repository Layout" 段落同步双 Agent 模型 + 悬浮球 UI 形态描述（一句话即可，不要写长篇）。
- `CLAUDE.md` 的 "Repo-specific working rules" 增加一条：**新加用户面 UI 一律走 ChatOverlay 体系；除工作台看板与必要配置外，不再增加顶层 tab。**
- 删除/归档 `Plan.md` 里与本计划冲突的旧 UX 描述段落（如有）。

---

## 6. 全量回归与收尾

- `python3 -m pytest services/backend/tests -q` 全绿。
- `npm run desktop:typecheck` 全绿。
- `npm run desktop:dev` 启动后逐项手工验收：
  - 工作台首页 / 候选人 / 设置三个 tab 正常。
  - 右下角悬浮球可见、可拖拽、状态指示正确。
  - 点开对话窗：左侧能看到 Assistant + Autonomous 两条；切换流畅。
  - Assistant 单 turn 对话能收到流式响应。
  - **Autonomous P0 happy path（这一步=人工 E2E）**：创建 goal → 出现 run → wait_human 时能在审批 tab 处理 → approve 后 run 续跑 → 候选人卡片出现并带联系方式 / 简历。
- **手工 E2E 验收通过后**，回头补 §1.5 的 `test_autonomous_external_site_e2e.py` 集成测试并跑绿，作为防回归保险。
- 一份简短 changelog（commit message 体）：
  - Autonomous 通用外部招聘站点 E2E 手工跑通 + 集成测试落地。
  - 全局悬浮球 + Claude Desktop 风对话窗上线。
  - 双 Agent 独立配置 + 生命周期 UI 统一。
  - 删除 ai-strategy / ai-review / workbench / state-machine 等冗余 tab（按 §0.2 确认）。

---

## 7. 验收 checklist（human 在 review 阶段对表）

- Codex 严格按 §0.2 表格执行，没有删除未在表中"建议删除"的文件。
- §1.1 调研结论清晰记录在 commit message 里。
- Autonomous P0 happy path 手工 E2E 通过（§6 第三条手工验收）。
- §1.5 集成测试在手工验收通过后已补齐并绿色。
- 主程序里能从工作台看到 Boss 拉来的真实候选人 + 联系方式 + 简历。
- 悬浮球在所有保留的页面都能看到，可拖拽、状态指示正确。
- 对话窗视觉与 Claude Desktop 截图对比差异在 §2.1 容差内。
- Assistant + Autonomous 各自有独立 prompt / goal / memory，互不串。
- 7 个 Agent tab 全部可用。
- 工作台看板与 Settings 完整保留，没有被误删。
- backend 全绿、typecheck 全绿。
