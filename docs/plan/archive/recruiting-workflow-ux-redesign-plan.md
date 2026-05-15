# Recruiting Workflow UX Redesign Plan

> Status: archived
> Supersedes: -
> Superseded by: current long-term specs under docs/specs/ and archived implementation plans.
> Distilled into: historical UX context only; current constraints live under docs/specs/
> Last reviewed against code: 2026-04-20
> Legacy path retained: docs/recruiting-workflow-ux-redesign-plan.md

> This document is a product and UX plan for the current RecruitStation codebase.
> It is not asking the team to remove the runtime core. The goal is to **hide implementation language behind recruiter-friendly workflows** and make the product feel like a recruiting workspace instead of an agent operations console.

## Why this document exists

The repository already contains strong building blocks for a recruiting product:

- candidate-scoped records and isolated memory
- JD-scoped memory
- structured assessments, scorecards, review decisions, and stage events
- runtime checkpoints, approvals, and operator interactions
- MCP-driven real environment access for Boss-style sourcing flows

However, the current desktop product still feels awkward to use because the UI surface is closer to the **internal runtime model** than to the **actual recruiting workflow**.

The result is a product that is powerful, but cognitively expensive:

- users think in terms of *candidates, jobs, queues, follow-ups, and hiring decisions*
- the product still exposes *goals, traces, graphs, runs, evolution artifacts, compact actions, and MCP health*

That mismatch is the main UX problem.

## Current truth

### What already works well

1. **The data model is stronger than the product surface.**
   The backend already models candidate lifecycle data in a useful way: `Candidate`, `CandidateStageEvent`, `CandidateAssessment`, `ResumeArtifact`, `CandidateScorecard`, `CandidateReviewDecision`, `TalentPoolSyncRecord`.
2. **Candidate isolation is a real product advantage.**
   Candidate memory, candidate thread, and candidate state are already separated cleanly.
3. **The system already has a real sourcing -> evaluation -> follow-up backbone.**
   Boss is no longer a hardcoded adapter, but the runtime can still use Browser MCP and real tools for sourcing and inspection.
4. **Human checkpoints exist.**
   This is good for recruiting, because communication, rejection, and progression often need human review.

### What feels wrong today

1. **Implementation concepts leak into the default UI.**
   Terms like `goal`, `trace`, `graph`, `artifact`, `compact`, `operator interaction`, `adaptive runtime`, and `MCP health` appear too early.
2. **The workflow is split across too many top-level pages.**
   Candidate work is currently scattered across `Dashboard`, `Workbench`, `Communications`, `Agent IM`, `Evolution`, and `RecruitStation`.
3. **The product starts from configuration and runtime control, not from recruiter work queues.**
   A recruiter should start from “what needs my attention now?”, not “run agent once” or “start adaptive goal”.
4. **The communication page mixes too many jobs.**
   Chat, state transition, assessment entry, resume facts, sync facts, and approvals are all placed in one screen.
5. **The stage model is too detailed for daily operation.**
   Backend micro-stages are useful internally, but the UI should present simpler macro-stages.
6. **The visual language still feels like a dark technical console.**
   It does not match the intended recruiter-facing, Boss-style operating experience.

## Evidence from the current implementation

The following files show why the product feels runtime-first instead of recruiter-first:

- `apps/desktop/src/features/workspace/DesktopWorkspace.tsx` loads almost every domain object at startup and exposes them as top-level tabs.
- `apps/desktop/src/features/workbench/WorkbenchView.tsx` mixes candidate progress with `run once`, `goal`, `replay`, `diagnostics`, `adaptive runtime`, queue depth, and sync backlog.
- `apps/desktop/src/features/communications/CommunicationsView.tsx` mixes chat, state transition, assessments, structured facts, and runtime confirmations.
- `apps/desktop/src/features/recruit-station/RecruitStationView.tsx` exposes blueprint, context policy, memory policy, and raw editing surfaces too prominently.
- `services/backend/src/recruit_station/api/routers/recruit_station.py` already contains strong recruiting CRUD endpoints, but they live next to runtime and governance endpoints in the same product surface.
- `apps/desktop/src/styles.css` and `apps/desktop/src/lib/theme.ts` still reflect a dark console visual system, which conflicts with the new desktop design guidelines.

