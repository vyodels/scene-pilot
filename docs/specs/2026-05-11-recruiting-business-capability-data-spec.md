# 招聘业务能力与数据规范

## 范围

本文是招聘业务能力、skill、业务事实、候选人/JD/投递数据模型和 UI/API 字段契约的合并规范。

本文只约束业务层。招聘业务不得进入 `services/backend/src/recruit_agent/agent_runtime/**`。

## 业务能力接入

招聘能力通过以下方式接入 Agent：

- `.recruit-agent/prompts/**`
- `.recruit-agent/skills/**`
- `.recruit-agent/plugins/**`
- backend thin plugin mount code
- tool schema / tool result
- MCP capability
- product adapter context
- business service / repository / projection

不允许通过 Agent runtime 分支接入。

## 业务 Tool Catalog

Recruit 业务方法需要包装为业务 tool，作为 Agent 和招聘业务系统之间的唯一可执行边界。现有业务 tool 至少覆盖：

- `list_job_descriptions` / `upsert_job_description`
- `list_candidates` / `upsert_candidate` / `delete_candidate`
- `list_candidate_threads` / `get_candidate_thread`
- `score_candidate` / `create_candidate_scorecard` / `create_candidate_review_decision`
- `record_outbound_message`
- `attach_resume_artifact` / `delete_resume_artifact`
- `transition_application` / `archive_candidate`
- `create_candidate_sync_record`
- `get_goal_progress`
- `take_over_candidate` / `release_candidate` / `list_locked_candidates`
- `request_human_approval`

业务 tool 的约束：

- tool handler 可以调用业务 service、repository、API helper 或 projection。
- tool schema 必须描述业务输入，不暴露 runtime 内部结构。
- tool result 必须返回业务对象、动作结果或可验证错误，不返回 provider payload。
- 写入、流转、删除、发送、外部副作用等高风险动作必须能被 permission / approval policy 治理。
- tool metadata 必须能标记 `business_tool`、`business_domain`、`resource_target_kind`、`capabilities` 与权限要求。

Assistant 和 Autonomous 使用同一套业务 tool。二者差异只在产品 adapter 的触发、状态、审批和用户体验，不在业务 tool 能力本身。

## Skill 沉淀

Skill 应围绕可复用业务动作沉淀，例如：

- JD 同步
- 候选人发现
- 简历结构化
- 候选人评分
- 沟通话术生成
- 跟进建议
- 候选人归档判断

Skill 不应围绕点击、翻页、tab、selector、DOM 或某站点临时页面结构沉淀为长期能力。

当业务动作可由结构化输入和确定性规则稳定完成时，应优先沉淀为 Python inline asset 或等价可执行资产。发送消息、上传附件、外部平台写入等副作用必须继续通过受治理的 tool surface 和 approval 机制执行。

## 业务事实

业务事实包括：

- candidate / candidate person
- application / 投递记录
- job description
- resume
- communication
- score / evaluation
- interview / progression
- business memory
- approval
- business result projection

这些对象属于 business data layer，可以被 product adapter、business service、tool、skill、plugin 使用，但不得进入 Agent runtime。

## 核心数据对象

```text
CandidatePerson
  -> Resume*
  -> Application*

JobDescription
  -> Application*

Application
  -> Communication*
  -> Evaluation*
  -> Approval*
```

新增业务字段必须明确：

- 所属对象
- 类型
- 是否可为空
- 来源
- 是否 human editable
- 是否可由 Agent 建议
- 是否可由 Agent 自动写入
- 审批要求
- UI 展示位置

如果字段只服务于一次运行过程，应放到 run context、runtime event 或 temporary projection，而不是进入长期业务对象。

## Agent 输出到业务事实

```text
InteractionOutput
  -> product adapter interprets result
  -> business validation
  -> business record / projection
  -> UI / API
```

禁止：

- runtime 直接写 candidate / JD / application
- runtime 直接生成业务 projection
- UI 直接解析 provider payload 当业务事实
- 把 tool loop event 当业务结果

## 运行事件与业务结果

运行事件记录“发生了什么”；业务结果记录“业务状态是什么”。

运行事件可以包含 model started/completed、tool call/result、permission requested、turn completed/failed。

业务结果应包含 status、summary、created/updated/skipped、blocker、next step、affected entities。

两者可以关联，但不能互相替代。

## Memory

长期 memory 只保存稳定、可复用、跨 run 有价值的业务知识。

不得把当前 run 的临时状态、当前 blocker、一次性页面细节、tool payload 或 UI 临时状态写入长期 memory。

## UI/API 字段治理

UI 只能展示来自 backend/shared/API 契约的字段。前端不得 mock 或硬编码业务事实字段。

需要展示 Agent 运行过程时，应展示 product adapter 生成的事件摘要，不直接展示 runtime 内部结构作为业务事实。

## 验收

业务能力和数据改动必须检查：

1. 是否没有业务字段或业务逻辑进入 `agent_runtime/**`。
2. 是否通过 tool / skill / plugin / MCP / adapter 连接 Agent 与业务对象。
3. 是否有明确 API/shared/backend 契约。
4. 是否区分 business status、run status、turn status。
5. 外部副作用是否仍受 permission / approval 治理。
6. UI 是否没有 mock 或硬编码业务事实。
