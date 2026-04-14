# 智能招聘 Agent 系统 — 完整落地方案

## 一、系统定位与核心目标

本系统是一个**独立运行的智能招聘 Agent 桌面应用**，代替人工完成招聘网站（Boss 直聘及其他平台）上的候选人发现、初筛、沟通、入库等自动化工作流。

**Agent 独立性**：Agent 是独立产品，自身具备完整的数据存储、工作流执行、Skill 管理能力，可以脱离任何外部系统独立运行。用户可以直接在 Agent 中配置工作流、筛选标准等数据，Agent 将所有数据落地到本地。

**可选的内网对接**：如果公司配置了招聘内网工作台（通过 MCP 或 API 对接），Agent 可以与其双向同步数据（工作流配置、候选人信息、人才库等）。未配置时，Agent 完全独立运行，所有数据本地管理。

核心设计原则：

- **独立优先**：Agent 本身是完整的产品，不依赖外部系统即可运行。招聘内网是可选的数据同步通道，不是 Agent 的运行前提
- **LLM 直接调用方案**：不依赖 Codex / Claude Code 等外部 Agent 框架，自建轻量 Agent Loop，保证对执行过程的完全控制权
- **Skill 驱动**：工作流中每个节点的执行能力抽象为 Skill，Agent 具备自学习、固化、自检、更新 Skill 的闭环能力
- **人机协同**：关键决策节点（Skill 落地、工作流变更）必须经人工确认，日常执行由 Agent 自主完成
- **串行操作**：因模拟用户浏览器行为，同一时刻只有一个 Agent 实例在操作，通过总控调度器实现多候选人任务的串行调度

---

## 二、整体架构

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    招聘 Agent 桌面应用（独立运行）                              │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                     前端 UI 层（TypeScript + React）                    │  │
│  │                                                                        │  │
│  │  工作流配置 │ Skill 管理 │ 候选人视图 │ Agent 监控 │ 数据看板 │ 确认/审批  │  │
│  └───────────────────────────────┬────────────────────────────────────────┘  │
│                                  │ HTTP (localhost)                          │
│  ┌───────────────────────────────┴────────────────────────────────────────┐  │
│  │                     后端服务层（Python 3.14 + FastAPI）                  │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │                       总控调度层                                   │  │  │
│  │  │  任务队列(Redis) │ 状态机管理 │ 串行调度器 │ 定时任务               │  │  │
│  │  └──────────────────────────────┬───────────────────────────────────┘  │  │
│  │                                 │                                      │  │
│  │  ┌──────────────────────────────┴───────────────────────────────────┐  │  │
│  │  │                       工作流引擎层                                 │  │  │
│  │  │  DAG 定义(工作流配置) │ 节点执行器(调用Agent) │ 条件分支(规则判断)   │  │  │
│  │  └──────────────────────────────┬───────────────────────────────────┘  │  │
│  │                                 │                                      │  │
│  │  ┌──────────────────────────────┴───────────────────────────────────┐  │  │
│  │  │                       Agent 执行层                                │  │  │
│  │  │  Agent Loop │ 工具调用层(browser-mcp/subprocess) │ 输出解析 │ 异常处理│ │  │
│  │  └──────────────────────────────┬───────────────────────────────────┘  │  │
│  │                                 │                                      │  │
│  │  ┌──────────────────────────────┴───────────────────────────────────┐  │  │
│  │  │                       基础设施层                                   │  │  │
│  │  │  提示词管理 │ 记忆体系(多层) │ Skill 管理 │ 本地数据存储(SQLite/PG)  │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │                       数据同步适配层                               │  │  │
│  │  │                                                                    │  │  │
│  │  │  ┌─────────────────────┐    ┌─────────────────────┐               │  │  │
│  │  │  │ 本地数据源 (默认)     │    │ 内网数据源 (可选)     │               │  │  │
│  │  │  │ · 工作流配置: 本地文件│    │ · 工作流配置: 从内网拉│               │  │  │
│  │  │  │ · 筛选标准: 本地配置  │    │ · 筛选标准: 从JD同步  │               │  │  │
│  │  │  │ · 候选人库: 本地DB   │    │ · 候选人库: 双向同步  │               │  │  │
│  │  │  │ · Skill库: 本地存储  │    │ · 上传结果: 推送内网  │               │  │  │
│  │  │  └─────────────────────┘    └──────────┬──────────┘               │  │  │
│  │  └────────────────────────────────────────┼──────────────────────────┘  │  │
│  └───────────────────────────────────────────┼────────────────────────────┘  │
└──────────────────────────────────────────────┼──────────────────────────────┘
                                               │
                              MCP / REST API（可选，按需配置）
                                               │
                               ┌───────────────┴───────────────┐
                               │     公司招聘内网工作台（可选）    │
                               │                               │
                               │   JD管理 │ 人才库 │ 面试流程    │
                               └───────────────────────────────┘
```

### 数据同步模式

Agent 通过数据同步适配层屏蔽数据来源差异，上层逻辑不关心数据是来自本地还是内网：

```python
class DataSourceAdapter:
    """
    统一数据访问接口
    根据配置自动切换本地/内网数据源
    """
    
    def __init__(self, config):
        self.intranet_enabled = config.get("intranet_enabled", False)
        self.intranet_client = IntranetClient(config) if self.intranet_enabled else None
        self.local_store = LocalDataStore()
    
    def get_workflow(self, jd_id: str) -> dict:
        """获取工作流配置：优先内网，回退本地"""
        if self.intranet_enabled:
            try:
                workflow = self.intranet_client.fetch_workflow(jd_id)
                self.local_store.cache_workflow(jd_id, workflow)  # 缓存到本地
                return workflow
            except ConnectionError:
                pass  # 内网不可用，回退本地
        return self.local_store.get_workflow(jd_id)
    
    def get_jd_criteria(self, jd_id: str) -> dict:
        """获取筛选标准：优先内网，回退本地"""
        if self.intranet_enabled:
            try:
                criteria = self.intranet_client.fetch_jd_criteria(jd_id)
                self.local_store.cache_criteria(jd_id, criteria)
                return criteria
            except ConnectionError:
                pass
        return self.local_store.get_criteria(jd_id)
    
    def save_candidate(self, candidate: dict):
        """保存候选人：始终存本地，有内网时同步上传"""
        self.local_store.save_candidate(candidate)
        if self.intranet_enabled:
            try:
                self.intranet_client.upload_candidate(candidate)
            except ConnectionError:
                self.local_store.mark_pending_sync(candidate["id"])
    
    def check_candidate_cooldown(self, platform_id: str) -> bool:
        """查冷却期：本地优先（本地数据更全），内网补充"""
        local_result = self.local_store.check_cooldown(platform_id)
        if local_result is not None:
            return local_result
        if self.intranet_enabled:
            try:
                return self.intranet_client.check_cooldown(platform_id)
            except ConnectionError:
                pass
        return False  # 未知则不在冷却期

    def sync_pending(self):
        """将本地积压的数据同步到内网（定时调用）"""
        if not self.intranet_enabled:
            return
        pending = self.local_store.get_pending_sync()
        for item in pending:
            try:
                self.intranet_client.upload(item)
                self.local_store.mark_synced(item["id"])
            except ConnectionError:
                break  # 内网不可用，下次再试
```

**独立运行模式**：用户在 Agent 的 UI 中直接配置工作流、输入 JD 筛选标准，所有数据存储在本地 SQLite/PostgreSQL。Agent 完全自给自足。

**内网对接模式**：用户在 Agent 设置中配置内网 MCP/API 地址和认证信息。Agent 自动从内网拉取工作流配置、JD 标准，候选人处理结果双向同步。内网断开时自动回退到本地数据，恢复后自动补推。

---

## 三、核心业务工作流

### 3.1 标准工作流节点

```
发现候选人 ──→ 候选人初筛 ──→ 沟通环节 ──→ 索要简历 ──→ AI评分 ──→ 人工介入
    │              │              │            │           │          │
    │              │              │            │           │          │
    ▼              ▼              ▼            ▼           ▼          ▼
  搜索/推荐/    查看在线简历    AI发起沟通    收到简历    多维度打分   通知HR
  主动投递      AI快速评估     预设话术沟通   联系方式    读取JD标准   定位对话框
                                                                     │
                                                              ┌──────┴──────┐
                                                              ▼             ▼
                                                         通过→入库       不通过→标记
                                                         上传人才库     冷却期N月
```

### 3.2 候选人状态流转

```
合法的状态转移关系：

discovered          → screening, cooldown
screening           → pending_communication, cooldown
pending_communication → communicating, cooldown
communicating       → waiting_reply, pending_resume, rejected
waiting_reply       → communicating, timeout_closed
pending_resume      → scoring, timeout_closed
scoring             → passed_to_talent_pool, rejected
passed_to_talent_pool → hr_review
hr_review           → team_review, rejected
team_review         → interview_scheduled, rejected
interview_scheduled → offer, rejected
```

### 3.3 冷却期与去重规则

- AI 初筛不通过：标记冷却期，1 个月内不再沟通
- 沟通后不通过：标记冷却期，1 个月内不再沟通
- 冷却期信息入内网数据库，Agent 每次接触候选人前必须查询
- 冷却期时长可按 JD / 岗位类型配置

---

## 四、模块详细设计

### 4.1 总控调度器

**职责**：管理所有候选人会话的生命周期，决定下一个执行什么任务，保证串行执行。

**核心逻辑**：

```
主循环：
  1. 从任务队列中按优先级取出一个任务
  2. 检查该任务对应的 Skill 是否 active
     - 不是 → 跳过，通知用户确认 Skill
  3. 加载候选人上下文（恢复 session）
  4. 调用 Agent 执行层完成任务
  5. 根据执行结果更新候选人状态，推进工作流
  6. 保存/挂起候选人上下文
  7. 将产出的 Skill 草案提交确认流程
  8. 回到步骤 1
```

**任务优先级规则**：

1. 候选人回复了消息（恢复等待中的会话）— 最高优先级
2. 人工确认后需要继续的任务
3. 新候选人的初筛任务
4. 主动发现候选人的任务 — 最低优先级

**串行控制**：同一时刻只有一个 Agent 在操作浏览器。调度器通过互斥锁保证这一点。上一个任务的 Agent Loop 完成/超时后，才启动下一个。

**定时任务**：

- 超时会话清理：超过 X 天未回复的候选人，关闭会话
- 长期记忆整理：定期让 LLM 合并、去重经验记忆
- Skill 健康检查：定期自检所有 active 状态的 Skill
- 每日统计报告：处理量、通过率、token 消耗等

---

### 4.2 Agent Loop（LLM 交互循环）

**核心**：这是整个系统中唯一涉及 LLM 多轮交互的部分。自研实现，不依赖外部 Agent 框架。

```python
def agent_loop(task, candidate_session, skill, tools):
    """
    核心 Agent 循环
    task: 当前任务描述
    candidate_session: 候选人上下文（可能为空）
    skill: 该任务节点的 Skill（可能为空）
    tools: 当前任务可用的工具集
    """
    # 1. 组装上下文
    messages = build_context(task, candidate_session, skill)
    
    token_budget = task.max_tokens or DEFAULT_TOKEN_BUDGET
    tokens_used = 0
    max_turns = task.max_turns or DEFAULT_MAX_TURNS
    turn = 0
    
    while turn < max_turns and tokens_used < token_budget:
        turn += 1
        
        # 2. 调用 LLM
        response = llm_call(messages, tools)
        tokens_used += response.usage.total_tokens
        
        # 3. 处理响应
        if response.has_tool_calls:
            # 3a. 工具调用 → 执行并将结果回传
            for tool_call in response.tool_calls:
                # 工具白名单校验
                if tool_call.name not in allowed_tools:
                    messages.append(tool_error("不允许的工具调用"))
                    continue
                    
                # 频率限制校验
                if rate_limited(tool_call.name):
                    messages.append(tool_error("操作过于频繁，请等待"))
                    continue
                
                # 执行工具
                try:
                    result = execute_tool(tool_call)
                    messages.append(tool_result(tool_call.id, result))
                except ToolExecutionError as e:
                    messages.append(tool_error(tool_call.id, str(e)))
            continue
        
        if response.has_result_submission:
            # 3b. 提交了结构化结果 → 任务完成
            return AgentResult(
                success=True,
                data=response.result_data,
                skill_draft=response.skill_summary,  # 如果有
                messages=messages,  # 保存完整对话用于审计
            )
        
        if response.needs_human_input:
            # 3c. 需要人工确认 → 挂起
            return AgentResult(
                success=False,
                status="waiting_human",
                question=response.content,
                messages=messages,
            )
        
        # 3d. LLM 返回了普通文本但没有调用工具也没有提交结果
        # 可能是在思考，提示它采取行动
        messages.append({
            "role": "user",
            "content": "请继续执行任务。如果已完成，请调用结果提交工具。"
        })
    
    # 超时兜底
    return AgentResult(
        success=False,
        status="timeout",
        messages=messages,
    )
```

**关键设计点**：

- 每个任务有独立的 token 预算和最大轮次限制
- 工具调用有白名单和频率限制双重校验
- 工具执行失败的错误信息会回传给 LLM，让它自行修正
- 完整的 messages 保存用于审计和调试
- 超时自动终止，不会无限循环

---

### 4.3 提示词管理体系

#### 分层结构

```
提示词 = 基础层 + 任务层 + 上下文层
```

**基础层（System Prompt）**：Agent 身份、行为准则、输出规范。始终存在，轻易不改。

```
prompts/
  base/
    identity.md          # 身份定义
    behavior_rules.md    # 行为准则（安全边界、操作限制）
    output_format.md     # 通用输出规范
```

**任务层**：按工作流节点类型分别定义，包含该节点的目标、执行步骤指引、输出格式要求。

```
prompts/
  tasks/
    discover_candidate.md      # 发现候选人
    initial_screening.md       # 初筛
    initiate_communication.md  # 发起沟通
    request_resume.md          # 索要简历
    candidate_scoring.md       # 候选人评分
    talent_pool_upload.md      # 入库汇总
```

**上下文层**：运行时动态注入的数据——Skill 策略、候选人信息、JD 标准、记忆等。

```
prompts/
  scoring_criteria/            # 按岗位的评分标准模板
    frontend_developer.md
    backend_developer.md
    product_manager.md
    ...
