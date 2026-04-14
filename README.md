# Recruit Agent

Local-first desktop recruiting agent scaffold based on the implementation plan in [Plan.md](./Plan.md).

## Workspace Layout

- `apps/desktop`: Electron + React desktop shell
- `packages/shared`: shared frontend contracts and mock data
- `services/backend`: FastAPI backend, runtime, workflow engine, scheduler, and persistence

## Current State

This repository now contains the first full scaffold for the platform:

- Electron/React desktop shell with major product views
- FastAPI backend with local SQLite-first configuration
- Domain models, repositories, and REST endpoints
- Agent runtime, workflow engine, scheduler, and platform abstraction
- Prompt templates, feature flags, and safety-oriented services
- Basic backend tests and frontend wiring points

## Start Points

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

The backend and desktop package definitions are present, but dependencies are not installed by default in this environment.

## Desktop Packaging

The repo now includes a first-pass release chain for the desktop app:

```bash
npm install --ignore-scripts
npm run desktop:build
npm run desktop:release:prepare
npm run desktop:release:preflight
npm run desktop:package:dir
```

Notes:

- Packaging is configured through `electron-builder.yml`.
- `npm run desktop:release:prepare` stages backend assets through `scripts/prepare-desktop-package.mjs`.
- `npm run desktop:release:preflight` validates that Electron is installed, the local Electron runtime binary exists, and the staged/backend build artifacts expected by `electron-builder` are present before packaging starts.
- `npm run desktop:package` and `npm run desktop:package:dir` now fail fast on preflight errors instead of passing opaque packaging failures through from deeper in the toolchain.
- Packaged startup looks for a bundled backend binary under `resources/backend-dist/`.
- If no bundled backend binary exists, the packaged app falls back to launching the backend from bundled source under `resources/backend-src/src`, which requires a system `python3` plus backend dependencies.
- The local `.npmrc` keeps `ignore-scripts=true` to avoid Electron download instability in this environment. Release machines that need Electron binary downloads should run install with scripts enabled.