## Product north star

The product should feel like this:

**A recruiter-facing operating workspace that helps the user move candidates from sourcing to decision with AI assistance, human checkpoints, and strong structured records.**

The product should not feel like this:

- a general agent lab
- a runtime debugger
- a workflow compiler UI
- a governance console that happens to contain candidates

## Proposed information architecture

Keep the current top-level names. Do **not** change product naming unless there is a separate naming decision.

The redesign should focus on:

- changing page responsibility
- changing information density and default entry points
- changing what is primary vs advanced
- adding missing business surfaces where necessary

### Keep existing top-level names, but redefine responsibilities

| Current surface | Recommended responsibility after redesign | Why |
|---|---|---|
| Dashboard | Today-facing actionable overview | Start from today’s actionable queues, not abstract metrics |
| Workbench | Main candidate pipeline workspace | Make the primary unit of work a candidate queue, not runtime operations |
| Communications | Candidate cockpit for thread-based work | Keep communication, resume, evaluation, and next actions in one recruiter flow |
| RecruitStation | Advanced agent configuration and strategy | Move blueprint/context/memory editing out of the default daily workflow |
| Agent IM + Evolution | Advanced review and governance area | Merge non-candidate approvals, skill issues, and evolution artifacts into one advanced governance layer |
| Settings | Operational/admin settings | Keep as operational and system configuration |
| — | Import Center (new page or nested module) | Add an explicit Boss/import intake surface |
| — | JD Workspace (new page or nested module) | Add a role/JD-centered view for hiring demand and calibration |

### Navigation principle

Keep existing product names if they are already chosen. The redesign should not require renaming top-level tabs.

Instead:

- `Dashboard` should behave like a Today view
- `Workbench` should behave like the main candidate pipeline
- `Communications` should behave like a candidate cockpit
- `RecruitStation` should be treated as advanced configuration
- `Agent IM` and `Evolution` should be visually and behaviorally pushed into advanced governance work

`runtime diagnostics`, `MCP registry`, `trace/graph`, and `memory editing` should be nested under advanced areas, not shown as core daily surfaces.

## Proposed end-to-end recruiting workflow

The user journey should be redesigned around the real hiring loop.

### Step 1. Source or import candidates

**User experience:**

- Open `Import Center`
- Choose `Capture current Boss page`, `Import selected candidates`, or `Import resume files`
- Review a staging list before records are committed

**System responsibility:**

- normalize raw source data
- deduplicate candidates
- detect missing fields
- create import batches and import errors
- write or update `Candidate`

### Step 2. AI triage and scoring

**User experience:**

- New candidates land in `Needs review`
- Each candidate card shows:
  - AI fit score
  - top positive signals
  - top risks
  - missing information
  - recommended next action
- The user can bulk accept, bulk reject, or move to outreach

**System responsibility:**

- create assessment
- generate scorecard and decision support
- expose confidence and evidence
- avoid forcing the user to open raw diagnostics

### Step 3. Outreach and resume collection

**User experience:**

- Candidate moves into `Needs outreach` or `Waiting for resume`
- The product offers channel-aware message drafts and variables
- Sending a first message or sensitive message can still require review

**System responsibility:**

- generate draft copy
- warn about missing contact channels
- store communication history
- update candidate state automatically after send/request/reply

### Step 4. Candidate cockpit review

**User experience:**

Each candidate gets one cockpit page with three stable zones:

- left: queue and candidate switching
- center: conversation / timeline / latest actions
- right: candidate dossier, resume, score summary, and next step recommendations

