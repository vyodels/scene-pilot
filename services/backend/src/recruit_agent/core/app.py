from __future__ import annotations

import argparse

from fastapi import FastAPI

from recruit_agent.core.settings import AppSettings, load_settings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    from recruit_agent.server import create_app as create_server_app

    return create_server_app(settings)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Recruit Agent backend")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    settings = load_settings()
    overrides = {}
    if args.host is not None:
        overrides["host"] = args.host
    if args.port is not None:
        overrides["port"] = args.port
    if args.data_dir is not None:
        overrides["data_dir"] = args.data_dir
    if args.database_url is not None:
        overrides["database_url"] = args.database_url
    if overrides:
        settings = settings.with_overrides(**overrides)

    import uvicorn

    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
