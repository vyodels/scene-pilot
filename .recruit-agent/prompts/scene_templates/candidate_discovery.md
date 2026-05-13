# 发现候选人

- key: candidate_discovery
- display_order: 30
- action_kind: candidate_discovery
- requires_jd: true
- supports_candidate_count_target: true
- default_candidate_count_target: 3
- direct_runnable: false

## Summary

围绕指定 JD，在 human 当前使用的普通浏览器（非 AI 模式浏览器）中发现候选人：优先复用已打开且可继续任务的招聘平台页面；优先使用 `browser_list_tabs` 枚举普通浏览器页签，再判断是否存在可复用目标页。只有在当前工具可达范围内确实没有可复用目标页时，才由 Agent 自行在该普通浏览器中打开招聘平台页面并把有效候选人写入工作区。

## Instruction

围绕指定 JD，在 human 当前使用的普通浏览器（非 AI 模式浏览器）中发现候选人：先复用已打开且可继续任务的招聘平台候选人列表页、推荐页、候选人详情页或其它等价页面；必须先用 `browser_list_tabs` 枚举普通浏览器全部窗口中的现有页签，再判断是否已存在可复用目标页。若当前窗口未发现目标页，或当前工具只覆盖默认窗口范围而无法确认其它窗口中是否已有可复用目标页，不得直接推出“可以新开页”，应先把它视为浏览器工具作用域受限。只有在当前工具可达范围内确实没有可复用目标页时，才由 Agent 自行在该普通浏览器中打开招聘平台页面并进入合适的候选人搜索、推荐或详情页面。随后将有效候选人写入工作区，并补齐基础联系信息；只有在登录、验证码、权限或其它明确必须由 human 介入的 blocker 下，才请求 human 协助。

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
