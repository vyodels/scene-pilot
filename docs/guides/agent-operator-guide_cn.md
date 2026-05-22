# Agent 操作手册 · 读页面 + 控键鼠

> **读者**：recruit-station 以及其他需要"读网页 → 决策 → 键鼠操作"的 Agent
> **单一事实源**：本文档是 Agent 使用 `browser-mcp` 和 `VirtualHID` 两套工具的**唯一入口说明**；两套工具仓库内部的实施文档不是 Agent 该读的
> **最后更新**：2026-04-25
> **配套跨系统方案**：`~/AgentProjects/cross-project-runtime-docs/recruit-station-browser-virtualhid-overview.md`

---

## 0. 一句话原则

Agent 手里有两件工具：

1. **`browser-mcp`**：只读网页（快照、坐标、截图、切标签页）
2. **`VirtualHID`**：拟人化键鼠注入（点击、输入、滚动、学习用户操作习惯）

这两件工具**互相看不到对方**。它们之间的业务贯穿——"这个页面上哪个元素是登录按钮，该用什么节奏点击"——**全部由 Agent 在自己脑子里和 prompt 里完成**。不要期望把业务逻辑下推到任何一端。

---

## 1. 接入方式（MCP 一把全）

两套工具都是 **MCP stdio server**。Agent 只需要在 Codex / Cursor / Claude Code 配置里把它们注册为 MCP server，工具就会自动出现在 `tools/list` 里。

### 1.1 Codex 注册示例（`~/.codex/config.toml`）

```toml
[mcp.servers.browser-mcp]
command = "node"
args = ["/Users/vyodels/AgentProjects/mcp-browser-chrome/mcp/server.mjs"]

[mcp.servers.virtualhid]
command = "node"
args = ["/Users/vyodels/AgentProjects/VirtualHID/mcp/server.mjs"]
```

两套仓库都自带 `npm run codex:mcp:install` 安装脚本，执行一次即可写入上面两段。

### 1.2 工具命名约定

- `browser_*`：**只读浏览器状态** + 标签页管理（Agent 认为"带这前缀的动作不会在页面里合成点击/输入/滚动"）
- `hid_*`：键鼠注入（Agent 认为"带这前缀的动作会真实落到系统键鼠事件流"）

**不要把两组前缀混起来调用**——比如"想点击按钮"的正确做法是：先 `browser_snapshot` 取目标上下文和候选落地区域，再把 `browser_target`、`computer_target`、`target_regions`、`action_plan` 这类稳定合同交给 `hid_action` 或 scene execution 层；**不要**去找什么 `browser_click`（已在只读化重构中删除），也不要让 Agent 自己算最终屏幕绝对坐标。

### 1.3 组合执行器时序

`browser-mcp` 和 `VirtualHID` 在实现上是两个 MCP server，但 Agent 调度时必须把它们当成一个完整的浏览器自动化执行器：

```text
browser observe/wait -> Agent decision -> hid_action write -> browser observe/wait -> Agent decision -> hid_action write
```

这条时序约束描述的是 `recruit-station` 内部 Agent 操作外部 / mock 招聘网站的产品执行链路，不限制外部测试 harness 操作 `recruit-station` 自己的前端。测试 harness 可以用 Playwright、Chrome DevTools 或等价 UI 工具启动 goal、配置参数和查看运行状态；一旦进入招聘网站执行，页面观察和写入仍必须回到 `browser-mcp` + `VirtualHID` 组合链路。

- `browser_*` 提供类似 Playwright locator / page state 的观察层。
- `hid_action` 提供类似 Playwright click/type/scroll 的写入层，只是写入由 macOS HID 事件完成。
- 点击、输入、发送聊天内容、滚动、拖拽、快捷键等浏览器目标 HID 动作后，下一次浏览器目标 HID 动作前必须先调用 `browser_snapshot`、`browser_wait_for_*`、`browser_query_elements`、`browser_locate_download` 或等价 browser 观察工具确认页面、下载或消息状态。
- 对外的 `click` 原语本身就是连续 HID 操作：VirtualHID 内部会先规划拟人化鼠标移动轨迹，再完成落点和点击。Agent 不应显式传 `move`，也不应把移动作为单独外部工具动作编排。
- Chrome 下载气泡、下载列表、菜单和 popover 是浏览器外壳 UI，不属于网页 DOM，也不会稳定出现在 `browser_snapshot`。这类遮挡由 VirtualHID 在浏览器目标 `hid_action` 的 `browserChromeOverlayPolicy` preflight 中处理；Agent 不要写页面 JS、mock fallback 或站点分支来关闭它。
- 这个约束是通用时序协议，不是站点流程硬编码；Agent 仍然必须根据当前 browser 证据自行判断下一步。

