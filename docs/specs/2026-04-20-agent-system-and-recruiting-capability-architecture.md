# Agent 体系与招聘业务能力建设规范

## 文档目标与适用范围
本文档用于定义 recruit-agent 中两类长期稳定、且不应跑偏的技术骨架：

1. 整个 Agent 体系的设计骨架
2. 招聘工作体系作为 Agent 业务工具能力建设体系的设计骨架

本文档记录的是长期规范，不是实施计划、handoff、迁移备忘或某一时点的实现现状。若当前实现、历史计划或临时兼容结构与本文档冲突，应优先修正实现，或先更新本文档后再继续变更。

## 1. 文档目标与适用范围

本文档不再把重点放在桌面 UI 形态上，而是用于沉淀两类更高优先级、且更不应跑偏的长期技术骨架：

1. **整个 Agent 体系的设计骨架**
2. **招聘工作体系作为 Agent 业务工具能力建设体系的设计骨架**

只要这两层不跑偏，UI 可以继续演进；如果这两层跑偏，哪怕界面长得再对，也会把系统带回错误方向。

本文档只保留长期成立的系统骨架、分层边界、能力建设路径与读写边界，不记录迁移细节、一次性页面结构、局部兼容逻辑或当前实现里的不合理细节。

## 2. 与现有规范的关系

- `docs/specs/2026-04-20-agent-product-design-principles.md` 定义“主程序提供环境与边界，不替 Agent 做业务决策”的上位原则；本文档把这条原则落到系统分层与招聘能力建设结构上。
- `docs/specs/2026-04-20-dual-agent-product-architecture.md` 定义 Assistant / Autonomous 的角色边界与共享能力底座；本文档进一步明确这套双 Agent 产品在技术上应锚定在哪些层次。
- `docs/specs/2026-04-20-autonomous-agent-runtime-constraints.md` 约束主 conversation / run / memory / prompt / tool / MCP 边界；本文档以此为基础，明确哪些是长期骨架，哪些只是迁移期实现。
- `docs/specs/2026-04-20-agent-intelligence-boundary-and-capability-evolution.md` 定义能力缺口修复顺序与 skill / prompt / tool / governance 的职责边界；本文档把招聘业务能力体系的建设方式锚定到这些边界上。

## 3. 结论先行

### 3.1 Agent 体系的长期技术锚点不在 UI，而在五层骨架

```text
Agent product model
-> Runtime/lifecycle contract
-> Shared capability substrate
-> Domain capability construction
-> Governance + memory/prompt boundaries
```

### 3.2 招聘工作体系的长期技术锚点不在页面，而在“业务能力如何被 Agent 消费”

```text
Recruiting business intent
-> shared scene templates / business action definitions
-> plugin / toolkit / MCP / tool surface
-> Agent runtime execution
-> structured business records / memories / approvals
```

### 3.3 不应把迁移期实现细节误当成长期真相

尤其不应把下面这些内容误写成骨架：

- 当前某个 UI 页面形态
- legacy `/api/recruit-agent/...` fallback 聚合逻辑
- 某个站点、某个浏览器上下文、某份 prompt 里的临时要求
- 当前少量已暴露的招聘 scene template 列表
- 当前 plugin 工具数量或某次宏观阶段映射实现

## 4. Agent 体系的技术锚定骨架

### 4.1 架构图：双 Agent 产品的嵌套骨架

