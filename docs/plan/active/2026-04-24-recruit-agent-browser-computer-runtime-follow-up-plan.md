# Recruit Agent Browser / Computer Scene Runtime 收口计划

> Status: active
> Supersedes: -
> Superseded by: -
> Distilled into: -
> Last reviewed against code: 2026-04-25
> Historical source path: -

## 1. 目标

在**不改动上游** `VirtualHID` 和 `mcp-browser-chrome` 仓库的前提下，把 `recruit-agent` 仓库内与 browser / HID scene runtime 相关的收口工作整理清楚，明确：

1. 本仓库内已经完成了哪些基础设施收口。
2. 还剩哪些事项尚未执行。
3. 哪些事项属于上游仓库或后续阶段，不应继续在本仓库里硬补。

## 2. 当前已完成

- [x] `browser-json-socket` 预置模板改走通用 stdio preset 通路，不再依赖 browser-only 分支。
- [x] 新增 `virtualhid-json-socket` 预置模板，并按 MCP `tools/list` 动态发现 `hid_*` 工具。
- [x] runtime 不再对 tool history 写死压缩；原始工具结果直接进入模型历史。
- [x] `LLMResponse -> Deliberation -> RoundOutcome` 全链保留 `result_data` 与 `skill_draft`。
- [x] `delegate_scene_context` / `SceneContextService` 支持 `browser_target`、`computer_target`、`target_regions`、`action_plan`、`artifact_expectations`。
- [x] scene execution contract 明确 `coordinate_policy = delegate_to_hid`，不再让主 Agent 自算最终屏幕绝对坐标。
- [x] prompt、guide、API 测试、runtime-bridge 测试已对齐当前 browser / VirtualHID 契约。
- [x] 已新增 `resume_collection` scene template，并用 Autonomous Agent 模拟环境招聘任务执行 fixture 证明 `JD sync -> candidate_discovery -> resume_collection -> artifact attach` 这条本地 contract 闭环可跑通。

### 2.1 已完成的模拟闭环证明

以下能力已经在**不接真实站点、不接真实 MCP 上游**的前提下完成本地证明：

- [x] `runtime_task_compiler`、任务 prompt 与 scene template 明确要求在 browser + HID 场景下产出稳定 scene contract，而不是把 DOM / click trace 塞回业务历史。
- [x] `services/backend/tests/agent/unit/test_simulated_recruiting_task_execution_prompt_contracts.py` 固化了 `delegate_scene_context`、`artifact_expectations`、`attach_resume_artifact` 与 `skill distillation` 的 prompt 约束。
- [x] `services/backend/tests/agent/integration/test_simulated_recruiting_task_execution_scene_contract_chain.py` 用模拟环境任务执行 fixture 验证了 3 段业务目标的最小闭环：
  - `job_description_sync`
  - `candidate_discovery`
  - `resume_collection`
- [x] 模拟闭环中的完成判定已明确依赖业务级 `result_data` 与本地 artifact 路径 / 格式验证，而不是依赖 `tabId`、DOM `ref`、`signature` 或 `clickPoint`。

这意味着：**本仓库内的 prompt / template / contract / workspace writeback 收口已经有模拟证据**；当前未做的是“真实 run 采用”和“真实上游联调”，不应继续混为一谈。

## 3. 仍未执行

### 3.1 真实 run 采纳链路

- [ ] 当前只完成了模拟环境任务执行 contract proof，尚未用真实业务 run 证明模型会稳定自行产出 scene 合同。
- [ ] 在真实业务 goal 中验证 `runtime_task_compiler -> scene template -> delegate_scene_context` 是否稳定产出 browser / computer scene 合同。
- [ ] 对 `candidate_discovery`、`job_description_sync`、`resume_collection` 做一次真实 run 级 contract review，确认需要时确实会下发 `browser_target`、`computer_target`、`target_regions`、`action_plan`。