### 1.4 Prompt 与运行状态隔离

Agent 的 prompt / instruction 只能描述稳定规则：角色边界、允许工具、完成标准、恢复策略、输出合同和证据要求。运行时观察到的具体数量、页面摘要、职位名、候选人名、已完成比例、剩余项等动态事实，必须放在结构化 context、tool result、`result_data` 或 evidence refs 中，不得拼回 system prompt、续跑 instruction 或 scene instruction。

因此，恢复执行时不应生成“已完成 1/5、剩余 4 个、继续打开某几个职位”这类由历史摘要推断出的提示词。正确做法是保持规则化 scene instruction，并要求 scene 按 output contract 返回结构化 `observed_*`、`completed_*`、`remaining_work`、`blockers` 和 `evidence` 字段；父 Agent 只能基于这些结构化字段和最新 browser 证据判断下一步。

### 1.5 前置条件

1. Chrome 加载 `mcp-browser-chrome` 的 `dist/` 扩展
2. macOS 给 VirtualHID 授过 **Accessibility** 和 **Input Monitoring** 权限（`hid_state` 可以查）
3. 目标 Chrome 窗口存在（不要求前台；VirtualHID 会按 `postMode` 决定是否先激活）

---

## 2. `browser-mcp` 工具清单

共 17 个工具。分五组。

### 2.1 标签页管理

| 工具 | 用途 |
|---|---|
| `browser_list_tabs` | 列举所有窗口 / 标签页 |
| `browser_get_active_tab` | 当前激活的标签页 |
| `browser_reload_extension` | 重载扩展，只允许外部维护/调试时使用，不能在 autonomous scene 内调用 |
| `browser_select_tab` | 激活指定标签页（顺带把 Chrome 窗口置前） |
| `browser_open_tab` | 默认在最后聚焦的 Chrome 窗口打开新标签页；传 `windowId` 可指定窗口；传 `tabId` 时复用并导航已有标签页；传 `newWindow: true` 时先复用 / 拆分已有同 URL 或同 origin 标签页，找不到才创建新的普通 Chrome 窗口 |

### 2.2 读页面（核心）

| 工具 | 用途 |
|---|---|
| `browser_snapshot` | **最重要**：页面全量快照 |
| `browser_query_elements` | 用 selector / text / role 查元素 |
| `browser_get_element` | 按 `@eN` ref 精确读一个元素 |
| `browser_debug_dom` | 冗长 DOM dump（调试用，token 烧钱） |
| `browser_screenshot` | 视口截图（`captureVisibleTab`，不标红框；只能截取目标窗口当前活跃 tab） |
| `browser_get_cookies` | 按 URL / domain / name 读取 cookie；常用于判断登录态 |

### 2.3 下载 / artifact 只读定位

| 工具 | 用途 |
|---|---|
| `browser_locate_download` | 通过 Chrome background/downloads API 定位下载记录、本地路径、下载状态和字节进度；用于 HID 触发下载后、workspace 写入前 |

`browser_locate_download` 不打开 `chrome://downloads`，不注入页面 JS，不让 mock 页面回传下载状态，也不使用 DOM 标记作为 proof。它只能把 Chrome 下载记录里可见的 `filename / state / exists / mime / url / finalUrl / referrer / bytesReceived / totalBytes / startTime / endTime` 等结构化事实交给 Agent；`state` 可以是 `in_progress`、`interrupted` 或 `complete`。当下载由 HID 点击触发时，Agent 应把点击前 snapshot 的 `href/sourceUrl`、`download` 或预期 filename、`startedAfter` 时间戳传给它做来源关联，避免多次下载造成路径误配。是否满足简历归档要求由 `recruit-station` 根据业务目标继续判断。

### 2.4 等待

| 工具 | 用途 |
|---|---|
| `browser_wait_for_element` | 等元素出现 |
| `browser_wait_for_text` | 等文本出现 |
| `browser_wait_for_navigation` | 等指定 tab 完成导航 |
| `browser_wait_for_disappear` | 等元素消失 |
| `browser_wait_for_url` | 等 URL 命中目标 pattern |

### 2.5 当前没有的动作

