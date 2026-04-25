# Autonomous Agent UI 级 E2E 测试与自迭代调通计划

> Status: active
> Supersedes: -
> Superseded by: -
> Distilled into: -
> Last reviewed against code: 2026-04-20
> Historical source path: docs/superpowers/plans/2026-04-19-autonomous-ui-e2e-test-plan.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Browser Tooling Note (2026-04-24):** 本计划中的 browser tooling 表述部分早于 `browser-mcp` 只读化和 `VirtualHID` MCP 接入。涉及 browser / HID 的当前真实口径，应以 [`docs/guides/agent-operator-guide_cn.md`](../../guides/agent-operator-guide_cn.md) 和 [`2026-04-24-recruit-agent-browser-computer-runtime-follow-up-plan.md`](./2026-04-24-recruit-agent-browser-computer-runtime-follow-up-plan.md) 为准。

**Goal:** 让 Codex 通过 chrome-devtools MCP 模拟 human 的方式，驱动 Recruit Agent 桌面主程序的 UI，反复运行下列端到端场景，直到 **Autonomous Agent 在 zhipin.com 上为每个 JD 拿到 3 个"含离线简历 + 含联系方式"的候选人**，并且这些数据全部上传到主程序、在工作台看板里可见、沟通记录在投递记录沟通界面可查。

**Codex 角色：** Codex 是测试驱动 + 修复驱动 + 假装 human 的"上帝视角运营者"——
- 用 chrome-devtools MCP 操作 desktop UI（点击悬浮球、创建 goal、批准/拒绝、查看候选人卡片）。
- 用 chrome-devtools MCP 抓 console / network / DOM 验证 UI 实际状态。
- 当任一测试用例失败时，Codex 必须**自行定位故障层**（prompt / Agent runtime / API / UI），改完代码再重启服务再跑，直到通过。
- Codex **不直接驱动 zhipin.com**——zhipin 由桌面主程序里的 LLM 通过已注册的 `browser-mcp` 服务操作。Codex 只是触发 Agent 并验证结果。

**Tech Stack:** Electron + React 桌面主程序、FastAPI + SQLite 后端、Anthropic/OpenAI provider、`browser-mcp`（操作 zhipin.com）、chrome-devtools MCP（操作 desktop UI）、Python ≥ 3.14、Node 20+。

---

## 0. 执行约束

### 0.1 优先级

| 等级 | 内容 | 完成判据 |
|------|------|---------|
| P0 | T1 + T2 + T3 + T4 + T5 全部通过 **且** §0.6 核心链路 CRUD 完整性达标 | 主程序工作台至少 1 个 JD 下能看到 3 个完整候选人（含离线简历附件 + 联系方式 + 至少 1 条沟通记录），且 §0.6.1 表中每个链路在 UI 上都能完成创建 / 修改 / 删除 |
| P1 | T6 工作台侧边栏功能回归通过 | 投递记录跟进 / 状态流转 / 详情抽屉全部可点可改 |

### 0.2 强约束（Codex 不得自行发挥）

- 不得在测试通过率不到 100% 的情况下声明"任务完成"。
- 不得为了通过测试 mock 任何关键链路（zhipin 同步必须经过真实 browser-mcp；候选人字段必须真的来自 zhipin 拉取，不允许 fixture 顶替）。
- 不得跳过 wait_human 审批门——Codex 必须在 UI 上**真实点 approve 按钮**模拟 human 操作。
- 不得改测试断言来"让测试变绿"；只允许改实现代码 / prompt 让真实行为达成断言。
- 不得删除 `2026-04-19-autonomous-e2e-and-chat-overlay-plan.md` 已经定义的悬浮球 / 双 Agent / 7 tab 结构；本计划假设那个 plan 已经实施完成或正在并行实施，命名以那个 plan 为准。
- 不得为了复用旧代码而保留与本计划评分提示词冲突的旧 prompt。
- 不得跑 `git commit` 自动提交——每次修复后 push 到工作分支即可，commit 由 human 在 review 阶段决定。

### 0.3 拟人测试约束：所有"动作"必须走 UI，API 只能用来"看"

**核心原则：** 测试用例中**任何会改变系统状态的动作**——创建 goal、批准/拒绝 OperatorInteraction、保存 prompt、状态流转、编辑备注、添加 tag 等等——Codex 必须通过 chrome-devtools 在 desktop UI 上**像 human 一样点击 / 输入 / 提交**完成。**不允许**为了图省事直接 `POST /api/...` 或 `curl -X PATCH ...` 绕过 UI 来"促成"测试通过。

#### 0.3.1 允许 vs 不允许

| 用途 | 是否允许走 API |
|------|--------------|
| **观察后端状态用于断言**（GET 请求 / 读 SQLite / 读 SSE / 读事件流） | ✅ 允许，且鼓励——这是"上帝视角验证" |
| **debug 排查问题**（curl 看响应、`/health`、`/mcp/health`、读日志） | ✅ 允许 |
| **测试环境准备 / 拆解**（删 SQLite、`/health` 探活、启动服务、热重启） | ✅ 允许（非业务流程） |
| **业务动作**：创建 goal / approve / reject / 编辑 prompt / 保存配置 / 状态流转 / 编辑候选人字段 / 上传简历 | ❌ **不允许走 API**，必须在 UI 上点 |
| **模拟 human 审批**（T3 中点 approve 按钮） | ❌ **不允许走 API**，必须 chrome-devtools click |

#### 0.3.2 UI 缺能力时怎么办（这才是真正考验 Codex 的地方）

如果 Codex 发现某个测试动作在 UI 上**根本没有入口**（例如缺一个"批准全部"按钮 / 缺一个"重启 Agent"按钮 / 缺某个字段编辑入口），处理顺序：

