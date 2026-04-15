# Recruit Agent 网页驱动、Tool Use 与 MCP 现状说明

更新时间：2026-04-15

这份文档用于记录当前 `Recruit Agent` 在网页驱动、`tool_use`、MCP 接入、学习进化与人工修正方面的真实状态，便于后续规划。

## 当前结论

当前系统已经具备一套**可试验的招聘 agent 基础能力**，但还没有达到 Codex app 或 Hermes 那种“通用、真实、可大范围自驱”的 agent OS 水平。

更准确地说：

- 网页能力已经切换到 **MCP 驱动**
- 浏览器能力不再写死在代码里，而是通过 **MCP 注册与动态工具暴露**
- 招聘场景仍然可以以 Boss 作为默认外部环境，但它不再是底层平台 adapter
- `tool_use` 是真的能跑
- 当前主要可用的 MCP 方向仍然是 **Browser MCP 预置模板**
- 学习与进化已经有最小闭环，但还不是稳定的“自动收敛最优路径”系统

## LLM 现在可以驱动网页吗

可以，但前提是有**真实可用的 MCP 能力**。

### 1. 读网页

当前系统已经能通过已注册的浏览器 MCP 读取真实浏览器场景。当前提供了一个 `Browser MCP` 预置模板，可通过本地 socket 暴露通用浏览器工具，例如：

- `browser_list_tabs`
- `browser_snapshot`
- `browser_execute_script`

这部分属于**真实外部环境读取**。

### 2. 写网页

网页写动作不再通过 `BossPlatformAdapter` 这类预制平台方法完成。当前方向是：

- runtime 只消费 **已注册 MCP 暴露的真实工具**
- 招聘站点上的读写逻辑由 **skill / strategy / memory** 驱动
- 如果缺少真实 MCP 能力，runtime 会 **fail fast**，而不会退回本地伪执行

因此当前阶段更准确的定义是：

- **网页读取：真实**
- **网页写入：取决于 MCP 工具与 skill 是否完备**

## LLM 是怎么知道“该怎么驱动”的

LLM 不是天然知道如何驱动网页，而是依赖 runtime 暴露给它的工具和上下文。

当前链路是：

1. 任务进入 runtime
2. `ContextAssembler` 生成本轮 `context_manifest`
3. `AgentLoop` 调模型，同时把当前可用工具描述发给模型
4. 模型返回 `tool_use / tool_call`
5. `ToolRegistry` 执行对应工具
6. 如果需要真实网页动作，则走：
   - 已注册 MCP 的动态工具
   - 由 skill 生成的解析/交互逻辑
   - Agent IM 中的确认 / 重试 / 纠偏 / 接管

因此关键不在于“模型会不会点网页”，而在于：

- runtime 暴露了哪些真实可执行工具
- skill 是否已经学会如何组合这些工具
- 当前环境是否真的可连通

## 现在是否必须有 MCP

如果要让系统读取或操作**真实网页页面**，当前需要有可用 MCP。

系统现在已经提供：

- MCP 注册机制
- MCP 管理页面
- `Browser MCP` 预置模板
- runtime 动态工具注册

这意味着：

- 可以直接安装预置 MCP，也可以手动注册自定义 MCP server
- 工程环境中必须有真实可用的 MCP endpoint
- 如果 MCP 不可用，系统会阻塞并要求处理，不会退回本地伪数据

## 当前真的具备 Codex app 的基本能力吗

只能说具备**一部分**，还不能说已经达到 Codex app 水平。

当前已经有的：

- 持久化 `AgentSession / AgentRun / Checkpoint / RuntimeEvent`
- 重启后的 run 恢复基础
- `tool_use`
- `Context Assembler`
- `GoalSpec / ExecutionTrace / StrategyFragment / ExecutionGraphProjection`
- `Agent IM / OperatorInteraction`
- MCP 注册与动态工具暴露

当前还缺的关键部分：

- 更完整的浏览器动作抽象和 skill 生态
- 任意外部工具生态
- 自动安装和接入任意 MCP
- 更成熟的真实网页写操作 skill 资产
- 更成熟的 provider routing / credential pool
- 更完整的 skill / memory platformization

因此当前更准确的定位是：

**Recruit Agent 的可试验 runtime 已经成型，但还不是通用 agent OS。**

## `tool_use` 是真的能调用外部工具吗

是，当前 `tool_use` 是真实执行的，不是摆设。

模型返回的 `tool_use / tool_call` 会被 runtime 解析，然后交给 `ToolRegistry.execute()` 执行。

当前实际暴露给模型的主要工具包括：

- 来自已注册 MCP 的动态工具，例如：
  - `browser_list_tabs`
  - `browser_snapshot`
  - `browser_execute_script`