```

#### 提示词模板示例

```markdown
# prompts/tasks/initial_screening.md

## 任务：候选人初筛

你当前需要完成候选人的初步筛选。

### 目标
查看候选人的在线简历，根据 JD 评估标准进行快速评判，决定是否进入沟通环节。

### 执行步骤
1. 通过浏览器工具打开候选人的详情页面
2. 提取候选人的关键信息：工作年限、技能栈、当前职位、教育背景
3. 对照评估标准进行打分
4. 调用 submit_screening_result 工具提交结果

### 评估标准
{jd_criteria}

### 输出要求
必须通过 submit_screening_result 工具提交，包含：
- 各维度评分（1-10）
- 综合判断（通过/不通过）
- 一段话的判断理由（后续供 HR 查看）
- 建议的下一步动作
```

#### 版本管理与热更新

- 提示词模板以文件形式存储，通过 Git 做版本管理
- 每次任务执行时从文件系统/数据库动态读取最新版本
- 修改提示词不需要重启系统
- 保留修改历史，支持回滚

#### 上下文组装逻辑

```python
def build_context(task, candidate_session, skill):
    system_parts = []
    user_parts = []
    
    # --- System Prompt ---
    # 基础层：始终加载
    system_parts.append(load_prompt("base/identity.md"))
    system_parts.append(load_prompt("base/behavior_rules.md"))
    system_parts.append(load_prompt("base/output_format.md"))
    
    # 任务层：按节点类型加载
    task_prompt = load_prompt(f"tasks/{task.node_type}.md")
    task_prompt = fill_template(task_prompt, task.variables)
    system_parts.append(task_prompt)
    
    system_message = {"role": "system", "content": "\n\n---\n\n".join(system_parts)}
    
    # --- User Messages (上下文层) ---
    # Skill 策略（如果有）
    if skill and skill.status == "active":
        user_parts.append(f"## 参考执行方案\n\n{skill.strategy}\n\n"
                         f"按此方案执行。如发现方案失效，自行适配并在完成后输出更新版方案。")
    else:
        user_parts.append("## 注意\n\n该任务没有现成执行方案。请自主探索完成，"
                         "完成后额外输出一份结构化的执行方案总结。")
    
    # 候选人信息（如果有）
    if candidate_session:
        user_parts.append(f"## 候选人信息\n\n{format_facts(candidate_session.facts)}")
        if candidate_session.context_summary:
            user_parts.append(f"## 此前沟通历史\n\n{candidate_session.context_summary}")
    
    # JD 评分标准（筛选/评分任务时加载）
    if task.node_type in ["initial_screening", "candidate_scoring"]:
        criteria = load_jd_criteria(task.jd_id)
        user_parts.append(f"## JD 评估标准\n\n{criteria}")
    
    # 相关长期记忆
    learnings = get_relevant_learnings(task.node_type, task.platform)
    if learnings:
        user_parts.append(f"## 历史经验参考\n\n{learnings}")
    
    user_message = {"role": "user", "content": "\n\n---\n\n".join(user_parts)}
    
    # 恢复候选人会话时，注入最近几轮原始对话
    recent = candidate_session.recent_messages if candidate_session else []
    
    return [system_message, user_message] + recent
```

---

### 4.4 多层记忆体系

#### 记忆分层

| 层级 | 内容 | 存活时间 | 存储方式 | 注入策略 |
|------|------|---------|---------|---------|
| 工作记忆 | 当前 Agent Loop 的 messages 列表 | 单次任务执行期间 | 内存 | 始终存在 |
| 短期记忆 | 候选人会话摘要 + 最近几轮对话 | 候选人生命周期（天~周） | 数据库 | 处理该候选人时加载 |
| 长期记忆-事实 | 候选人数据库（联系记录、冷却期、状态） | 永久 | SQLite（独立）/ PostgreSQL（内网） | 按需查询（不注入 prompt） |
| 长期记忆-经验 | Agent 积累的平台经验、沟通技巧等 | 长期，定期整理 | 文件/数据库 | 按任务类型检索相关条目注入 |
| Skill 策略 | 任务节点的执行方案 | 长期，有版本更新 | 数据库 | 执行对应节点时注入 |

#### 候选人会话管理

```python
class CandidateSession:
    candidate_id: str
    status: str              # active / suspended / closed
    
    # 上下文
    messages: list           # 完整消息历史（活跃时）
    context_summary: str     # LLM 生成的结构化摘要（挂起时）
    recent_messages: list    # 最近 N 轮原始消息（挂起时保留）
    
    # 候选人事实信息（不压缩、不丢弃）
    facts: dict              # name, current_company, experience_years,
                             # resume_text, contact_info, ai_scores, ...
    
    # 元数据
    workflow_node: str       # 当前所在的工作流节点
    last_active: datetime
    suspend_reason: str      # waiting_reply / waiting_review / ...
    cooldown_until: datetime # 冷却期截止时间
```

#### 上下文压缩

当活跃会话的 messages 超过 token 阈值时触发：

```python
def compress_context(session):
    summary_prompt = """
    将以下对话历史压缩为结构化摘要，必须保留：
    1. 候选人表达的关键意向和诉求
    2. 已问过的问题及回答
    3. 当前沟通进展阶段
    4. 下一步应该做什么
    5. 任何异常情况或需要注意的信息
    """
    summary = llm_call(summary_prompt + format_messages(session.messages))
    session.context_summary = summary
    session.recent_messages = session.messages[-KEEP_RECENT_N:]
    session.messages = []  # 释放
```

#### 挂起与恢复

```python
def suspend_session(session):
    """候选人暂无需处理时调用"""
    if not session.context_summary:
        compress_context(session)
    db.save({
        "candidate_id": session.candidate_id,
        "context_summary": session.context_summary,
        "facts": session.facts,
        "recent_messages": session.recent_messages,
        "workflow_node": session.workflow_node,
        "status": "suspended",
        "last_active": now(),
    })

def resume_session(candidate_id, new_event=None):
    """候选人需要继续处理时调用（如收到回复）"""
    data = db.load(candidate_id)
    session = CandidateSession(**data)
    session.status = "active"
    
    # 重建消息列表由 build_context 处理
    # new_event 会作为新消息注入
    return session
```

#### 长期经验记忆

```python
def extract_learnings(task_result, messages):
    """任务完成后提取可复用的经验"""
    prompt = """
    回顾本次任务执行过程，提取值得长期记住的经验。
    只提取具有复用价值的发现，不要包含具体候选人信息。
    
    分类输出：
    - [平台经验] 关于招聘网站操作的发现
    - [沟通经验] 关于和候选人沟通的发现
    - [筛选经验] 关于评估候选人的发现
    
    如果没有新经验，输出"无"。
    """
    learnings = llm_call(prompt)
    if learnings.strip() != "无":
        append_to_memory_store("long_term_learnings", learnings, 
                               tags=[task.node_type, task.platform])

def consolidate_learnings():
    """定期整理长期记忆，合并去重，控制总量"""
    current = load_all_learnings()
    prompt = f"""
    整理以下 Agent 经验记录：
    - 合并重复或相似的条目
    - 删除已被后续条目否定的旧经验
    - 按类别重新组织
    - 控制总量在 2000 字以内
    - 保留每条经验的来源标签
    
    当前记录：
    {current}
    """
    consolidated = llm_call(prompt)
    overwrite_memory_store("long_term_learnings", consolidated)
```

---

### 4.5 Skill 管理体系

#### Skill 定义结构

```yaml
skill_id: "discover_candidates_boss_zhipin"
name: "在Boss直聘发现候选人"
version: 3
bound_to_workflow_node: "discover_candidates"
platform: "boss_zhipin"
status: "active"  # draft / pending_review / approved / active / degraded

# 策略层 — Agent 执行时的指引（自然语言，由 LLM 理解和执行）
strategy:
  objective: "从Boss直聘找到符合JD的候选人"
  steps:
    - "进入推荐候选人页面"
    - "逐个查看候选人卡片，提取基本信息（姓名、职位、经验年限）"
    - "根据JD要求做快速判断：经验年限是否匹配、技能是否相关、职位相关度"
    - "对值得深入了解的候选人，点击查看详细简历"
    - "推荐页看完后，如果数量不足，使用搜索功能按关键词补充"
    - "每个候选人处理前先查询内网数据库确认冷却期状态"
  success_criteria: "至少发现3个通过快速筛选的候选人，或推荐页+搜索页均已遍历完毕"
  exception_handling:
    - "页面加载异常 → 等待后重试，最多3次"
    - "被平台检测到异常行为 → 立即暂停，通知用户"
    - "搜索无结果 → 适当放宽关键词重试1次"

# 执行提示 — 可选的加速信息，失效不影响功能
execution_hints:
  entry_url: "https://www.zhipin.com/web/boss/recommend"
  search_url: "https://www.zhipin.com/web/boss/search"
  cached_selectors:
    candidate_card: ".recommend-item"
    next_page: ".pagination-next"

# 前置条件
preconditions:
  - "已登录Boss直聘"
  - "已有当前JD的筛选标准"

# 学习记录
learning_history:
  - version: 1
    date: "2026-03-01"
    note: "初始版本，Agent 探索 Boss 直聘推荐页生成"
    confirmed_by: "HR-张三"
  - version: 2
    date: "2026-03-15"
    note: "推荐页改版，cached_selectors 更新，策略不变"
    auto_updated: true
  - version: 3
    date: "2026-04-10"
    note: "增加搜索页作为 fallback 来源"
    confirmed_by: "HR-张三"

# 自检配置
health_check:
  method: "尝试加载入口页面，验证能看到候选人列表"
  frequency: "每次执行前"
  last_check: "2026-04-13T10:00:00Z"
  last_status: "healthy"
```

#### Skill 生命周期

```
                                    ┌─────────────────────┐
                                    │  Agent 探索任务环境   │
                                    │  推理出执行方案       │
                                    └──────────┬──────────┘
                                               │
                                               ▼
                                        ┌──────────┐
                                        │  draft    │
                                        └─────┬────┘
                                              │ 小范围试运行
                                              │ 生成确认报告
                                              ▼
                                     ┌─────────────────┐
                         ┌───────────│ pending_review   │───────────┐
                         │           └─────────────────┘           │
                    用户确认                                    用户废弃
                         │                                         │
                         ▼                                         ▼
                   ┌──────────┐                             回到 draft
                   │ approved  │                            (换思路重来)
                   └─────┬────┘
                         │ 正式执行成功
                         ▼
                   ┌──────────┐
            ┌──────│  active   │◄──────────────────────────┐
            │      └─────┬────┘                            │
            │            │ 自检失败                          │
            │            ▼                                  │
            │     ┌──────────┐                              │
            │     │ degraded  │                             │
            │     └─────┬────┘                              │
            │           │                                   │
            │     ┌─────┴──────────┐                        │
            │     ▼                ▼                        │
            │  选择器级变更      逻辑级变更                   │
            │  (自动修复)       (需确认)                     │
            │     │                │                        │
            │     │           pending_review                │
            │     │                │                        │
            │     └────────────────┴────────────────────────┘
            │
            │ 用户手动停用
            ▼
       ┌──────────┐
       │ disabled  │
       └──────────┘
```

#### Skill 产出流程

调度器给 Agent 的任务 prompt 中要求产出 Skill：

```
完成任务后，请额外输出一份结构化的执行方案总结（JSON），包含：
{
  "objective": "任务目标",
  "steps": ["实际执行的步骤序列"],
  "success_criteria": "怎么判断完成",
  "exception_handling": ["遇到的异常及处理方式"],
  "execution_hints": {
    "entry_url": "入口URL",
    "cached_selectors": {}
  }
}
```

#### Skill 消费流程

有 Skill 时注入到上下文：

```
参考执行方案（已验证有效）：
{skill.strategy 内容}

请按照上述方案执行。如果发现方案中某些步骤已失效（如页面结构变化），
自行适配并完成任务。完成后，如果方案有更新，请输出更新后的方案。
```

#### 人工确认界面

Skill 进入 pending_review 状态时，向用户呈现简化的确认报告：

```
────────────────────────────────────────────────
📋 新 Skill 待确认：「在Boss直聘发现候选人」

目标：从推荐页和搜索页找到符合JD的候选人

执行步骤：
  1. 打开推荐页，提取候选人列表
  2. 对每个候选人做快速筛选（匹配JD关键要求）
  3. 推荐页不足时，切换到搜索页补充
  4. 通过筛选的候选人进入「初筛」环节
  5. 未通过的记录到数据库，标记冷却期

异常处理：
  - 页面变化 → 自动修复选择器
  - 被平台限制 → 暂停并通知你
  - 搜索无结果 → 放宽条件重试1次

试运行结果：
  ✅ 成功从推荐页提取到 12 个候选人卡片
  ✅ 快速筛选出 4 个匹配候选人
  ✅ 数据库写入正常

[确认启用]  [修改后再试]  [废弃重来]
────────────────────────────────────────────────
```

**变更分级**：

- 选择器级变更（cached_selectors 更新）：自动修复，事后通知用户
- 策略级变更（steps/objective 改变）：必须走 pending_review 流程

---

### 4.6 Agent 自学习与自进化机制

这是整个系统最核心的能力。Agent 不是一个被预编程的 RPA 工具，而是一个能够主动理解任务、探索执行方案、固化能力、持续优化的智能体。自学习进化机制作用于整个工作流的所有环节，而不仅仅是网页解析。

#### 4.6.1 自学习的触发场景

Agent 的学习行为在以下五种场景中被触发：

```
场景一：首次遇到新任务节点（无 Skill）
  触发条件：工作流中某个节点没有对应的 active Skill
  行为：进入完整的探索式学习流程

场景二：现有 Skill 执行失败（Skill 失效）
  触发条件：Skill 自检失败 / 执行过程中连续异常
  行为：进入诊断→修复→验证流程

场景三：执行成功但发现更优路径（Skill 优化）
  触发条件：Agent 在执行过程中发现比当前 Skill 更高效的做法
  行为：记录优化建议，积累到阈值后触发 Skill 升级

场景四：任务目标变化（Skill 适配）
  触发条件：JD 要求变更、评分标准调整、工作流节点配置变化
  行为：评估现有 Skill 是否仍然适用，必要时调整

