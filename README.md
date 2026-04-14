# General Automation Runtime

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

Website integrations such as Boss are runtime capabilities and environment states. They are not the product's fixed business flow.

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

## Core Runtime Concepts

- `TaskSpec`: normalized task contract compiled from natural language
- `ExecutionPlan`: runtime execution graph created from task intent plus current environment state
- `ExecutionEpisode`: one supervised or production execution attempt with replayable observations
- `WorkflowTemplate`: a reusable template promoted from validated execution patterns
- `WorkflowPatch`: a proposed workflow update created when runtime execution diverges
- `Skill`: a local stable capability with versioning, health checks, and deactivation
- `EnvironmentSnapshot`: a structured record of the current site/app/runtime state

Read the detailed architecture in [docs/general-automation-runtime.md](./docs/general-automation-runtime.md) and the phased rollout in [Plan.md](./Plan.md).

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
uvicorn recruit_agent.server:create_app --reload --factory
```

## Desktop Packaging

The desktop release chain is present but final packaging still depends on Electron runtime binaries being available on the packaging machine.

```bash
npm install --ignore-scripts
npm run desktop:build
npm run desktop:release:prepare
npm run desktop:release:preflight
npm run desktop:package:dir
```

Notes:

- `scripts/prepare-desktop-package.mjs` stages backend assets for packaging.
- `scripts/preflight-desktop-package.mjs` fails early if Electron runtime artifacts are missing.
- `.npmrc` keeps `ignore-scripts=true` in this environment to avoid unstable downloads; release machines should install with scripts enabled.