This replaces the current pattern where the user jumps between workbench, communications, approvals, and evaluation details.

### Step 5. Interview and decision handling

**User experience:**

- Macro-stage progression is simple: `New`, `Review`, `Outreach`, `Resume`, `Interview`, `Decision`, `Archived`
- Internal stage details are still available, but secondary
- Reviewers can record structured notes and explicit decisions

**System responsibility:**

- map backend micro-stages to macro-stages
- preserve stage events and structured facts
- keep AI and human decisions visible in the same narrative surface

### Step 6. Sync, talent pool, and archive

**User experience:**

- Export and sync should appear as delivery status, not as infrastructure backlog
- The user should see “sent”, “failed”, “retrying”, and “destination” in business language

**System responsibility:**

- separate business sync records from infrastructure retry queues
- only show technical backlog in advanced views

## Page redesign recommendations

### 1. Dashboard

This should become the daily command surface.

Show only:

- candidates needing review
- messages needing reply
- resumes newly received
- interview actions due today
- blocked items
- sync failures that impact business outcomes

Do not show:

- raw traces
n- graphs
- adaptive goal creation
- replay diagnostics
- MCP health by default

### 2. Workbench

This should replace the current `Workbench` as the main work surface.

Core layout:

- top: filters by JD, source, stage, owner, score band
- center: candidate list with dense cards or table rows
- right drawer: quick preview and next actions
- batch actions: `Score`, `Move to outreach`, `Request resume`, `Reject`, `Assign`

Key principle:

**The default workflow should be queue-first and batch-friendly.**

### 3. Communications

This should absorb most of today’s `Communications` page, but in a clearer structure.

Three-pane layout:

- left: candidate list / queue
- center: communication and activity timeline
- right: candidate dossier

The right-side dossier should include:

- summary
- source and JD
- contact state
- latest resume
- AI fit summary
- human review summary
- next recommended actions

State transition and manual assessment should move into structured action modules instead of long free-form panels.

### 4. Import Center

This is currently missing as a first-class business surface.

It should cover:

- Boss page capture
- import batches
- dedupe review
- parse failures
- incomplete profiles
- missing contact or resume data

This page makes the sourcing-to-database flow explicit for operators.

### 5. JD Workspace

The system is candidate-heavy today, but recruiters also work role-first.

Each JD page should show:

- hiring target and progress
- candidate funnel for this JD
- calibration notes
- strong/weak signals learned for this JD
- recommended sourcing gaps

This is the right place to expose JD memory in business language.

### 6. Agent IM + Evolution (advanced area)

Merge today’s `Agent IM` and `Evolution` into one advanced governance surface.

Keep here:

- non-candidate approvals
- skill degradation
- prompt/playbook/memory policy patches
- MCP or provider issues
- diagnostics and runtime health

Remove these from the default recruiter flow.

### 7. RecruitStation (advanced area)

Today’s `RecruitStation` page should be reframed as an advanced admin surface.

Keep here:

- agent profile
- playbook editing
- context policy
- memory policy
- skill registry

Default users should rarely need to visit this page.

## Terminology guidance

Use business language first, implementation language second.

This guidance is about **descriptions, helper copy, panel titles, empty states, CTA text, and explanatory text**, not about forcibly renaming already-chosen product page names.

| Current term | Better default explanatory wording |
|---|---|
| Goal | Task / Automation request |
| Run / Episode | AI activity / Processing record |
| Trace | Execution notes |
| Graph projection | Reasoning path |
| Evolution artifact | AI change proposal |
| Operator interaction | Review request |
| Compact memory | Refresh AI summary |
| Talent pool sync record | Export status |
| Workbench | candidate pipeline workspace |
| Communications | candidate cockpit / thread workspace |
| RecruitStation | advanced agent strategy/configuration area |
| Agent IM | advanced review center / operator review area |

## Backend and API alignment recommendations

The backend model is already strong, but the UI needs better aggregation and business framing.

