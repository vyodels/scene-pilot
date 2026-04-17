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
    application_id = str(getattr(application, "id", "") or "").strip()
    person_id = str(getattr(application, "person_id", "") or "").strip() or None
    job_description_id = str(getattr(application, "job_description_id", "") or "").strip() or None
    return {
        "application_id": application_id,
        "candidate_id": application_id,
        "person_id": person_id,
        "name": str(getattr(person, "name", "") or ""),
        "platform": str(getattr(application, "platform", None) or getattr(person, "platform", None) or "site"),
        "platform_candidate_id": str(getattr(person, "platform_candidate_id", None) or "") or None,
        "current_status": str(getattr(application, "current_status", None) or "discovered"),
        "stage_key": str(
            getattr(application, "current_stage_key", None)
            or getattr(application, "current_status", None)
            or "discovered"
        ),
        "job_description_id": job_description_id,
        "job_description_title": str(getattr(job_description, "title", None) or job_description_id or "未分配岗位"),
        "match_score": int(ai_scores.get("overall", 0) or 0),
        "experience_years": int(contact_info.get("experience_years", 0) or 0),
        "next_action": str(contact_info.get("next_action", "查看申请并决定下一步动作。") or "查看申请并决定下一步动作。"),
        "summary": str(
            getattr(application, "ai_reasoning", None)
            or getattr(person, "online_resume_text", None)
            or "申请档案正在等待审查。"
        ),
        "location": str(contact_info.get("location", "未知") or "未知"),
        "tags": list(contact_info.get("tags", []) or []),
        "resume_available": bool(getattr(person, "resume_path", None) or getattr(person, "online_resume_text", None)),
        "state_snapshot": state_snapshot,
        "contact_info": contact_info,
        "ai_scores": ai_scores,
        "cooldown_until": getattr(application, "cooldown_until", None),
        "last_contacted_at": getattr(application, "last_contacted_at", None),
        "created_at": getattr(application, "created_at", None),
        "updated_at": getattr(application, "updated_at", None),
    }
