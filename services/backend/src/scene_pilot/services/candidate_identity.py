from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from scene_pilot.db.base import utcnow
from scene_pilot.models import Candidate, CandidateApplication
from scene_pilot.repositories import CandidatePlatformIdxRepository, CandidateRepository


def normalize_phone(raw: str | None) -> str | None:
    text = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if not text:
        return None
    if text.startswith("86") and len(text) > 11:
        text = text[2:]
    return text or None


def normalize_wechat(raw: str | None) -> str | None:
    text = str(raw or "").strip().lower()
    return text or None


def normalize_email(raw: str | None) -> str | None:
    text = str(raw or "").strip().lower()
    return text or None


def extract_contact_identities(contact_info: dict[str, Any] | None) -> dict[str, str]:
    payload = dict(contact_info or {})
    identities: dict[str, str] = {}
    phone = normalize_phone(payload.get("phone") or payload.get("mobile"))
    wechat = normalize_wechat(payload.get("wechat"))
    email = normalize_email(payload.get("email"))
    if phone:
        identities["phone"] = phone
    if wechat:
        identities["wechat"] = wechat
    if email:
        identities["email"] = email
    return identities


def contact_channels_from_info(contact_info: dict[str, Any] | None) -> list[str]:
    identities = extract_contact_identities(contact_info)
    ordered = [channel for channel in ("phone", "wechat", "email") if channel in identities]
    return ordered


def canonicalize_contact_info(contact_info: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(contact_info or {})
    identities = extract_contact_identities(payload)
    if identities.get("phone"):
        payload["phone"] = identities["phone"]
        payload["has_phone"] = True
    if identities.get("wechat"):
        payload["wechat"] = identities["wechat"]
        payload["has_wechat"] = True
    if identities.get("email"):
        payload["email"] = identities["email"]
        payload["has_email"] = True
    payload["channels"] = contact_channels_from_info(payload)
    return payload


def merge_contact_info(target: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(target or {})
    for key, value in dict(patch or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return canonicalize_contact_info(merged)


def _candidate_matches_identities(candidate: Candidate, identities: dict[str, str]) -> bool:
    current = extract_contact_identities(dict(candidate.contact_info or {}))
    return any(current.get(key) == value for key, value in identities.items())


def resolve_candidate_by_contact_info(
    session: Session,
    *,
    contact_info: dict[str, Any] | None,
    exclude_candidate_id: str | None = None,
) -> Candidate | None:
    identities = extract_contact_identities(contact_info)
    if not identities:
        return None
    repo = CandidateRepository(session)
    for candidate in repo.list(limit=5000, offset=0):
        if exclude_candidate_id and candidate.id == exclude_candidate_id:
            continue
        if _candidate_matches_identities(candidate, identities):
            return candidate
    return None


def resolve_candidate_by_platform_identity(
    session: Session,
    *,
    platform: str,
    platform_candidate_id: str,
) -> Candidate | None:
    platform_key = str(platform or "").strip()
    platform_identity = str(platform_candidate_id or "").strip()
    if not platform_key or not platform_identity:
        return None
    idx = CandidatePlatformIdxRepository(session).by_platform_identity(platform_key, platform_identity)
    if idx is not None:
        candidate = CandidateRepository(session).get_by_storage_id(idx.candidate_id)
        if candidate is not None:
            return candidate
    return CandidateRepository(session).by_platform_candidate_id(platform_key, platform_identity)


def relink_application_person_by_contact_info(
    session: Session,
    *,
    application: CandidateApplication,
    current_candidate: Candidate,
    contact_info: dict[str, Any] | None,
) -> Candidate:
    merged_current = merge_contact_info(dict(current_candidate.contact_info or {}), contact_info)
    current_candidate.contact_info = merged_current

    matched = resolve_candidate_by_contact_info(
        session,
        contact_info=contact_info,
        exclude_candidate_id=current_candidate.id,
    )
    if matched is None:
        return current_candidate

    matched.contact_info = merge_contact_info(dict(matched.contact_info or {}), merged_current)
    application.person_id = matched.id
    application.updated_at = utcnow()
    session.flush()
    return matched