场景五：新平台接入（Skill 迁移学习）
  触发条件：需要在新的招聘平台上执行已有类型的任务节点
  行为：基于已有平台的 Skill 经验，加速学习新平台的执行方案
```

#### 4.6.2 探索式学习流程（首次学习）

当 Agent 遇到一个没有 Skill 的任务节点时，执行以下完整的学习流程：

```python
def skill_learning_flow(task_node, platform, jd_context):
    """
    完整的 Skill 探索式学习流程
    """
    
    # ============ 阶段一：任务理解 ============
    # Agent 首先理解"这个任务节点到底要干什么"
    
    understanding_prompt = f"""
    你需要学习如何完成以下任务节点：
    
    节点类型：{task_node.type}
    节点描述：{task_node.description}
    节点在工作流中的位置：{task_node.workflow_context}
    前置节点输出：{task_node.input_spec}
    后续节点期望输入：{task_node.output_spec}
    目标平台：{platform}
    
    请分析：
    1. 这个任务的核心目标是什么？
    2. 完成这个任务需要哪些关键步骤？
    3. 判断任务成功/失败的标准是什么？
    4. 可能遇到的异常情况有哪些？
    5. 你需要使用哪些工具来完成？
    
    输出你的理解，格式为 JSON。
    """
    
    task_understanding = llm_call(understanding_prompt)
    
    # ============ 阶段二：环境探索 ============
    # Agent 通过浏览器观察目标平台的实际页面结构和交互方式
    
    exploration_prompt = f"""
    你已经理解了任务目标：
    {task_understanding}
    
    现在请通过浏览器工具探索 {platform} 的相关页面：
    1. 找到完成此任务需要访问的页面
    2. 观察页面结构，理解可用的操作和信息
    3. 尝试关键操作路径，验证是否可行
    4. 记录页面的关键元素和交互模式
    
    探索过程中保持谨慎，不要执行不可逆操作（如发送消息）。
    每一步操作后，描述你观察到了什么、下一步打算做什么。
    """
    
    # 这里进入 Agent Loop，让 LLM 通过工具调用自主探索
    exploration_result = agent_loop(
        prompt=exploration_prompt,
        tools=EXPLORATION_TOOLS,  # 只包含 navigate/get_content/click/scroll，不包含发消息等操作
        max_turns=30,
        token_budget=80000,
    )
    
    # ============ 阶段三：方案推理 ============
    # 基于探索结果，推理出完整的执行方案
    
    reasoning_prompt = f"""
    基于你对任务的理解和对平台的探索：
    
    任务理解：{task_understanding}
    探索发现：{exploration_result.summary}
    
    现在请推理出一个完整的执行方案：
    
    1. 完整的步骤序列（每步包含：目标、具体操作、预期结果）
    2. 每个步骤的异常处理方式
    3. 关键页面的导航路径
    4. 页面关键元素的描述（自然语言，不依赖选择器）
    5. 成功标准（怎么判断任务完成了）
    6. 可以缓存的选择器（用于加速，但不作为硬依赖）
    
    输出格式为 Skill 策略 JSON。
    """
    
    skill_draft = llm_call(reasoning_prompt)
    
    # ============ 阶段四：试运行验证 ============
    # 用推理出的方案做一次小范围试执行
    
    trial_prompt = f"""
    请按照以下执行方案，进行一次小范围试运行：
    {skill_draft}
    
    试运行约束：
    - 只处理 1-2 个候选人（不要全量执行）
    - 如果涉及发消息，先停下来报告，不要实际发送
    - 详细记录每一步的执行情况和结果
    - 如果某个步骤失败，记录失败原因但继续尝试后续步骤
    
    试运行完成后，输出：
    1. 每步的执行结果（成功/失败/跳过）
    2. 方案需要修正的地方
    3. 最终的修正版执行方案
    """
    
    trial_result = agent_loop(
        prompt=trial_prompt,
        tools=TRIAL_TOOLS,  # 有操作限制的工具集
        max_turns=40,
        token_budget=60000,
    )
    
    # ============ 阶段五：固化与提交确认 ============
    
    if trial_result.success:
        skill = create_skill(
            skill_id=generate_skill_id(task_node.type, platform),
            strategy=trial_result.refined_plan,
            execution_hints=trial_result.cached_selectors,
            trial_report=trial_result.report,
            status="pending_review",
        )
        
        # 生成人类可读的确认报告
        confirmation_report = generate_confirmation_report(skill, trial_result)
        notify_user_for_review(skill, confirmation_report)
        
        return skill
    else:
        # 试运行失败，分析原因
        failure_analysis = analyze_failure(trial_result)
        
        if failure_analysis.retryable:
            # 可以换个思路重试（最多 N 次）
            return retry_with_different_approach(task_node, platform, failure_analysis)
        else:
            # 无法自动解决，需要人工介入
            notify_user_skill_learning_failed(task_node, failure_analysis)
            return None
```

#### 4.6.3 Skill 失效自检机制

Skill 需要持续验证自身是否仍然有效。自检分为三个层级：

```python
class SkillHealthChecker:
    
    def check_before_execution(self, skill):
        """
        执行前自检（每次使用 Skill 前调用）
        轻量级检查，快速判断 Skill 是否基本可用
        """
        checks = []
        
        # 1. 入口页面可达性检查
        entry_url = skill.execution_hints.get("entry_url")
        if entry_url:
            page = browser_navigate(entry_url)
            if not page.loaded_successfully:
                return HealthResult(status="failed", reason="入口页面无法访问")
            checks.append("entry_url_ok")
        
        # 2. 关键元素存在性检查
        cached_selectors = skill.execution_hints.get("cached_selectors", {})
        if cached_selectors:
            missing = []
            for name, selector in cached_selectors.items():
                if not browser_element_exists(selector):
                    missing.append(name)
            
            if missing:
                # 选择器失效，但不一定是策略失效
                return HealthResult(
                    status="selector_degraded",
                    reason=f"以下选择器失效：{missing}",
                    auto_fixable=True
                )
            checks.append("selectors_ok")
        
        # 3. 页面语义验证（用 LLM 快速判断）
        page_content = browser_get_content()
        semantic_check = llm_call_light(f"""
            当前页面内容摘要：{page_content[:2000]}
            
            这个 Skill 的目标是：{skill.strategy['objective']}
            预期在这个页面上应该能看到：{skill.strategy['steps'][0]}
            
            请判断当前页面是否符合预期？只回答：符合 / 不符合 / 不确定
        """)
        
        if "不符合" in semantic_check:
            return HealthResult(
                status="semantic_mismatch",
                reason="页面内容与 Skill 预期不匹配",
                auto_fixable=False  # 需要重新学习
            )
        
        return HealthResult(status="healthy", checks=checks)
    
    def deep_health_check(self, skill):
        """
        深度自检（定时执行，比如每天一次）
        完整验证 Skill 的每个步骤是否仍然可行
        """
        validation_prompt = f"""
        请对以下 Skill 进行完整性验证：
        
        Skill：{skill.name}
        策略：{json.dumps(skill.strategy, ensure_ascii=False)}
        
        验证方式：
        1. 按照策略中的每个步骤，逐步在浏览器中验证是否可执行
        2. 不要实际执行有副作用的操作（如发消息），只验证操作路径是否可达
        3. 检查每个步骤的判断逻辑是否仍然合理
        
        输出每个步骤的验证结果：
        - step_id
        - status: ok / degraded / broken
        - detail: 具体情况说明
        - fix_suggestion: 如果有问题，建议怎么修
        """
        
        result = agent_loop(
            prompt=validation_prompt,
            tools=READONLY_TOOLS,
            max_turns=20,
            token_budget=30000,
        )
        
        return result
    
    def performance_health_check(self, skill):
        """
        性能自检（基于历史执行数据）
        检测 Skill 的执行效果是否在退化
        """
        recent_executions = db.get_recent_executions(skill.skill_id, limit=20)
        
        metrics = {
            "success_rate": calc_success_rate(recent_executions),
            "avg_turns": calc_avg_turns(recent_executions),
            "avg_tokens": calc_avg_tokens(recent_executions),
            "avg_duration": calc_avg_duration(recent_executions),
            "error_types": collect_error_types(recent_executions),
        }
        
        # 与历史基线对比
        baseline = skill.performance_baseline
        
        alerts = []
        if metrics["success_rate"] < baseline["success_rate"] * 0.8:
            alerts.append("成功率显著下降")
        if metrics["avg_turns"] > baseline["avg_turns"] * 1.5:
            alerts.append("平均执行步数显著增加（可能在反复重试）")
        if metrics["avg_tokens"] > baseline["avg_tokens"] * 2:
            alerts.append("Token 消耗显著增加")
        
        if alerts:
            return HealthResult(
                status="performance_degraded",
                reason=f"性能退化：{'; '.join(alerts)}",
                metrics=metrics,
            )
        
        return HealthResult(status="healthy", metrics=metrics)
```

#### 4.6.4 Skill 失效后的自动修复与更新

根据失效类型，采取不同的修复策略：

```python
def handle_skill_degradation(skill, health_result):
    """
    Skill 失效后的分级处理
    """
    
    if health_result.status == "selector_degraded":
        # ====== 级别一：选择器失效 → 自动修复 ======
        # 策略逻辑不变，只是页面元素的定位方式变了
        
        fix_prompt = f"""
        以下 Skill 的部分选择器已失效：
        失效的选择器：{health_result.reason}
        
        请在当前页面中找到这些元素的新选择器。
        对于每个失效的选择器：
        1. 根据元素的功能描述，在页面中定位对应元素
        2. 提取新的 CSS 选择器
        3. 验证新选择器能正确定位到目标元素
        
        输出更新后的选择器映射 JSON。
        """
        
        new_selectors = agent_loop(fix_prompt, READONLY_TOOLS)
        
        # 自动更新，不需要人工确认
        skill.execution_hints["cached_selectors"] = new_selectors
        skill.version += 1
        skill.learning_history.append({
            "version": skill.version,
            "date": now(),
            "note": f"选择器自动修复：{health_result.reason}",
            "auto_updated": True,
        })
        skill.save()
        
        # 事后通知用户
        notify_user(f"Skill「{skill.name}」选择器已自动修复", level="info")
    
    elif health_result.status == "semantic_mismatch":
        # ====== 级别二：页面结构/流程变化 → 重新学习 ======
        # 页面改版导致操作流程变化，需要重新探索
        
        relearn_prompt = f"""
        Skill「{skill.name}」的目标页面已经发生变化，
        原有的执行方案可能不再适用。
        
        原方案：
        {json.dumps(skill.strategy, ensure_ascii=False)}
        
        变化情况：
        {health_result.reason}
        
        请重新探索当前页面，推理出更新后的执行方案。
        保持原有的任务目标和成功标准不变，只调整执行步骤。
        
        输出更新后的完整策略 JSON，并说明与原方案的差异。
        """
        
        updated_skill = agent_loop(relearn_prompt, EXPLORATION_TOOLS)
        
        # 需要人工确认
        skill.strategy = updated_skill.strategy
        skill.status = "pending_review"
        skill.version += 1
        skill.learning_history.append({
            "version": skill.version,
            "date": now(),
            "note": f"页面变化重新学习：{health_result.reason}",
            "requires_confirmation": True,
        })
        skill.save()
        
        notify_user_for_review(skill, "页面结构变化，Skill 已重新学习，请确认")
    
    elif health_result.status == "performance_degraded":
        # ====== 级别三：性能退化 → 诊断优化 ======
        # Skill 能用但效果变差了
        
        diagnose_prompt = f"""
        Skill「{skill.name}」近期执行表现出现退化：
        {json.dumps(health_result.metrics, ensure_ascii=False)}
        
        历史基线：
        {json.dumps(skill.performance_baseline, ensure_ascii=False)}
        
        最近的错误类型：
        {health_result.metrics['error_types']}
        
        请分析可能的原因，并给出优化建议：
        1. 是平台变化导致的？
        2. 是候选人特征变化导致的？
        3. 是策略本身有可以改进的地方？
        
        如果有明确的优化方案，请输出更新后的策略。
        """
        
        diagnosis = llm_call(diagnose_prompt)
        
        # 性能优化建议先记录，积累后再决定是否更新
        skill.optimization_suggestions.append({
            "date": now(),
            "diagnosis": diagnosis,
            "metrics_snapshot": health_result.metrics,
        })
        skill.save()
        
        # 如果诊断出明确的可修复问题
        if diagnosis.has_fix:
            skill.status = "pending_review"
            notify_user_for_review(skill, f"Skill 性能退化诊断完成，建议优化")
```

#### 4.6.5 Skill 主动优化机制

Agent 在正常执行 Skill 的过程中，持续发现优化机会并积累优化建议：

```python
def post_execution_analysis(skill, execution_result, messages):
    """
    每次 Skill 执行完毕后的反思分析
    """
    
    analysis_prompt = f"""
    你刚刚使用 Skill「{skill.name}」完成了一次任务。
    
    当前 Skill 策略：
    {json.dumps(skill.strategy, ensure_ascii=False)}
    
    本次执行摘要：
    - 耗时：{execution_result.duration}
    - 步数：{execution_result.turns}
    - Token 消耗：{execution_result.tokens_used}
    - 结果：{execution_result.status}
    - 遇到的问题：{execution_result.issues}
    
    请反思以下几个方面：
    
    1. 【效率优化】
       - 有没有可以跳过或合并的步骤？
       - 有没有更短的操作路径达到同样的结果？
       - 有没有不必要的等待或重试？
    
    2. 【质量优化】
       - 判断标准是否够准确？有没有误判的情况？
       - 异常处理是否覆盖了实际遇到的情况？
       - 有没有遗漏的边界情况？
    
    3. 【新发现】
       - 发现了平台的新功能/新入口可以利用吗？
       - 发现了候选人行为的新模式吗？
       - 发现了更好的操作时机或策略吗？
    
    如果有优化建议，输出 JSON：
    {
      "has_suggestion": true/false,
      "category": "efficiency/quality/new_capability",
      "importance": "high/medium/low",
      "current_approach": "当前做法",
      "suggested_approach": "建议做法",
      "expected_improvement": "预期改善效果",
      "confidence": "high/medium/low"
    }
    
    如果本次执行一切正常没有新发现，输出 {"has_suggestion": false}
    """
    
    analysis = llm_call(analysis_prompt)
    
    if analysis["has_suggestion"]:
        skill.optimization_log.append({
            "date": now(),
            "suggestion": analysis,
            "execution_context": execution_result.summary,
        })
        skill.save()
        
        # 检查是否积累了足够的优化建议来触发 Skill 升级
        check_optimization_threshold(skill)


