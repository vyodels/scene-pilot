# 2026-04-19 UI Recovery Handoff

## 当前状态

- 当前仓库分支上的代码改动已经包含以下修复：
  - 桌面端 `desktop:dev` 启动链已收口为：
    - 固定 renderer 端口 `5174`
    - 通过 `scripts/dev-desktop.mjs` 启动 Vite + Electron
    - Electron dev 模式开启 `9222` remote debugging
  - Electron 主进程修复：
    - 兼容 ESM 下的 `__dirname`
    - 先复用已在线 backend，再尝试启动 backend
    - 修复 GUI 环境下 `spawn python3 ENOENT`
  - preload 修复：
    - `apps/desktop/electron/preload.cts`
    - `apps/desktop/tsconfig.node.json` 已包含 `electron/**/*.cts`
    - 编译后会生成 `dist-electron/electron/preload.cjs`
  - CSP 修复：
    - `apps/desktop/index.html` 已补开发期 CSP
    - 已移除无效的 `frame-ancestors` meta 配置
  - 共享场景模板收口：
    - 后端执行入口已从 `autonomous/actions/...` 改为 `scene-templates/{template_key}/runs`
    - 前端 API 已改为 `runSceneTemplate(...)`
    - overlay 中的 `actionKey` 已改为 `sceneTemplateKey`
    - `action_panel` 已改为 `scene_template_panel`
    - 全局模板 scope 默认已改为 `workspace:shared`

## 已验证通过

- `python3 -m pytest services/backend/tests/api/test_agents_routes.py -q`
- `mypy --strict services/backend/src/recruit_agent/api/routers/agent.py`
- `npm run desktop:typecheck`
- `npm --workspace apps/desktop run electron:build`

## 当前唯一阻塞

- Electron 应用本身已可启动，且 `9222` 正常监听。
- 可直接验证：
  - `curl -sS http://127.0.0.1:9222/json/version`
- 当前阻塞不在项目代码，而在本次 Codex 会话绑定的 `chrome-devtools` MCP transport：
  - `mcp__chrome_devtools__list_pages` 持续返回 `Transport closed`
- 本机残留的 `chrome-devtools-mcp` 进程已经清理过一次；如果新会话仍有问题，可再次清理。

## 新会话第一步

1. 保持桌面端 dev 进程运行，不要关闭。
2. 新会话进入仓库后，先执行：
   - `mcp__chrome_devtools__list_pages`
3. 如果恢复正常，继续做 UI 验收：
   - 悬浮球
   - ChatOverlay
   - 会话列表/分组/排序
   - Autonomous/Assistant 主流程 UI

## 如果仍然失败

- 再次确认：
  - `curl -sS http://127.0.0.1:9222/json/version`
- 如果 curl 正常但 `chrome-devtools` 仍然 `Transport closed`：
  - 说明依然是 Codex 客户端会话级 connector 问题，不是仓库问题
  - 需要重开 Codex 客户端或再次新建会话

## 建议给新会话的开场提示

读取 `docs/session-handoff-2026-04-19-ui-recovery.md`，继续做 UI 验收。先验证 `chrome-devtools list_pages` 是否恢复，再继续主程序 UI 自动验收，不要从头分析。
