from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.db.base import utcnow
from scene_pilot.models.domain import CandidateAutonomousLock, JobDescription
from scene_pilot.repositories.domain import JobDescriptionPlatformIdxRepository, JobDescriptionRepository

_UNSET = object()


def take_over_candidate(
    session_factory: sessionmaker[Session],
    *,
    candidate_person_id: str,
    locked_by: str,
    reason: str | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    with session_factory() as session:
        lock = _active_lock(session, candidate_person_id)
        if lock is None:
            lock = CandidateAutonomousLock(
                candidate_person_id=candidate_person_id,
                locked_by=locked_by,
                reason=reason,
                expires_at=expires_at,
            )
            session.add(lock)
        else:
            lock.locked_by = locked_by
            lock.reason = reason
            lock.expires_at = expires_at
            lock.released_at = None
            lock.released_by = None
        session.commit()
        session.refresh(lock)
        return _serialize_lock(lock)


def release_candidate(
    session_factory: sessionmaker[Session],
    *,
    candidate_person_id: str,
    released_by: str,
    handover_note: str | None = None,
    handover_next_hint: str | None = None,
) -> dict[str, Any]:
    with session_factory() as session:
        lock = _active_lock(session, candidate_person_id)
        if lock is None:
            raise KeyError(f"candidate {candidate_person_id} is not locked")
        lock.released_at = utcnow()
        lock.released_by = released_by
        if handover_note is not None:
            lock.handover_note = handover_note
        if handover_next_hint is not None:
            lock.handover_next_hint = handover_next_hint
        session.commit()
        session.refresh(lock)
        return _serialize_lock(lock)


def list_locked_candidates(session_factory: sessionmaker[Session]) -> list[dict[str, Any]]:
    with session_factory() as session:
        stmt = select(CandidateAutonomousLock).where(CandidateAutonomousLock.released_at.is_(None))
        return [_serialize_lock(lock) for lock in session.scalars(stmt).all() if _not_expired(lock)]


def list_job_descriptions(
    session_factory: sessionmaker[Session],
    *,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
) -> list[dict[str, Any]]:
    with session_factory() as session:
        stmt = select(JobDescription).order_by(JobDescription.updated_at.desc(), JobDescription.id.asc()).offset(offset).limit(
            max(1, min(int(limit or 100), 500))
        )
        normalized_status = _normalize_optional_text(status)
        if normalized_status:
            stmt = stmt.where(JobDescription.status == normalized_status)
        items = session.scalars(stmt).all()
        return [_serialize_job_description(session, item) for item in items]


def upsert_job_description(
    session_factory: sessionmaker[Session],
    *,
    title: str,
    job_description_id: str | None = None,
    company_name: Any = _UNSET,
    department: Any = _UNSET,
    location: Any = _UNSET,
    employment_type: Any = _UNSET,
    headcount: Any = _UNSET,
    salary_min: Any = _UNSET,
    salary_max: Any = _UNSET,
    compensation_text: Any = _UNSET,
    experience_requirement: Any = _UNSET,
    education_requirement: Any = _UNSET,
    summary: Any = _UNSET,
    description: Any = _UNSET,
    requirements: Any = _UNSET,
    benefit_tags: Any = _UNSET,
    detail_metadata: Any = _UNSET,
    status: Any = _UNSET,
    source: Any = _UNSET,
    platform: Any = _UNSET,
    external_id: Any = _UNSET,
    external_url: Any = _UNSET,
    sync_status: Any = _UNSET,
    sync_metadata: Any = _UNSET,
) -> dict[str, Any]:
    normalized_title = _normalize_required_text(title, field_name="title")
    normalized_platform = None if platform is _UNSET else _normalize_optional_text(platform)
    normalized_external_id = None if external_id is _UNSET else _normalize_optional_text(external_id)
    normalized_external_url = None if external_url is _UNSET else _normalize_optional_text(external_url)
    normalized_sync_status = None if sync_status is _UNSET else (_normalize_optional_text(sync_status) or "synced")
    normalized_department = None if department is _UNSET else _normalize_optional_text(department)
    normalized_location = None if location is _UNSET else _normalize_optional_text(location)

    with session_factory() as session:
        repo = JobDescriptionRepository(session)
        idx_repo = JobDescriptionPlatformIdxRepository(session)

        item = None if not job_description_id else repo.get(str(job_description_id).strip())
        if item is None and normalized_platform and normalized_external_id:
            idx = idx_repo.by_platform_identity(normalized_platform, normalized_external_id)
            if idx is not None:
                item = repo.get_by_storage_id(idx.job_description_id)

        if item is None:
            item = _find_matching_job(
                session,
                title=normalized_title,
                department=normalized_department,
                location=normalized_location,
            )

        payload: dict[str, Any] = {"title": normalized_title}
        _set_if_provided(payload, "company_name", company_name, _normalize_optional_text)
        _set_if_provided(payload, "department", department, _normalize_optional_text)
        _set_if_provided(payload, "location", location, _normalize_optional_text)
        _set_if_provided(payload, "employment_type", employment_type, _normalize_optional_text)
        _set_if_provided(payload, "headcount", headcount)
        _set_if_provided(payload, "salary_min", salary_min)
        _set_if_provided(payload, "salary_max", salary_max)
        _set_if_provided(payload, "compensation_text", compensation_text, _normalize_optional_text)
        _set_if_provided(payload, "experience_requirement", experience_requirement, _normalize_optional_text)
        _set_if_provided(payload, "education_requirement", education_requirement, _normalize_optional_text)
        _set_if_provided(payload, "summary", summary, _normalize_optional_text)
        _set_if_provided(payload, "description", description, _normalize_optional_text)
        _set_if_provided(payload, "requirements", requirements, _normalize_optional_text)
        _set_if_provided(payload, "benefit_tags", benefit_tags, _normalize_string_list)
        _set_if_provided(payload, "detail_metadata", detail_metadata, lambda value: _normalize_mapping(value, field_name="detail_metadata"))

        if status is _UNSET:
            if item is None:
                payload["status"] = "active"
        else:
            payload["status"] = _normalize_optional_text(status) or "active"

        if source is _UNSET:
            if item is None:
                payload["source"] = "platform_sync"
        else:
            payload["source"] = _normalize_optional_text(source) or "platform_sync"

        action = "created"
        if item is None:
            item = repo.create(payload)
        else:
            item = repo.update(item, payload)
            action = "updated"

        platform_identity = None
        if normalized_platform and normalized_external_id:
            idx = idx_repo.by_platform_identity(normalized_platform, normalized_external_id)
            idx_payload: dict[str, Any] = {
                "job_description_id": item.id,
                "platform": normalized_platform,
                "external_id": normalized_external_id,
                "last_synced_at": utcnow(),
            }
            if idx is None or external_url is not _UNSET:
                idx_payload["external_url"] = normalized_external_url
            if idx is None or sync_status is not _UNSET:
                idx_payload["sync_status"] = normalized_sync_status or "synced"
            if idx is None or sync_metadata is not _UNSET:
                idx_payload["sync_metadata"] = _normalize_mapping(sync_metadata, field_name="sync_metadata")
            if idx is None:
                idx = idx_repo.create(idx_payload)
            else:
                idx = idx_repo.update(idx, idx_payload)
            platform_identity = {
                "platform": idx.platform,
                "external_id": idx.external_id,
                "external_url": idx.external_url,
                "sync_status": idx.sync_status,
                "sync_metadata": dict(idx.sync_metadata or {}),
                "last_synced_at": idx.last_synced_at,
            }

        return {
            "action": action,
            "job_description": _serialize_job_description(session, item),
            "platform_identity": platform_identity,
        }


def _active_lock(session: Session, candidate_person_id: str) -> CandidateAutonomousLock | None:
    stmt = (
        select(CandidateAutonomousLock)
        .where(
            CandidateAutonomousLock.candidate_person_id == candidate_person_id,
            CandidateAutonomousLock.released_at.is_(None),
        )
        .order_by(CandidateAutonomousLock.locked_at.desc(), CandidateAutonomousLock.id.desc())
    )
    for lock in session.scalars(stmt).all():
        if _not_expired(lock):
            return lock
    return None


def _not_expired(lock: CandidateAutonomousLock) -> bool:
    return lock.expires_at is None or lock.expires_at >= datetime.now(UTC)


def _serialize_lock(lock: CandidateAutonomousLock) -> dict[str, Any]:
    return {
        "id": lock.id,
        "candidate_person_id": lock.candidate_person_id,
        "locked_at": lock.locked_at,
        "locked_by": lock.locked_by,
        "reason": lock.reason,
        "expires_at": lock.expires_at,
        "released_at": lock.released_at,
        "released_by": lock.released_by,
        "handover_note": lock.handover_note,
        "handover_next_hint": lock.handover_next_hint,
    }


def _find_matching_job(session: Session, *, title: str, department: str | None, location: str | None) -> JobDescription | None:
    stmt = select(JobDescription).where(JobDescription.title == title)
    if department is not None:
        stmt = stmt.where(JobDescription.department == department)
    if location is not None:
        stmt = stmt.where(JobDescription.location == location)
    stmt = stmt.order_by(JobDescription.updated_at.desc(), JobDescription.id.asc())
    return session.scalars(stmt).first()


def _serialize_job_description(session: Session, item: JobDescription) -> dict[str, Any]:
    idx_repo = JobDescriptionPlatformIdxRepository(session)
    platform_identities = []
    for idx in session.scalars(
        select(idx_repo.model)
        .where(idx_repo.model.job_description_id == item.id)
        .order_by(idx_repo.model.updated_at.desc(), idx_repo.model.id.asc())
    ).all():
        platform_identities.append(
            {
                "platform": idx.platform,
                "external_id": idx.external_id,
                "external_url": idx.external_url,
                "sync_status": idx.sync_status,
                "sync_metadata": dict(idx.sync_metadata or {}),
                "last_synced_at": idx.last_synced_at,
            }
        )
    return {
        "job_description_id": item.job_description_id,
        "title": item.title,
        "company_name": item.company_name,
        "department": item.department,
        "location": item.location,
        "employment_type": item.employment_type,
        "headcount": item.headcount,
        "salary_min": item.salary_min,
        "salary_max": item.salary_max,
        "compensation_text": item.compensation_text,
        "experience_requirement": item.experience_requirement,
        "education_requirement": item.education_requirement,
        "summary": item.summary,
        "description": item.description,
        "requirements": item.requirements,
        "benefit_tags": list(item.benefit_tags or []),
        "detail_metadata": dict(item.detail_metadata or {}),
        "status": item.status,
        "source": item.source,
        "platform_identities": platform_identities,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _normalize_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _normalize_optional_text(item)
        if text is None or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _normalize_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value in (None, _UNSET):
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise ValueError(f"{field_name} must be an object")


def _set_if_provided(
    payload: dict[str, Any],
    key: str,
    value: Any,
    normalizer: Callable[[Any], Any] | None = None,
) -> None:
    if value is _UNSET:
        return
    payload[key] = normalizer(value) if normalizer is not None else value


def _normalize_required_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