- `record_observation`
- `advance_plan_step`
- `request_replan`
- `request_human_checkpoint`
- `request_system_command`
- `record_note`

需要注意的是：

- 当前默认动态工具集合还比较小
- 真实网页能力主要依赖 Browser MCP 预置模板
- 系统已具备 MCP 注册与管理基础，但还不是完整的外部工具市场

## 当前是否有可直接试验的 Boss 招聘能力

有基础，但更适合作为**真实环境试验模板**而不是稳定成品。

按当前能力，较合理的 Boss 自主试验最小闭环应是：

1. 读取 Boss 当前列表页场景
2. 通过 skill 识别候选人列表和入口
3. inspect 候选人资料
4. 做初筛
5. 生成沟通草稿或网页操作脚本
6. 在 IM 中请求用户确认 / 纠偏 / 接管
7. 请求简历
8. 评分
9. 推进下一阶段或淘汰

建议将这套能力定义为：

**Boss 环境下的招聘试验模板 / bootstrap skeleton**

它的作用是帮助 agent 起步，而不是作为最终执行真相；真正长期沉淀的是 `skill / strategy / memory`。

## 如果执行路径不满意，能否学习进化或由用户辅助修改

可以，而且当前已经有最小闭环。

当前系统已具备这些对象：

- `GoalSpec`
- `ExecutionTrace`
- `StrategyFragment`
- `ExecutionGraphProjection`
- `OperatorInteraction`

因此当前已经支持：

- 用户对当前路径不满意时直接纠偏
- 用户在 `Agent IM` 中执行：
  - `confirm`
  - `retry`
  - `correct`
  - `teach`
  - `handoff`
  - `stop`
- 系统沉淀 trace、策略片段和图投影

但要明确：

当前是**可学习雏形**，还不是成熟的自优化系统。

也就是说：

- 可以逐步变好
- 可以保留已验证的较优做法
- 可以在用户教学后继续调整
- 但还不能保证稳定自动收敛到“最佳路径”

## 当前有可用的外部 MCP 吗

明确可见、已经接入工程的，主要还是：

- **Browser MCP 预置模板**

系统已经具备基础的：

- MCP 注册中心
- MCP 管理页面
- 预置 MCP 安装入口

但还没有做到：

- MCP 市场
- 任意远端连接器的自动发现
- 更丰富的外部数据 MCP 生态

## 如果没有 MCP，系统能自主安装吗

当前不能认为已经具备“通用 MCP 自主安装能力”。

目前最接近这类能力的是：

- `request_system_command`

但它是一个**受控系统命令请求机制**，特点是：

- 需要人工确认
- 默认走白名单
- 不是任意命令都能执行
- 更适合受限工程操作，不等于自动安装任意 MCP

因此当前结论是：

- **通用 MCP 自主安装：没有**
- **受控系统命令请求：有，但能力很有限**

## LLM 多次尝试后，最终会落下“最优路径”吗

当前不能把结果定义成“保证最优路径”。

更准确的说法是：

- 系统可以逐步沉淀出**当前已知较优路径**
- 这些沉淀会表现为：
  - `ExecutionTrace`
  - `StrategyFragment`
  - `ExecutionGraphProjection`
  - `OperatorInteraction` 历史

但这不等于数学意义上的全局最优。

当前更适合的术语是：

- `best-known path`
- `current validated path`

而不是：

- `guaranteed optimal path`

原因在于：

- 目标驱动 runtime 仍处于第一轮并行接入阶段
- 学习闭环和资产排序还不够成熟
- 还没有完整的自动试验放大器、策略排名器和长期验证机制

## 当前阶段的整体判断

现在这套系统更适合被定义为：

**一个可试验的 Recruit Agent runtime**

它已经能够：

- 理解真实网页场景
- 调用有限但真实存在的 MCP 工具
- 形成 trace / strategy / interaction 的沉淀
- 接受用户在 IM 中的纠偏、教学和接管

但它还没有完成以下关键跃迁：

- 更丰富的真实网页写操作 skill 资产
- 更通用的 MCP 生态
- 外部工具自主接入
- 稳定的“最优路径”收敛机制

## 后续规划建议

这部分暂不执行，只作为后续规划参考。

### P0

- 强化真实网页写操作的 skill 资产
- 明确 Boss 试验模板
- 完善 Agent IM 中的运行时纠偏与重试链路

### P1

- 扩展更多真实浏览器动作工具
- 让 LLM 能在更多真实可执行动作中选择
- 继续强化 `StrategyFragment` 的沉淀和复用

### P2

- 引入更通用的 MCP 管理能力
- 逐步补齐 provider routing / credential pool
- 让 `best-known path` 具备更强的验证与排序机制