```text
┌──────────────────────────────────────────────────────────────────────┐
│                    recruit-agent Agent Product（双 Agent 产品层）       │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Shared Capability Substrate（共享能力底座）                    │  │
│  │                                                                │  │
│  │ kernel                  （通用执行内核）                        │  │
│  │ tool registry           （统一工具注册表）                      │  │
│  │ plugin host             （插件挂载底座）                        │  │
│  │ MCP registry            （MCP 能力注册）                        │  │
│  │ skill mechanism         （skill 创建/调用/列举/持久化机制）      │  │
│  │ memory mechanisms       （记忆机制）                            │  │
│  │ governance / approvals  （治理/审批边界）                       │  │
│  │ persistence / events    （持久化/事件）                         │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────┐   ┌──────────────────────────────┐ │
│  │ Assistant（协作入口）         │   │ Autonomous（持续推进器）      │ │
│  │                              │   │                              │ │
│  │ trigger: user conversation   │   │ trigger: goal / resume /    │ │
│  │          （用户对话触发）      │   │          scheduler wake      │ │
│  │ scope: conversation-first    │   │          （目标/恢复/调度）    │ │
│  │        （会话优先）            │   │ scope: main conversation +   │ │
│  │ lifecycle: short-loop        │   │        GoalSpec / AgentRun   │ │
│  │            interaction       │   │        （主会话+目标+运行历史）│ │
│  │            （短回路交互）      │   │                              │ │
│  └──────────────────────────────┘   └──────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

长期应稳定的是：

- 系统是**双内置 Agent 产品**，不是一个 God Agent 附带模式切换
- Assistant / Autonomous 共享能力底座，而不是各自一套割裂能力系统
- 差异体现在目标、生命周期、记忆范围、执行策略、治理与可见性，而不是体现在能力是否被单独挂载

### 4.2 架构图：Agent 体系的五层嵌套骨架

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 1. Product Role Model（产品角色层）                           │
│ Assistant / Autonomous                                              │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Layer 2. Runtime & Lifecycle Contract（运行时与生命周期层）    │  │
│  │ main conversation / GoalSpec / AgentRun / turn-round /         │  │
│  │ heartbeat                                                      │  │
│  │                                                                │  │
│  │  ┌──────────────────────────────────────────────────────────┐  │  │
│  │  │ Layer 3. Shared Capability Substrate（共享能力底座层）  │  │  │
│  │  │ kernel / tool registry / plugin host / MCP registry /   │  │  │
│  │  │ skill mechanism / prompts / memory mechanisms            │  │  │
│  │  │                                                          │  │  │
│  │  │  ┌────────────────────────────────────────────────────┐  │  │  │
│  │  │  │ Layer 4. Domain Capability Construction（领域能力层）│ │  │  │
│  │  │  │ recruit plugin / scene templates / toolkits /      │  │  │  │
│  │  │  │ observation enrichers / guard checks / skill assets│  │  │  │
│  │  │  │                                                    │  │  │  │
│  │  │  │  ┌──────────────────────────────────────────────┐  │  │  │  │
│  │  │  │  │ Layer 5. Governance & Persistence（治理持久化层）│ │  │  │  │
│  │  │  │  │ approvals / checkpoints / events / memory    │  │  │  │  │
│  │  │  │  │ stores / audit / recovery                    │  │  │  │  │
│  │  │  │  └──────────────────────────────────────────────┘  │  │  │  │
│  │  │  └────────────────────────────────────────────────────┘  │  │  │
│  │  └──────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

这五层才是 Agent 体系真正的技术骨架。UI 只是这些层的一个承载面，不是骨架本身。

### 4.3 时序图：Autonomous 的长期执行主链

```text
Goal / scene template request
-> GoalSpec
-> AgentRun + queued task
-> Heartbeat / scheduler wake
-> AutonomousAgent.run_turn_from_envelope(...)
-> AgentKernel.run_round(...)
-> approvals / checkpoints / events / memory updates
-> same main Agent lifecycle continues
```

这条时序链路表达的长期真相是：

- Autonomous 是一个长期主实例
- `GoalSpec` 是目标语义
- `AgentRun` 是执行历史
- `turn / round` 是运行时执行单位
- heartbeat / scheduler 是持续推进机制

这些对象关系不能因为某次 UI 或 API 表达方便而被打乱。

### 4.4 角色对照：Assistant 与 Autonomous 的稳定差异

```text
Assistant（协作入口）
- trigger: user conversation（用户对话触发）
- scope: conversation collaboration（会话协作）
- primary object: conversation（主对象是 conversation）
- rhythm: short-loop interaction（短回路交互）

Autonomous（持续推进器）
- trigger: goal / scheduler / resume（目标/调度/恢复触发）
- scope: long-running objective progression（长期目标推进）
- primary object: main conversation + GoalSpec + AgentRun history
  （主对象是主会话 + 目标 + 运行历史）
