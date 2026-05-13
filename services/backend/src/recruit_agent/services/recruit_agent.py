from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from recruit_agent.models import AgentDefinition
from recruit_agent.repositories import AgentDefinitionRepository


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
    "candidate_context",
    "job_context",
    "global_context",
    "assessments",
    "scorecards",
    "review_decisions",
    "skill_summary",
    "approval_context",
    "platform_context",
}
ALLOWED_PROMPT_CONFIG_KEYS = {
    "system_prompt",
    "systemPrompt",
    "prompt",
    "context_slots",
    "context_policy",
    "response_policy",
    "scoringRubric",
    "scoring_rubric",
    "rubric",
    "rubric_text",
    "recruitingPolicy",
    "recruiting_policy",
    "boundaries",
}

DEFAULT_CANDIDATE_STATUSES = [
    "discovered",
    "online_resume_fetching",
    "online_resume_acquired",
    "online_resume_passed",
    "online_resume_rejected",
    "offline_resume_fetching",
    "offline_resume_acquired",
    "offline_resume_passed",
    "offline_resume_rejected",
    "human_screening",
    "human_screening_passed",
    "human_screening_rejected",
    "profile_ready",
    "interview_pending",
    "interview_scheduled",
    "interview_passed",
    "interview_rejected",
    "offer_sent",
    "offer_accepted",
    "offer_rejected",
    "exception_closed",
]


