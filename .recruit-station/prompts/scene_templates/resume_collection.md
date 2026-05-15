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

围绕指定 JD 下当前正在处理的候选人，在 human 当前使用的普通浏览器（非 AI 模式浏览器）中收集已经可见的在线简历或附件简历线索。优先复用已打开且可继续任务的候选人详情页、附件卡片或其它等价页面；若目标要求本地文件，不得在仅确认“看到了附件入口”后结束，必须继续完成允许的预览或下载路径。浏览器触发下载前，保留 snapshot 中的 `href` / source URL、`download` 或预期 filename、source signature/ref、tab 与 click-before `startedAt`，并调用 `local_download_create_attempt` 生成 `downloadAttemptId` 和下载目录快照；HID 点击后先 browser observe/wait，再用 `local_download_attribute(downloadAttemptId)` 将新增本地文件和目标下载入口强关联。只有 `completed` 可作为 browser-managed 下载的本地路径证据；`timeout` 或 `ambiguous` 必须继续观察、等待、换路径或返回 blocker。成功时在结构化结果中保留 `artifact.file_path`、`artifact.file_name`、`download_attribution`、sourceUrl/finalUrl/referrer、以及适配 `attach_resume_artifact` 的 `business_writeback.arguments`，再由 Agent 把已验证的简历 artifact 写入共享工作区。只有在登录、验证码、权限、设备绑定或其它明确的 human-only blocker 下，才请求 human 协助；human 的职责是解除阻塞，而不是代替 Agent 完成页面导航、下载判断或本地归档。

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
