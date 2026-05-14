# Project Handoff

## 目的

这份文档只保留**稳定项目入口**，不再承载临时会话细节。

- 项目级长期边界：看 [AGENTS.md](../AGENTS.md) 与 `docs/specs/`
- 当前产品与架构总入口：看 [README.md](../README.md) 与 `docs/plan/active/`
- 已完成/已被覆盖的历史方案：看 `docs/plan/completed/` 与 `docs/plan/archive/`
- 非规范参考资料：看 `docs/reference/`
- 当前桌面 UI 商业化与组件复用交接：看 `docs/plan/completed/2026-05-14-desktop-ui-commercialization-handoff.md`
- 旧 plan/spec/reference 路径暂时保留，待迁移使用方切换后再下掉旧文件

## 当前项目事实

- 当前主路径是桌面端 `chat-overlay + floating bubble` 与后端 `assistant / autonomous + InteractionEngine`
- 共享招聘业务能力应通过通用 `plugin / toolkit / MCP / tool surface` 暴露，不应建模成某个 Agent 私有动作目录
- 外部招聘站点接入不能 hardcode 到主程序；主程序只提供通用流程语义、MCP 桥接、审批、记忆和持久化
- UI 验收时，外部开发代理可以通过 Playwright、Chrome DevTools 或等价 UI 工具操作主程序前端；`browser-mcp` 只保留给主程序内部 Agent 驱动外部 / mock 招聘站点

## 桌面端重点入口

- 工作台壳：[/apps/desktop/src/features/workspace/DesktopWorkspace.tsx](/Users/didi/AgentProjects/recruit-agent/apps/desktop/src/features/workspace/DesktopWorkspace.tsx:1)
- Overlay 主体：[/apps/desktop/src/features/chat-overlay/ChatOverlay.tsx](/Users/didi/AgentProjects/recruit-agent/apps/desktop/src/features/chat-overlay/ChatOverlay.tsx:1)
- 悬浮球：[/apps/desktop/src/features/chat-overlay/FloatingBubble.tsx](/Users/didi/AgentProjects/recruit-agent/apps/desktop/src/features/chat-overlay/FloatingBubble.tsx:1)
- 仪表盘：[/apps/desktop/src/features/dashboard/DashboardView.tsx](/Users/didi/AgentProjects/recruit-agent/apps/desktop/src/features/dashboard/DashboardView.tsx:1)
- 设置页：[/apps/desktop/src/features/settings/SettingsView.tsx](/Users/didi/AgentProjects/recruit-agent/apps/desktop/src/features/settings/SettingsView.tsx:1)

## 后端重点入口

- Agent 路由：[/services/backend/src/recruit_agent/api/routers/agent.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/api/routers/agent.py:1)
- Recruit 路由：[/services/backend/src/recruit_agent/api/routers/recruit_agent.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/api/routers/recruit_agent.py:1)
- Autonomous 主流程：[/services/backend/src/recruit_agent/agents/autonomous.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/agents/autonomous.py:1)
- Recruit 服务：[/services/backend/src/recruit_agent/services/recruit_agent.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/recruit_agent.py:1)
- 共享场景模板：[/services/backend/src/recruit_agent/services/scene_templates.py](/Users/didi/AgentProjects/recruit-agent/services/backend/src/recruit_agent/services/scene_templates.py:1)

## 默认验证

```bash
python3 -m pytest services/backend/tests -q
npm run desktop:typecheck
```

## 清理约定

- `project-handoff.md` 只保留稳定入口，不追加一次性排障细节
- 临时交接只在仍有效时保留在根目录；失效后移入 `docs/plan/archive/` 或删除