### Recommended API changes

1. Add a **candidate cockpit aggregate endpoint**.
   Instead of the frontend loading thread, assessments, scorecards, review decisions, assignments, resume artifacts, and sync records indirectly, provide one recruiter-facing aggregate payload.
2. Add a **home summary endpoint built around queues**.
   It should return `needs_review`, `needs_reply`, `needs_resume`, `needs_schedule`, `blocked`, and `export_failures`.
3. Add an **import batch model and import queue endpoints**.
   The sourcing step needs first-class visibility.
4. Add **macro-stage mapping** in the API.
   Keep backend micro-stages, but expose a simpler macro-stage for the UI.
5. Add a **next_action** or **action queue** summary per candidate.
   The UI should not derive actionability from many low-level fields each time.
6. Separate **business sync status** from **technical retry backlog** in the default UI payloads.

### Recommended frontend data-loading changes

1. Stop loading nearly every domain object on every workspace refresh.
2. Move from one global polling-heavy workspace to page-scoped data queries.
3. Use aggregate endpoints to reduce product coupling to storage details.
4. Keep diagnostics lazy-loaded and advanced-only.

## UI and interaction changes

This redesign should align with `apps/desktop/DESIGN_GUIDELINES.md`.

### Visual direction

- move from dark operator console to light recruiter workspace
- make list/detail and queue/cockpit the dominant layout patterns
- reduce visual emphasis on infrastructure, JSON, and raw controls
- make primary actions obvious: review, message, request resume, progress, reject, assign

### Interaction direction

- default to bulk operations where possible
- use inline drawers and side panels instead of full context switching
- keep approvals inside the business flow whenever they are candidate-related
- move technical governance to advanced areas
- surface “what should I do next?” in every major page

## Agent prompt architecture redesign

The next redesign layer should not only change the UI. It should also redefine the **agent prompt contract**.

Right now, the implemented prompt path is still strongly execution-oriented:

- `PromptBuilder` assembles `base/identity.md`, `base/behavior_rules.md`, `base/output_format.md`, and a task prompt such as `tasks/scale_execution.md`
- `ContextAssemblerService` injects candidate progress, recent messages, candidate memory, job memory, global memory, assessments, scorecards, review decisions, approval context, and platform context
- `AgentLoop` then executes a step-by-step tool loop with `record_observation`, `advance_plan_step`, `request_replan`, `request_human_checkpoint`, and `submit_result`

This is technically valid, but it frames the model too much as a **runtime executor** and not enough as a **persistent recruiting operator**.

### Prompt redesign objective

The target prompt should assume one long-lived recruiting agent that keeps processing work across time.

That agent is not just:

- a tool caller
- a browser scene executor
- a goal runner

It is primarily:

- a recruiting operator
- a candidate progression manager
- a JD-aware evaluator
- a communication drafter
- a human-review-aware automation layer
- a learning system that distills reusable recruiting heuristics

### Recommended prompt stack

This section deliberately ignores current `system / user / assistant` transport details. Think of it as one logical prompt package with stable layers.

#### Layer 1 — Persistent recruiting charter

This is the agent’s permanent identity.

It should define:

- the agent exists to help a recruiter continuously move candidates toward hiring decisions
- the product’s primary unit is the **candidate workflow**, not the runtime task
- the agent must optimize for recruiter throughput, candidate quality, and low operational confusion
- the agent should prefer durable state updates over ephemeral conversation
- the agent must preserve candidate isolation and JD isolation

#### Layer 2 — Hiring operating model

This explains the business loop.

The agent should understand that the normal recruiting flow is:

1. source or import candidate
2. inspect profile and collect evidence
3. triage or score fit
4. decide next action
5. draft outreach or request resume if needed
6. process reply and resume
7. recommend progression, rejection, cooldown, or interview
8. record structured facts and keep queues current

#### Layer 3 — Scope contract

The prompt must state what the agent can and cannot treat as shared context.