def check_optimization_threshold(skill):
    """
    当优化建议积累到一定程度时，触发 Skill 升级
    """
    recent_suggestions = [
        s for s in skill.optimization_log
        if s["date"] > now() - timedelta(days=7)
    ]
    
    # 触发条件：
    # - 7天内累积 5 条以上优化建议
    # - 或者出现 2 条以上 high importance 的建议
    # - 或者出现 3 条以上同一 category 的建议
    
    high_importance = [s for s in recent_suggestions if s["suggestion"]["importance"] == "high"]
    
    should_upgrade = (
        len(recent_suggestions) >= 5 or
        len(high_importance) >= 2
    )
    
    if should_upgrade:
        trigger_skill_upgrade(skill, recent_suggestions)


def trigger_skill_upgrade(skill, suggestions):
    """
    基于积累的优化建议，生成升级版 Skill
    """
    upgrade_prompt = f"""
    Skill「{skill.name}」收到了多条优化建议，需要升级。
    
    当前策略（v{skill.version}）：
    {json.dumps(skill.strategy, ensure_ascii=False)}
    
    近期优化建议汇总：
    {json.dumps([s["suggestion"] for s in suggestions], ensure_ascii=False)}
    
    近期执行统计：
    {json.dumps(skill.recent_metrics, ensure_ascii=False)}
    
    请综合所有建议，生成升级版策略：
    1. 将有价值的优化建议融入策略步骤
    2. 保持核心目标不变
    3. 明确标注与当前版本的差异
    4. 评估升级后的预期效果
    
    输出：
    - upgraded_strategy: 升级后的完整策略 JSON
    - changes_summary: 变更摘要（给人看的简要说明）
    - expected_improvements: 预期改善
    """
    
    upgrade_result = llm_call(upgrade_prompt)
    
    # 升级版 Skill 必须经人工确认
    skill.pending_upgrade = upgrade_result
    skill.status = "pending_review"
    skill.save()
    
    notify_user_for_review(skill, f"""
    📈 Skill 优化升级待确认：「{skill.name}」v{skill.version} → v{skill.version + 1}
    
    变更摘要：{upgrade_result['changes_summary']}
    
    基于近期 {len(suggestions)} 条执行反馈的优化。
    预期改善：{upgrade_result['expected_improvements']}
    
    [确认升级]  [保持现版本]  [查看详情]
    """)
```

#### 4.6.6 任务理解与 Skill 拆解能力

Agent 不只是学习"怎么做一个已定义好的任务节点"，还需要能够**主动理解一个模糊的任务描述，拆解成可执行的子任务，并为每个子任务建立 Skill**：

```python
def understand_and_decompose_task(task_description, workflow_context):
    """
    当用户给出一个较模糊的任务描述时，
    Agent 主动理解、拆解、并规划 Skill 学习路径
    """
    
    decompose_prompt = f"""
    用户描述了一个新的工作任务：
    "{task_description}"
    
    当前工作流上下文：
    {workflow_context}
    
    已有的 Skill 库：
    {list_existing_skills_summary()}
    
    请完成以下分析：
    
    1. 【任务理解】
       这个任务的最终目标是什么？
       需要在哪个平台上完成？
       输入是什么？输出是什么？
    
    2. 【子任务拆解】
       将这个任务拆解为有序的子任务列表。
       每个子任务应该是一个可独立完成的操作单元。
       标注每个子任务之间的依赖关系。
    
    3. 【Skill 映射】
       对于每个子任务：
       - 已有的 Skill 是否可以直接复用？（标注 skill_id）
       - 已有的 Skill 是否可以稍作修改复用？（标注修改点）
       - 需要全新学习？（标注学习优先级）
    
    4. 【学习计划】
       对于需要新学习的子任务，按以下优先级排序：
       - 阻塞其他子任务的优先
       - 复杂度低的优先（快速出成果）
       - 有类似 Skill 可参考的优先
    
    输出格式 JSON：
    {
      "task_understanding": {...},
      "subtasks": [
        {
          "id": "subtask_1",
          "name": "...",
          "description": "...",
          "depends_on": [],
          "existing_skill": null / "skill_id",
          "needs_modification": false,
          "needs_learning": true,
          "learning_priority": 1,
          "estimated_complexity": "low/medium/high"
        },
        ...
      ],
      "learning_plan": [
        {
          "order": 1,
          "subtask_id": "subtask_1",
          "approach": "从零学习 / 基于已有 Skill 修改 / 迁移学习",
          "reference_skill": null / "existing_skill_id"
        },
        ...
      ]
    }
    """
    
    decomposition = llm_call(decompose_prompt)
    
    # 向用户确认拆解方案
    confirmation = present_decomposition_to_user(decomposition)
    
    if confirmation.approved:
        # 按学习计划依次学习每个子任务的 Skill
        for learning_task in decomposition["learning_plan"]:
            subtask = find_subtask(decomposition, learning_task["subtask_id"])
            
            if learning_task["approach"] == "从零学习":
                skill = skill_learning_flow(subtask, platform, jd_context)
            
            elif learning_task["approach"] == "基于已有 Skill 修改":
                skill = skill_adaptation_flow(
                    subtask, 
                    reference_skill=load_skill(learning_task["reference_skill"])
                )
            
            elif learning_task["approach"] == "迁移学习":
                skill = skill_transfer_learning(
                    subtask,
                    source_skill=load_skill(learning_task["reference_skill"]),
                    target_platform=platform,
                )
            
            # 每个 Skill 学习完都需要人工确认
            if skill and skill.status == "pending_review":
                wait_for_user_confirmation(skill)
    
    return decomposition
```

#### 4.6.7 跨平台 Skill 迁移学习

当需要在新平台上执行已有类型的任务时，不从零开始，而是基于已有平台的 Skill 经验加速学习：

```python
def skill_transfer_learning(subtask, source_skill, target_platform):
    """
    将一个平台的 Skill 迁移到新平台
    保留策略逻辑，重新学习平台特定的操作方式
    """
    
    transfer_prompt = f"""
    你需要将以下 Skill 从 {source_skill.platform} 迁移到 {target_platform}：
    
    原 Skill：{source_skill.name}
    原策略：
    {json.dumps(source_skill.strategy, ensure_ascii=False)}
    
    迁移原则：
    1. 任务目标和成功标准保持一致
    2. 策略的逻辑步骤尽量复用（如"查看候选人卡片→提取信息→快速判断"）
    3. 平台特定的操作方式需要重新学习（如页面结构、按钮位置、交互方式）
    4. 平台特有的功能/限制需要适配
    
    请先探索 {target_platform} 的相关页面，然后：
    1. 找出原策略中哪些步骤可以直接复用
    2. 找出哪些步骤需要重新适配
    3. 是否有新平台特有的优势可以利用
    4. 生成适配后的完整策略
    """
    
    transfer_result = agent_loop(
        prompt=transfer_prompt,
        tools=EXPLORATION_TOOLS,
        max_turns=30,
    )
    
    # 生成新平台的 Skill
    new_skill = create_skill(
        skill_id=generate_skill_id(subtask.type, target_platform),
        strategy=transfer_result.strategy,
        execution_hints=transfer_result.hints,
        status="pending_review",
        transfer_source=source_skill.skill_id,  # 记录迁移来源
    )
    
    return new_skill
```

#### 4.6.8 工作流级别的自优化

不止是单个 Skill 会进化，整个工作流也需要根据实际运行情况自我优化：

```python
def workflow_self_optimization(workflow, execution_history):
    """
    定期（如每周）对整个工作流进行反思优化
    """
    
    optimization_prompt = f"""
    以下是招聘工作流在过去一周的运行统计：
    
    工作流定义：
    {json.dumps(workflow.config, ensure_ascii=False)}
    
    各节点执行统计：
    {json.dumps(execution_history.per_node_stats, ensure_ascii=False)}
    
    整体漏斗数据：
    - 发现候选人：{stats.discovered} 人
    - 初筛通过：{stats.screening_passed} 人（{stats.screening_rate}%）
    - 沟通回复：{stats.replied} 人（{stats.reply_rate}%）
    - 简历获取：{stats.resume_received} 人（{stats.resume_rate}%）
    - AI评分通过：{stats.scoring_passed} 人（{stats.scoring_rate}%）
    - 最终入库：{stats.talent_pool} 人（{stats.overall_rate}%）
    
    瓶颈节点：{stats.bottleneck_node}
    最耗时节点：{stats.slowest_node}
    最耗 Token 节点：{stats.most_expensive_node}
    
    HR 反馈汇总：
    {execution_history.hr_feedback_summary}
    
    请分析：
    
    1. 工作流是否有冗余或不合理的节点？
    2. 节点顺序是否最优？（比如某些检查是否应该提前）
    3. 是否需要增加新的节点？（比如增加一个预筛选步骤减少无效沟通）
    4. 各节点的阈值设置是否合理？（比如 AI 评分的通过分数线）
    5. 是否有可以并行化的步骤？（在串行约束下的逻辑并行）
    
    输出：
    {
      "has_optimization": true/false,
      "suggestions": [
        {
          "type": "add_node / remove_node / reorder / adjust_threshold / other",
          "description": "...",
          "expected_impact": "...",
          "confidence": "high/medium/low",
          "proposed_change": {...}  // 具体的工作流变更
        }
      ]
    }
    """
    
    analysis = llm_call(optimization_prompt)
    
    if analysis["has_optimization"]:
        # 筛选高置信度的建议
        high_confidence = [
            s for s in analysis["suggestions"] 
            if s["confidence"] == "high"
        ]
        
        if high_confidence:
            # 向用户展示优化建议
            notify_user(f"""
            📊 工作流周度优化建议
            
            基于过去一周 {stats.discovered} 个候选人的处理数据分析：
            
            {''.join([format_suggestion(s) for s in high_confidence])}
            
            [查看详情并确认]  [暂不调整]
            """)
```

#### 4.6.9 自学习的安全护栏

自进化能力必须有边界和约束，防止 Agent "学歪了"：

```python
LEARNING_GUARDRAILS = {
    # 学习过程的约束
    "max_exploration_turns": 30,        # 单次探索最多30轮交互
    "max_learning_token_budget": 100000, # 单次学习最多消耗10万 token
    "max_retry_attempts": 3,            # 学习失败最多重试3次
    "exploration_tools_only": True,     # 探索时不能执行有副作用的操作
    
    # Skill 变更的约束
    "auto_update_scope": "selectors_only",  # 自动更新只限于选择器级
    "strategy_change_requires_review": True, # 策略变更必须人工确认
    "workflow_change_requires_review": True,  # 工作流变更必须人工确认
    
    # 优化的约束
    "min_executions_before_optimization": 10,  # 至少执行10次才有足够数据优化
    "optimization_cooldown_days": 3,           # 同一 Skill 的优化间隔至少3天
    "max_optimization_frequency": "weekly",    # 工作流优化最多每周一次
    
    # 质量兜底
    "trial_run_required": True,                # 新 Skill 必须先试运行
    "trial_scope_limit": 2,                    # 试运行最多处理2个候选人
    "rollback_on_degradation": True,           # 性能退化时自动回滚到上一版本
}
```

#### 4.6.10 学习进度的可视化与追踪

向用户展示 Agent 的学习状态和能力覆盖情况：

```yaml
学习状态看板：

┌─────────────────────────────────────────────────────────────┐
│  Skill 能力覆盖图                                            │
│                                                              │
│  ┌──────────────────┬────────────┬────────────┬───────────┐ │
│  │ 工作流节点        │ Boss直聘   │  猎聘       │  拉勾      │ │
│  ├──────────────────┼────────────┼────────────┼───────────┤ │
│  │ 发现候选人        │ ✅ v3      │ ✅ v1      │ 🔄 学习中  │ │
│  │ 初筛              │ ✅ v2      │ ✅ v1      │ ⏳ 待学习   │ │
│  │ 发起沟通          │ ✅ v4      │ ⚠️ v2 退化  │ ⏳ 待学习   │ │
│  │ 索要简历          │ ✅ v2      │ ✅ v1      │ ⏳ 待学习   │ │
│  │ AI评分            │ ✅ v3 (通用)│            │            │ │
│  │ 入库汇总          │ ✅ v1 (通用)│            │            │ │
│  └──────────────────┴────────────┴────────────┴───────────┘ │
│                                                              │
│  本周学习活动：                                               │
│  · 新学习 Skill 2 个（拉勾-发现候选人 学习中）                 │
│  · 自动修复 1 个（Boss直聘选择器更新）                         │
│  · 优化升级 1 个（发起沟通 v3→v4，沟通回复率提升 12%）         │
│  · 性能退化告警 1 个（猎聘-发起沟通，待诊断）                  │
│                                                              │
│  学习消耗：本周 Token 消耗 320K（学习占比 40%，执行占比 60%）   │
└─────────────────────────────────────────────────────────────┘
```

#### 4.6.11 完整的自学习循环总览

```
                    ┌─────────────────────────────────┐
                    │         自学习进化引擎            │
                    └─────────────────┬───────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
              ▼                       ▼                       ▼
     ┌────────────────┐    ┌──────────────────┐    ┌──────────────────┐
     │  主动学习       │    │  被动修复         │    │  持续优化         │
     │                │    │                  │    │                  │
     │  新任务节点     │    │  Skill 失效检测   │    │  执行后反思       │
     │  ↓             │    │  ↓               │    │  ↓               │
     │  任务理解       │    │  失效分级判断     │    │  优化建议积累     │
     │  ↓             │    │  ↓               │    │  ↓               │
     │  环境探索       │    │  自动修复(选择器) │    │  达到阈值         │
     │  ↓             │    │  或              │    │  ↓               │
     │  方案推理       │    │  重新学习(逻辑)   │    │  生成升级方案     │
     │  ↓             │    │  ↓               │    │  ↓               │
     │  试运行验证     │    │  验证修复结果     │    │  工作流级优化     │
     │  ↓             │    │  ↓               │    │  ↓               │
     │  人工确认       │    │  自动/人工确认    │    │  人工确认         │
     │  ↓             │    │  ↓               │    │  ↓               │
     │  Skill 落地     │    │  Skill 更新      │    │  Skill/工作流升级 │
     └────────┬───────┘    └────────┬─────────┘    └────────┬─────────┘
              │                     │                       │
              └─────────────────────┼───────────────────────┘
                                    │
                                    ▼
                         ┌──────────────────┐
                         │  Skill 库 + 经验库 │
                         │  (能力持续积累)     │
                         └──────────────────┘
                                    │
                              反哺下次执行
                                    │
                                    ▼
                         ┌──────────────────┐
                         │  Agent 越来越强    │
                         │  · 执行更快        │
                         │  · 判断更准        │
                         │  · 异常处理更全     │
                         │  · 覆盖平台更多     │
                         └──────────────────┘
