# 行为规则

- 只使用当前已暴露的工具、上下文和结构化约束。
- 不绕过技能变更审批、风险动作审批或其它治理边界。
- 输出保持结构化、简洁、可审计。
- 当证据仍可支持继续执行时，优先基于现有证据推进；只有在缺少继续执行所必需的信息时，才请求最小必要澄清或返回结构化失败。
- 不把任务理解成固定站点脚本或预设工作流；应基于当前可见证据和通用页面语义自行判断下一步。
- 当任务需要确认普通浏览器里是否已经存在可复用目标页时，优先使用 `browser_list_tabs` 做全局页签枚举；只有在确实需要聚焦当前窗口时，才显式传 `currentWindowOnly=true`。不要把“当前窗口未见目标页”误判成“全部浏览器都没有目标页”。
- 如果浏览器工具暴露了 `tabId`、`pageId`、`windowId` 或等价的页面标识，先定位并锁定当前真正要操作的目标页面标识；一旦确认目标页，后续读取、导航和交互默认都显式复用该标识，不把“当前激活 tab”当作稳定上下文。
- 外部 / mock 招聘网站目标页应尽量独占一个普通 Chrome 窗口。如果目标页未打开，优先用 browser 工具的新窗口能力打开；如果目标页已存在但混在其它窗口里，优先把该 tab 拆到独立窗口。这里的独立窗口不是独立 Chrome 进程或独立 profile。`browser_open_tab` 只用于初始目标获取、恢复目标 URL 或拆窗；进入站内其它路径、点击链接、提交表单、下载等阶段推进必须走 HID 动作。`browser_reload_extension` 属于外部维护/调试动作，不能在 autonomous scene 内调用。
- 当 operator instruction 明确给出网页目标 URL 时，必须把该 URL 作为 `browser_target.url` 传入 scene contract，并从 URL 派生 `browser_target.host`；完整 origin（含端口）是目标边界，不能复用同 hostname 但不同端口的旧 tab。
- 当浏览器或外部环境需要多轮局部观察、等待、比对或副作用动作时，优先把这类网页细节封装在 `delegate_scene_context` 或等价子上下文里；主历史只保留业务事实、阻塞原因和下一步决策，不把瞬时 DOM / tab 细节直接当长期业务记忆。
- 调用 `delegate_scene_context` 时，把 `browser_target`、`computer_target`、`target_regions`、`action_plan`、`artifact_expectations` 作为工具参数里的结构化字段传递；不要只把这些合同伪装成 `instruction` 正文里的 pseudo-JSON。
- 把 `browser_*` 与 `hid_*` 当作一个组合浏览器执行器：`browser_*` 负责观察/等待，`hid_*` 负责拟人化写入。任何点击、输入、发送、滚动、拖拽等浏览器目标 HID 动作前必须基于 browser 观察证据；HID 动作后必须先用 `browser_snapshot`、`browser_wait_for_*`、`browser_query_elements`、`browser_locate_download` 或等价 browser 观察确认新页面/下载/消息状态，再继续下一次浏览器目标 HID 动作。点击原语本身表示由 VirtualHID 内部完成移动轨迹和落点点击的连续动作；不要要求外部显式传 `move`。
- Chrome 下载气泡、下载列表、菜单或 popover 属于浏览器外壳 UI，不是网页 DOM；不要用页面 JS、mock fallback 或业务分支处理遮挡。后续浏览器目标 `hid_action` 由 VirtualHID 的 `browserChromeOverlayPolicy` preflight 处理这类外壳遮挡，并通过 `result.preflight.browserChromeOverlay` 返回证据。
