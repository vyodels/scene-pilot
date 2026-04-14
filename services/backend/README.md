# ScenePilot Backend

FastAPI backend foundation for the ScenePilot automation runtime.

## What is here

- SQLAlchemy models for candidates, workflows, skills, approvals, settings, audit logs, and agent learning records.
- Repository layer for local-first SQLite persistence.
- Pydantic schemas for REST payloads.
- FastAPI routers for health, workflows, candidates, skills, settings, approvals, and metrics.

## Run

Install dependencies and start the app:

```bash
python -m pip install -e .[dev]
scene-pilot-backend --port 8741
```

By default the backend stores SQLite data under the configured data directory and exposes the API on `127.0.0.1`.

## API surface

- `GET /health`
- `GET|POST|PATCH|DELETE /api/workflows`
- `GET|POST|PATCH|DELETE /api/candidates`
- `GET|POST|PATCH|DELETE /api/skills`
- `GET|PUT /api/settings`
- `GET|POST|PATCH /api/approvals`
- `GET /api/metrics`
