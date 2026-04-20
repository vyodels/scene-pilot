from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from scene_pilot.asset_paths import prompt_path
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scene_pilot.memory.global_memory_projection import (
    GLOBAL_MEMORY_SCHEMA_VERSION,
    empty_agent_global_memory_payload,
    needs_agent_global_memory_projection,
    project_agent_global_memory,
)
from scene_pilot.models import AgentGlobalMemory, AgentRun, CandidatePersonMemory, GoalSpec, JobDescriptionMemory, RecruitAgentProfile
from scene_pilot.repositories import (
    AgentGlobalMemoryRepository,
    CandidatePersonMemoryRepository,
    JobDescriptionMemoryRepository,
    RecruitAgentProfileRepository,
)
from scene_pilot.runtime.models import Message
from scene_pilot.runtime.providers import LLMProvider, ProviderError


AUTO_COMPACT_THRESHOLD = 1_000_000
EVOLUTION_ARTIFACT_KINDS = {
    "skill_draft",
    "prompt_patch",
    "memory_policy_patch",
    "playbook_patch",
    "playbook_patch",
}
EVOLUTION_ARTIFACT_STATUSES = {
    "draft",
    "pending_review",
    "approved",
    "applied",
    "rejected",
    "archived",
}
EVOLUTION_ARTIFACT_REQUIRED_BODY_KEYS: dict[str, tuple[str, ...]] = {
    "skill_draft": ("skill_contract",),
    "prompt_patch": ("before", "after"),
    "memory_policy_patch": ("before", "after", "scope"),
    "playbook_patch": ("before", "after"),
    "playbook_patch": ("before", "after"),
}
CONTEXT_POLICY_LANES = {"candidate", "agent"}
CONTEXT_POLICY_WEIGHT_KEYS = {
    "task_brief",
    "session_context",
    "candidate_progress",
    "recent_messages",
    "candidate_memory",
    "job_memory",
    "global_memory",
    "assessments",
    "scorecards",
    "review_decisions",
    "skill_summary",
    "approval_context",
    "platform_context",
}

DEFAULT_CANDIDATE_STATUSES = [
    "discovered",
    "profile_reviewed",
    "screening_passed",
    "screening_rejected",
    "contact_required",
    "contact_acquired",
    "pending_communication",
    "waiting_reply",
    "resume_requested",
    "resume_received",
    "ai_assessment_completed",
    "human_assessment_pending",
    "human_assessment_completed",
    "waiting_schedule_round_1",
    "interview_round_1_scheduled",
    "waiting_schedule_round_2",
    "interview_round_2_scheduled",
    "waiting_schedule_final",
    "interview_final_scheduled",
    "offer_review",
    "passed_to_talent_pool",
    "rejected",
    "cooldown",
]


@lru_cache(maxsize=8)
def _load_prompt_text(prompt_key: str) -> str:
    asset_path = prompt_path(prompt_key)
    if not asset_path.exists():
        return ""
    return asset_path.read_text(encoding="utf-8").strip()


def resolve_goal_template(prompt_config: dict[str, Any] | None) -> str:
    configured = str((prompt_config or {}).get("goal_template") or (prompt_config or {}).get("goalTemplate") or "").strip()
    if configured:
        return configured
    return _load_prompt_text("base/autonomous_goal_template")


def _playbook_stage_groups() -> list[dict[str, Any]]:
    return [
        {
            "id": "discovery_and_screening",
            "name": "发现与初筛",
            "repeatable": False,
            "stages": [
                {"key": "discovered", "label": "已发现"},
                {"key": "profile_reviewed", "label": "已查看资料"},
                {"key": "screening_passed", "label": "初筛通过"},
                {"key": "screening_rejected", "label": "初筛不通过"},
            ],
        },
        {
            "id": "contact_and_resume",
            "name": "联系方式与简历",
            "repeatable": False,
            "stages": [
                {"key": "contact_required", "label": "待获取联系方式"},
                {"key": "contact_acquired", "label": "已拿到联系方式"},
                {"key": "pending_communication", "label": "待沟通"},
                {"key": "waiting_reply", "label": "等待回复"},
                {"key": "resume_requested", "label": "已请求简历"},
                {"key": "resume_received", "label": "已收到简历"},
            ],
        },
        {
            "id": "assessment",
            "name": "评估",
            "repeatable": False,
            "stages": [
                {"key": "ai_assessment_completed", "label": "AI 评估完成"},
                {"key": "human_assessment_pending", "label": "待人工评估"},
                {"key": "human_assessment_completed", "label": "人工评估完成"},
            ],
        },
        {
            "id": "interviews",
            "name": "面试",
            "repeatable": True,
            "configurable_rounds": True,
            "default_rounds": [
                {"round": 1, "waiting_key": "waiting_schedule_round_1", "scheduled_key": "interview_round_1_scheduled"},
                {"round": 2, "waiting_key": "waiting_schedule_round_2", "scheduled_key": "interview_round_2_scheduled"},
                {"round": 3, "waiting_key": "waiting_schedule_final", "scheduled_key": "interview_final_scheduled"},
            ],
        },
        {
            "id": "outcome",
            "name": "结果",
            "repeatable": False,
            "stages": [
                {"key": "offer_review", "label": "等待发 Offer/终面决策"},
                {"key": "passed_to_talent_pool", "label": "进入后续流程"},
                {"key": "rejected", "label": "已淘汰"},
                {"key": "cooldown", "label": "冷却中"},
            ],
        },
    ]