1. **先停下评估**：这个动作在产品语义上 human 是不是真的应该能做？如果是，说明 UI 缺能力。
2. **补 UI（必要时一并补底层 API）**：在前端加按钮 / 加表单 / 加菜单项，必要时在后端补对应 endpoint。补完之后再用 chrome-devtools 走新 UI 完成动作。
3. **不要走 API 绕过**：哪怕"先 API 暂时跑通后面再补 UI"也不允许——这会让 UI 永远缺这块，且测试覆盖出现盲区。
4. **写 commit 注明**：`commit message` 里写"为了让 T{n} 通过，补了 UI: <按钮/表单/页面>"，让 human review 知道改动来由。

#### 0.3.3 反面示例（Codex 不要做）

- ❌ "OperatorInteraction approve 按钮在 UI 上找不到，先 `curl -X POST /api/operator-interactions/{id}/approve` 让 T3 跑下去。"
  - ✅ 正确做法：去 §3 那个 plan 的"审批 tab"补上 approve 按钮，再用 chrome-devtools 点。
- ❌ "悬浮球的 '新建 goal' 表单没做完，先用 `curl -X POST /api/agents/autonomous/goals` 创建 goal 让 T3 跑下去。"
  - ✅ 正确做法：把表单做完，用 chrome-devtools 在表单里填完点提交。
- ❌ "候选人状态流转的 dropdown 显示但点了没反应，写一个 Python 脚本直接改数据库 `application.state`。"
  - ✅ 正确做法：修 dropdown click handler 的 bug，再用 chrome-devtools 点 dropdown 触发流转。

#### 0.3.4 例外白名单

只有以下三类操作允许走 API / CLI 而不需要 UI：
1. 服务启停、SQLite 清空、`/health` 探活——属于"测试基建"。
2. backend 单测 / typecheck 触发——属于"代码质量门"。
3. 通过 `mcp/health` 探活 browser-mcp 是否在线——属于"基础设施健康检查"。

除上述三类，业务动作一律走 UI。

### 0.4 唯一允许中途停止的情况

1. zhipin.com 反爬把账号封了 / cookie 过期，需要 human 重新登录 browser-mcp。
2. browser-mcp 服务自身崩溃且重启后仍不可用。
3. 连续 5 轮自迭代修复都没有让同一个失败用例通过——这时 Codex 应该停下来把"失败现场 + 已尝试的 5 种修复方案"汇报给 human。
4. 任何涉及"扣费 / 真实付款"的操作（理论上不应出现，出现就停）。
5. Codex 自己意识到要写 zhipin / boss 站点专属的解析 / 操作代码才能让某个测试通过（区别于"`source` 字段存字符串值"的允许情形）——必须停下来，参见 §0.5。

### 0.5 职责边界：Codex 提供工具包，Agent 完成业务工作

**核心原则：** Codex 负责**主程序里给 Agent 提供的通用工具包**和**通用基础设施**；Agent 负责**用这些工具去外部招聘平台真正完成业务**。Codex 不许越线替 Agent 干活。

#### 0.5.1 Codex **应该**做的事（这是本计划要求的工作量）

- **完整的招聘业务工具包 / plugins**（平台中性，围绕"招聘领域 schema"建模；项目级 plugin 资产/配置/元数据统一落在 `.recruit-agent/plugins/recruit/*`，backend 仅在 `services/backend/src/recruit_agent/plugins/recruit/*.py` 保留可 import 的薄运行时 shell / mount code，给 Agent 提供"可直接调用的完整招聘业务能力集"）。**不是只凑够下面这几个**——凡是招聘全流程所需的业务动作，都应当有一个平台中性的业务工具覆盖它，才能让 Agent 不用为了"这个业务语义在主程序里没入口"而自己造轮子或调用底层原语硬拼。最低基线包含但不限于：
  - JD 管理：`recruit.upsert_job_description(payload)`、`recruit.list_job_descriptions()`、`recruit.archive_job_description(jd_id)`、`recruit.edit_job_description(jd_id, patch)`。
  - 候选人全生命周期：`recruit.upsert_candidate(payload)`（含发现 / 在线摘要更新 / 离线简历关联 / 联系方式补齐）、`recruit.list_candidates(filter)`、`recruit.edit_candidate(candidate_id, patch)`、`recruit.archive_candidate(candidate_id, reason)`、`recruit.delete_candidate(candidate_id)`。
  - 简历：`recruit.attach_resume(candidate_id, file_path, source_hint)`、`recruit.replace_resume(candidate_id, file_path)`、`recruit.delete_resume(candidate_id)`、`recruit.get_resume(candidate_id)`。
  - 评分：`recruit.score_candidate(candidate_id, breakdown)`、`recruit.get_scoring_rubric()`、`recruit.save_scoring_rubric(rubric)`。
  - 状态流转：`recruit.transition_application(application_id, to_state, reason)`、`recruit.list_state_machine()`。
  - 沟通：`recruit.record_outbound_message(candidate_id, content, channel_hint, status="draft"|"sent")`、`recruit.list_threads(candidate_id)`、`recruit.edit_message(message_id, patch)`、`recruit.delete_message(message_id)`。
  - 审批：`human.request_approval(action_kind, payload)`、`recruit.list_operator_interactions(filter)`、`recruit.resolve_operator_interaction(interaction_id, decision, reason)`。
  - 标签 / 备注：`recruit.add_tag(candidate_id, tag)`、`recruit.remove_tag(candidate_id, tag)`、`recruit.set_note(candidate_id, note)`。
  - 查询 / 统计：`recruit.list_pending_jds()` / `recruit.list_pending_candidates()` / `recruit.get_goal_progress(goal_id)` 等。
  - **评判准则**：凡是 human 会在 UI 上做的招聘动作、以及 Agent 需要在自动化流程中完成的业务判断，都应该有一个对应的平台中性业务工具；只能做一个"底层原语集合"把业务语义都推给 Agent 自己在 prompt 里拼是**不允许**的——那是给 Agent 做繁重脑力劳动，不是给它提供完整业务工具包。
