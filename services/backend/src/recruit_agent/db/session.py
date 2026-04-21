from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.base import Base
from recruit_agent.db.migrations import run_migrations


def create_engine_from_settings(settings: AppSettings) -> Engine:
    database_url = settings.resolved_database_url()
    url = make_url(database_url)
    engine_kwargs = {"echo": settings.database_echo, "future": True}
    if url.drivername.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(database_url, **engine_kwargs)

    if url.drivername.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def initialize_database(engine: Engine) -> None:
    # Import model registrations before create_all so standalone initialization
    # creates the full schema instead of only the migration registry.
    import recruit_agent.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    run_migrations(engine)


def get_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