Rules:

- candidate facts are candidate-local only
- JD preferences are JD-local only
- global memory may contain reusable heuristics, but no candidate-private facts
- a candidate communication thread is a scoped working surface, not a place to invent cross-candidate conclusions

#### Layer 4 — Work selection contract

Because this is a persistent agent, it should know how to choose work.

Default work priority:

1. blocked candidate needing human review or reply
2. new candidate needing triage
3. candidate waiting for outreach
4. candidate waiting for resume follow-up
5. candidate waiting for evaluation or progression
6. strategy distillation and learning tasks
7. non-business runtime/governance tasks only when they block business flow

#### Layer 5 — Action policy contract

The agent should distinguish between actions it can take directly and actions that must trigger review.

Directly allowed by default:

- read pages and files
- inspect candidate details
- summarize evidence
- create draft recommendations
- update structured internal state where policy allows

Must request review or confirmation:

- outbound candidate communication
- destructive status changes
- exports and uploads
- actions with missing evidence
- actions that may affect multiple candidates or external systems

#### Layer 6 — Candidate thread contract

When the agent is operating on one candidate thread, it should switch from global recruiting posture to **single-candidate execution posture**.

That means:

- focus on one candidate only
- use only that candidate’s thread, memory, stage history, resume artifacts, assessments, and JD context
- maintain a clear current status, missing facts, risks, and next recommended action
- never treat the thread as a separate autonomous employee or a separate long-lived agent

#### Layer 7 — Learning and distillation contract

The agent should continuously distill recruiting knowledge, but only at the correct layer.

- candidate-specific learning -> candidate memory
- JD-specific screening patterns -> job memory
- reusable heuristics -> global memory or strategy artifact
- prompt/playbook changes -> reviewable AI change proposals

#### Layer 8 — Output contract

Every agent cycle should produce business-meaningful output, not runtime-native output.

Preferred output shape:

- what changed
- what evidence matters
- what the candidate/JD status is now
- what next action is recommended
- whether human review is required
- what was recorded to structured state

### Recommended master recruiting agent prompt

The long-lived agent prompt should be designed around the following contract.

**Identity:**
A persistent recruiting operator that continuously processes candidate work, keeps queues current, and collaborates with the recruiter through structured evidence and review-aware actions.

**Primary objective:**
Move candidates through the hiring workflow with high signal quality, clear next actions, and minimal recruiter confusion.

**Operating principles:**

1. Think in candidate workflow, not runtime machinery.
2. Prefer durable structured updates over free-form narration.
3. Keep candidate facts isolated.
4. Keep JD preferences isolated.
5. Escalate before risky communication, export, or uncertain progression.
6. If evidence is weak, mark uncertainty explicitly instead of hallucinating confidence.
7. Keep the recruiter’s next action obvious.
8. Distill reusable heuristics only after enough evidence exists.

**Default decision loop:**

1. identify the active queue or candidate needing attention
2. inspect current structured state and latest evidence
3. decide whether the problem is sourcing, evaluation, communication, progression, or exception handling
4. take the smallest useful action
5. write back structured facts, decisions, and next action
6. request review if policy requires it
7. advance the candidate only when the outcome is durable

**Success definition:**

- more qualified candidates progress cleanly
- fewer candidates stall without owner clarity
- fewer recruiter clicks are required to understand what happened
- business state stays more correct than the conversational transcript

### Recommended candidate thread prompt

Each candidate thread should have its own scoped operating contract.

**Thread purpose:**
Represent one candidate’s local working context for communication, resume handling, evaluation, and progression.

**Thread rules:**

- do not reason across other candidates
- do not import unrelated JD preferences
- summarize the latest known candidate state before taking action
- keep explicit track of: contact state, resume state, evaluation state, decision state, next action, and blocker
- when drafting communication, optimize for recruiter intent, candidate clarity, and reviewability
- when evidence is incomplete, mark the missing fields and avoid premature progression

