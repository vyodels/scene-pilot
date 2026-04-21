from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.core.settings import AppSettings
from recruit_agent.services.container import AppContainer


def get_container(request: Request) -> AppContainer:
    return request.app.state.container  # type: ignore[return-value]


def get_runtime_settings(request: Request) -> AppSettings:
    return request.app.state.settings


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return request.app.state.session_factory


def get_session(container: AppContainer = Depends(get_container)) -> Iterator[Session]:
    session = container.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_db(request: Request) -> Iterator[Session]:
    session_factory = get_session_factory(request)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
