# Agent Management Recruiting Automation Handoff

Date: 2026-05-15
Repo: `/Users/vyodels/AgentProjects/RecruitStation`

## Current State

This handoff records the completed Agent management pass for the automated recruiting agent. The implementation keeps recruiting business behavior in product adapter, API, UI configuration, business tools, and tests. It does not move JD strategy, scoring, IM sync, resume/contact handling, or workflow policy into `agent_runtime`.

The completed shape has three main pieces:

- Workspace-level control for the automated recruiting agent: `start`, `pause`, `continue`, and `terminate`.
- Productized configuration pages for high-frequency recruiting policy: JD strategy, execution SOP, activation/priority, resume strategy, external sync, run plan, business tool permissions, and read-only base capability.
- A realistic multi-JD workflow validation using the existing `AutonomousAdapter` plus recruiting business tools: 5 JDs, 10 candidates per JD, online/offline resumes, contact details, communication logs, outbound IM sync acknowledgements, scoring, scorecards, review decisions, and JD progress checks.

## Boundary Rules Preserved

Do not put recruiting business policy or workflow orchestration into:

```text
services/backend/src/recruit_station/agent_runtime/**
```

The runtime remains generic. This pass only changed:

- `services/backend/src/recruit_station/agents/heartbeat.py`
- `services/backend/src/recruit_station/api/routers/agent.py`
- desktop Agent management UI and API client files
- focused backend tests

The execution SOP remains a high-authority business policy/prompt dimension. It is not implemented as a programmatic workflow engine. Programmatic control is limited to workspace gates, activation/stop/priority policy data, queue behavior, and approval/tool permissions.

## Backend Changes

Workspace control is stored through `AgentGlobalState.state_metadata["workspace_control"]`.

New API surface:

```text
GET  /api/agents/autonomous/workspace-control
POST /api/agents/autonomous/workspace-control/start
POST /api/agents/autonomous/workspace-control/pause
POST /api/agents/autonomous/workspace-control/continue
POST /api/agents/autonomous/workspace-control/terminate
```

Behavior:

- `start` opens the autonomous queue gate; it does not create a run.
- `pause` stops future queue claim through `Heartbeat`.
- `continue` reopens the queue gate after a pause.
- `terminate` stops the workspace and cancels open autonomous runs plus their pending/running queue items.
- `GET /api/agents/{kind}/workspace` now includes `workspaceControl` for the autonomous workspace.

Existing run-level controls remain:

```text
POST /api/agents/autonomous/runs/{run_id}/cancel
POST /api/agents/autonomous/runs/{run_id}/resume
```

## Frontend Changes

Updated files:

```text
apps/desktop/src/features/chat-overlay/ChatOverlay.tsx
apps/desktop/src/lib/api.ts
apps/desktop/src/lib/types.ts
apps/desktop/src/styles.css
```

Agent management now exposes a compact workspace control area for the automated recruiting agent:

- stopped: `开始`
- running: `暂停` and `终止`
- paused: `继续` and `终止`

Autonomous instructions and structured run plans are blocked in the UI until the workspace is started. This enforces the product rule that configuring the agent does not directly execute it.

The desktop API client also fixes old autonomous run control paths from the removed `execution-episodes` route to the current `runs/{run_id}` route.

## Configuration Pages

The automated recruiting configuration now has independent pages:

- `JD 策略`: per-JD screening criteria, online resume scoring, offline resume scoring, composite scoring, pass thresholds, and manual review rules.
- `执行 SOP`: shared recruiting execution SOP for all selected JDs in the current run. This is prompt/business policy, not a programmatic workflow engine.
- `激活与优先级`: start conditions, stop conditions, priority preset, priority scoring model, cooldown/frequency limits. These are programmatic scheduling inputs.
- `恢复策略`: state resume sources and runtime input preview. This describes `State Resume + Summary Resume`.
- `同步策略`: external JD state, IM bidirectional sync, resume/contact/evidence sync boundaries.
- `运行计划`: executable JD selection for the next run.
- `工具权限`: business-tool-bound approval gates.
- `基础能力`: read-only system/developer/base capability inspection.

Saved configuration is stored under the autonomous agent runtime metadata as `automationRecruitingConfig`.

## Workflow Validation

The integration test added a realistic data-only workflow validation:

```text
services/backend/tests/agent/integration/test_multi_jd_recruiting_agent_mock_workflow.py
```

Coverage:

- 5 active JDs.
- 10 candidates per JD.
- Candidate discovery through `upsert_candidate`.
- Online resume text with realistic role evidence and contact details.
- Outbound and inbound IM records.
- Offline resume artifacts with extracted text and contact snapshots.
- Pending outbound sync records and sync acknowledgements.
- Online resume scoring, offline resume scoring, composite scoring.
- Explicit scorecards.
- Review decisions.
- Per-JD progress: 10 candidates, 10 contacts, 10 resumes, 10 AI scores.
- No VirtualHID/browser-mcp dependency.

The validation intentionally uses `AutonomousAdapter + ScriptedProvider + recruit toolkit` rather than browser automation.

## Validation Already Run

These passed:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/backend/src python3 -m pytest services/backend/tests/api/test_agents_routes.py services/backend/tests/agent/integration/test_heartbeat.py services/backend/tests/agent/integration/test_multi_jd_recruiting_agent_mock_workflow.py -q
```

Result:

```text
15 passed
```

Additional checks:

```bash
python3 -m compileall -q services/backend/src/recruit_station
npm --workspace apps/desktop run typecheck
git diff -- services/backend/src/recruit_station/agent_runtime
```

The `agent_runtime` diff was empty.

## Follow-Up Risks

- The configuration UI is now functionally complete for the requested policy shape, but future visual refinement should still keep each module page independent rather than collapsing everything into one form.
- Workspace `terminate` cancels open runs and queue items. It does not hard-interrupt an already executing model/tool turn inside the same process; hard interruption would require a separate cancellation token design.
- Activation/priority policy is persisted and passed as structured policy data, but a full external event scanner or scheduler evaluator is outside this pass.

## Resume Instructions

For future work on Agent management:

1. Read `docs/specs/2026-05-11-agent-runtime-product-boundary-spec.md`.
2. Read `docs/specs/2026-05-11-recruiting-business-capability-data-spec.md`.
3. Keep recruiting business policy out of `agent_runtime`.
4. Use the focused validation set before changing the automated recruiting flow:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/backend/src python3 -m pytest services/backend/tests/api/test_agents_routes.py services/backend/tests/agent/integration/test_heartbeat.py services/backend/tests/agent/integration/test_multi_jd_recruiting_agent_mock_workflow.py -q
npm --workspace apps/desktop run typecheck
```