def default_context_policy() -> dict[str, Any]:
    return {
        "version": "context-policy-v1",
        "global": {
            "token_budget_default": 1_000_000,
            "llm_rerank_enabled": False,
            "llm_rerank_top_k": 6,
            "llm_rerank_max_boost": 8,
            "drop_order": ["global_memory", "job_memory", "platform_context", "session_context"],
        },
        "lanes": {
            "candidate": {
                "must_include": ["task_brief", "candidate_progress"],
                "default_weights": {
                    "recent_messages": 1.2,
                    "candidate_memory": 1.1,
                    "job_memory": 0.95,
                    "assessments": 1.0,
                    "scorecards": 1.0,
                    "review_decisions": 1.0,
                    "skill_summary": 0.75,
                    "global_memory": 0.4,
                    "platform_context": 0.7,
                    "session_context": 0.85,
                },
            },
            "agent": {
                "must_include": ["task_brief", "approval_context"],
                "default_weights": {
                    "approval_context": 1.25,
                    "skill_summary": 1.05,
                    "global_memory": 0.55,
                    "platform_context": 0.6,
                    "session_context": 0.5,
                },
            },
        },
        "run_type_overrides": {
            "candidate_outreach": {
                "prefer": ["recent_messages", "candidate_memory", "job_memory"],
                "suppress": ["global_memory"],
            },
            "candidate_scoring": {
                "prefer": ["assessments", "scorecards", "job_memory"],
                "suppress": ["global_memory"],
            },
            "resume_collection": {
                "prefer": ["recent_messages", "candidate_progress", "candidate_memory"],
                "suppress": ["global_memory"],
            },
        },
    }


def default_memory_policy() -> dict[str, Any]:
    return {
        "candidate_memory": {
            "isolation": "strict_by_candidate",
            "auto_compact": True,
            "compact_threshold": AUTO_COMPACT_THRESHOLD,
            "schema": [
                "identity_summary",
                "facts",
                "interaction_summary",
                "risk_flags",
                "open_questions",
                "recommended_next_actions",
                "evidence_refs",
                "confidence",
            ],
            "disclosure": ["preview", "operator_summary", "model_context"],
        },
        "job_memory": {
            "isolation": "strict_by_jd",
            "auto_compact": True,
            "compact_threshold": AUTO_COMPACT_THRESHOLD,
            "schema": [
                "screening_preferences",
                "strong_positive_signals",
                "common_reject_reasons",
                "communication_notes",
                "quality_thresholds",
                "historical_patterns",
            ],
            "disclosure": ["preview", "operator_summary", "model_context"],
        },
        "agent_global_memory": {
            "scope": "agent_global",
            "auto_compact": True,
            "compact_threshold": AUTO_COMPACT_THRESHOLD,
            "schema": ["facts", "decisions", "open_questions", "next_actions", "risk_flags", "evidence_refs", "confidence"],
            "disclosure": ["preview", "operator_summary", "model_context"],
        },
    }


def _sanitize_weight_map(value: Any, defaults: dict[str, float]) -> dict[str, float]:
    source = value if isinstance(value, dict) else {}
    resolved = dict(defaults)
    for key, raw in source.items():
        if key not in CONTEXT_POLICY_WEIGHT_KEYS:
            continue
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            continue
        resolved[key] = max(0.0, min(parsed, 3.0))
    return resolved