- **通用基础工具包**：
  - `browser_*` —— browser-mcp 透传：读页面、列 tab、切 tab、等待、快照、查元素、截图、读 cookie。
  - `hid_*` —— VirtualHID 透传：真实键鼠注入、窗口激活、观察、trace、profile 学习。
  - `delegate_scene_context` —— 把 browser / computer 细节封装到隔离 scene 子上下文。
  - `bash.run(cmd)` 或 `shell.exec` —— 通用命令行（受沙箱约束）。
  - `http.fetch(url, ...)` —— 通用 HTTP。
  - `fs.read / fs.write` —— 通用文件读写（受沙箱约束）。
  - `human.request_approval(action_kind, payload)` —— 通用人机协作。
  - `skill.create / skill.invoke` —— 让 Agent 自己沉淀 + 复用 skill。
- 这些工具的契约必须是**平台中性的**：参数与返回值都按"招聘领域通用 schema"或"基础设施通用 schema"建模，**不在签名上绑死任何站点**。
- 候选人 / JD 的唯一键设计成 `(source: str, external_id: str)` 是允许的，`source` 字段里出现 `"zhipin"` 这种数据值也是允许的——**这是数据，不是代码逻辑分支**。
- **业务层的"招聘平台来源映射"是允许的、本就需要的**：诸如 `platform` / `source_platform` / `platform_candidate_id` / `platform_jd_id` / `platform_url` / 招聘平台枚举常量等字段、模型、API schema、UI 标签——这些是多平台招聘数据建模的正常组成部分（候选人需要标"来自哪个平台"才能去重 / 跳转 / 展示来源徽章），**不在本节边界约束范围内**。本节真正限制的只有"只服务于 Boss/直聘的解析与操作 tool 能力被 hardcode"这一种情形。

#### 0.5.2 Codex **不应该**做的事（**唯一被限制的形态：Boss/直聘专用解析或操作的 tool 能力被 hardcode**）

- 不要在仓库里预先写 zhipin / boss 站点专属的 parser / scraper / DOM 解析器 / selector 常量库 / 字段抽取规则。
- 不要在 `services/backend/src/recruit_agent/plugins/recruit/toolkit.py` 这类 backend 薄运行时 shell，或 `services/` 其它路径下提前生成 `def parse_zhipin_jd(...)` / `class BossResumeFetcher` / `def fetch_zhipin_contact(...)` 这类"专门替 Boss/直聘干活的工具函数"——这些是 Agent 的事。
- 不要写 `if source == "zhipin": <调用某个专属解析逻辑>` 这种**按平台分发到平台专属解析/操作的 if 分支**。（区别于"`if source == 'zhipin': badge = '直聘'`"这种纯展示/标签映射——后者属于业务展示，不在限制范围内。）
- 不要把 zhipin 的 DOM 结构、字段顺序、CSS selector、xpath 烧进 system prompt 当作"操作手册"。
- 不要为了让 T1/T2/T3 通过，临时在 toolkit 里加一个"zhipin 一键同步" / "zhipin 一键拉简历"工具——这正好是 Agent 应该靠 `browser_*` + `delegate_scene_context` + `hid_*` + 自己沉淀 skill 完成的事。
- 不要为 zhipin 反爬 / 限频 / 字段缺失写专属 fallback；如果遇到这类问题，只能改 prompt（让 Agent 自己应对）或者补**通用**的浏览器原语能力（如增加一个通用 retry 工具）。

#### 0.5.3 判定准则（Codex 在动手前自检 / 在 review 时复核）

**唯一标准：** 这段代码是不是"**只服务于 Boss/直聘 的解析或操作 tool 能力，且被 hardcode 到仓库里**"？是 → 越线；否 → 允许。

具体来说，对每一段新增 / 修改的代码，问自己：
1. **它是不是一段"工具能力"代码**（即在跑 zhipin 网页操作 / 解析 zhipin 返回内容 / 替 Agent 在 zhipin 上完成某件事的逻辑）？
   - 是工具能力代码 → 进第 2 题。
   - 不是（是数据模型 / 业务字段 / 平台来源映射 / UI 标签 / 唯一键设计 / 通用 schema）→ **允许**。
2. **它是不是仅服务于 Boss/直聘一家**（不改一行代码就没法用在拉勾 / 猎聘 / linkedin 上）？
   - 是 → 越线，撤回，让 Agent 自己用 `browser_*` + `delegate_scene_context` + `hid_*` + `skill.create` 在运行时完成。
   - 否 → 允许（说明是平台中性的通用工具）。

**典型允许示例：**
- `Candidate.platform: str` / `Candidate.platform_external_id: str` / `JobDescription.source_platform` 字段。
- 一个枚举 `KNOWN_PLATFORMS = ["zhipin", "lagou", "liepin", "linkedin"]`（仅作下拉选项 / 校验，不分发执行逻辑）。
- UI 标签 `{ zhipin: "直聘", lagou: "拉勾" }` 映射。
- `def build_platform_url(platform, external_id)` 把平台名和 ID 拼成展示用的 URL（纯字符串拼接，不操作目标站点）。
- 候选人详情抽屉里的来源徽章 / 来源跳转链接。

