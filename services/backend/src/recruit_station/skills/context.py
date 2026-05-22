from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
import json
from typing import Any

from recruit_station.models.domain import Skill
from recruit_station.skills.contracts import skill_asset_manifest

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
_ACTIVE_CONTEXT_STATUSES = {"active", "trial"}


@dataclass(frozen=True, slots=True)
class SkillContextInjection:
    skill_id: str
    name: str
    description: str | None
    trigger_hint: str | None
    category: str
    platform: str
    version: int
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    instructions: str | None
    metadata: dict[str, Any]
    execution: dict[str, Any]

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "skill_id": self.skill_id,
            "name": self.name,
            "category": self.category,
            "platform": self.platform,
            "version": self.version,
        }
        if self.description:
            payload["description"] = self.description
        if self.trigger_hint:
            payload["trigger_hint"] = self.trigger_hint
        if self.instructions:
            payload["instructions"] = self.instructions
        if self.input_schema:
            payload["input_schema"] = self.input_schema
        if self.output_schema:
            payload["output_schema"] = self.output_schema
        if self.metadata:
            payload["metadata"] = self.metadata
        if self.execution:
            payload["execution"] = self.execution
        return payload


def build_skill_context_injections(
    skills: list[Skill],
    *,
    limit: int = 12,
    token_budget: int | None = None,
    max_instruction_chars: int = 1200,
    max_schema_chars: int = 1200,
    query: str | None = None,
    task_text: str | None = None,
    category: str | None = None,
    explicit_skill_ids: Sequence[str] | None = None,
) -> list[SkillContextInjection]:
    active_skills = [
        skill
        for skill in skills
        if str(skill.status or "").strip() in _ACTIVE_CONTEXT_STATUSES
    ]
    if not _has_relevance_input(
        query=query,
        task_text=task_text,
        category=category,
        explicit_skill_ids=explicit_skill_ids,
    ):
        selected = sorted(active_skills, key=_stable_skill_key)
        return _budgeted_injections(
            selected[: max(limit, 0)],
            token_budget=token_budget,
            max_instruction_chars=max_instruction_chars,
            max_schema_chars=max_schema_chars,
        )

    relevance = _SkillRelevanceInput.from_values(
        query=query,
        task_text=task_text,
        category=category,
        explicit_skill_ids=explicit_skill_ids,
    )
    selected = sorted(
        active_skills,
        key=lambda skill: _relevant_skill_key(skill, relevance),
    )
    return _budgeted_injections(
        selected[: max(limit, 0)],
        token_budget=token_budget,
        max_instruction_chars=max_instruction_chars,
        max_schema_chars=max_schema_chars,
    )


def _skill_context_injection(
    skill: Skill,
    *,
    max_instruction_chars: int = 1200,
    max_schema_chars: int = 1200,
) -> SkillContextInjection:
    body = dict(skill.body or {})
    execution_hints = dict(skill.execution_hints or {})
    return SkillContextInjection(
        skill_id=str(skill.skill_id or ""),
        name=str(skill.name or ""),
        description=skill.description,
        trigger_hint=skill.trigger_hint,
        category=str(skill.category or "general"),
        platform=str(skill.platform or "site"),
        version=int(skill.version or 1),
        input_schema=_truncate_mapping(dict(skill.input_schema or {}), max_chars=max_schema_chars),
        output_schema=_truncate_mapping(dict(skill.output_schema or {}), max_chars=max_schema_chars),
        instructions=_truncate_text(_skill_instructions(body), max_chars=max_instruction_chars),
        metadata=_context_metadata(skill),
        execution=_context_execution(skill, body=body, execution_hints=execution_hints),
    )


def _budgeted_injections(
    skills: list[Skill],
    *,
    token_budget: int | None,
    max_instruction_chars: int,
    max_schema_chars: int,
) -> list[SkillContextInjection]:
    budget = int(token_budget or 0)
    if budget <= 0:
        return [
            _skill_context_injection(
                skill,
                max_instruction_chars=max_instruction_chars,
                max_schema_chars=max_schema_chars,
            )
            for skill in skills
        ]
    selected: list[SkillContextInjection] = []
    spent = 0
    for skill in skills:
        injection = _skill_context_injection(
            skill,
            max_instruction_chars=max_instruction_chars,
            max_schema_chars=max_schema_chars,
        )
        estimate = _token_estimate(injection.to_prompt_payload())
        if selected and spent + estimate > budget:
            continue
        if not selected and estimate > budget:
            injection = _skill_context_injection(
                skill,
                max_instruction_chars=max(160, min(max_instruction_chars, budget * 2)),
                max_schema_chars=max(160, min(max_schema_chars, budget * 2)),
            )
            estimate = _token_estimate(injection.to_prompt_payload())
        selected.append(injection)
        spent += estimate
    return selected