### 3.2 下载 / 上传 artifact 闭环

- [ ] 当前只在模拟环境任务执行中证明了 artifact 路径 / 格式验证与 workspace attach 的 contract 闭环，尚未验证真实下载副作用。
- [ ] 在真实 scene 中验证下载、上传、导出这类外部副作用链路，确认 `artifact_expectations` 足以支撑“获取 -> 本地路径验证 -> 业务摘要返回”。
- [ ] 统一 scene result 中 artifact 相关字段的业务表达，避免后续业务写入链各自发明返回格式。

### 3.3 真实 MCP 联调验证

- [x] 上游 browser L2 acceptance、VirtualHID control-server / MCP smoke 已在真实环境跑通。
- [ ] 基于已通过的上游 smoke，继续做三项目真实 upstream MCP 联调与业务 run 采用验证。
- [ ] 在联调后记录 `scene_context`、`hid_action`、artifact 验证链路中的剩余缺口，再决定是否需要继续补 prompt / contract / business write 映射。

2026-04-25 当前上游状态：

- `mcp-browser-chrome` 已补齐页面 JS 可观测面验证、active-tab-only `browser_screenshot` 边界；真实环境完整 `node scripts/acceptance-smoke.mjs` 已通过。
- `VirtualHID` Swift 工具链已收口，`swift test` 通过 26 个测试；`ReplayTraceStore`、目标定位 V2、视口映射、执行计划、执行证据基础能力已落地；真实环境 `control-server-smoke` / `mcp-smoke` 已通过。
- recruit-agent 本仓库仍只消费上游稳定合同，不在本仓库实现 browser 截图、JS 检测、HID 坐标换算或 tab 激活。

### 3.4 旧 plan 继续刷新

- [ ] 继续刷新仍在使用旧 browser 词汇的 active E2E / UI plan 段落。
- [ ] 把剩余 active plan 中的浏览器动作示例统一收敛到“read-only browser + HID / scene execution”口径。

### 3.5 明确暂缓

- [ ] `await_scene_context` / `read_scene_context_result` 异步委派链仍然暂缓，不在本轮继续展开。

## 4. 明确不在本轮范围

- [x] 不在 `recruit-agent` 仓库里修改 `VirtualHID` 上游实现。
- [x] 不在 `recruit-agent` 仓库里修改 `mcp-browser-chrome` 上游实现。
- [x] 不为基础 HID 动作额外新增默认审批门；是否要求确认仍由现有 runtime policy 决定。
- [x] 不引入站点专用 selector、站点专用操作剧本、站点专用 fallback。

## 5. 相关文档关系

- 规范真相：[`docs/specs/2026-04-20-autonomous-agent-runtime-constraints.md`](../../specs/2026-04-20-autonomous-agent-runtime-constraints.md)
- 智能边界：[`docs/specs/2026-04-20-agent-intelligence-boundary-and-capability-evolution.md`](../../specs/2026-04-20-agent-intelligence-boundary-and-capability-evolution.md)
- 已完成的 scene context 主链收口：[`docs/plan/completed/2026-04-20-autonomous-scene-context-delegation-plan.md`](../completed/2026-04-20-autonomous-scene-context-delegation-plan.md)
- 当前 browser / HID 操作口径：[`docs/guides/agent-operator-guide_cn.md`](../../guides/agent-operator-guide_cn.md)
- 当前实现状态参考：[`docs/reference/recruit-agent-web-tooling-notes.md`](../../reference/recruit-agent-web-tooling-notes.md)

## 6. 当前结论

当前 `recruit-agent` 仓库内已经把 **MCP preset 通路、scene contract、runtime 结果传递、prompt/test/doc drift** 这四块基础设施收住了。剩下没执行的，主要是**真实 run 采用、真实 artifact 副作用闭环、以及等上游稳定后的真实联调**，而不是继续在本仓库里发明新的 browser / HID 底层能力。