def _sanitize_string_list(value: Any, *, allowed: set[str] | None = None) -> list[str]:
    items: list[str] = []
    for item in list(value or []) if isinstance(value, list) else []:
        text = str(item).strip()
        if not text:
            continue
        if allowed is not None and text not in allowed:
            continue
        if text not in items:
            items.append(text)
    return items


def _sanitize_free_string_list(value: Any) -> list[str]:
    return _sanitize_string_list(value)


def resolve_context_policy(prompt_config: dict[str, Any] | None) -> dict[str, Any]:
    defaults = default_context_policy()
    configured = dict((prompt_config or {}).get("context_policy") or {})

    global_defaults = dict(defaults["global"])
    global_config = dict(configured.get("global") or {})
    lanes_defaults = dict(defaults["lanes"])
    lanes_config = dict(configured.get("lanes") or {})
    overrides_defaults = dict(defaults.get("run_type_overrides") or {})
    overrides_config = dict(configured.get("run_type_overrides") or {})

    resolved_lanes: dict[str, Any] = {}
    for lane in CONTEXT_POLICY_LANES:
        lane_defaults = dict(lanes_defaults.get(lane) or {})
        lane_config = dict(lanes_config.get(lane) or {})
        resolved_lanes[lane] = {
            "must_include": _sanitize_string_list(
                lane_config.get("must_include") or lane_defaults.get("must_include"),
                allowed=CONTEXT_POLICY_WEIGHT_KEYS,
            ),
            "default_weights": _sanitize_weight_map(
                lane_config.get("default_weights"),
                lane_defaults.get("default_weights") or {},
            ),
        }

    resolved_overrides: dict[str, Any] = {}
    for run_type, raw_override in {**overrides_defaults, **overrides_config}.items():
        if not str(run_type).strip() or not isinstance(raw_override, dict):
            continue
        resolved_overrides[str(run_type).strip()] = {
            "prefer": _sanitize_string_list(raw_override.get("prefer"), allowed=CONTEXT_POLICY_WEIGHT_KEYS),
            "suppress": _sanitize_string_list(raw_override.get("suppress"), allowed=CONTEXT_POLICY_WEIGHT_KEYS),
            **(
                {"token_budget": max(int(raw_override.get("token_budget") or 1), 1)}
                if raw_override.get("token_budget") is not None
                else {}
            ),
        }

    return {
        "version": str(configured.get("version") or defaults["version"]),
        "global": {
            "token_budget_default": max(int(global_config.get("token_budget_default") or global_defaults["token_budget_default"]), 1),
            "llm_rerank_enabled": bool(global_config.get("llm_rerank_enabled", global_defaults["llm_rerank_enabled"])),
            "llm_rerank_top_k": max(int(global_config.get("llm_rerank_top_k") or global_defaults["llm_rerank_top_k"]), 1),
            "llm_rerank_max_boost": max(int(global_config.get("llm_rerank_max_boost") or global_defaults["llm_rerank_max_boost"]), 1),
            "drop_order": _sanitize_string_list(
                global_config.get("drop_order") or global_defaults["drop_order"],
                allowed=CONTEXT_POLICY_WEIGHT_KEYS,
            ),
        },
        "lanes": resolved_lanes,
        "run_type_overrides": resolved_overrides or defaults["run_type_overrides"],
    }


def resolve_memory_policy(memory_policy: dict[str, Any] | None) -> dict[str, Any]:
    defaults = default_memory_policy()
    configured = dict(memory_policy or {})
    resolved: dict[str, Any] = {}

    for scope_key, default_scope in defaults.items():
        scope_config = dict(configured.get(scope_key) or {})
        resolved_scope = dict(default_scope)
        for key in ("isolation", "scope"):
            if scope_config.get(key) is not None:
                resolved_scope[key] = str(scope_config.get(key)).strip() or default_scope[key]
        if scope_config.get("auto_compact") is not None:
            resolved_scope["auto_compact"] = bool(scope_config.get("auto_compact"))
        if scope_config.get("compact_threshold") is not None:
            try:
                resolved_scope["compact_threshold"] = max(int(scope_config.get("compact_threshold") or 1), 1)
            except (TypeError, ValueError):
                resolved_scope["compact_threshold"] = default_scope["compact_threshold"]

        if scope_key == "agent_global_memory":
            resolved_scope["schema"] = list(default_scope["schema"])
        elif isinstance(scope_config.get("schema"), list):
            resolved_scope["schema"] = _sanitize_free_string_list(scope_config.get("schema")) or list(default_scope["schema"])

        if isinstance(scope_config.get("disclosure"), list):
            resolved_scope["disclosure"] = _sanitize_free_string_list(scope_config.get("disclosure")) or list(default_scope["disclosure"])
        else:
            resolved_scope["disclosure"] = list(default_scope["disclosure"])
        resolved[scope_key] = resolved_scope

    return resolved


