from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import BIGINT, DateTime, JSON, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def unix_seconds_now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def generate_business_id() -> str:
    return uuid4().hex


def generate_id() -> str:
    return generate_business_id()


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[int] = mapped_column(BIGINT, default=unix_seconds_now, nullable=False)
    updated_at: Mapped[int] = mapped_column(BIGINT, default=unix_seconds_now, onupdate=unix_seconds_now, nullable=False)


class JsonPayloadMixin:
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class TextPayloadMixin:
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