```

---

### 4.7 工具定义与管理

#### 工具分组

按任务节点类型加载不同的工具子集，减少 LLM 误调用：

```python
TOOL_GROUPS = {
    "discover_candidates": [
        "browser_navigate", "browser_get_content",
        "browser_click", "browser_scroll",
        "db_check_candidate_cooldown",
        "db_save_candidate",
        "submit_discovery_result",       # 结构化结果提交
    ],
    "initial_screening": [
        "browser_navigate", "browser_get_content",
        "browser_click",
        "db_read_jd_criteria",
        "submit_screening_result",
    ],
    "communication": [
        "browser_navigate", "browser_get_content",
        "browser_type", "browser_click",
        "browser_upload_file",
        "db_read_candidate_info",
        "submit_communication_result",
    ],
    "candidate_scoring": [
        "db_read_jd_criteria",
        "db_read_candidate_info",
        "db_read_resume",
        "db_read_communication_history",
        "submit_scoring_result",
    ],
}
```

#### 工具描述原则

- 写给 LLM 看，不是写给程序员看
- 明确说明何时使用、何时不使用
- 包含使用约束和常见错误提示
- 参数说明用自然语言

#### 结构化结果提交工具

每个任务节点有对应的结果提交工具，强制 LLM 以结构化方式返回：

```python
{
    "name": "submit_screening_result",
    "description": "提交候选人初筛结果。初筛完成后必须调用此工具。",
    "parameters": {
        "candidate_id": {"type": "string"},
        "passed": {"type": "boolean"},
        "scores": {
            "type": "object",
            "properties": {
                "experience_match": {"type": "integer", "min": 1, "max": 10},
                "skill_match": {"type": "integer", "min": 1, "max": 10},
                "education": {"type": "integer", "min": 1, "max": 10},
                "overall": {"type": "integer", "min": 1, "max": 10},
            }
        },
        "reasoning": {"type": "string", "description": "一段话的判断理由，供HR查看"},
        "next_action": {
            "type": "string",
            "enum": ["proceed_to_communication", "reject_and_cooldown", "need_more_info"]
        }
    }
}
```

---

### 4.8 工作流引擎

#### 工作流定义格式

```yaml
workflow_id: "standard_recruitment_v1"
name: "标准招聘流程"
jd_id: "jd_frontend_senior"

nodes:
  - id: "discover"
    type: "discover_candidates"
    skill_id: "discover_candidates_boss_zhipin"  # 绑定的 Skill
    config:
      max_candidates_per_run: 20
      platforms: ["boss_zhipin"]
    next:
      - condition: "candidate_found"
        target: "screening"

  - id: "screening"
    type: "initial_screening"
    skill_id: "initial_screening_boss_zhipin"
    next:
      - condition: "passed"
        target: "communication"
      - condition: "rejected"
        target: "mark_cooldown"

  - id: "communication"
    type: "initiate_communication"
    skill_id: "communication_boss_zhipin"
    config:
      greeting_template: "templates/greeting_frontend.md"
      questions: ["期望薪资", "到岗时间", "离职原因"]
    next:
      - condition: "resume_received"
        target: "scoring"
      - condition: "no_reply_timeout"
        target: "mark_timeout"
      - condition: "rejected_by_candidate"
        target: "mark_rejected"

  - id: "scoring"
    type: "candidate_scoring"
    skill_id: "candidate_scoring_general"
    config:
      criteria_id: "criteria_frontend_senior"
    next:
      - condition: "passed"
        target: "notify_hr"
      - condition: "rejected"
        target: "mark_cooldown"

  - id: "notify_hr"
    type: "human_intervention"
    config:
      notification_channel: "dingtalk"  # 通知渠道
      auto_position_chat: true          # 自动定位到对话框
      timeout_hours: 48                 # HR 超时未处理的提醒
    next:
      - condition: "hr_approved"
        target: "upload_talent_pool"
      - condition: "hr_rejected"
        target: "mark_rejected"

  - id: "upload_talent_pool"
    type: "talent_pool_upload"
    skill_id: "talent_pool_upload_intranet"
    # 后续流程...

  - id: "mark_cooldown"
    type: "system_action"
    action: "set_cooldown"
    config:
      cooldown_days: 30

  - id: "mark_timeout"
    type: "system_action"
    action: "close_session"
    config:
      reason: "timeout_no_reply"

  - id: "mark_rejected"
    type: "system_action"
    action: "close_session"
    config:
      reason: "rejected"
```

#### 工作流编排由 LLM 辅助

用户可以用自然语言描述工作流需求，LLM 生成上述 YAML 配置的初版，用户在内网 UI 上确认/调整后保存。

工作流变更的确认流程：

1. 用户描述需求变更 → LLM 生成新版工作流
2. 对比差异，向用户展示变更内容
3. 用户确认后生效
4. 运行中发现工作流不合理 → Agent 提出修改建议 → 用户确认

---

### 4.9 安全与权限控制

#### 操作白名单

```yaml
allowed_operations:
  browser:
    - navigate          # 打开页面
    - get_content       # 读取内容
    - click             # 点击元素
    - type              # 输入文本
    - scroll            # 滚动页面
    - upload_file       # 上传文件（简历）
  
  database:
    - read_candidate    # 读取候选人信息
    - write_candidate   # 写入/更新候选人信息
    - read_jd           # 读取 JD 信息
    - read_criteria     # 读取评分标准

forbidden_operations:
  - 修改招聘网站账号设置
  - 删除任何数据库记录
  - 点击付费功能
  - 访问非招聘相关页面
  - 向外部发送候选人隐私数据
```

#### 频率限制

```yaml
rate_limits:
  boss_zhipin:
    browser_actions_per_minute: 10
    messages_per_hour: 20
    messages_per_day: 50
    profile_views_per_hour: 30
  
  general:
    llm_calls_per_minute: 30
    max_concurrent_browser_sessions: 1
```

#### 敏感信息处理

- 候选人手机号、微信号、简历内容：可存入内网数据库，日志中脱敏显示
- LLM API 调用中包含的候选人信息：评估数据合规风险，考虑使用支持数据隐私的 API 方案
- 操作日志中的个人信息：定期清理或脱敏

---

### 4.10 可观测性与审计

#### 日志体系

```python
# 每次 LLM 调用记录
llm_call_log = {
    "timestamp": "...",
    "task_id": "...",
    "candidate_id": "...",
    "turn": 3,
    "input_tokens": 2500,
    "output_tokens": 800,
    "tools_called": ["browser_navigate", "browser_get_content"],
    "tool_results_summary": "...",
    "llm_response_summary": "...",
    "full_messages": "..."  # 存储完整 prompt，用于调试
}

# 关键决策记录
decision_log = {
    "timestamp": "...",
    "candidate_id": "...",
    "decision_type": "initial_screening",
    "decision": "passed",
    "scores": {"experience": 8, "skill": 7, "education": 6, "overall": 7},
    "reasoning": "候选人有5年React经验...",
    "input_context": "...",  # 决策时的完整输入（JD + 简历），供HR复查
}

# 操作记录
operation_log = {
    "timestamp": "...",
    "task_id": "...",
    "operation": "browser_click",
    "target": "发送消息按钮",
    "result": "success",
    "screenshot_path": "...",  # 可选：关键操作截图
}
```

#### 异常告警

```yaml
alert_rules:
  - name: "连续工具调用失败"
    condition: "同一任务连续3次工具调用失败"
    action: "暂停任务，通知用户"
    channel: "dingtalk"
  
  - name: "任务超时"
    condition: "单任务执行超过15分钟"
    action: "强制终止，记录现场"
  
  - name: "Token 预算耗尽"
    condition: "单任务 token 消耗超过预算"
    action: "终止任务，标记需人工处理"
  
  - name: "Skill 自检失败"
    condition: "Skill 健康检查连续2次失败"
    action: "标记 Skill 为 degraded，通知用户"
  
  - name: "平台异常"
    condition: "招聘平台返回登录页/验证码/封号提示"
    action: "暂停所有任务，紧急通知用户"
```

---

### 4.11 成本控制

#### Token 预算管理

```yaml
token_budgets:
  per_task:
    discover_candidates: 50000    # 涉及多页浏览，消耗较大
    initial_screening: 15000      # 单次评估，较简单
    communication: 20000          # 沟通内容生成
    candidate_scoring: 20000      # 多维度评分
    skill_learning: 100000        # 首次学习 Skill，允许更多探索
  
  per_day: 500000                 # 每日总预算
  
  alert_threshold: 0.8            # 消耗达到80%时告警
```

#### 模型分级策略

模型分级通过 LLMManager 的路由配置实现（详见 6.2 LLM Provider 抽象层）：

```yaml
model_routing:
  # 轻量任务用小模型（成本低、速度快）
  light:
    provider: anthropic
    model: claude-haiku-4
    tasks:
      - "判断页面是否加载完成"
      - "提取页面中的结构化信息"
      - "简单的是非判断"
  
  # 核心任务用强模型
  heavy:
    provider: anthropic
    model: claude-sonnet-4-20250514
    tasks:
      - "候选人评分"
      - "沟通内容生成"
      - "Skill 学习"
      - "工作流编排"
      - "上下文压缩/摘要"
  
  # 复杂推理用最强模型
  reasoning:
    provider: anthropic
    model: claude-opus-4
    fallback:
      provider: deepseek
      model: deepseek-reasoner
    tasks:
      - "异常诊断"
      - "工作流调整建议"
```

用户可以在设置中灵活配置：全部用 Anthropic、全部用 OpenAI、或者混合使用。每个层级还支持 fallback，主 Provider 不可用时自动切换。

---

### 4.12 评估与反馈闭环

#### 量化指标

```yaml
metrics:
  efficiency:
    - "每日处理候选人数量"
    - "平均每个候选人的处理耗时"
    - "平均每个候选人的 token 消耗"
    - "Skill 复用率（使用已有 Skill vs 重新学习）"
  
  quality:
    - "AI初筛通过 → HR二次筛选也通过的比例（准确率）"
    - "AI初筛拒绝 → HR认为不应该拒绝的比例（误杀率）"
    - "候选人沟通回复率"
    - "候选人主动提供简历的比例"
    - "从发现到入库的平均耗时"
  
  stability:
    - "工具调用成功率"
    - "任务超时率"
    - "Skill 自检失败率"
    - "系统异常频率"
```

#### HR 反馈回流

```python
def on_hr_override(candidate_id, ai_decision, hr_decision, hr_reason):
    """HR 推翻 AI 决策时触发"""
    if ai_decision != hr_decision:
        candidate = db.load_candidate(candidate_id)
        
        # 让 LLM 从分歧中提取经验
        learning_prompt = f"""
        AI 与 HR 对候选人的判断不一致：
        候选人背景：{candidate.summary}
        AI 判断：{ai_decision}，理由：{candidate.ai_reasoning}
        HR 判断：{hr_decision}，理由：{hr_reason}
        
        请总结出一条可复用的经验教训，用于改进后续的筛选判断。
        """
        learning = llm_call(learning_prompt)
        append_to_long_term_memory(learning, tags=["screening_calibration"])
        
        # 统计分歧率，用于调整评分阈值
        update_calibration_stats(ai_decision, hr_decision, candidate.jd_id)
```

---

### 4.13 多平台适配

#### 平台抽象层

工作流引擎不关心具体平台，Skill 封装平台差异：

```python
# 同一个工作流节点，不同平台用不同 Skill
skill = find_skill(
    workflow_node="discover_candidates",
    platform=task.platform  # "boss_zhipin" / "liepin" / "lagou"
)
```

新增平台的步骤：

1. 创建该平台的账号配置（URL、频率限制等）
2. 让 Agent 学习该平台对应的各节点 Skill（discovery、screening、communication...）
3. 每个 Skill 经人工确认后即可投入使用

#### 平台配置

```yaml
platforms:
  boss_zhipin:
    name: "Boss直聘"
    base_url: "https://www.zhipin.com"
    login_check_hint: "检查是否有登录态（头像/用户名元素存在）"
    rate_limits:
      actions_per_minute: 10
      messages_per_day: 50
    special_notes:
      - "Boss直聘使用实时聊天模式，不是邮件模式"
      - "候选人简历分为在线简历和附件简历两种"

  liepin:
    name: "猎聘"
    base_url: "https://www.liepin.com"
    login_check_hint: "..."
    rate_limits:
      actions_per_minute: 8
      messages_per_day: 40
    special_notes:
      - "猎聘的候选人详情页需要额外权限查看完整信息"
```

---

### 4.14 部署与运维

#### 运行模式

```
总控调度器: 后台守护进程，持续运行
  ├── 主任务循环: 从队列取任务 → 执行 → 更新状态
  ├── 定时任务-超时清理: 每小时执行
  ├── 定时任务-记忆整理: 每天执行
  ├── 定时任务-Skill自检: 每天执行
  ├── 定时任务-日报生成: 每天执行
  └── 事件监听: 候选人回复消息 → 触发高优先级任务
```

#### 优雅停机

```python
def shutdown_handler(signal):
    """收到停止信号时"""
    logger.info("收到停止信号，等待当前任务完成...")
    scheduler.stop_accepting_new_tasks()
    
    if current_task:
        # 等待当前 Agent Loop 完成（或超时强制终止）
        current_task.wait(timeout=60)
        # 保存当前候选人会话状态
        suspend_session(current_session)
    
    # 持久化队列状态
    save_queue_state()
    logger.info("安全退出")