def default_candidate_state_snapshot(
    *,
    status: str = "discovered",
    stage_key: str | None = None,
    stage_label: str | None = None,
) -> dict[str, Any]:
    resolved_stage_key = stage_key or status
    resolved_stage_label = stage_label or resolved_stage_key.replace("_", " ")
    return {
        "current_phase_key": "discovery_and_screening",
        "current_phase_label": "发现与初筛",
        "current_stage_key": resolved_stage_key,
        "current_stage_label": resolved_stage_label,
        "contact_status": "unknown",
        "contact_channels": [],
        "contact_acquired": False,
        "resume_status": "not_requested",
        "ai_assessment_status": "pending",
        "human_assessment_status": "pending",
        "operator_flags": [],
        "next_recommended_stages": ["profile_reviewed"],
        "interview_plan": {
            "active_round": 0,
            "rounds": [
                {"round": 1, "label": "一面", "status": "not_started"},
                {"round": 2, "label": "二面", "status": "not_started"},
                {"round": 3, "label": "终面", "status": "not_started"},
            ],
        },
        "latest_note": None,
        "latest_transition_at": None,
        "latest_transition_source": None,
        "snapshot_metadata": {"status_machine_version": "candidate-progress-v2"},
    }


def build_memory_disclosure(*, scope: str, summary: str | None, content: dict[str, Any], token_estimate: int) -> dict[str, Any]:
    compact_summary = summary or f"{scope} memory ready."
    model_excerpt = json.dumps(content or {}, ensure_ascii=False)[:1600]
    return {
        "preview": compact_summary[:180],
        "operator_summary": compact_summary,
        "model_context": model_excerpt,
        "tiers": [
            {"level": "preview", "label": "Preview", "token_estimate": min(token_estimate, 180)},
            {"level": "operator", "label": "Operator Summary", "token_estimate": min(token_estimate, 900)},
            {"level": "model", "label": "Model Context", "token_estimate": min(token_estimate, 1600)},
        ],
    }


def validate_evolution_artifact(
    *,
    artifact_kind: str,
    status: str,
    artifact_body: dict[str, Any],
) -> None:
    if artifact_kind not in EVOLUTION_ARTIFACT_KINDS:
        raise ValueError(f"Unsupported evolution artifact kind: {artifact_kind}")
    if status not in EVOLUTION_ARTIFACT_STATUSES:
        raise ValueError(f"Unsupported evolution artifact status: {status}")
    required_keys = EVOLUTION_ARTIFACT_REQUIRED_BODY_KEYS.get(artifact_kind, ())
    missing = [key for key in required_keys if key not in artifact_body]
    if missing:
        raise ValueError(f"{artifact_kind} 缺少必要字段: {', '.join(missing)}")