**典型不允许示例：**
- `def parse_zhipin_candidate_card(html_snippet)` 这种专门解析 Boss 候选人卡片 DOM 的函数。
- `class ZhipinJDFetcher` 这种"封装 Boss 网站抓取流程"的类。
- prompt 里写"zhipin 的候选人列表是 div.candidate-card"。
- toolkit 里注册一个 `tool_id="zhipin.search_candidates"` 让 Agent 直接调用（而不是让 Agent 用通用 `browser_*` / `hid_*` 自己操作）。

#### 0.5.4 自检脚本（Codex 每轮自迭代结束跑一次）

Codex 在每轮 §4 自迭代结束后，运行如下命令并把结果存到 `.codex/e2e-runs/round-{n}/boundary-check.txt`：

```bash
rg -i 'zhipin|boss' --type py --type ts \
   services/backend/src apps/desktop/src packages \
   | grep -v -E '(^|/)(tests?|__tests__|fixtures?|docs?|README|\.md:)'
```

对每一行命中，按 §0.5.3 的两道题判定：
- 命中位置是数据模型 / 业务字段 / 平台来源映射 / UI 标签 / 唯一键设计 / 枚举 / URL 拼接 → **允许**。
- 命中位置是"只服务于 Boss/直聘的解析或操作 tool 能力 hardcode"（专属 parser / 专属 fetcher / 专属 tool 注册 / prompt 里的 selector 操作手册 / 按平台分发到专属解析逻辑的 if 分支）→ **不允许，必须撤回**。

把判断理由也写到 `boundary-check.txt`，每行一句（"L42: 数据字段 platform，允许" / "L88: ZhipinJDParser 类，越线，撤回"）。human review 阶段会按这份文件抽查。

#### 0.5.5 心智模型

把 Autonomous Agent 想象成一个**新入职的人类招聘**，他有：
- 一台开了 Chrome 的电脑（= browser-mcp）；
- 一个 zhipin 已登录账号（= cookie 已就绪）；
- 一份招聘流程 SOP（= §2 system prompt）；
- 一份评分细则（= §2 评分 rubric）；
- 主程序里一组"录入候选人 / 上传简历 / 留沟通记录 / 发起审批"的**通用按钮**（= Codex 提供的 §0.5.1 通用工具包）；
- 一台终端 / 一个浏览器开发者工具（= bash / browser.eval 等通用基础工具）。

他被告知"去把 3 个候选人搞定"。剩下的——怎么打开 zhipin 的搜索页、怎么识别候选人卡片、怎么点开简历、什么时候点"沟通"按钮——全凭他自己看页面、自己思考、自己点。

Codex 的任务**不是**替他写"zhipin 自动化脚本"，而是：
- 把主程序的通用按钮做得清晰好用（§0.5.1）；
- 把 SOP 与评分细则写清楚（§2）；
- 观察 Agent 干得怎么样，干不动了就改 SOP / 改评分细则 / 完善通用按钮的语义；
- **绝不**替他写"在 zhipin 上点哪个按钮、抽哪个 div 的文字"这种代码。

### 0.6 功能完整性兜底要求：核心链路要走"完整生命周期"，缺什么补什么

**核心原则：** 跑通一遍 happy path 不算交付。每条核心链路都要把"创建 → 查询 → 修改 → 删除 / 归档"四态走完。Codex 在跑 T1–T6 的过程中，凡是发现某个生命周期环节"只在 API 中内置、UI 没暴露"或"UI 只能查、不能改 / 不能删"，必须当场按 §0.3.2 的处理顺序补齐——先补 UI（必要时一并补底层 API），不允许"先记下来回头补"。

#### 0.6.1 必查的核心链路（每条都要 CRUD 全绿）

| 链路 | 必须可用的 UI 操作 |
|------|------------------|
| Autonomous Goal | 新建 / 列表 / 详情 / 编辑 / 暂停 / 恢复 / 删除 |
| Autonomous Run（goal 下的执行实例） | 列表 / 详情 / 中止 / 重跑 |
| OperatorInteraction（审批） | 列表 / 详情 / approve / reject / 撤回（误操作回退） |
| Candidate | 手工新建（补人）/ 列表 / 详情 / 编辑核心字段（姓名 / 联系方式 / 备注 / tag）/ 状态流转 / 归档 / 删除 |
| 简历附件 | 上传 / 预览 / 替换 / 删除 |
| 沟通记录 | 列表 / 编辑草稿 / 删除草稿 / 标记已发送 |
| Agent 配置（Assistant + Autonomous 各自） | 查看 / 编辑 system prompt / 编辑评分 rubric / 保存 / 重置默认 |
| LLM provider / MCP server | 新增 / 编辑 / 删除 / 测试连通性 |
| JD | 同步触发 / 列表 / 详情 / 手工编辑（如改岗位描述）/ 归档 |

#### 0.6.2 缺失发现时的处理顺序

完全沿用 §0.3.2：
1. 评估：human 在产品语义上是否应当能做这件事？是 → 算缺口。
2. 补 UI（必要时一并补 API）。
3. **不要走 API 绕过、不要先跳过、不要"P2 再补"**——只要它在 §0.6.1 表里就必须本轮补完。
4. commit message 注明 `为了 §0.6.1 链路完整性，补 {功能}`，让 human review 能看到改动来由。

#### 0.6.3 自检脚本（每轮自迭代结束跑一次）

Codex 每轮自迭代结束后，按 §0.6.1 表逐行对照 desktop UI 实际能力，写到 `.codex/e2e-runs/round-{n}/lifecycle-check.md`，每行一条结论，格式如：

