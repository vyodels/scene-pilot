# ScenePilot Handoff

## What This Project Is

ScenePilot is a local-first desktop automation runtime.

It is not a recruiting product with fixed site integrations.
Recruiting remains the first domain pack, but the product core is:

- `Task Compiler`
- `Planner / Replanner`
- `Supervised Trial & Learning`
- `ReAct-like Executor`

Concrete sites, internal systems, desktop apps, and tools are all `runtime scenes`.

## Current State

As of `2026-04-15`, the current local refactor wave is complete.

Completed:

- project renamed to `ScenePilot`
- Python package renamed to `scene_pilot`
- root workspace renamed to `scene-pilot`
- desktop product name / app id / package names updated
- env var prefix updated to `SCENE_PILOT_`
- `Task Compiler` upgraded to `LLM-first structured semantic compiler`
- `Planner / Replanner` converged on scene-driven runtime replanning
- `ReAct-like Executor` deepened with step-level tool preferences and runtime execution prompt
- `Capability Drivers` expanded and wired into planning and execution
- `Learning Loop` hardened with replay, patch approval/apply, template candidate approval, skill health checks, and single-machine governance
- local queue / replay / diagnostics / runtime launch flow working in the desktop control plane
- desktop information architecture reorganized around workflow lifecycle:
  - `概览`
  - `工作流管理`
  - `工作台`
  - `审批中心`
  - `Skills`
  - `设置`
- user-facing terminology updated:
  - `domain pack` -> `场景画像`
  - `task` -> `工作流`
  - `task instance` -> `工作流实例`
- formal recruiting workflow validation completed against the live local provider
  - compile path used `llm_structured`
  - supervised trial succeeded
  - trial confirmation promoted an active workflow version
  - production execution now stops at `waiting_human` / `awaiting_review` when no live browser snapshot is available
  - previous false `timeout / Token budget exceeded` behavior is fixed

Verified locally:

- `python3 -m pytest services/backend/tests -q`
- `npm run desktop:typecheck`
- `npm run desktop:build`

## Latest Key Commits

- `e0b3f5d` `refactor: rename project to scenepilot`
- `0261dd6` `feat: converge runtime planner and executor`
- `003fd06` `feat: harden runtime compiler and queue governance`
- `f495857` `feat: deepen runtime browser scene planning`
- `52051c0` `feat: publish runtime compiler contract`
- `b1d35e1` `feat: reorganize workflow lifecycle workspace`
- `896cb7d` `feat: refine workflow console and validation gating`

## What Is Not Pending As Core Dev Work

These are no longer valid backlog items:

- pre-integrating `Boss`
- pre-integrating any specific website
- growing the core runtime around fixed site workflows

Correct interpretation:

- `Boss`, GitHub, intranet systems, news sites, tool directories, and other apps are runtime scenes
- the runtime should approach them through `capability drivers + environment model + supervised trial + learning loop`

## Remaining Work

No mandatory local code gap remains for the current wave.

Remaining items are external or later-stage:

- real `Anthropic` environment validation
- Apple signing / notarization credentials and release run
- final validation against the real intranet environment

## Most Recent Validation Outcome

The most recent formal validation target was the recruiting workflow.

What was verified:

- natural language request -> workflow compile
- compile used the live local OpenAI-compatible provider
- trial run -> review -> version activation
- production launch through the queue
- managed execution preflight gating

Important outcome:

- if production execution lacks a live browser/environment snapshot, the runtime now stops early and requests human review
- it no longer proceeds into the executor loop and wastes tokens
- a blocked-task approval is created for desktop review

## Resume Checklist On Another Machine

1. Clone the repository to any path you want.
2. Install dependencies.
3. Run backend tests.
4. Run desktop typecheck/build.
5. If you need a local OpenAI-compatible provider, configure it via `SCENE_PILOT_...` env vars or `/api/settings`.
6. For the current recruiting validation flow, ensure the backend settings point at the local provider and then run a supervised trial before production launch.

Recommended verification commands:

```bash
python3 -m pytest services/backend/tests -q
npm install --ignore-scripts
npm run desktop:typecheck
npm run desktop:build
```

Backend dev entry:

```bash
cd services/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn scene_pilot.server:create_app --reload --factory
```

Desktop dev entry:

```bash
npm install --ignore-scripts
npm run desktop:dev
```

## Local Provider Note

A local OpenAI-compatible provider was validated during development:

- base URL: `http://127.0.0.1:8317/v1`
- model: `gpt-5.4`

No secret is stored in the repository.

If you want to resume with a local provider, set it locally through environment variables or the settings API/UI.

## Naming And Path Notes

- repo workspace name: `scene-pilot`
- Python package: `scene_pilot`
- desktop product name: `ScenePilot`
- old `recruit-agent` / `recruit_agent` naming should be treated as historical only

## Primary Files To Read First

- [README.md](../README.md)
- [Plan.md](../Plan.md)
- [docs/general-automation-runtime.md](./general-automation-runtime.md)
- [services/backend/src/scene_pilot/services/runtime.py](../services/backend/src/scene_pilot/services/runtime.py)
- [services/backend/src/scene_pilot/runtime/agent_loop.py](../services/backend/src/scene_pilot/runtime/agent_loop.py)
- [apps/desktop/src/features/workspace/DesktopWorkspace.tsx](../apps/desktop/src/features/workspace/DesktopWorkspace.tsx)