def _adaptive_execution_to_payload() -> dict[str, Any]:
    return {
        "blueprint_id": "recruit-goal-driven-v1",
        "name": "Recruit Goal-Driven Runtime",
        "initial_stage": "exploration_trial",
        "version": 1,
        "stage_groups": _playbook_stage_groups(),
        "status_machine": {"default_statuses": DEFAULT_CANDIDATE_STATUSES, "mutable": True},
        "adaptive_stages": [
            {
                "id": "goal_intake",
                "name": "Goal Intake",
                "task_type": "goal_intake",
                "requires_skill": False,
                "kind": "goal",
                "purpose": "把用户目标、约束和成功标准归一成一次可执行目标。",
                "next_stage": "exploration_trial",
            },
            {
                "id": "exploration_trial",
                "name": "Exploration Trial",
                "task_type": "exploration_trial",
                "requires_skill": True,
                "kind": "exploration",
                "purpose": "先在真实外部环境中做小规模试探，验证入口、筛选器和候选路径。",
                "next_stage": "strategy_distill",
            },
            {
                "id": "candidate_discovery",
                "name": "Candidate Discovery",
                "task_type": "candidate_discovery",
                "requires_skill": True,
                "kind": "candidate",
                "purpose": "在真实站点环境中发现候选人，并为后续投递记录跟进沉淀有效入口。",
                "next_stage": "strategy_distill",
            },
            {
                "id": "candidate_probe",
                "name": "Candidate Probe",
                "task_type": "candidate_probe",
                "requires_skill": True,
                "kind": "candidate",
                "purpose": "围绕单条投递记录做资料观察、初筛和事实记录。",
                "next_stage": "strategy_distill",
            },
            {
                "id": "candidate_outreach",
                "name": "Application Follow-up",
                "task_type": "candidate_outreach",
                "requires_skill": True,
                "kind": "candidate",
                "purpose": "在人工确认下推进投递记录跟进中的沟通、接管或纠偏。",
                "next_stage": "strategy_distill",
            },
            {
                "id": "resume_collection",
                "name": "Resume Collection",
                "task_type": "resume_collection",
                "requires_skill": True,
                "kind": "candidate",
                "purpose": "围绕投递记录获取简历或补充资料，并保留真实环境证据。",
                "next_stage": "strategy_distill",
            },
            {
                "id": "candidate_scoring",
                "name": "Candidate Scoring",
                "task_type": "candidate_scoring",
                "requires_skill": True,
                "kind": "candidate",
                "purpose": "完成投递记录评分与证据化结论，供人工继续判断。",
                "next_stage": "strategy_distill",
            },
            {
                "id": "strategy_distill",
                "name": "Strategy Distill",
                "task_type": "strategy_distill",
                "requires_skill": False,
                "kind": "learning",
                "purpose": "从本次真实执行中提炼 trace、strategy fragment 和图投影。",
                "next_stage": None,
            },
            {
                "id": "scale_execution",
                "name": "Scale Execution",
                "task_type": "scale_execution",
                "requires_skill": True,
                "kind": "execution",
                "purpose": "把已验证的路径扩大到更多投递记录或更多目标范围。",
                "next_stage": "strategy_distill",
            },
            {
                "id": "candidate_archive",
                "name": "Candidate Archive",
                "task_type": "candidate_archive",
                "requires_skill": True,
                "kind": "candidate",
                "purpose": "在真实环境中对投递记录执行归档、冷却或结束动作，并保留结果证据。",
                "next_stage": "strategy_distill",
            }
        ],
        "goal_modes": [
            {
                "key": "candidate_review",
                "label": "投递记录评估",
                "initial_stage": "candidate_probe",
                "success_signals": ["screening_passed", "screening_rejected", "human_assessment_completed"],
            },
            {
                "key": "candidate_outreach",
                "label": "投递记录跟进",
                "initial_stage": "candidate_outreach",
                "success_signals": ["waiting_reply", "resume_requested", "resume_received"],
            },
            {
                "key": "candidate_discovery",
                "label": "候选人发现",
                "initial_stage": "candidate_discovery",
                "success_signals": ["discovered", "profile_reviewed"],
            },
        ],
    }


def default_recruit_agent_profile() -> dict[str, Any]:
    goal_template = resolve_goal_template(None)
    return {
        "agent_key": "recruit-agent",
        "name": "Recruit Agent",
        "status": "active",
        "description": "招聘场景优先的本地 agent，负责候选人发现，以及围绕投递记录完成初筛、跟进、简历获取、评分与后续交接。",
        "is_primary": True,
        "role_definition": {
            "identity": "招聘智能助理",
            "positioning": "在人工监督下围绕投递记录推进招聘流程的本地 agent。",
            "duties": [
                "整理候选人事实并推进当前投递记录阶段。",
                "根据 JD 和证据完成投递记录初筛与评分。",
                "在需要时草拟投递记录跟进中的沟通内容并等待人工确认。",
                "持续沉淀 skill、memory 和 strategy fragment。",
            ],
            "tone": "professional, concise, evidence-driven",
            "boundaries": [
                "不得跨投递记录混用跟进上下文。",
                "不得跨 JD 混用岗位结论。",
                "外联、上传、写入类动作必须保留确认意识。",
            ],
            "success_criteria": [
                "投递记录状态更新准确。",
                "结论有证据支撑。",
                "投递记录跟进中的沟通内容合规且可审查。",
                "skill 与 memory 演进可追踪。",
            ],
            "forbidden_actions": [
                "未经确认发送高风险内容。",
                "擅自覆盖历史事实记录。",
                "将某条投递记录的跟进事实暴露给其他投递记录。",
            ],
        },
        "prompt_config": {
            "system_prompt": "你是 Recruit Agent。你的核心职责是严格在招聘场景中维护候选人与投递记录事实，以投递记录为单位推进流程、记录证据，并把高风险动作交给人工确认。",
            "goal_template": goal_template,
            "context_slots": ["candidate_memory", "job_memory", "agent_global_memory", "candidate_thread", "candidate_progress"],
            "context_policy": default_context_policy(),
            "response_policy": {
                "prefer_structured_output": True,
                "require_evidence_refs": True,
                "separate_fact_from_inference": True,
            },
        },
        "playbook_blueprint": _adaptive_execution_to_payload(),
        "memory_policy": default_memory_policy(),
        "dashboard_config": {
            "layout": [
                "candidate_progress",
                "candidate_inbox",
                "agent_activity",
                "skill_health",
                "evolution_queue",
            ]
        },
        "channel_config": {
            "candidate_messaging": {"enabled": True, "requires_confirmation": True},
            "resume_request": {"enabled": True, "requires_confirmation": True},
            "talent_pool_upload": {"enabled": False, "mode": "future_integration"},
        },
        "agent_metadata": {
            "product_mode": "recruit_agent",
            "supports_builtin_agents": True,
            "current_primary_agent": "recruit-agent",
        },
    }