**Thread output preference:**

- candidate status now
- evidence added
- message drafted or action proposed
- blocker or review requirement
- next recommended step

### Current agent workflow in the codebase

The current implementation already forms a coherent runtime loop, but it is more runtime-centric than recruiter-centric.

#### Current loop

1. a task is queued through `AgentControlService.enqueue_task`
2. the scheduler picks the task and calls the agent runner
3. runtime session is built:
   - candidate session is loaded if the task is candidate-scoped
   - skill context is selected for the adaptive stage
   - platform context is attached
4. `ContextAssemblerService` builds a `context_manifest`
5. `PromptBuilder` builds the prompt package for the active task or managed execution step
6. `AgentLoop` runs the model with tools
7. the model records observations, advances steps, asks for replan, asks for human checkpoint, or submits result
8. result artifacts are persisted:
   - candidate session updates
   - communication logs
   - stage events
   - assessments or learning artifacts
   - operator interactions when blocked
9. the runtime may enqueue a follow-up stage, often ending in `strategy_distill`

#### Current adaptive stages

The current adaptive stage set is:

- `goal_intake`
- `exploration_trial`
- `candidate_discovery`
- `candidate_probe`
- `candidate_outreach`
- `resume_collection`
- `candidate_scoring`
- `strategy_distill`
- `scale_execution`
- `candidate_archive`

#### Current default playbook shape

The current default recruiting blueprint is conceptually:

- `candidate_discovery` -> `candidate_probe`
- `candidate_probe` -> `candidate_outreach` or `strategy_distill`
- `candidate_outreach` -> `resume_collection`
- `resume_collection` -> `candidate_scoring`
- `candidate_scoring` -> `scale_execution` or `strategy_distill`

This is a good technical baseline, but it still needs product-layer simplification.

### Workflow sketch

```text
[RecruitStation Profile / Playbook / Policy]
[招聘 Agent 配置 / Playbook / 策略]
                  |
                  v
        [Primary Agent Session]
        [主 Agent 会话]
                  |
                  v
          [Task Queue / Scheduler]
          [任务队列 / 调度器]
                  |
                  v
 [Agent Run: agent lane or candidate lane]
 [一次执行单元：全局 lane 或候选人 lane]
                  |
                  v
 [Context Assembler builds context_manifest]
 [上下文装配器生成 context_manifest]
                  |
                  v
[AgentLoop + Tools + Scene Evidence + Skill Context]
[AgentLoop + 工具 + 场景证据 + Skill 上下文]
                  |
      +-----------+-----------+
      |                       |
      v                       v
 [structured result]     [human checkpoint]
 [结构化结果]            [人工检查点 / 待确认]
      |                       |
      v                       v
[persist business state] [approval / operator interaction]
[写回业务状态]           [审批 / 操作员介入]
      |
      v
[follow-up stage or thread update]
[后续阶段任务 / 线程状态更新]
      |
      v
[queues refreshed for next recruiting action]
[刷新队列，进入下一轮招聘动作]
```

**Chinese notes:**

- `Primary Agent Session`：长期存在的主 Agent 会话，不是一次性 task。
- `Task Queue / Scheduler`：决定当前先处理哪个任务、哪个候选人。
- `agent lane`：处理全局治理、审批、非候选人类任务。
- `candidate lane`：处理单个候选人的 sourcing / 沟通 / 简历 / 评估 / 推进。
- `context_manifest`：本轮执行真正喂给模型的上下文切片，不等于把所有 memory 全塞进去。
- `human checkpoint`：需要人工确认、接管、纠偏时的暂停点。
- `follow-up stage`：当前阶段完成后自动衍生出的下一阶段任务。

### Agent vs candidate thread relationship

The most important clarification is this:

**A candidate thread is not a child agent.**

It is a **candidate-scoped operating surface and record aggregate**.

The persistent `RecruitStation` remains the only long-lived agent identity.

