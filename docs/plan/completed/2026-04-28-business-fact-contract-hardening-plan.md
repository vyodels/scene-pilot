# 2026-04-28 Business Fact Contract Hardening Plan

> Status: completed
> Distilled into: [`docs/specs/2026-04-29-business-fact-contract-governance.md`](../../specs/2026-04-29-business-fact-contract-governance.md)
> Completed: 2026-04-29
> Note: 本计划中的持续契约治理内容已迁移为长期规范；剩余产品口径确认项由新规范承载，不再作为 active implementation plan 跟踪。

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
- JD 漏斗统计新增 `GET /api/job-descriptions/{id}/funnel-stats`，前端 JD 管理页当前页逐 JD 读取后端 typed stats，不再用前端状态文本 token 归类沟通、面试、Offer。
- 沟通话术模板迁移到 `.recruit-agent/communication_templates/default.json`，后端提供 `GET /api/communication-templates` 与 `POST /api/communication-templates/{id}/render`；前端不再拼接常用语、发送职位、交换微信、建议话术文案。
- 简历 artifact 创建时后端写入基础 `structured_facts`，前端投递跟进页不再从在线简历文本正则猜年龄、学历、工作年限。
- 删除静态 demo 头像资源，头像只允许读取后端 `contactInfo/avatarUrl` 等真实字段，缺失时降级为空或首字。
- AI 评分、简历评分、状态汇总、时间线等前端兜底假值已收敛为缺失态。

## 待设计能力

### 1. 话术模板

已落地基础版：
- 默认模板以资产文件方式存放在 `.recruit-agent/communication_templates/default.json`。
- 后端提供模板列表与按投递记录上下文渲染接口。
- 前端投递记录跟进页与共享 `ChatInputArea` 只调用后端渲染接口，不再拼接话术正文。

后续建议：
- 如果需要运营可编辑，应新增持久化领域对象 `CommunicationTemplate`，字段至少包括 `templateId`、`name`、`category`、`channel`、`applicationStatus`、`jobDescriptionId`、`body`、`variables`、`status`、`createdBy`、`updatedAt`。
- 可继续复用现有 `ApplicationThreadRead`、`JobDescriptionRead`、`PersonSummaryRead` 作为模板变量上下文。

待确认：
- 模板是否需要按 JD、岗位族、招聘阶段、渠道分别配置。
- 模板发布是否需要审批或版本管理。

### 2. 简历结构化解析

已落地基础版：
- 后端新增基础结构化解析服务，在创建 `ResumeArtifact` 时写入 `artifact_metadata.structured_facts` 与 `CandidateApplication.resume_snapshot.structured_facts`。
- 前端投递跟进页只读取 `resumeSnapshot.structured_facts` 与 typed person/contact 字段；没有结构化事实时显示缺失态。

后续建议：
- 如字段稳定，再提升为 typed schema，例如 `ResumeStructuredFactsRead`。
- 如需要更高质量解析，应接入 LLM/规则混合解析与人工确认队列，不在前端恢复文本猜测。

待确认：
- 结构化字段首批是否只包含姓名、年龄、学历、学校、专业、工作年限、当前城市、手机号、邮箱、技能、最近公司。
- 解析失败是否需要人工确认队列。

### 3. JD 漏斗阶段统计

已落地基础版：
- 后端已提供 `GET /api/job-descriptions/{id}/funnel-stats`。
- 当前统计通过后端 state machine 的 phase / milestone 计算累计漏斗：
  - `applications`
  - `communicating`
  - `interviewing`
  - `offers`
  - `hired`
  - `withContact`
  - `withResume`
  - `withAiScore`
- 前端只展示后端返回的 stats，缺失时显示缺失态。

后续建议：
- 列表接口后续可选择内嵌轻量 stats，避免当前页 N+1 请求。
- 统计口径应继续收敛到后端 state-machine/milestone 投影服务，并用契约测试防止前后端口径分裂。

待确认：
- 漏斗统计是否按当前筛选时间范围计算。

## 当前不新增的字段

- 不新增 JD `trendRate/trendCount`。
- 不新增当前用户头像字段。
- 不新增 JD owner/recruiter typed 字段。当前负责人如果需要作为正式业务字段，需要另行确认 owner 的身份模型、来源和权限边界。