def ensure_primary_recruit_agent_profile(session: Session) -> RecruitAgentProfile:
    repo = RecruitAgentProfileRepository(session)
    existing = repo.primary()
    if existing is not None:
        prompt_config = dict(existing.prompt_config or {})
        resolved_context_policy = resolve_context_policy(prompt_config)
        resolved_goal_template = resolve_goal_template(prompt_config)
        resolved_memory_policy = resolve_memory_policy(existing.memory_policy)
        patch: dict[str, Any] = {}
        if prompt_config.get("context_policy") != resolved_context_policy:
            prompt_config["context_policy"] = resolved_context_policy
            patch["prompt_config"] = prompt_config
        if prompt_config.get("goal_template") != resolved_goal_template:
            prompt_config["goal_template"] = resolved_goal_template
            patch["prompt_config"] = prompt_config
        if existing.memory_policy != resolved_memory_policy:
            patch["memory_policy"] = resolved_memory_policy
        if patch:
            existing = repo.update(existing, patch)
        return existing
    try:
        return repo.create(default_recruit_agent_profile())
    except IntegrityError:
        session.rollback()
        existing = repo.primary()
        if existing is None:
            raise
        prompt_config = dict(existing.prompt_config or {})
        resolved_context_policy = resolve_context_policy(prompt_config)
        resolved_goal_template = resolve_goal_template(prompt_config)
        resolved_memory_policy = resolve_memory_policy(existing.memory_policy)
        patch: dict[str, Any] = {}
        if prompt_config.get("context_policy") != resolved_context_policy:
            prompt_config["context_policy"] = resolved_context_policy
            patch["prompt_config"] = prompt_config
        if prompt_config.get("goal_template") != resolved_goal_template:
            prompt_config["goal_template"] = resolved_goal_template
            patch["prompt_config"] = prompt_config
        if existing.memory_policy != resolved_memory_policy:
            patch["memory_policy"] = resolved_memory_policy
        if patch:
            existing = repo.update(existing, patch)
        return existing


def ensure_candidate_person_memory(
    session: Session,
    *,
    agent_profile_id: str,
    person_id: str,
) -> CandidatePersonMemory:
    repo = CandidatePersonMemoryRepository(session)
    memory = repo.by_agent_and_person(agent_profile_id=agent_profile_id, person_id=person_id)
    if memory is not None:
        return memory
    return repo.create(
        {
            "agent_profile_id": agent_profile_id,
            "person_id": person_id,
            "status": "active",
            "memory_schema_version": "candidate-person-memory-v1",
            "summary": "候选人长期记忆尚未整理。",
            "raw_content": {
                "identity_summary": "",
                "facts": [],
                "interaction_summary": [],
                "risk_flags": [],
                "open_questions": [],
                "recommended_next_actions": [],
                "evidence_refs": [],
                "confidence": "unknown",
            },
            "content": {
                "facts": [],
                "decisions": [],
                "open_questions": [],
                "next_actions": [],
                "risk_flags": [],
                "evidence_refs": [],
                "confidence": "unknown",
            },
            "disclosure": build_memory_disclosure(
                scope="candidate",
                summary="候选人长期记忆尚未整理。",
                content={"facts": [], "decisions": [], "open_questions": [], "next_actions": [], "risk_flags": [], "evidence_refs": [], "confidence": "unknown"},
                token_estimate=0,
            ),
            "token_estimate": 0,
            "source_count": 0,
            "memory_metadata": {"scope": "candidate_person", "isolation_key": person_id},
        }
    )


