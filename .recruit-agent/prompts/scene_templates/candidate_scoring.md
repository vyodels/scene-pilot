# AI 评分

- key: candidate_scoring
- display_order: 40
- action_kind: candidate_scoring
- requires_jd: true
- supports_candidate_count_target: false
- direct_runnable: false

## Summary

对指定 JD 下的投递记录执行 AI 评分，并把评分结果回写工作区。

## Instruction

对指定 JD 下的投递记录执行 AI 评分，并把评分结论回写工作区。

## Constraints

- scope_kind: job
- memory_scope_kind: job
- target_entity: candidate_application

## Success Criteria

- entity: candidate_score
- outcome: candidate_scoring

## Context Hints

- trigger: scene_template_panel
