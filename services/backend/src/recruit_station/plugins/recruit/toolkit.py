from __future__ import annotations

from datetime import UTC, datetime, timezone
import html
import json
import re
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from recruit_station.db.base import utcnow
from recruit_station.models.domain import ApplicationCommunicationLog, CandidateAutonomousLock, CandidatePlatformIdx, JobDescription
from recruit_station.repositories.domain import (
    ApplicationCommunicationLogRepository,
    CandidateApplicationRepository,
    CandidatePlatformIdxRepository,
    CandidateRepository,
    JobDescriptionPlatformIdxRepository,
    JobDescriptionRepository,
    ResumeArtifactRepository,
)
from recruit_station.schemas import (
    CandidateAssessmentCreate,
    CandidateConversationEntryCreate,
    CandidateReviewDecisionCreate,
    CandidateScorecardCreate,
    CandidateStateTransitionRequest,
    ResumeArtifactCreate,
    TalentPoolSyncRecordCreate,
)
from recruit_station.services.application_window import make_application_window
from recruit_station.services.candidate_identity import (
    canonicalize_contact_info,
    contact_channels_from_info,
    extract_contact_info_from_text,
    merge_contact_info,
)
from recruit_station.services.job_description_stats import build_job_description_funnel_stats
from recruit_station.services.recruit_station import default_candidate_state_snapshot
from recruit_station.services.state_machine import available_state_statuses

_UNSET = object()


def take_over_candidate(
    session_factory: sessionmaker[Session],
    *,
    application_id: str,
    locked_by: str,
    reason: str | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    with session_factory() as session:
        application = _resolve_application(session, application_id=application_id)
        candidate = CandidateRepository(session).get_by_storage_id(application.person_id)
        if candidate is None:
            raise KeyError(f"candidate person for application {application.candidate_application_id} not found")
        lock = _active_lock(session, application.candidate_application_id)
        if lock is None:
            lock = CandidateAutonomousLock(
                application_id=application.candidate_application_id,
                candidate_person_id=candidate.candidate_person_id,
                locked_by=locked_by,
                reason=reason,
                expires_at=expires_at,
            )
            session.add(lock)
        else:
            lock.application_id = application.candidate_application_id
            lock.candidate_person_id = candidate.candidate_person_id
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
    application_id: str,
    released_by: str,
    handover_note: str | None = None,
    handover_next_hint: str | None = None,
) -> dict[str, Any]:
    with session_factory() as session:
        lock = _active_lock(session, application_id)
        if lock is None:
            raise KeyError(f"candidate application {application_id} is not locked")
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
    normalized_sync_metadata = None if sync_metadata is _UNSET else _normalize_mapping(sync_metadata, field_name="sync_metadata")

    _validate_mock_recruiting_site_exact_jd_fields(
        title=normalized_title,
        company_name=None if company_name is _UNSET else _normalize_optional_text(company_name),
        department=normalized_department,
        location=normalized_location,
        compensation_text=None if compensation_text is _UNSET else _normalize_optional_text(compensation_text),
        headcount=None if headcount is _UNSET else headcount,
        platform=normalized_platform,
        external_url=normalized_external_url,
        sync_metadata=normalized_sync_metadata,
    )

    with session_factory() as session:
        repo = JobDescriptionRepository(session)
        idx_repo = JobDescriptionPlatformIdxRepository(session)

        item = None if not job_description_id else repo.get(str(job_description_id).strip())
        if item is None and normalized_platform and normalized_external_id:
            idx = idx_repo.by_platform_identity(normalized_platform, normalized_external_id)
            if idx is not None:
                item = repo.get_by_storage_id(idx.job_description_id)

        if item is None and normalized_external_id:
            item = _find_matching_job_by_external_identity(
                session,
                title=normalized_title,
                external_id=normalized_external_id,
                external_url=normalized_external_url,
            )

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
                idx_payload["sync_metadata"] = normalized_sync_metadata or {}
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


def list_candidates(
    session_factory: sessionmaker[Session],
    *,
    limit: int = 100,
    offset: int = 0,
    platform: str | None = None,
    job_description_id: str | None = None,
    application_status: str | None = None,
) -> list[dict[str, Any]]:
    normalized_platform = _normalize_optional_text(platform)
    normalized_job_description_id = _normalize_optional_text(job_description_id)
    normalized_application_status = _normalize_optional_text(application_status)
    with session_factory() as session:
        candidate_repo = CandidateRepository(session)
        application_repo = CandidateApplicationRepository(session)
        candidates = candidate_repo.list(limit=5000, offset=0)
        filtered: list[dict[str, Any]] = []
        for candidate in candidates:
            if normalized_platform and candidate.platform != normalized_platform:
                continue
            applications = application_repo.by_person(candidate.id, limit=100, offset=0)
            matched_applications = [
                application
                for application in applications
                if (
                    (not normalized_job_description_id or _application_job_description_id(session, application) == normalized_job_description_id)
                    and (not normalized_application_status or str(application.current_status or "").strip() == normalized_application_status)
                )
            ]
            if normalized_job_description_id or normalized_application_status:
                if not matched_applications:
                    continue
                filtered.append(_serialize_candidate(session, candidate, applications=matched_applications))
                continue
            filtered.append(_serialize_candidate(session, candidate, applications=applications))
        start = max(0, int(offset or 0))
        end = start + max(1, min(int(limit or 100), 500))
        return filtered[start:end]