def ensure_job_description_memory(
    session: Session,
    *,
    agent_profile_id: str,
    job_description_id: str,
) -> JobDescriptionMemory:
    repo = JobDescriptionMemoryRepository(session)
    memory = repo.by_agent_and_job_description(agent_profile_id=agent_profile_id, job_description_id=job_description_id)
    if memory is not None:
        return memory
    return repo.create(
        {
            "agent_profile_id": agent_profile_id,
            "job_description_id": job_description_id,
            "status": "active",
            "memory_schema_version": "job-description-memory-v1",
            "summary": "岗位长期记忆尚未整理。",
            "raw_content": {
                "screening_preferences": [],
                "strong_positive_signals": [],
                "common_reject_reasons": [],
                "communication_notes": [],
                "quality_thresholds": [],
                "historical_patterns": [],
            },
            "content": {
                "facts": [],
                "decisions": [],
                "open_questions": [],
                "next_actions": [],
                "risk_flags": [],
                "evidence_refs": [],
                "confidence": "unknown",
            },
            "disclosure": build_memory_disclosure(
                scope="job",
                summary="岗位长期记忆尚未整理。",
                content={"facts": [], "decisions": [], "open_questions": [], "next_actions": [], "risk_flags": [], "evidence_refs": [], "confidence": "unknown"},
                token_estimate=0,
            ),
            "token_estimate": 0,
            "source_count": 0,
            "memory_metadata": {"scope": "job_description", "isolation_key": job_description_id},
        }
    )


def ensure_global_memory(
    session: Session,
    *,
    agent_profile_id: str,
) -> AgentGlobalMemory:
    repo = AgentGlobalMemoryRepository(session)
    memory = repo.by_agent(agent_profile_id)
    if memory is not None:
        if needs_agent_global_memory_projection(
            memory_schema_version=memory.memory_schema_version,
            summary=memory.summary,
            content=dict(memory.content or {}),
            raw_content=dict(memory.raw_content or {}),
            memory_metadata=dict(memory.memory_metadata or {}),
        ):
            runtime_link = dict(memory.raw_content or {})
            runtime_link_meta = dict(memory.memory_metadata or {})
            run_pk = str(runtime_link.get("run_pk") or runtime_link_meta.get("run_pk") or "").strip() or None
            conversation_pk = str(
                runtime_link.get("conversation_pk") or runtime_link_meta.get("conversation_pk") or ""
            ).strip() or None
            goal_kind: str | None = None
            goal_title: str | None = None
            round_status: str | None = None
            if run_pk:
                run = session.get(AgentRun, run_pk)
                if run is not None:
                    round_status = str(run.status or "").strip() or None
                    if conversation_pk is None:
                        conversation_pk = str((run.runtime_metadata or {}).get("conversation_id") or "").strip() or None
                    goal_spec = session.get(GoalSpec, run.goal_spec_id) if run.goal_spec_id else None
                    if goal_spec is not None:
                        goal_kind = str(goal_spec.goal_kind or "").strip() or None
                        goal_title = str(goal_spec.title or "").strip() or None
            projected = project_agent_global_memory(
                summary=memory.summary,
                content=dict(memory.content or {}),
                raw_content=dict(memory.raw_content or {}),
                goal_kind=goal_kind,
                goal_title=goal_title,
                round_status=round_status,
                source_kind=str((memory.memory_metadata or {}).get("source_kind") or memory.kind or "autonomous"),
                run_pk=run_pk,
                conversation_pk=conversation_pk,
            )
            metadata = dict(memory.memory_metadata or {})
            metadata.update(dict(projected.get("memory_metadata") or {}))
            metadata["normalized_from"] = str(memory.memory_schema_version or "legacy")
            memory = repo.update(
                memory,
                {
                    "memory_schema_version": GLOBAL_MEMORY_SCHEMA_VERSION,
                    "summary": projected["summary"],
                    "raw_content": dict(projected["raw_content"] or {}),
                    "content": dict(projected["content"] or {}),
                    "disclosure": build_memory_disclosure(
                        scope="agent_global",
                        summary=str(projected["summary"]),
                        content=dict(projected["content"] or {}),
                        token_estimate=content_length(dict(projected["content"] or {})),
                    ),
                    "token_estimate": content_length(dict(projected["content"] or {})),
                    "memory_metadata": metadata,
                },
            )
        return memory
    default_payload = empty_agent_global_memory_payload()
    return repo.create(
        {
            "agent_profile_id": agent_profile_id,
            "status": "active",
            "memory_schema_version": GLOBAL_MEMORY_SCHEMA_VERSION,
            "summary": default_payload["summary"],
            "raw_content": dict(default_payload["raw_content"] or {}),
            "content": dict(default_payload["content"] or {}),
            "disclosure": build_memory_disclosure(
                scope="agent_global",
                summary=str(default_payload["summary"]),
                content=dict(default_payload["content"] or {}),
                token_estimate=content_length(dict(default_payload["content"] or {})),
            ),
            "token_estimate": content_length(dict(default_payload["content"] or {})),
            "source_count": 0,
            "memory_metadata": dict(default_payload["memory_metadata"] or {}),
        }
    )


