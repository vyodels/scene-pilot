# 收集简历

- key: resume_collection
- display_order: 35
- action_kind: resume_collection
- requires_jd: true
- supports_candidate_count_target: false
- direct_runnable: false

## Summary

围绕指定 JD 下当前正在处理的候选人，在 human 当前使用的普通浏览器（非 AI 模式浏览器）中收集已经可见的在线简历或附件简历线索；若目标要求本地文件，必须继续完成下载或预览后的本地 artifact 路径定位与业务格式验证，再把可验证的简历 artifact 归档到共享工作区。

## Instruction

围绕指定 JD 下当前正在处理的候选人，在 human 当前使用的普通浏览器（非 AI 模式浏览器）中收集已经可见的在线简历或附件简历线索。优先复用已打开且可继续任务的候选人详情页、附件卡片或其它等价页面；若目标要求本地文件，不得在仅确认“看到了附件入口”后结束，必须继续完成允许的预览或下载路径。浏览器触发下载前，保留 snapshot 中的 `href` / source URL、`download` 或预期 filename、source signature/ref、tab 与 click-before `startedAfter`；下载触发后，优先用 `browser_locate_download` 只读定位 Chrome 下载记录、本地路径、进度和 `in_progress` / `interrupted` / `complete` 状态，并用这些 browser-derived 字段把本地文件和目标下载入口强关联。若显式设置 `waitMs`，保持 `waitMs <= 5000`，必要时用相同关联字段重试短等待或立即查询，而不是让单次调用超过 MCP 传输超时。若 `browser_locate_download` 返回 `located=true`、`state=complete`、`exists=true`、本地路径、扩展名或 mime、以及 sourceUrl/finalUrl/referrer 关联证据，可将其作为 browser-managed 下载的本地路径与格式证据；不要因为 scene 内没有 shell `file` 工具而丢弃这类下载记录。成功时在结构化结果中保留 `artifact.file_path`、`artifact.file_name`、`browser_download`、sourceUrl/finalUrl/referrer、以及适配 `attach_resume_artifact` 的 `business_writeback.arguments`，再由 Agent 把已验证的简历 artifact 写入共享工作区。只有在登录、验证码、权限、设备绑定或其它明确的 human-only blocker 下，才请求 human 协助；human 的职责是解除阻塞，而不是代替 Agent 完成页面导航、下载判断或本地归档。

## Constraints

- scope_kind: job
- memory_scope_kind: job
- target_entity: resume_artifact
- source_surface: browser_accessible_candidate_pages
- target_store: shared_workspace_resume_artifacts
- write_strategy: verify_local_artifact_then_attach_to_workspace

## Success Criteria

- entity: resume_artifact
- outcome: resume_collection
- source: browser_accessible_candidate_pages
- target: shared_workspace_resume_artifacts
- write_policy: verify_local_artifact_then_attach_to_workspace

## Context Hints

- trigger: scene_template_panel
- candidate_context_required: true
