from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from scene_pilot.db.base import utcnow
from scene_pilot.repositories import SkillRepository
from scene_pilot.services.feature_flags import FeatureFlagService


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return normalized.strip("_")


def _dedupe_sequence(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    deduped: list[Any] = []
    for value in values:
        marker = repr(value)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(value)
    return deduped


def _merge_sequence_field(existing: dict[str, Any], incoming: dict[str, Any], field_name: str) -> list[Any]:
    merged = list(existing.get(field_name) or []) + list(incoming.get(field_name) or [])
    return _dedupe_sequence(merged)[-20:]


def _normalize_skill_contract(draft: dict[str, Any], *, fallback_title: str) -> dict[str, Any]:
    contract = draft.get("skill_contract")
    if isinstance(contract, dict):
        normalized = dict(contract)
        if "skill_metadata" not in normalized and isinstance(draft.get("artifact_metadata"), dict):
            normalized["skill_metadata"] = dict(draft.get("artifact_metadata") or {})
        return normalized

    normalized = dict(draft)
    normalized.setdefault("name", fallback_title)
    return normalized


def resolve_promoted_skill_snapshot(payload: dict[str, Any] | None) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    promoted = payload.get("promoted_skill")
    if not isinstance(promoted, dict):
        return None
    promoted_id = str(promoted.get("id") or "").strip()
    if not promoted_id:
        return None
    return {
        "id": promoted_id,
        "skill_id": str(promoted.get("skill_id") or "").strip() or None,
        "name": str(promoted.get("name") or "").strip() or None,
        "status": str(promoted.get("status") or "").strip() or None,
        "version": int(promoted.get("version") or 0),
    }


def promote_skill_draft_contract(
    session: Session,
    *,
    flags: FeatureFlagService,
    draft: dict[str, Any],
    reviewer: str | None,
    reason: str | None,
    fallback_title: str,
    fallback_platform: str | None = None,
    fallback_stage: str | None = None,
    learning_id: str | None = None,
    promotion_source: str = "evolution_artifact",
    source_kind: str | None = None,
    source_id: str | None = None,
) -> dict[str, object]:
    repo = SkillRepository(session)
    contract = _normalize_skill_contract(draft, fallback_title=fallback_title)

    skill_name = str(contract.get("skill_name") or contract.get("name") or fallback_title).strip()
    skill_key = str(contract.get("skill_id") or _slugify(skill_name)).strip("_")
    if learning_id and not contract.get("skill_id"):
        skill_key = f"{skill_key}_{learning_id[:8]}"
    skill_key = skill_key or f"runtime_skill_{fallback_title[:8].strip() or 'draft'}"

    incoming_strategy = dict(contract.get("strategy") or {})
    if not incoming_strategy:
        seed_instruction = contract.get("content") or contract.get("summary") or contract.get("description")
        if isinstance(seed_instruction, str) and seed_instruction.strip():
            incoming_strategy = {"instruction": seed_instruction.strip()}

    incoming_execution_hints = dict(contract.get("execution_hints") or {})
    incoming_version_governance = dict(contract.get("version_governance") or {})
    incoming_health_check_config = dict(contract.get("health_check_config") or {})
    if not incoming_health_check_config:
        incoming_health_check_config = {"expected_result_status": "pass"}
    incoming_skill_metadata = dict(contract.get("skill_metadata") or contract.get("metadata") or {})

    status = "active" if flags.is_enabled("skills.auto_activate") else "approved"
    platform = (
        str(contract.get("platform") or "").strip()
        or str(fallback_platform or "").strip()
        or str(incoming_execution_hints.get("domain") or "").strip()
        or "runtime-scene"
    )
    existing = repo.by_skill_id(skill_key)
    next_version = int(existing.version) + 1 if existing is not None else 1

    existing_strategy = dict(existing.strategy or {}) if existing is not None else {}
    existing_execution_hints = dict(existing.execution_hints or {}) if existing is not None else {}
    existing_health_check_config = dict(existing.health_check_config or {}) if existing is not None else {}
    existing_skill_metadata = dict(existing.skill_metadata or {}) if existing is not None else {}

    merged_strategy = {**existing_strategy, **incoming_strategy}
    if existing_strategy or incoming_strategy:
        merged_strategy["learned_patterns"] = _merge_sequence_field(existing_strategy, incoming_strategy, "learned_patterns")
        merged_strategy["observed_actions"] = _merge_sequence_field(existing_strategy, incoming_strategy, "observed_actions")

    merged_execution_hints = {**existing_execution_hints, **incoming_execution_hints}
    if existing_execution_hints or incoming_execution_hints:
        merged_execution_hints["observed_outcomes"] = _merge_sequence_field(existing_execution_hints, incoming_execution_hints, "observed_outcomes")

    merged_skill_metadata = {**existing_skill_metadata, **incoming_skill_metadata}
    merged_skill_metadata["promotion_source"] = promotion_source
    if source_kind:
        merged_skill_metadata["promotion_source_kind"] = source_kind
    if source_id:
        merged_skill_metadata["promotion_source_id"] = source_id

    governance_payload = {
        **incoming_version_governance,
        "approved_by": reviewer,
        "approved_reason": reason,
        "approved_at": utcnow().isoformat(),
        "skill_version": next_version,
        "promotion_source": promotion_source,
        "promotion_source_kind": source_kind,
        "promotion_source_id": source_id,
    }
    merged_strategy["version_governance"] = {
        **dict(existing_strategy.get("version_governance") or {}),
        **dict(incoming_strategy.get("version_governance") or {}),
        **governance_payload,
    }
    merged_execution_hints["version_governance"] = {
        **dict(existing_execution_hints.get("version_governance") or {}),
        **dict(incoming_execution_hints.get("version_governance") or {}),
        **governance_payload,
    }
    merged_health_check_config = {
        **existing_health_check_config,
        **incoming_health_check_config,
        "version_governance": {
            **dict(existing_health_check_config.get("version_governance") or {}),
            **dict(incoming_health_check_config.get("version_governance") or {}),
            **governance_payload,
        },
    }
    merged_skill_metadata["version_governance"] = {
        **dict(existing_skill_metadata.get("version_governance") or {}),
        **dict(incoming_skill_metadata.get("version_governance") or {}),
        **governance_payload,
    }

    defaults = {
        "skill_id": skill_key,
        "name": skill_name,
        "description": contract.get("description"),
        "category": str(contract.get("category") or "general"),
        "version": next_version,
        "status": status,
        "platform": platform,
        "bound_to_stage": contract.get("bound_to_stage") or fallback_stage,
        "input_schema": dict(contract.get("input_schema") or {}),
        "output_schema": dict(contract.get("output_schema") or {}),
        "strategy": merged_strategy,
        "execution_hints": merged_execution_hints,
        "risk_level": str(contract.get("risk_level") or "medium"),
        "health_check_config": merged_health_check_config,
        "skill_metadata": merged_skill_metadata,
        "confirmed_by": reviewer,
        "confirmed_at": utcnow(),
        "last_health_status": reason or ("healthy" if status == "active" else "approved"),
    }

    skill = repo.update(existing, defaults) if existing is not None else repo.create(defaults)
    return {
        "id": skill.id,
        "skill_id": skill.skill_id,
        "name": skill.name,
        "status": skill.status,
        "version": skill.version,
    }
