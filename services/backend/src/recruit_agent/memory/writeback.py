from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any
from uuid import uuid4

from recruit_agent.agent_runtime.types import LLMMessage, LLMProvider, LLMRequest
from recruit_agent.memory.filesystem import MemoryFileStore


@dataclass(frozen=True, slots=True)
class MemoryWritebackPolicy:
    min_confidence: float = 0.35
    max_stable_facts: int = 8
    trust_level: str = "agent_observed"
    min_completed_turns_between_jobs: int = 3
    min_evidence_chars_between_jobs: int = 1500
    force_on_explicit_request: bool = True


@dataclass(slots=True)
class MemoryWritebackResult:
    stable_facts_written: int = 0
    skipped: list[dict[str, Any]] = field(default_factory=list)


def should_start_memory_writeback_job(
    policy: MemoryWritebackPolicy,
    *,
    completed_turns_since_last_job: int,
    evidence_text: str,
    force: bool = False,
) -> bool:
    if policy.max_stable_facts <= 0:
        return False
    if force and policy.force_on_explicit_request:
        return True
    min_turns = max(int(policy.min_completed_turns_between_jobs or 0), 0)
    min_chars = max(int(policy.min_evidence_chars_between_jobs or 0), 0)
    if min_turns <= 0 and min_chars <= 0:
        return True
    if min_turns > 0 and completed_turns_since_last_job >= min_turns:
        return True
    return min_chars > 0 and len(str(evidence_text or "").strip()) >= min_chars


def select_stable_memory_facts_with_llm(
    provider: LLMProvider,
    *,
    instruction: str,
    final_output: str,
    scope_kind: str,
    scope_ref: str,
    memory_entries: list[dict[str, Any]],
    max_stable_facts: int,
) -> list[dict[str, Any]]:
    if max_stable_facts <= 0 or not str(final_output or "").strip():
        return []
    request_id = f"memory_writeback_{uuid4().hex}"
    prompt = {
        "instruction": instruction,
        "scope": {"kind": scope_kind, "ref": scope_ref},
        "existing_memory_summaries": [
            {
                "memory_item_id": item.get("memory_item_id"),
                "summary": item.get("summary"),
                "kind": item.get("kind"),
                "confidence": item.get("confidence"),
            }
            for item in list(memory_entries or [])[:50]
        ],
        "final_output": final_output,
        "max_stable_facts": max_stable_facts,
    }
    response = provider.invoke(
        LLMRequest(
            id=request_id,
            turn_id=request_id,
            invocation_id=request_id,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "You decide whether a completed agent turn contains stable long-term memory facts. "
                        "Return strict JSON only: {\"stable_facts\":[{\"summary\":\"...\",\"content\":{},\"confidence\":0.0-1.0}]}. "
                        "Return an empty stable_facts array when there are no durable facts. "
                        "Do not store transient run status, page state, current blockers, raw tool payloads, or one-off UI details."
                    ),
                ),
                LLMMessage(role="user", content=json.dumps(prompt, ensure_ascii=False, default=str)),
            ],
        )
    ).response
    content = response.assistant_message.content if response.assistant_message is not None else ""
    payload = _json_object_from_text(str(content or ""))
    if not payload:
        return []
    return _normalized_stable_memory_facts(payload.get("stable_facts") or [])


def write_stable_memory_facts_to_files(
    memory_file_store: MemoryFileStore,
    *,
    scope_kind: str,
    scope_ref: str,
    agent_definition_id: str | None,
    facts: list[dict[str, Any]],
    run_id: str | None = None,
    run_pk: str | None = None,
    turn_id: str | None = None,
    source: str = "memory_writeback_pipeline",
    policy: MemoryWritebackPolicy | None = None,
) -> MemoryWritebackResult:
    result = MemoryWritebackResult()
    if agent_definition_id is None:
        return result
    active_policy = policy or MemoryWritebackPolicy()
    existing_content = memory_file_store.read_file(
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        path="stable_facts.md",
        agent_definition_id=agent_definition_id,
    ).get("content", "")
    existing_text = str(existing_content or "")
    lines: list[str] = []
    for fact in _normalized_stable_memory_facts(facts)[: max(active_policy.max_stable_facts, 0)]:
        summary = _summary(fact)
        if not summary:
            result.skipped.append({"reason": "missing_summary", "fact": fact})
            continue
        confidence = _coerce_confidence(fact.get("confidence"), default=0.6)
        if confidence < active_policy.min_confidence:
            result.skipped.append({"reason": "low_confidence", "summary": summary, "confidence": confidence})
            continue
        if summary in existing_text:
            result.skipped.append({"reason": "duplicate_summary", "summary": summary})
            continue
        metadata = {
            "confidence": confidence,
            "source": source,
            "run_id": run_pk or run_id,
            "turn_id": turn_id,
        }
        lines.append(f"- {summary} <!-- {json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)} -->\n")
        result.stable_facts_written += 1
    if lines:
        prefix = "\n" if existing_text and not existing_text.endswith("\n") else ""
        memory_file_store.write_file(
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            path="stable_facts.md",
            agent_definition_id=agent_definition_id,
            content=prefix + "".join(lines),
            mode="append",
        )
    return result


def _normalized_stable_memory_facts(raw_facts: Any) -> list[dict[str, Any]]:
    if isinstance(raw_facts, dict):
        raw_facts = raw_facts.get("items") or raw_facts.get("facts") or [raw_facts]
    facts: list[dict[str, Any]] = []
    for item in raw_facts if isinstance(raw_facts, list) else []:
        if isinstance(item, dict):
            facts.append(dict(item))
        elif isinstance(item, str) and item.strip():
            facts.append({"summary": item.strip(), "content": {"fact": item.strip()}})
    return [fact for fact in facts if _summary(fact)]


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    if not candidate.startswith("{"):
        return None
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _summary(patch: dict[str, Any]) -> str:
    raw = patch.get("summary") or patch.get("fact")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    content = patch.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        raw_fact = content.get("fact") or content.get("summary")
        if isinstance(raw_fact, str) and raw_fact.strip():
            return raw_fact.strip()
    return ""


def _coerce_confidence(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(parsed, 1.0))


def memory_writeback_policy_from_config(config: dict[str, Any] | None) -> MemoryWritebackPolicy:
    raw_config = dict(config or {})
    if raw_config.get("enabled") is False:
        return MemoryWritebackPolicy(max_stable_facts=0)
    return MemoryWritebackPolicy(
        min_confidence=_bounded_float(raw_config.get("auto_write_min_confidence"), default=0.35),
        max_stable_facts=_bounded_int(raw_config.get("max_stable_facts"), default=8, minimum=0, maximum=32),
        trust_level=str(raw_config.get("trust_level") or "agent_observed"),
        min_completed_turns_between_jobs=_bounded_int(
            raw_config.get("min_completed_turns_between_jobs"),
            default=3,
            minimum=0,
            maximum=100,
        ),
        min_evidence_chars_between_jobs=_bounded_int(
            raw_config.get("min_evidence_chars_between_jobs"),
            default=1500,
            minimum=0,
            maximum=200000,
        ),
        force_on_explicit_request=bool(raw_config.get("force_on_explicit_request", True)),
    )


def _bounded_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(parsed, 1.0))


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))
