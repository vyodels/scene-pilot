from __future__ import annotations

import json
from functools import lru_cache
import re
from typing import Any

from recruit_station.asset_paths import prompt_path
from sqlalchemy.orm import Session

from recruit_station.db.base import utcnow
from recruit_station.repositories import SkillRepository
from recruit_station.agent_runtime.types import LLMMessage, LLMRequest
from recruit_station.agent_runtime.providers import LLMProvider
from recruit_station.skills.contracts import validate_skill_contract


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


def _normalize_environment_scope(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized or "unspecified"


def _is_mock_environment_scope(environment_scope: str) -> bool:
    return _normalize_environment_scope(environment_scope) in {
        "mock",
        "mock_only",
        "simulated",
        "fixture",
        "test",
        "fixture_contract_regression",
    }


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


def build_skill_distill_review_payload(
    *,
    run_id: str,
    run_type: str | None,
    run_kind: str | None,
    engine_output_count: int,
    final_output: str | None,
    tool_activity: list[dict[str, Any]],
    event_outline: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "run_type": str(run_type or "").strip() or None,
        "run_kind": str(run_kind or "").strip() or None,
        "engine_output_count": max(int(engine_output_count or 0), 0),
        "final_output": str(final_output or "").strip() or None,
        "tool_activity": [dict(item) for item in tool_activity if isinstance(item, dict)],
        "event_outline": [dict(item) for item in event_outline if isinstance(item, dict)],
    }


def distill_skill_contract_from_run(
    *,
    provider: LLMProvider,
    review_payload: dict[str, Any],
    max_tokens: int = 2600,
) -> dict[str, Any]:
    prompt = _load_prompt("tasks/skill_distill_from_run")
    if not prompt:
        raise ValueError("skill distill prompt is missing")
    result = provider.invoke(
        LLMRequest(
            id="skill_distill",
            turn_id="skill_distill",
            invocation_id="skill_distill",
            messages=[
                LLMMessage(role="system", content=prompt),
                LLMMessage(role="user", content=json.dumps(review_payload, ensure_ascii=False, default=str)),
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
    )
    content = ""
    if result.response.assistant_message is not None and isinstance(result.response.assistant_message.content, str):
        content = result.response.assistant_message.content
    return _extract_skill_contract(content)


def _extract_skill_contract(content: str) -> dict[str, Any]:
    parsed = _parse_json_object(content)
    if not isinstance(parsed, dict):
        raise ValueError("skill distill response did not return a JSON object")
    nested = parsed.get("skill_contract")
    if isinstance(nested, dict):
        return dict(nested)
    return parsed


def _parse_json_object(content: str | None) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if not text:
        return None
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


@lru_cache(maxsize=8)
def _load_prompt(prompt_key: str) -> str:
    asset_path = prompt_path(prompt_key)
    if not asset_path.exists():
        return ""
    return asset_path.read_text(encoding="utf-8").strip()


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
    auto_activate: bool,
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
    contract = validate_skill_contract(_normalize_skill_contract(draft, fallback_title=fallback_title))

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

    incoming_body = dict(contract.get("body") or {})
    if not incoming_body:
        seed_body = contract.get("summary") or contract.get("description")
        if isinstance(seed_body, str) and seed_body.strip():
            incoming_body = {"summary": seed_body.strip()}

    incoming_execution_hints = dict(contract.get("execution_hints") or {})
    incoming_version_governance = dict(contract.get("version_governance") or {})
    incoming_health_check_config = dict(contract.get("health_check_config") or {})
    if not incoming_health_check_config:
        incoming_health_check_config = {"expected_result_status": "pass"}
    incoming_skill_metadata = dict(contract.get("skill_metadata") or contract.get("metadata") or {})
    environment_scope = _normalize_environment_scope(
        incoming_skill_metadata.get("environment_scope")
        or contract.get("environment_scope")
        or "unspecified"
    )
    status = "active" if auto_activate else "approved"
    platform = (
        str(contract.get("platform") or "").strip()
        or str(fallback_platform or "").strip()
        or str(incoming_execution_hints.get("domain") or "").strip()
        or "runtime-scene"
    )
    existing = repo.by_skill_id(skill_key)
    next_version = int(existing.version) + 1 if existing is not None else 1

    existing_strategy = dict(existing.strategy or {}) if existing is not None else {}
    existing_body = dict(existing.body or {}) if existing is not None else {}
    existing_execution_hints = dict(existing.execution_hints or {}) if existing is not None else {}
    existing_health_check_config = dict(existing.health_check_config or {}) if existing is not None else {}
    existing_skill_metadata = dict(existing.skill_metadata or {}) if existing is not None else {}
    existing_human_gate_policy = dict(existing.human_gate_policy or {}) if existing is not None else {}

    merged_strategy = {**existing_strategy, **incoming_strategy}
    if existing_strategy or incoming_strategy:
        merged_strategy["learned_patterns"] = _merge_sequence_field(existing_strategy, incoming_strategy, "learned_patterns")
        merged_strategy["observed_actions"] = _merge_sequence_field(existing_strategy, incoming_strategy, "observed_actions")

    merged_body = {**existing_body, **incoming_body}
    if existing_body or incoming_body:
        merged_body["checklist"] = _merge_sequence_field(existing_body, incoming_body, "checklist")
        merged_body["anti_patterns"] = _merge_sequence_field(existing_body, incoming_body, "anti_patterns")

    merged_execution_hints = {**existing_execution_hints, **incoming_execution_hints}
    if existing_execution_hints or incoming_execution_hints:
        merged_execution_hints["observed_outcomes"] = _merge_sequence_field(existing_execution_hints, incoming_execution_hints, "observed_outcomes")

    merged_skill_metadata = {**existing_skill_metadata, **incoming_skill_metadata}
    merged_skill_metadata["environment_scope"] = environment_scope
    merged_skill_metadata["test_skill"] = environment_scope != "real_site_verified"
    if _is_mock_environment_scope(environment_scope):
        merged_skill_metadata["not_for_real_site"] = True
        merged_skill_metadata["real_site_verified"] = False
    elif environment_scope == "real_site_verified":
        merged_skill_metadata["not_for_real_site"] = False
        merged_skill_metadata["real_site_verified"] = True
    else:
        merged_skill_metadata["real_site_verified"] = False
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

    existing_trigger_hint = str(existing.trigger_hint or "").strip() if existing is not None else ""
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
        "body": merged_body,
        "execution_hints": merged_execution_hints,
        "risk_level": str(contract.get("risk_level") or "medium"),
        "health_check_config": merged_health_check_config,
        "skill_metadata": merged_skill_metadata,
        "confirmed_by": reviewer,
        "confirmed_at": utcnow(),
        "last_health_status": reason or ("healthy" if status == "active" else "approved"),
        "trigger_hint": str(contract.get("trigger_hint") or existing_trigger_hint or skill_name),
        "requires_human_gate": bool(contract.get("requires_human_gate") or False),
        "human_gate_policy": {
            **existing_human_gate_policy,
            **dict(contract.get("human_gate_policy") or {}),
        },
    }

    skill = repo.update(existing, defaults) if existing is not None else repo.create(defaults)
    return {
        "id": skill.id,
        "skill_id": skill.skill_id,
        "name": skill.name,
        "status": skill.status,
        "version": skill.version,
    }
