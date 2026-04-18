from __future__ import annotations

from typing import Any

from scene_pilot.models.domain import Skill


def execute_skill(skill: Skill, payload: dict[str, Any]) -> dict[str, Any]:
    return {"skill_id": skill.skill_id, "payload": payload, "strategy": dict(skill.strategy or {})}
