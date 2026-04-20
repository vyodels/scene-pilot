# 招聘业务 Skill 蒸馏与创作规范

## 文档目标与适用范围
本文档定义招聘业务场景下 skill 的蒸馏单位、表达口径、可执行资产优先级，以及项目内 skill 创作入口的长期规范。

本文档适用于以下工作：
- 成功 run 结束后的 skill distill
- 手工创建或修改招聘业务 skill
- skill 资产的结构设计、审查与持久化
- 为 Agent 补足招聘业务级 Python 能力资产

本文档记录的是长期稳定的规范，不是某次试验、某个站点的临时打法或当前数据库快照。若实现与本文档冲突，应优先修正实现，或先更新本文档再继续变更。

## 与上位规范的关系
- 与 [`2026-04-20-agent-product-design-principles.md`](./2026-04-20-agent-product-design-principles.md) 一致：skill 是运行中沉淀的长期学习资产，主程序只提供机制，不预写站点专属 skill 正文。
- 与 [`2026-04-20-agent-intelligence-boundary-and-capability-evolution.md`](./2026-04-20-agent-intelligence-boundary-and-capability-evolution.md) 一致：skill 必须承载业务语义，不得退化为网页细节或站点脚本。
- 与 [`2026-04-20-autonomous-agent-runtime-constraints.md`](./2026-04-20-autonomous-agent-runtime-constraints.md) 一致：浏览器 / DOM / tab 等细节属于子上下文，不得作为主 skill 的长期表达口径。

## 核心原则
### 1. Skill 的最小沉淀单元是业务动作，不是网页动作
招聘 skill 必须优先围绕“一个可复用的业务动作”沉淀，而不是围绕点击、翻页、切 tab、读某个按钮、读某个 selector 之类网页动作沉淀。

正确示例：
- 活跃 JD 增量同步
- 推荐页定位
- 推荐候选人列表获取
- 在线简历获取
- 沟通记录获取
- 候选人首轮打招呼
- 索要简历 / 索要电话 / 索要微信
- 接收候选人发来的简历并结构化入库
- 候选人 AI 在线初筛
- 候选人归档 / 冷却

错误示例：
- 打开某站点推荐页第二个标签
- 点击某个“立即沟通”按钮
- 读取某个 DOM 卡片里的第三段文本
- 通过某个 URL 路由进入详情页

### 2. Skill 必须尽量一技一用
一个 skill 应尽量只承载一个清晰的招聘业务动作。

如果一个 skill 同时覆盖“发现候选人 + 获取在线简历 + 发起沟通 + 索要电话 + 归档结果”，通常说明粒度过大，应拆分为多个业务级 skill。

### 3. Skill 的稳定语义要高于站点差异
不同站点、不同页面、不同 UI 路径的差异，应被表达为：
- 前置条件差异
- 证据来源差异
- 在线简历获取途径差异
- 结构化输入差异
- Python 脚本中的分支逻辑

不应被表达为主 skill 正文里的站点 selector、固定按钮文案、固定点击路径或专属页面手册。

### 4. 优先沉淀结构化输入输出
招聘业务 skill 必须尽量给出清晰的：
- 输入对象
- 输出对象
- 成功 / 失败 / 跳过 / blocker 的结构化结果

skill 的价值不只是“让模型少想一点”，而是“让未来执行更稳定、更低 token、更容易复核”。

### 5. 优先沉淀 Python 代码级资产
当某个招聘业务动作可以被**结构化输入 + 确定性规则**稳定完成时，应优先把它蒸馏为 Python 代码级资产，而不只是文本经验。

优先顺序如下：
1. 业务语义明确
2. 结构化输入输出明确
3. 可以通过一次 Python 调用完成核心处理
4. 仍然保留高层 `strategy` 与 `body.summary`

这里的 Python 资产用于降低后续 LLM 调用成本，并尽量把“一个业务动作”收敛为“一次 skill 调用”。

## 招聘业务 Skill 的优先沉淀目录
成功 run 完成后，优先判断能否沉淀为以下业务级 skill：