- 当前 `browser-mcp` 没有 `browser_close_tab`、`browser_navigate`、`browser_go_back`、`browser_reload`、`browser_wait` 这类旧动作。
- 需要打开目标 URL 时，走 `browser_open_tab`。
- 测试和回归场景应优先复用已有测试 tab，传 `tabId + url` 导航，不要大量打开新标签页。
- 如果 operator goal 已明确给出目标 URL，该 URL 必须进入 `browser_target.url`，并从 URL 派生 `browser_target.host`；目标边界按完整 origin 判断，包含端口，不能用同 hostname 的旧 tab 替代。
- 招聘网站目标页应尽量独占一个普通 Google Chrome 窗口：先用 `browser_list_tabs` 查找同 origin 目标页；如果已存在目标 tab 但混在其它窗口里，用 `browser_open_tab({ tabId, newWindow: true, active: true })` 把它拆到独立窗口；只有完全没有同 origin 目标页时，才用 `browser_open_tab({ url, newWindow: true, active: true })` 获取初始目标。这里的独立窗口不是独立 Chrome 进程或独立 profile，避免制造同 bundle 多进程导致 VirtualHID 错窗。
- 在 scene / 招聘网站执行链路里，`browser_open_tab` 只能用于初始目标获取、恢复 scene 目标 URL 或拆窗；进入站内其它路径、点击链接、筛选、提交、下载等阶段推进必须走 `hid_*`，再用 browser 观察确认结果。
- `browser_reload_extension` 只能在外部维护流程中使用，用来恢复 browser MCP runtime；不能交给 autonomous scene 当成任务内恢复动作，否则会主动打断当前 native-host / socket 链路。
- 需要真实点击、输入、滚动时，统一走 `hid_*`。
- 需要截图辅助定位时，可用 `browser_screenshot`，但如果传入 inactive `tabId` 会失败返回；必须先显式 `browser_select_tab` 激活目标页。
- 下载记录和本地路径定位走 `browser_locate_download` 这类 background/downloads 只读证据，不走页面 JS、mock DOM 标记或 fixture URL 直连。
- `mcp-browser-chrome` 维护了页面 JS 可观测面验证：只读观察工具、download location lookup 和 active-tab 截图不应留下页面 JS 可见信号；tab 切换会触发 `visibilitychange/focus/blur`，这是 tab 管理行为的天然可见性，不是页面输入能力。

---

## 3. `browser_snapshot` 详解（Agent 最常用）

### 3.1 入参

```jsonc
{
  "tabId": "optional — 不传就用当前激活 tab",
  "includeText": false,         // 要不要夹带每个 clickable 的 text（默认 false，省 token）
  "clickableLimit": 200         // 最多返回多少个 clickable，防止快照撑爆
}
```

### 3.2 返回结构（Agent 解析重点）

```jsonc
{
  "url": "...",
  "title": "...",
  "viewport": {
    "width": 1280,
    "height": 720,
    "devicePixelRatio": 2,
    "scrollX": 0,
    "scrollY": 0,
    "screenX": 0,                  // window.screenX —— 浏览器窗口在屏幕上的左上角
    "screenY": 25,                 // window.screenY
    "visualViewport": {            // 可选；pinch zoom 时非 null
      "scale": 1.0,
      "offsetLeft": 0,
      "offsetTop": 0
    }
  },
  "document": {                    // 文档绝对坐标（含滚动）
    "width": 1280,
    "height": 4800
  },
  "clickables": [
    {
      "ref": "@e37",               // 本次 snapshot 内有效，下次 snapshot 会重置
      "tag": "button",
      "role": "button",
      "text": "Submit",            // 仅当 includeText:true 时存在
      "framePath": [],             // 主文档为空；iframe 里的元素给出同源 frame 路径
      "shadowDepth": 0,            // 在第几层 open shadow root
      "detectedBy": "role",        // role / selector / clickListener / ...
      "signature": "a8f2c3e9b40e1d77",   // FNV-1a 64 bit hex；(host, sig) 是稳定 key
      "viewport": { "x": 420, "y": 312, "width": 120, "height": 40 },
      "document": { "x": 420, "y": 1112, "width": 120, "height": 40 }
    }
  ]
}
```

### 3.3 signature 是什么？怎么用？

`signature` 是 `mcp-browser-chrome` 对每个 clickable 元素计算的 FNV-1a 64 bit 哈希，输入是 `host | role | text | cssPath`。它的特性：

