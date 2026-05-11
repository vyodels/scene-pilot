# Agent Type 与 Product Adapter 完成计划

## 背景

当前 Agent runtime 已完成核心收敛：`InteractionEngine`、turn/tool loop、transcript、history compaction、permission output protocol 都应作为既有能力使用。接下来只做产品层收敛，避免再次把 Assistant / Autonomous、MCP、skill、memory 或业务 workflow 写进 runtime。

长期设计以 [`../../design/agent-core/01-agent-types-and-product-adapters.md`](../../design/agent-core/01-agent-types-and-product-adapters.md) 和 [`../../specs/2026-05-11-agent-runtime-product-boundary-spec.md`](../../specs/2026-05-11-agent-runtime-product-boundary-spec.md) 为准。

## 核心思路

Assistant / Autonomous 是 Agent type，不是 runtime type。

```text
assistant
  临时任务型产品适配

autonomous
  常态化复杂任务型产品适配

runtime
  继续使用现有 InteractionEngine.submitMessage(...) 与 InteractionOutput protocol
```

两类 Agent 的差异只体现在：

- 配置方式。
- 触发方式。
- 生命周期。
- 产品状态治理。
- UI/API 投影。
- memory / context / skill / tool policy 的产品层选择。

两类 Agent 的共同点：

- 使用同一个 Agent runtime。
- 使用同一套 business tools。
- 不引入新的执行单位。
- 不引入新的 continuation API。
- 不让 runtime 认识 `assistant` / `autonomous`。

## 明确禁止

本计划执行期间禁止：

- 新增历史 shell/kernel/round/execution-unit 类抽象。
- 新增第二套 tool-result continuation API。
- 在 adapter 层手拼 provider 对话结构作为新通用机制。
- 把 MCP、skill、memory、context source 定义为 runtime 类型或能力来源 provider。
- 把招聘业务对象、业务 workflow、业务状态机写进 `agent_runtime/**`。
- 因为整理外层而修改 `InteractionEngine` 语义。

如果发现必须修改 `agent_runtime/**` 才能继续，先停止实现并回到设计讨论。

## 当前已完成基线

- `agent_runtime/**` 无本轮新增产品层依赖。
- 错误引入的 shell/adapter 执行封装已经清除。
- `InteractionEngine` 仍只使用现有 `submitMessage(...)` 入口。
- 业务 tool metadata 已开始标记 `business_tool`、`business_domain`、`permission_scope`、`risk_level`。
- workspace tools API 已开始投影 business tool 治理字段。

## 实施阶段

### 阶段 1：文档与命名收敛

目标：

- 所有当前文档统一使用 `Agent type`、`Product adapter`、`Business tool`。
- 不再使用 shell 作为架构概念。
- 计划、spec、design 三处互相引用一致。

允许改动：

- `docs/design/**`
- `docs/specs/**`
- `docs/plan/**`

验收：

- 文档中没有历史 shell 架构、第二套 tool-result continuation API 等错误概念。
- `shell` 仅允许出现在历史归档或非架构语义文本中。

### 阶段 2：Business tool 边界补齐

目标：

- recruit 业务能力通过 business tool 暴露。
- business tool 具备治理 metadata。
- UI/API 能看到 tool 的业务域、目标资源、权限范围和风险等级。

允许改动：

- `plugins/recruit/manifest.py`
- `plugins/recruit/toolkit.py`
- `api/routers/agent.py`
- 对应测试

禁止改动：

- `agent_runtime/**`

验收：

- recruit tool category 不再表达成 generic plugin 能力。
- read/write/approval tool 的 `permission_scope` 可区分。
- 写入、删除、流转、外部副作用类 tool 有明确审批或风险字段。
- workspace API 返回 `businessTool`、`businessDomain`、`resourceTargetKind`、`permissionScope`。

### 阶段 3：Assistant 产品适配检查

目标：

- Assistant 继续作为临时任务入口。
- 使用现有 `InteractionEngine.submitMessage(...)`。
- confirm/cancel 只做产品状态映射，不新增 runtime continuation 协议。

允许改动：

- `agents/assistant.py`
- `assistant/**`
- `api/routers/assistant.py`
- `api/routers/agent.py`
- 对应测试

禁止改动：

- `agent_runtime/**`

验收：

- Assistant 没有独立 tool loop。
- Assistant 没有新增运行封装层。
- pending approval 的产品记录不要求 runtime 产生第二套 API。
- 现有 Assistant conversation / confirm / cancel 测试通过。

### 阶段 4：Autonomous 产品适配检查

目标：

- Autonomous 作为常态化复杂任务入口。
- 复杂招聘 workflow 通过 prompt、business tools、memory/context、skill policy、业务事件表达。
- durable run、checkpoint、approval、intervention、状态投影保留在产品层。

允许改动：

- `agents/autonomous.py`
- `agents/heartbeat.py`
- `scheduler/**`
- `api/routers/agent.py`
- 对应测试

禁止改动：

- `agent_runtime/**`
- 新增 workflow engine 替 Agent 做业务编排

验收：

- Autonomous 没有新增 runtime 类型。
- Autonomous 不硬编码招聘 workflow 到 runtime。
- run status、turn record、runtime event、approval item 的职责清晰。
- 现有 autonomous goal / visibility / approval 相关测试通过。

### 阶段 5：边界与回归验证

必须执行：

```text
rg agent_runtime 反向导入产品层
rg 禁止概念
pytest agent_runtime
pytest assistant/autonomous 关键路径
pytest api agent routes
git diff --check
```

验收标准：

- `agent_runtime/**` 不导入 `agents/services/plugins/models/repositories/api/memory`。
- 无历史 shell/kernel/round/execution-unit 架构或第二套 tool-result continuation API。
- 关键测试通过。
- 文档和代码边界一致。

## 执行顺序

1. 先完成阶段 1，并确认文档没有错误概念。
2. 再完成阶段 2，补 business tool metadata/API 投影。
3. 再检查 Assistant，只有发现实际不一致才改。
4. 再检查 Autonomous，优先删除历史包袱，不新增 runtime 抽象。
5. 最后做全量边界扫描和关键测试。

## 非目标

本计划不做：

- 新 Agent runtime。
- 新 tool loop。
- 新 MCP / skill / memory runtime 类型。
- 新 workflow engine。
- 新 MCP / skill / memory / business capability provider abstraction。
- 大规模 UI 重做。

## 中止条件

出现以下情况必须暂停并讨论：

- 需要修改 `agent_runtime/**` 的公开语义。
- 需要新增 runtime API。
- 需要把产品 run / approval / business workflow 映射成 runtime 状态。
- 需要让 Assistant / Autonomous 在 runtime 内部分支。
