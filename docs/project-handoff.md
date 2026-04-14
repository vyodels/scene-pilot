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

As of `2026-04-14`, the current local refactor wave is complete.

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

## Resume Checklist On Another Machine

1. Clone the repository to any path you want.
2. Install dependencies.
3. Run backend tests.
4. Run desktop typecheck/build.
5. If you need a local OpenAI-compatible provider, configure it via `SCENE_PILOT_...` env vars or `/api/settings`.

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

A local OpenAI-compatible provider was previously validated during development, but no secret is stored in the repository.

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
