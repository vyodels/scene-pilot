# 任务：发现候选人

围绕当前招聘目标，在 human 当前使用的普通浏览器（非 AI 模式浏览器）中发现候选人，并返回结构化发现结果。

- 外部事实来源是当前可通过通用浏览器工具读取的招聘平台页面；目标存储是共享工作区候选人库，读取用 `list_candidates`，写入用 `upsert_candidate`。
- 优先复用普通浏览器里已经打开且能够继续任务的招聘平台候选人列表页、推荐页、候选人详情页或其它等价页面。只有当当前工具可达范围内的证据足以支持“没有可复用目标页”时，才自行打开招聘平台并进入可执行页面。
- 在判断普通浏览器里是否已经存在可复用目标页时，优先使用 `browser_list_tabs` 枚举普通浏览器全部窗口里的页签；只有在必须聚焦当前窗口时，才显式传 `currentWindowOnly=true`。不要把“当前窗口未见目标页”直接当成可以新开页的依据。
- 一旦从页签枚举结果里定位到候选招聘页面，应立即记录并复用该页面的精确 `tabId`；后续 `browser_snapshot`、`browser_query_elements`、`browser_get_element`、`browser_debug_dom`、`browser_wait_for_*` 等页面读取或等待动作，都应显式带上这个已确认的 `tabId`，不要退回依赖“当前激活 tab”。
- 如果浏览器工具的 tab / page 可见范围只覆盖当前窗口，而不能确认其它普通浏览器窗口是否已存在可复用目标页，不要把“当前窗口未见目标页”当成直接新开页面的依据；应把这种工具作用域不足明确表述为 blocker，而不是绕过可能已经打开的可复用招聘页。
- 不依赖预标注页面实体。应根据浏览器快照、可见页面文本，以及用提供工具可读取到的 DOM 或页面状态，自行判断候选人列表、资料面板、在线简历线索和候选人详情。
- 多个招聘页同时打开时，优先检查候选人列表、推荐流、候选人详情或其它最能直接支撑当前发现任务的页面，而不是随机选择当前激活页。
- 先用页面快照理解当前场景；当快照文本不足以判断页面结构或提取候选人字段时，再用 `browser_query_elements`、`browser_get_element`、`browser_debug_dom` 或等价页面读取工具补充证据。
- 优先抽取证据而不是额外动作。除非目标明确要求且操作仍处于已批准的工具边界内，否则不要发送消息、不要索要简历，也不要对招聘站点做不必要变更。
- 如果当前场景还不足以形成可信候选人记录，应继续检查当前可达范围内的其它招聘页；不要因为单个页面证据不足就过早结束。
- 当页面理解需要多轮观察、局部等待或候选人详情比对时，优先通过 `delegate_scene_context` 封装 scene contract。scene contract 至少应带上稳定的 `browser_target`；仅在后续 scene 确实需要浏览器/HID 落点时，再补 `target_regions` 或 `action_plan`。
- 把 `browser_target`、`target_regions`、`action_plan`、以及后续可能复用的简历 `artifact_expectations` 视为可传递的 tool surface 合同字段。若当前阶段已经看见候选人详情入口、附件落点或下载线索，应尽量把它们整理成结构化合同，而不是只留在自然语言摘要里。
- 若后续 scene 可能使用 HID 执行网页目标动作，`browser_target.host/url/tab_id` 必须来自 `browser_list_tabs`、active tab 或 `browser_snapshot` 的原始 URL 语义，并沿 scene contract 传递给 HID 归因字段；不要根据站点名称、按钮文案或平台猜测 host。
- scene 子上下文的完成结果应保持业务级：返回候选人事实、来源证据、在线简历或附件线索，以及可直接传给 `upsert_candidate` 的规范化字段。不要把 tab、DOM ref、点击路径或一次性页面标签写回主历史。
- 若本轮 run 形成稳定经验，应把后续 skill distillation 候选描述成业务动作，例如“推荐候选人列表获取”“候选人详情事实抽取”或“在线简历线索获取”，并让 skill 输入输出优先复用当前 scene contract 与业务结果字段，而不是页面脚本。
- 只使用通用招聘页面语义进行判断，不假设任何站点专用 selector、按钮文案、路由、页面分支、词表或预接好的平台适配器。
- 只有在登录、验证码、权限、设备绑定或其它明确的 human-only blocker 下，才请求 human 协助。human 的职责是解除阻塞，而不是代替 Agent 打开页面或完成站内导航。
- 成功时返回紧凑的结构化摘要，至少包含 `created`、`updated`、`skipped`、`blocked`、候选人事实、来源证据，以及任何当前场景中可验证的在线简历或附件线索。
