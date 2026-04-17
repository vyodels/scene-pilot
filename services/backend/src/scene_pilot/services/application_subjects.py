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
    ai_scores = dict(getattr(application, "ai_scores", None) or {})
    application_id = str(
        getattr(application, "candidate_application_id", None) or getattr(application, "id", "") or ""
    ).strip()
    person_id = str(
        getattr(person, "candidate_person_id", None) or getattr(application, "person_id", "") or ""
    ).strip() or None
    job_description_id = str(
        getattr(job_description, "job_description_id", None) or getattr(application, "job_description_id", "") or ""
    ).strip() or None
    return {
        "id": application_id,
        "application_id": application_id,
        "person_id": person_id,
        "person": {
            "person_id": person_id,
            "platform_candidate_id": str(getattr(person, "platform_candidate_id", None) or "") or None,
            "name": str(getattr(person, "name", "") or ""),
            "title": str(contact_info.get("title", "候选人") or "候选人"),
            "location": str(contact_info.get("location", "未知") or "未知"),
            "experience_years": int(contact_info.get("experience_years", 0) or 0),
            "tags": list(contact_info.get("tags", []) or []),
            "contact_info": contact_info,
        },
        "job_description": {
            "job_description_id": job_description_id,
            "title": str(getattr(job_description, "title", None) or job_description_id or "未分配岗位"),
        },
        "platform": str(getattr(application, "platform", None) or getattr(person, "platform", None) or "site"),
        "current_status": str(getattr(application, "current_status", None) or "discovered"),
        "stage_key": str(
            getattr(application, "current_stage_key", None)
            or getattr(application, "current_status", None)
            or "discovered"
        ),
        "deepest_milestone": str(getattr(application, "deepest_milestone", None) or "") or None,
        "job_description_id": job_description_id,
        "match_score": int(ai_scores.get("overall", 0) or 0),
        "next_action": str(contact_info.get("next_action", "查看申请并决定下一步动作。") or "查看申请并决定下一步动作。"),
        "summary": str(
            getattr(application, "ai_reasoning", None)
            or getattr(person, "online_resume_text", None)
            or "申请档案正在等待审查。"
        ),
        "resume_available": bool(getattr(person, "resume_path", None) or getattr(person, "online_resume_text", None)),
        "state_snapshot": state_snapshot,
        "ai_scores": ai_scores,
        "ai_reasoning": str(getattr(application, "ai_reasoning", None) or "") or None,
        "cooldown_until": getattr(application, "cooldown_until", None),
        "last_contacted_at": getattr(application, "last_contacted_at", None),
        "created_at": getattr(application, "created_at", None),
        "updated_at": getattr(application, "updated_at", None),
    }
