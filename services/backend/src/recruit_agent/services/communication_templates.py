from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from recruit_agent.asset_paths import communication_templates_root
from recruit_agent.repositories import CandidateApplicationRepository, CandidateRepository, JobDescriptionRepository


VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


@lru_cache(maxsize=1)
def list_communication_templates() -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    root = communication_templates_root()
    for path in sorted(root.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for item in payload if isinstance(payload, list) else []:
            if isinstance(item, dict):
                templates.append(_normalize_template(item))
    return templates


def get_communication_template(template_id: str) -> dict[str, Any] | None:
    normalized = str(template_id or "").strip()
    return next((template for template in list_communication_templates() if template["template_id"] == normalized), None)


def render_communication_template(
    session: Session,
    *,
    template_id: str,
    application_id: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    template = get_communication_template(template_id)
    if template is None:
        return None
    context = _application_template_context(session, application_id)
    if context is None:
        return None
    merged_context = {**context, **{key: _string_value(value) for key, value in dict(variables or {}).items()}}
    missing_variables = [
        variable
        for variable in template["variables"]
        if not str(merged_context.get(variable) or "").strip()
    ]
    content = VARIABLE_PATTERN.sub(lambda match: str(merged_context.get(match.group(1)) or ""), template["body"]).strip()
    return {
        "template_id": template["template_id"],
        "name": template["name"],
        "category": template["category"],
        "message_type": template["message_type"],
        "content": content,
        "missing_variables": missing_variables,
    }


def _normalize_template(item: dict[str, Any]) -> dict[str, Any]:
    template_id = str(item.get("templateId") or item.get("template_id") or "").strip()
    variables = [
        str(variable).strip()
        for variable in list(item.get("variables") or [])
        if str(variable).strip()
    ]
    if not template_id:
        raise ValueError("communication template missing templateId")
    return {
        "template_id": template_id,
        "name": str(item.get("name") or template_id).strip(),
        "category": str(item.get("category") or "general").strip(),
        "message_type": str(item.get("messageType") or item.get("message_type") or "text").strip(),
        "body": str(item.get("body") or "").strip(),
        "variables": variables,
        "status": str(item.get("status") or "active").strip(),
    }


def _application_template_context(session: Session, application_id: str) -> dict[str, str] | None:
    application = CandidateApplicationRepository(session).get(application_id)
    if application is None:
        return None
    person = CandidateRepository(session).get_by_storage_id(application.person_id)
    job = JobDescriptionRepository(session).get_by_storage_id(application.job_description_id) if application.job_description_id else None
    person_contact = dict(getattr(person, "contact_info", None) or {})
    person_tags = [str(item).strip() for item in list(person_contact.get("tags") or []) if str(item).strip()]
    person_title = _string_value(person_contact.get("title"))
    job_company = _string_value(getattr(job, "company_name", None))
    job_location = _string_value(getattr(job, "location", None))
    compensation = _string_value(getattr(job, "compensation_text", None))
    return {
        "personName": _string_value(getattr(person, "name", None)),
        "personTitle": person_title,
        "personLocation": _string_value(person_contact.get("location")),
        "personTagLine": "、".join(person_tags[:2]) or person_title,
        "jobTitle": _string_value(getattr(job, "title", None)),
        "jobCompanyName": job_company,
        "jobLocation": job_location,
        "jobCompensationText": compensation,
        "jobCompanyLine": f"，公司 {job_company}" if job_company else "",
        "jobLocationLine": f"，地点 {job_location}" if job_location else "",
        "jobCompensationLine": f"，薪资 {compensation}" if compensation else "",
    }


def _string_value(value: Any) -> str:
    return str(value).strip() if value is not None else ""