def content_length(content: dict[str, Any]) -> int:
    return len(json.dumps(content or {}, ensure_ascii=False))


def needs_compaction(content: dict[str, Any], *, threshold: int = AUTO_COMPACT_THRESHOLD) -> bool:
    return content_length(content) > threshold


def _fallback_compaction_payload(content: dict[str, Any], *, scope: str) -> dict[str, Any]:
    serialized = json.dumps(content or {}, ensure_ascii=False)
    excerpt = serialized[:1200]
    return {
        "summary": f"{scope} memory compacted with fallback summarization.",
        "content": {
            "facts": [],
            "decisions": [],
            "open_questions": [],
            "next_actions": [],
            "risk_flags": [],
            "evidence_refs": [],
            "confidence": "low",
            "excerpt": excerpt,
        },
    }


def compact_memory_payload(
    *,
    provider: LLMProvider,
    scope: str,
    content: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    prompt = (
        "你是 Recruit Agent 的 memory compactor。\n"
        "请把输入的 memory 压缩成结构化 JSON。\n"
        "要求：\n"
        "- 保留事实，不要编造。\n"
        "- 区分事实、决策、风险和待确认问题。\n"
        "- 只返回 JSON，不要附加解释。\n"
        "- 返回结构必须至少包含: summary, content.facts, content.decisions, content.open_questions, content.next_actions, content.risk_flags, content.evidence_refs, content.confidence\n"
        f"- 当前 memory scope: {scope}\n"
        f"- 当前 compact reason: {reason}\n"
    )
    try:
        response = provider.generate(
            [
                Message(role="system", content=prompt),
                Message(role="user", content=json.dumps(content or {}, ensure_ascii=False)),
            ],
            max_tokens=1200,
            temperature=0.1,
        )
        payload = json.loads(response.content or "{}")
        if isinstance(payload, dict) and isinstance(payload.get("content"), dict):
            payload.setdefault("summary", f"{scope} memory compacted.")
            return payload
    except (ProviderError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return _fallback_compaction_payload(content, scope=scope)


def apply_memory_compaction(
    record: CandidatePersonMemory | JobDescriptionMemory | AgentGlobalMemory,
    *,
    provider: LLMProvider,
    scope: str,
    reason: str,
    compacted_at: datetime,
) -> CandidatePersonMemory | JobDescriptionMemory | AgentGlobalMemory:
    original_raw_content = dict(record.raw_content or {}) or dict(record.content or {})
    compacted = compact_memory_payload(
        provider=provider,
        scope=scope,
        content=original_raw_content,
        reason=reason,
    )
    record.summary = str(compacted.get("summary") or record.summary or "")
    record.raw_content = original_raw_content
    record.content = dict(compacted.get("content") or {})
    record.disclosure = build_memory_disclosure(
        scope=scope,
        summary=record.summary,
        content=dict(record.content or {}),
        token_estimate=content_length(dict(record.content or {})),
    )
    record.token_estimate = content_length(record.content)
    record.compacted_at = compacted_at
    record.compacted_reason = reason
    metadata = dict(record.memory_metadata or {})
    history = list(metadata.get("compaction_history") or [])
    history.append({"at": compacted_at.isoformat(), "reason": reason, "token_estimate": record.token_estimate})
    metadata["compaction_history"] = history[-20:]
    record.memory_metadata = metadata
    return record