```
- Goal.删除：✅ UI 已有，路径：悬浮球 → Autonomous → 运行 tab → goal 详情 → "删除" 按钮
- Goal.编辑：❌ 缺，已补，新增按钮位于：goal 详情 → "编辑" 按钮，对应 PATCH /api/agents/autonomous/goals/{id}
- Candidate.删除：❌ 缺，未补，理由：…（仅当 human 明确同意推迟时才允许，否则不允许出现）
```

#### 0.6.4 验收门

§5 验收新增一条：`lifecycle-check.md` **不允许**出现 `❌ 缺，未补`（除非 human 在该轮 review 中显式同意推迟，并在 commit 中留下推迟理由）。

#### 0.6.5 反面场景（Codex 不要做）

- ❌ "Goal 后端 API 有 DELETE，但 UI 没暴露——T3 只跑创建 + approve 流程，删除留到下一阶段。"
  - ✅ 正确：补 UI 上的删除按钮 + 二次确认弹框，再用 chrome-devtools 走删除路径验证。
- ❌ "OperatorInteraction 误 approve 后无法撤回——但 T3 只验 approve，所以放过。"
  - ✅ 正确：补"撤回"能力（前端按钮 + 后端状态机回退）；如果产品语义上不允许撤回，至少要在 UI 上给出明确的不可撤回提示。
- ❌ "候选人详情抽屉里能看 tag，但加 / 删 tag 只能调 API——测试只查不改即可通过。"
  - ✅ 正确：补 UI 上的 tag 编辑控件，测试用例必须实际通过 UI 加一个 tag、删一个 tag、然后断言数据库一致。

---

## 1. 测试基础设施

### 1.1 启动顺序

每轮测试 Codex 必须按以下顺序启动并验证：

- [ ] `cd services/backend && python3 -m pytest -q --collect-only > /dev/null` —— 验证 Python 环境与依赖。
- [ ] 启动 backend：`uvicorn recruit_agent.server:create_app --reload --factory --port 8741`（后台运行）。
- [ ] curl `http://127.0.0.1:8741/health` 返回 200。
- [ ] 启动 desktop dev：`npm run desktop:dev`（后台运行）。
- [ ] 等待 Electron 主窗口加载完成；如果是无头跑就用 `npm run desktop:build` + headless Electron。
- [ ] chrome-devtools MCP 连接到 Electron 的 devtools 端口（参考 `apps/desktop/electron/main.ts` 中开放的端口；如未开放，Codex 在 `electron/main.ts` 里加 `--remote-debugging-port=9222`，本地测试场景安全）。
- [ ] 验证 `mcp__chrome-devtools__list_pages` 能列出 Electron 的 renderer 页面。

### 1.2 zhipin.com 前置条件

- [ ] human 已经在 browser-mcp 关联的 Chrome profile 中登录 zhipin.com BOSS 账号。
- [ ] Codex 通过后端 API 调用 `mcp/health` 验证 `browser-mcp` 服务在线，且能访问 `https://www.zhipin.com/`。
- [ ] 测试约束更新：Codex/human 不负责预先打开具体的 `zhipin.com` 页面；Agent 必须先检查普通浏览器里是否已有可用的 `zhipin.com` 活跃页，有则直接复用，没有则由 Agent 自行打开。只有登录、验证码、权限等 human-only 阻塞时，才允许请求 human 介入。
- [ ] 如果 cookie 过期，Codex 不得自动重新登录；停下来请 human 介入（命中 §0.3 第 1 条）。

### 1.3 测试数据基线

- [ ] 测试开始前，Codex 删除本地 SQLite（默认 `~/.recruit-agent/*.db`）后再启动 backend，确保从空库开始。
- [ ] 通过 UI 在 Settings 里确认 LLM provider / model 已配置。
- [ ] 通过 Agent 配置面板（悬浮球 → Autonomous Agent → 配置 tab）注入 §2 的 system prompt 与评分 rubric；保存。

### 1.4 chrome-devtools 操作约定

Codex 操作 desktop UI 时必须遵循：

- 任何点击 / 输入前先 `mcp__chrome-devtools__take_snapshot` 拿 DOM 快照定位元素。
- 任何关键步骤后 `mcp__chrome-devtools__take_screenshot` 留证据，命名 `evidence/T{n}-step{m}.png`。
- 异步等待 `mcp__chrome-devtools__wait_for` 而不是固定 sleep。
- 失败时先 `mcp__chrome-devtools__list_console_messages` + `list_network_requests`，把错误贴进失败报告再去改代码。

---

## 2. 评分 Rubric（写到 Autonomous Agent 的 system prompt 里）

### 2.1 提示词模板（Codex 必须把这段写进 `.recruit-agent/prompts/` 下对应的 Autonomous Agent prompt 文件）