- rhythm: long-loop progression with approvals/resume（长回路推进）
```

长期应稳定的是这组角色差异，而不是某个具体页面里怎么排版它们。

### 4.5 哪些代码骨架是长期锚点

当前代码里可作为长期锚点参考的部分主要是：

- `services/backend/src/recruit_agent/services/container.py`
  - 体现 built-in agent、plugin host、tool registry、MCP registry、heartbeat、assistant/autonomous 装配
- `services/backend/src/recruit_agent/agents/autonomous.py`
  - 体现 `GoalSpec -> AgentRun -> run_turn_from_envelope -> kernel.run_round` 的持续推进主链
- `services/backend/src/recruit_agent/api/routers/agent.py`
  - 体现 `/api/agents/...` 作为统一 Agent 高级 API 面
- `docs/specs/*.md`
  - 体现长期边界定义

### 4.6 哪些现状不应被误写成技术锚点

```text
NOT anchors（这些不是长期技术锚点）
- 某个页面布局
- 某个 legacy API fallback 聚合逻辑
- 某个站点/浏览器假设
- 某个临时 summary / status projection
- 某次迁移期兼容结构
```

## 5. 招聘工作体系的技术锚定骨架

这里的“招聘工作体系”不是一组页面，也不是一个固定 workflow，而是**Agent 可消费的业务能力建设体系**。

### 5.1 架构图：招聘能力建设的嵌套骨架

```text
┌──────────────────────────────────────────────────────────────────────┐
│         Recruiting Work System for Agent（招聘业务能力体系总框）      │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Business Intent Definition Layer（业务意图定义层）             │  │
│  │                                                                │  │
│  │ shared scene templates      （共享场景模板）                    │  │
│  │ business action definitions （共享业务动作定义）                │  │
│  │ goal_kind / constraints /   （目标类型/约束/成功标准/上下文）   │  │
│  │ success_criteria / context_hints                               │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Domain Capability Construction Layer（领域能力建设层）         │  │
│  │                                                                │  │
│  │ recruit plugin            （招聘插件）                          │  │
│  │ recruit router            （招聘领域路由）                      │  │
│  │ observation enrichers     （观察增强器）                        │  │
│  │ guard checks              （治理/守卫检查）                     │  │
│  │ persona fragments         （领域 persona 片段）                 │  │
│  │ skill assets              （运行中沉淀的招聘 skill 资产）       │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Shared Capability Exposure Layer（共享能力暴露层）             │  │
│  │                                                                │  │
│  │ plugin tools              （插件工具）                          │  │
│  │ toolkit                   （领域 toolkit）                      │  │
│  │ MCP                       （外部能力接入）                      │  │
│  │ generic tool surface      （通用工具面）                        │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Business State / Result Layer（业务状态与结果层）              │  │
│  │                                                                │  │
│  │ job descriptions           （职位）                             │  │
│  │ candidate records          （候选人）                           │  │
│  │ assessments / scorecards / （评估/评分卡/评审决定）             │  │
│  │ review decisions                                              │  │
│  │ memories / approvals /     （记忆/审批/事件）                   │  │
│  │ events                                                         │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

长期应稳定的是这条主链：

- 业务意图先被定义成共享场景/共享动作语义
- 再通过通用能力面暴露给 Agent
- 再由 Agent 在运行时自主组合与执行
- 最后落到结构化业务记录、memory、approval、event 等结果层

### 5.2 架构图：招聘能力体系的四层嵌套骨架

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Layer A. Business Intent Definition（业务意图定义层）               │
│ shared scene templates / business action definitions                │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Layer B. Domain Capability Construction（领域能力建设层）      │  │
│  │ recruit plugin / recruit router / observation enrichers /      │  │
│  │ guard checks / persona fragments / skill assets                │  │
│  │                                                                │  │
│  │  ┌──────────────────────────────────────────────────────────┐  │  │
│  │  │ Layer C. Shared Capability Exposure（共享能力暴露层）   │  │  │
│  │  │ generic tools / MCP tools / tool registry / plugin host │  │  │
│  │  │ / skill mechanism                                        │  │  │
│  │  │                                                          │  │  │
│  │  │  ┌────────────────────────────────────────────────────┐  │  │  │
│  │  │  │ Layer D. Business State / Result（业务状态结果层） │  │  │  │
│  │  │  │ job descriptions / candidate records /            │  │  │  │
│  │  │  │ assessments / scorecards / review decisions /    │  │  │  │
│  │  │  │ memories / approvals                              │  │  │  │
│  │  │  └────────────────────────────────────────────────────┘  │  │  │
│  │  └──────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

这四层共同构成“招聘工作体系作为 Agent 业务能力建设体系”的长期骨架。

### 5.3 主链路：招聘业务动作如何被执行

```text
shared scene template selected（选择共享场景模板）
-> parsed into structured template metadata（解析成结构化模板元数据）
-> create goal / run request（创建目标 / 运行请求）
-> Agent executes through shared runtime（进入共享运行时执行）
-> recruit plugin enriches / guards / routes（招聘插件补充观察 / 守卫 / 路由）
-> tools + MCP + domain tools are used（调用通用工具 / MCP / 领域工具）
-> business records and summaries are updated（回写业务记录与摘要）
```

长期应稳定的是：

- 招聘业务动作先是**共享场景定义**
- 再进入 Agent runtime
- 再通过 recruit plugin 和共享工具面影响执行
- 最后回流业务对象层

而不是“先写一个站点专属流程，再让 Agent 调”。

### 5.4 scene template 的锚点地位

当前代码里，`services/backend/src/recruit_agent/services/scene_templates.py` 已经体现出一个关键方向：

- 共享场景模板不是 UI 配置
- 不是私有 Agent 动作目录
- 而是**共享业务意图的结构化定义层**

它至少承载：

- `goal_kind`
- `constraints`
- `success_criteria`
- `context_hints`
- direct runnable / JD requirement / candidate target support 等结构化元数据

长期应稳定的是这个“共享业务意图定义层”的存在，而不是当前模板列表是否刚好只有几项。

### 5.5 recruit plugin 的锚点地位

当前 `services/backend/src/recruit_agent/plugins/recruit/manifest.py` 体现出另一个关键方向：

- 招聘不是写进 kernel 的主流程分支
- 而是通过 plugin manifest 把 domain-specific 能力挂到共享底座上

在项目结构上，这个方向应进一步收敛为：

- `.recruit-agent/plugins/` 是项目级 plugin 资产、配置与元数据的统一根目录
- `services/backend/src/recruit_agent/plugins/recruit/*.py` 这类 backend 文件只承担可 import 的薄运行时 shell / mount code，负责读取这些资产并完成注册与挂载

长期应稳定的是 plugin 这种**领域适配层**的角色：

- register tools
- register observation enrichers
- register guard checks
- register persona fragments
- register router

而不是当前恰好注册了哪几个具体工具，也不是把 plugin 边界误写成“全部留在 backend”或“全部搬进 `.recruit-agent`”。

### 5.6 skill 在主骨架中的位置

skill 不需要单独拆出一张体系图，它应该集成在主架构图中理解：

- 在 **Agent 体系**里，skill 属于共享能力底座中的 **skill mechanism**
- 在 **招聘能力体系**里，skill 属于领域能力建设层中的 **skill assets**，同时又通过共享能力暴露层被 Agent 消费
- 在 **治理层**里，skill 的 review / approval / apply / reject / archive 属于 evolution / governance 边界

也就是说，skill 在长期骨架中的正确理解不是“一个平行系统”，而是：

```text
shared capability substrate
-> 提供 skill mechanism

domain capability construction
-> 沉淀 domain skill assets

governance / persistence
-> 管理 skill 的生命周期与审计
```

当前 specs 与代码已经体现出几个应长期稳定的锚点：

- 主程序只负责 **skill 机制**，不预写 skill 正文
- skill 是 **长期学习资产**，不是 run 级临时内存
- skill 的**归属与作用域**需要按 Agent 身份清晰隔离
- skill 应被纳入 workspace 聚合与 API 暴露，而不是散落在某个单独页面逻辑里
- skill 的演进需要进入 review / approval / apply / reject / archive 这类治理生命周期

当前代码里能支撑这几个锚点的主要位置是：

- `docs/specs/2026-04-20-agent-product-design-principles.md`
- `docs/specs/2026-04-20-agent-intelligence-boundary-and-capability-evolution.md`
- `services/backend/src/recruit_agent/api/routers/agent.py`
  - `/api/agents/{kind}/skills`
  - `_list_workspace_skills(...)`
- `services/backend/src/recruit_agent/evolution/learning_writer.py`
  - skill draft / auto promote / pending review 路径
- `services/backend/src/recruit_agent/evolution/queue.py`
  - pending_review / applied / rejected 治理状态
- `services/backend/src/recruit_agent/services/recruit_agent.py`
  - evolution artifact kind/status 约束

不应稳定的是：

- 当前 workspace 里恰好只显示哪些状态的 skill
- 当前具体 review 状态枚举的字面值
- 某个具体 skill 草稿结构或某次自动提升策略

### 5.7 memory / context / playbook 在招聘能力体系中的锚点

`services/backend/src/recruit_agent/services/recruit_agent.py` 当前已经体现出另一个关键方向：

- 候选人 memory、JD memory、global memory 是分层的
- context policy 是可配置且按 lane / run_type 有偏好的
- playbook / stage groups 是招聘业务过程的可演进表达，而不是写死在 kernel 里的状态机

长期应稳定的是：

- memory 分层与隔离边界
- context assembly 的策略化
- playbook / stage grouping 作为可演进的业务过程表达

不应稳定的是当前某个具体状态列表或阶段命名本身。

### 5.8 招聘能力体系中哪些不是长期真相

```text
NOT long-term truth（这些不是长期真相）
- 当前只暴露了少量 scene templates
- 当前 plugin 里只注册了少量 recruit tools
- 某份 prompt 里提到的具体站点或页面名
- 当前某个 stage label / macro-stage 映射细节
- 当前 legacy recruit-agent 命名残留
```

这些都更接近迁移期现状、部分落地状态或局部实现，不应反向定义长期骨架。

## 6. 哪些东西一旦跑偏，就会伤到系统本体

### 6.1 Agent 体系跑偏的典型信号

```text
wrong direction（Agent 体系跑偏信号）
- 把双 Agent 做回一个 God Agent
- 把共享能力做成某个 Agent 私有动作目录
- 把 Autonomous 做成“每个 goal 一个新身份”
- 把 run / goal / turn / round 语义混掉
- 让 UI / projection convenience 反向决定系统架构
```

### 6.2 招聘能力体系跑偏的典型信号

```text
wrong direction（招聘能力体系跑偏信号）
- 用站点专属流程替代共享场景定义
- 用 core runtime 硬编码招聘判断
- 把 scene template 退化成页面按钮配置
- 把 plugin 退化成 site adapter hardcode 层
- 把 skill 误做成独立平行体系，而不是嵌入主骨架
- 把业务状态、memory、approval、runtime projection 混成一层
```

## 7. 设计变更判断规则

以后评审相关变更时，至少先问：

1. 这次改动动的是五层 Agent 骨架中的哪一层？
2. 这次改动动的是四层招聘能力体系中的哪一层？
3. 这次改动是在增强 Agent 的环境与边界，还是在替 Agent 做业务判断？
4. 这次改动是在增强共享能力定义层，还是在偷偷堆站点专属 hardcode？
5. 这次改动是否把迁移期现状误写成长期真相？

## 8. 当前待你确认的点

在转成正式规范前，需要你确认：

1. 这版是否已经更接近你说的“真正的技术锚定骨架”
2. Agent 五层骨架是否还需要继续压缩/改名
3. 招聘能力体系四层结构是否表达对了，还是你希望把 scene template / plugin / toolkit / MCP / business records 之间再拆得更细
4. 这份文档是否要继续保留少量 UI 说明，还是彻底只谈系统骨架与能力建设骨架