def upsert_candidate(
    session_factory: sessionmaker[Session],
    *,
    name: str,
    candidate_person_id: str | None = None,
    platform: str = "site",
    platform_candidate_id: str | None = None,
    contact_info: Any = _UNSET,
    resume_path: Any = _UNSET,
    online_resume_text: Any = _UNSET,
    profile_url: Any = _UNSET,
    raw_profile: Any = _UNSET,
    first_seen_at: Any = _UNSET,
    last_seen_at: Any = _UNSET,
    job_description_id: str | None = None,
    platform_application_id: str | None = None,
    current_status: str | None = None,
    current_stage_key: str | None = None,
    deepest_milestone: str | None = None,
    state_snapshot: Any = _UNSET,
    application_metadata: Any = _UNSET,
    source_platform: str | None = None,
    source_observation: Any = _UNSET,
) -> dict[str, Any]:
    normalized_name = _normalize_required_text(name, field_name="name")
    normalized_platform = _normalize_optional_text(platform) or "site"
    normalized_candidate_person_id = _normalize_optional_text(candidate_person_id)
    normalized_platform_candidate_id = _normalize_optional_text(platform_candidate_id)
    normalized_job_description_id = _normalize_optional_text(job_description_id)
    normalized_source_platform = _normalize_optional_text(source_platform) or normalized_platform

    with session_factory() as session:
        normalized_current_status, normalized_current_stage, source_state_metadata = _normalize_application_state_input(
            session,
            current_status=current_status,
            current_stage_key=current_stage_key,
        )
        candidate_repo = CandidateRepository(session)
        idx_repo = CandidatePlatformIdxRepository(session)
        candidate = None if normalized_candidate_person_id is None else candidate_repo.get(normalized_candidate_person_id)
        if candidate is None and normalized_platform_candidate_id:
            candidate = candidate_repo.by_platform_candidate_id(normalized_platform, normalized_platform_candidate_id)

        normalized_contact_info: dict[str, Any] | None = None
        if contact_info is not _UNSET:
            normalized_contact_info = canonicalize_contact_info(
                _normalize_mapping(contact_info, field_name="contact_info")
            )
        normalized_online_resume_text = (
            _normalize_optional_text(online_resume_text) if online_resume_text is not _UNSET else None
        )
        inferred_contact_info = extract_contact_info_from_text(normalized_online_resume_text)
        if inferred_contact_info:
            normalized_contact_info = merge_contact_info(inferred_contact_info, normalized_contact_info)

        candidate_payload: dict[str, Any] = {
            "name": normalized_name,
            "platform": normalized_platform,
        }
        if normalized_platform_candidate_id is not None:
            candidate_payload["platform_candidate_id"] = normalized_platform_candidate_id
        if normalized_contact_info is not None:
            candidate_payload["contact_info"] = normalized_contact_info
        if resume_path is not _UNSET:
            candidate_payload["resume_path"] = _normalize_optional_text(resume_path)
        if online_resume_text is not _UNSET:
            candidate_payload["online_resume_text"] = normalized_online_resume_text

        candidate_action = "created"
        if candidate is None:
            candidate = candidate_repo.create(candidate_payload)
        else:
            if normalized_contact_info is not None:
                candidate_payload["contact_info"] = merge_contact_info(dict(candidate.contact_info or {}), candidate_payload["contact_info"])
            candidate = candidate_repo.update(candidate, candidate_payload)
            candidate_action = "updated"

        platform_identity = None
        if normalized_platform_candidate_id:
            candidate_idx = idx_repo.by_candidate_and_platform(candidate.id, normalized_platform)
            idx_payload = {
                "candidate_id": candidate.id,
                "platform": normalized_platform,
                "platform_candidate_person_id": normalized_platform_candidate_id,
            }
            if profile_url is not _UNSET:
                idx_payload["profile_url"] = _normalize_optional_text(profile_url)
            if raw_profile is not _UNSET:
                idx_payload["raw_profile"] = _normalize_mapping(raw_profile, field_name="raw_profile")
            if first_seen_at is not _UNSET:
                idx_payload["first_seen_at"] = _normalize_datetime(first_seen_at, field_name="first_seen_at")
            if last_seen_at is not _UNSET:
                idx_payload["last_seen_at"] = _normalize_datetime(last_seen_at, field_name="last_seen_at")
            if candidate_idx is None:
                candidate_idx = idx_repo.create(idx_payload)
            else:
                candidate_idx = idx_repo.update(candidate_idx, idx_payload)
            platform_identity = _serialize_candidate_platform_idx(candidate_idx)

        application_payload = None
        application_action = None
        if normalized_job_description_id:
            application_repo = CandidateApplicationRepository(session)
            canonical_window = make_application_window(candidate.candidate_person_id, normalized_job_description_id)
            application = application_repo.by_application_window(canonical_window)
            payload: dict[str, Any] = {
                "person_id": candidate.candidate_person_id,
                "job_description_id": normalized_job_description_id,
                "platform": normalized_source_platform,
                "source_platform": normalized_source_platform,
                "current_status": normalized_current_status,
                "current_stage_key": normalized_current_stage,
                "deepest_milestone": _normalize_optional_text(deepest_milestone),
                "application_window": canonical_window,
            }
            if normalized_platform_candidate_id:
                payload["source_platform_candidate_person_id"] = normalized_platform_candidate_id
            if platform_application_id is not None:
                payload["platform_application_id"] = _normalize_optional_text(platform_application_id)
            snapshot = (
                _normalize_mapping(state_snapshot, field_name="state_snapshot")
                if state_snapshot is not _UNSET
                else default_candidate_state_snapshot(
                    status=normalized_current_status,
                    stage_key=normalized_current_stage,
                )
            )
            _align_state_snapshot(
                snapshot,
                status=normalized_current_status,
                stage_key=normalized_current_stage,
            )
            contact_snapshot = merge_contact_info({}, dict(candidate.contact_info or {}))
            if contact_snapshot:
                snapshot["contact_channels"] = contact_channels_from_info(contact_snapshot)
                snapshot["contact_acquired"] = bool(contact_snapshot.get("channels"))
                snapshot["contact_status"] = "available" if snapshot["contact_acquired"] else snapshot.get("contact_status") or "unknown"
            payload["state_snapshot"] = snapshot
            payload["contact_snapshot"] = contact_snapshot
            payload["resume_snapshot"] = _resume_snapshot_from_candidate(candidate)
            combined_application_metadata = (
                _normalize_mapping(application_metadata, field_name="application_metadata")
                if application_metadata is not _UNSET
                else {}
            )
            if source_observation is not _UNSET:
                combined_application_metadata["source_observation"] = _normalize_mapping(
                    source_observation,
                    field_name="source_observation",
                )
            if source_state_metadata:
                existing_source_state = (
                    combined_application_metadata.get("source_state")
                    if isinstance(combined_application_metadata.get("source_state"), dict)
                    else {}
                )
                combined_application_metadata["source_state"] = {
                    **existing_source_state,
                    **source_state_metadata,
                }
            if combined_application_metadata:
                payload["application_metadata"] = combined_application_metadata
            if application is None:
                application = application_repo.create(payload)
                application_action = "created"
            else:
                application = application_repo.update(application, payload)
                application_action = "updated"
            application_payload = _serialize_candidate_application(session, application)

        return {
            "action": candidate_action,
            "candidate": _serialize_candidate(session, candidate),
            "platform_identity": platform_identity,
            "application_action": application_action,
            "application": application_payload,
        }