```text
你是 Recruit Agent 的 Autonomous 招聘子智能体。你的目标是为每个 JD 找到 3 个"高匹配且可继续沟通"的候选人。

== 候选人合格定义 ==
一个候选人**只有在以下三件事全部完成**才算"合格候选人"：
1. 拿到该候选人的离线简历文件（PDF/DOC/DOCX），并且文件已上传到主程序。
2. 拿到该候选人的至少一种联系方式（手机 / 微信 / 邮箱），并写入候选人记录。
3. 评分通过下方 §评分规则，且该评分已写入候选人记录。

== 工作能力 ==
你有一个已登录目标招聘网站的浏览器（通过 browser-mcp 通用原语：open / snapshot / click / fill / wait_for / eval），还有主程序的一组**平台中性**写入工具（recruit.upsert_job_description / recruit.upsert_candidate / recruit.attach_resume / recruit.record_outbound_message / recruit.score_candidate / human.request_approval ...）。

**不要假设有任何站点专属 API**。你需要靠自己看页面（snapshot 出来的 DOM 文本）来理解界面、识别字段、决定下一步点哪里。如果你发现自己反复在做一段相同的"在某个网站上完成某件事"的子流程，请用 `skill.create(...)` 把它沉淀为一条 skill，下次复用——这条 skill 可以是平台专属的，但它由你产出，不是预设。

== 工作流（严格按节点推进，每个节点都要把数据上传平台）==
节点 A: 在目标招聘网站上按 JD 检索候选人列表，每发现一个候选人就调用 `recruit.upsert_candidate` 得到 candidate_id。
节点 B: 拉取候选人在线简历摘要（不含联系方式 / 离线附件），通过 `recruit.upsert_candidate` 更新候选人记录。
节点 C: 用 §评分规则给候选人打分，调用 `recruit.score_candidate`。低于 60 分直接归档。
节点 D: 评分 ≥ 60 分的候选人，调用 `human.request_approval(action_kind="request_offline_resume", ...)` 发起索要离线简历动作。
节点 E: 拿到离线简历后调用 `recruit.attach_resume` 写入存储 + 关联候选人。
节点 F: 调用 `human.request_approval(action_kind="request_contact", ...)` 发起索要联系方式动作。
节点 G: 拿到联系方式后调用 `recruit.upsert_candidate` 把联系方式补进候选人记录。
节点 H: 当本 JD 已累计 3 个完成节点 G 的候选人，停止本 JD 的扫描。

每个节点完成后必须立即调用对应的写入工具把数据落到主程序，**不要等所有节点跑完再批量写**。

== 评分规则 ==
评分由两部分组成，总分 100：
1. **JD 匹配度（70 分）**——根据 JD 文本动态生成。注意从 JD 中提取以下维度：岗位职责吻合、技术栈吻合、行业 / 业务线吻合、语言能力（如 JD 提到外语）。每个维度按 0–25 自评，加权汇总到 70 分。
2. **硬性筛选（30 分，不达标直接 0 分本项 + 总分降为 0，候选人归档）**：
   - 学历：本科及以上 → 15 分；不达标 → 候选人**直接归档**。
   - 年龄：30 – 35 岁（含两端）→ 15 分；不达标 → 候选人**直接归档**。

输出格式（JSON）：
{
  "candidate_external_id": "...",
  "score_total": 0-100,
  "score_breakdown": {
    "jd_fit": 0-70,
    "education": 0|15,
    "age": 0|15
  },
  "decision": "advance" | "archive",
  "reason": "一句话说明"
}

== 边界 ==
- 严禁绕过 wait_human 审批门去执行"索要离线简历 / 索要联系方式"。
- 严禁伪造候选人字段；如 zhipin 上没有就标 null + reason="missing_on_source"。
- 严禁直接发消息给候选人（本测试阶段不真发消息），只在主程序的"沟通界面"留草稿即可。
```

### 2.2 任务

- [ ] Codex 把 §2.1 写到 `.recruit-agent/prompts/` 下现有等价 prompt 资源文件。
- [ ] Autonomous Agent 启动时确实加载这段 prompt（`AssembleNode` 的 system message 里能搜到）。
- [ ] §2.1 的 JSON 输出格式被 Agent 的 evaluate 节点解析并存入 `Candidate.score_breakdown` 字段（如缺则补字段）。
- [ ] **边界确认**：prompt 文本中可以出现"zhipin"作为目标网站名称（这是数据 / 业务事实），但不允许写 zhipin DOM 描述、CSS selector、字段顺序、xpath 等"操作手册"。如果 Agent 智能不足以自行识别 zhipin 页面，**只允许加抽象描述**（如"招聘网站通常会有'职位列表 - 候选人列表 - 候选人详情 - 联系方式弹窗'四级页面"），不允许写"候选人列表是 div.candidate-card 这种 selector"。

---

## 3. 测试用例

### T1: JD 初始全量同步

**场景：** 主程序首次启动后，应当能从 zhipin 全量同步 JD 一次。

**操作：**
- [ ] Codex 在 desktop UI 中点击悬浮球 → Autonomous Agent → "工具" tab → 触发 "同步 JD（初始）" 按钮（如不存在，Codex 在 §3.0 实施前先到 §3.1 把按钮和后端 API 加上）。
- [ ] 等待 sync 完成事件。

**通过判据：**
- [ ] 工作台 → 候选人 → JD 管理 视图至少显示 1 条 JD。
- [ ] backend SQLite 中 `job_descriptions` 表 row count ≥ 1。
- [ ] `AgentRuntimeEvent` 表中存在 `event_type LIKE 'sync.jd.%'` 的记录。

**失败排查顺序（按 §0.5 边界，前两条只能改 prompt / 通用工具，不能写 zhipin 专属代码）：**
1. browser-mcp 是否能打开任意 URL 并返回 DOM 快照（用一个无关 URL 验，如 `https://example.com/`）；如果不行，问题在 browser-mcp 本身。
2. Agent 的 system prompt 是否教会它"如何在不知道 zhipin 具体 DOM 的情况下，靠 take_snapshot + 语义识别完成 JD 列表抽取"——若 Agent 反复抽错字段，**改 prompt** 或让 Agent 沉淀一条自己写的 skill，**不要替它写解析器**。
3. UI 是否真的发起了同步 API 调用（chrome-devtools 看 network）。
4. `recruit.upsert_job_description` 通用写入工具是不是有 bug 把 Agent 写入的字段丢了。

### T2: JD 增量小时级同步

**场景：** T1 已通过的前提下，再次触发"同步 JD（增量）"应只更新差异，不全量重写。

