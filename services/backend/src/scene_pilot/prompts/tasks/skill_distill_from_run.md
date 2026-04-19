# 任务：从成功 run 提炼试用 Skill

你要根据一次已经成功完成的 Agent 运行记录，提炼出一个可复用的试用 skill 草案。

目标是沉淀未来还能复用的业务级策略，而不是复述一次性的网页细节、按钮文案、DOM 结构、selector 或站点专用路径。

要求：
- 只基于输入里已经发生过并且能被证据支持的成功执行来总结。
- 不要把 task 模板、goal 文本、约束文案原样抄写成 skill 正文；必须做归纳和抽象。
- 优先提炼业务级动作模式、前置条件、工具偏好、风险边界和可观察结果。
- 不要编造任何未在输入中出现的站点字段、页面结构或隐含步骤。
- 如果输入不足以形成稳定 skill，也要返回结构完整的 `skill_contract`，并在描述里明确说明局限。
- 只返回 JSON，不要附加解释。

返回格式：

```json
{
  "skill_contract": {
    "skill_name": "一句清晰的 skill 名称",
    "description": "说明这个 skill 解决什么问题、在什么条件下复用",
    "category": "recruiting",
    "platform": "runtime-scene",
    "input_schema": {},
    "output_schema": {},
    "strategy": {
      "instruction": "一句高层策略说明",
      "learned_patterns": ["从本次成功执行里提炼出的可复用模式"],
      "observed_actions": ["已经观察到有效的业务动作"]
    },
    "body": {
      "summary": "对 skill 的简短摘要",
      "checklist": ["执行时需要关注的关键检查项"],
      "anti_patterns": ["不要重复的无效或危险做法"]
    },
    "execution_hints": {
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
      "llm_generated": true
    }
  }
}
```