```

#### 健康检查

```python
def health_check():
    checks = {
        "browser": check_browser_mcp_available(),
        "llm_api": check_llm_api_available(),
        "database": check_db_connection(),
        "platform_login": check_platform_login_status(),
    }
    
    all_healthy = all(checks.values())
    if not all_healthy:
        failed = [k for k, v in checks.items() if not v]
        alert(f"健康检查失败：{failed}")
        scheduler.pause_tasks()
    
    return checks
```

---

## 五、数据模型

### 5.1 核心数据表

```
candidates（候选人主表）
├── id
├── name
├── platform                    # 来源平台
├── platform_candidate_id       # 平台上的候选人ID
├── status                      # 当前状态
├── current_workflow_node       # 当前工作流节点
├── jd_id                       # 关联的JD
├── contact_info                # 联系方式（加密存储）
├── resume_path                 # 简历文件路径
├── online_resume_text          # 在线简历文本
├── ai_scores                   # AI评分（JSON）
├── ai_reasoning                # AI评分理由
├── cooldown_until              # 冷却期截止
├── created_at
├── updated_at
└── last_contacted_at

candidate_sessions（候选人会话）
├── id
├── candidate_id
├── status                      # active / suspended / closed
├── context_summary             # 上下文摘要
├── recent_messages             # 最近N轮消息（JSON）
├── facts                       # 事实信息快照（JSON）
├── suspend_reason
├── created_at
├── updated_at
└── last_active_at

communication_logs（沟通记录）
├── id
├── candidate_id
├── direction                   # inbound / outbound
├── content                     # 消息内容
├── message_type                # text / file / system
├── platform
├── timestamp

skills（Skill 库）
├── id
├── skill_id                    # 业务标识
├── name
├── version
├── status                      # draft / pending_review / approved / active / degraded / disabled
├── bound_to_workflow_node
├── platform
├── strategy                    # 策略内容（JSON/YAML）
├── execution_hints             # 执行提示（JSON）
├── health_check_config         # 自检配置
├── last_health_check
├── last_health_status
├── confirmed_by                # 确认人
├── confirmed_at
├── created_at
├── updated_at

workflows（工作流配置）
├── id
├── name
├── jd_id
├── config                      # 完整工作流定义（YAML/JSON）
├── status                      # active / draft / archived
├── version
├── created_at
├── updated_at

decision_logs（决策审计日志）
├── id
├── candidate_id
├── task_id
├── decision_type
├── decision
├── scores
├── reasoning
├── input_context_snapshot       # 决策时的完整输入
├── hr_override                 # HR 是否推翻
├── hr_override_reason
├── timestamp

agent_learnings（长期经验记忆）
├── id
├── content                     # 经验内容
├── tags                        # 分类标签
├── source_task_id              # 来源任务
├── created_at
├── consolidated_at             # 上次整理时间
├── is_active                   # 是否仍有效
```

---

## 六、技术栈

| 组件 | 方案 | 说明 |
|------|------|------|
| **后端语言** | **Python 3.14.2** | Agent 引擎、调度器、工具调用、LLM 交互 |
| **后端框架** | **FastAPI** | 异步 HTTP 服务，为前端提供 API + WebSocket |
| **前端语言** | **TypeScript + React** | 桌面应用 UI，现代 Web 技术栈 |
| **桌面壳** | **Electron** | 封装 Web 前端 + 启动本地 FastAPI 后端 |
| LLM API | OpenAI 格式 + Anthropic 格式（多 Provider） | 统一抽象层，支持切换和混用 |
| 浏览器操作 | Browser-MCP（已有） | 已有能力，直接复用 |
| 任务队列 | Redis (Queue/Stream) 或内存队列 | 独立运行时可用内存队列，生产环境用 Redis |
| 数据库 | SQLite（独立模式）/ PostgreSQL（内网模式） | 独立运行用 SQLite 零配置，连内网时可切换 PG |
| 文件存储 | 本地文件系统 | 简历、截图、Skill 文件 |
| 提示词管理 | Git + 文件系统 | 版本管理、热更新 |
| 系统命令执行 | subprocess (Python 标准库) | Agent 扩展能力的基础 |
| 打包分发 | electron-builder + PyInstaller | macOS .app，内嵌 Python 后端 |

---

## 6.1 桌面应用架构（Electron + FastAPI）

### 架构原理

和 LobeChat 桌面版原理一致：**Electron 提供桌面壳和本地系统能力，Web 技术做 UI，后端服务处理业务逻辑**。区别在于 LobeChat 用 Node.js 做后端，你的系统用 Python FastAPI 做后端。

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Electron 桌面应用 (.app)                           │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                 Electron 主进程 (Node.js)                       │  │
│  │                                                                │  │
│  │  · 应用生命周期管理（启动/退出）                                  │  │
│  │  · 启动内嵌的 Python FastAPI 后端（子进程）                      │  │
│  │  · 启动 browser-mcp（子进程）                                   │  │
│  │  · 系统托盘、菜单、通知                                         │  │
│  │  · 自动更新                                                    │  │
│  └──────────────────────────┬─────────────────────────────────────┘  │
│                              │ IPC                                    │
│  ┌──────────────────────────┴─────────────────────────────────────┐  │
│  │              Electron 渲染进程（TypeScript + React）             │  │
│  │                                                                │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │  │
│  │  │ 工作流管理│ │ Skill 管理│ │ 候选人视图│ │ Agent 监控/日志  │  │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘  │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │  │
│  │  │ 数据看板  │ │ 确认/审批 │ │ 设置页面  │ │ 内网连接配置    │  │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘  │  │
│  └──────────────────────────┬─────────────────────────────────────┘  │
│                              │ HTTP + WebSocket (localhost:port)       │
│  ┌──────────────────────────┴─────────────────────────────────────┐  │
│  │              Python FastAPI 后端（子进程）                        │  │
│  │                                                                │  │
│  │  ┌──────────────────────────────────────────────────────────┐  │  │
│  │  │  REST API 路由                                            │  │  │
│  │  │  /api/workflows    — 工作流 CRUD                          │  │  │
│  │  │  /api/candidates   — 候选人管理                            │  │  │
│  │  │  /api/skills       — Skill 管理与确认                      │  │  │
│  │  │  /api/agent        — Agent 启停、状态查询                   │  │  │
│  │  │  /api/settings     — 设置（含内网配置）                     │  │  │
│  │  │  /ws/agent-stream  — WebSocket 实时日志/状态推送            │  │  │
│  │  └──────────────────────────────────────────────────────────┘  │  │
│  │                                                                │  │
│  │  ┌──────────────────────────────────────────────────────────┐  │  │
│  │  │  Agent 引擎（后台 asyncio 任务）                           │  │  │
│  │  │  · Agent Loop (LLM 交互)                                  │  │  │
│  │  │  · 调度器 (状态机 + 队列)                                  │  │  │
│  │  │  · 工具调用层 (browser-mcp / subprocess)                   │  │  │
│  │  │  · 提示词管理 / 记忆管理 / Skill 管理                      │  │  │
│  │  │  · 数据同步适配层 (本地 ⟷ 内网)                            │  │  │
│  │  └──────────────────────────────────────────────────────────┘  │  │
│  │                                                                │  │
│  │  ┌──────────────────────────────────────────────────────────┐  │  │
│  │  │  系统访问层                                                │  │  │
│  │  │  subprocess → bash / git / curl / pip                     │  │  │
│  │  │  本地文件系统读写                                           │  │  │
│  │  │  SQLite / PostgreSQL                                      │  │  │
│  │  └──────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 启动流程

```
用户双击 RecruitAgent.app
    │
    ▼
Electron 主进程启动
    │
    ├── 1. 检查内嵌的 Python 环境是否就绪
    │
    ├── 2. 启动 FastAPI 后端子进程
    │       python -m recruit_agent.server --port {random_port}
    │       等待后端返回 "ready" 信号
    │
    ├── 3. 启动 browser-mcp 子进程（如需要）
    │
    ├── 4. 创建 BrowserWindow，加载前端页面
    │       前端通过 localhost:{port} 连接后端
    │
    └── 5. 前端加载完成，用户看到 Agent 主界面
```

```typescript
// Electron 主进程 main.ts
import { app, BrowserWindow } from 'electron';
import { spawn } from 'child_process';
import path from 'path';

let pythonProcess: ChildProcess | null = null;
let backendPort: number;

async function startPythonBackend(): Promise<number> {
  const port = await getRandomPort();
  const pythonPath = getPythonPath(); // 内嵌的 Python 或系统 Python
  
  pythonProcess = spawn(pythonPath, [
    '-m', 'recruit_agent.server',
    '--port', String(port),
    '--data-dir', app.getPath('userData'),
  ]);
  
  // 等待后端就绪
  await waitForReady(`http://localhost:${port}/health`);
  return port;
}

app.whenReady().then(async () => {
  backendPort = await startPythonBackend();
  
  const mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  
  // 开发模式加载 dev server，生产模式加载打包的静态文件
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
  } else {
    mainWindow.loadFile(path.join(__dirname, '../frontend/dist/index.html'));
  }
  
  // 通过 preload 将后端端口传给前端
  mainWindow.webContents.on('did-finish-load', () => {
    mainWindow.webContents.send('backend-port', backendPort);
  });
});

app.on('will-quit', () => {
  // 优雅关闭 Python 后端
  if (pythonProcess) {
    pythonProcess.kill('SIGTERM');
  }
});
```

### FastAPI 后端入口

```python
# recruit_agent/server.py
import asyncio
import uvicorn
from fastapi import FastAPI, WebSocket
from contextlib import asynccontextmanager

from .engine import AgentEngine
from .routes import workflows, candidates, skills, agent, settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化 Agent 引擎
    engine = AgentEngine(data_dir=app.state.data_dir)
    app.state.engine = engine
    await engine.initialize()
    
    yield
    
    # 关闭时优雅停机
    await engine.shutdown()

app = FastAPI(title="RecruitAgent", lifespan=lifespan)

# API 路由
app.include_router(workflows.router, prefix="/api/workflows")
app.include_router(candidates.router, prefix="/api/candidates")
app.include_router(skills.router, prefix="/api/skills")
app.include_router(agent.router, prefix="/api/agent")
app.include_router(settings.router, prefix="/api/settings")

@app.get("/health")
async def health():
    return {"status": "ready"}

@app.websocket("/ws/agent-stream")
async def agent_stream(websocket: WebSocket):
    """实时推送 Agent 执行日志和状态变更"""
    await websocket.accept()
    engine = app.state.engine
    
    async for event in engine.event_stream():
        await websocket.send_json(event)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8741)
    parser.add_argument("--data-dir", type=str, default="~/.recruit-agent")
    args = parser.parse_args()
    
    app.state.data_dir = args.data_dir
    uvicorn.run(app, host="127.0.0.1", port=args.port)
```

### 前端与后端的通信

```typescript
// 前端 TypeScript - API 客户端
class AgentAPIClient {
  private baseUrl: string;
  private ws: WebSocket | null = null;

  constructor(port: number) {
    this.baseUrl = `http://localhost:${port}`;
  }

  // REST API 调用
  async getWorkflows() {
    return fetch(`${this.baseUrl}/api/workflows`).then(r => r.json());
  }

  async startAgent(workflowId: string) {
    return fetch(`${this.baseUrl}/api/agent/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflow_id: workflowId }),
    }).then(r => r.json());
  }

  async confirmSkill(skillId: string, approved: boolean) {
    return fetch(`${this.baseUrl}/api/skills/${skillId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved }),
    }).then(r => r.json());
  }

  // WebSocket 实时流
  connectStream(onEvent: (event: AgentEvent) => void) {
    this.ws = new WebSocket(
      `ws://localhost:${this.baseUrl.split(':')[2]}/ws/agent-stream`
    );
    this.ws.onmessage = (msg) => {
      onEvent(JSON.parse(msg.data));
    };
  }
}
```

### 打包分发

```bash
# 1. 打包 Python 后端为独立可执行文件
pyinstaller --onedir --name recruit-agent-backend \
  recruit_agent/server.py

# 2. 打包前端
cd frontend && npm run build

# 3. 用 electron-builder 打包整个桌面应用
#    将 Python 后端可执行文件和前端静态文件打包进 .app
electron-builder --mac --config electron-builder.yml
```

```yaml
# electron-builder.yml
appId: com.yourcompany.recruit-agent
productName: RecruitAgent
mac:
  category: public.app-category.business
  target: dmg
  icon: assets/icon.icns
  
extraResources:
  # 内嵌 Python 后端
  - from: dist/recruit-agent-backend/
    to: backend/
    filter: ["**/*"]

files:
  - dist/electron/**/*
  - frontend/dist/**/*
```

### 也可以不打包 Electron——纯命令行 + 浏览器模式

如果不需要桌面应用壳，也可以直接运行 Python 后端，用浏览器打开：

```bash
# 启动 Agent 后端
python -m recruit_agent.server --port 8741

# 浏览器打开 http://localhost:8741
# 前端静态文件由 FastAPI 的 StaticFiles 直接 serve
```

这种模式适合开发调试，或者对桌面壳没有强需求的场景。功能完全一致，只是没有系统托盘、菜单、通知等原生体验。

---

## 6.2 LLM Provider 抽象层

Agent 系统同时支持 OpenAI 格式和 Anthropic 格式的 API，用户可以在设置中自由配置使用哪个 Provider，也可以混合使用（比如轻量任务用一个、重型任务用另一个）。

### 6.2.1 统一接口设计

无论底层是 OpenAI 还是 Anthropic，上层业务代码调用的始终是同一个 `llm_call` 接口：

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator
import httpx


@dataclass
class LLMMessage:
    role: str           # "system" | "user" | "assistant" | "tool"
    content: str | list # 文本或多模态内容块
    tool_call_id: str | None = None  # 工具调用结果的关联 ID


@dataclass
class ToolCall:
    id: str             # 工具调用 ID
    name: str           # 工具名称
    arguments: dict     # 工具参数


@dataclass
class LLMResponse:
    content: str | None              # 文本回复
    tool_calls: list[ToolCall]       # 工具调用列表
    usage: dict                      # {"input_tokens": ..., "output_tokens": ..., "total_tokens": ...}
    raw_response: dict               # 原始 API 返回，用于调试
    
    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class ToolDefinition:
    """统一的工具定义格式（内部表示）"""
    name: str
    description: str
    parameters: dict   # JSON Schema 格式


class LLMProvider(ABC):
    """LLM Provider 抽象基类"""
    
    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """发起一次 LLM 调用"""
        ...
    
    @abstractmethod
    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """流式调用（用于实时显示）"""
        ...
    
    @abstractmethod
    def get_available_models(self) -> list[dict]:
        """返回该 Provider 支持的模型列表"""
        ...
```

