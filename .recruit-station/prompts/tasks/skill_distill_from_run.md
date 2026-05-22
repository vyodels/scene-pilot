# 任务：从成功 run 提炼试用 Skill

你要根据一次已经成功完成的 Agent 运行记录，提炼出一个可复用的试用 skill 草案。

你的目标不是复述某次网页操作，而是沉淀**未来可复用的招聘业务能力单元**。

## 蒸馏原则
- 只基于输入里已经发生过并且能被证据支持的成功执行来总结。
- 不要把 task 模板、instruction 文本、约束文案原样抄写成 skill 正文；必须做归纳和抽象。
- 不要把浏览器标签、URL、按钮文案、DOM 结构、selector、固定点击路径、站点专用页面分支写进 skill。
- 优先提炼业务级动作模式、前置条件、工具偏好、风险边界和可观察结果。
- skill 的命名与摘要必须是招聘业务语义，而不是网页语义。
- 如果输入不足以形成稳定 skill，不要硬造可复用能力；返回 JSON：`{"skill_contract": null, "skip_reason": "evidence_insufficient"}`。
- 只有当输入明确包含完整成功终局、关键工具结果和可复用业务证据时，才返回结构完整的 `skill_contract`。
- 只返回 JSON，不要附加解释。

## 优先蒸馏的招聘业务单元
优先判断这次成功 run 是否可以沉淀为以下类型之一：
- 活跃 JD 增量同步
- JD 详情补齐
- 推荐页定位
- 推荐候选人列表获取
- 候选人详情事实抽取
- 在线简历获取
- 沟通记录获取
- 候选人首轮打招呼
- 索要简历
- 索要电话
- 索要微信
- 接收候选人发送的简历并归档
- 候选人 AI 在线初筛 / 评分输入整理
- 候选人冷却 / 归档 / 退出信号归因

如果本次 run 明显属于以上某类，请直接按对应业务语义命名，不要退化成“页面读取”“按钮点击”“列表抓取”等底层名字。

## Python 资产优先级
如果这次 skill 可以被归纳为“结构化输入 -> 确定性处理 -> 结构化输出”的单次业务动作，请优先在 `body.artifacts.python_inline` 中附带 Python inline 资产。

适合提供 Python inline 资产的情况：
- JD / 候选人差异比对
- 候选人列表归一化
- 在线简历获取路径归类
- 沟通记录解析
- 打招呼 / 求简历 / 求电话 / 求微信文案生成
- 候选人回复信号分类
- 评分输入整理与结果摘要拼装

Python inline 资产要求：
- 必须是纯 Python 业务处理逻辑。
- 不要写 selector、URL、浏览器切换、DOM 操作或站点专用步骤。
- 不要依赖文件系统、网络、shell、外部进程或未声明的环境。
- 入口函数默认叫 `run`，签名优先使用 `run(payload, context)`。
- 如果本次 run 证据不足以支持稳定脚本，就不要硬写 Python 代码。

## 返回格式

```json
{
  "skill_contract": {
    "skill_name": "一句清晰的招聘业务 skill 名称",
    "description": "说明这个 skill 解决什么业务问题、在什么条件下复用",
    "category": "recruiting",
    "platform": "runtime-scene",
    "input_schema": {},
    "output_schema": {},
    "strategy": {
      "instruction": "一句高层业务策略说明",
      "learned_patterns": ["从本次成功执行里提炼出的可复用业务模式"],
      "observed_actions": ["已经观察到有效的业务动作"]
    },
    "body": {
      "summary": "对 skill 的简短业务摘要",
      "checklist": ["执行时需要关注的关键检查项"],
      "anti_patterns": ["不要重复的无效或危险做法"],
      "artifacts": {
        "python_inline": {
          "entrypoint": "run",
          "code": "def run(payload, context):\n    return payload",
          "input_contract": {},
          "output_contract": {}
        }
      }
    },
    "execution_hints": {
      "executor_mode": "python_inline",
      "preconditions": ["执行前提"],
      "tool_preferences": ["优先使用的工具或能力面"],
      "observed_outcomes": ["本次 run 里观察到的有效结果"]
    },
    "risk_level": "low",
    "health_check_config": {
      "expected_result_status": "completed"
    },
    "skill_metadata": {
      "source_kind": "autonomous",
      "llm_generated": true,
      "creator_standard": "skill-creator"
    }
  }
}
```

说明：
- 如果不适合提供 Python inline 资产，可以保留 `body.artifacts` 为空对象，并把 `execution_hints.executor_mode` 设为 `tool_or_llm`。
- `observed_actions` 必须表达业务动作，例如“比对活跃 JD 差异”“整理投递记录沟通记录”，不要表达“点击按钮”“读取第三列文本”。