- **稳定**：刷新页面、甚至跨会话，只要结构没变就不变
- **中立**：`browser-mcp` 不解读它的业务含义
- **组合键**：Agent 应把 `(host, signature)` 当作一个元素的稳定身份

Agent 用它来做两件事：

1. **喂给 VirtualHID 学习**：`hid_action` 的 `context.element.sig = signature`；VirtualHID 据此把"在这个元素上的操作"聚合成可学习的模板
2. **跨快照去重 / 缓存**：Agent 自己可以用 `(host, signature)` 当 cache key，避免每次都重新思考"这是登录按钮"

---

## 4. `VirtualHID` 工具清单（MCP）

VirtualHID 对外是一个 MCP stdio server。实现上 MCP shim 会连接 VirtualHID 本地 HID/HUD runtime，但这是 VirtualHID 内部 IPC，**Agent 不需要关心，也不能绕过 MCP 直接调用**。

### 4.1 工具表（10 个）

| 工具 | 主要 input 字段 | 用途 |
|---|---|---|
| `hid_action` | `id, target?, geometry?, primitives, context, options?` | **核心**：执行一串键鼠原语，并返回执行计划与执行证据 |
| `hid_state` | `{}` | 读当前状态（kill switch / 修饰键 / 权限 / post mode / ...） |
| `hid_stop` | `{}` | 主动停止正在跑的 action |
| `hid_unlock` | `{}` | kill switch 触发后恢复 |
| `hid_observe` | `{ enable, host?, taskId? }` | 开关被动观察（学习数据源） |
| `hid_profiles_list` | `{ host? }` | 列当前站可用 template |
| `hid_profiles_get` | `{ host, sig, taskId?, action }` | 取具体 template 参数 |
| `hid_profiles_forget` | `{ host, sig? }` | 忘掉某站 / 某元素的学习结果 |
| `hid_trace_tail` | `{ sinceEventId? }` | 轮询未标注的真实用户事件（observe 模式产出） |
| `hid_trace_commit` | `{ eventId, elementSig, role?, host, taskId?, stage? }` | 给真实事件打上元素身份，写回学习表 |

### 4.2 错误码（MCP 响应里的 `isError: true` + 文本前缀）

| 前缀 | 含义 | Agent 应对 |
|---|---|---|
| `E_BUSY` | 有别的 action 在跑 | 退避重试 |
| `E_KILL_SWITCH` | kill switch 已触发 | 停手，提示用户；等 `hid_unlock` |
| `E_NO_TARGET` | 找不到目标窗口 | 先补全 `browser_target` / 窗口信息；必要时再 `browser_select_tab` |
| `E_PERMISSION` | 缺 Accessibility / Input Monitoring | 提示用户去系统设置授权 |
| `E_PRIMITIVES_REQUIRED` | 没传 HID primitives 或传了空数组 | 回到 browser snapshot / target_regions，用 clickPoint 或允许落点构造 `click/type/scroll` 等对外原语后再试 |
| `E_PRIMITIVE_INVALID` | primitive 缺少 `type` 或必需坐标/文本字段 | 修正 primitive schema，不要只传空对象 |
| `E_CONTEXT_REQUIRED` | 没传 `context` | 必须带 `host` + `element.sig` 再试 |
| `E_PROFILE_MISS` | 要求用 template 但没学到 | 降级到默认拟人参数 |
| `E_NOT_FRONTMOST` | `postMode=global` 但窗口非前台 | 先激活，或切 `postMode=auto` |
| `E_POST_MODE_UNSUPPORTED` | `postMode=pid` 却要投点击/输入 | 切 `global` 或 `auto` |
| `E_DAEMON_UNREACHABLE` | Swift daemon 没起 | 提示用户启动 daemon |

---

## 5. `ActionContext`：Agent 独家承担的业务贯穿

`ActionContext` 是 **Agent ↔ VirtualHID** 的契约。`browser-mcp` **完全不感知** 这个结构。

### 5.1 最小可用 schema

```jsonc
{
  "host": "recruit.example.com",
  "url": "https://recruit.example.com/candidates/42",
  "element": {
    "sig": "a8f2c3e9b40e1d77",         // 来自 browser_snapshot 的 signature —— 学习 key
    "role": "button"                   // 可选，VirtualHID 仅在"敏感过滤"里看一眼
  },
  "taskId": "review-candidate",        // Agent 自己定义的任务标识
  "stage": "submit",                   // Agent 自己定义的阶段
  "hints": {
    "urgency": "normal"                // VirtualHID 用它调速度
  }
}
```