### 6.2.2 Anthropic Provider 实现

```python
class AnthropicProvider(LLMProvider):
    """Anthropic Claude API Provider"""
    
    MODELS = {
        "claude-opus-4":   {"tier": "reasoning", "context": 200000},
        "claude-sonnet-4": {"tier": "heavy",     "context": 200000},
        "claude-haiku-4":  {"tier": "light",     "context": 200000},
    }
    
    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com"):
        self.api_key = api_key
        self.base_url = base_url
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=120.0,
        )
    
    async def chat(self, messages, tools=None, model=None, 
                   temperature=0.7, max_tokens=4096) -> LLMResponse:
        model = model or "claude-sonnet-4-20250514"
        
        # 转换消息格式：分离 system 和对话消息
        system_prompt, api_messages = self._convert_messages(messages)
        
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": api_messages,
        }
        if system_prompt:
            body["system"] = system_prompt
        if tools:
            body["tools"] = self._convert_tools_to_anthropic(tools)
        
        resp = await self.client.post("/v1/messages", json=body)
        resp.raise_for_status()
        data = resp.json()
        
        return self._parse_response(data)
    
    def _convert_messages(self, messages: list[LLMMessage]):
        """将统一格式转换为 Anthropic 格式"""
        system_prompt = None
        api_messages = []
        
        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content if isinstance(msg.content, str) else str(msg.content)
            elif msg.role == "tool":
                # Anthropic 用 tool_result content block
                api_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }]
                })
            else:
                api_messages.append({
                    "role": msg.role,
                    "content": msg.content,
                })
        
        return system_prompt, api_messages
    
    def _convert_tools_to_anthropic(self, tools: list[ToolDefinition]) -> list:
        """转换工具定义为 Anthropic 格式"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]
    
    def _parse_response(self, data: dict) -> LLMResponse:
        """解析 Anthropic API 响应"""
        content_text = None
        tool_calls = []
        
        for block in data.get("content", []):
            if block["type"] == "text":
                content_text = (content_text or "") + block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append(ToolCall(
                    id=block["id"],
                    name=block["name"],
                    arguments=block["input"],
                ))
        
        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            usage={
                "input_tokens": data["usage"]["input_tokens"],
                "output_tokens": data["usage"]["output_tokens"],
                "total_tokens": data["usage"]["input_tokens"] + data["usage"]["output_tokens"],
            },
            raw_response=data,
        )
    
    def get_available_models(self) -> list[dict]:
        return [
            {"id": k, **v} for k, v in self.MODELS.items()
        ]
```

### 6.2.3 OpenAI 格式 Provider 实现

```python
class OpenAIProvider(LLMProvider):
    """
    OpenAI 格式 Provider
    支持 OpenAI 官方 API 以及所有兼容 OpenAI 格式的服务：
    - OpenAI (gpt-4o, gpt-4o-mini, o3, ...)
    - DeepSeek (deepseek-chat, deepseek-reasoner)
    - 其他兼容服务（通过自定义 base_url）
    """
    
    DEFAULT_MODELS = {
        "gpt-4o":       {"tier": "heavy",     "context": 128000},
        "gpt-4o-mini":  {"tier": "light",     "context": 128000},
        "o3":           {"tier": "reasoning", "context": 200000},
        "o4-mini":      {"tier": "heavy",     "context": 200000},
    }
    
    def __init__(self, api_key: str, 
                 base_url: str = "https://api.openai.com/v1",
                 models: dict | None = None):
        """
        api_key: API 密钥
        base_url: API 地址，默认 OpenAI 官方。
                  DeepSeek: https://api.deepseek.com/v1
                  自定义服务: http://your-server/v1
        models: 自定义模型列表（覆盖默认）
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.models = models or self.DEFAULT_MODELS
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )
    
    async def chat(self, messages, tools=None, model=None,
                   temperature=0.7, max_tokens=4096) -> LLMResponse:
        model = model or "gpt-4o"
        
        body = {
            "model": model,
            "messages": self._convert_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = self._convert_tools_to_openai(tools)
        
        resp = await self.client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        
        return self._parse_response(data)
    
    def _convert_messages(self, messages: list[LLMMessage]) -> list:
        """将统一格式转换为 OpenAI 格式"""
        api_messages = []
        for msg in messages:
            if msg.role == "tool":
                api_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
            else:
                api_messages.append({
                    "role": msg.role,
                    "content": msg.content,
                })
        return api_messages
    
    def _convert_tools_to_openai(self, tools: list[ToolDefinition]) -> list:
        """转换工具定义为 OpenAI function calling 格式"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            }
            for tool in tools
        ]
    
    def _parse_response(self, data: dict) -> LLMResponse:
        """解析 OpenAI 格式响应"""
        choice = data["choices"][0]
        message = choice["message"]
        
        tool_calls = []
        if message.get("tool_calls"):
            import json
            for tc in message["tool_calls"]:
                tool_calls.append(ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=json.loads(tc["function"]["arguments"]),
                ))
        
        usage = data.get("usage", {})
        
        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            raw_response=data,
        )
    
    def get_available_models(self) -> list[dict]:
        return [{"id": k, **v} for k, v in self.models.items()]
```

### 6.2.4 LLM 管理器（多 Provider + 模型路由）

上层业务代码通过 `LLMManager` 调用，不直接接触 Provider：

```python
class LLMManager:
    """
    LLM 统一管理器
    - 管理多个 Provider（Anthropic / OpenAI / DeepSeek / ...）
    - 根据任务类型自动路由到合适的模型
    - 处理重试、fallback、成本统计
    """
    
    def __init__(self, config: dict):
        self.providers: dict[str, LLMProvider] = {}
        self.model_routing: dict[str, dict] = {}
        self.usage_tracker = UsageTracker()
        
        self._init_providers(config)
        self._init_routing(config)
    
    def _init_providers(self, config: dict):
        """根据配置初始化 Provider"""
        for name, provider_config in config.get("providers", {}).items():
            api_type = provider_config["type"]  # "anthropic" | "openai"
            
            if api_type == "anthropic":
                self.providers[name] = AnthropicProvider(
                    api_key=provider_config["api_key"],
                    base_url=provider_config.get("base_url", "https://api.anthropic.com"),
                )
            elif api_type == "openai":
                self.providers[name] = OpenAIProvider(
                    api_key=provider_config["api_key"],
                    base_url=provider_config.get("base_url", "https://api.openai.com/v1"),
                    models=provider_config.get("models"),
                )
    
    def _init_routing(self, config: dict):
        """初始化模型路由规则"""
        self.model_routing = config.get("model_routing", {
            "light": {"provider": "anthropic", "model": "claude-haiku-4"},
            "heavy": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
            "reasoning": {"provider": "anthropic", "model": "claude-opus-4"},
        })
    
    async def call(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        tier: str = "heavy",           # "light" | "heavy" | "reasoning"
        task_id: str | None = None,    # 用于成本追踪
        **kwargs,
    ) -> LLMResponse:
        """
        统一调用入口
        根据 tier 自动路由到对应的 Provider + Model
        """
        route = self.model_routing[tier]
        provider_name = route["provider"]
        model = route["model"]
        provider = self.providers[provider_name]
        
        try:
            response = await provider.chat(
                messages=messages,
                tools=tools,
                model=model,
                **kwargs,
            )
            
            # 记录用量
            self.usage_tracker.record(
                provider=provider_name,
                model=model,
                tier=tier,
                task_id=task_id,
                usage=response.usage,
            )
            
            return response
        
        except Exception as e:
            # 尝试 fallback
            fallback = route.get("fallback")
            if fallback:
                fb_provider = self.providers[fallback["provider"]]
                return await fb_provider.chat(
                    messages=messages, tools=tools,
                    model=fallback["model"], **kwargs,
                )
            raise
    
    # === 便捷方法，供业务代码使用 ===
    
    async def call_light(self, messages, tools=None, **kwargs) -> LLMResponse:
        """轻量调用：页面判断、简单提取等"""
        return await self.call(messages, tools, tier="light", **kwargs)
    
    async def call_heavy(self, messages, tools=None, **kwargs) -> LLMResponse:
        """标准调用：评分、沟通、Skill 学习等"""
        return await self.call(messages, tools, tier="heavy", **kwargs)
    
    async def call_reasoning(self, messages, tools=None, **kwargs) -> LLMResponse:
        """强推理调用：异常诊断、工作流优化等"""
        return await self.call(messages, tools, tier="reasoning", **kwargs)


class UsageTracker:
    """用量追踪和成本统计"""
    
    def record(self, provider, model, tier, task_id, usage):
        # 存入数据库，用于成本看板
        ...
    
    def get_daily_usage(self) -> dict:
        ...
    
    def get_task_usage(self, task_id: str) -> dict:
        ...
```

### 6.2.5 用户配置

用户在 Agent 设置页面中配置 LLM Provider：

```yaml
# ~/.recruit-agent/config.yaml

llm:
  providers:
    # Anthropic（Claude 系列）
    anthropic:
      type: anthropic
      api_key: "sk-ant-xxx"
      base_url: "https://api.anthropic.com"      # 可选，默认官方地址
    
    # OpenAI（GPT 系列）
    openai:
      type: openai
      api_key: "sk-xxx"
      base_url: "https://api.openai.com/v1"      # 可选，默认官方地址
    
    # DeepSeek（兼容 OpenAI 格式）
    deepseek:
      type: openai                                 # 用 openai 类型，换 base_url
      api_key: "sk-xxx"
      base_url: "https://api.deepseek.com/v1"
      models:                                      # 自定义模型列表
        deepseek-chat:
          tier: heavy
          context: 128000
        deepseek-reasoner:
          tier: reasoning
          context: 128000
    
    # 自部署的兼容服务（如 vLLM、Ollama 等）
    local:
      type: openai
      api_key: "not-needed"
      base_url: "http://localhost:11434/v1"        # Ollama 示例
      models:
        qwen2.5:72b:
          tier: heavy
          context: 32000

  # 模型路由：哪个任务层级用哪个 Provider + Model
  model_routing:
    light:
      provider: anthropic
      model: claude-haiku-4
      fallback:                                    # 主 Provider 不可用时的备选
        provider: openai
        model: gpt-4o-mini
    
    heavy:
      provider: anthropic
      model: claude-sonnet-4-20250514
      fallback:
        provider: openai
        model: gpt-4o
    
    reasoning:
      provider: anthropic
      model: claude-opus-4
      fallback:
        provider: deepseek
        model: deepseek-reasoner
  
  # 全局限制
  rate_limits:
    max_calls_per_minute: 30
    max_daily_tokens: 500000
    alert_threshold: 0.8
```

### 6.2.6 Agent Loop 中的使用

之前方案中所有的 `llm_call` 现在统一走 `LLMManager`：

```python
class AgentEngine:
    def __init__(self, config):
        self.llm = LLMManager(config["llm"])
        # ...
    
    async def agent_loop(self, task, candidate_session, skill, tools):
        messages = build_context(task, candidate_session, skill)
        
        while turn < max_turns:
            # 根据任务类型选择合适的模型层级
            tier = self._get_tier_for_task(task.node_type)
            
            response = await self.llm.call(
                messages=messages,
                tools=tools,
                tier=tier,
                task_id=task.id,
            )
            # ... 后续处理逻辑不变
    
    def _get_tier_for_task(self, node_type: str) -> str:
        """根据任务节点类型决定模型层级"""
        TIER_MAP = {
            # 轻量任务
            "page_check": "light",
            "extract_info": "light",
            
            # 标准任务
            "discover_candidates": "heavy",
            "initial_screening": "heavy",
            "communication": "heavy",
            "candidate_scoring": "heavy",
            "skill_learning": "heavy",
            "context_compression": "heavy",
            
            # 强推理任务
            "workflow_optimization": "reasoning",
            "failure_diagnosis": "reasoning",
            "workflow_generation": "reasoning",
        }
        return TIER_MAP.get(node_type, "heavy")
```

### 6.2.7 前端设置页面

```typescript
// 前端 TypeScript - LLM 配置组件的数据结构

interface LLMProviderConfig {
  name: string;
  type: 'anthropic' | 'openai';
  apiKey: string;
  baseUrl: string;
  models?: Record<string, { tier: string; context: number }>;
}

interface ModelRouting {
  light:     { provider: string; model: string; fallback?: { provider: string; model: string } };
  heavy:     { provider: string; model: string; fallback?: { provider: string; model: string } };
  reasoning: { provider: string; model: string; fallback?: { provider: string; model: string } };
}

// 设置页面允许用户：
// 1. 添加/删除 Provider（填 API Key + Base URL）
// 2. 点击 "测试连接" 验证 Provider 可用性
// 3. 配置模型路由（哪个层级用哪个 Provider 的哪个模型）
// 4. 查看用量统计（按 Provider、按模型、按天的 token 消耗）
```

---

## 6.3 系统命令扩展能力

Agent 在执行任务过程中，可能遇到需要通过 bash 命令、git、curl、pip 等系统工具来解决的问题。这不是预编程的，而是 Agent 在执行中**自主判断需要、自主使用、自主固化**的能力。

### 6.3.1 系统命令作为工具

将系统命令执行注册为 Agent 可调用的工具：

