from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from recruit_agent.evolution.promotion import PromotionService
from recruit_agent.evolution.queue import EvolutionQueue


def build_router(*, queue: EvolutionQueue, promotion: PromotionService) -> APIRouter:
    router = APIRouter(prefix="/api/evolution", tags=["evolution"])

    @router.get("/queue")
    def list_queue(status: str = "pending_review") -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "title": item.title,
                "status": item.status,
                "artifact_kind": item.artifact_kind,
                "related_skill_id": item.related_skill_id,
                "metadata": dict(item.artifact_metadata or {}),
            }
            for item in queue.list_pending(status=status)
        ]

    @router.post("/queue/{artifact_id}/approve")
    def approve_queue_item(artifact_id: str) -> dict[str, Any]:
        item = queue.approve(artifact_id)
        return {
            "id": item.id,
            "status": item.status,
            "artifact_kind": item.artifact_kind,
            "metadata": dict(item.artifact_metadata or {}),
        }

    @router.post("/queue/{artifact_id}/reject")
    def reject_queue_item(artifact_id: str) -> dict[str, Any]:
        item = queue.reject(artifact_id)
        return {
            "id": item.id,
            "status": item.status,
            "artifact_kind": item.artifact_kind,
            "metadata": dict(item.artifact_metadata or {}),
        }

    @router.get("/skills")
    def list_skills(status: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "id": skill.id,
                "name": skill.name,
                "status": skill.status,
                "trial_metrics": dict(skill.trial_metrics or {}),
            }
            for skill in promotion.list_skills(status=status)
        ]

    @router.post("/skills/{skill_id}/promote")
    def promote_skill(skill_id: str) -> dict[str, Any]:
        skill = promotion.promote_skill(skill_id)
        return {
            "id": skill.id,
            "status": skill.status,
            "trial_metrics": dict(skill.trial_metrics or {}),
        }

    return router