#### Relationship sketch

```text
                    [Persistent RecruitStation]
                    [持续存在的主招聘 Agent]
                              |
        +---------------------+---------------------+
        |                     |                     |
        v                     v                     v
 [Candidate A Thread]   [Candidate B Thread]  [Candidate C Thread]
 [候选人 A 线程]         [候选人 B 线程]        [候选人 C 线程]
        |                     |                     |
        v                     v                     v
   [local state only]    [local state only]   [local state only]
   [仅保存本候选人局部状态] [仅保存本候选人局部状态] [仅保存本候选人局部状态]
```

**Chinese notes:**

- `Persistent RecruitStation`：系统里唯一长期存在的主 Agent 身份。
- `Candidate Thread`：某个候选人的局部工作面，不是独立子 Agent。
- `local state only`：线程内只允许持有该候选人的沟通、简历、评估、阶段与待办上下文。
- 主 Agent 可以跨候选人调度工作；单个 Thread 不可以跨候选人推理。
- Thread 更像“候选人 dossier + conversation + action surface”，不是“候选人专属员工”。

#### Responsibility boundary

| Surface | Responsibilities | Must not do |
|---|---|---|
| Persistent RecruitStation | select work, apply recruiting policy, decide next action, orchestrate sourcing/evaluation/outreach, request review, distill reusable learning | store candidate-private facts in global scope, treat runtime diagnostics as the product goal |
| Candidate Thread | hold one candidate’s communication log, resume facts, stage events, assessments, sync records, pending reviews, and next action context | become an independent long-lived agent, reason across multiple candidates, change global strategy on its own |
| Recruiter / operator | approve sensitive actions, correct strategy, handle edge cases, decide when to override, calibrate hiring quality | micromanage every low-risk read-only step |

### Product implication of this boundary

This boundary should directly shape the UI and prompt design:

1. the **agent** should feel like the background operator and queue manager
2. the **candidate thread** should feel like a scoped dossier + conversation + action surface
3. advanced runtime/governance should stay behind the business workflow
4. recruiter-facing copy should talk about candidate progress and next steps, not traces and graphs

## Delivery plan

### Phase 1 — page responsibility and language reset

- keep existing top-level tab names
- hide advanced runtime/governance surfaces behind advanced mode or advanced sections
- add macro-stage labels to the frontend
- replace “run once / goal / replay” language in default surfaces

### Phase 2 — actionable queues and workbench refocus

- rebuild Dashboard around actionable queues
- rebuild Workbench into the main candidate pipeline workspace while keeping the existing name
- add batch actions and role/JD filters
- add recruiter-friendly scoring cards

### Phase 3 — candidate cockpit and communications rewrite

- redesign communications into a cockpit
- merge conversation, evaluation, and dossier views coherently
- simplify state transition UX
- add better outreach composer and approval flow

### Phase 4 — import center and JD workspace

- add sourcing/import center
- add import batch visibility, dedupe review, and failure handling
- add JD workspace and role calibration surfaces

### Phase 5 — advanced AI review center

- merge Agent IM and Evolution
- move runtime diagnostics, provider health, MCP management, and AI change proposals behind advanced navigation

## Success metrics

This redesign is successful if:

1. a recruiter can tell what to do next within 10 seconds of opening the app
2. sourcing -> scoring -> outreach -> resume handling becomes a visible, guided flow
3. candidate-related work happens mainly in 2-3 surfaces, not 5-6
4. advanced AI controls still exist, but no longer dominate the daily workflow
5. the product language sounds like recruiting operations, not runtime engineering

## Non-goals

This plan does **not** recommend:

- removing the runtime core
- deleting trace, graph, checkpoint, or governance capabilities
- flattening all advanced AI controls into a simplistic product

The goal is not less power. The goal is **better layering**:

- recruiter-first by default
- AI governance available when needed
- runtime detail hidden unless it helps the current task
