# 2026-04-28 Business Fact Contract Hardening Plan

## 背景

当前 JD 管理、投递记录跟进与沟通页面正在从“前端展示可用”收敛到“所有业务字段来自后端事实或共享契约”。本计划只记录待收敛契约与可复用能力，不把缺失字段先写成前端 mock。

## 已确认决策

- JD 列表接口返回分页 envelope：`items,total,limit,offset,hasNext`。
- JD KPI 的“较昨日”增减、`trendRate`、`trendCount` 暂时不新增 typed 后端字段；UI 不展示假趋势。
- 前端不得硬编码或 mock 候选人、投递记录、JD、状态、阶段、数量、评分、渠道、时间线、审批等业务字段值。
- 后端缺失的数据在 UI 中显示为空、禁用或“待获取”；新增字段前必须确认语义、来源和兼容策略。

## 本轮已落地

- `/api/job-descriptions` 改为分页对象，并支持 `limit/offset/status/location/department/owner/keyword` 服务端过滤。
- JD 管理页表格分页与筛选改为通过后端分页接口读取。
- JD KPI 的状态数量通过后端分页接口的 `total` 读取，不再使用前端假增减。
- 删除静态 demo 头像资源，头像只允许读取后端 `contactInfo/avatarUrl` 等真实字段，缺失时降级为空或首字。
- AI 评分、简历评分、状态汇总、时间线等前端兜底假值已收敛为缺失态。

## 待设计能力

### 1. 话术模板

现状：
- 投递记录跟进页仍有前端函数生成打招呼、发送职位、交换微信等话术。
- 后端已有 `PlaybookVersion`、共享场景模板和 runtime template 能力，但它们面向 agent 任务编排，不是招聘沟通话术模板。

建议设计：
- 新增后端领域对象 `CommunicationTemplate`，字段至少包括 `templateId`、`name`、`category`、`channel`、`applicationStatus`、`jobDescriptionId`、`body`、`variables`、`status`、`createdBy`、`updatedAt`。
- 后端提供 `GET /api/communication-templates` 与 `POST /api/communication-templates/{id}/render`，前端只负责选择模板和展示后端渲染结果。
- 可复用现有 `ApplicationThreadRead`、`JobDescriptionRead`、`PersonSummaryRead` 作为模板变量上下文，避免前端自行拼业务文案。

待确认：
- 模板是否需要按 JD、岗位族、招聘阶段、渠道分别配置。
- 模板发布是否需要审批或版本管理。

### 2. 简历结构化解析

现状：
- 后端已有 `ResumeArtifact`、`PersonResumeArtifact`、`resume_snapshot`、`contact_snapshot`、`online_resume_text`。
- 前端仍存在基于文本的 `parseResumeBasics`，用于从在线简历文本里猜年龄、学历、工作年限。

建议设计：
- 新增后端解析服务 `ResumeStructureService`，输入 `ResumeArtifact.extracted_text` 或在线简历文本，输出结构化事实。
- 结构化结果先写入 `ResumeArtifact.artifact_metadata.structured_facts` 与 `CandidateApplication.resume_snapshot.structured_facts`。
- 后续如字段稳定，再提升为 typed schema，例如 `ResumeStructuredFactsRead`。
- 前端只展示 `resume_snapshot.structured_facts` 或 artifact metadata 中的后端事实；没有则显示缺失态。

待确认：
- 结构化字段首批是否只包含姓名、年龄、学历、学校、专业、工作年限、当前城市、手机号、邮箱、技能、最近公司。
- 解析失败是否需要人工确认队列。

### 3. JD 漏斗阶段统计

现状：
- 前端 JD 管理页仍基于投递记录状态文本 token 计算沟通中、面试中、Offer 中等数量。
- 后端 recruit toolkit 已有 `get_goal_progress`，能按 JD 汇总状态数量、联系方式、简历、AI 分数。
- `packages/shared/src/types/milestone.ts` 已定义 funnel milestones，但后端未直接暴露 typed JD funnel stats。

建议设计：
- 后端新增 `JobDescriptionFunnelStatsRead`，按 `CandidateApplication.current_status`、`deepest_milestone`、`state_snapshot` 计算：
  - `applications`
  - `communicating`
  - `interviewing`
  - `offers`
  - `hired`
  - `withContact`
  - `withResume`
  - `withAiScore`
- 新增 `GET /api/job-descriptions/{id}/funnel-stats`，列表接口可选择后续内嵌轻量 stats。
- 统计口径优先复用共享 milestone 定义；如果 Python 后端无法直接复用 TS 包，应沉淀一份后端 state-machine/milestone 投影服务，并用契约测试防止前后端口径分裂。

待确认：
- JD 管理列表是否需要每行内嵌 funnel stats，还是详情侧栏打开后再拉取。
- 漏斗统计是否按当前筛选时间范围计算。

## 当前不新增的字段

- 不新增 JD `trendRate/trendCount`。
- 不新增当前用户头像字段。
- 不新增 JD owner/recruiter typed 字段。当前负责人如果需要作为正式业务字段，需要另行确认 owner 的身份模型、来源和权限边界。
