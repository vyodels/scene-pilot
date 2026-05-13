from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from recruit_agent.repositories import CandidateApplicationRepository, JobDescriptionRepository
from recruit_agent.services.state_machine import ensure_latest_state_machine


FUNNEL_STAGE_DEFINITIONS = (
    ("applications", "投递"),
    ("communicating", "在线简历"),
    ("interviewing", "面试中"),
    ("offers", "Offer中"),
    ("hired", "入职"),
)

PHASE_DEPTH = {
    "A": 10,
    "B": 20,
    "C": 30,
    "D": 40,
    "E": 50,
    "F": 60,
    "G": 70,
    "H": 80,
}


def build_job_description_funnel_stats(session: Session, job_description_id: str) -> dict[str, Any] | None:
    job = JobDescriptionRepository(session).get(job_description_id)
    if job is None:
        return None
    applications = CandidateApplicationRepository(session).by_job_description_storage_id(job.id, limit=5000, offset=0)
    state_machine = ensure_latest_state_machine(session)
    node_by_id = {
        str(node.get("id")): dict(node)
        for node in state_machine.get("nodes", [])
        if node.get("id")
    }
    milestone_depths = _milestone_depths(node_by_id)

    counts = {
        "applications": len(applications),
        "communicating": 0,
        "interviewing": 0,
        "offers": 0,
        "hired": 0,
    }
    with_contact = 0
    with_resume = 0
    with_ai_score = 0
    by_status: Counter[str] = Counter()

    for application in applications:
        current_status = str(getattr(application, "current_status", None) or "").strip()
        if current_status:
            by_status[current_status] += 1
        depth = _application_depth(application, node_by_id=node_by_id, milestone_depths=milestone_depths)
        if depth >= PHASE_DEPTH["B"]:
            counts["communicating"] += 1
        if depth >= PHASE_DEPTH["G"]:
            counts["interviewing"] += 1
        if depth >= PHASE_DEPTH["H"]:
            counts["offers"] += 1
        if current_status == "offer_accepted" or str(getattr(application, "deepest_milestone", None) or "").strip() == "M19":
            counts["hired"] += 1
        contact_snapshot = dict(getattr(application, "contact_snapshot", None) or {})
        resume_snapshot = dict(getattr(application, "resume_snapshot", None) or {})
        ai_scores = dict(getattr(application, "ai_scores", None) or {})
        if contact_snapshot:
            with_contact += 1
        if resume_snapshot.get("available") or resume_snapshot.get("file_path") or resume_snapshot.get("filePath"):
            with_resume += 1
        if ai_scores.get("overall") is not None or ai_scores.get("decision"):
            with_ai_score += 1

    total = counts["applications"]
    return {
        "job_description_id": job.job_description_id,
        "steps": [
            {
                "key": key,
                "label": label,
                "value": counts[key],
                "percent": _percent(counts[key], total),
            }
            for key, label in FUNNEL_STAGE_DEFINITIONS
        ],
        "applications": counts["applications"],
        "communicating": counts["communicating"],
        "interviewing": counts["interviewing"],
        "offers": counts["offers"],
        "hired": counts["hired"],
        "with_contact": with_contact,
        "with_resume": with_resume,
        "with_ai_score": with_ai_score,
        "by_status": dict(by_status),
    }


def _milestone_depths(node_by_id: dict[str, dict[str, Any]]) -> dict[str, int]:
    depths: dict[str, int] = {}
    for node in node_by_id.values():
        milestone_id = str(node.get("milestoneId") or node.get("milestone_id") or "").strip()
        phase = str(node.get("phase") or "").strip().upper()
        if not milestone_id or phase == "I":
            continue
        phase_depth = PHASE_DEPTH.get(phase, -1)
        if phase_depth >= 0:
            depths[milestone_id] = max(depths.get(milestone_id, -1), phase_depth)
    return depths


def _application_depth(application: Any, *, node_by_id: dict[str, dict[str, Any]], milestone_depths: dict[str, int]) -> int:
    current_status = str(getattr(application, "current_status", None) or "").strip()
    current_node = node_by_id.get(current_status) or {}
    current_phase = str(current_node.get("phase") or "").strip().upper()
    current_depth = PHASE_DEPTH.get(current_phase, -1) if current_phase != "I" else -1
    deepest_milestone = str(getattr(application, "deepest_milestone", None) or "").strip()
    deepest_depth = milestone_depths.get(deepest_milestone, -1)
    return max(current_depth, deepest_depth)


def _percent(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((value / total) * 1000) / 10
