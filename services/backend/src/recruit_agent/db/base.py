from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

try:
    from uuid import uuid7
except ImportError:  # pragma: no cover - Python < 3.14 fallback
    uuid7 = None  # type: ignore[assignment]

from sqlalchemy import BIGINT, JSON, Text
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def unix_seconds_now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def generate_business_id() -> str:
    if uuid7 is not None:
        return uuid7().hex
    return uuid4().hex


def generate_id() -> str:
    return generate_business_id()


class Base(DeclarativeBase):
    pass


class UnixTimestamp(TypeDecorator[int]):
    impl = BIGINT
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> int | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, datetime):
            dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.isdigit():
                return int(text)
            try:
                dt = datetime.fromisoformat(text)
            except ValueError as exc:  # pragma: no cover - defensive path
                raise TypeError(f"Unsupported timestamp string: {value!r}") from exc
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        raise TypeError(f"Unsupported timestamp value: {value!r}")

    def process_result_value(self, value: Any, dialect) -> int | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.isdigit():
                return int(text)
            else:
                dt = datetime.fromisoformat(text)
        else:  # pragma: no cover - defensive path
            raise TypeError(f"Unsupported timestamp result value: {value!r}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())


class TimestampMixin:
    created_at: Mapped[int] = mapped_column(BIGINT, default=unix_seconds_now, nullable=False)
    updated_at: Mapped[int] = mapped_column(BIGINT, default=unix_seconds_now, onupdate=unix_seconds_now, nullable=False)


class JsonPayloadMixin:
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class TextPayloadMixin:
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