def _playbook_stage_groups() -> list[dict[str, Any]]:
    return [
        {
            "id": "discovery",
            "name": "发现",
            "repeatable": False,
            "stages": [
                {"key": "discovered", "label": "已发现"},
            ],
        },
        {
            "id": "online_resume",
            "name": "在线简历",
            "repeatable": False,
            "stages": [
                {"key": "online_resume_fetching", "label": "在线简历获取中"},
                {"key": "online_resume_acquired", "label": "在线简历获取成功"},
                {"key": "online_resume_passed", "label": "在线简历评估通过"},
                {"key": "online_resume_rejected", "label": "在线简历评估淘汰"},
            ],
        },
        {
            "id": "offline_resume",
            "name": "离线简历",
            "repeatable": False,
            "stages": [
                {"key": "offline_resume_fetching", "label": "离线简历获取中"},
                {"key": "offline_resume_acquired", "label": "离线简历获取成功"},
                {"key": "offline_resume_passed", "label": "离线简历评估通过"},
                {"key": "offline_resume_rejected", "label": "离线简历评估淘汰"},
            ],
        },
        {
            "id": "human_screening",
            "name": "人工筛选",
            "repeatable": False,
            "stages": [
                {"key": "human_screening", "label": "人工筛选中"},
                {"key": "human_screening_passed", "label": "人工筛选通过"},
                {"key": "human_screening_rejected", "label": "人工筛选未通过"},
                {"key": "profile_ready", "label": "候选人资料准备完毕"},
            ],
        },
        {
            "id": "interviews",
            "name": "面试",
            "repeatable": True,
            "configurable_rounds": True,
            "default_rounds": [
                {"round": 1, "waiting_key": "interview_pending", "scheduled_key": "interview_scheduled"},
            ],
            "stages": [
                {"key": "interview_pending", "label": "待预约面试"},
                {"key": "interview_scheduled", "label": "面试已预约"},
                {"key": "interview_passed", "label": "面试通过"},
                {"key": "interview_rejected", "label": "面试未通过"},
            ],
        },
        {
            "id": "outcome",
            "name": "结果",
            "repeatable": False,
            "stages": [
                {"key": "offer_sent", "label": "Offer已发出"},
                {"key": "offer_accepted", "label": "Offer已接受"},
                {"key": "offer_rejected", "label": "Offer被拒"},
                {"key": "exception_closed", "label": "异常关闭"},
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
            "drop_order": ["global_context", "job_context", "platform_context", "session_context"],
        },
        "lanes": {
            "candidate": {
                "must_include": ["task_brief", "candidate_progress"],
                "default_weights": {
                    "recent_messages": 1.2,
                    "candidate_context": 1.1,
                    "job_context": 0.95,
                    "assessments": 1.0,
                    "scorecards": 1.0,
                    "review_decisions": 1.0,
                    "skill_summary": 0.75,
                    "global_context": 0.4,
                    "platform_context": 0.7,
                    "session_context": 0.85,
                },
            },
            "agent": {
                "must_include": ["task_brief", "approval_context"],
                "default_weights": {
                    "approval_context": 1.25,
                    "skill_summary": 1.05,
                    "global_context": 0.55,
                    "platform_context": 0.6,
                    "session_context": 0.5,
                },
            },
        },
        "run_type_overrides": {
            "candidate_outreach": {
                "prefer": ["recent_messages", "candidate_context", "job_context"],
                "suppress": ["global_context"],
            },
            "candidate_scoring": {
                "prefer": ["assessments", "scorecards", "job_context"],
                "suppress": ["global_context"],
            },
            "resume_collection": {
                "prefer": ["recent_messages", "candidate_progress", "candidate_context"],
                "suppress": ["global_context"],
            },
        },
    }


def default_memory_policy() -> dict[str, Any]:
    return {
        "writeback": {
            "enabled": True,
            "auto_write_min_confidence": 0.35,
            "max_stable_facts": 8,
            "trust_level": "agent_observed",
            "min_completed_turns_between_jobs": 3,
            "min_evidence_chars_between_jobs": 1500,
            "force_on_explicit_request": True,
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


def normalize_prompt_config(prompt_config: dict[str, Any] | None) -> dict[str, Any]:
    return {key: value for key, value in dict(prompt_config or {}).items() if key in ALLOWED_PROMPT_CONFIG_KEYS}


def resolve_memory_policy(memory_policy: dict[str, Any] | None) -> dict[str, Any]:
    defaults = default_memory_policy()
    configured = dict(memory_policy or {})
    resolved: dict[str, Any] = {}

    writeback_defaults = dict(defaults["writeback"])
    writeback_config = dict(configured.get("writeback") or {})
    resolved["writeback"] = {
        "enabled": bool(writeback_config.get("enabled", writeback_defaults["enabled"])),
        "auto_write_min_confidence": _bounded_float(
            writeback_config.get("auto_write_min_confidence"),
            default=float(writeback_defaults["auto_write_min_confidence"]),
        ),
        "max_stable_facts": _bounded_int(
            writeback_config.get("max_stable_facts"),
            default=int(writeback_defaults["max_stable_facts"]),
            minimum=0,
            maximum=32,
        ),
        "trust_level": str(writeback_config.get("trust_level") or writeback_defaults["trust_level"]),
        "min_completed_turns_between_jobs": _bounded_int(
            writeback_config.get("min_completed_turns_between_jobs"),
            default=int(writeback_defaults["min_completed_turns_between_jobs"]),
            minimum=0,
            maximum=100,
        ),
        "min_evidence_chars_between_jobs": _bounded_int(
            writeback_config.get("min_evidence_chars_between_jobs"),
            default=int(writeback_defaults["min_evidence_chars_between_jobs"]),
            minimum=0,
            maximum=200000,
        ),
        "force_on_explicit_request": bool(
            writeback_config.get(
                "force_on_explicit_request",
                writeback_defaults["force_on_explicit_request"],
            )
        ),
    }

    return resolved


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


def default_candidate_state_snapshot(
    *,
    status: str = "discovered",
    stage_key: str | None = None,
    stage_label: str | None = None,
) -> dict[str, Any]:
    resolved_stage_key = stage_key or status
    resolved_stage_label = stage_label or resolved_stage_key.replace("_", " ")
    recommended_stages_by_status = {
        "discovered": ["online_resume_fetching"],
        "online_resume_fetching": ["online_resume_acquired"],
        "online_resume_acquired": ["online_resume_passed", "online_resume_rejected"],
        "online_resume_passed": ["offline_resume_fetching"],
        "offline_resume_fetching": ["offline_resume_acquired"],
        "offline_resume_acquired": ["offline_resume_passed", "offline_resume_rejected"],
        "offline_resume_passed": ["human_screening"],
        "human_screening": ["human_screening_passed", "human_screening_rejected"],
        "human_screening_passed": ["profile_ready"],
        "profile_ready": ["interview_pending"],
        "interview_pending": ["interview_scheduled"],
        "interview_scheduled": ["interview_passed", "interview_rejected"],
        "interview_passed": ["offer_sent"],
        "offer_sent": ["offer_accepted", "offer_rejected"],
    }
    return {
        "current_phase_key": "discovery",
        "current_phase_label": "发现",
        "current_stage_key": resolved_stage_key,
        "current_stage_label": resolved_stage_label,
        "contact_status": "unknown",
        "contact_channels": [],
        "contact_acquired": False,
        "resume_status": "not_requested",
        "ai_assessment_status": "pending",
        "human_assessment_status": "pending",
        "operator_flags": [],
        "next_recommended_stages": recommended_stages_by_status.get(status, []),
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
        "snapshot_metadata": {"status_machine_version": "candidate-progress-v3"},
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
        "blueprint_id": "recruit-run-driven-v1",
        "name": "Recruit Run-Driven Runtime",
        "initial_stage": "exploration_trial",
        "version": 1,
        "stage_groups": _playbook_stage_groups(),
        "status_machine": {"default_statuses": DEFAULT_CANDIDATE_STATUSES, "mutable": True},
        "adaptive_stages": [
            {
                "id": "instruction_intake",
                "name": "Instruction Intake",
                "task_type": "instruction_intake",
                "requires_skill": False,
                "kind": "instruction",
                "purpose": "把用户输入、约束和成功标准归一成一次可执行运行输入。",
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
                "purpose": "把已验证的路径扩大到更多投递记录或更多任务范围。",
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
        "action_modes": [
            {
                "key": "candidate_review",
                "label": "投递记录评估",
                "initial_stage": "candidate_probe",
                "success_signals": ["online_resume_passed", "offline_resume_passed", "human_screening_passed"],
            },
            {
                "key": "candidate_outreach",
                "label": "投递记录跟进",
                "initial_stage": "candidate_outreach",
                "success_signals": ["offline_resume_fetching", "offline_resume_acquired", "profile_ready"],
            },
            {
                "key": "candidate_discovery",
                "label": "候选人发现",
                "initial_stage": "candidate_discovery",
                "success_signals": ["discovered", "online_resume_fetching"],
            },
        ],
    }


def default_agent_definition() -> dict[str, Any]:
    return {
        "definition_key": "recruit-agent",
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
            "system_prompt": _default_recruit_agent_system_prompt(),
            "context_slots": ["candidate_context", "job_context", "global_context", "candidate_thread", "candidate_progress"],
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
        "product_bindings": {
            "autonomous": {
                "enabled": True,
                "session_key": "autonomous",
                "definition_role": "primary_execution",
                "memory_scope": "agent_definition",
            },
            "assistant": {
                "enabled": True,
                "session_key": "assistant",
                "definition_role": "interactive_projection",
                "memory_scope": "agent_definition",
            },
        },
        "product_config": {
            "autonomous": {
                "context_policy": default_context_policy(),
                "memory_policy": default_memory_policy(),
            },
            "assistant": {
                "prompt_config": {
                    "system_prompt": "你是 Assistant 类型的 Recruit Agent。你的职责是在聊天界面中与用户协作，清晰解释状态、回答问题，并在高风险动作前等待确认。",
                    "context_policy": {
                        "memory_scope": "conversation",
                        "share_global_context": True,
                    },
                    "response_policy": {
                        "prefer_structured_output": False,
                        "require_evidence_refs": False,
                        "separate_fact_from_inference": True,
                    },
                },
                "memory_policy": default_memory_policy(),
            },
        },
        "product_projections": {
            "autonomous": {
                "name": "Autonomous",
                "description": "长期运行的招聘执行 Agent，负责按指令推进招聘任务、沉淀结果并请求必要审批。",
                "dashboard_config": {"layout": ["candidate_progress", "agent_activity", "skill_health", "evolution_queue"]},
                "channel_config": {
                    "candidate_messaging": {"enabled": True, "requires_confirmation": True},
                    "resume_request": {"enabled": True, "requires_confirmation": True},
                },
            },
            "assistant": {
                "name": "Assistant",
                "description": "面向聊天界面的协作助手，负责解释状态、回答问题，并在需要时等待人工确认。",
                "dashboard_config": {"layout": ["chat_sessions", "recent_activity"]},
                "channel_config": {"chat": {"enabled": True, "requires_confirmation": True}},
            },
        },
        "agent_metadata": {
            "product_mode": "recruit_agent",
            "supports_builtin_agents": True,
            "current_primary_definition": "recruit-agent",
        },
    }


def ensure_primary_agent_definition(session: Session) -> AgentDefinition:
    repo = AgentDefinitionRepository(session)
    existing = repo.primary()
    if existing is not None:
        original_prompt_config = dict(existing.prompt_config or {})
        prompt_config = normalize_prompt_config(original_prompt_config)
        resolved_context_policy = resolve_context_policy(prompt_config)
        resolved_memory_policy = resolve_memory_policy(existing.memory_policy)
        patch: dict[str, Any] = {}
        if prompt_config != original_prompt_config:
            patch["prompt_config"] = prompt_config
        if prompt_config.get("context_policy") != resolved_context_policy:
            prompt_config["context_policy"] = resolved_context_policy
            patch["prompt_config"] = prompt_config
        if existing.memory_policy != resolved_memory_policy:
            patch["memory_policy"] = resolved_memory_policy
        if patch:
            existing = repo.update(existing, patch)
        return existing
    try:
        return repo.create(default_agent_definition())
    except IntegrityError:
        session.rollback()
        existing = repo.primary()
        if existing is None:
            raise
        original_prompt_config = dict(existing.prompt_config or {})
        prompt_config = normalize_prompt_config(original_prompt_config)
        resolved_context_policy = resolve_context_policy(prompt_config)
        resolved_memory_policy = resolve_memory_policy(existing.memory_policy)
        patch: dict[str, Any] = {}
        if prompt_config != original_prompt_config:
            patch["prompt_config"] = prompt_config
        if prompt_config.get("context_policy") != resolved_context_policy:
            prompt_config["context_policy"] = resolved_context_policy
            patch["prompt_config"] = prompt_config
        if existing.memory_policy != resolved_memory_policy:
            patch["memory_policy"] = resolved_memory_policy
        if patch:
            existing = repo.update(existing, patch)
        return existing


def _default_recruit_agent_system_prompt() -> str:
    return "\n".join(
        [
            "你是 Recruit Agent。你的核心职责是严格在招聘场景中维护候选人与投递记录事实，以投递记录为单位推进流程、记录证据，并把高风险动作交给人工确认。",
            "你负责在共享招聘工作区中持续推进完整的招聘任务，而不是只停留在某一个孤立节点。",
            "默认覆盖 JD 同步、候选人发现、在线资料或在线简历读取、AI 评分、合规外联草拟、简历或补充材料索取、系统事实写回和后续交接。",
            "执行时优先利用当前会话、共享工作区、已有 JD、投递记录和可访问外部场景来拆解子任务。",
            "涉及外部站点时，优先复用普通浏览器里已经打开且可继续任务的页签；工具能力不足以确认时，应标记为工具能力阻塞。",
            "除非出现登录、验证码、权限、设备绑定、人工审批或其它明确 human-only blocker，否则不要只完成某一步就结束。",
            "若本轮只能完成一部分，在结果中明确区分已完成、待继续、已阻塞，以及每一项对应的系统内状态更新。",
        ]
    )
