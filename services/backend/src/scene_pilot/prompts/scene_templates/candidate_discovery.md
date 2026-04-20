# 发现候选人

- key: candidate_discovery
- display_order: 30
- goal_kind: candidate_discovery
- requires_jd: true
- supports_candidate_count_target: true
- default_candidate_count_target: 3
- direct_runnable: false

## Summary

围绕指定 JD，优先复用 human 当前使用的普通浏览器（非 AI 模式浏览器）中已打开的 zhipin.com 页面筛选候选人；若不存在可用页面，则由 Agent 自行在该普通浏览器中打开 zhipin.com，并把有效候选人写入工作区。

## Goal Text

围绕指定 JD，优先复用 human 当前使用的普通浏览器（非 AI 模式浏览器）中已打开的 zhipin.com 页面筛选候选人；若不存在可用页面，则由 Agent 自行在该普通浏览器中打开 zhipin.com 并进入合适的候选人搜索或详情页面。随后将有效候选人写入工作区，并补齐基础联系信息；只有在登录、验证码、权限或浏览器能力受限等必须由 human 介入时，才请求 human 协助。

## Constraints

- scope_kind: job
- memory_scope_kind: job
- target_entity: candidate
- source_surface: browser_accessible_candidate_pages

## Success Criteria

- entity: candidate
- outcome: candidate_discovery

## Context Hints

- trigger: scene_template_panel