def score_candidate(
    session_factory: sessionmaker[Session],
    *,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
    score: int | None = None,
    decision: str | None = None,
    summary: str | None = None,
    stage_key: str | None = None,
    evidence_refs: list[Any] | None = None,
    created_by: str | None = "autonomous",
    rubric_version: str | None = None,
    dimension_scores: Any = _UNSET,
    metadata: Any = _UNSET,
) -> dict[str, Any]:
    from recruit_station.api.routers._candidate_application_support import create_application_assessment

    with session_factory() as session:
        application = _resolve_application(
            session,
            application_id=application_id,
            candidate_person_id=candidate_person_id,
            job_description_id=job_description_id,
        )
        assessment_metadata = _normalize_mapping(metadata, field_name="metadata") if metadata is not _UNSET else {}
        if rubric_version is not None:
            assessment_metadata["rubric_version"] = _normalize_optional_text(rubric_version) or "recruit-scorecard-v1"
        if dimension_scores is not _UNSET:
            assessment_metadata["dimension_scores"] = _normalize_mapping(dimension_scores, field_name="dimension_scores")
        assessment = create_application_assessment(
            application.candidate_application_id,
            CandidateAssessmentCreate(
                assessment_type="ai",
                stage_key=_normalize_optional_text(stage_key) or application.current_stage_key or application.current_status,
                status="completed",
                decision=_normalize_optional_text(decision),
                score=score,
                summary=_normalize_optional_text(summary),
                evidence_refs=list(evidence_refs or []),
                metadata=assessment_metadata,
                created_by=_normalize_optional_text(created_by) or "autonomous",
            ),
            session,
        )
        ai_scores = {
            "overall": score,
            "decision": _normalize_optional_text(decision),
            "evidence_refs": list(evidence_refs or []),
            "dimension_scores": dict(assessment_metadata.get("dimension_scores") or {}),
            "rubric_version": str(assessment_metadata.get("rubric_version") or "recruit-scorecard-v1"),
        }
        refreshed = CandidateApplicationRepository(session).update(
            application,
            {
                "ai_scores": ai_scores,
                "ai_reasoning": _normalize_optional_text(summary),
                "current_stage_key": _normalize_optional_text(stage_key) or application.current_stage_key,
            },
        )
        return {
            "assessment": assessment.model_dump(by_alias=True),
            "application": _serialize_candidate_application(session, refreshed),
        }


def record_outbound_message(
    session_factory: sessionmaker[Session],
    *,
    content: str,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
    channel_hint: str | None = None,
    status: str = "draft",
    message_type: str = "text",
    metadata: Any = _UNSET,
) -> dict[str, Any]:
    entry_metadata = _normalize_mapping(metadata, field_name="metadata") if metadata is not _UNSET else {}
    entry_metadata.setdefault(
        "outbound_sync",
        {
            "status": "pending",
            "source": "record_outbound_message",
            "created_at": utcnow().isoformat(),
            "destinations": {},
        },
    )
    return record_candidate_message(
        session_factory,
        content=content,
        direction="outbound",
        application_id=application_id,
        candidate_person_id=candidate_person_id,
        job_description_id=job_description_id,
        channel_hint=channel_hint,
        status=status,
        message_type=message_type,
        metadata=entry_metadata,
    )


def record_candidate_message(
    session_factory: sessionmaker[Session],
    *,
    content: str,
    direction: str = "inbound",
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
    channel_hint: str | None = None,
    status: str = "received",
    message_type: str = "text",
    observed_at: Any = _UNSET,
    metadata: Any = _UNSET,
) -> dict[str, Any]:
    from recruit_station.api.routers._candidate_application_support import create_application_entry

    normalized_content = _normalize_required_text(content, field_name="content")
    normalized_direction = (_normalize_optional_text(direction) or "inbound").lower()
    if normalized_direction not in {"inbound", "outbound", "system"}:
        raise ValueError("direction must be inbound, outbound, or system")
    normalized_status = _normalize_optional_text(status) or "draft"
    with session_factory() as session:
        application = _resolve_application(
            session,
            application_id=application_id,
            candidate_person_id=candidate_person_id,
            job_description_id=job_description_id,
        )
        entry_metadata = _normalize_mapping(metadata, field_name="metadata") if metadata is not _UNSET else {}
        if channel_hint is not None:
            entry_metadata["channel_hint"] = _normalize_optional_text(channel_hint)
        entry_metadata["status"] = normalized_status
        if normalized_direction == "outbound" and "outbound_sync" not in entry_metadata:
            observed_timestamp = _normalize_datetime(observed_at, field_name="observed_at") if observed_at is not _UNSET else None
            entry_metadata["outbound_sync"] = {
                "status": "observed",
                "source": "record_candidate_message",
                "observed_at": observed_timestamp.isoformat() if observed_timestamp is not None else utcnow().isoformat(),
                "destinations": {},
            }
        entry = create_application_entry(
            session,
            application.candidate_application_id,
            CandidateConversationEntryCreate(
                direction=normalized_direction,
                content=normalized_content,
                message_type=_normalize_optional_text(message_type) or "text",
                platform=str(application.source_platform or application.platform or "site"),
                metadata=entry_metadata,
                timestamp=_normalize_datetime(observed_at, field_name="observed_at") if observed_at is not _UNSET else None,
            ),
        )
        snapshot = dict(application.state_snapshot or {}) or default_candidate_state_snapshot(status=application.current_status)
        if normalized_direction == "outbound":
            snapshot["contact_status"] = "sent" if normalized_status == "sent" else "drafted"
        elif normalized_direction == "inbound":
            snapshot["contact_status"] = "replied"
        snapshot["latest_note"] = normalized_content[:240]
        channel = _normalize_optional_text(channel_hint)
        if channel:
            existing_channels = list(snapshot.get("contact_channels") or [])
            if channel not in existing_channels:
                existing_channels.append(channel)
            snapshot["contact_channels"] = existing_channels
        refreshed = CandidateApplicationRepository(session).update(
            application,
            {
                "state_snapshot": snapshot,
                "last_contacted_at": utcnow() if normalized_status == "sent" else application.last_contacted_at,
            },
        )
        return {
            "entry": entry.model_dump(by_alias=True),
            "application": _serialize_candidate_application(session, refreshed),
        }


