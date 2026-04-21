This package contains the canonical FastAPI API surface for the Recruit Agent backend.

Layout:

- `api/__init__.py`: router registration and compatibility exports
- `api/deps.py`: canonical dependency injection helpers
- `api/routers/*`: route modules mounted by `include_api_routers`

`api/dependencies.py` has been removed in favor of `api/deps.py`.
