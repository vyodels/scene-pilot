# ScenePilot

Local-first desktop control plane and backend runtime for natural-language automation workflows. Recruiting is one domain pack on top of the runtime, not the product core.

## Product Positioning

This project is building a general automation system that can:

- compile natural-language goals into executable `TaskSpec` and `ExecutionPlan`
- inspect runtime environment state and choose capabilities dynamically
- run new workflows under supervised trial mode before promotion
- learn stable local `Skill` objects from repeated execution
- propose `WorkflowPatch` updates when real execution diverges, then route them through human confirmation

Examples of supported domains include:

- recruiting workflows such as sourcing, resume collection, scoring, and internal upload
- daily market/news collection and summarization
- web research tasks such as tool discovery and comparison
- GitHub trend collection and structured reporting

Boss, GitHub, internal systems, desktop applications, third-party tools, and websites in general are runtime scenes. They are not the product's fixed business flow or a hardcoded development-time integration backlog.

More precisely:

- New sites, tools, and internal systems are runtime scenarios, not a backlog of fixed development-time integrations.
- The system is expected to approach new scenarios through `capability drivers + environment model + supervised trial + learning loop`.
- Any concrete site name in the repository should be read as an example domain scenario or compatibility surface, not as the architectural center of the product.

## Target Runtime Layers

The target runtime is organized around four layers:

- `Task Compiler`: an `LLM-first structured semantic compiler` that turns natural-language requests into structured task contracts. It is not a keyword rules engine.
- `Planner / Replanner`: builds and repairs `ExecutionPlan` objects from task intent plus live environment state.
- `Supervised Trial & Learning`: runs first-pass supervised trials, records episodes, proposes patches, and promotes validated skills/templates.
- `ReAct-like Executor`: performs observe-reason-act loops inside approved capability boundaries.

## Current Repository Layout

- `apps/desktop`: Electron + React desktop control plane
- `services/backend`: FastAPI backend, runtime, scheduler, persistence, and domain packs
- `packages/shared`: shared frontend contracts and mock/demo data
- `docs`: architecture and refactor design notes

## Current State

The repository already contains a local-first desktop/backend baseline:

- Electron/React operator workspace
- FastAPI backend with SQLite-first persistence
- approval-gated agent execution, event streaming, and scheduler scaffolding
- recruiting domain pack as the first implemented workflow family
- learning, sync, and system-command safety scaffolding

The current refactor wave is moving the system from a recruiting-specific architecture toward a general automation runtime while preserving the existing recruiting flow as a domain pack.

That shift means the main engineering target is not "finish integrating site X". The target is to make the runtime capable of entering unfamiliar environments, testing a plan under supervision, learning reusable skills/templates, and correcting itself when the environment changes.

Some parts of the current codebase are still transitional:

- recruiting-specific routes, screens, and terminology remain as the first domain pack and compatibility surface
- some workflow and agent paths still reflect the earlier fixed-flow implementation style
- some concrete site/platform names remain in example data, compatibility tool names, or legacy persistence fields

Those transitional pieces should not be read as the final architecture.

## Core Runtime Concepts

- `TaskSpec`: normalized task contract compiled from natural language
- `ExecutionPlan`: runtime execution graph created from task intent plus current environment state
- `ExecutionEpisode`: one supervised or production execution attempt with replayable observations
- `WorkflowTemplate`: a reusable template promoted from validated execution patterns
- `WorkflowPatch`: a proposed workflow update created when runtime execution diverges
- `Skill`: a local stable capability with versioning, health checks, and deactivation
- `EnvironmentSnapshot`: a structured record of the current site/app/runtime state

These concepts exist to support runtime adaptation. They are intentionally broader than any one website workflow.

Read the detailed architecture in [docs/general-automation-runtime.md](./docs/general-automation-runtime.md) and the phased rollout in [Plan.md](./Plan.md).
For a machine-to-machine resume guide, read [docs/project-handoff.md](./docs/project-handoff.md).

## Development Start Points

Frontend:

```bash
npm install --ignore-scripts
npm run desktop:dev
```

Backend:

```bash
cd services/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn scene_pilot.server:create_app --reload --factory
```

## Desktop Packaging

The desktop release chain now supports both local verification packages and distribution-grade macOS release preflight.

```bash
npm install --ignore-scripts
npm run desktop:build
npm run desktop:release:prepare
npm run desktop:release:preflight
npm run desktop:package:dir
```

Notes:

- `scripts/prepare-desktop-package.mjs` stages backend assets and the local Electron runtime for packaging.
- `scripts/preflight-desktop-package.mjs` reports Electron runtime readiness, signing mode, and notarization mode.
- `.npmrc` keeps `ignore-scripts=true` in this environment to avoid unstable downloads; release machines should install with scripts enabled.
- For an externally distributed macOS build, use:

```bash
npm run desktop:release:preflight:distribution
npm run desktop:package:distribution
```

- Release-signing details are documented in [docs/macos-release.md](./docs/macos-release.md).
