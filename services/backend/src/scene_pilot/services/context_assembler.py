from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from scene_pilot.runtime.models import Message
from scene_pilot.runtime.providers import LLMProvider, ProviderError
from scene_pilot.repositories import (
    AgentGlobalMemoryRepository,
    ApprovalRepository,
    CandidateAssessmentRepository,
    CandidateMemoryRepository,
    CandidateRepository,
    CandidateReviewDecisionRepository,
    CandidateScorecardRepository,
    CandidateSessionRepository,
    JobMemoryRepository,
)
from scene_pilot.scheduler.queue import TaskEnvelope
from scene_pilot.services.recruit_agent import ensure_primary_recruit_agent_profile, resolve_context_policy


def _estimate_tokens(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return max(len(text) // 4, 1)


class ContextAssemblerService:
    def __init__(self, session: Session, *, provider: LLMProvider | None = None) -> None:
        self.session = session
        self.provider = provider

    def build(
        self,
        task: TaskEnvelope,
        *,
        lane: str,
        session_context: dict[str, Any] | None,
        skill_context: dict[str, Any] | None,
        platform_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        profile = ensure_primary_recruit_agent_profile(self.session)
        prompt_config = dict(profile.prompt_config or {})
        context_policy = resolve_context_policy(prompt_config)
        run_override = dict((context_policy.get("run_type_overrides") or {}).get(task.task_type) or {})
        token_budget = int(
            task.payload.get("token_budget")
            or task.metadata.get("token_budget")
            or run_override.get("token_budget")
            or (context_policy.get("global") or {}).get("token_budget_default")
            or 4096
        )
        lane_policy = dict((context_policy.get("lanes") or {}).get(lane) or {})
        default_weights = dict(lane_policy.get("default_weights") or {})
        must_include = {str(item) for item in list(lane_policy.get("must_include") or [])}
        prefer = {str(item) for item in list(run_override.get("prefer") or [])}
        suppress = {str(item) for item in list(run_override.get("suppress") or [])}
        drop_order = [str(item) for item in list((context_policy.get("global") or {}).get("drop_order") or [])]
        fragments: list[dict[str, Any]] = []

        def add_fragment(
            *,
            source: str,
            policy_key: str,
            kind: str,
            tier: str,
            content: Any,
            required: bool = False,
            score: int = 50,
        ) -> None:
            fragments.append(
                {
                    "id": f"fragment_{len(fragments) + 1}",
                    "source": source,
                    "policy_key": policy_key,
                    "kind": kind,
                    "tier": tier,
                    "required": required,
                    "base_score": score,
                    "token_estimate": _estimate_tokens(content),
                    "content": content,
                }
            )

        add_fragment(
            source="task",
            policy_key="task_brief",
            kind="task_brief",
            tier="required",
            content={
                "task_type": task.task_type,
                "adaptive_stage": str(task.metadata.get("adaptive_stage") or task.payload.get("adaptive_stage") or task.task_type),
                "goal_spec_id": str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "") or None,
                "candidate_id": task.candidate_id,
                "workflow_id": task.workflow_id,
                "workflow_node_id": task.workflow_node_id,
                "payload": dict(task.payload or {}),
                "metadata": dict(task.metadata or {}),
            },
            required=True,
            score=100,
        )

        if session_context:
            add_fragment(
                source="session_context",
                policy_key="session_context",
                kind="candidate_session",
                tier="operator_summary",
                content=session_context,
                required=lane == "candidate",
                score=92,
            )

        candidate = None
        if task.candidate_id:
            candidate = CandidateRepository(self.session).resolve(task.candidate_id)
        if candidate is not None:
            add_fragment(
                source="candidate",
                policy_key="candidate_progress",
                kind="candidate_progress",
                tier="required",
                content={
                    "candidate_id": candidate.id,
                    "status": candidate.status,
                    "current_workflow_node": candidate.current_workflow_node,
                    "jd_id": candidate.jd_id,
                    "state_snapshot": dict(candidate.state_snapshot or {}),
                },
                required=True,
                score=98,
            )

            candidate_session = CandidateSessionRepository(self.session).by_candidate_id(candidate.id)
            if candidate_session is not None:
                recent_messages = list(candidate_session.recent_messages or [])[-8:]
                if recent_messages:
                    add_fragment(
                        source="candidate_session",
                        policy_key="recent_messages",
                        kind="recent_messages",
                        tier="operator_summary",
                        content=recent_messages,
                        required=lane == "candidate",
                        score=90,
                    )
            candidate_memory = CandidateMemoryRepository(self.session).by_agent_and_candidate(
                agent_profile_id=profile.id,
                candidate_id=candidate.id,
            )
            if candidate_memory is not None:
                disclosure = dict(candidate_memory.disclosure or {})
                add_fragment(
                    source="candidate_memory",
                    policy_key="candidate_memory",
                    kind="candidate_memory_preview",
                    tier="preview",
                    content=disclosure.get("preview") or candidate_memory.summary,
                    required=False,
                    score=86,
                )
                add_fragment(
                    source="candidate_memory",
                    policy_key="candidate_memory",
                    kind="candidate_memory_operator",
                    tier="operator_summary",
                    content=disclosure.get("operator_summary") or candidate_memory.summary,
                    required=False,
                    score=82,
                )
                add_fragment(
                    source="candidate_memory",
                    policy_key="candidate_memory",
                    kind="candidate_memory_model",
                    tier="model_context",
                    content=disclosure.get("model_context") or dict(candidate_memory.content or {}),
                    required=False,
                    score=75,
                )

            if candidate.jd_id:
                job_memory = JobMemoryRepository(self.session).by_agent_and_jd(
                    agent_profile_id=profile.id,
                    jd_id=candidate.jd_id,
                )
                if job_memory is not None:
                    disclosure = dict(job_memory.disclosure or {})
                    add_fragment(
                        source="job_memory",
                        policy_key="job_memory",
                        kind="job_memory_preview",
                        tier="preview",
                        content=disclosure.get("preview") or job_memory.summary,
                        required=False,
                        score=78,
                    )
                    add_fragment(
                        source="job_memory",
                        policy_key="job_memory",
                        kind="job_memory_operator",
                        tier="operator_summary",
                        content=disclosure.get("operator_summary") or job_memory.summary,
                        required=False,
                        score=72,
                    )

            global_memory = AgentGlobalMemoryRepository(self.session).by_agent(profile.id)
            if global_memory is not None:
                disclosure = dict(global_memory.disclosure or {})
                add_fragment(
                    source="agent_global_memory",
                    policy_key="global_memory",
                    kind="agent_global_memory_preview",
                    tier="preview",
                    content=disclosure.get("preview") or global_memory.summary,
                    required=False,
                    score=58,
                )

            latest_assessments = CandidateAssessmentRepository(self.session).by_candidate(candidate.id, limit=3, offset=0)
            if latest_assessments:
                add_fragment(
                    source="assessments",
                    policy_key="assessments",
                    kind="latest_assessments",
                    tier="operator_summary",
                    content=[{"type": item.assessment_type, "decision": item.decision, "score": item.score, "summary": item.summary} for item in latest_assessments],
                    required=False,
                    score=88,
                )
            latest_scorecards = CandidateScorecardRepository(self.session).by_candidate(candidate.id, limit=2, offset=0)
            if latest_scorecards:
                add_fragment(
                    source="scorecards",
                    policy_key="scorecards",
                    kind="latest_scorecards",
                    tier="operator_summary",
                    content=[{"verdict": item.verdict, "score_total": item.score_total, "summary": item.summary} for item in latest_scorecards],
                    required=False,
                    score=84,
                )
            latest_decisions = CandidateReviewDecisionRepository(self.session).by_candidate(candidate.id, limit=2, offset=0)
            if latest_decisions:
                add_fragment(
                    source="review_decisions",
                    policy_key="review_decisions",
                    kind="latest_review_decisions",
                    tier="operator_summary",
                    content=[{"decision": item.decision, "stage_key": item.stage_key, "rationale": item.rationale} for item in latest_decisions],
                    required=False,
                    score=80,
                )

        if skill_context:
            add_fragment(
                source="skill",
                policy_key="skill_summary",
                kind="skill_summary",
                tier="operator_summary",
                content={
                    "skill_id": skill_context.get("skill_id"),
                    "name": skill_context.get("name"),
                    "status": skill_context.get("status"),
                    "platform": skill_context.get("platform"),
                    "execution_hints": dict(skill_context.get("execution_hints") or {}),
                },
                required=False,
                score=74,
            )

        approval_id = task.metadata.get("approval_id") or task.payload.get("approval_id")
        if isinstance(approval_id, str) and approval_id.strip():
            approval = ApprovalRepository(self.session).get(approval_id.strip())
            if approval is not None:
                add_fragment(
                    source="approval",
                    policy_key="approval_context",
                    kind="approval_context",
                    tier="operator_summary",
                    content={
                        "approval_id": approval.id,
                        "target_type": approval.target_type,
                        "title": approval.title,
                        "status": approval.status,
                        "payload": dict(approval.payload or {}),
                    },
                    required=lane == "agent",
                    score=87,
                )

        if platform_context:
            add_fragment(
                source="platform",
                policy_key="platform_context",
                kind="platform_context",
                tier="preview",
                content=platform_context,
                required=False,
                score=68,
            )

        drop_penalties = {
            key: max(0, 12 - index * 2)
            for index, key in enumerate(drop_order)
        }
        for fragment in fragments:
            policy_key = str(fragment["policy_key"])
            required_by_policy = policy_key in must_include
            weight = float(default_weights.get(policy_key, 1.0))
            user_adjustment = round((weight - 1.0) * 20)
            if policy_key in prefer:
                user_adjustment += 12
            if policy_key in suppress:
                user_adjustment -= 15
            user_adjustment -= int(drop_penalties.get(policy_key, 0))
            fragment["required"] = bool(fragment["required"] or required_by_policy)
            fragment["user_adjustment"] = user_adjustment
            fragment["llm_adjustment"] = 0
            fragment["final_score"] = int(fragment["base_score"]) + user_adjustment

        self._apply_llm_rerank(
            fragments,
            context_policy=context_policy,
            lane=lane,
            task_type=task.task_type,
        )

        ordered = sorted(
            fragments,
            key=lambda item: (
                0 if item["required"] else 1,
                -int(item["final_score"]),
                int(item["token_estimate"]),
            ),
        )
        selected: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        used_tokens = 0
        for fragment in ordered:
            fragment_tokens = int(fragment["token_estimate"])
            if selected and used_tokens + fragment_tokens > token_budget and not fragment["required"]:
                dropped.append(
                    {
                        "source": fragment["source"],
                        "policy_key": fragment["policy_key"],
                        "kind": fragment["kind"],
                        "tier": fragment["tier"],
                        "token_estimate": fragment_tokens,
                        "final_score": int(fragment["final_score"]),
                        "reason": "token_budget_exceeded",
                    }
                )
                continue
            selected.append(fragment)
            used_tokens += fragment_tokens

        return {
            "lane": lane,
            "run_type": task.task_type,
            "candidate_id": candidate.id if candidate is not None else None,
            "job_id": candidate.jd_id if candidate is not None else None,
            "token_budget": token_budget,
            "context_policy": context_policy,
            "selected_token_estimate": used_tokens,
            "fragment_count": len(selected),
            "dropped_fragment_count": len(dropped),
            "fragments": selected,
            "dropped_fragments": dropped,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _apply_llm_rerank(
        self,
        fragments: list[dict[str, Any]],
        *,
        context_policy: dict[str, Any],
        lane: str,
        task_type: str,
    ) -> None:
        global_policy = dict(context_policy.get("global") or {})
        if not global_policy.get("llm_rerank_enabled"):
            return
        if self.provider is None:
            return

        max_boost = max(int(global_policy.get("llm_rerank_max_boost") or 0), 1)
        top_k = max(int(global_policy.get("llm_rerank_top_k") or 0), 1)
        candidates = sorted(
            [item for item in fragments if not item["required"]],
            key=lambda item: (-int(item["final_score"]), int(item["token_estimate"])),
        )[:top_k]
        if len(candidates) < 2:
            return

        try:
            response = self.provider.generate(
                [
                    Message(
                        role="system",
                        content=(
                            "你是 Recruit Agent 的 Context Assembler 辅助重排器。\n"
                            "只能在给定片段中做小幅重排，不能引入新来源，也不能越过硬边界。\n"
                            "只返回 JSON，格式为 {\"adjustments\": [{\"fragment_id\": \"...\", \"adjustment\": 1-8, \"reason\": \"...\"}]}。\n"
                            "adjustment 可以为负数，但绝对值不能超过给定上限。"
                        ),
                    ),
                    Message(
                        role="user",
                        content=json.dumps(
                            {
                                "lane": lane,
                                "task_type": task_type,
                                "max_boost": max_boost,
                                "fragments": [
                                    {
                                        "fragment_id": item["id"],
                                        "policy_key": item["policy_key"],
                                        "kind": item["kind"],
                                        "tier": item["tier"],
                                        "base_score": item["base_score"],
                                        "current_score": item["final_score"],
                                        "token_estimate": item["token_estimate"],
                                        "preview": self._fragment_preview(item["content"]),
                                    }
                                    for item in candidates
                                ],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
                max_tokens=600,
                temperature=0.1,
            )
        except ProviderError:
            return
        except Exception:
            return

        try:
            payload = json.loads(response.content or "{}")
        except json.JSONDecodeError:
            return
        adjustments = list(payload.get("adjustments") or []) if isinstance(payload, dict) else []
        by_id = {item["id"]: item for item in candidates}
        for raw in adjustments:
            if not isinstance(raw, dict):
                continue
            fragment_id = str(raw.get("fragment_id") or "").strip()
            item = by_id.get(fragment_id)
            if item is None:
                continue
            try:
                adjustment = int(raw.get("adjustment") or 0)
            except (TypeError, ValueError):
                continue
            adjustment = max(-max_boost, min(adjustment, max_boost))
            item["llm_adjustment"] = adjustment
            item["llm_reason"] = str(raw.get("reason") or "").strip()
            item["final_score"] = int(item["base_score"]) + int(item["user_adjustment"]) + adjustment

    def _fragment_preview(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            text = content
        else:
            text = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
        return text[:320]