### 5.2 网页 host 的来源和传递

网页目标场景中，`host` 必须来自浏览器原始语义，而不是 Agent 凭空编写：

```text
browser_list_tabs / browser_get_active_tab / browser_snapshot 的 URL
  -> browser_target.host / browser_target.url / browser_target.tab_id
  -> hid_action.target.host + hid_action.context.host
  -> VirtualHID profile / trace / learning / execution attribution
```

`context.host` 是 VirtualHID 的学习、trace、profile 和执行归因键，不是站点适配开关。Agent 可以把 browser 原始 URL 规范化出的 host 传下去，也可以让 scene runtime 从已观测 tab/snapshot 补齐；但不能因为“这是某招聘站”而写站点分支或凭空生成 host。

非网页桌面目标可以使用其它稳定 target/context 归因字段；不要把网页 host 规则扩大成所有 HID 场景的硬必填。

### 5.3 VirtualHID 白名单字段（超出这些字段一律不看）

- `host`：网页目标的 profile / trace 归因主键，必须能追溯到 browser 原始 URL、active tab 或 snapshot
- `element.sig`：profile 查询主键
- `element.role`：仅用于敏感过滤（password 输入框事件 drop）
- `taskId` / `stage`：profile 查询的精细化维度
- `hints.urgency`：拟人参数调速

`ActionContext` 不承载窗口、tab、坐标或页面几何；这些信息应放在 `hid_action.target` / `hid_action.geometry` 或上层 scene contract 中。

**不允许**让 VirtualHID 根据 `host` 做"这是 linkedin 所以特殊处理"一类业务判断；也不允许 Agent 在 runtime 里写“这是某站所以补某 host”的站点分支。host 只能从 browser 观察语义传递或归一化而来。

---

## 6. 落点与坐标责任边界

当前约定里，**坐标换算不再由 Agent 负责**。

- Agent 负责提供：
  - 目标应用 / 窗口 / `tabId` / `host`
  - 当前页面里的固定目标点、候选区域或可见性提示
  - `scrollOffset`、`pageScale`、`viewportSize`、元素 bbox / clickPoint 等页面坐标证据
  - 要执行的动作意图和顺序，例如“若元素已在当前视口则点击，否则先滚到可见再点”
- VirtualHID 负责：
  - 根据 `target` 生成目标激活计划，并在真实执行路径中确认前台目标
  - 计算视口坐标到 macOS 绝对坐标的映射
  - 生成鼠标轨迹、滚动量和最终落点计划
  - 返回动作结果、`plan` 与 `verification` 执行证据

所以 Agent 不应再把 `browser_snapshot` 里的坐标直接换算成最终 `CGPoint`；应把页面语义、目标区域和动作意图传给 VirtualHID。

`viewportInScreen`、`screenX/screenY` 这类屏幕坐标最多只能作为兼容诊断字段；browser / recruit-station 不承担屏幕坐标权威，VirtualHID 必须通过 macOS AX/CG/目标窗口证据解析真实 viewport/window 并完成 screen 坐标换算。

`verification` 只说明 HID 执行层证据，例如注入事件、最终指针、焦点确认。页面语义是否成功，仍必须由 `browser_snapshot` / recruit-station 业务结果确认。

### 6.2 recruit-station 侧合同建议

在 `recruit-station` 里，推荐把这组信息放进 `delegate_scene_context` 的 `environment_requirements` / `context`：

1. `browser_target`：`application`、`window_title`、`tab_id`、`host`、`url` / `url_pattern`
2. `computer_target`：`application`、`window_title`、`post_mode`、`activation_policy`
3. `target_regions`：页面里的候选落地区域、signature、可见性提示、bbox
4. `action_plan`：如“已在视口则点击，不在则先滚到可见再点”“若下载入口出现则触发下载并验证本地文件”

这层合同的目标是：**Agent 只表达业务意图和稳定目标，不表达最终像素点。**

---

## 7. 典型工作流

### 7.1 "读页面 → 点一下按钮"