def _skill_instructions(body: dict[str, Any]) -> str | None:
    for key in ("instructions", "summary", "content", "prompt"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _context_metadata(skill: Skill) -> dict[str, Any]:
    metadata = dict(skill.skill_metadata or {})
    allowed_keys = {
        "environment_scope",
        "not_for_real_site",
        "real_site_verified",
        "test_skill",
        "source_kind",
        "trigger_examples",
    }
    return {key: metadata[key] for key in sorted(allowed_keys) if key in metadata}


def _context_execution(skill: Skill, *, body: dict[str, Any], execution_hints: dict[str, Any]) -> dict[str, Any]:
    manifest = skill_asset_manifest(body, execution_hints)
    if skill.last_health_status:
        manifest["last_health_status"] = str(skill.last_health_status)
    return manifest


@dataclass(frozen=True, slots=True)
class _SkillRelevanceInput:
    text: str
    tokens: frozenset[str]
    category: str
    explicit_skill_order: dict[str, int]

    @classmethod
    def from_values(
        cls,
        *,
        query: str | None,
        task_text: str | None,
        category: str | None,
        explicit_skill_ids: Sequence[str] | None,
    ) -> _SkillRelevanceInput:
        text = " ".join(
            item
            for item in (
                _normalize_text(query),
                _normalize_text(task_text),
                _normalize_text(category),
            )
            if item
        )
        explicit_order: dict[str, int] = {}
        for skill_id in explicit_skill_ids or ():
            normalized_id = _normalize_text(skill_id)
            if normalized_id and normalized_id not in explicit_order:
                explicit_order[normalized_id] = len(explicit_order)
        return cls(
            text=text,
            tokens=frozenset(_tokens(text)),
            category=_normalize_text(category),
            explicit_skill_order=explicit_order,
        )


def _has_relevance_input(
    *,
    query: str | None,
    task_text: str | None,
    category: str | None,
    explicit_skill_ids: Sequence[str] | None,
) -> bool:
    if _normalize_text(query) or _normalize_text(task_text) or _normalize_text(category):
        return True
    return any(_normalize_text(skill_id) for skill_id in explicit_skill_ids or ())


def _relevant_skill_key(
    skill: Skill,
    relevance: _SkillRelevanceInput,
) -> tuple[int, int, int, str, str]:
    explicit_rank = _explicit_rank(skill, relevance)
    explicit_sort = (
        explicit_rank if explicit_rank is not None else len(relevance.explicit_skill_order)
    )
    score = _skill_relevance_score(skill, relevance)
    return (
        0 if explicit_rank is not None else 1,
        explicit_sort,
        -score,
        *_stable_skill_key(skill),
    )


def _skill_relevance_score(skill: Skill, relevance: _SkillRelevanceInput) -> int:
    if not relevance.text and not relevance.tokens and not relevance.category:
        return 0

    score = 0
    score += _text_relevance_score(str(skill.skill_id or ""), relevance, weight=6)
    score += _text_relevance_score(str(skill.name or ""), relevance, weight=8)
    score += _text_relevance_score(skill.trigger_hint, relevance, weight=10)
    score += _text_relevance_score(skill.description, relevance, weight=5)
    score += _text_relevance_score(str(skill.category or ""), relevance, weight=6)
    score += _text_relevance_score(str(skill.platform or ""), relevance, weight=2)

    if relevance.category and _normalize_text(str(skill.category or "")) == relevance.category:
        score += 30

    metadata = dict(skill.skill_metadata or {})
    score += _text_relevance_score(metadata.get("aliases"), relevance, weight=8)
    score += _text_relevance_score(metadata.get("trigger_examples"), relevance, weight=10)

    body = dict(skill.body or {})
    for key in ("instructions", "summary", "content", "prompt"):
        score += _text_relevance_score(body.get(key), relevance, weight=3)
    return score


def _text_relevance_score(value: Any, relevance: _SkillRelevanceInput, *, weight: int) -> int:
    score = 0
    for text in _string_values(value):
        normalized = _normalize_text(text)
        if not normalized:
            continue
        if relevance.text and (normalized in relevance.text or relevance.text in normalized):
            score += weight * 4
        matched_tokens = set(_tokens(normalized)) & relevance.tokens
        score += len(matched_tokens) * weight
    return score


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        values: list[str] = []
        for item in value:
            values.extend(_string_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(_string_values(item))
        return values
    return []


def _stable_skill_key(skill: Skill) -> tuple[str, str]:
    return (str(skill.name or "").lower(), str(skill.skill_id or ""))


def _explicit_rank(skill: Skill, relevance: _SkillRelevanceInput) -> int | None:
    refs = [
        str(skill.skill_id or ""),
        str(skill.name or ""),
    ]
    metadata = dict(skill.skill_metadata or {})
    refs.extend(_string_values(metadata.get("aliases")))
    ranks = [
        relevance.explicit_skill_order.get(_normalize_text(ref))
        for ref in refs
        if _normalize_text(ref) in relevance.explicit_skill_order
    ]
    return min(ranks) if ranks else None


def _truncate_text(value: str | None, *, max_chars: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[: max(max_chars - 24, 0)].rstrip() + "\n[truncated]"


def _truncate_mapping(value: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    if not value:
        return {}
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(text) <= max_chars:
        return value
    return {"_truncated_json": text[: max(max_chars - 24, 0)], "_truncated": True}


def _token_estimate(value: Any) -> int:
    return max(1, len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)) // 4)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _tokens(value: str) -> list[str]:
    return _TOKEN_RE.findall(_normalize_text(value))