### 1. JD 侧
- 活跃 JD 增量同步
- JD 详情补齐
- JD 差异比对与去重

### 2. 候选人发现侧
- 推荐页定位
- 推荐候选人列表获取
- 候选人详情事实抽取
- 在线简历获取

其中“在线简历获取”必须区分途径，而不是混成一条笼统经验。例如：
- 从推荐列表摘要直接获取
- 从候选人详情侧栏获取
- 从沟通上下文中的附件 / 文本线索获取

### 3. 沟通侧
- 沟通记录获取
- 首轮打招呼
- 索要简历
- 接收候选人发送的简历并归档
- 索要电话
- 索要微信
- 根据候选人回复决定下一步沟通动作

### 4. 评估侧
- 在线简历 AI 初筛
- 评分输入整理
- 评分结论结构化

### 5. 收口侧
- 候选人冷却
- 候选人归档
- 候选人退出 / 暂缓信号归因

## Skill 结构规范
招聘 skill 继续复用项目现有的 `strategy`、`body`、`execution_hints`、`skill_metadata` 等字段，不引入新的产品层概念。

### 1. `strategy`
用于表达业务级策略，不写网页细节。

至少应包含：
- `instruction`
- `learned_patterns`
- `observed_actions`

### 2. `body`
用于表达：
- `summary`
- `checklist`
- `anti_patterns`

当 skill 适合沉淀成确定性代码资产时，应在 `body.artifacts.python_inline` 中附带 Python 代码资产。

推荐结构：

```json
{
  "artifacts": {
    "python_inline": {
      "entrypoint": "run",
      "code": "def run(payload, context): ...",
      "input_contract": {},
      "output_contract": {}
    }
  }
}
```

### 3. `execution_hints`
用于表达执行建议，而不是网页剧本。

至少应包含：
- `preconditions`
- `tool_preferences`
- `observed_outcomes`

当存在 Python 资产时，应补充：
- `executor_mode`

推荐值：
- `python_inline`
- `tool_or_llm`

### 4. `skill_metadata`
用于记录：
- 来源 run / goal kind
- 是否 LLM 生成
- 是否采用 `skill-creator` 标准创作
- 其它治理信息

## Python 资产约束
### 1. Python 资产优先解决确定性业务处理
优先用 Python 资产承载以下内容：
- 结构化抽取结果归一化
- 候选人 / JD 差异比对
- 消息文案生成模板
- 候选人回复信号分类
- 评分输入整理与聚合
- 结果摘要拼装

### 2. 不得把 Python 资产写成站点专属浏览器脚本
Python 资产不得内置：
- selector
- 固定按钮文案
- URL 路由
- tab 切换路径
- 某站点专属页面树

### 3. 外部副作用仍受治理边界约束
Python 资产可以降低 LLM 成本，但不能绕过项目已有的审批、治理与工具边界。

当某个业务动作需要真实对外写入、发消息、上传附件或其它外部副作用时，仍应通过受治理的工具面完成；Python 资产负责把业务动作尽量收敛为低成本、结构化、可复用的能力单元，而不是绕开治理。

## 项目内 Skill 创作入口
项目内统一使用仓库本地 skill 包 [`./.recruit-agent/skills/recruiting-skill-authoring`](../../.recruit-agent/skills/recruiting-skill-authoring/SKILL.md) 作为招聘业务 skill 的创作入口。

该 skill 包应遵循 `skill-creator` 标准方法，承担以下职责：
- 指导如何把招聘业务动作拆成可复用 skill
- 指导何时提供 Python inline 资产
- 提供技能结构模板与示例
- 避免把网页细节误沉淀成 skill

## 变更原则
- 如果某次改动让 skill 更像网页操作录像，而不像业务能力资产，应视为退化。
- 如果某次改动让 skill 更像“一个确定性的招聘业务单元”，且更容易落成一次 Python 调用，应视为正确方向。
- 若确实需要扩展字段，优先复用现有 `body` / `execution_hints` / `skill_metadata` 的承载方式；不要轻易引入新的产品概念名词。
