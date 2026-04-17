from __future__ import annotations

from typing import Any


def application_payload_from_application(
    application: Any,
    *,
    person: Any | None = None,
    job_description: Any | None = None,
) -> dict[str, Any]:
    contact_info = dict(getattr(person, "contact_info", None) or {})
    state_snapshot = dict(getattr(application, "state_snapshot", None) or {})
    application_metadata = dict(getattr(application, "application_metadata", None) or {})
    ai_scores = dict(getattr(application, "ai_scores", None) or {})
    application_id = str(getattr(application, "candidate_application_id", None) or getattr(application, "id", "") or "").strip()
    person_id = str(getattr(person, "candidate_person_id", None) or getattr(application, "person_id", "") or "").strip() or None
    job_description_id = str(getattr(job_description, "job_description_id", None) or getattr(application, "job_description_id", "") or "").strip() or None
    summary = str(
        getattr(application, "ai_reasoning", None)
        or state_snapshot.get("latest_note")
        or application_metadata.get("summary")
        or application_metadata.get("resume_summary")
        or "申请档案正在等待审查。"
    ).strip()
    resume_snapshot = dict(
        application_metadata.get("resume_snapshot")
        or state_snapshot.get("resume_snapshot")
        or {}
    )
    resume_status = str(
        application_metadata.get("resume_status")
        or state_snapshot.get("resume_status")
        or resume_snapshot.get("status")
        or ""
    ).strip().lower()
    resume_available = bool(
        application_metadata.get("resume_available")
        or state_snapshot.get("resume_available")
        or resume_snapshot.get("available")
        or resume_snapshot.get("is_available")
        or resume_status in {"received", "available", "ready", "present"}
    )

    person_payload = {
        "person_id": person_id,
        "name": str(getattr(person, "name", "") or ""),
        "title": str(contact_info.get("title", "候选人") or "候选人"),
        "location": str(contact_info.get("location", "未知") or "未知"),
        "experience_years": int(contact_info.get("experience_years", 0) or 0),
        "tags": list(contact_info.get("tags", []) or []),
        "contact_info": contact_info,
    }
    application_payload = {
        "application_id": application_id,
        "person_id": person_id,
        "platform": str(
            getattr(application, "source_platform", None)
            or getattr(application, "platform", None)
            or "site"
        ),
        "current_status": str(getattr(application, "current_status", None) or "discovered"),
        "stage_key": str(getattr(application, "current_stage_key", None) or getattr(application, "current_status", None) or "discovered"),
        "deepest_milestone": str(getattr(application, "deepest_milestone", None) or "") or None,
        "job_description_id": job_description_id,
        "source_platform_candidate_person_id": str(
            getattr(application, "source_platform_candidate_person_id", None) or ""
        ).strip()
        or None,
        "state_snapshot": state_snapshot,
        "ai_scores": ai_scores,
        "ai_reasoning": str(getattr(application, "ai_reasoning", None) or "") or None,
        "cooldown_until": getattr(application, "cooldown_until", None),
        "last_contacted_at": getattr(application, "last_contacted_at", None),
        "application_metadata": dict(getattr(application, "application_metadata", None) or {}),
        "resume_available": resume_available,
    }
    job_description_payload = {
        "job_description_id": job_description_id,
        "title": str(getattr(job_description, "title", None) or job_description_id or "未分配岗位"),
    }
    return {
        "id": application_id,
        "application_id": application_id,
        "person_id": person_id,
        "job_description_id": job_description_id,
        "person": person_payload,
        "application": application_payload,
        "job_description": job_description_payload,
        "platform": application_payload["platform"],
        "current_status": application_payload["current_status"],
        "stage_key": application_payload["stage_key"],
        "deepest_milestone": application_payload["deepest_milestone"],
        "match_score": int(ai_scores.get("overall", 0) or 0),
        "next_action": str(contact_info.get("next_action", "查看申请并决定下一步动作。") or "查看申请并决定下一步动作。"),
        "summary": summary,
        "resume_available": resume_available,
        "state_snapshot": state_snapshot,
        "ai_scores": ai_scores,
        "ai_reasoning": application_payload["ai_reasoning"],
        "cooldown_until": application_payload["cooldown_until"],
        "last_contacted_at": application_payload["last_contacted_at"],
        "created_at": getattr(application, "created_at", None),
        "updated_at": getattr(application, "updated_at", None),
    }