**操作：**
- [ ] Codex 在 zhipin 上手动新增 / 删除 1 条 JD（这一步**例外**，Codex 可以通过 browser-mcp 直接操作 zhipin 准备测试数据，但只能加 / 改不能影响 human 的实际业务数据；如果不允许动 human 的 zhipin，跳过加 JD 这一步，只验证"重复同步不重复创建"）。
- [ ] 触发增量同步。

**通过判据：**
- [ ] `job_descriptions` 表的总行数变化与 zhipin 实际变化一致。
- [ ] 已存在的 JD 没有被新建为重复行（按 zhipin 端 JD ID 去重）。
- [ ] `AgentRuntimeEvent` 中存在 `event_type='sync.jd.incremental'` 且 payload 中带 `added_count` / `updated_count` / `removed_count`。

**失败排查顺序：**
1. JD 唯一键设计——通用形态：`(source: str, external_id: str)`；其中 `source` 是字符串自由文本（Agent 自己填 `"zhipin"`），不是枚举常量、不是 `if source=="zhipin"` 的分发依据。
2. 同步策略——`recruit.upsert_job_description` 必须是 upsert（按 `(source, external_id)` 唯一键），不是 insert。
3. 调度——本计划只验证手动触发增量；hourly 调度先**不在 P0 范围**，但 Codex 应在 scheduler 里留好通用"周期触发 Agent 工作"挂钩（不是"周期跑 zhipin sync 函数"），并写一行 TODO 注释。

### T3: Autonomous Agent 为 1 个 JD 凑齐 3 个完整候选人（核心 P0 用例）

**场景：** 选 1 个 JD，启动 Autonomous Agent，让它自驱直到为该 JD 拿到 3 个含离线简历 + 联系方式的候选人。

**操作：**
- [ ] Codex 在悬浮球 → Autonomous → 运行 tab → "+ 新建 goal"，填写：
  - title: `JD-{external_id} 找够 3 名候选人`
  - jd_id: T1 同步到的某个 JD
  - candidate_count_target: 3
  - goal_text: `按 system prompt 中的工作流，为 JD {jd_title} 找够 3 个完整候选人。`
- [ ] 提交，run 进入 running。
- [ ] Codex 进入"循环监控 + 模拟 human 审批"模式：
  - 用 `mcp__chrome-devtools__wait_for` + 轮询切到 Autonomous → 审批 tab。
  - 每出现一条 `OperatorInteraction(status=pending)`，Codex 检查 payload 是否合规（`action_kind in {"request_offline_resume","request_contact"}`、target candidate id 已写入主程序）。
  - 合规则点 approve；不合规则点 reject 并附带 reason，然后排查 Agent prompt 是否产生了不合规的请求。
- [ ] 持续监控直到 run.status == 'completed' 或 'failed' 或 'blocked'。

**通过判据（同时满足）：**
- [ ] 该 JD 下 `Candidate` 表至少有 3 条记录满足：
  - `score_total >= 60`
  - `decision = 'advance'`
  - `phone IS NOT NULL OR wechat IS NOT NULL OR email IS NOT NULL`
  - `resume_file_path IS NOT NULL` 且文件实际存在
  - `score_breakdown.education = 15`（学历本科+ 已校验）
  - `score_breakdown.age = 15`（年龄 30-35 已校验）
- [ ] 工作台 → 候选人 → 该 JD 漏斗能看到这 3 个候选人卡片，且每张卡片显示联系方式徽标 + 简历附件 chip。
- [ ] run 最终状态为 `completed`。

**失败排查顺序：**
1. Agent 是不是不接受 system prompt？看 turn 1 的 assembled_messages 里有没有 §2 的内容。
2. Agent 是不是没遵守工作流节点顺序？看 round 事件流里 tool_calls 顺序。
3. 评分输出格式是否正确？看 `score_breakdown` 字段是不是 NULL 或乱码——若是，加一个 evaluate 节点的 JSON schema 校验 + 重试 prompt。
4. wait_human 是不是没有正确触发？看 OperatorInteraction 表是不是空的——若是，去 §3 的 happy path plan §1.2 检查 `requires_confirmation` 是否标对。
5. 候选人字段没写入？看 candidates write service 是不是被 Agent 调用了——chrome-devtools network 抓 `/api/candidates/*` 调用。
6. zhipin 这边返回的字段缺失？降级——把 §2.1 的"严禁伪造字段"理解成"标 null"，但**不算合格候选人**，让 Agent 继续找下一个。

### T4: 候选人节点逐级流转可观测

**场景：** 在 T3 跑的过程中，每个候选人在每个节点（A→B→C→D→E→F→G）都应该在 desktop UI 实时可见。

**操作：**
- [ ] Codex 选一个 T3 中正在处理的候选人，打开候选人详情抽屉。
- [ ] 在候选人时间线 / 沟通记录区域，截图记录其在 5 个节点的状态变迁。

**通过判据：**
- [ ] 时间线至少出现 5 条事件：`discovered` / `online_resume_fetched` / `scored` / `offline_resume_fetched` / `contact_fetched`。
- [ ] 每条事件的 timestamp 单调递增。
- [ ] 任意一条节点失败，时间线必须出现 `failed` 事件 + reason，不能静默吞掉。

**失败排查顺序：**
1. `AgentRuntimeEvent` 是否真的写了候选人级 event。
2. 候选人详情抽屉的事件订阅是否拉取了候选人 scope 的事件流。
3. SSE 流是否把 candidate-id 透传给前端。

### T5: 沟通记录留痕

**场景：** Agent 在尝试索要离线简历 / 联系方式时，给某条投递记录生成的"消息草稿"必须落到投递记录沟通界面（即使本测试阶段不真发）。