```python
import subprocess
import shlex
import os

class SystemCommandTool:
    """
    Agent 可调用的系统命令执行工具
    带安全白名单和沙箱约束
    """
    
    # 允许 Agent 使用的命令白名单
    ALLOWED_COMMANDS = {
        # 信息获取类
        "curl": "发起 HTTP 请求获取外部信息",
        "wget": "下载文件",
        "git": "版本控制操作",
        "cat": "查看文件内容",
        "ls": "列出目录内容",
        "find": "搜索文件",
        "grep": "文本搜索",
        "head": "查看文件头部",
        "tail": "查看文件尾部",
        "wc": "统计文件行数/字数",
        
        # 包管理类
        "pip": "安装/管理 Python 包",
        "pip3": "安装/管理 Python 包",
        
        # 数据处理类
        "jq": "JSON 数据处理",
        "sed": "文本流编辑",
        "awk": "文本处理",
        "sort": "排序",
        "uniq": "去重",
        
        # 系统信息类
        "which": "查找命令路径",
        "whoami": "当前用户",
        "date": "当前日期时间",
        "uname": "系统信息",
    }
    
    # 绝对禁止的命令
    BLOCKED_COMMANDS = {
        "rm", "rmdir",         # 删除
        "sudo", "su",          # 提权
        "chmod", "chown",      # 权限修改
        "kill", "killall",     # 进程终止
        "shutdown", "reboot",  # 系统操作
        "dd", "mkfs",          # 磁盘操作
        "eval", "exec",        # 代码执行
    }
    
    # 工作目录约束
    ALLOWED_WORK_DIRS = [
        os.path.expanduser("~/.recruit-agent/"),  # Agent 工作目录
        "/tmp/recruit-agent/",                      # 临时目录
    ]
    
    def execute(self, command: str, timeout: int = 30) -> dict:
        """
        执行系统命令
        """
        # 解析命令
        parts = shlex.split(command)
        cmd_name = parts[0]
        
        # 安全校验
        if cmd_name in self.BLOCKED_COMMANDS:
            return {"success": False, "error": f"命令 {cmd_name} 被禁止使用"}
        
        if cmd_name not in self.ALLOWED_COMMANDS:
            return {
                "success": False, 
                "error": f"命令 {cmd_name} 不在白名单中。"
                         f"可用命令：{list(self.ALLOWED_COMMANDS.keys())}"
            }
        
        # pip 特殊处理：只允许安装到 Agent 的虚拟环境
        if cmd_name in ("pip", "pip3"):
            if "install" in parts:
                # 强制加上 --target 参数，安装到 Agent 目录
                if "--target" not in command:
                    parts.extend(["--target", 
                                  os.path.expanduser("~/.recruit-agent/packages/")])
        
        try:
            result = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.ALLOWED_WORK_DIRS[0],
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout[:10000],  # 限制输出长度
                "stderr": result.stderr[:5000],
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"命令执行超时（{timeout}秒）"}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

将其注册为 LLM 可调用的工具：

```python
system_command_tool_definition = {
    "name": "execute_system_command",
    "description": """
    在本地系统上执行 bash 命令。用于：
    - 用 curl 获取外部 API 数据或网页信息
    - 用 git 管理代码和配置
    - 用 pip 安装需要的 Python 包
    - 用 jq/grep/awk 处理数据
    - 获取系统信息
    
    注意：
    - 只能使用白名单中的命令
    - 不能执行删除、提权、系统修改操作
    - 命令执行有 30 秒超时限制
    - pip install 会安装到 Agent 专用目录
    """,
    "parameters": {
        "command": {
            "type": "string",
            "description": "要执行的完整命令，如 'curl -s https://api.example.com/data'"
        },
        "timeout": {
            "type": "integer",
            "description": "超时时间（秒），默认30，最大120",
            "default": 30
        }
    }
}
```

### 6.3.2 自动安装扩展工具包

Agent 在执行任务过程中发现需要某个 Python 包或系统工具时，能自主安装：

```python
class ToolExtensionManager:
    """
    管理 Agent 的工具扩展能力
    Agent 可以自主发现、安装、使用新的工具包
    """
    
    # Agent 专用的包安装目录
    PACKAGES_DIR = os.path.expanduser("~/.recruit-agent/packages/")
    
    # 已安装的扩展包记录
    EXTENSIONS_REGISTRY = os.path.expanduser("~/.recruit-agent/extensions.json")
    
    # 允许安装的包白名单（或前缀白名单）
    ALLOWED_PACKAGES = {
        # 数据处理
        "pandas", "openpyxl", "xlsxwriter",
        # 文档解析
        "pdfplumber", "python-docx", "pymupdf",
        # 网络请求
        "httpx", "aiohttp",
        # 数据格式
        "pyyaml", "toml",
        # 文本处理
        "chardet", "python-magic",
        # 图像处理
        "pillow",
    }
    
    def check_and_install(self, package_name: str) -> dict:
        """
        检查包是否已安装，未安装则自动安装
        """
        if package_name not in self.ALLOWED_PACKAGES:
            return {
                "success": False,
                "error": f"包 {package_name} 不在允许安装的列表中。"
                         f"如需使用，请联系管理员将其加入白名单。"
            }
        
        # 检查是否已安装
        try:
            __import__(package_name)
            return {"success": True, "status": "already_installed"}
        except ImportError:
            pass
        
        # 安装到 Agent 专用目录
        result = subprocess.run(
            ["pip3", "install", package_name, 
             "--target", self.PACKAGES_DIR,
             "--quiet"],
            capture_output=True, text=True, timeout=120,
        )
        
        if result.returncode == 0:
            # 将目录加入 Python 路径
            if self.PACKAGES_DIR not in sys.path:
                sys.path.insert(0, self.PACKAGES_DIR)
            
            # 记录安装信息
            self._record_extension(package_name)
            
            return {"success": True, "status": "newly_installed"}
        else:
            return {"success": False, "error": result.stderr}
    
    def _record_extension(self, package_name):
        """记录扩展包安装历史"""
        registry = self._load_registry()
        registry[package_name] = {
            "installed_at": datetime.now().isoformat(),
            "installed_by": "agent_auto",
            "version": self._get_installed_version(package_name),
        }
        self._save_registry(registry)
```

### 6.3.3 系统命令能力自动落地为 Skill

当 Agent 通过系统命令解决了某个问题后，这个能力也要固化为 Skill：

```python
def post_command_skill_extraction(task, commands_executed, results):
    """
    Agent 通过系统命令完成了任务后，
    分析是否可以将这组命令固化为 Skill 的一部分
    """
    
    extraction_prompt = f"""
    在执行任务「{task.name}」的过程中，你使用了以下系统命令：
    
    {format_command_history(commands_executed, results)}
    
    请分析：
    1. 这些命令是否构成了一个可复用的操作模式？
    2. 如果是，请将其总结为 Skill 的一个执行步骤，包含：
       - 目的：为什么需要执行这些命令
       - 命令序列：具体的命令（参数化，用变量替代硬编码值）
       - 前置条件：需要哪些工具/包已安装
       - 预期结果：命令执行成功应该看到什么
       - 异常处理：命令失败时怎么办
    3. 是否需要安装额外的工具包来支持这个能力？
    
    输出 JSON 格式。如果不构成可复用模式，输出 {{"reusable": false}}
    """
    
    analysis = llm_call(extraction_prompt)
    
    if analysis.get("reusable"):
        # 合并到对应的 Skill 中
        skill = find_skill_for_task(task)
        if skill:
            skill.strategy["steps"].append({
                "type": "system_command",
                "purpose": analysis["purpose"],
                "commands": analysis["command_sequence"],
                "prerequisites": analysis["prerequisites"],
                "expected_result": analysis["expected_result"],
                "error_handling": analysis["error_handling"],
            })
            skill.status = "pending_review"
            skill.save()
            notify_user_for_review(skill, "Skill 新增了系统命令步骤，请确认")
```

### 6.3.4 典型场景示例

**场景一：Agent 需要解析一个非标准格式的简历**

```
Agent 执行「候选人评分」→ 收到候选人的简历是 .docx 格式
→ Agent 发现没有安装 python-docx
→ 调用 ToolExtensionManager.check_and_install("python-docx")
→ 自动安装到 Agent 目录
→ 用 python-docx 提取简历文本
→ 完成评分
→ 将 "使用 python-docx 解析 .docx 简历" 固化为评分 Skill 的一个步骤
```

**场景二：Agent 需要获取某个 JD 的外部市场薪资数据**

```
Agent 执行「候选人评分」→ JD 要求参考市场薪资水平
→ Agent 调用 execute_system_command("curl -s 'https://api.salary.com/...'")
→ 获取市场薪资数据
→ 调用 execute_system_command("echo '...' | jq '.data.median'") 处理 JSON
→ 将薪资数据纳入评分参考
→ 将 "通过 API 获取市场薪资数据" 固化为评分 Skill 的一个前置步骤
```

**场景三：Agent 需要将候选人简历转换为标准格式存储**

```
Agent 执行「入库汇总」→ 候选人简历是 PDF 格式，需要提取文本
→ 调用 ToolExtensionManager.check_and_install("pdfplumber")
→ 安装成功
→ 提取 PDF 文本
→ 如果 pdfplumber 失败（扫描件 PDF），自动尝试安装 pymupdf + pytesseract
→ 用 OCR 提取文本
→ 将完整的 PDF 处理流程固化为 Skill
```

### 6.3.5 安全约束

系统命令扩展能力必须有严格的安全边界：

```yaml
system_command_security:
  # 命令白名单（只有这些命令可以执行）
  allowed_commands:
    - curl      # 网络请求
    - wget      # 下载文件
    - git       # 版本控制
    - pip/pip3  # 包管理（仅限 Agent 目录）
    - jq        # JSON 处理
    - grep/sed/awk  # 文本处理
    - cat/head/tail  # 文件查看
    - ls/find   # 目录浏览
    - which     # 命令查找
    
  # 绝对禁止（即使在白名单扩展请求中也不允许）
  permanently_blocked:
    - rm/rmdir  # 删除
    - sudo/su   # 提权
    - chmod/chown  # 权限
    - kill      # 进程
    - eval/exec # 代码执行
    - dd/mkfs   # 磁盘
  
  # 工作目录限制
  allowed_directories:
    - ~/.recruit-agent/     # Agent 自己的工作目录
    - /tmp/recruit-agent/   # 临时文件
  
  # 包安装限制
  pip_constraints:
    target_dir: ~/.recruit-agent/packages/  # 不污染系统环境
    allowed_packages: [...]  # 白名单
    max_package_size_mb: 100
    
  # 网络限制
  network_constraints:
    allowed_domains: ["*"]      # curl/wget 允许访问的域名
    blocked_domains: ["localhost", "127.0.0.1", "internal.*"]
    max_download_size_mb: 50
  
  # 执行限制
  execution_constraints:
    timeout_seconds: 30        # 单命令超时
    max_commands_per_task: 20  # 单任务最多执行20条命令
    max_output_length: 10000  # 输出截断长度
    
  # 白名单扩展需要人工确认
  whitelist_extension_requires_review: true
```

### Phase 1：最小可用（2-3周）

目标：Agent 能跑通一个完整的"发现 → 初筛"流程

- [ ] Agent Loop 核心实现（LLM 调用 + 工具调用循环 + 重试）
- [ ] 提示词管理基础（基础层 + 2个任务层模板）
- [ ] Browser-MCP 工具接入（navigate / get_content / click）
- [ ] 候选人数据库基础表
- [ ] 单个 Skill 手动创建和加载
- [ ] 单任务执行，命令行触发

### Phase 2：沟通与评分（2-3周）

目标：Agent 能完成沟通、索要简历、AI 评分全流程

- [ ] 候选人会话管理（挂起/恢复/压缩）
- [ ] 沟通工具接入（browser_type / 消息发送）
- [ ] 候选人评分工具（结构化输出）
- [ ] 冷却期管理
- [ ] 记忆体系基础（短期记忆 + 上下文压缩）

### Phase 3：调度与自动化（2-3周）

目标：总控调度器运行，多候选人串行处理

- [ ] 任务队列实现（Redis）
- [ ] 总控调度器（优先级调度 + 串行控制）
- [ ] 工作流引擎（DAG 解析 + 节点执行 + 条件分支）
- [ ] 定时任务（超时清理、健康检查）
- [ ] 异常告警基础

### Phase 4：Skill 学习闭环（2-3周）

目标：Agent 能自主学习新 Skill，经人工确认后使用

- [ ] Skill 生命周期管理（draft → pending_review → active）
- [ ] Skill 产出流程（Agent 输出执行方案）
- [ ] Skill 确认界面（内网工作台）
- [ ] Skill 自检机制
- [ ] Skill 自动更新（选择器级）

### Phase 5：桌面应用（3-4周）

目标：打包为可分发的 macOS 桌面应用

- [ ] Electron 主进程框架（启动 Python 后端子进程、窗口管理）
- [ ] FastAPI 后端 API 路由（workflows / candidates / skills / agent / settings）
- [ ] WebSocket 实时日志推送
- [ ] React + TypeScript 前端框架搭建
- [ ] 工作流配置界面
- [ ] Skill 管理与确认界面
- [ ] 候选人管理和状态查看
- [ ] Agent 实时监控和日志面板
- [ ] 数据看板（效率/质量/成本指标）
- [ ] 设置页面（内网连接配置、LLM API 配置）
- [ ] electron-builder + PyInstaller 打包

### Phase 6：系统命令扩展与进化（2-3周）

- [ ] SystemCommandTool 实现（白名单 + 安全约束）
- [ ] ToolExtensionManager 实现（自动安装 Python 包）
- [ ] 系统命令能力自动落地为 Skill
- [ ] 白名单扩展的人工确认流程

### Phase 7：持续进化与优化（持续）

- [ ] 长期经验记忆积累和整理
- [ ] HR 反馈回流机制
- [ ] 模型分级策略优化
- [ ] 多平台适配（新增猎聘/拉勾等）
- [ ] 评分标准自动校准
- [ ] 工作流 LLM 辅助编排
- [ ] Skill 跨平台迁移学习

---

## 八、风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|---------|
| 招聘平台封号/限制 | 系统无法运行 | 严格频率限制；模拟人类操作节奏；多账号轮换；异常立即暂停 |
| LLM 评分偏差 | 误筛优质候选人 | HR 反馈回流；定期校准评分标准；保留决策审计日志供复查 |
| 页面结构变更 | Skill 失效 | Skill 自检机制；策略层与选择器层分离；LLM 实时适配 |
| LLM API 不可用 | 系统暂停 | 重试+退避策略；备选 LLM 提供商；优雅暂停 |
| 候选人隐私数据泄露 | 合规风险 | 数据加密存储；日志脱敏；评估 LLM API 的数据隐私政策 |
| Token 消耗失控 | 成本超支 | 单任务预算限制；模型分级；Skill 复用降低消耗；每日预算上限 |
| 沟通质量不佳 | 影响公司形象 | 沟通话术模板人工审核；禁止词/禁止承诺清单；初期人工抽查 |
