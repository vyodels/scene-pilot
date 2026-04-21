from __future__ import annotations

from datetime import datetime, timezone


def normalize_application_window_month(at: datetime | None = None) -> str:
    reference = at or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(timezone.utc).strftime("%Y-%m")


def make_application_window(person_id: str, job_description_id: str, at: datetime | None = None) -> str:
    person_key = str(person_id or "").strip()
    job_key = str(job_description_id or "").strip()
    if not person_key:
        raise ValueError("person_id is required to build application_window")
    if not job_key:
        raise ValueError("job_description_id is required to build application_window")
    return f"{person_key}_{job_key}_{normalize_application_window_month(at)}"
