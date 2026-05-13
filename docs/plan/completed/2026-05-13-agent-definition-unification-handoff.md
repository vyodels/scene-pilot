# AgentDefinition Unification Handoff

Date: 2026-05-13
Branch: `main`
Latest implementation commit: `b2aba15 Unify AgentDefinition assembly`
Repo: `/Users/didi/AgentProjects/recruit-agent`

## Current State

The AgentDefinition / Agent unification plan has been implemented and committed.

This pass intentionally uses a fresh final shape:

- no database migration compatibility layer
- no legacy Goal / objective / instruction alias compatibility
- no live `RecruitAgentProfile` / AgentProfile concept
- no separate Assistant runtime or Autonomous runtime

`AgentDefinition` is now the live core Agent definition contract. Assistant and Autonomous are product types / product adapters that bind to AgentDefinition and provide lifecycle, IO projection, trigger, wakeup, resume, checkpoint, writeback, and UI/API concerns.

## Core Constraints

The current long-term constraint source is:

```text
docs/specs/2026-05-11-agent-runtime-product-boundary-spec.md
```

The spec now states:

- `AgentDefinition` expresses Agent identity, duties, boundaries, system prompt, business strategy, tool scope, memory policy, skill policy, MCP policy, permission policy, output policy, and budget policy.
- Different AgentDefinitions may have different content values.
- Assistant / Autonomous cannot become a second Agent definition source.
- Product mode may inject runtime hints such as chat response style or durable run output contract, but must not override Agent identity, duties, boundaries, or tool governance.
- Shared assembly owns system prompt placement, history, turn input, product context, memory, skills, MCP resources, tool registry, permission metadata, and limits.
- Shared runner owns final output, status, gate signal, tool calls/results, permission request, and runtime events.

The runtime boundary remains: `agent_runtime/**` must stay product/business free.

## Implemented

- Replaced live `RecruitAgentProfile` model/schema/repository/API naming with `AgentDefinition`.
- Removed old live Goal concepts and routes, including `/api/recruit-agent/goals`.
- Removed legacy autonomous goal prompt template.
- Made autonomous run creation canonical on `instruction`; empty instruction is rejected.
- Added shared product-layer runner:

```text
services/backend/src/recruit_agent/product_adapters/agent_runner.py
```

- Routed Assistant and Autonomous through shared runner semantics for prompt placement, tool scoping, output normalization, status/gate handling, and permission requests.
- Added transcript checkpoint serialization for pending permission state.
- Added durable Autonomous permission resume from stored runtime checkpoint after adapter cache loss.
- Fixed `extract_execution_status` to prefer `execution_status` over business `status`.
- Updated frontend/shared contracts around `AgentDefinition`, `AgentDefinitionConfig`, and `AgentProductBinding`.
- Updated Agent Management config UI to separate AgentDefinition config from product adapter config.
- Updated capability sidebar/detail UI to show schema/metadata, risk, permission, domain, source, and status.
- Updated active specs and tests to guard against Goal/Profile reintroduction.

## Important Files

- `docs/specs/2026-05-11-agent-runtime-product-boundary-spec.md`
- `services/backend/src/recruit_agent/models/domain.py`
- `services/backend/src/recruit_agent/schemas/domain.py`
- `services/backend/src/recruit_agent/repositories/domain.py`
- `services/backend/src/recruit_agent/api/routers/agent.py`
- `services/backend/src/recruit_agent/api/routers/recruit_agent.py`
- `services/backend/src/recruit_agent/product_adapters/agent_runner.py`
- `services/backend/src/recruit_agent/product_adapters/context_builder.py`
- `services/backend/src/recruit_agent/agents/assistant.py`
- `services/backend/src/recruit_agent/agents/autonomous.py`
- `services/backend/src/recruit_agent/agent_runtime/engine.py`
- `services/backend/src/recruit_agent/agent_runtime/transcript.py`
- `packages/shared/src/contracts.ts`
- `apps/desktop/src/lib/api.ts`
- `apps/desktop/src/lib/types.ts`
- `apps/desktop/src/features/chat-overlay/ChatOverlay.tsx`

## Validation Already Run

These passed before commit `b2aba15`:

```bash
python3 -m compileall -q services/backend/src services/backend/tests
npm run shared:build
npm run desktop:typecheck
python3 -m pytest services/backend/tests -q
git diff --check
```

Additional scans passed:

```bash
rg -n "AgentProfile|RecruitAgentProfile|agent_profile_id|agentProfileId|agent_key|agentKey|getAgentProfile|updateAgentProfile|/api/recruit-agent/profile|agent profile|Recruit agent profile|agent_profiles" services/backend/src apps/desktop/src packages/shared/src docs/specs docs/plan/active
rg -n "\bgoal\b|\bGoal\b|GoalSpec|goal_spec|goalId|goal_id|goal_text|/api/recruit-agent/goals|automationInstruction|automation_instruction|instruction_template|resolve_instruction_template|get_goal_progress" services/backend/src apps/desktop/src packages/shared/src docs/specs docs/plan/active .recruit-agent/prompts
```

Both scans returned no live-code/spec/prompt hits.

## Resume Instructions

On the new machine:

1. Pull or otherwise transfer branch `main` including commit `b2aba15`.
2. Run:

```bash
git status --short
python3 -m pytest services/backend/tests -q
npm run shared:build
npm run desktop:typecheck
```

3. If continuing implementation, start from the runtime boundary spec and this handoff. Do not use older completed handoffs as current guidance.

## Known Boundaries

- Archive/reference docs are historical only and were not part of the live cleanup target.
- No old database migration compatibility was added by design.
- TaskSpec remains a task compilation / scene delegation artifact, not an Agent target or Goal replacement.
- Product adapter code may contain product concepts such as Assistant, Autonomous, AgentRun, and recruiting business state. `agent_runtime/**` must not.
- Assistant and Autonomous may bind to different AgentDefinitions, but cannot fork runner, tool loop, permission semantics, transcript semantics, or output semantics.

## Current Follow-Up Risk

No blocker is known after `b2aba15`.

If future work changes AgentDefinition, verify:

- fresh schema still has `agent_definitions` and no `recruit_agent_profiles`
- fresh schema has no `goal_specs`, `agent_profile_id`, or `goal_spec_id`
- `agent_runtime/**` remains free of product/business imports and terms
- Autonomous permission approval still resumes from checkpoint after adapter cache loss
