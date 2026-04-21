from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.evolution.promotion import (
    activate_prompt_revision,
    activate_skill,
    evaluate_trial_metrics,
)
from recruit_agent.models.domain import AgentLearning, EvolutionArtifact, PromptOverlayRevision, Skill


class LearningWriter:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def record_learning(
        self,
        *,
        content: str,
        tags: list[str],
        promote: bool = False,
        skill_name: str | None = None,
        trial_metrics: dict[str, Any] | None = None,
        job_description_id: str | None = None,
        artifact_kind: str | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            learning = AgentLearning(content=content, tags=list(tags))
            session.add(learning)
            session.flush()

            skill: Skill | None = None
            skill_judgment: dict[str, Any] | None = None
            if promote:
                resolved_skill_name = skill_name or "trial-skill"
                skill = self._upsert_skill(session, resolved_skill_name, content)
                merged_metrics = _merge_trial_metrics(dict(skill.trial_metrics or {}), dict(trial_metrics or {}))
                skill_judgment = evaluate_trial_metrics(merged_metrics)
                skill.trial_metrics = skill_judgment
                if bool(skill_judgment["auto_promote"]):
                    activate_skill(skill, reviewer="system")
                else:
                    skill.status = "trial"

            revision: PromptOverlayRevision | None = None
            revision_judgment: dict[str, Any] | None = None
            if job_description_id is not None:
                revision = self._create_prompt_revision(session, job_description_id, content, dict(trial_metrics or {}))
                revision_judgment = evaluate_trial_metrics(dict(revision.trial_metrics or {}))
                revision.trial_metrics = {
                    **dict(revision.trial_metrics or {}),
                    **revision_judgment,
                }
                if bool(revision_judgment["auto_promote"]):
                    activate_prompt_revision(revision, baseline_metrics=revision.trial_metrics)
                else:
                    revision.status = "trial"

            resolved_artifact_kind = artifact_kind or ("skill_draft" if promote else "prompt_overlay_revision" if revision is not None else "prompt_lesson")
            active_judgment = skill_judgment if skill_judgment is not None else revision_judgment
            artifact = EvolutionArtifact(
                artifact_kind=resolved_artifact_kind,
                title=skill_name or _prompt_revision_title(job_description_id, revision) or "learning-artifact",
                status="auto_promoted" if active_judgment and active_judgment["auto_promote"] else "pending_review",
                artifact_body={
                    "content": content,
                    "tags": tags,
                    "trial_metrics": trial_metrics or {},
                    "job_description_id": job_description_id,
                },
                related_skill_id=None if skill is None else skill.id,
                artifact_metadata={
                    "learning_id": learning.id,
                    "queue_state": "auto_promoted" if active_judgment and active_judgment["auto_promote"] else "pending_review",
                    "judgment": dict(active_judgment or {}),
                    "prompt_revision_id": None if revision is None else revision.id,
                    "prompt_revision_status": None if revision is None else revision.status,
                    "skill_id": None if skill is None else skill.id,
                },
            )
            session.add(artifact)
            session.commit()
            session.refresh(artifact)
            return {
                "learning_id": learning.id,
                "artifact_id": artifact.id,
                "skill_id": None if skill is None else skill.id,
                "prompt_revision_id": None if revision is None else revision.id,
                "auto_promoted": bool(active_judgment and active_judgment["auto_promote"]),
                "queued": not bool(active_judgment and active_judgment["auto_promote"]),
                "judgment": dict(active_judgment or {}),
            }

    def record_skill_draft(
        self,
        *,
        draft_contract: dict[str, Any],
        tags: list[str],
        trial_metrics: dict[str, Any] | None = None,
        learning_content: str | None = None,
        source_run_id: str | None = None,
        source_turn_id: str | None = None,
        source_kind: str = "autonomous",
        agent_profile_id: str | None = None,
        proposed_by: str | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            skill_name = str(draft_contract.get("skill_name") or draft_contract.get("name") or "llm-trial-skill").strip()
            learning = AgentLearning(
                content=learning_content or json.dumps(draft_contract, ensure_ascii=False),
                tags=list(tags),
            )
            session.add(learning)
            session.flush()

            skill = self._upsert_skill_contract(session, draft_contract, fallback_name=skill_name)
            merged_metrics = _merge_trial_metrics(dict(skill.trial_metrics or {}), dict(trial_metrics or {}))
            judgment = evaluate_trial_metrics(merged_metrics)
            skill.trial_metrics = judgment
            if bool(judgment["auto_promote"]):
                activate_skill(skill, reviewer="system")
            else:
                skill.status = "trial"

            artifact = EvolutionArtifact(
                agent_profile_id=agent_profile_id,
                artifact_kind="skill_draft",
                title=skill_name or "llm-trial-skill",
                summary=str(draft_contract.get("description") or "").strip() or None,
                status="auto_promoted" if judgment["auto_promote"] else "pending_review",
                related_skill_id=skill.id,
                proposed_by=proposed_by or source_kind,
                artifact_body={
                    "skill_contract": dict(draft_contract),
                    "tags": list(tags),
                    "trial_metrics": dict(trial_metrics or {}),
                },
                artifact_metadata={
                    "learning_id": learning.id,
                    "queue_state": "auto_promoted" if judgment["auto_promote"] else "pending_review",
                    "judgment": dict(judgment),
                    "skill_id": skill.id,
                    "source_kind": source_kind,
                    "source_run_id": source_run_id,
                    "source_turn_id": source_turn_id,
                    "llm_generated": True,
                },
            )
            session.add(artifact)
            session.commit()
            session.refresh(artifact)
            return {
                "learning_id": learning.id,
                "artifact_id": artifact.id,
                "skill_id": skill.id,
                "auto_promoted": bool(judgment["auto_promote"]),
                "queued": not bool(judgment["auto_promote"]),
                "judgment": dict(judgment),
                "skill_name": skill.name,
            }

    def _upsert_skill(self, session: Session, skill_name: str, content: str) -> Skill:
        stmt = select(Skill).where(Skill.skill_id == skill_name)
        skill = session.scalars(stmt).first()
        if skill is None:
            skill = Skill(
                skill_id=skill_name,
                name=skill_name,
                status="trial",
                trigger_hint=skill_name,
                body={"content": content},
                strategy={"content": content},
            )
            session.add(skill)
            session.flush()
        else:
            skill.body = {"content": content}
            skill.strategy = {"content": content}
        return skill

    def _upsert_skill_contract(self, session: Session, draft_contract: dict[str, Any], *, fallback_name: str) -> Skill:
        skill_name = str(draft_contract.get("skill_name") or draft_contract.get("name") or fallback_name).strip() or fallback_name
        stmt = select(Skill).where(Skill.skill_id == skill_name)
        skill = session.scalars(stmt).first()
        body = dict(draft_contract.get("body") or {})
        if not body:
            description = str(draft_contract.get("description") or "").strip()
            if description:
                body = {"summary": description}
        strategy = dict(draft_contract.get("strategy") or {})
        execution_hints = dict(draft_contract.get("execution_hints") or {})
        health_check_config = dict(draft_contract.get("health_check_config") or {"expected_result_status": "pass"})
        skill_metadata = {
            **dict(draft_contract.get("skill_metadata") or {}),
            "llm_generated": True,
        }
        payload = {
            "name": skill_name,
            "description": str(draft_contract.get("description") or "").strip() or None,
            "category": str(draft_contract.get("category") or "general"),
            "bound_to_stage": str(draft_contract.get("bound_to_stage") or "").strip() or None,
            "platform": str(draft_contract.get("platform") or "runtime-scene"),
            "input_schema": dict(draft_contract.get("input_schema") or {}),
            "output_schema": dict(draft_contract.get("output_schema") or {}),
            "strategy": strategy,
            "execution_hints": execution_hints,
            "risk_level": str(draft_contract.get("risk_level") or "medium"),
            "health_check_config": health_check_config,
            "skill_metadata": skill_metadata,
            "trigger_hint": str(draft_contract.get("trigger_hint") or skill_name),
            "body": body,
            "requires_human_gate": bool(draft_contract.get("requires_human_gate") or False),
            "human_gate_policy": dict(draft_contract.get("human_gate_policy") or {}),
        }
        if skill is None:
            skill = Skill(
                skill_id=skill_name,
                status="trial",
                **payload,
            )
            session.add(skill)
            session.flush()
            return skill
        for key, value in payload.items():
            setattr(skill, key, value)
        return skill

    def _create_prompt_revision(
        self,
        session: Session,
        job_description_id: str,
        content: str,
        trial_metrics: dict[str, Any],
    ) -> PromptOverlayRevision:
        next_version = int(
            session.scalar(
                select(func.max(PromptOverlayRevision.version)).where(
                    PromptOverlayRevision.job_description_id == job_description_id
                )
            )
            or 0
        ) + 1
        revision = PromptOverlayRevision(
            job_description_id=job_description_id,
            version=next_version,
            content={"content": content},
            status="trial",
            trial_metrics=_merge_trial_metrics({}, trial_metrics),
        )
        session.add(revision)
        session.flush()
        return revision


def _merge_trial_metrics(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    runs = int(current.get("runs") or 0) + int(incoming.get("runs") or 0)
    successes = int(current.get("successes") or 0) + int(incoming.get("successes") or 0)
    failures = int(current.get("failures") or 0) + int(incoming.get("failures") or 0)
    if runs == 0 and (successes or failures):
        runs = successes + failures
    return {"runs": runs, "successes": successes, "failures": failures}


def _prompt_revision_title(job_description_id: str | None, revision: PromptOverlayRevision | None) -> str | None:
    if revision is None:
        return None
    scope = job_description_id or revision.job_description_id
    return f"prompt-overlay:{scope}:v{revision.version}"