def list_pending_candidate_message_syncs(
    session_factory: sessionmaker[Session],
    *,
    application_id: str | None = None,
    destination: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    normalized_destination = _normalize_optional_text(destination)
    normalized_limit = max(1, min(int(limit or 100), 500))
    with session_factory() as session:
        stmt = (
            select(ApplicationCommunicationLog)
            .where(ApplicationCommunicationLog.direction == "outbound")
            .order_by(ApplicationCommunicationLog.timestamp.asc(), ApplicationCommunicationLog.id.asc())
            .limit(normalized_limit)
        )
        if application_id:
            application = _resolve_application(session, application_id=application_id)
            stmt = stmt.where(ApplicationCommunicationLog.application_id == application.id)
        pending: list[dict[str, Any]] = []
        for message in session.scalars(stmt).all():
            metadata = dict(message.message_metadata or {})
            sync_state = _message_outbound_sync_state(metadata)
            if not sync_state:
                continue
            if not _message_sync_is_pending(sync_state, destination=normalized_destination):
                continue
            pending.append(_serialize_application_message(session, message))
        return pending


def record_candidate_message_sync_ack(
    session_factory: sessionmaker[Session],
    *,
    message_id: str,
    destination: str,
    status: str = "synced",
    external_message_id: str | None = None,
    external_event_id: str | None = None,
    observed_at: Any = _UNSET,
    metadata: Any = _UNSET,
) -> dict[str, Any]:
    normalized_message_id = _normalize_required_text(message_id, field_name="message_id")
    normalized_destination = _normalize_required_text(destination, field_name="destination")
    normalized_status = _normalize_optional_text(status) or "synced"
    with session_factory() as session:
        message = _resolve_application_message(session, normalized_message_id)
        message_metadata = dict(message.message_metadata or {})
        sync_state = _message_outbound_sync_state(message_metadata)
        if not sync_state:
            sync_state = {
                "status": "pending",
                "source": "external_sync_ack",
                "created_at": utcnow().isoformat(),
                "destinations": {},
            }
        destinations = dict(sync_state.get("destinations") or {})
        destination_state = dict(destinations.get(normalized_destination) or {})
        destination_state["status"] = normalized_status
        destination_state["acknowledged_at"] = utcnow().isoformat()
        if external_message_id is not None:
            destination_state["external_message_id"] = _normalize_optional_text(external_message_id)
        if external_event_id is not None:
            destination_state["external_event_id"] = _normalize_optional_text(external_event_id)
        normalized_observed_at = _normalize_datetime(observed_at, field_name="observed_at") if observed_at is not _UNSET else None
        if normalized_observed_at is not None:
            destination_state["observed_at"] = normalized_observed_at.isoformat()
        if metadata is not _UNSET:
            destination_state["metadata"] = _normalize_mapping(metadata, field_name="metadata")
        destinations[normalized_destination] = destination_state
        sync_state["destinations"] = destinations
        sync_state["status"] = normalized_status
        sync_state["last_destination"] = normalized_destination
        sync_state["updated_at"] = utcnow().isoformat()
        message_metadata["outbound_sync"] = sync_state
        message.message_metadata = message_metadata
        session.commit()
        session.refresh(message)
        return _serialize_application_message(session, message)


def attach_resume_artifact(
    session_factory: sessionmaker[Session],
    *,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
    source: str = "site",
    artifact_type: str = "resume",
    file_name: str | None = None,
    file_path: str | None = None,
    extracted_text: str | None = None,
    contact_snapshot: Any = _UNSET,
    metadata: Any = _UNSET,
) -> dict[str, Any]:
    from recruit_station.api.routers._candidate_application_support import build_application_thread, create_application_resume_artifact

    with session_factory() as session:
        application = _resolve_application(
            session,
            application_id=application_id,
            candidate_person_id=candidate_person_id,
            job_description_id=job_description_id,
        )
        artifact = create_application_resume_artifact(
            application.candidate_application_id,
            ResumeArtifactCreate(
                source=_normalize_optional_text(source) or "site",
                artifact_type=_normalize_optional_text(artifact_type) or "resume",
                file_name=_normalize_optional_text(file_name),
                file_path=_normalize_optional_text(file_path),
                extracted_text=_normalize_optional_text(extracted_text),
                contact_snapshot=(
                    canonicalize_contact_info(_normalize_mapping(contact_snapshot, field_name="contact_snapshot"))
                    if contact_snapshot is not _UNSET
                    else {}
                ),
                metadata=_normalize_mapping(metadata, field_name="metadata") if metadata is not _UNSET else {},
            ),
            session,
        )
        thread = build_application_thread(session, application.candidate_application_id)
        return {
            "artifact": artifact.model_dump(by_alias=True),
            "thread": thread.model_dump(by_alias=True),
        }


def delete_resume_artifact(
    session_factory: sessionmaker[Session],
    *,
    artifact_id: str,
) -> dict[str, Any]:
    normalized_artifact_id = _normalize_required_text(artifact_id, field_name="artifact_id")
    with session_factory() as session:
        repo = ResumeArtifactRepository(session)
        item = repo.get(normalized_artifact_id)
        if item is None:
            raise KeyError(f"resume artifact {normalized_artifact_id} not found")
        repo.delete(item)
        return {"deleted": True, "artifact_id": normalized_artifact_id}


def transition_application(
    session_factory: sessionmaker[Session],
    *,
    to_status: str,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
    phase_key: str | None = None,
    phase_label: str | None = None,
    stage_key: str | None = None,
    stage_label: str | None = None,
    note: str | None = None,
    actor: str | None = "agent",
    actor_id: str | None = "autonomous",
    trigger: str | None = "agent_tool",
    override_reason: str | None = None,
    metadata: Any = _UNSET,
    interview_round: int | None = None,
    contact_channels: list[str] | None = None,
) -> dict[str, Any]:
    from recruit_station.api.routers._candidate_application_support import create_application_status_transition

    with session_factory() as session:
        application = _resolve_application(
            session,
            application_id=application_id,
            candidate_person_id=candidate_person_id,
            job_description_id=job_description_id,
        )
        normalized_to_status = _normalize_required_text(to_status, field_name="to_status")
        normalized_metadata = _normalize_mapping(metadata, field_name="metadata") if metadata is not _UNSET else {}
        normalized_stage_key = _normalize_optional_text(stage_key)
        if normalized_stage_key and normalized_stage_key != normalized_to_status:
            normalized_metadata.setdefault("requested_stage_key", normalized_stage_key)
            normalized_stage_key = normalized_to_status
        thread = create_application_status_transition(
            session,
            application.candidate_application_id,
            CandidateStateTransitionRequest(
                to_status=normalized_to_status,
                phase_key=_normalize_optional_text(phase_key),
                phase_label=_normalize_optional_text(phase_label),
                stage_key=normalized_stage_key,
                stage_label=_normalize_optional_text(stage_label),
                note=_normalize_optional_text(note),
                source="agent",
                actor=_normalize_optional_text(actor) or "agent",
                actor_id=_normalize_optional_text(actor_id),
                trigger=_normalize_optional_text(trigger) or "agent_tool",
                override_reason=_normalize_optional_text(override_reason),
                metadata=normalized_metadata,
                interview_round=interview_round,
                contact_channels=contact_channels,
            ),
        )
        return {"thread": thread.model_dump(by_alias=True)}


def archive_candidate(
    session_factory: sessionmaker[Session],
    *,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return transition_application(
        session_factory,
        to_status="exception_closed",
        application_id=application_id,
        candidate_person_id=candidate_person_id,
        job_description_id=job_description_id,
        stage_key="exception_closed",
        stage_label="异常关闭",
        note=note,
        actor="agent",
        actor_id="autonomous",
        trigger="archive_candidate",
    )


def delete_candidate(
    session_factory: sessionmaker[Session],
    *,
    candidate_person_id: str,
) -> dict[str, Any]:
    normalized_candidate_person_id = _normalize_required_text(candidate_person_id, field_name="candidate_person_id")
    with session_factory() as session:
        repo = CandidateRepository(session)
        item = repo.get(normalized_candidate_person_id)
        if item is None:
            raise KeyError(f"candidate {normalized_candidate_person_id} not found")
        repo.delete(item)
        return {"deleted": True, "candidate_person_id": normalized_candidate_person_id}


def list_candidate_threads(
    session_factory: sessionmaker[Session],
    *,
    limit: int = 50,
    offset: int = 0,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
) -> list[dict[str, Any]]:
    from recruit_station.api.routers._candidate_application_support import build_application_thread, list_application_threads

    with session_factory() as session:
        normalized_application_id = _normalize_optional_text(application_id)
        if normalized_application_id:
            return [build_application_thread(session, normalized_application_id).model_dump(by_alias=True)]
        threads = [thread.model_dump(by_alias=True) for thread in list_application_threads(limit=max(1, min(int(limit or 50), 200)), offset=max(0, int(offset or 0)), session=session)]
        normalized_candidate_person_id = _normalize_optional_text(candidate_person_id)
        normalized_job_description_id = _normalize_optional_text(job_description_id)
        filtered: list[dict[str, Any]] = []
        for thread in threads:
            if normalized_candidate_person_id and str(thread.get("personId") or thread.get("person_id") or "") != normalized_candidate_person_id:
                continue
            if normalized_job_description_id and str(thread.get("jobDescriptionId") or thread.get("job_description_id") or "") != normalized_job_description_id:
                continue
            filtered.append(thread)
        return filtered


def get_candidate_thread(
    session_factory: sessionmaker[Session],
    *,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
) -> dict[str, Any]:
    from recruit_station.api.routers._candidate_application_support import build_application_thread

    with session_factory() as session:
        application = _resolve_application(
            session,
            application_id=application_id,
            candidate_person_id=candidate_person_id,
            job_description_id=job_description_id,
        )
        return build_application_thread(session, application.candidate_application_id).model_dump(by_alias=True)


def create_candidate_scorecard(
    session_factory: sessionmaker[Session],
    *,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
    stage_key: str | None = None,
    source: str = "ai",
    rubric_version: str = "recruit-scorecard-v1",
    score_total: int | None = None,
    verdict: str | None = None,
    summary: str | None = None,
    dimension_scores: Any = _UNSET,
    evidence_refs: list[Any] | None = None,
    metadata: Any = _UNSET,
) -> dict[str, Any]:
    from recruit_station.api.routers._candidate_application_support import create_application_scorecard

    with session_factory() as session:
        application = _resolve_application(
            session,
            application_id=application_id,
            candidate_person_id=candidate_person_id,
            job_description_id=job_description_id,
        )
        scorecard = create_application_scorecard(
            application.candidate_application_id,
            CandidateScorecardCreate(
                stage_key=_normalize_optional_text(stage_key) or application.current_stage_key or application.current_status,
                source=_normalize_optional_text(source) or "ai",
                rubric_version=_normalize_optional_text(rubric_version) or "recruit-scorecard-v1",
                score_total=score_total,
                verdict=_normalize_optional_text(verdict),
                summary=_normalize_optional_text(summary),
                dimension_scores=_normalize_mapping(dimension_scores, field_name="dimension_scores") if dimension_scores is not _UNSET else {},
                evidence_refs=list(evidence_refs or []),
                metadata=_normalize_mapping(metadata, field_name="metadata") if metadata is not _UNSET else {},
            ),
            session,
        )
        return {"scorecard": scorecard.model_dump(by_alias=True)}


def create_candidate_review_decision(
    session_factory: sessionmaker[Session],
    *,
    decision: str,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
    stage_key: str | None = None,
    rationale: str | None = None,
    decision_source: str = "manual",
    decided_by: str | None = "autonomous",
    scorecard_id: str | None = None,
    metadata: Any = _UNSET,
) -> dict[str, Any]:
    from recruit_station.api.routers._candidate_application_support import create_application_review_decision

    with session_factory() as session:
        application = _resolve_application(
            session,
            application_id=application_id,
            candidate_person_id=candidate_person_id,
            job_description_id=job_description_id,
        )
        review = create_application_review_decision(
            application.candidate_application_id,
            CandidateReviewDecisionCreate(
                stage_key=_normalize_optional_text(stage_key) or application.current_stage_key or application.current_status,
                decision=_normalize_required_text(decision, field_name="decision"),
                rationale=_normalize_optional_text(rationale),
                decision_source=_normalize_optional_text(decision_source) or "manual",
                decided_by=_normalize_optional_text(decided_by) or "autonomous",
                scorecard_id=_normalize_optional_text(scorecard_id),
                metadata=_normalize_mapping(metadata, field_name="metadata") if metadata is not _UNSET else {},
            ),
            session,
        )
        return {"review_decision": review.model_dump(by_alias=True)}


def create_candidate_sync_record(
    session_factory: sessionmaker[Session],
    *,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
    destination: str = "talent_pool",
    status: str = "pending",
    external_ref: str | None = None,
    payload_snapshot: Any = _UNSET,
    error_message: str | None = None,
    metadata: Any = _UNSET,
) -> dict[str, Any]:
    from recruit_station.api.routers._candidate_application_support import create_application_sync_record

    with session_factory() as session:
        application = _resolve_application(
            session,
            application_id=application_id,
            candidate_person_id=candidate_person_id,
            job_description_id=job_description_id,
        )
        sync_record = create_application_sync_record(
            application.candidate_application_id,
            TalentPoolSyncRecordCreate(
                destination=_normalize_optional_text(destination) or "talent_pool",
                status=_normalize_optional_text(status) or "pending",
                external_ref=_normalize_optional_text(external_ref),
                payload_snapshot=_normalize_mapping(payload_snapshot, field_name="payload_snapshot") if payload_snapshot is not _UNSET else {},
                error_message=_normalize_optional_text(error_message),
                metadata=_normalize_mapping(metadata, field_name="metadata") if metadata is not _UNSET else {},
            ),
            session,
        )
        return {"sync_record": sync_record.model_dump(by_alias=True)}


def get_jd_progress(
    session_factory: sessionmaker[Session],
    *,
    job_description_id: str,
) -> dict[str, Any]:
    normalized_job_description_id = _normalize_required_text(job_description_id, field_name="job_description_id")
    with session_factory() as session:
        stats = build_job_description_funnel_stats(session, normalized_job_description_id)
        if stats is None:
            return {
                "job_description_id": normalized_job_description_id,
                "candidate_count": 0,
                "by_status": {},
                "with_contact": 0,
                "with_resume": 0,
                "with_ai_score": 0,
            }
        return {
            "job_description_id": normalized_job_description_id,
            "candidate_count": stats["applications"],
            "by_status": stats["by_status"],
            "with_contact": stats["with_contact"],
            "with_resume": stats["with_resume"],
            "with_ai_score": stats["with_ai_score"],
            "funnel": stats["steps"],
        }


def request_human_approval(
    session_factory: sessionmaker[Session],
    *,
    title: str,
    summary: str | None = None,
    action_kind: str | None = None,
    candidate_person_id: str | None = None,
    application_id: str | None = None,
    job_description_id: str | None = None,
    payload: Any = _UNSET,
) -> dict[str, Any]:
    _ = session_factory
    return {
        "status": "approved",
        "title": _normalize_required_text(title, field_name="title"),
        "summary": _normalize_optional_text(summary),
        "action_kind": _normalize_optional_text(action_kind) or "review_request",
        "candidate_person_id": _normalize_optional_text(candidate_person_id),
        "application_id": _normalize_optional_text(application_id),
        "job_description_id": _normalize_optional_text(job_description_id),
        "payload": _normalize_mapping(payload, field_name="payload") if payload is not _UNSET else {},
    }


def _active_lock(session: Session, application_id: str) -> CandidateAutonomousLock | None:
    stmt = (
        select(CandidateAutonomousLock)
        .where(
            CandidateAutonomousLock.application_id == application_id,
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


def _validate_mock_recruiting_site_exact_jd_fields(
    *,
    title: str,
    company_name: str | None,
    department: str | None,
    location: str | None,
    compensation_text: str | None,
    headcount: Any,
    platform: str | None,
    external_url: str | None,
    sync_metadata: dict[str, Any] | None,
) -> None:
    if platform != "mock_recruiting_site":
        return
    metadata = sync_metadata or {}
    if not _metadata_truthy(metadata.get("detail_complete")):
        return
    source_url = _normalize_optional_text(metadata.get("observed_detail_url")) or external_url
    if not source_url:
        raise ValueError("mock_recruiting_site JD sync requires observed_detail_url or external_url for exact-field validation")
    expected = _mock_recruiting_site_sync_json(source_url)
    provided = {
        "title": title,
        "company_name": company_name,
        "department": department,
        "location": location,
        "compensation_text": compensation_text,
        "headcount": headcount,
    }
    mismatches: list[str] = []
    for field_name, actual in provided.items():
        if actual is None:
            mismatches.append(f"{field_name}: missing, expected {expected.get(field_name)!r}")
            continue
        if str(actual).strip() != str(expected.get(field_name)).strip():
            mismatches.append(f"{field_name}: got {actual!r}, expected {expected.get(field_name)!r}")
    expected_path = _normalize_optional_text(expected.get("external_url_path"))
    if expected_path and external_url:
        actual_path = urlparse(external_url).path
        if actual_path != expected_path:
            mismatches.append(f"external_url_path: got {actual_path!r}, expected {expected_path!r}")
    if mismatches:
        raise ValueError(
            "mock_recruiting_site JD sync fields must exactly match the page sync-json before saving: "
            + "; ".join(mismatches)
        )


def _metadata_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _mock_recruiting_site_sync_json(source_url: str) -> dict[str, Any]:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("mock_recruiting_site exact-field validation only accepts localhost detail URLs")
    with urlopen(source_url, timeout=3) as response:
        body = response.read().decode("utf-8", errors="replace")
    match = re.search(
        r"<pre\b[^>]*class=[\"'][^\"']*\bsync-json\b[^\"']*[\"'][^>]*>(.*?)</pre>",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise ValueError("mock_recruiting_site detail page is missing sync-json exact-field evidence")
    payload = json.loads(html.unescape(match.group(1)).strip())
    if not isinstance(payload, dict):
        raise ValueError("mock_recruiting_site sync-json must be an object")
    return payload


def _serialize_lock(lock: CandidateAutonomousLock) -> dict[str, Any]:
    return {
        "id": lock.id,
        "application_id": lock.application_id,
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


def _find_matching_job_by_external_identity(
    session: Session,
    *,
    title: str,
    external_id: str,
    external_url: str | None,
) -> JobDescription | None:
    idx_model = JobDescriptionPlatformIdxRepository.model
    stmt = (
        select(idx_model)
        .where(idx_model.external_id == external_id)
        .order_by(idx_model.updated_at.desc(), idx_model.id.asc())
    )
    for idx in session.scalars(stmt).all():
        if external_url and idx.external_url and not _external_urls_compatible(idx.external_url, external_url):
            continue
        item = session.get(JobDescription, idx.job_description_id)
        if item is None or item.title != title:
            continue
        return item
    return None


def _find_matching_job(session: Session, *, title: str, department: str | None, location: str | None) -> JobDescription | None:
    stmt = select(JobDescription).where(JobDescription.title == title).order_by(
        JobDescription.updated_at.desc(),
        JobDescription.id.asc(),
    )
    candidates = []
    for item in session.scalars(stmt).all():
        if department and item.department and item.department != department:
            continue
        if location and item.location and item.location != location:
            continue
        score = 0
        if department and item.department == department:
            score += 2
        if location and item.location == location:
            score += 2
        if item.status == "active":
            score += 1
        candidates.append((score, item.updated_at, item.id, item))
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: (-candidate[0], -candidate[1], candidate[2]))
    return candidates[0][3]


def _external_urls_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    left_host = urlparse(left).netloc
    right_host = urlparse(right).netloc
    return bool(left_host and right_host and left_host == right_host)


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


def _serialize_candidate(
    session: Session,
    item,
    *,
    applications: list[Any] | None = None,
) -> dict[str, Any]:
    idx_repo = CandidatePlatformIdxRepository(session)
    platform_identities = []
    for idx in session.scalars(
        select(idx_repo.model)
        .where(idx_repo.model.candidate_id == item.id)
        .order_by(idx_repo.model.updated_at.desc(), idx_repo.model.id.asc())
    ).all():
        platform_identities.append(_serialize_candidate_platform_idx(idx))
    resolved_applications = applications
    if resolved_applications is None:
        resolved_applications = CandidateApplicationRepository(session).by_person(item.id, limit=100, offset=0)
    return {
        "candidate_person_id": item.candidate_person_id,
        "name": item.name,
        "platform": item.platform,
        "platform_candidate_id": item.platform_candidate_id,
        "contact_info": dict(item.contact_info or {}),
        "resume_path": item.resume_path,
        "online_resume_text": item.online_resume_text,
        "platform_identities": platform_identities,
        "applications": [_serialize_candidate_application(session, application) for application in resolved_applications],
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _serialize_candidate_platform_idx(item: CandidatePlatformIdx) -> dict[str, Any]:
    return {
        "platform": item.platform,
        "platform_candidate_person_id": item.platform_candidate_person_id,
        "profile_url": item.profile_url,
        "raw_profile": dict(item.raw_profile or {}),
        "first_seen_at": item.first_seen_at,
        "last_seen_at": item.last_seen_at,
    }


def _serialize_candidate_application(session: Session, item) -> dict[str, Any]:
    person = CandidateRepository(session).get_by_storage_id(item.person_id)
    job = JobDescriptionRepository(session).get_by_storage_id(item.job_description_id) if item.job_description_id else None
    application_metadata = dict(item.application_metadata or {})
    return {
        "application_id": item.candidate_application_id,
        "person_id": person.candidate_person_id if person is not None else item.person_id,
        "job_description_id": job.job_description_id if job is not None else None,
        "source_platform": item.source_platform or item.platform,
        "source_platform_candidate_person_id": item.source_platform_candidate_person_id,
        "platform_application_id": item.platform_application_id,
        "current_status": item.current_status,
        "current_stage_key": item.current_stage_key,
        "deepest_milestone": item.deepest_milestone,
        "state_snapshot": dict(item.state_snapshot or {}),
        "contact_snapshot": dict(item.contact_snapshot or {}),
        "resume_snapshot": dict(item.resume_snapshot or {}),
        "ai_scores": dict(item.ai_scores or {}),
        "ai_reasoning": item.ai_reasoning,
        "application_metadata": application_metadata,
        "source_observation": dict(application_metadata.get("source_observation") or {}),
        "application_window": item.application_window,
        "last_contacted_at": item.last_contacted_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _serialize_application_message(session: Session, item: ApplicationCommunicationLog) -> dict[str, Any]:
    application = CandidateApplicationRepository(session).get_by_storage_id(item.application_id)
    return {
        "message_id": item.candidate_application_message_id,
        "storage_id": item.id,
        "application_id": application.candidate_application_id if application is not None else item.application_id,
        "direction": item.direction,
        "content": item.content,
        "message_type": item.message_type,
        "platform": item.platform,
        "metadata": dict(item.message_metadata or {}),
        "timestamp": item.timestamp,
    }


def _message_outbound_sync_state(metadata: dict[str, Any]) -> dict[str, Any]:
    sync_state = metadata.get("outbound_sync")
    return dict(sync_state or {}) if isinstance(sync_state, dict) else {}


def _message_sync_is_pending(sync_state: dict[str, Any], *, destination: str | None = None) -> bool:
    local_sources = {"record_outbound_message", "recruit_station_thread"}
    if _normalize_optional_text(sync_state.get("source")) not in local_sources:
        return False
    final_statuses = {"synced", "sent", "acknowledged", "observed"}
    if destination:
        destination_state = dict(dict(sync_state.get("destinations") or {}).get(destination) or {})
        destination_status = _normalize_optional_text(destination_state.get("status"))
        if destination_status in final_statuses:
            return False
        return True
    return (_normalize_optional_text(sync_state.get("status")) or "pending") not in final_statuses


def _resolve_application_message(session: Session, message_id: str) -> ApplicationCommunicationLog:
    normalized_message_id = _normalize_required_text(message_id, field_name="message_id")
    repo = ApplicationCommunicationLogRepository(session)
    message = repo.get(normalized_message_id)
    if message is None:
        stmt = select(ApplicationCommunicationLog).where(
            ApplicationCommunicationLog.candidate_application_message_id == normalized_message_id
        )
        message = session.scalars(stmt).first()
    if message is None:
        raise KeyError(f"candidate application message {message_id} not found")
    return message


def _application_job_description_id(session: Session, application) -> str | None:
    if not application.job_description_id:
        return None
    job = JobDescriptionRepository(session).get_by_storage_id(application.job_description_id)
    return job.job_description_id if job is not None else None


def _resolve_application(
    session: Session,
    *,
    application_id: str | None = None,
    candidate_person_id: str | None = None,
    job_description_id: str | None = None,
):
    application_repo = CandidateApplicationRepository(session)
    normalized_application_id = _normalize_optional_text(application_id)
    if normalized_application_id:
        application = application_repo.get(normalized_application_id)
        if application is not None:
            return application
        raise KeyError(f"candidate application {normalized_application_id} not found")
    normalized_candidate_person_id = _normalize_optional_text(candidate_person_id)
    normalized_job_description_id = _normalize_optional_text(job_description_id)
    if normalized_candidate_person_id and normalized_job_description_id:
        canonical_window = make_application_window(normalized_candidate_person_id, normalized_job_description_id)
        application = application_repo.by_application_window(canonical_window)
        if application is not None:
            return application
        raise KeyError(f"candidate application window {canonical_window} not found")
    raise ValueError("application_id or candidate_person_id + job_description_id is required")


def _resume_snapshot_from_candidate(candidate) -> dict[str, Any]:
    available = bool(candidate.resume_path or candidate.online_resume_text)
    return {
        "available": available,
        "status": "received" if available else "not_received",
        "file_path": candidate.resume_path,
        "source": candidate.platform,
    }


def _normalize_application_state_input(
    session: Session,
    *,
    current_status: Any,
    current_stage_key: Any,
) -> tuple[str, str, dict[str, Any]]:
    known_statuses = set(available_state_statuses(session))
    requested_status = _normalize_optional_text(current_status) or "discovered"
    requested_stage = _normalize_optional_text(current_stage_key)

    if requested_status in known_statuses:
        normalized_status = requested_status
    elif requested_stage in known_statuses:
        normalized_status = requested_stage
    else:
        normalized_status = "discovered"

    normalized_stage = requested_stage if requested_stage in known_statuses else normalized_status
    source_state: dict[str, Any] = {}
    if requested_status != normalized_status:
        source_state["requested_current_status"] = requested_status
        source_state["normalized_current_status"] = normalized_status
    if requested_stage is not None and requested_stage != normalized_stage:
        source_state["requested_current_stage_key"] = requested_stage
        source_state["normalized_current_stage_key"] = normalized_stage
    return normalized_status, normalized_stage, source_state


def _align_state_snapshot(snapshot: dict[str, Any], *, status: str, stage_key: str) -> None:
    default_snapshot = default_candidate_state_snapshot(status=status, stage_key=stage_key)
    snapshot["current_stage_key"] = stage_key
    snapshot.setdefault("current_stage_label", default_snapshot["current_stage_label"])
    snapshot["next_recommended_stages"] = list(default_snapshot["next_recommended_stages"])
    snapshot.setdefault("snapshot_metadata", default_snapshot["snapshot_metadata"])


def _normalize_datetime(value: Any, *, field_name: str) -> datetime | None:
    if value in (None, "", _UNSET):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 datetime") from exc
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    raise ValueError(f"{field_name} must be a datetime-compatible value")


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