```text
1. browser_list_tabs / browser_get_active_tab —— 确认目标 `tabId`
2. browser_snapshot { includeText: true }
3. 在 clickables 里挑目标元素，记下 signature、viewport bbox、当前是否可见
4. 组装 scene 合同：`browser_target + computer_target + target_regions + action_plan`
5. hid_action / scene execution —— 执行层负责目标激活计划、滚动计划、坐标换算、拟人化轨迹和最终落点
6. 如果返回 E_NO_TARGET / E_NOT_FRONTMOST → 更新目标上下文后重试，必要时切 `postMode: "auto"`
7. 读取 `plan` / `verification` 判断 HID 层是否执行完整
8. 执行后回到步骤 2 拿新 snapshot 确认页面语义状态变化
```

### 7.2 "学习用户习惯"（可选，质量提升路径）

```text
1. hid_observe { enable: true, host: "recruit.example.com", taskId: "review" }
2. 用户手动操作页面（几分钟～几小时）
3. 定期调 hid_trace_tail —— 拿到未标注的真实事件列表
4. 对每条事件：
   a. 从 Agent 自己缓存的 snapshot 窗口里找时间戳最近的一份
   b. 在 clickables 里找 viewport 坐标距事件最近（≤8px）的元素
   c. hid_trace_commit { eventId, elementSig: el.signature, role: el.role, host, taskId, stage }
5. 触发 profiles rebuild（当前由 daemon / 上游工具链负责，Agent 不应在业务 prompt 里硬编码重建细节）
6. 下次执行 hid_action 带同样的 (host, sig)，VirtualHID 会自动用学到的节奏
```

### 7.3 "紧急停止"

- **用户**：物理键盘连按 **5 次 ESC**（1.5s 内）→ VirtualHID kill switch 触发，释放所有修饰键，蜂鸣
- **Agent**：任何 `hid_action` 会变成 `E_KILL_SWITCH`；此时**立即停手**，提示用户"已触发紧急停止，如需恢复请说明"，等用户确认后调 `hid_unlock`

---

## 8. 红线（Agent 必须遵守）

1. **不要让 `browser-mcp` 做动作**：它是只读的；想点击/输入一律走 `hid_*`
2. **不要在 MCP 工具调用里泄漏 ActionContext 给 browser-mcp**：`browser_*` 的 input schema 没有 `context` 字段
3. **不要复用跨快照的 `@eN` ref**：ref 每次 `browser_snapshot` 都会重置；跨快照稳定的是 `signature`
4. **不要省略目标上下文**：至少把目标 `tabId` / 窗口 / `host` 放进 scene 合同；是否先显式 `browser_select_tab`，由当前执行策略决定
5. **不要在 `postMode=pid` 下发 click/type**：会直接 `E_POST_MODE_UNSUPPORTED`
6. **不要关闭 kill switch**：永远不要"为了不被用户打断而绕开 kill switch"；那是用户的最终保险
7. **敏感字段**：`password` 输入永远通过 `primitives: [{ type: "type", text: ... }]`，VirtualHID 会自动 drop 它在 observer 里的痕迹；但 Agent **不应**把密码原文写进 prompt / 日志
8. **不要把 `signature` 当全局唯一 ID**：它是 `(host, sig)` 组合键的一半；不同站的 sig 可能碰撞

---

## 9. 工具参考的追加阅读（可选，调试时才需要）

本文档之外的这些文档是**实施细节**，Agent 正常工作不需要读，但出问题时可以查：

- `~/AgentProjects/mcp-browser-chrome/docs/completed/2026-04-23-browser-mcp-signature-impl_cn.md`
- `~/AgentProjects/mcp-browser-chrome/docs/plan/active/2026-04-23-hid-and-learning-plan_cn.md`（跨系统主方案）
- `~/AgentProjects/VirtualHID/docs/plan/active/2026-04-23-virtualhid-impl_cn.md`
- `~/AgentProjects/mcp-browser-chrome/docs/specs/2026-04-23-chrome-mcp-readonly-acceptance_cn.md`

---

## 10. 修订记录

| 日期 | 修改人 | 内容 |
|---|---|---|
| 2026-04-23 | Cursor Agent | 初稿；统一两套工具入口为 MCP；`browser_*` 15 个 + `hid_*` 10 个；坐标换算公式；典型工作流；红线 |
| 2026-04-23 | Cursor Agent | §9 追加阅读路径与 mcp-browser-chrome 文档归档一致：`docs/completed/`（已完成的 plan）、`docs/specs/`（验收标准） |
| 2026-04-25 | Codex | 同步 `browser_*` 16 工具、截图 active-tab 边界、页面 JS 可观测面验证、`hid_action.target/geometry` 与 `plan/verification` 执行证据口径 |