**操作：**
- [ ] T3 通过后，Codex 打开 3 条完整投递记录的沟通界面。

**通过判据：**
- [ ] 每个投递记录沟通界面至少有 2 条 outbound 消息草稿（一条索要离线简历、一条索要联系方式）。
- [ ] 草稿状态明确标 `draft` 或 `not_sent`，不与"已发送"混淆。

**失败排查顺序：**
1. Agent 工具签名里是不是把"发送消息"和"留草稿"做成了同一个 tool——必须分开，且草稿走 `application_threads` / `candidate_thread` 写入。
2. 投递记录沟通界面是不是只读了 inbound——补 outbound 渲染。

### T6: 工作台侧边栏投递记录跟进 / 流转回归（P1）

**场景：** T3 通过后，验证工作台左侧导航与候选人看板核心功能未被悬浮球改造破坏。

**操作 + 通过判据：**
- [ ] 点击 Sidebar `home` → DashboardView 正常加载，今日待办区域显示 T3 产生的候选人数量徽章。
- [ ] 点击 Sidebar `candidates` → 三个子 tab（投递记录漏斗 / 投递记录跟进 / JD 管理）都能切换，且每个 tab 有真实数据。
- [ ] 在投递记录漏斗里把 1 条投递记录手动状态流转到下一阶段（如 `screening → interview`）：
  - 状态变更立即在 UI 反映。
  - backend 中对应 `application` 状态字段更新。
  - 状态机历史 / 时间线追加一条 manual transition 事件。
- [ ] 在候选人详情抽屉里编辑备注 / 添加 tag，刷新页面后仍存在。
- [ ] 投递记录跟进 tab 显示需要 human 跟进的投递记录列表（基于 §2 的工作流，节点 D / F 等待审批的投递记录应该出现在这里）。
- [ ] 点击 Sidebar `settings` → SettingsView 完整加载；LLM provider / MCP server 配置未丢失。
- [ ] 悬浮球在以上每个页面都可见、可拖拽、状态指示正确（idle / running / waiting_human）。

**失败排查顺序：**
1. 路由 / tab 联合类型是不是被悬浮球改造遗漏。
2. `loadWorkspace` 是不是把候选人列表 fetch 漏掉了。
3. 候选人详情抽屉是不是仍指向旧 API。

---

## 4. 自迭代循环（fail → 定位 → 修 → 再跑）

Codex 每跑完一轮 T1–T6，按以下流程处理：

```
for round_no in 1..N:
    清理上一轮的 SQLite + chrome-devtools 截图目录
    启动 backend + desktop
    依次跑 T1, T2, T3, T4, T5, T6
    if 全部通过:
        write SUCCESS_REPORT.md (含每个 T 的 evidence 截图引用)
        break
    else:
        for 每个失败用例 t:
            按 t 的"失败排查顺序"逐项排查，找到根因层
            改对应代码 / prompt
            git diff 控制在 200 行以内（避免一次改太多）
        重启服务，回到 for 顶部
    if round_no >= 5 且仍有同一个用例失败:
        停下来，把"失败现场 + 5 轮已尝试修复方案"写到 BLOCKED_REPORT.md，等 human
```

### 4.1 任务

- [ ] Codex 在工作分支根目录建一个 `.codex/e2e-runs/` 目录，存每轮的截图与日志（`round-{n}/T{m}/...png`、`round-{n}/console.log`）。
- [ ] 每轮通过 / 失败结果写到 `.codex/e2e-runs/round-{n}/result.json`。
- [ ] 每轮在 git 上不自动 commit，只 push 到工作分支供 human review。

---

## 5. 验收（human 在 review 阶段对表）

- [ ] T1 同步 ≥ 1 条 JD。
- [ ] T2 增量同步无重复 row。
- [ ] T3 至少 1 个 JD 下有 3 个完整候选人（学历本科+、年龄 30-35、score ≥ 60、含离线简历 + 联系方式）。
- [ ] T4 候选人时间线 5 节点完整。
- [ ] T5 每个投递记录沟通界面 ≥ 2 条 outbound 草稿。
- [ ] T6 工作台 home / candidates / settings 三 tab + 状态流转 + 详情编辑全部可用，悬浮球状态指示正确。
- [ ] `.codex/e2e-runs/round-{最终轮}/result.json` 全绿。
- [ ] `.codex/e2e-runs/round-{最终轮}/boundary-check.txt` 经 §0.5.3 命令产出后**为空**（除文档与 fixture 外没有 zhipin/boss 字样）。
- [ ] `.codex/e2e-runs/round-{最终轮}/lifecycle-check.md`（§0.6.3）所有行均为 ✅；如有 `❌ 缺，未补`，必须有 human 在 review 中显式同意推迟的记录。
- [ ] backend 全量 pytest 仍然全绿。
- [ ] desktop typecheck 仍然全绿。

---

## 6. 给 human 的提示

- 本计划假设 `2026-04-19-autonomous-e2e-and-chat-overlay-plan.md` 已经完成或正在并行实施；如果那个 plan 的双 Agent / 7 tab / 悬浮球结构还没建完，本计划的 T3 / T6 会大量失败，应先把那个 plan 收尾。
- §2.1 的提示词是测试基线，可以根据真实 JD 内容微调"JD 匹配度"细分维度，但**学历本科+、年龄 30–35** 两条硬筛选必须保留，否则验收无法对齐。
- 如果 zhipin 端字段缺失（年龄不公开、学历不公开）频繁导致候选人不够 3 个，这是真实业务问题，不是测试问题——human 决定是否放宽自定义阈值。
