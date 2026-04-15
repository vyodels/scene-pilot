from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

from pydantic import AliasChoices, BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from scene_pilot.db.base import utcnow
from scene_pilot.models import ApprovalItem, Skill, WorkflowPatch
from scene_pilot.repositories import (
    AgentLearningRepository,
    ApprovalRepository,
    EnvironmentSnapshotRepository,
    ExecutionEpisodeRepository,
    ExecutionPlanRepository,
    SkillRepository,
    TaskSpecRepository,
    WorkflowPatchRepository,
    WorkflowTemplateRepository,
)
from scene_pilot.schemas import (
    ActionAffordanceRead,
    ApprovalRead,
    CapabilityDriverRead,
    DomainPackRead,
    EnvironmentAssessmentRead,
    EnvironmentAssessmentRequest,
    EpisodeConfirmRequest,
    EnvironmentSnapshotCreate,
    EnvironmentSnapshotContextRead,
    EnvironmentSnapshotRead,
    ExecutionEpisodeCreate,
    ExecutionEpisodeRead,
    ExecutionEpisodeUpdate,
    ExecutionPlanReplanRead,
    ExecutionPlanReplanRequest,
    ExecutionPlanRead,
    LearningDraftRead,
    ObservedEntityRead,
    PlannerGuidanceRead,
    RuntimeEpisodeReplayRead,
    RuntimeReplayDiagnosticsRead,
    RuntimeReplayEventRead,
    RuntimeLearningOutcomeRead,
    SceneProfileRead,
    TaskCompileRequest,
    TaskCompilerContractRead,
    TaskCompileResponse,
    TaskSpecCreate,
    TaskSpecRead,
    TrialRunExecuteRequest,
    TrialRunRequest,
    WorkflowPatchCreate,
    WorkflowPatchDecisionRequest,
    WorkflowPatchRead,
    WorkflowTemplateCreate,
    WorkflowTemplateRead,
    WorkflowTemplateUpdate,
)
from scene_pilot.runtime.agent_loop import AgentLoop, AgentLoopConfig
from scene_pilot.runtime.models import AgentResult, Message
from scene_pilot.runtime.providers import ProviderError, ProviderRegistry, ScriptedProvider
from scene_pilot.runtime.prompts import PromptBuilder
from scene_pilot.runtime.result_semantics import extract_business_status
from scene_pilot.runtime.tools import ToolRegistry
from scene_pilot.services.skills import SkillHealthCheckService


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def _normalize_compile_outline_item(item: Any, *, index: int) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    text = str(item or "").strip()
    if not text:
        return {"id": f"step_{index + 1}", "action": f"Step {index + 1}"}
    return {"id": f"step_{index + 1}", "action": text}


def _normalize_compile_checkpoint_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    text = str(item or "").strip()
    if not text:
        return {"kind": "checkpoint", "label": "Unnamed checkpoint"}
    return {"kind": "checkpoint", "label": text}


_GENERIC_EXECUTION_RESULT_STATUSES = {
    "completed",
    "complete",
    "success",
    "ok",
    "done",
    "result",
    "default",
    "succeeded",
}


def _json_ready(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


DOMAIN_PACKS: dict[str, dict[str, Any]] = {
    "general": {
        "name": "内部通用能力",
        "description": "仅作为 Recruit Agent 内部执行内核的通用支持，不再作为独立产品场景暴露。",
        "version": "1.2.0",
        "maturity": "beta",
        "runtime_only": True,
        "default_capabilities": ["analyze", "browser", "llm", "document"],
        "sample_tasks": [
            "打开一个网站，观察页面后提炼有价值的信息。",
            "在人工监督下试跑一条新工作流，并提出后续修正建议。",
        ],
        "default_constraints": {"requires_human_supervision": True},
        "default_output_contract": {"kind": "summary", "format": "markdown"},
        "template_keys": ["general_supervised_trial", "patch_review_loop"],
        "compiler_hints": [
            "优先按能力驱动来组织步骤，而不是写死固定站点流程。",
            "在运行时证明可复用模式之前，默认都应先走受监督试跑。",
        ],
        "quality_gates": {
            "requires_goal_clarity": True,
            "requires_output_contract": True,
            "requires_trial": True,
        },
        "scene_expectations": ["web_scene", "interactive_surface", "local_runtime"],
        "trial_expectations": {"requires_supervised_trial": True, "requires_scene_assessment_for_browser": True},
    },
    "recruiting": {
        "name": "招聘",
        "description": "寻找候选人、获取档案上下文、完成简历初筛，并准备经过批准的交接材料。",
        "version": "1.1.0",
        "maturity": "beta",
        "runtime_only": True,
        "default_capabilities": ["browser", "search", "document", "llm", "api"],
        "sample_tasks": [
            "找到匹配候选人，提取简历，并在上传前完成评分。",
            "查看候选人档案、记录证据，并整理招聘备注。",
        ],
        "default_constraints": {"requires_human_supervision": True, "respect_messaging_approval": True},
        "default_output_contract": {"kind": "candidate_bundle", "fields": ["resume", "score", "notes"]},
        "template_keys": ["recruiting_trial_screening"],
        "compiler_hints": [
            "把招聘网站和内网系统都视为运行时场景，而不是固定集成。",
            "简历获取、评分和后续写入步骤必须始终保留审批感知。",
        ],
        "quality_gates": {
            "requires_candidate_evidence": True,
            "requires_score": True,
            "requires_downstream_write_review": True,
        },
        "scene_expectations": ["listing_surface", "detail_surface", "submission_scene"],
        "trial_expectations": {"requires_supervised_trial": True, "requires_scene_assessment_for_browser": True},
    },
    "archived_public_briefing": {
        "name": "归档示例：资讯汇总",
        "description": "归档的内部回归样例，仅保留为执行内核验证用途。",
        "version": "0.4.0",
        "maturity": "experimental",
        "runtime_only": True,
        "default_capabilities": ["search", "http", "browser", "llm", "document"],
        "sample_tasks": [
            "查找最新股市新闻，并整理带来源的摘要。",
            "总结最能影响市场的头条，并解释它们为什么重要。",
        ],
        "default_constraints": {"requires_source_links": True},
        "default_output_contract": {"kind": "news_digest", "format": "bullet_summary"},
        "template_keys": ["archived_public_briefing_digest"],
        "compiler_hints": [
            "保留一手来源链接，并让摘要聚焦当前市场影响。",
            "在做文章综合之前，优先完成来源发现。",
        ],
        "quality_gates": {
            "requires_source_links": True,
            "minimum_sources": 3,
            "include_market_impact": True,
        },
        "scene_expectations": ["listing_surface", "detail_surface", "news_page"],
        "trial_expectations": {"minimum_sources": 3, "requires_scene_assessment_for_browser": True},
    },
    "archived_public_research": {
        "name": "归档示例：公开网页比较",
        "description": "归档的内部回归样例，仅保留为执行内核验证用途。",
        "version": "0.4.0",
        "maturity": "experimental",
        "runtime_only": True,
        "default_capabilities": ["search", "browser", "http", "llm", "document"],
        "sample_tasks": [
            "对公开网页结果做候选项比较并生成 shortlist。",
            "在全网研究工具，并说明为什么值得尝试。",
        ],
        "default_constraints": {"requires_source_links": True},
        "default_output_contract": {"kind": "research_shortlist", "format": "table"},
        "template_keys": ["archived_public_research_shortlist"],
        "compiler_hints": [
            "优先输出带理由、链接和取舍说明的候选清单。",
            "当场景仍在探索阶段时，先用搜索和浏览器观察，再做最终综合。",
        ],
        "quality_gates": {
            "requires_source_links": True,
            "minimum_candidates": 3,
            "requires_comparison": True,
        },
        "scene_expectations": ["listing_surface", "detail_surface", "tool_listing"],
        "trial_expectations": {"minimum_candidates": 3, "requires_scene_assessment_for_browser": True},
    },
    "archived_repository_watch": {
        "name": "归档示例：公开仓库观察",
        "description": "归档的内部回归样例，仅保留为执行内核验证用途。",
        "version": "0.4.0",
        "maturity": "experimental",
        "runtime_only": True,
        "default_capabilities": ["http", "search", "browser", "llm", "document"],
        "sample_tasks": [
            "列出今天的热门仓库，并附上链接和一句话摘要。",
            "追踪热门开源项目，并整理一份简明简报。",
        ],
        "default_constraints": {"requires_source_links": True},
        "default_output_contract": {"kind": "repository_digest", "format": "table"},
        "template_keys": ["archived_repository_watch_digest"],
        "compiler_hints": [
            "保留仓库链接、一句话摘要，以及项目为什么值得关注的证据。",
            "先用 HTTP 或搜索做广度发现，再用浏览器完成细节核验。",
        ],
        "quality_gates": {
            "requires_source_links": True,
            "minimum_repositories": 5,
            "requires_project_summary": True,
        },
        "scene_expectations": ["listing_surface", "detail_surface", "repository_listing"],
        "trial_expectations": {"minimum_repositories": 5, "requires_scene_assessment_for_browser": True},
    },
}


CAPABILITY_DRIVERS: dict[str, dict[str, Any]] = {
    "analyze": {
        "description": "在不改变环境的前提下分析任务、比较证据，或决定下一步动作。",
        "risk": "low",
        "signal_labels": ["task_contract", "plan_fit", "divergence_signal"],
        "executor_mode": "deliberate",
        "replan_on_error": False,
        "scene_required": False,
        "preferred_tools": ["record_observation", "advance_plan_step", "submit_result"],
        "checkpoint_policy": {"checkpoint_on_divergence": True},
    },
    "browser": {
        "description": "把网站和 Web 应用当作运行时场景进行观察或交互。",
        "risk": "medium",
        "signal_labels": [
            "observed_entities",
            "action_affordances",
            "scene_profile",
            "auth_gate",
            "verification_gate",
            "navigation_target",
        ],
        "executor_mode": "observe_act",
        "replan_on_error": True,
        "scene_required": True,
        "preferred_tools": [
            "record_observation",
            "advance_plan_step",
            "request_replan",
            "request_human_checkpoint",
            "submit_result",
        ],
        "checkpoint_policy": {
            "requires_scene_assessment": True,
            "checkpoint_on_auth_gate": True,
            "checkpoint_on_write_surface": True,
        },
    },
    "search": {
        "description": "在搜索界面中发现相关目标、来源、候选项或备选方案。",
        "risk": "low",
        "signal_labels": ["query_intent", "result_listing", "ranking_signal"],
        "executor_mode": "discover",
        "replan_on_error": False,
        "scene_required": False,
        "preferred_tools": [
            "record_observation",
            "advance_plan_step",
            "submit_result",
        ],
        "checkpoint_policy": {"checkpoint_on_empty_results": True},
    },
    "http": {
        "description": "调用结构化 HTTP 或 API 接口，读取或写入面向机器的数据。",
        "risk": "medium",
        "signal_labels": ["endpoint_schema", "response_contract", "transport_state"],
        "executor_mode": "request_response",
        "replan_on_error": True,
        "scene_required": False,
        "preferred_tools": ["record_observation", "advance_plan_step", "request_replan", "submit_result"],
        "checkpoint_policy": {"checkpoint_on_schema_mismatch": True},
    },
    "document": {
        "description": "起草、摘要或格式化可长期保存的输出材料。",
        "risk": "low",
        "signal_labels": ["artifact_outline", "summary_contract", "handoff_bundle"],
        "executor_mode": "artifact",
        "replan_on_error": False,
        "scene_required": False,
        "preferred_tools": ["record_observation", "advance_plan_step", "submit_result"],
        "checkpoint_policy": {"checkpoint_before_publish": False},
    },
    "filesystem": {
        "description": "在运行时策略控制下读取、写入、暂存或整理本地文件与目录。",
        "risk": "medium",
        "signal_labels": ["path_target", "artifact_store", "file_state"],
        "executor_mode": "local_io",
        "replan_on_error": True,
        "scene_required": False,
        "preferred_tools": ["record_observation", "advance_plan_step", "request_human_checkpoint", "submit_result"],
        "checkpoint_policy": {"checkpoint_on_write": True},
    },
    "api": {
        "description": "把结构化数据写入下游系统或服务。",
        "risk": "high",
        "signal_labels": ["write_contract", "destination_system", "sync_result"],
        "executor_mode": "downstream_write",
        "replan_on_error": True,
        "scene_required": False,
        "preferred_tools": ["record_observation", "advance_plan_step", "request_human_checkpoint", "submit_result"],
        "checkpoint_policy": {"checkpoint_before_write": True, "checkpoint_after_write": True},
    },
    "command": {
        "description": "在审批和策略控制下执行本地系统命令。",
        "risk": "high",
        "signal_labels": ["command_intent", "stdout_signal", "system_mutation"],
        "executor_mode": "command",
        "replan_on_error": True,
        "scene_required": False,
        "preferred_tools": ["record_observation", "advance_plan_step", "request_human_checkpoint", "submit_result"],
        "checkpoint_policy": {"requires_approval": True, "checkpoint_on_mutation": True},
    },
    "llm": {
        "description": "把推理、综合或分类任务交给语言模型运行时处理。",
        "risk": "low",
        "signal_labels": ["prompt_contract", "synthesis_result", "classification_signal"],
        "executor_mode": "reason",
        "replan_on_error": False,
        "scene_required": False,
        "preferred_tools": ["record_observation", "advance_plan_step", "submit_result"],
        "checkpoint_policy": {"checkpoint_on_low_confidence": True},
    },
    "approval": {
        "description": "在人工审查或审批检查点暂停流程。",
        "risk": "low",
        "signal_labels": ["review_gate", "human_decision", "approval_reason"],
        "executor_mode": "checkpoint",
        "replan_on_error": False,
        "scene_required": False,
        "preferred_tools": ["request_human_checkpoint", "record_observation", "advance_plan_step", "submit_result"],
        "checkpoint_policy": {"requires_approval": True},
    },
}


DEFAULT_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_key": "general_supervised_trial",
        "name": "通用受监督试跑",
        "domain": "general",
        "status": "active",
        "version": 1,
        "template_body": {
            "steps": [
                {"id": "understand_task", "capability": "analyze"},
                {"id": "inspect_environment", "capability": "browser"},
                {"id": "execute_goal", "capability": "llm"},
                {"id": "summarize_result", "capability": "document"},
            ]
        },
        "activation_strategy": {"mode": "trial_first"},
        "validation_summary": "通用受监督运行时工作流的基线版本。",
    },
    {
        "template_key": "patch_review_loop",
        "name": "修订审查循环",
        "domain": "general",
        "status": "active",
        "version": 1,
        "template_body": {
            "steps": [
                {"id": "inspect_patch", "capability": "analyze"},
                {"id": "review_risk", "capability": "approval"},
                {"id": "decide_rollout", "capability": "llm"},
            ]
        },
        "activation_strategy": {"mode": "approval_gated"},
        "validation_summary": "工作流修订建议的种子审查模板。",
    },
    {
        "template_key": "recruiting_trial_screening",
        "name": "招聘试跑初筛",
        "domain": "recruiting",
        "status": "active",
        "version": 1,
        "template_body": {
            "steps": [
                {"id": "open_workspace", "capability": "browser"},
                {"id": "locate_candidates", "capability": "search"},
                {"id": "capture_candidate_context", "capability": "document"},
                {"id": "score_candidate", "capability": "llm"},
                {"id": "prepare_handoff", "capability": "api"},
            ]
        },
        "activation_strategy": {"mode": "trial_first", "requires_approval": True},
        "validation_summary": "用于 Recruit Agent 受监督初筛的种子版本。",
    },
    {
        "template_key": "archived_public_briefing_digest",
        "name": "归档示例：资讯汇总摘要",
        "domain": "archived_public_briefing",
        "status": "active",
        "version": 1,
        "template_body": {
            "steps": [
                {"id": "collect_headlines", "capability": "search"},
                {"id": "open_sources", "capability": "browser"},
                {"id": "rank_events", "capability": "llm"},
                {"id": "draft_digest", "capability": "document"},
            ]
        },
        "activation_strategy": {"mode": "trial_first"},
        "validation_summary": "归档的资讯汇总回归样例模板。",
    },
    {
        "template_key": "archived_public_research_shortlist",
        "name": "归档示例：公开网页候选清单",
        "domain": "archived_public_research",
        "status": "active",
        "version": 1,
        "template_body": {
            "steps": [
                {"id": "search_candidates", "capability": "search"},
                {"id": "inspect_tools", "capability": "browser"},
                {"id": "compare_findings", "capability": "llm"},
                {"id": "produce_shortlist", "capability": "document"},
            ]
        },
        "activation_strategy": {"mode": "trial_first"},
        "validation_summary": "用于网页工具研究和 shortlist 的种子模板。",
    },
    {
        "template_key": "archived_repository_watch_digest",
        "name": "归档示例：公开仓库摘要",
        "domain": "archived_repository_watch",
        "status": "active",
        "version": 1,
        "template_body": {
            "steps": [
                {"id": "collect_trending_repos", "capability": "http"},
                {"id": "inspect_repository_pages", "capability": "browser"},
                {"id": "summarize_repositories", "capability": "llm"},
                {"id": "publish_digest", "capability": "document"},
            ]
        },
        "activation_strategy": {"mode": "trial_first"},
        "validation_summary": "归档的公开仓库观察回归样例模板。",
    },
)


class CompilePlanRequest(BaseModel):
    task_spec_id: str
    workflow_template_id: str | None = None
    name: str | None = None
    mode: str = "trial"
    status: str = "draft"
    compiled_from_instruction: str | None = Field(
        default=None,
        validation_alias=AliasChoices("compiled_from_instruction", "instruction"),
    )
    environment_requirements: dict[str, Any] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    steps: list[dict[str, Any]] = Field(default_factory=list)


class SemanticTaskCompileDraft(BaseModel):
    title: str | None = None
    description: str | None = None
    goal: str
    domain: str = "general"
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    approval_policy: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    preferred_capabilities: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)
    environment_requirements: dict[str, Any] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    step_outline: list[dict[str, Any]] = Field(default_factory=list)
    compiler_notes: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class CompiledTaskDraft:
    task_spec: TaskSpecCreate
    domain_key: str
    compiler_name: str
    compiler_notes: list[str]


@dataclass(slots=True)
class ManagedExecutionContext:
    task_spec: TaskSpecRead
    execution_plan: ExecutionPlanRead
    execution_episode: ExecutionEpisodeRead
    assessment: EnvironmentAssessmentRead
    capability_drivers: list[CapabilityDriverRead]
    execution_contract: dict[str, Any]


@dataclass(slots=True)
class PersistedRuntimeService:
    session: Session
    providers: ProviderRegistry | None = None
    tools: ToolRegistry | None = None
    prompt_builder: PromptBuilder = field(default_factory=PromptBuilder)
    allow_heuristic_fallback: bool = False

    def list_domain_packs(self) -> list[DomainPackRead]:
        return [self._domain_pack_read(key, config) for key, config in DOMAIN_PACKS.items()]

    def get_task_compiler_contract(self) -> TaskCompilerContractRead:
        return TaskCompilerContractRead(
            contract_version="runtime-task-compiler-v4",
            strategy="llm_first_structured_semantic_compiler",
            fallback_strategy="heuristic_domain_and_capability_inference" if self.allow_heuristic_fallback else "none",
            prompt_asset="tasks/runtime_task_compiler.md",
            required_fields=[
                "goal",
                "domain",
                "constraints",
                "success_criteria",
                "approval_policy",
                "output_contract",
            ],
            optional_fields=[
                "inputs",
                "preferred_capabilities",
                "preferred_domains",
                "environment_requirements",
                "checkpoints",
                "step_outline",
                "compiler_notes",
            ],
            invariants=[
                "The compiler must not assume any fixed site integration during development time.",
                "The compiler must emit a structured task contract before execution begins.",
                "LLM task compilation is mandatory unless heuristic fallback is explicitly enabled by runtime policy.",
                "Write-oriented actions must remain approval-aware even when inferred at compile time.",
            ],
            quality_gates=[
                "Goal and output contract must be concrete enough to run a supervised trial.",
                "Write-oriented or outbound actions must remain approval-aware.",
                "Browser-oriented tasks should declare environment requirements or scene checkpoints.",
                "Domain-pack quality gates should be reflected in success criteria or output contract.",
            ],
            repair_policy={
                "max_repair_passes": 1,
                "repair_triggers": [
                    "invalid_json",
                    "schema_validation_error",
                    "critical_quality_gap",
                ],
                "fallback_on_failure": "heuristic_domain_and_capability_inference" if self.allow_heuristic_fallback else "none",
            },
            available_domains=self.list_domain_packs(),
            available_capabilities=self.list_capability_drivers(),
        )

    def list_capability_drivers(self, *, domain: str | None = None) -> list[CapabilityDriverRead]:
        normalized_domain = self._normalize_domain(domain)
        items: list[CapabilityDriverRead] = []
        for key, config in CAPABILITY_DRIVERS.items():
            supported_domains = [
                domain_key
                for domain_key, domain_config in DOMAIN_PACKS.items()
                if key in list(domain_config.get("default_capabilities") or [])
            ]
            if normalized_domain and normalized_domain not in supported_domains:
                continue
            items.append(
                CapabilityDriverRead(
                    key=key,
                    description=str(config["description"]),
                    risk=str(config["risk"]),
                    supported_domains=supported_domains,
                    recommended_scene_types=self._recommended_scene_types_for_capability(key),
                    signal_labels=list(config.get("signal_labels") or []),
                    executor_mode=str(config.get("executor_mode") or "tool_loop"),
                    replan_on_error=bool(config.get("replan_on_error", False)),
                    scene_required=bool(config.get("scene_required", False)),
                    preferred_tools=list(config.get("preferred_tools") or []),
                    checkpoint_policy=dict(config.get("checkpoint_policy") or {}),
                    writes_state=key in {"api", "command"},
                    requires_supervision=key in {"browser", "api", "command"} or str(config["risk"]) == "high",
                    audit_tags=[f"risk:{config['risk']}", "generic_runtime"],
                )
            )
        return items

    def assess_environment(self, payload: EnvironmentAssessmentRequest) -> EnvironmentAssessmentRead:
        task_spec, plan, episode, snapshot_context, persisted_snapshot = self._resolve_assessment_context(payload)
        domain = (
            (task_spec.domain if task_spec is not None else None)
            or (plan.plan_body or {}).get("domain") if plan is not None else None
        ) or "general"
        compiler_payload = dict(payload.compiler_payload or {})
        observed_entities = self._normalize_observed_entities(snapshot_context)
        affordances = self._normalize_affordances(snapshot_context)
        scene_type = self._derive_scene_type(snapshot_context, observed_entities=observed_entities, affordances=affordances)
        scene_profile = self._derive_scene_profile(
            snapshot=snapshot_context,
            scene_type=scene_type,
            observed_entities=observed_entities,
            affordances=affordances,
        )
        recommended_capabilities = self._derive_assessment_capabilities(
            task_spec=task_spec,
            plan=plan,
            snapshot=snapshot_context,
            compiler_payload=compiler_payload,
            scene_profile=scene_profile,
        )
        scene_key = (
            snapshot_context.environment_key
            if snapshot_context is not None and snapshot_context.environment_key
            else f"{self._normalize_domain(domain)}:{scene_type}"
        )
        blockers = self._derive_assessment_blockers(
            plan=plan,
            episode=episode,
            snapshot=snapshot_context,
            recommended_capabilities=recommended_capabilities,
            scene_profile=scene_profile,
        )
        scene_profile = scene_profile.model_copy(update={"blockers": blockers})
        planner_guidance = self._derive_planner_guidance(
            scene_profile=scene_profile,
            recommended_capabilities=recommended_capabilities,
            blockers=blockers,
            compiler_payload=compiler_payload,
        )
        plan_fit = "blocked" if blockers else "aligned"
        if blockers and not any(item.startswith("missing_") for item in blockers):
            plan_fit = "partial"
        environment_requirements = self._merge_dicts(
            self._default_environment_requirements(str(domain), recommended_capabilities),
            dict(plan.environment_requirements or {}) if plan is not None else {},
        )
        environment_requirements = self._merge_dicts(
            environment_requirements,
            dict(compiler_payload.get("environment_requirements") or {}),
        )
        environment_requirements = self._merge_dicts(
            environment_requirements,
            self._environment_requirements_from_snapshot(
                snapshot_context,
                observed_entities=observed_entities,
                affordances=affordances,
                scene_profile=scene_profile,
            ),
        )
        checkpoints = self._dedupe_dict_list(
            [
                *(list(plan.checkpoints or []) if plan is not None else []),
                *self._assessment_checkpoints(
                    blockers=blockers,
                    snapshot=snapshot_context,
                    scene_profile=scene_profile,
                    planner_guidance=planner_guidance,
                ),
                *list(payload.plan_context.get("checkpoints") or []),
            ]
        )
        confidence = self._derive_assessment_confidence(
            snapshot=snapshot_context,
            observed_entities=observed_entities,
            affordances=affordances,
            blockers=blockers,
            plan=plan,
        )
        if blockers:
            confidence = max(0.35, confidence - 0.18)
        assessment_notes = self._build_assessment_notes(
            domain=str(domain),
            scene_type=scene_type,
            blockers=blockers,
            recommended_capabilities=recommended_capabilities,
            compiler_payload=compiler_payload,
            scene_profile=scene_profile,
            planner_guidance=planner_guidance,
        )
        audit_metadata = {
            "site_assumption_policy": "generic_only",
            "task_spec_id": task_spec.id if task_spec is not None else payload.task_spec_id,
            "execution_plan_id": plan.id if plan is not None else payload.execution_plan_id,
            "execution_episode_id": episode.id if episode is not None else payload.execution_episode_id,
            "environment_snapshot_id": persisted_snapshot.id if persisted_snapshot is not None else payload.environment_snapshot_id,
            "compiler_payload_keys": sorted(str(key) for key in compiler_payload.keys()),
            "plan_context_keys": sorted(str(key) for key in payload.plan_context.keys()),
            "scene_profile_signals": list(scene_profile.signals),
        }
        return EnvironmentAssessmentRead(
            task_spec=TaskSpecRead.model_validate(task_spec) if task_spec is not None else None,
            execution_plan=ExecutionPlanRead.model_validate(plan) if plan is not None else None,
            execution_episode=ExecutionEpisodeRead.model_validate(episode) if episode is not None else None,
            snapshot=snapshot_context,
            scene_type=scene_type,
            scene_key=scene_key,
            confidence=round(confidence, 2),
            plan_fit=plan_fit,
            observed_entities=observed_entities,
            affordances=affordances,
            scene_profile=scene_profile,
            planner_guidance=planner_guidance,
            recommended_capabilities=recommended_capabilities,
            blockers=blockers,
            environment_requirements=environment_requirements,
            checkpoints=checkpoints,
            assessment_notes=assessment_notes,
            audit_metadata=audit_metadata,
        )

    def list_environment_assessments(
        self,
        *,
        execution_plan_id: str | None = None,
        task_spec_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EnvironmentAssessmentRead]:
        plan_repo = ExecutionPlanRepository(self.session)
        episode_repo = ExecutionEpisodeRepository(self.session)
        snapshot_repo = EnvironmentSnapshotRepository(self.session)

        plans = (
            plan_repo.by_task_spec(task_spec_id, limit=limit, offset=offset)
            if task_spec_id
            else plan_repo.list(limit=limit, offset=offset)
        )
        if execution_plan_id is not None:
            plans = [plan for plan in plans if plan.id == execution_plan_id]

        assessments: list[EnvironmentAssessmentRead] = []
        for plan in plans:
            latest_episode = next(iter(episode_repo.by_plan(plan.id, limit=1, offset=0)), None)
            latest_snapshot = snapshot_repo.latest_for_episode(latest_episode.id) if latest_episode is not None else None
            assessments.append(
                self.assess_environment(
                    EnvironmentAssessmentRequest(
                        task_spec_id=plan.task_spec_id,
                        execution_plan_id=plan.id,
                        execution_episode_id=latest_episode.id if latest_episode is not None else None,
                        environment_snapshot_id=latest_snapshot.id if latest_snapshot is not None else None,
                    )
                )
            )
        return assessments

    def replan_execution(self, plan_id: str, payload: ExecutionPlanReplanRequest) -> ExecutionPlanReplanRead:
        plan_repo = ExecutionPlanRepository(self.session)
        task_repo = TaskSpecRepository(self.session)
        episode_repo = ExecutionEpisodeRepository(self.session)
        current_plan = plan_repo.get(plan_id)
        if current_plan is None:
            raise ValueError("Execution plan not found")
        task_spec = task_repo.get(current_plan.task_spec_id)
        if task_spec is None:
            raise ValueError("Task spec not found")
        source_episode = episode_repo.get(payload.execution_episode_id) if payload.execution_episode_id else None

        assessment = self.assess_environment(
            EnvironmentAssessmentRequest(
                task_spec_id=task_spec.id,
                execution_plan_id=current_plan.id,
                execution_episode_id=payload.execution_episode_id,
                environment_snapshot_id=payload.environment_snapshot_id,
                snapshot=payload.snapshot,
                compiler_payload=payload.compiler_payload,
                plan_context=payload.plan_context,
            )
        )
        if source_episode is not None and source_episode.divergence_detected:
            assessment = self._coerce_recovery_assessment(
                assessment,
                reason=str(payload.reason or "Runtime divergence requested a safer recovery plan."),
            )
        compiler_payload = dict(payload.compiler_payload or {})
        compiler_notes = [str(item) for item in compiler_payload.get("compiler_notes", []) if str(item).strip()]
        compiler_notes.extend(assessment.assessment_notes)

        new_steps = self._derive_replanned_steps(
            current_steps=list((current_plan.plan_body or {}).get("steps") or []),
            assessment=assessment,
            compiler_payload=compiler_payload,
        )
        new_checkpoints = self._dedupe_dict_list(
            [
                *list(current_plan.checkpoints or []),
                *assessment.checkpoints,
                *list(compiler_payload.get("checkpoints") or []),
                *list(payload.checkpoints or []),
            ]
        )
        new_environment_requirements = self._merge_dicts(
            dict(current_plan.environment_requirements or {}),
            assessment.environment_requirements,
        )
        new_environment_requirements = self._merge_dicts(
            new_environment_requirements,
            dict(payload.plan_context.get("environment_requirements") or {}),
        )

        audit_entry = {
            "at": utcnow().isoformat(),
            "requested_by": payload.requested_by,
            "reason": payload.reason,
            "source_plan_id": current_plan.id,
            "source_episode_id": payload.execution_episode_id,
            "source_snapshot_id": payload.environment_snapshot_id,
            "scene_type": assessment.scene_type,
            "plan_fit": assessment.plan_fit,
            "blockers": list(assessment.blockers),
            "planner_posture": assessment.planner_guidance.posture,
            "site_assumption_policy": "generic_only",
        }
        runtime_metadata = {
            **dict(current_plan.runtime_metadata or {}),
            **dict(payload.runtime_metadata or {}),
            "replanned_from_plan_id": current_plan.id,
            "replan_reason": payload.reason,
            "replan_requested_by": payload.requested_by,
            "replan_assessment": {
                "scene_type": assessment.scene_type,
                "scene_key": assessment.scene_key,
                "plan_fit": assessment.plan_fit,
                "recommended_capabilities": list(assessment.recommended_capabilities),
                "blockers": list(assessment.blockers),
                "planner_posture": assessment.planner_guidance.posture,
                "scene_signals": list(assessment.scene_profile.signals),
            },
            "planner_guidance": assessment.planner_guidance.model_dump(),
            "scene_profile": assessment.scene_profile.model_dump(),
            "replan_history": [
                *list((current_plan.runtime_metadata or {}).get("replan_history") or []),
                audit_entry,
            ],
            "site_assumption_policy": "generic_only",
        }
        if compiler_payload:
            runtime_metadata["replan_compiler_payload"] = compiler_payload

        status = "planned" if assessment.plan_fit != "aligned" else "validated"
        approval_state = "pending_review" if assessment.blockers else "unreviewed"
        replanned = plan_repo.create(
            {
                "task_spec_id": current_plan.task_spec_id,
                "name": payload.name or f"{current_plan.name} 重规划 v{int(current_plan.version) + 1}",
                "mode": current_plan.mode,
                "status": status,
                "version": int(current_plan.version) + 1,
                "approval_state": approval_state,
                "plan_body": {
                    **dict(current_plan.plan_body or {}),
                    "steps": new_steps,
                    "instruction": (current_plan.plan_body or {}).get("instruction") or task_spec.source_text or task_spec.goal,
                    "domain": (current_plan.plan_body or {}).get("domain") or task_spec.domain,
                },
                "environment_requirements": new_environment_requirements,
                "checkpoints": new_checkpoints,
                "runtime_metadata": runtime_metadata,
                "compiled_from_patch_id": current_plan.compiled_from_patch_id,
            }
        )
        if payload.preserve_active_plan:
            task_repo.update(task_spec, {"active_plan_id": replanned.id})

        audit_metadata = {
            **assessment.audit_metadata,
            "replanned_from_plan_id": current_plan.id,
            "replanned_to_plan_id": replanned.id,
            "site_assumption_policy": "generic_only",
        }
        return ExecutionPlanReplanRead(
            id=replanned.id,
            task_spec_id=current_plan.task_spec_id,
            base_execution_plan_id=current_plan.id,
            previous_plan=ExecutionPlanRead.model_validate(current_plan),
            execution_plan=ExecutionPlanRead.model_validate(replanned),
            assessment=assessment,
            status="replanned",
            summary=str(payload.reason or "已根据最新运行时场景生成修订后的执行计划。"),
            compiler_notes=compiler_notes,
            recommended_capability_keys=list(assessment.recommended_capabilities),
            audit_metadata=audit_metadata,
            created_at=replanned.updated_at,
        )

    def _coerce_recovery_assessment(
        self,
        assessment: EnvironmentAssessmentRead,
        *,
        reason: str,
    ) -> EnvironmentAssessmentRead:
        blockers = list(assessment.blockers or [])
        if "divergence_detected" not in blockers:
            blockers.append("divergence_detected")
        guidance = assessment.planner_guidance.model_copy(
            update={
                "posture": "recover",
                "requires_human_review": True,
                "should_checkpoint": True,
                "rationale": [
                    *list(assessment.planner_guidance.rationale or []),
                    reason,
                ],
            }
        )
        scene_profile = assessment.scene_profile.model_copy(
            update={"blockers": list(dict.fromkeys([*list(assessment.scene_profile.blockers or []), *blockers]))}
        )
        return assessment.model_copy(
            update={
                "plan_fit": "blocked",
                "blockers": blockers,
                "planner_guidance": guidance,
                "scene_profile": scene_profile,
            }
        )

    def _replan_assessment_from_metadata(
        self,
        *,
        plan,
        task_spec: TaskSpecRead | None,
    ) -> EnvironmentAssessmentRead:
        metadata = dict(plan.runtime_metadata or {})
        assessment_payload = dict(metadata.get("replan_assessment") or {})
        recommended_capabilities = [
            str(item)
            for item in list(assessment_payload.get("recommended_capabilities") or [])
            if str(item).strip()
        ]
        blockers = [str(item) for item in list(assessment_payload.get("blockers") or []) if str(item).strip()]
        planner_posture = str(assessment_payload.get("planner_posture") or "recover")
        scene_signals = [str(item) for item in list(assessment_payload.get("scene_signals") or []) if str(item).strip()]
        scene_type = str(assessment_payload.get("scene_type") or "runtime_scene")
        scene_key = str(assessment_payload.get("scene_key") or f"{task_spec.domain if task_spec is not None else 'general'}:{scene_type}")
        environment_requirements = dict(plan.environment_requirements or {})
        return EnvironmentAssessmentRead(
            task_spec=task_spec,
            execution_plan=ExecutionPlanRead.model_validate(plan),
            execution_episode=None,
            snapshot=None,
            scene_type=scene_type,
            scene_key=scene_key,
            confidence=0.74,
            plan_fit=str(assessment_payload.get("plan_fit") or ("blocked" if blockers else "partial")),
            observed_entities=[],
            affordances=[],
            scene_profile=SceneProfileRead(
                source="runtime_metadata",
                scene_type=scene_type,
                interaction_mode="inspect",
                volatility="medium",
                auth_state="unknown",
                entity_count=0,
                affordance_count=0,
                primary_targets=[],
                signals=scene_signals,
                blockers=blockers,
                evidence={},
            ),
            planner_guidance=PlannerGuidanceRead(
                posture=planner_posture,
                required_capabilities=recommended_capabilities,
                inserted_capabilities=[],
                preferred_next_actions=[],
                requires_scene_assessment=bool(environment_requirements.get("scene_assessment_required")),
                requires_human_review=planner_posture == "recover" or bool(blockers),
                should_checkpoint=True,
                rationale=["已根据持久化的重规划元数据还原场景评估。"],
            ),
            recommended_capabilities=recommended_capabilities,
            blockers=blockers,
            environment_requirements=environment_requirements,
            checkpoints=list(plan.checkpoints or []),
            assessment_notes=[],
            audit_metadata={"site_assumption_policy": str(metadata.get("site_assumption_policy") or "generic_only")},
        )

    def compile_task(self, payload: TaskCompileRequest) -> TaskCompileResponse:
        compiled = self._compile_task_spec(payload)
        domain_config = DOMAIN_PACKS[compiled.domain_key]
        task = self.create_task_spec(compiled.task_spec)

        plan = None
        if payload.auto_plan:
            plan = self.compile_plan(
                CompilePlanRequest(
                    task_spec_id=task.id,
                    name=f"{task.title} 试跑计划",
                    mode="trial",
                    status="planned",
                    compiled_from_instruction=payload.instruction,
                    runtime_metadata={
                        "compiler": compiled.compiler_name,
                        "requested_by": payload.requested_by,
                    },
                )
            )
            task_repo = TaskSpecRepository(self.session)
            task_model = task_repo.get(task.id)
            if task_model is not None:
                task = TaskSpecRead.model_validate(
                    task_repo.update(
                        task_model,
                        {"active_plan_id": plan.id, "status": "trial_ready"},
                    )
                )

        return TaskCompileResponse(
            domain_pack=self._domain_pack_read(compiled.domain_key, domain_config),
            compiler_notes=compiled.compiler_notes,
            task_spec=task,
            execution_plan=plan,
        )

    def _compile_task_spec(self, payload: TaskCompileRequest) -> CompiledTaskDraft:
        llm_draft, llm_errors = self._compile_task_spec_with_llm(payload)
        if llm_draft is not None:
            return llm_draft
        if self.allow_heuristic_fallback:
            return self._compile_task_spec_heuristic(payload, notes=llm_errors)
        if llm_errors:
            raise ValueError("LLM 任务编译失败：" + " ".join(llm_errors))
        raise ValueError("任务编译依赖 LLM，但当前没有可用的非脚本化 Provider。")

    def _compile_task_spec_with_llm(self, payload: TaskCompileRequest) -> tuple[CompiledTaskDraft | None, list[str]]:
        if self.providers is None:
            return None, ["当前没有为语义任务编译配置 Provider 注册表。"]

        errors: list[str] = []
        for provider_name in self._semantic_compiler_provider_names():
            provider = self.providers.providers.get(provider_name)
            if provider is None:
                continue
            response = None
            repair_messages: list[Message] | None = None
            try:
                compile_messages = self._build_semantic_compile_messages(payload)
                response = provider.generate(
                    compile_messages,
                    task={
                        "task_type": "semantic_task_compile",
                        "instruction": payload.instruction,
                        "output_schema": "SemanticTaskCompileDraft",
                    },
                    max_tokens=1_400,
                    temperature=0.1,
                )
                draft = self._parse_semantic_compile_response(response)
                quality_review = self._review_semantic_compile_candidate(payload=payload, draft=draft)
                if quality_review["critical_issues"]:
                    repair_messages = self._build_semantic_compile_quality_repair_messages(
                        payload,
                        response,
                        quality_review,
                    )
                    raise ValueError(
                        "语义编译结果存在关键质量缺口："
                        + ", ".join(list(quality_review["critical_issues"]))
                    )
                compiler_notes = list(draft.compiler_notes or [])
                compiler_notes.append(f"语义任务编译已通过 Provider {provider_name} 成功完成。")
                return (
                    self._materialize_compiled_task_draft(
                        payload=payload,
                        draft=draft,
                        compiler_name="llm_structured",
                        compiler_notes=compiler_notes,
                        provider_name=provider_name,
                        quality_warnings=list(quality_review["warnings"]),
                    ),
                    [],
                )
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                if response is None:
                    errors.append(f"LLM 语义编译器通过 {provider_name} 执行失败：{exc}。")
                    continue
                try:
                    repaired_response = provider.generate(
                        repair_messages or self._build_semantic_compile_repair_messages(payload, response, str(exc)),
                        task={
                            "task_type": "semantic_task_compile_repair",
                            "instruction": payload.instruction,
                            "output_schema": "SemanticTaskCompileDraft",
                        },
                        max_tokens=1_400,
                        temperature=0.0,
                    )
                    draft = self._parse_semantic_compile_response(repaired_response)
                    quality_review = self._review_semantic_compile_candidate(payload=payload, draft=draft)
                    if quality_review["critical_issues"]:
                        raise ValueError(
                            "Critical semantic compile quality gaps remained after repair: "
                            + ", ".join(list(quality_review["critical_issues"]))
                        )
                    compiler_notes = list(draft.compiler_notes or [])
                    compiler_notes.append(
                        f"语义任务编译已通过 Provider {provider_name} 成功完成，并执行了一次修复。"
                    )
                    return (
                        self._materialize_compiled_task_draft(
                            payload=payload,
                            draft=draft,
                            compiler_name="llm_structured",
                            compiler_notes=compiler_notes,
                            provider_name=provider_name,
                            quality_warnings=list(quality_review["warnings"]),
                            repair_count=1,
                        ),
                        [],
                    )
                except (ProviderError, ValidationError, ValueError, json.JSONDecodeError) as repair_exc:
                    errors.append(
                        f"LLM 语义编译器通过 {provider_name} 首次校验失败（{exc}），"
                        f"且修复流程也失败（{repair_exc}）。"
                    )
            except ProviderError as exc:
                errors.append(f"LLM 语义编译器通过 {provider_name} 执行失败：{exc}。")

        if not errors:
            errors.append("当前没有可用于语义任务编译的非脚本化 Provider。")
        return None, errors

    def _compile_task_spec_heuristic(
        self,
        payload: TaskCompileRequest,
        *,
        notes: list[str] | None = None,
    ) -> CompiledTaskDraft:
        compiler_notes = list(notes or [])
        domain_key, domain_config, heuristic_notes = self._resolve_domain_pack(
            payload.domain_hint,
            payload.instruction,
            payload.preferred_domains,
        )
        compiler_notes.extend(heuristic_notes)
        capabilities = self._infer_capabilities(payload.instruction, domain_key, payload.preferred_capabilities)
        constraints = self._merge_dicts(domain_config.get("default_constraints") or {}, payload.constraints)
        success_criteria = payload.success_criteria or self._default_success_criteria(domain_key)
        approval_policy = self._merge_dicts(
            self._default_approval_policy(payload.instruction, capabilities),
            payload.approval_policy,
        )
        output_contract = self._merge_dicts(dict(domain_config.get("default_output_contract") or {}), payload.output_contract)
        compiler_notes.append("已回退到启发式任务编译器。")
        quality_audit = self._build_compiler_quality_audit(
            compiler_name="heuristic",
            domain_key=domain_key,
            domain_config=domain_config,
            instruction=payload.instruction,
            capabilities=capabilities,
            success_criteria=success_criteria,
            approval_policy=approval_policy,
            output_contract=output_contract,
            environment_requirements={},
            checkpoints=[],
            step_outline=[],
            compiler_notes=compiler_notes,
            fallback_used=True,
            warnings=["由于语义编译不可用或结果无效，系统已回退到启发式编译。"],
        )
        return CompiledTaskDraft(
            task_spec=TaskSpecCreate(
                title=payload.title or self._derive_title(payload.instruction, domain_config["name"]),
                description=payload.description or f"Compiled from natural language for {domain_config['name']}.",
                goal=self._derive_goal(payload.instruction),
                domain=domain_key,
                status="compiled",
                source_kind="natural_language",
                source_text=payload.instruction,
                inputs=dict(payload.inputs),
                constraints=constraints,
                success_criteria=success_criteria,
                approval_policy=approval_policy,
                output_contract=output_contract,
                preferred_capabilities=capabilities,
                preferred_domains=list(dict.fromkeys([domain_key, *payload.preferred_domains])),
                compiled_payload={
                    "task_key": self._slugify(payload.title or payload.instruction),
                    "compiler": "heuristic",
                    "compiler_notes": compiler_notes,
                    "domain_pack": domain_key,
                    "keyword_hits": self._keyword_hits(payload.instruction),
                    "requires_trial": True,
                    "compiler_quality": quality_audit,
                },
            ),
            domain_key=domain_key,
            compiler_name="heuristic",
            compiler_notes=compiler_notes,
        )

    def _materialize_compiled_task_draft(
        self,
        *,
        payload: TaskCompileRequest,
        draft: SemanticTaskCompileDraft,
        compiler_name: str,
        compiler_notes: list[str],
        provider_name: str | None,
        quality_warnings: list[str] | None = None,
        repair_count: int = 0,
    ) -> CompiledTaskDraft:
        domain_key, domain_config, domain_notes = self._select_compiled_domain(
            compiled_domain=draft.domain,
            domain_hint=payload.domain_hint,
            instruction=payload.instruction,
            preferred_domains=payload.preferred_domains,
        )
        notes = [*compiler_notes, *domain_notes]
        capabilities = self._select_compiled_capabilities(
            compiled_capabilities=draft.preferred_capabilities,
            instruction=payload.instruction,
            domain_key=domain_key,
            preferred_capabilities=payload.preferred_capabilities,
        )
        constraints = self._merge_dicts(domain_config.get("default_constraints") or {}, draft.constraints)
        constraints = self._merge_dicts(constraints, payload.constraints)
        success_criteria = self._merge_dicts(self._default_success_criteria(domain_key), draft.success_criteria)
        success_criteria = self._merge_dicts(success_criteria, payload.success_criteria)
        approval_policy = self._merge_dicts(self._default_approval_policy(payload.instruction, capabilities), draft.approval_policy)
        approval_policy = self._merge_dicts(approval_policy, payload.approval_policy)
        output_contract = self._merge_dicts(dict(domain_config.get("default_output_contract") or {}), draft.output_contract)
        output_contract = self._merge_dicts(output_contract, payload.output_contract)
        preferred_domains = list(
            dict.fromkeys(
                [
                    domain_key,
                    *[self._normalize_domain(item) for item in draft.preferred_domains],
                    *payload.preferred_domains,
                ]
            )
        )

        title = payload.title or draft.title or self._derive_title(payload.instruction, domain_config["name"])
        description = payload.description or draft.description or f"Semantically compiled for {domain_config['name']}."
        goal = draft.goal.strip() if draft.goal.strip() else self._derive_goal(payload.instruction)
        quality_audit = self._build_compiler_quality_audit(
            compiler_name=compiler_name,
            domain_key=domain_key,
            domain_config=domain_config,
            instruction=payload.instruction,
            capabilities=capabilities,
            success_criteria=success_criteria,
            approval_policy=approval_policy,
            output_contract=output_contract,
            environment_requirements=dict(draft.environment_requirements or {}),
            checkpoints=list(draft.checkpoints or []),
            step_outline=list(draft.step_outline or []),
            compiler_notes=notes,
            fallback_used=False,
            warnings=list(quality_warnings or []),
            repair_count=repair_count,
        )

        return CompiledTaskDraft(
            task_spec=TaskSpecCreate(
                title=title,
                description=description,
                goal=goal,
                domain=domain_key,
                status="compiled",
                source_kind="natural_language",
                source_text=payload.instruction,
                inputs=self._merge_dicts(draft.inputs, payload.inputs),
                constraints=constraints,
                success_criteria=success_criteria,
                approval_policy=approval_policy,
                output_contract=output_contract,
                preferred_capabilities=capabilities,
                preferred_domains=preferred_domains,
                compiled_payload={
                    "task_key": self._slugify(title or payload.instruction),
                    "compiler": compiler_name,
                    "compiler_provider": provider_name,
                    "compiler_notes": notes,
                    "domain_pack": domain_key,
                    "requires_trial": True,
                    "capability_catalog": list(CAPABILITY_DRIVERS.keys()),
                    "environment_requirements": dict(draft.environment_requirements or {}),
                    "checkpoints": list(draft.checkpoints or []),
                    "step_outline": list(draft.step_outline or []),
                    "compiler_quality": quality_audit,
                },
            ),
            domain_key=domain_key,
            compiler_name=compiler_name,
            compiler_notes=notes,
        )

    def _semantic_compiler_provider_names(self) -> list[str]:
        if self.providers is None:
            return []
        provider_names: list[str] = []
        for provider_name in self.providers.fallback_order:
            provider = self.providers.providers.get(provider_name)
            if provider is None or isinstance(provider, ScriptedProvider):
                continue
            provider_names.append(provider_name)
        return provider_names

    def _build_semantic_compile_messages(self, payload: TaskCompileRequest) -> list[Message]:
        domain_catalog = {
            key: {
                "description": value["description"],
                "default_capabilities": value["default_capabilities"],
                "default_constraints": value["default_constraints"],
                "default_output_contract": value["default_output_contract"],
                "compiler_hints": value.get("compiler_hints") or [],
                "quality_gates": value.get("quality_gates") or {},
                "scene_expectations": value.get("scene_expectations") or [],
                "trial_expectations": value.get("trial_expectations") or {},
            }
            for key, value in DOMAIN_PACKS.items()
        }
        capability_catalog = {
            key: {
                "description": value["description"],
                "risk": value["risk"],
                "signal_labels": value.get("signal_labels", []),
            }
            for key, value in CAPABILITY_DRIVERS.items()
        }
        compiler_request = {
            "instruction": payload.instruction,
            "title_hint": payload.title,
            "description_hint": payload.description,
            "domain_hint": payload.domain_hint,
            "inputs": payload.inputs,
            "constraints": payload.constraints,
            "success_criteria": payload.success_criteria,
            "approval_policy": payload.approval_policy,
            "output_contract": payload.output_contract,
            "preferred_capabilities": payload.preferred_capabilities,
            "preferred_domains": payload.preferred_domains,
            "available_domains": domain_catalog,
            "available_capabilities": capability_catalog,
            "compiler_contract": {
                "required_fields": self.get_task_compiler_contract().required_fields,
                "optional_fields": self.get_task_compiler_contract().optional_fields,
                "quality_gates": self.get_task_compiler_contract().quality_gates,
            },
        }
        base_parts = [
            self.prompt_builder.loader.load_text(path).strip()
            for path in self.prompt_builder.base_prompts
        ]
        compiler_prompt = self.prompt_builder.loader.load_text("tasks/runtime_task_compiler.md").strip()
        system_prompt = "\n\n---\n\n".join(part for part in [*base_parts, compiler_prompt] if part)
        user_prompt = self.prompt_builder.build_user_prompt(
            "runtime_task_compiler",
            context={
                "request": json.dumps(compiler_request, ensure_ascii=False, indent=2),
            },
        )
        return [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

    def _build_semantic_compile_quality_repair_messages(
        self,
        payload: TaskCompileRequest,
        response,
        quality_report: dict[str, Any],
    ) -> list[Message]:
        original_messages = self._build_semantic_compile_messages(payload)
        prior_output = ""
        if isinstance(response.result_data, dict):
            prior_output = json.dumps(response.result_data, ensure_ascii=False)
        elif response.content:
            prior_output = response.content
        elif response.raw:
            prior_output = json.dumps(response.raw, ensure_ascii=False)
        repair_prompt = json.dumps(
            {
                "repair_reason": "critical_quality_gap",
                "quality_report": quality_report,
                "instructions": [
                    "Return corrected JSON only.",
                    "Preserve the same SemanticTaskCompileDraft schema.",
                    "Fix the listed quality gaps without introducing site-specific assumptions.",
                    "If the task implies browser scenes, keep environment requirements and checkpoints explicit.",
                ],
                "prior_output": prior_output,
            },
            ensure_ascii=False,
            indent=2,
        )
        return [
            *original_messages,
            Message(role="assistant", content=prior_output),
            Message(role="user", content=repair_prompt),
        ]

    def _build_semantic_compile_repair_messages(
        self,
        payload: TaskCompileRequest,
        response,
        error: str,
    ) -> list[Message]:
        original_messages = self._build_semantic_compile_messages(payload)
        prior_output = ""
        if isinstance(response.result_data, dict):
            prior_output = json.dumps(response.result_data, ensure_ascii=False)
        elif response.content:
            prior_output = response.content
        elif response.raw:
            prior_output = json.dumps(response.raw, ensure_ascii=False)
        repair_prompt = json.dumps(
            {
                "repair_error": error,
                "instructions": [
                    "Return corrected JSON only.",
                    "Keep the same schema as SemanticTaskCompileDraft.",
                    "If a field is unknown, use an empty object, empty list, or the 'general' domain instead of prose.",
                    "Preserve approval-aware handling for write-oriented or outbound actions.",
                ],
                "invalid_output": prior_output,
            },
            ensure_ascii=False,
            indent=2,
        )
        return [
            *original_messages,
            Message(role="assistant", content=prior_output),
            Message(role="user", content=repair_prompt),
        ]

    def _parse_semantic_compile_response(self, response) -> SemanticTaskCompileDraft:
        if isinstance(response.result_data, dict):
            payload = dict(response.result_data)
            payload["checkpoints"] = [
                _normalize_compile_checkpoint_item(item)
                for item in list(payload.get("checkpoints") or [])
            ]
            payload["step_outline"] = [
                _normalize_compile_outline_item(item, index=index)
                for index, item in enumerate(list(payload.get("step_outline") or []))
            ]
            return SemanticTaskCompileDraft.model_validate(payload)

        content = (response.content or "").strip()
        if not content:
            raise ValueError("Compiler returned an empty response")
        payload = self._extract_json_object(content)
        payload["checkpoints"] = [
            _normalize_compile_checkpoint_item(item)
            for item in list(payload.get("checkpoints") or [])
        ]
        payload["step_outline"] = [
            _normalize_compile_outline_item(item, index=index)
            for index, item in enumerate(list(payload.get("step_outline") or []))
        ]
        return SemanticTaskCompileDraft.model_validate(payload)

    def _review_semantic_compile_candidate(
        self,
        *,
        payload: TaskCompileRequest,
        draft: SemanticTaskCompileDraft,
    ) -> dict[str, Any]:
        domain_key, domain_config, _ = self._select_compiled_domain(
            compiled_domain=draft.domain,
            domain_hint=payload.domain_hint,
            instruction=payload.instruction,
            preferred_domains=payload.preferred_domains,
        )
        capabilities = self._select_compiled_capabilities(
            compiled_capabilities=draft.preferred_capabilities,
            instruction=payload.instruction,
            domain_key=domain_key,
            preferred_capabilities=payload.preferred_capabilities,
        )
        critical_issues: list[str] = []
        warnings: list[str] = []

        if len((draft.goal or "").strip()) < 12:
            critical_issues.append("goal_too_brief")
        if not isinstance(draft.success_criteria, dict) or not draft.success_criteria:
            critical_issues.append("missing_success_criteria")
        if not isinstance(draft.output_contract, dict) or not draft.output_contract:
            critical_issues.append("missing_output_contract")

        approval_policy = self._merge_dicts(
            self._default_approval_policy(payload.instruction, capabilities),
            draft.approval_policy,
        )
        approval_policy = self._merge_dicts(approval_policy, payload.approval_policy)
        approval_actions = {
            str(item).strip().lower()
            for item in list(approval_policy.get("approval_actions") or [])
            if str(item).strip()
        }
        write_or_outbound_requested = any(cap in capabilities for cap in ("api", "command", "filesystem")) or any(
            token in payload.instruction.lower()
            for token in ("upload", "sync", "push", "write", "save", "send", "message", "command", "shell")
        )
        if write_or_outbound_requested and not approval_actions:
            critical_issues.append("missing_write_or_outbound_approval")

        browser_or_web_requested = "browser" in capabilities or any(
            token in payload.instruction.lower()
            for token in ("website", "web", "browser", "page", "open ")
        )
        if browser_or_web_requested and not dict(draft.environment_requirements or {}):
            warnings.append("missing_browser_environment_requirements")
        if browser_or_web_requested and not list(draft.checkpoints or []):
            warnings.append("missing_browser_checkpoints")
        if not list(draft.step_outline or []):
            warnings.append("missing_step_outline")
        if not list(draft.compiler_notes or []):
            warnings.append("missing_compiler_notes")

        quality_gates = dict(domain_config.get("quality_gates") or {})
        if quality_gates.get("requires_source_links"):
            merged_text = json.dumps(
                {
                    "constraints": draft.constraints,
                    "success_criteria": draft.success_criteria,
                    "output_contract": draft.output_contract,
                },
                ensure_ascii=False,
            ).lower()
            if "source" not in merged_text and "link" not in merged_text and "citation" not in merged_text:
                warnings.append("domain_quality_gate_source_links_not_explicit")
        minimum_sources = quality_gates.get("minimum_sources")
        if isinstance(minimum_sources, int) and minimum_sources > 0:
            actual = int(dict(draft.success_criteria or {}).get("minimum_sources") or 0)
            if actual < minimum_sources:
                warnings.append("domain_quality_gate_minimum_sources_not_met")
        minimum_candidates = quality_gates.get("minimum_candidates")
        if isinstance(minimum_candidates, int) and minimum_candidates > 0:
            actual = int(dict(draft.success_criteria or {}).get("minimum_candidates") or 0)
            if actual < minimum_candidates:
                warnings.append("domain_quality_gate_minimum_candidates_not_met")
        minimum_repositories = quality_gates.get("minimum_repositories")
        if isinstance(minimum_repositories, int) and minimum_repositories > 0:
            actual = int(dict(draft.success_criteria or {}).get("minimum_repositories") or 0)
            if actual < minimum_repositories:
                warnings.append("domain_quality_gate_minimum_repositories_not_met")

        return {
            "domain_key": domain_key,
            "capabilities": capabilities,
            "critical_issues": list(dict.fromkeys(critical_issues)),
            "warnings": list(dict.fromkeys(warnings)),
        }

    def _build_compiler_quality_audit(
        self,
        *,
        compiler_name: str,
        domain_key: str,
        domain_config: dict[str, Any],
        instruction: str,
        capabilities: list[str],
        success_criteria: dict[str, Any],
        approval_policy: dict[str, Any],
        output_contract: dict[str, Any],
        environment_requirements: dict[str, Any],
        checkpoints: list[dict[str, Any]],
        step_outline: list[dict[str, Any]],
        compiler_notes: list[str],
        fallback_used: bool,
        warnings: list[str] | None = None,
        repair_count: int = 0,
    ) -> dict[str, Any]:
        quality_gates = dict(domain_config.get("quality_gates") or {})
        warnings_list = list(dict.fromkeys(warnings or []))
        satisfied_gates: dict[str, bool] = {
            "has_success_criteria": bool(success_criteria),
            "has_output_contract": bool(output_contract),
            "has_step_outline": bool(step_outline),
            "has_checkpoints": bool(checkpoints),
            "has_compiler_notes": bool(compiler_notes),
        }
        if "browser" in capabilities or any(token in instruction.lower() for token in ("web", "browser", "website", "page", "open ")):
            satisfied_gates["has_environment_requirements"] = bool(environment_requirements)
        approval_actions = {
            str(item).strip().lower()
            for item in list(approval_policy.get("approval_actions") or [])
            if str(item).strip()
        }
        if any(cap in capabilities for cap in ("api", "command", "filesystem")):
            satisfied_gates["write_actions_are_approval_aware"] = bool(approval_actions)
        if quality_gates.get("requires_source_links"):
            quality_blob = json.dumps(
                {
                    "success_criteria": success_criteria,
                    "output_contract": output_contract,
                    "approval_policy": approval_policy,
                },
                ensure_ascii=False,
            ).lower()
            satisfied_gates["source_links_are_explicit"] = any(
                token in quality_blob for token in ("source", "link", "citation")
            )
        if isinstance(quality_gates.get("minimum_sources"), int):
            satisfied_gates["minimum_sources_met"] = int(success_criteria.get("minimum_sources") or 0) >= int(
                quality_gates["minimum_sources"]
            )
        if isinstance(quality_gates.get("minimum_candidates"), int):
            satisfied_gates["minimum_candidates_met"] = int(success_criteria.get("minimum_candidates") or 0) >= int(
                quality_gates["minimum_candidates"]
            )
        if isinstance(quality_gates.get("minimum_repositories"), int):
            satisfied_gates["minimum_repositories_met"] = int(
                success_criteria.get("minimum_repositories") or 0
            ) >= int(quality_gates["minimum_repositories"])

        quality_score = 1.0
        quality_score -= 0.05 * len([value for value in satisfied_gates.values() if not value])
        quality_score -= 0.04 * len(warnings_list)
        if fallback_used:
            quality_score -= 0.08
        if repair_count:
            quality_score -= min(0.08, repair_count * 0.04)
        quality_score = max(0.25, min(0.99, round(quality_score, 2)))

        quality_status = "accepted"
        if fallback_used:
            quality_status = "fallback"
        if not all(satisfied_gates.values()):
            quality_status = "guardrailed" if quality_status == "accepted" else quality_status

        return {
            "contract_version": "runtime-task-compiler-v4",
            "compiler": compiler_name,
            "quality_status": quality_status,
            "quality_score": quality_score,
            "fallback_used": fallback_used,
            "repair_count": repair_count,
            "domain_pack_version": str(domain_config.get("version") or "1.0.0"),
            "quality_gates": quality_gates,
            "gates_satisfied": satisfied_gates,
            "warnings": warnings_list,
        }

    def _extract_json_object(self, content: str) -> dict[str, Any]:
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, flags=re.DOTALL)
        if fenced:
            return dict(json.loads(fenced.group(1)))

        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("Compiler response did not contain a JSON object")
        return dict(json.loads(content[start : end + 1]))

    def _select_compiled_domain(
        self,
        *,
        compiled_domain: str,
        domain_hint: str | None,
        instruction: str,
        preferred_domains: list[str],
    ) -> tuple[str, dict[str, Any], list[str]]:
        notes: list[str] = []
        hinted_domain = self._normalize_domain(domain_hint)
        if hinted_domain in DOMAIN_PACKS:
            notes.append(f"Respected explicit domain hint: {hinted_domain}.")
            return hinted_domain, DOMAIN_PACKS[hinted_domain], notes

        normalized = self._normalize_domain(compiled_domain)
        if normalized in DOMAIN_PACKS:
            notes.append(f"Selected execution profile from semantic compiler output: {normalized}.")
            return normalized, DOMAIN_PACKS[normalized], notes

        fallback_domain, fallback_config, fallback_notes = self._resolve_domain_pack(None, instruction, preferred_domains)
        notes.append(f"Semantic compiler proposed unknown domain '{compiled_domain}'.")
        notes.extend(fallback_notes)
        return fallback_domain, fallback_config, notes

    def _select_compiled_capabilities(
        self,
        *,
        compiled_capabilities: list[str],
        instruction: str,
        domain_key: str,
        preferred_capabilities: list[str],
    ) -> list[str]:
        cleaned = [str(item).strip().lower() for item in compiled_capabilities if str(item).strip()]
        accepted = [item for item in cleaned if item in CAPABILITY_DRIVERS]
        if not accepted:
            accepted = self._infer_capabilities(instruction, domain_key, [])
        accepted.extend(preferred_capabilities)
        return list(dict.fromkeys(accepted))

    def _default_approval_policy(self, instruction: str, capabilities: list[str]) -> dict[str, Any]:
        actions: list[str] = []
        normalized_instruction = instruction.lower()
        keyword_actions = {
            "upload": "write_to_downstream_system",
            "push": "write_to_downstream_system",
            "sync": "write_to_downstream_system",
            "send": "outbound_communication",
            "message": "outbound_communication",
            "command": "local_command",
            "terminal": "local_command",
            "shell": "local_command",
        }
        for keyword, action in keyword_actions.items():
            if keyword in normalized_instruction:
                actions.append(action)
        if "api" in capabilities:
            actions.append("write_to_downstream_system")
        if "command" in capabilities:
            actions.append("local_command")

        return {
            "mode": "desktop_review",
            "trial_required": True,
            "requires_confirmation_before_production": True,
            "requires_environment_snapshot": "browser" in capabilities,
            "approval_actions": list(dict.fromkeys(actions)),
        }

    def list_task_specs(self, *, domain: str | None = None, limit: int = 100, offset: int = 0) -> list[TaskSpecRead]:
        repo = TaskSpecRepository(self.session)
        items = repo.by_domain(domain, limit=limit, offset=offset) if domain else repo.list(limit=limit, offset=offset)
        return [TaskSpecRead.model_validate(item) for item in items]

    def create_task_spec(self, payload: TaskSpecCreate) -> TaskSpecRead:
        item = TaskSpecRepository(self.session).create(payload)
        return TaskSpecRead.model_validate(item)

    def get_task_spec(self, task_spec_id: str) -> TaskSpecRead:
        item = TaskSpecRepository(self.session).get(task_spec_id)
        if item is None:
            raise ValueError("Task spec not found")
        return TaskSpecRead.model_validate(item)

    def list_plans(self, *, task_spec_id: str | None = None, limit: int = 100, offset: int = 0) -> list[ExecutionPlanRead]:
        repo = ExecutionPlanRepository(self.session)
        items = repo.by_task_spec(task_spec_id, limit=limit, offset=offset) if task_spec_id else repo.list(limit=limit, offset=offset)
        return [ExecutionPlanRead.model_validate(item) for item in items]

    def list_replans(self, *, limit: int = 100, offset: int = 0) -> list[ExecutionPlanReplanRead]:
        plan_repo = ExecutionPlanRepository(self.session)
        task_repo = TaskSpecRepository(self.session)
        replans: list[ExecutionPlanReplanRead] = []
        for plan in plan_repo.list(limit=limit + offset + 200, offset=0):
            metadata = dict(plan.runtime_metadata or {})
            previous_plan_id = str(metadata.get("replanned_from_plan_id") or "").strip()
            if not previous_plan_id:
                continue
            previous_plan = plan_repo.get(previous_plan_id)
            if previous_plan is None:
                continue
            task_spec = task_repo.get(plan.task_spec_id)
            task_spec_read = TaskSpecRead.model_validate(task_spec) if task_spec is not None else None
            assessment = self._replan_assessment_from_metadata(plan=plan, task_spec=task_spec_read)
            compiler_notes = [
                str(item)
                for item in list((metadata.get("replan_compiler_payload") or {}).get("compiler_notes") or [])
                if str(item).strip()
            ]
            replans.append(
                ExecutionPlanReplanRead(
                    id=plan.id,
                    task_spec_id=plan.task_spec_id,
                    base_execution_plan_id=previous_plan.id,
                    previous_plan=ExecutionPlanRead.model_validate(previous_plan),
                    execution_plan=ExecutionPlanRead.model_validate(plan),
                    assessment=assessment,
                    status="replanned",
                    summary=str(
                        metadata.get("replan_reason")
                        or (assessment.assessment_notes[0] if assessment.assessment_notes else "")
                        or "已根据最新运行时场景生成修订后的执行计划。"
                    ),
                    compiler_notes=compiler_notes,
                    recommended_capability_keys=list(assessment.recommended_capabilities),
                    audit_metadata={
                        **assessment.audit_metadata,
                        "replanned_from_plan_id": previous_plan.id,
                        "replanned_to_plan_id": plan.id,
                    },
                    created_at=plan.updated_at,
                )
            )
        replans.sort(key=lambda item: item.execution_plan.updated_at, reverse=True)
        return replans[offset : offset + limit]

    def get_plan(self, plan_id: str) -> ExecutionPlanRead:
        item = ExecutionPlanRepository(self.session).get(plan_id)
        if item is None:
            raise ValueError("Execution plan not found")
        return ExecutionPlanRead.model_validate(item)

    def compile_plan(self, payload: CompilePlanRequest) -> ExecutionPlanRead:
        task_spec = TaskSpecRepository(self.session).get(payload.task_spec_id)
        if task_spec is None:
            raise ValueError("Task spec not found")

        template = None
        if payload.workflow_template_id is not None:
            template = WorkflowTemplateRepository(self.session).get(payload.workflow_template_id)
            if template is None:
                raise ValueError("Workflow template not found")

        steps = self._normalize_steps(
            list(payload.steps) or self._default_steps(task_spec, template),
            domain=task_spec.domain,
        )
        item = ExecutionPlanRepository(self.session).create(
            {
                "task_spec_id": task_spec.id,
                "name": payload.name or f"{task_spec.title} Plan",
                "mode": payload.mode,
                "status": payload.status,
                "plan_body": {
                    "steps": steps,
                    "instruction": payload.compiled_from_instruction or task_spec.source_text or task_spec.goal,
                    "domain": task_spec.domain,
                },
                "environment_requirements": self._merge_dicts(
                    self._merge_dicts(
                        self._default_environment_requirements(task_spec.domain, task_spec.preferred_capabilities),
                        dict((task_spec.compiled_payload or {}).get("environment_requirements") or {}),
                    ),
                    dict(payload.environment_requirements),
                ),
                "checkpoints": list(payload.checkpoints) or self._default_checkpoints(task_spec, template),
                "runtime_metadata": {
                    **dict(payload.runtime_metadata),
                    "workflow_template_id": template.id if template is not None else None,
                    "workflow_template_key": template.template_key if template is not None else None,
                    "domain_pack": task_spec.domain,
                    "planner_contract_version": "runtime-scene-v2",
                    "step_outline_source": "compiled_payload"
                    if (task_spec.compiled_payload or {}).get("step_outline")
                    else "default_seed",
                    "scene_assessment_required": bool(
                        ((task_spec.compiled_payload or {}).get("environment_requirements") or {}).get("requires_browser")
                        or "browser" in list(task_spec.preferred_capabilities or [])
                    ),
                },
            }
        )
        return ExecutionPlanRead.model_validate(item)

    def list_episodes(
        self,
        *,
        execution_plan_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExecutionEpisodeRead]:
        repo = ExecutionEpisodeRepository(self.session)
        items = repo.by_plan(execution_plan_id, limit=limit, offset=offset) if execution_plan_id else repo.list(limit=limit, offset=offset)
        return [ExecutionEpisodeRead.model_validate(item) for item in items]

    def get_episode(self, episode_id: str) -> ExecutionEpisodeRead:
        item = ExecutionEpisodeRepository(self.session).get(episode_id)
        if item is None:
            raise ValueError("Execution episode not found")
        return ExecutionEpisodeRead.model_validate(item)

    def recover_running_episodes(self) -> int:
        recovered = ExecutionEpisodeRepository(self.session).recover_running()
        if recovered:
            active_plans = ExecutionPlanRepository(self.session).active(limit=500, offset=0)
            for plan in active_plans:
                if plan.status == "running":
                    ExecutionPlanRepository(self.session).update(
                        plan,
                        {
                            "status": "planned",
                            "runtime_metadata": {
                                **dict(plan.runtime_metadata or {}),
                                "recovered_after_restart": True,
                            },
                        },
                    )
        return recovered

    def get_episode_replay(self, episode_id: str) -> RuntimeEpisodeReplayRead:
        episode = ExecutionEpisodeRepository(self.session).get(episode_id)
        if episode is None:
            raise ValueError("Execution episode not found")

        task_spec = TaskSpecRepository(self.session).get(episode.task_spec_id)
        if task_spec is None:
            raise ValueError("Task spec not found")
        plan = ExecutionPlanRepository(self.session).get(episode.execution_plan_id)
        if plan is None:
            raise ValueError("Execution plan not found")

        snapshots = EnvironmentSnapshotRepository(self.session).for_episode(episode.id, limit=500, offset=0)
        patch = self._get_episode_patch(episode)
        template = self._episode_template(episode) or self._get_episode_template(plan=plan, task_spec=task_spec, patch=patch)
        learning = self._episode_learning(episode) or self._get_episode_learning(task_spec_id=task_spec.id)
        approvals = self._get_episode_approvals(episode=episode, patch=patch, learning=learning)

        diagnostics = RuntimeReplayDiagnosticsRead(
            domain=str(task_spec.domain),
            status=str(episode.status),
            requires_confirmation=bool(episode.requires_confirmation),
            divergence_detected=bool(episode.divergence_detected),
            action_count=len(list(episode.actions or [])),
            observation_count=len(list(episode.observations or [])),
            snapshot_count=len(snapshots),
            approval_count=len(approvals),
            pending_approval_count=sum(1 for item in approvals if item.status == "pending"),
            completion_rate=self._safe_float((episode.metrics or {}).get("completion_rate")),
            latest_snapshot_page_type=(snapshots[-1].page_type if snapshots else None),
            latest_error=episode.last_error,
        )

        timeline = self._build_episode_timeline(
            task_spec=task_spec,
            plan=plan,
            episode=episode,
            snapshots=snapshots,
            template=template,
            patch=patch,
            learning=learning,
            approvals=approvals,
        )

        return RuntimeEpisodeReplayRead(
            task_spec=TaskSpecRead.model_validate(task_spec),
            execution_plan=ExecutionPlanRead.model_validate(plan),
            episode=ExecutionEpisodeRead.model_validate(episode),
            snapshots=[EnvironmentSnapshotRead.model_validate(item) for item in snapshots],
            template=WorkflowTemplateRead.model_validate(template) if template is not None else None,
            patch=WorkflowPatchRead.model_validate(patch) if patch is not None else None,
            learning_draft=LearningDraftRead.model_validate(learning) if learning is not None else None,
            approvals=[ApprovalRead.model_validate(item) for item in approvals],
            diagnostics=diagnostics,
            timeline=timeline,
        )

    def create_episode(self, payload: ExecutionEpisodeCreate) -> ExecutionEpisodeRead:
        if TaskSpecRepository(self.session).get(payload.task_spec_id) is None:
            raise ValueError("Task spec not found")
        plan = ExecutionPlanRepository(self.session).get(payload.execution_plan_id)
        if plan is None:
            raise ValueError("Execution plan not found")
        if plan.task_spec_id != payload.task_spec_id:
            raise ValueError("Execution plan does not belong to the task spec")

        item = ExecutionEpisodeRepository(self.session).create(payload)
        return ExecutionEpisodeRead.model_validate(item)

    def start_managed_execution(
        self,
        *,
        task_spec_id: str,
        execution_plan_id: str,
        requested_by: str = "runtime",
        mode: str = "production",
        task_id: str | None = None,
        task_payload: dict[str, Any] | None = None,
        runtime_metadata: dict[str, Any] | None = None,
        execution_episode_id: str | None = None,
    ) -> ManagedExecutionContext:
        task_repo = TaskSpecRepository(self.session)
        plan_repo = ExecutionPlanRepository(self.session)
        episode_repo = ExecutionEpisodeRepository(self.session)

        task_spec = task_repo.get(task_spec_id)
        if task_spec is None:
            raise ValueError("Task spec not found")
        plan = plan_repo.get(execution_plan_id)
        if plan is None:
            raise ValueError("Execution plan not found")
        if plan.task_spec_id != task_spec.id:
            raise ValueError("Execution plan does not belong to the task spec")

        runtime_payload = dict(task_payload or {})
        runtime_state = dict(runtime_metadata or {})
        snapshot_payload = self._managed_snapshot_payload(
            task_spec=task_spec,
            plan=plan,
            execution_episode_id=execution_episode_id,
            task_payload=runtime_payload,
            runtime_metadata=runtime_state,
        )

        if execution_episode_id:
            episode_model = episode_repo.get(execution_episode_id)
            if episode_model is None:
                raise ValueError("Execution episode not found")
        else:
            episode_model = episode_repo.create(
                ExecutionEpisodeCreate(
                    task_spec_id=task_spec.id,
                    execution_plan_id=plan.id,
                    mode=mode,
                    status="running",
                    requested_by=requested_by,
                    requires_confirmation=mode != "production",
                    started_at=utcnow(),
                    runtime_metadata={
                        **runtime_state,
                        "task_id": task_id,
                        "task_payload": runtime_payload,
                        "managed_execution": True,
                    },
                )
            )

        persisted_snapshot = None
        if snapshot_payload is not None:
            if snapshot_payload.execution_episode_id is None:
                snapshot_payload = snapshot_payload.model_copy(update={"execution_episode_id": episode_model.id})
            persisted_snapshot = self.create_environment_snapshot(snapshot_payload)

        assessment = self.assess_environment(
            EnvironmentAssessmentRequest(
                task_spec_id=task_spec.id,
                execution_plan_id=plan.id,
                execution_episode_id=episode_model.id,
                environment_snapshot_id=persisted_snapshot.id if persisted_snapshot is not None else None,
                snapshot=None if persisted_snapshot is not None else snapshot_payload,
                compiler_payload=dict(task_spec.compiled_payload or {}),
                plan_context={"task_payload": runtime_payload, "mode": mode, **runtime_state},
            )
        )
        if assessment.plan_fit == "blocked" or assessment.planner_guidance.posture == "recover":
            replanned = self.replan_execution(
                plan.id,
                ExecutionPlanReplanRequest(
                    reason="Managed execution preflight detected a scene/plan mismatch.",
                    requested_by=requested_by,
                    execution_episode_id=episode_model.id,
                    snapshot=snapshot_payload,
                    compiler_payload={
                        "compiler_notes": [
                            "Managed execution requested a preflight replan before entering the executor loop."
                        ],
                        "preferred_capabilities": list(assessment.recommended_capabilities),
                    },
                    plan_context={"task_payload": runtime_payload, "mode": mode, **runtime_state},
                    runtime_metadata={"generated_by": "managed_execution_preflight"},
                    preserve_active_plan=True,
                ),
            )
            replanned_model = plan_repo.get(replanned.execution_plan.id)
            if replanned_model is not None:
                plan = replanned_model
                episode_model = episode_repo.update(
                    episode_model,
                    {
                        "execution_plan_id": plan.id,
                        "runtime_metadata": {
                            **dict(episode_model.runtime_metadata or {}),
                            "preflight_replanned_from_plan_id": replanned.previous_plan.id,
                            "preflight_replanned_to_plan_id": plan.id,
                        },
                    },
                )
                assessment = self.assess_environment(
                    EnvironmentAssessmentRequest(
                        task_spec_id=task_spec.id,
                        execution_plan_id=plan.id,
                        execution_episode_id=episode_model.id,
                        snapshot=snapshot_payload,
                        compiler_payload=dict(task_spec.compiled_payload or {}),
                        plan_context={"task_payload": runtime_payload, "mode": mode, **runtime_state},
                    )
                )
        capability_drivers = self.list_capability_drivers(domain=task_spec.domain)
        execution_contract = self._build_execution_contract(
            task_spec=task_spec,
            plan=plan,
            episode=episode_model,
            assessment=assessment,
            capability_drivers=capability_drivers,
            task_payload=runtime_payload,
        )
        plan = plan_repo.update(
            plan,
            {
                "status": "running",
                "runtime_metadata": _json_ready(
                    {
                        **dict(plan.runtime_metadata or {}),
                        "last_episode_id": episode_model.id,
                        "last_task_id": task_id,
                        "last_execution_contract": execution_contract,
                        "planner_guidance": assessment.planner_guidance,
                        "scene_profile": assessment.scene_profile,
                    }
                ),
            },
        )
        episode = episode_repo.update(
            episode_model,
            {
                "runtime_metadata": _json_ready(
                    {
                        **dict(episode_model.runtime_metadata or {}),
                        "execution_contract": execution_contract,
                        "scene_assessment": assessment,
                        "environment_snapshot_id": persisted_snapshot.id if persisted_snapshot is not None else None,
                    }
                )
            },
        )
        return ManagedExecutionContext(
            task_spec=TaskSpecRead.model_validate(task_spec),
            execution_plan=ExecutionPlanRead.model_validate(plan),
            execution_episode=ExecutionEpisodeRead.model_validate(episode),
            assessment=assessment,
            capability_drivers=capability_drivers,
            execution_contract=execution_contract,
        )

    def finalize_managed_execution(
        self,
        *,
        execution_episode_id: str,
        result: AgentResult,
        task_payload: dict[str, Any] | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> RuntimeLearningOutcomeRead:
        episode_repo = ExecutionEpisodeRepository(self.session)
        plan_repo = ExecutionPlanRepository(self.session)
        task_repo = TaskSpecRepository(self.session)

        episode = episode_repo.get(execution_episode_id)
        if episode is None:
            raise ValueError("Execution episode not found")
        plan = plan_repo.get(episode.execution_plan_id)
        if plan is None:
            raise ValueError("Execution plan not found")
        task_spec = task_repo.get(episode.task_spec_id)
        if task_spec is None:
            raise ValueError("Task spec not found")

        trace = dict(result.metadata.get("executor_trace") or {})
        observations = self._managed_observations(episode=episode, trace=trace, result=result)
        actions = self._managed_actions(episode=episode, trace=trace)
        metrics = self._managed_metrics(plan=plan, trace=trace, result=result)
        divergence_detected = result.status == "replan_requested"
        status = self._managed_episode_status(result, requires_confirmation=bool(episode.requires_confirmation))
        finished_at = utcnow()
        merged_runtime_metadata = _json_ready(
            {
                **dict(episode.runtime_metadata or {}),
                **dict(runtime_metadata or {}),
                "final_result_status": result.status,
                "final_result_success": result.success,
                "final_result_data": dict(result.data or {}),
                "agent_result": {
                    "status": result.status,
                    "success": result.success,
                    "content": result.content,
                    "data": dict(result.data or {}),
                    "usage": {
                        "prompt_tokens": result.usage.prompt_tokens,
                        "completion_tokens": result.usage.completion_tokens,
                        "total_tokens": result.usage.total_tokens,
                    },
                    "tool_outputs": [
                        {
                            "tool_name": item.tool_name,
                            "is_error": item.is_error,
                            "message_length": len(item.to_message_content() or ""),
                        }
                        for item in list(result.tool_outputs or [])
                    ],
                    "message_lengths": [
                        {
                            "role": message.role,
                            "name": message.name,
                            "length": len(message.content or ""),
                        }
                        for message in list(result.messages or [])
                    ],
                },
                "executor_metadata": dict(result.metadata or {}),
            }
        )

        updated_episode = episode_repo.update(
            episode,
            ExecutionEpisodeUpdate(
                status=status,
                started_at=episode.started_at or utcnow(),
                finished_at=finished_at,
                result_summary=result.content or self._runtime_result_summary(task_spec.domain, result),
                observations=observations,
                actions=actions,
                metrics=metrics,
                divergence_detected=divergence_detected,
                runtime_metadata=merged_runtime_metadata,
                last_error=None if result.success else result.content,
            ),
        )

        scene_snapshot = self._latest_scene_update(trace)
        if scene_snapshot is not None:
            self.create_environment_snapshot(
                self._managed_environment_snapshot_create(
                    task_spec=task_spec,
                    plan=plan,
                    episode=updated_episode,
                    task_payload=dict(task_payload or {}),
                    scene_snapshot=scene_snapshot,
                )
            )

        plan_status = "active" if result.success else "blocked" if result.status == "waiting_human" else "diverged" if divergence_detected else "failed"
        updated_plan = plan_repo.update(
            plan,
            {
                "status": plan_status,
                "approval_state": "pending_review" if result.status in {"waiting_human", "replan_requested"} else plan.approval_state,
                "runtime_metadata": _json_ready(
                    {
                        **dict(plan.runtime_metadata or {}),
                        "last_episode_id": updated_episode.id,
                        "last_executor_trace": trace,
                        "last_result_status": result.status,
                    }
                ),
            },
        )

        if result.status in {"completed", "replan_requested"}:
            outcome = self.derive_learning_from_episode(updated_episode.id)
        else:
            outcome = RuntimeLearningOutcomeRead(
                episode=ExecutionEpisodeRead.model_validate(updated_episode),
                skill_health=self._evaluate_skill_health(plan=updated_plan, episode=updated_episode),
            )
        return outcome

    def create_trial_run(self, payload: TrialRunRequest) -> ExecutionEpisodeRead:
        plan = ExecutionPlanRepository(self.session).get(payload.execution_plan_id)
        if plan is None:
            raise ValueError("Execution plan not found")
        if TaskSpecRepository(self.session).get(payload.task_spec_id) is None:
            raise ValueError("Task spec not found")
        if plan.task_spec_id != payload.task_spec_id:
            raise ValueError("Execution plan does not belong to the task spec")

        return self.create_episode(
            ExecutionEpisodeCreate(
                task_spec_id=payload.task_spec_id,
                execution_plan_id=payload.execution_plan_id,
                mode="trial",
                status="pending",
                requested_by=payload.requested_by,
                requires_confirmation=True,
                runtime_metadata={"trial_notes": payload.notes, **payload.runtime_metadata},
            )
        )

    def execute_trial_run(self, episode_id: str, payload: TrialRunExecuteRequest) -> RuntimeLearningOutcomeRead:
        episode_repo = ExecutionEpisodeRepository(self.session)
        episode = episode_repo.get(episode_id)
        if episode is None:
            raise ValueError("Execution episode not found")

        plan = ExecutionPlanRepository(self.session).get(episode.execution_plan_id)
        if plan is None:
            raise ValueError("Execution plan not found")
        task_spec = TaskSpecRepository(self.session).get(episode.task_spec_id)
        if task_spec is None:
            raise ValueError("Task spec not found")

        payload = self._hydrate_trial_payload_with_live_scene(task_spec=task_spec, payload=payload)

        if self.providers is not None and self.tools is not None:
            managed_payload = self._trial_task_payload(task_spec=task_spec, plan=plan, payload=payload)
            managed = self.start_managed_execution(
                task_spec_id=task_spec.id,
                execution_plan_id=plan.id,
                execution_episode_id=episode.id,
                requested_by=payload.operator,
                mode="trial",
                task_payload=managed_payload,
                runtime_metadata={
                    **dict(episode.runtime_metadata or {}),
                    **dict(payload.runtime_metadata),
                    "operator": payload.operator,
                    "last_execution_notes": payload.notes,
                },
            )
            runtime_task = SimpleNamespace(
                task_type="runtime_execution",
                workflow_node_id="runtime_execution",
                payload={
                    **managed_payload,
                    "goal": managed.task_spec.goal,
                    "domain": managed.task_spec.domain,
                    "plan_name": managed.execution_plan.name,
                },
                max_turns=8,
                token_budget=16_384,
            )
            loop = AgentLoop(
                provider=self.providers,
                tools=self.tools,
                prompt_builder=self.prompt_builder,
                config=AgentLoopConfig(max_turns=8, token_budget=16_384),
            )
            result = loop.run(
                runtime_task,
                extra_context={
                    "scene_assessment": managed.assessment.model_dump(),
                    "capability_drivers": [driver.model_dump() for driver in managed.capability_drivers],
                    "execution_episode": managed.execution_episode.model_dump(),
                    "execution_plan": managed.execution_plan.model_dump(),
                    "scene_profile": managed.assessment.scene_profile.model_dump(),
                    "planner_guidance": managed.assessment.planner_guidance.model_dump(),
                    "execution_contract": managed.execution_contract,
                },
            )
            if payload.simulate_divergence and result.status not in {"replan_requested", "waiting_human"}:
                result = self._simulate_managed_divergence(
                    result=result,
                    episode=managed.execution_episode,
                    plan=managed.execution_plan,
                )
            outcome = self.finalize_managed_execution(
                execution_episode_id=managed.execution_episode.id,
                result=result,
                task_payload=managed_payload,
                runtime_metadata={
                    "operator": payload.operator,
                    "last_execution_notes": payload.notes,
                    "trial_execution_mode": "managed_runtime",
                },
            )
            if result.status == "replan_requested":
                latest_request = self._latest_replan_request(result)
                replan = self.replan_execution(
                    managed.execution_plan.id,
                    ExecutionPlanReplanRequest(
                        reason=str(latest_request.get("reason") or result.content or "Managed trial requested replanning."),
                        requested_by=payload.operator,
                        execution_episode_id=managed.execution_episode.id,
                        environment_snapshot_id=self._latest_snapshot_id(managed.execution_episode.id),
                        compiler_payload={
                            "compiler_notes": [
                                str(latest_request.get("reason") or result.content or "Managed trial requested replanning."),
                                "Auto-generated replan from managed trial execution.",
                            ],
                            "preferred_capabilities": list(latest_request.get("preferred_capabilities") or []),
                            "step_outline": list(latest_request.get("suggested_steps") or []),
                            "checkpoints": [{"kind": "planner", "label": "Review auto-replanned trial execution"}],
                        },
                        plan_context={"task_payload": managed_payload, "trial_mode": True},
                        runtime_metadata={"generated_by": "managed_trial_executor", "execution_episode_id": managed.execution_episode.id},
                        preserve_active_plan=False,
                    ),
                )
                outcome.episode.runtime_metadata = {
                    **dict(outcome.episode.runtime_metadata or {}),
                    "replanned_execution_plan_id": replan.execution_plan.id,
                }
            return outcome

        observations, actions, metrics, result_summary = self._simulate_episode(task_spec, plan, episode, payload)
        started_at = episode.started_at or utcnow()
        finished_at = utcnow()
        simulate_divergence = bool(
            payload.simulate_divergence
            if payload.simulate_divergence is not None
            else episode.runtime_metadata.get("simulate_divergence")
        )
        status = "awaiting_review" if episode.requires_confirmation else "completed"
        if simulate_divergence:
            status = "diverged"

        updated_episode = episode_repo.update(
            episode,
            ExecutionEpisodeUpdate(
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                result_summary=result_summary,
                observations=observations,
                actions=actions,
                metrics=metrics,
                divergence_detected=simulate_divergence,
                runtime_metadata={
                    **dict(episode.runtime_metadata or {}),
                    **dict(payload.runtime_metadata),
                    "operator": payload.operator,
                    "last_execution_notes": payload.notes,
                },
            ),
        )

        self._ensure_environment_snapshot(
            task_spec_id=task_spec.id,
            execution_plan_id=plan.id,
            execution_episode_id=updated_episode.id,
            payload=payload,
            plan=plan,
            task_spec=task_spec,
        )

        plan_repo = ExecutionPlanRepository(self.session)
        plan_repo.update(
            plan,
            {
                "status": "diverged" if simulate_divergence else "trial_completed",
                "approval_state": "pending_review" if updated_episode.requires_confirmation else "ready",
                "runtime_metadata": {
                    **dict(plan.runtime_metadata or {}),
                    "last_episode_id": updated_episode.id,
                    "last_operator": payload.operator,
                },
            },
        )

        return self.derive_learning_from_episode(updated_episode.id)

    def _hydrate_trial_payload_with_live_scene(self, *, task_spec, payload: TrialRunExecuteRequest) -> TrialRunExecuteRequest:
        return payload

    def derive_learning_from_episode(self, episode_id: str) -> RuntimeLearningOutcomeRead:
        episode_repo = ExecutionEpisodeRepository(self.session)
        episode = episode_repo.get(episode_id)
        if episode is None:
            raise ValueError("Execution episode not found")

        plan = ExecutionPlanRepository(self.session).get(episode.execution_plan_id)
        if plan is None:
            raise ValueError("Execution plan not found")
        task_spec = TaskSpecRepository(self.session).get(episode.task_spec_id)
        if task_spec is None:
            raise ValueError("Task spec not found")

        template = self._materialize_template(task_spec=task_spec, plan=plan, episode=episode)
        template_approval = self._ensure_template_candidate_approval(
            task_spec=task_spec,
            plan=plan,
            episode=episode,
            template=template,
        )
        patch = self._materialize_patch(task_spec=task_spec, plan=plan, episode=episode, template=template)
        learning = self._materialize_learning(task_spec=task_spec, plan=plan, episode=episode)
        approval = self._materialize_skill_draft_approval(task_spec=task_spec, plan=plan, episode=episode, learning=learning)
        skill_health = self._evaluate_skill_health(plan=plan, episode=episode)

        if template is not None and not episode.divergence_detected:
            ExecutionPlanRepository(self.session).update(
                plan,
                {"approval_state": "template_candidate", "status": "validated"},
            )

        refreshed_episode = episode_repo.get(episode_id)
        if refreshed_episode is None:
            raise ValueError("Execution episode not found")

        return RuntimeLearningOutcomeRead(
            episode=ExecutionEpisodeRead.model_validate(refreshed_episode),
            template=WorkflowTemplateRead.model_validate(template) if template is not None else None,
            patch=WorkflowPatchRead.model_validate(patch) if patch is not None else None,
            learning_draft=LearningDraftRead.model_validate(learning) if learning is not None else None,
            approval=ApprovalRead.model_validate(approval) if approval is not None else ApprovalRead.model_validate(template_approval) if template_approval is not None else None,
            template_approval=ApprovalRead.model_validate(template_approval) if template_approval is not None else None,
            skill_health=skill_health,
        )

    def confirm_episode(self, episode_id: str, payload: EpisodeConfirmRequest) -> RuntimeLearningOutcomeRead:
        return self.review_episode_confirmation(episode_id, payload, approve=True)

    def review_episode_confirmation(
        self,
        episode_id: str,
        payload: EpisodeConfirmRequest,
        *,
        approve: bool,
    ) -> RuntimeLearningOutcomeRead:
        outcome = self.derive_learning_from_episode(episode_id)
        episode_repo = ExecutionEpisodeRepository(self.session)
        plan_repo = ExecutionPlanRepository(self.session)
        task_repo = TaskSpecRepository(self.session)

        episode = episode_repo.get(episode_id)
        if episode is None:
            raise ValueError("Execution episode not found")
        plan = plan_repo.get(episode.execution_plan_id)
        if plan is None:
            raise ValueError("Execution plan not found")
        task = task_repo.get(episode.task_spec_id)
        if task is None:
            raise ValueError("Task spec not found")

        template = None
        template_approval = outcome.template_approval
        template_model = None
        if outcome.template is not None:
            template_repo = WorkflowTemplateRepository(self.session)
            template_model = template_repo.get(outcome.template.id)
            if approve and template_model is not None:
                template = template_repo.update(
                    template_model,
                    WorkflowTemplateUpdate(
                        name=payload.template_name or template_model.name,
                        status="active" if payload.activate_template else template_model.status,
                        validation_summary=payload.reason or template_model.validation_summary or "Confirmed from supervised trial run.",
                        last_validated_at=utcnow(),
                    ),
                )
            elif template_model is not None:
                template = template_model
            template_approval = self._mark_template_candidate_approval(
                episode_id=episode.id,
                reviewer=payload.reviewer,
                reason=payload.reason,
                approved=approve,
                template=template_model if template_model is not None else None,
            )

        plan_runtime_metadata = {
            **dict(plan.runtime_metadata or {}),
            "reviewed_by": payload.reviewer,
            "reviewed_reason": payload.reason,
            "review_decision": "approved" if approve else "rejected",
        }
        if approve:
            plan_runtime_metadata["confirmed_by"] = payload.reviewer
            plan_runtime_metadata["confirmed_reason"] = payload.reason
        plan_repo.update(
            plan,
            {
                "status": "active" if approve and payload.activate_template else "validated",
                "approval_state": "approved" if approve else "rejected",
                "runtime_metadata": plan_runtime_metadata,
            },
        )
        if approve:
            task_repo.update(
                task,
                {
                    "status": "production_ready" if payload.activate_template else "validated",
                    "active_plan_id": plan.id,
                },
            )
        episode_runtime_metadata = {
            **dict(episode.runtime_metadata or {}),
            "reviewed_by": payload.reviewer,
            "reviewed_reason": payload.reason,
            "review_decision": "approved" if approve else "rejected",
        }
        if approve:
            episode_runtime_metadata["confirmed_by"] = payload.reviewer
            episode_runtime_metadata["confirmed_reason"] = payload.reason
        episode = episode_repo.update(
            episode,
            ExecutionEpisodeUpdate(
                status="confirmed" if approve else "rejected",
                requires_confirmation=False,
                runtime_metadata=episode_runtime_metadata,
            ),
        )

        return RuntimeLearningOutcomeRead(
            episode=ExecutionEpisodeRead.model_validate(episode),
            template=WorkflowTemplateRead.model_validate(template) if template is not None else outcome.template,
            patch=outcome.patch,
            learning_draft=outcome.learning_draft,
            approval=outcome.approval,
            template_approval=ApprovalRead.model_validate(template_approval) if template_approval is not None else outcome.template_approval,
            skill_health=outcome.skill_health,
        )

    def list_environment_snapshots(
        self,
        *,
        execution_episode_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EnvironmentSnapshotRead]:
        repo = EnvironmentSnapshotRepository(self.session)
        items = repo.for_episode(execution_episode_id, limit=limit, offset=offset) if execution_episode_id else repo.list(limit=limit, offset=offset)
        return [EnvironmentSnapshotRead.model_validate(item) for item in items]

    def create_environment_snapshot(self, payload: EnvironmentSnapshotCreate) -> EnvironmentSnapshotRead:
        if payload.execution_episode_id is not None and ExecutionEpisodeRepository(self.session).get(payload.execution_episode_id) is None:
            raise ValueError("Execution episode not found")
        item = EnvironmentSnapshotRepository(self.session).create(payload)
        return EnvironmentSnapshotRead.model_validate(item)

    def list_templates(self, *, domain: str | None = None, limit: int = 100, offset: int = 0) -> list[WorkflowTemplateRead]:
        repo = WorkflowTemplateRepository(self.session)
        items = repo.list(limit=limit, offset=offset)
        if not items:
            items = [self._seed_template(repo, item) for item in DEFAULT_WORKFLOW_TEMPLATES]
        if domain is not None:
            items = [item for item in items if item.domain == domain]
        return [WorkflowTemplateRead.model_validate(item) for item in items]

    def get_template(self, template_id: str) -> WorkflowTemplateRead:
        item = WorkflowTemplateRepository(self.session).get(template_id)
        if item is None:
            raise ValueError("Workflow template not found")
        return WorkflowTemplateRead.model_validate(item)

    def create_template(self, payload: WorkflowTemplateCreate) -> WorkflowTemplateRead:
        repo = WorkflowTemplateRepository(self.session)
        if repo.by_template_key(payload.template_key) is not None:
            raise ValueError("Workflow template with the same template_key already exists")
        item = repo.create(payload)
        return WorkflowTemplateRead.model_validate(item)

    def update_template(self, template_id: str, payload: WorkflowTemplateUpdate) -> WorkflowTemplateRead:
        repo = WorkflowTemplateRepository(self.session)
        item = repo.get(template_id)
        if item is None:
            raise ValueError("Workflow template not found")
        if payload.template_key and payload.template_key != item.template_key:
            existing = repo.by_template_key(payload.template_key)
            if existing is not None and existing.id != item.id:
                raise ValueError("Workflow template with the same template_key already exists")
        updated = repo.update(item, payload)
        return WorkflowTemplateRead.model_validate(updated)

    def list_workflow_patches(
        self,
        *,
        status: str | None = None,
        workflow_template_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkflowPatchRead]:
        repo = WorkflowPatchRepository(self.session)
        items = repo.pending_review(limit=limit, offset=offset) if status == "pending_review" else repo.list(limit=limit, offset=offset)
        if workflow_template_id is not None:
            items = [item for item in items if item.template_id == workflow_template_id]
        if status is not None and status != "pending_review":
            items = [item for item in items if item.status == status]
        return [WorkflowPatchRead.model_validate(item) for item in items]

    def create_workflow_patch(self, payload: WorkflowPatchCreate) -> WorkflowPatchRead:
        if payload.template_id is not None:
            template = WorkflowTemplateRepository(self.session).get(payload.template_id)
            if template is None:
                raise ValueError("Workflow template not found")
        if payload.task_spec_id is not None and TaskSpecRepository(self.session).get(payload.task_spec_id) is None:
            raise ValueError("Task spec not found")
        if payload.execution_plan_id is not None and ExecutionPlanRepository(self.session).get(payload.execution_plan_id) is None:
            raise ValueError("Execution plan not found")
        if payload.execution_episode_id is not None and ExecutionEpisodeRepository(self.session).get(payload.execution_episode_id) is None:
            raise ValueError("Execution episode not found")

        item = WorkflowPatchRepository(self.session).create(payload)
        if payload.execution_episode_id is not None:
            episode_repo = ExecutionEpisodeRepository(self.session)
            episode = episode_repo.get(payload.execution_episode_id)
            if episode is not None:
                episode_repo.update(episode, {"patch_id": item.id, "divergence_detected": True})

        self._ensure_patch_approval(item)
        return WorkflowPatchRead.model_validate(item)

    def review_workflow_patch(self, patch_id: str, payload: WorkflowPatchDecisionRequest, *, approve: bool) -> WorkflowPatchRead:
        repo = WorkflowPatchRepository(self.session)
        item = repo.get(patch_id)
        if item is None:
            raise ValueError("Workflow patch not found")

        applied_artifacts: dict[str, Any] = {}
        if approve and payload.apply_immediately:
            applied_artifacts = self._apply_workflow_patch(item, reviewer=payload.reviewer, reason=payload.reason)

        status = "applied" if approve and payload.apply_immediately else "approved" if approve else "rejected"
        updated = repo.mark_review(
            item,
            status=status,
            reviewer=payload.reviewer,
            rationale=payload.reason,
            applied_at=utcnow() if approve and payload.apply_immediately else None,
        )
        if applied_artifacts:
            updated = repo.update(
                updated,
                {
                    "runtime_metadata": {
                        **dict(updated.runtime_metadata or {}),
                        "apply_result": applied_artifacts,
                    }
                },
            )
        self._sync_patch_approval(updated, payload=payload, approve=approve)
        return WorkflowPatchRead.model_validate(updated)

    def _ensure_patch_approval(self, patch: WorkflowPatch) -> ApprovalItem:
        existing = self._get_patch_approval(patch.id)
        if existing is not None:
            return existing
        return ApprovalRepository(self.session).create(
            {
                "target_type": "workflow_patch",
                "target_id": patch.id,
                "title": patch.title,
                "status": "pending",
                "requested_by": patch.proposed_by or "runtime",
                "payload": {
                    "summary": patch.divergence_summary or patch.rationale or patch.title,
                    "workflow_patch_id": patch.id,
                    "template_id": patch.template_id,
                    "task_spec_id": patch.task_spec_id,
                    "execution_plan_id": patch.execution_plan_id,
                    "execution_episode_id": patch.execution_episode_id,
                    "patch_body": dict(patch.patch_body or {}),
                },
            }
        )

    def _ensure_template_candidate_approval(self, *, task_spec, plan, episode, template):
        if template is None or not episode.requires_confirmation:
            return None

        existing = self._get_template_candidate_approval(episode.id)
        if existing is not None:
            self._remember_episode_artifact(episode, "template_approval_id", existing.id)
            return existing

        approval = ApprovalRepository(self.session).create(
            {
                "target_type": "template_candidate",
                "target_id": episode.id,
                "title": f"Review template candidate for {task_spec.title}",
                "status": "pending",
                "requested_by": episode.requested_by or "runtime",
                "payload": {
                    "template_id": template.id,
                    "task_spec_id": task_spec.id,
                    "execution_plan_id": plan.id,
                    "execution_episode_id": episode.id,
                    "template_key": template.template_key,
                    "template_version": template.version,
                    "summary": template.validation_summary,
                    "governance": dict((template.activation_strategy or {}).get("governance") or {}),
                    "version_policy": dict((template.activation_strategy or {}).get("version_policy") or {}),
                },
            }
        )
        self._remember_episode_artifact(episode, "template_approval_id", approval.id)
        return approval

    def _mark_template_candidate_approval(
        self,
        *,
        episode_id: str,
        reviewer: str,
        reason: str | None,
        approved: bool,
        template=None,
    ) -> ApprovalItem | None:
        approval = self._get_template_candidate_approval(episode_id)
        if approval is None:
            return None
        approval.payload = {
            **dict(approval.payload or {}),
            "resolution": {
                "status": "approved" if approved else "rejected",
                "reviewer": reviewer,
                "reason": reason,
                "reviewed_at": utcnow().isoformat(),
                "template_id": getattr(template, "id", None) or dict(approval.payload or {}).get("template_id"),
                "template_version": getattr(template, "version", None) or dict(approval.payload or {}).get("template_version"),
                "governance": dict((getattr(template, "activation_strategy", {}) or {}).get("governance") or {}),
            },
        }
        self.session.commit()
        return ApprovalRepository(self.session).mark_review(
            approval,
            "approved" if approved else "rejected",
            reviewer=reviewer,
            notes=reason,
        )

    def _sync_patch_approval(
        self,
        patch: WorkflowPatch,
        *,
        payload: WorkflowPatchDecisionRequest,
        approve: bool,
    ) -> None:
        approval = self._get_patch_approval(patch.id)
        if approval is None:
            approval = self._ensure_patch_approval(patch)
        approval.payload = {
            **dict(approval.payload or {}),
            "resolution": {
                "status": patch.status,
                "reviewer": payload.reviewer,
                "reason": payload.reason,
                "apply_immediately": payload.apply_immediately if approve else False,
                **dict((patch.runtime_metadata or {}).get("apply_result") or {}),
            },
        }
        self.session.commit()
        ApprovalRepository(self.session).mark_review(
            approval,
            "approved" if approve else "rejected",
            reviewer=payload.reviewer,
            notes=payload.reason,
        )

    def _get_patch_approval(self, patch_id: str) -> ApprovalItem | None:
        stmt = select(ApprovalItem).where(
            ApprovalItem.target_type == "workflow_patch",
            ApprovalItem.target_id == patch_id,
        )
        return self.session.scalars(stmt).first()

    def _get_template_candidate_approval(self, episode_id: str) -> ApprovalItem | None:
        stmt = select(ApprovalItem).where(
            ApprovalItem.target_type == "template_candidate",
            ApprovalItem.target_id == episode_id,
        )
        return self.session.scalars(stmt).first()

    def _apply_workflow_patch(
        self,
        patch: WorkflowPatch,
        *,
        reviewer: str,
        reason: str | None,
    ) -> dict[str, Any]:
        existing_result = dict((patch.runtime_metadata or {}).get("apply_result") or {})
        if existing_result.get("execution_plan_id"):
            existing_plan = ExecutionPlanRepository(self.session).get(str(existing_result["execution_plan_id"]))
            if existing_plan is not None:
                return existing_result

        apply_result: dict[str, Any] = {
            "applied_by": reviewer,
            "applied_reason": reason,
            "applied_at": utcnow().isoformat(),
        }

        template_repo = WorkflowTemplateRepository(self.session)
        plan_repo = ExecutionPlanRepository(self.session)
        task_repo = TaskSpecRepository(self.session)

        current_plan = plan_repo.get(patch.execution_plan_id) if patch.execution_plan_id else None
        task_spec = task_repo.get(patch.task_spec_id) if patch.task_spec_id else None
        if task_spec is None and current_plan is not None:
            task_spec = task_repo.get(current_plan.task_spec_id)

        template = template_repo.get(patch.template_id) if patch.template_id else None
        if template is None and current_plan is not None and task_spec is not None:
            template = self._get_episode_template(
                plan=current_plan,
                task_spec=task_spec,
                patch=patch,
            )

        fallback_label = patch.divergence_summary or patch.title
        if task_spec is not None:
            patch_governance = {
                "domain_pack_version": str((DOMAIN_PACKS.get(task_spec.domain, DOMAIN_PACKS["general"])).get("version") or "1.0.0"),
                "domain_pack_maturity": str((DOMAIN_PACKS.get(task_spec.domain, DOMAIN_PACKS["general"])).get("maturity") or "experimental"),
                "episode_quality_band": str((patch.runtime_metadata or {}).get("episode_quality_band") or "medium"),
                "quality_gates": dict((DOMAIN_PACKS.get(task_spec.domain, DOMAIN_PACKS["general"])).get("quality_gates") or {}),
                "patch_id": patch.id,
                "governance_event": "patch_apply",
            }
            if template is None:
                template_key = f"{self._template_key(task_spec)}_patch"
                template = template_repo.by_template_key(template_key)
                base_body = {
                    "steps": list((current_plan.plan_body or {}).get("steps") or []) if current_plan is not None else self._default_steps(task_spec, None),
                    "checkpoints": list(current_plan.checkpoints or []) if current_plan is not None else self._default_checkpoints(task_spec, None),
                    "success_criteria": dict(task_spec.success_criteria or {}),
                    "patch_history": [],
                    "governance": patch_governance,
                    "governance_history": [{"recorded_at": utcnow().isoformat(), **patch_governance}],
                }
                if template is None:
                    template = template_repo.create(
                        WorkflowTemplateCreate(
                            template_key=template_key,
                            name=f"{task_spec.title} Patch Template",
                            domain=task_spec.domain,
                            status="draft",
                            source_task_spec_id=task_spec.id,
                            template_body=base_body,
                            activation_strategy={
                                "mode": "patch_review",
                                "lineage": {
                                    "source_task_spec_id": task_spec.id,
                                    "created_from_patch_id": patch.id,
                                    "created_from_plan_id": current_plan.id if current_plan is not None else None,
                                },
                                "governance": patch_governance,
                                "version_policy": {
                                    "strategy": "patch_review_semver",
                                    "promotion_gate": "patch_approval",
                                    "history_depth": 1,
                                },
                            },
                            validation_summary=patch.divergence_summary or patch.rationale or patch.title,
                            last_validated_at=utcnow(),
                        )
                    )
            if template is not None:
                template_steps = list((template.template_body or {}).get("steps") or [])
                patched_checkpoints = self._merge_patch_checkpoints(
                    list((template.template_body or {}).get("checkpoints") or []),
                    patch.patch_body,
                    fallback_label=fallback_label,
                )
                patched_steps = self._merge_patch_steps(template_steps, patch.patch_body) or template_steps
                patch_history = [
                    *list((template.template_body or {}).get("patch_history") or []),
                    {
                        "patch_id": patch.id,
                        "reviewer": reviewer,
                        "reason": reason,
                        "applied_at": utcnow().isoformat(),
                    },
                ]
                lineage = {
                    **dict((template.activation_strategy or {}).get("lineage") or {}),
                    "source_task_spec_id": task_spec.id,
                    "last_applied_patch_id": patch.id,
                    "last_applied_plan_id": current_plan.id if current_plan is not None else None,
                }
                governance_history = self._append_governance_history(
                    list((template.template_body or {}).get("governance_history") or []),
                    patch_governance,
                )
                template = template_repo.update(
                    template,
                    WorkflowTemplateUpdate(
                        version=int(template.version) + 1,
                        status="active",
                        template_body={
                            **dict(template.template_body or {}),
                            "steps": patched_steps,
                            "checkpoints": patched_checkpoints,
                            "patch_history": patch_history[-20:],
                            "governance": patch_governance,
                            "governance_history": governance_history,
                        },
                        activation_strategy={
                            **dict(template.activation_strategy or {}),
                            "mode": "patch_review",
                            "lineage": lineage,
                            "governance": self._merge_dicts(
                                dict((template.activation_strategy or {}).get("governance") or {}),
                                patch_governance,
                            ),
                            "version_policy": {
                                **dict((template.activation_strategy or {}).get("version_policy") or {}),
                                "strategy": "patch_review_semver",
                                "promotion_gate": "patch_approval",
                                "history_depth": len(governance_history),
                            },
                        },
                        validation_summary=reason or patch.divergence_summary or template.validation_summary,
                        last_validated_at=utcnow(),
                    ),
                )
                apply_result["template_id"] = template.id
                apply_result["template_version"] = template.version

        if current_plan is not None:
            new_checkpoints = self._merge_patch_checkpoints(
                list(current_plan.checkpoints or []),
                patch.patch_body,
                fallback_label=fallback_label,
            )
            new_steps = self._merge_patch_steps(list((current_plan.plan_body or {}).get("steps") or []), patch.patch_body)
            replanned = plan_repo.create(
                {
                    "task_spec_id": current_plan.task_spec_id,
                    "name": f"{current_plan.name} Patch v{int(current_plan.version) + 1}",
                    "mode": current_plan.mode,
                    "status": "validated",
                    "version": int(current_plan.version) + 1,
                    "approval_state": "approved",
                    "plan_body": {
                        **dict(current_plan.plan_body or {}),
                        "steps": new_steps,
                    },
                    "environment_requirements": self._merge_dicts(
                        dict(current_plan.environment_requirements or {}),
                        dict(patch.patch_body.get("environment_requirements") or {}),
                    ),
                    "checkpoints": new_checkpoints,
                    "runtime_metadata": {
                        **dict(current_plan.runtime_metadata or {}),
                        "patched_from_plan_id": current_plan.id,
                        "applied_patch_id": patch.id,
                        "patched_by": reviewer,
                        "patch_reason": reason,
                        "workflow_template_id": template.id if template is not None else dict(current_plan.runtime_metadata or {}).get("workflow_template_id"),
                        "workflow_template_key": template.template_key if template is not None else dict(current_plan.runtime_metadata or {}).get("workflow_template_key"),
                    },
                    "compiled_from_patch_id": patch.id,
                }
            )
            task = task_repo.get(current_plan.task_spec_id)
            if task is not None:
                task_repo.update(task, {"active_plan_id": replanned.id, "status": "validated"})
            apply_result["execution_plan_id"] = replanned.id
            apply_result["execution_plan_version"] = replanned.version
            apply_result["previous_plan_id"] = current_plan.id

        return apply_result

    def _seed_template(self, repo: WorkflowTemplateRepository, payload: dict[str, Any]):
        existing = repo.by_template_key(payload["template_key"])
        if existing is not None:
            return existing
        return repo.create(payload)

    def _resolve_assessment_context(
        self,
        payload: EnvironmentAssessmentRequest,
    ) -> tuple[Any | None, Any | None, Any | None, EnvironmentSnapshotContextRead | None, Any | None]:
        task_repo = TaskSpecRepository(self.session)
        plan_repo = ExecutionPlanRepository(self.session)
        episode_repo = ExecutionEpisodeRepository(self.session)
        snapshot_repo = EnvironmentSnapshotRepository(self.session)

        task_spec = task_repo.get(payload.task_spec_id) if payload.task_spec_id else None
        plan = plan_repo.get(payload.execution_plan_id) if payload.execution_plan_id else None
        episode = episode_repo.get(payload.execution_episode_id) if payload.execution_episode_id else None
        persisted_snapshot = snapshot_repo.get(payload.environment_snapshot_id) if payload.environment_snapshot_id else None

        if episode is not None:
            if task_spec is None:
                task_spec = task_repo.get(episode.task_spec_id)
            if plan is None:
                plan = plan_repo.get(episode.execution_plan_id)
            if persisted_snapshot is None:
                persisted_snapshot = snapshot_repo.latest_for_episode(episode.id)

        if persisted_snapshot is not None:
            if task_spec is None and persisted_snapshot.task_spec_id:
                task_spec = task_repo.get(persisted_snapshot.task_spec_id)
            if plan is None and persisted_snapshot.execution_plan_id:
                plan = plan_repo.get(persisted_snapshot.execution_plan_id)
            if episode is None and persisted_snapshot.execution_episode_id:
                episode = episode_repo.get(persisted_snapshot.execution_episode_id)

        if plan is not None and task_spec is None:
            task_spec = task_repo.get(plan.task_spec_id)

        if payload.task_spec_id and task_spec is None:
            raise ValueError("Task spec not found")
        if payload.execution_plan_id and plan is None:
            raise ValueError("Execution plan not found")
        if payload.execution_episode_id and episode is None:
            raise ValueError("Execution episode not found")
        if payload.environment_snapshot_id and persisted_snapshot is None:
            raise ValueError("Environment snapshot not found")

        snapshot_context: EnvironmentSnapshotContextRead | None = None
        if persisted_snapshot is not None:
            snapshot_context = self._snapshot_context_from_record(persisted_snapshot)
        elif payload.snapshot is not None:
            snapshot_context = self._snapshot_context_from_payload(payload.snapshot)

        return task_spec, plan, episode, snapshot_context, persisted_snapshot

    def _snapshot_context_from_record(self, snapshot: Any) -> EnvironmentSnapshotContextRead:
        return EnvironmentSnapshotContextRead(
            persisted=True,
            id=snapshot.id,
            source=snapshot.source,
            environment_key=snapshot.environment_key,
            status=snapshot.status,
            url=snapshot.url,
            title=snapshot.title,
            page_type=snapshot.page_type,
            capability_hints=list(snapshot.capability_hints or []),
            observed_entities=list(snapshot.observed_entities or []),
            affordances=list(snapshot.affordances or []),
            runtime_metadata=dict(snapshot.runtime_metadata or {}),
        )

    def _snapshot_context_from_payload(self, snapshot: EnvironmentSnapshotCreate) -> EnvironmentSnapshotContextRead:
        return EnvironmentSnapshotContextRead(
            persisted=False,
            source=snapshot.source,
            environment_key=snapshot.environment_key,
            status=snapshot.status,
            url=snapshot.url,
            title=snapshot.title,
            page_type=snapshot.page_type,
            capability_hints=list(snapshot.capability_hints or []),
            observed_entities=list(snapshot.observed_entities or []),
            affordances=list(snapshot.affordances or []),
            runtime_metadata=dict(snapshot.runtime_metadata or {}),
        )

    def _recommended_scene_types_for_capability(self, capability: str) -> list[str]:
        mapping = {
            "browser": ["web_scene", "interactive_surface"],
            "search": ["listing", "search_surface"],
            "http": ["api_surface", "remote_service"],
            "api": ["remote_service", "write_surface"],
            "command": ["local_runtime", "execution_surface"],
            "filesystem": ["local_runtime", "artifact_store"],
            "document": ["document_task", "result_pack"],
            "approval": ["review_gate"],
        }
        return list(mapping.get(capability, ["generic_scene"]))

    def _normalize_observed_entities(
        self,
        snapshot: EnvironmentSnapshotContextRead | None,
    ) -> list[ObservedEntityRead]:
        normalized: list[ObservedEntityRead] = []
        for raw in list(snapshot.observed_entities or []) if snapshot is not None else []:
            if not isinstance(raw, dict):
                continue
            kind = self._slugify(str(raw.get("kind") or raw.get("type") or raw.get("role") or "entity"))
            label = str(raw.get("label") or raw.get("name") or raw.get("text") or kind.replace("_", " ")).strip()
            if not label:
                label = kind.replace("_", " ")
            signal_values = [
                str(item).strip()
                for item in list(raw.get("signals") or raw.get("tags") or [])
                if str(item).strip()
            ]
            normalized.append(
                ObservedEntityRead(
                    kind=kind,
                    label=label,
                    entity_id=str(raw.get("id") or raw.get("entity_id") or "") or None,
                    role=str(raw.get("role") or "").strip() or None,
                    confidence=self._coerce_confidence(raw.get("confidence")),
                    state=str(raw.get("state") or "").strip() or None,
                    interactive=bool(raw.get("interactive") or raw.get("clickable")),
                    signals=list(dict.fromkeys(signal_values)),
                    locator=self._normalize_locator(raw),
                    attributes=self._normalize_attributes(raw, excluded={"signals", "tags", "kind", "type", "role", "id", "entity_id", "confidence", "state", "interactive", "clickable", "label", "name", "text"}),
                )
            )
        return normalized

    def _normalize_affordances(
        self,
        snapshot: EnvironmentSnapshotContextRead | None,
    ) -> list[ActionAffordanceRead]:
        normalized: list[ActionAffordanceRead] = []
        for raw in list(snapshot.affordances or []) if snapshot is not None else []:
            if not isinstance(raw, dict):
                continue
            kind = self._slugify(str(raw.get("kind") or raw.get("type") or raw.get("action") or "action"))
            raw_action = str(raw.get("action") or raw.get("intent") or "").strip()
            action = self._slugify(raw_action or self._default_affordance_action(kind))
            label = str(raw.get("label") or raw.get("name") or raw.get("text") or action.replace("_", " ")).strip()
            if not label:
                label = action.replace("_", " ")
            signal_values = [
                str(item).strip()
                for item in list(raw.get("signals") or raw.get("tags") or [])
                if str(item).strip()
            ]
            normalized.append(
                ActionAffordanceRead(
                    kind=kind,
                    label=label,
                    action=action,
                    target=str(raw.get("target") or raw.get("href") or raw.get("destination") or "").strip() or None,
                    confidence=self._coerce_confidence(raw.get("confidence")),
                    enabled=bool(raw.get("enabled", True)),
                    requires_confirmation=bool(raw.get("requires_confirmation") or raw.get("requiresApproval")),
                    signals=list(dict.fromkeys(signal_values)),
                    locator=self._normalize_locator(raw),
                    metadata=self._normalize_attributes(raw, excluded={"signals", "tags", "kind", "type", "action", "intent", "confidence", "enabled", "requires_confirmation", "requiresApproval", "label", "name", "text", "target", "href", "destination"}),
                )
            )
        return normalized

    def _default_affordance_action(self, kind: str) -> str:
        mapping = {
            "link": "navigate",
            "button": "click",
            "input": "fill",
            "textarea": "fill",
            "form": "submit",
        }
        return mapping.get(kind, kind or "inspect")

    def _normalize_locator(self, raw: dict[str, Any]) -> dict[str, Any]:
        locator = raw.get("locator")
        if isinstance(locator, dict):
            return dict(locator)
        selector = str(raw.get("selector") or raw.get("css") or raw.get("xpath") or "").strip()
        if selector:
            return {"selector": selector}
        return {}

    def _normalize_attributes(self, raw: dict[str, Any], *, excluded: set[str]) -> dict[str, Any]:
        return {str(key): value for key, value in raw.items() if str(key) not in excluded and value is not None}

    def _coerce_confidence(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number < 0:
            return 0.0
        if number > 1:
            return 1.0
        return number

    def _derive_scene_profile(
        self,
        *,
        snapshot: EnvironmentSnapshotContextRead | None,
        scene_type: str,
        observed_entities: list[ObservedEntityRead],
        affordances: list[ActionAffordanceRead],
    ) -> SceneProfileRead:
        source = snapshot.source if snapshot is not None else "runtime"
        auth_state = "unknown"
        interaction_mode = "inspect"
        volatility = "medium"
        signals: list[str] = []

        combined_labels = " ".join(
            [
                *[entity.label for entity in observed_entities],
                *[affordance.label for affordance in affordances],
                str(snapshot.title or "") if snapshot is not None else "",
                str(snapshot.page_type or "") if snapshot is not None else "",
            ]
        ).lower()
        if any(token in combined_labels for token in ("login", "sign in", "sign-in", "authenticate", "verification")):
            auth_state = "required"
            signals.append("auth_gate")
        if any(token in combined_labels for token in ("captcha", "verification code", "2fa", "verify")):
            auth_state = "challenged"
            signals.append("verification_gate")
        if any(action.action in {"click", "open", "navigate"} for action in affordances):
            interaction_mode = "navigate"
        if any(action.action in {"submit", "upload", "send"} for action in affordances):
            interaction_mode = "submit"
            signals.append("write_surface")
        if any(entity.kind in {"candidate_card", "repository_card", "result_card", "tool_card"} for entity in observed_entities):
            signals.append("listing_surface")
        if any(entity.kind in {"detail_panel", "candidate_detail", "repository_detail"} for entity in observed_entities):
            signals.append("detail_surface")
        if any(entity.kind in {"form", "editor", "composer"} for entity in observed_entities):
            signals.append("input_surface")
        if any(action.requires_confirmation for action in affordances):
            signals.append("approval_sensitive")
        if len(observed_entities) < 2 and len(affordances) < 2:
            volatility = "high"
            signals.append("low_signal_scene")
        elif len(observed_entities) >= 6 and len(affordances) >= 4:
            volatility = "low"
            signals.append("well_observed_scene")

        primary_targets = [
            entity.label
            for entity in observed_entities
            if entity.kind in {"candidate_card", "candidate_detail", "repository_card", "repository_detail", "tool_card", "document", "detail_panel"}
        ][:5]
        evidence = {
            "persisted_snapshot": bool(snapshot.persisted) if snapshot is not None else False,
            "observed_entity_kinds": sorted({entity.kind for entity in observed_entities}),
            "affordance_actions": sorted({affordance.action for affordance in affordances}),
        }
        return SceneProfileRead(
            source=source,
            scene_type=scene_type,
            interaction_mode=interaction_mode,
            volatility=volatility,
            auth_state=auth_state,
            entity_count=len(observed_entities),
            affordance_count=len(affordances),
            primary_targets=primary_targets,
            signals=list(dict.fromkeys(signals)),
            blockers=[],
            evidence=evidence,
        )

    def _derive_assessment_capabilities(
        self,
        *,
        task_spec: Any | None,
        plan: Any | None,
        snapshot: EnvironmentSnapshotContextRead | None,
        compiler_payload: dict[str, Any],
        scene_profile: SceneProfileRead | None = None,
    ) -> list[str]:
        capabilities: list[str] = []
        if task_spec is not None:
            capabilities.extend(list(task_spec.preferred_capabilities or []))
        if plan is not None:
            capabilities.extend(
                str(step.get("capability") or "").strip()
                for step in list((plan.plan_body or {}).get("steps") or [])
                if str(step.get("capability") or "").strip()
            )
        if snapshot is not None:
            capabilities.extend(list(snapshot.capability_hints or []))
        capabilities.extend(list(compiler_payload.get("preferred_capabilities") or []))
        if scene_profile is not None:
            if scene_profile.source == "browser":
                capabilities.append("browser")
            if scene_profile.interaction_mode == "submit":
                capabilities.append("approval")
            if "listing_surface" in scene_profile.signals:
                capabilities.append("search")
            if "write_surface" in scene_profile.signals:
                capabilities.append("document")
        capabilities = [item for item in capabilities if item in CAPABILITY_DRIVERS]
        if not capabilities and task_spec is not None:
            capabilities = self._infer_capabilities(task_spec.goal, task_spec.domain, [])
        if not capabilities:
            capabilities = list(DOMAIN_PACKS["general"]["default_capabilities"])
        return list(dict.fromkeys(capabilities))

    def _derive_scene_type(
        self,
        snapshot: EnvironmentSnapshotContextRead | None,
        *,
        observed_entities: list[ObservedEntityRead] | None = None,
        affordances: list[ActionAffordanceRead] | None = None,
    ) -> str:
        if snapshot is None:
            return "generic_runtime"
        if snapshot.page_type:
            return self._slugify(snapshot.page_type)
        entity_kinds = {entity.kind for entity in observed_entities or []}
        affordance_actions = {affordance.action for affordance in affordances or []}
        if {"candidate_card", "repository_card", "tool_card"} & entity_kinds:
            return "listing_scene"
        if {"candidate_detail", "repository_detail", "detail_panel"} & entity_kinds:
            return "detail_scene"
        if "upload" in affordance_actions:
            return "upload_scene"
        if {"submit", "send"} & affordance_actions:
            return "submission_scene"
        if snapshot.source == "browser":
            return "web_scene" if snapshot.url else "browser_scene"
        if snapshot.source in {"http", "api"}:
            return "api_surface"
        if snapshot.source == "command":
            return "local_runtime"
        return "runtime_state"

    def _derive_assessment_blockers(
        self,
        *,
        plan: Any | None,
        episode: Any | None,
        snapshot: EnvironmentSnapshotContextRead | None,
        recommended_capabilities: list[str],
        scene_profile: SceneProfileRead | None = None,
    ) -> list[str]:
        blockers: list[str] = []
        requires_browser = "browser" in recommended_capabilities or bool((plan.environment_requirements or {}).get("requires_browser")) if plan is not None else "browser" in recommended_capabilities
        if requires_browser and (snapshot is None or snapshot.source != "browser"):
            blockers.append("missing_browser_snapshot")
        if snapshot is not None and snapshot.source == "browser" and not snapshot.affordances and not snapshot.observed_entities:
            blockers.append("limited_interaction_signals")
        if scene_profile is not None:
            if scene_profile.auth_state == "required":
                blockers.append("authentication_required")
            if scene_profile.auth_state == "challenged":
                blockers.append("verification_required")
            if scene_profile.source == "browser" and scene_profile.affordance_count == 0:
                blockers.append("missing_actionable_affordances")
            if "low_signal_scene" in scene_profile.signals:
                blockers.append("scene_needs_reassessment")
        if episode is not None and bool(episode.divergence_detected):
            blockers.append("prior_divergence_detected")
        return list(dict.fromkeys(blockers))

    def _environment_requirements_from_snapshot(
        self,
        snapshot: EnvironmentSnapshotContextRead | None,
        *,
        observed_entities: list[ObservedEntityRead],
        affordances: list[ActionAffordanceRead],
        scene_profile: SceneProfileRead,
    ) -> dict[str, Any]:
        if snapshot is None:
            return {}
        requirements: dict[str, Any] = {
            "requires_browser": snapshot.source == "browser",
            "observed_affordance_count": len(affordances),
            "observed_entity_count": len(observed_entities),
            "scene_interaction_mode": scene_profile.interaction_mode,
        }
        if scene_profile.auth_state in {"required", "challenged"}:
            requirements["requires_authentication"] = True
        if any(action.action in {"send", "submit", "upload"} for action in affordances):
            requirements["requires_approval_gate"] = True
        if any(entity.kind in {"form", "editor", "composer"} for entity in observed_entities):
            requirements["requires_input_validation"] = True
        return requirements

    def _assessment_checkpoints(
        self,
        *,
        blockers: list[str],
        snapshot: EnvironmentSnapshotContextRead | None,
        scene_profile: SceneProfileRead,
        planner_guidance: PlannerGuidanceRead,
    ) -> list[dict[str, Any]]:
        checkpoints: list[dict[str, Any]] = [{"kind": "scene_assessment", "label": "审查环境评估结果"}]
        if snapshot is not None and snapshot.source == "browser":
            checkpoints.append({"kind": "snapshot", "label": "确认已捕获的环境状态"})
        if planner_guidance.requires_scene_assessment:
            checkpoints.append({"kind": "planner", "label": "执行前确认重规划姿态"})
        if scene_profile.auth_state in {"required", "challenged"}:
            checkpoints.append({"kind": "approval", "label": "恢复前先处理认证或校验问题"})
        if blockers:
            checkpoints.append({"kind": "approval", "label": "执行前先处理阻塞项"})
        return checkpoints

    def _build_assessment_notes(
        self,
        *,
        domain: str,
        scene_type: str,
        blockers: list[str],
        recommended_capabilities: list[str],
        compiler_payload: dict[str, Any],
        scene_profile: SceneProfileRead,
        planner_guidance: PlannerGuidanceRead,
    ) -> list[str]:
        notes = [
            f"Assessed scene type: {scene_type}.",
            f"Recommended capabilities: {', '.join(recommended_capabilities)}.",
            f"Planner posture: {planner_guidance.posture}.",
            f"Scene interaction mode: {scene_profile.interaction_mode}.",
            f"Applied generic domain heuristics for {domain}.",
            "No fixed-site assumptions were introduced during assessment.",
        ]
        if blockers:
            notes.append(f"Detected blockers: {', '.join(blockers)}.")
        if compiler_payload:
            notes.append(
                f"Assessment merged compiler payload keys: {', '.join(sorted(str(key) for key in compiler_payload.keys()))}."
            )
        return notes

    def _derive_planner_guidance(
        self,
        *,
        scene_profile: SceneProfileRead,
        recommended_capabilities: list[str],
        blockers: list[str],
        compiler_payload: dict[str, Any],
    ) -> PlannerGuidanceRead:
        posture = "advance"
        inserted: list[str] = []
        preferred_next_actions: list[str] = []
        rationale: list[str] = []
        requires_review = bool(blockers)
        requires_scene_assessment = scene_profile.source == "browser"

        if blockers:
            posture = "recover"
            rationale.append("The current scene has unresolved blockers and needs supervised recovery.")
        elif scene_profile.interaction_mode in {"navigate", "inspect"}:
            posture = "verify"
            rationale.append("The planner should verify the scene before deeper extraction.")
        if scene_profile.auth_state in {"required", "challenged"}:
            inserted.extend(["approval", "browser"])
            preferred_next_actions.append("Resolve authentication or verification before continuing.")
            requires_review = True
        if "listing_surface" in scene_profile.signals:
            inserted.append("search")
            preferred_next_actions.append("Confirm the listing layout and identify the primary target set.")
        if "detail_surface" in scene_profile.signals:
            preferred_next_actions.append("Capture detail evidence before summarizing or writing downstream.")
        if scene_profile.interaction_mode == "submit":
            inserted.append("approval")
            preferred_next_actions.append("Pause before any write-oriented browser action.")
            requires_review = True
        if compiler_payload.get("step_outline"):
            rationale.append("The compiler provided an initial step outline that should be preserved where valid.")
        return PlannerGuidanceRead(
            posture=posture,
            required_capabilities=list(dict.fromkeys(recommended_capabilities)),
            inserted_capabilities=list(dict.fromkeys(cap for cap in inserted if cap in CAPABILITY_DRIVERS)),
            preferred_next_actions=list(dict.fromkeys(preferred_next_actions)),
            requires_scene_assessment=requires_scene_assessment,
            requires_human_review=requires_review,
            should_checkpoint=True,
            rationale=rationale or ["The current plan can proceed after a lightweight scene verification pass."],
        )

    def _derive_assessment_confidence(
        self,
        *,
        snapshot: EnvironmentSnapshotContextRead | None,
        observed_entities: list[ObservedEntityRead],
        affordances: list[ActionAffordanceRead],
        blockers: list[str],
        plan: Any | None,
    ) -> float:
        confidence = 0.92 if snapshot is not None else 0.64 if plan is not None else 0.5
        if observed_entities:
            confidence += min(0.04, len(observed_entities) * 0.01)
        if affordances:
            confidence += min(0.04, len(affordances) * 0.01)
        if blockers:
            confidence -= min(0.18, len(blockers) * 0.04)
        return max(0.2, min(0.98, confidence))

    def _scene_driven_replan_steps(self, assessment: EnvironmentAssessmentRead) -> list[dict[str, Any]]:
        scene_profile = assessment.scene_profile
        steps: list[dict[str, Any]] = []
        if assessment.planner_guidance.requires_scene_assessment:
            steps.append(
                {
                    "id": "assess_runtime_scene",
                    "capability": "browser" if "browser" in assessment.recommended_capabilities else "analyze",
                    "summary": "Refresh the runtime scene model and validate the current target before proceeding.",
                }
            )

        if scene_profile.auth_state in {"required", "challenged"}:
            steps.append(
                {
                    "id": "resolve_access_gate",
                    "capability": "approval",
                    "summary": "Pause for operator help to clear the authentication or verification gate.",
                }
            )
            return steps

        if "listing_surface" in scene_profile.signals:
            steps.extend(
                [
                    {
                        "id": "triage_visible_targets",
                        "capability": "browser",
                        "summary": "Inspect the visible target list and capture the strongest candidate set for the current task.",
                    },
                    {
                        "id": "select_priority_target",
                        "capability": "analyze",
                        "summary": "Choose the next target to open based on the task contract, evidence, and current scene state.",
                    },
                ]
            )
        elif "detail_surface" in scene_profile.signals:
            steps.extend(
                [
                    {
                        "id": "inspect_detail_surface",
                        "capability": "browser",
                        "summary": "Inspect the focused detail surface and capture the durable evidence needed downstream.",
                    },
                    {
                        "id": "record_detail_evidence",
                        "capability": "document",
                        "summary": "Summarize the captured detail evidence before deciding whether to continue, branch, or write.",
                    },
                ]
            )

        if scene_profile.interaction_mode == "submit":
            steps.append(
                {
                    "id": "review_write_risk",
                    "capability": "approval",
                    "summary": "Review the pending write-oriented action before allowing the runtime to continue.",
                }
            )
        return steps

    def _derive_replanned_steps(
        self,
        *,
        current_steps: list[dict[str, Any]],
        assessment: EnvironmentAssessmentRead,
        compiler_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        compiler_steps = self._normalize_steps(list(compiler_payload.get("step_outline") or []))
        if compiler_steps:
            steps = [
                *self._scene_driven_replan_steps(assessment),
                *compiler_steps,
            ]
        else:
            steps = [
                *self._scene_driven_replan_steps(assessment),
                *self._normalize_steps(
                    current_steps,
                    domain=(assessment.execution_plan.plan_body or {}).get("domain", "general")
                    if assessment.execution_plan is not None
                    else "general",
                ),
            ]
            if assessment.blockers and not any(str(step.get("id") or "") == "reassess_environment" for step in steps):
                steps.insert(
                    0,
                    {
                        "id": "reassess_environment",
                        "capability": "analyze",
                        "summary": "Review the current scene and update the plan before retrying.",
                    },
                )
            missing_capabilities = [
                capability
                for capability in [
                    *assessment.planner_guidance.inserted_capabilities,
                    *assessment.recommended_capabilities,
                ]
                if capability not in {str(step.get("capability") or "") for step in steps}
            ]
            for index, capability in enumerate(missing_capabilities, start=1):
                steps.append(
                    {
                        "id": f"adapt_{capability}_{index}",
                        "capability": capability,
                        "summary": self._step_summary(
                            (assessment.execution_plan.plan_body or {}).get("domain", "general")
                            if assessment.execution_plan is not None
                            else "general",
                            capability,
                        ),
                    }
                )
        if assessment.blockers and not any(str(step.get("capability")) == "approval" for step in steps):
            steps.append(
                {
                    "id": "review_replanned_execution",
                    "capability": "approval",
                    "summary": "Pause for review before executing the updated plan.",
                }
            )
        return self._normalize_steps(
            steps,
            domain=(assessment.execution_plan.plan_body or {}).get("domain", "general")
            if assessment.execution_plan is not None
            else "general",
        )

    def _normalize_steps(self, steps: list[dict[str, Any]], *, domain: str = "general") -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, dict):
                continue
            capability = str(raw_step.get("capability") or "").strip().lower()
            if not capability:
                capability = self._infer_step_capability(raw_step, domain=domain)
            if capability not in CAPABILITY_DRIVERS:
                capability = "analyze"
            step_id = str(raw_step.get("id") or f"{capability}_{index}").strip() or f"{capability}_{index}"
            marker = f"{step_id}:{capability}"
            if marker in seen:
                continue
            seen.add(marker)
            normalized.append(
                {
                    **dict(raw_step),
                    "id": step_id,
                    "capability": capability,
                    "summary": raw_step.get("summary") or self._step_summary(domain, capability),
                }
            )
        return normalized

    def _infer_step_capability(self, raw_step: dict[str, Any], *, domain: str) -> str:
        text = " ".join(
            str(raw_step.get(key) or "").strip()
            for key in ("action", "summary", "details", "name", "objective", "id")
        ).lower()
        if not text:
            return "analyze"

        keyword_groups = [
            ("analyze", ("requirements", "input", "scope", "constraint", "goal", "任务输入", "岗位要求", "评分标准", "约束", "目标")),
            ("approval", ("approve", "approval", "review", "checkpoint", "人工确认", "审批", "审阅")),
            ("command", ("command", "shell", "terminal", "cli", "命令", "终端")),
            ("api", ("upload", "sync", "submit", "push", "handoff", "write", "api", "提交", "同步", "写入", "上传")),
            ("filesystem", ("file", "filesystem", "download", "export", "保存到本地", "文件", "导出", "下载")),
            ("search", ("search", "find", "locate", "discover", "query", "筛选", "搜索", "查找", "发现", "选择候选人")),
            ("browser", ("open", "inspect", "view", "browse", "page", "site", "workspace", "profile", "resume", "scene", "页面", "网站", "工作台", "资料", "简历", "浏览", "查看")),
            ("document", ("summarize", "draft", "record", "capture evidence", "prepare output", "bundle", "report", "summary", "输出", "整理", "记录", "总结", "证据", "结论")),
            ("llm", ("score", "evaluate", "assess", "reason", "recommend", "classify", "rank", "评分", "评估", "分析", "判断", "建议")),
        ]
        for capability, keywords in keyword_groups:
            if any(keyword in text for keyword in keywords):
                return capability

        domain_defaults = list((DOMAIN_PACKS.get(domain) or DOMAIN_PACKS["general"]).get("default_capabilities") or [])
        return domain_defaults[0] if domain_defaults else "analyze"

    def _dedupe_dict_list(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            marker = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(item)
        return deduped

    def _build_execution_contract(
        self,
        *,
        task_spec,
        plan,
        episode,
        assessment: EnvironmentAssessmentRead,
        capability_drivers: list[CapabilityDriverRead],
        task_payload: dict[str, Any],
    ) -> dict[str, Any]:
        driver_by_key = {driver.key: driver for driver in capability_drivers}
        steps: list[dict[str, Any]] = []
        for index, raw_step in enumerate(self._normalize_steps(list((plan.plan_body or {}).get("steps") or [])), start=1):
            capability = str(raw_step.get("capability") or "analyze")
            driver = driver_by_key.get(capability)
            steps.append(
                {
                    **dict(raw_step),
                    "index": index,
                    "executor_mode": driver.executor_mode if driver is not None else "tool_loop",
                    "replan_on_error": bool(driver.replan_on_error) if driver is not None else False,
                    "scene_required": bool(driver.scene_required) if driver is not None else False,
                    "preferred_tools": list(driver.preferred_tools) if driver is not None else [],
                    "checkpoint_policy": dict(driver.checkpoint_policy) if driver is not None else {},
                }
            )

        return {
            "contract_version": "runtime-execution-contract-v1",
            "task_spec_id": task_spec.id,
            "execution_plan_id": plan.id,
            "execution_episode_id": episode.id,
            "plan_name": plan.name,
            "domain": task_spec.domain,
            "goal": task_spec.goal,
            "mode": episode.mode,
            "status": plan.status,
            "scene_type": assessment.scene_type,
            "planner_posture": assessment.planner_guidance.posture,
            "approval_policy": dict(task_spec.approval_policy or {}),
            "output_contract": dict(task_spec.output_contract or {}),
            "environment_requirements": self._merge_dicts(
                dict(plan.environment_requirements or {}),
                assessment.environment_requirements,
            ),
            "checkpoints": self._dedupe_dict_list(
                [*list(plan.checkpoints or []), *list(assessment.checkpoints or [])]
            ),
            "planner_guidance": assessment.planner_guidance.model_dump(),
            "scene_profile": assessment.scene_profile.model_dump(),
            "recommended_capabilities": list(assessment.recommended_capabilities),
            "preferred_next_actions": list(assessment.planner_guidance.preferred_next_actions),
            "blockers": list(assessment.blockers),
            "task_payload": task_payload,
            "steps": steps,
            "current_step_id": steps[0]["id"] if steps else None,
        }

    def _trial_task_payload(self, *, task_spec, plan, payload: TrialRunExecuteRequest) -> dict[str, Any]:
        return {
            "instruction": task_spec.source_text or task_spec.goal,
            "goal": task_spec.goal,
            "domain": task_spec.domain,
            "plan_name": plan.name,
            "operator": payload.operator,
            "notes": payload.notes,
            "environment_snapshot": {
                "source": payload.source,
                "environment_key": payload.environment_key,
                "url": payload.url,
                "title": payload.title,
                "page_type": payload.page_type,
                "observed_entities": list(payload.observed_entities or []),
                "affordances": list(payload.affordances or []),
                "capability_hints": list(payload.capability_hints or []),
                "runtime_metadata": dict(payload.runtime_metadata or {}),
            },
        }

    def _latest_replan_request(self, result: AgentResult) -> dict[str, Any]:
        trace = dict(result.metadata.get("executor_trace") or {})
        requests = list(trace.get("replan_requests") or [])
        if requests:
            return dict(requests[-1])
        control = dict(result.metadata.get("executor_control") or {})
        return control if control else {}

    def _latest_snapshot_id(self, execution_episode_id: str) -> str | None:
        latest = EnvironmentSnapshotRepository(self.session).latest_for_episode(execution_episode_id)
        return latest.id if latest is not None else None

    def _managed_snapshot_payload(
        self,
        *,
        task_spec,
        plan,
        execution_episode_id: str | None,
        task_payload: dict[str, Any],
        runtime_metadata: dict[str, Any],
    ) -> EnvironmentSnapshotCreate | None:
        raw_snapshot = (
            runtime_metadata.get("environment_snapshot")
            or runtime_metadata.get("scene_snapshot")
            or task_payload.get("environment_snapshot")
            or task_payload.get("scene_snapshot")
        )
        if not isinstance(raw_snapshot, dict):
            if not any(task_payload.get(key) for key in ("url", "title", "page_type", "observed_entities", "affordances")):
                return None
            raw_snapshot = task_payload

        source = str(raw_snapshot.get("source") or ("browser" if "browser" in list(task_spec.preferred_capabilities or []) else "runtime"))
        environment_key = str(
            raw_snapshot.get("environment_key")
            or f"{task_spec.domain}:{raw_snapshot.get('page_type') or 'runtime_scene'}"
        )
        return EnvironmentSnapshotCreate(
            task_spec_id=task_spec.id,
            execution_plan_id=plan.id,
            execution_episode_id=execution_episode_id,
            source=source,
            environment_key=environment_key,
            status=str(raw_snapshot.get("status") or "captured"),
            url=raw_snapshot.get("url"),
            title=raw_snapshot.get("title"),
            page_type=raw_snapshot.get("page_type"),
            capability_hints=list(raw_snapshot.get("capability_hints") or list(task_spec.preferred_capabilities or [])),
            observed_entities=list(raw_snapshot.get("observed_entities") or []),
            affordances=list(raw_snapshot.get("affordances") or []),
            runtime_metadata=dict(raw_snapshot.get("runtime_metadata") or {}),
        )

    def _managed_environment_snapshot_create(
        self,
        *,
        task_spec,
        plan,
        episode,
        task_payload: dict[str, Any],
        scene_snapshot: dict[str, Any],
    ) -> EnvironmentSnapshotCreate:
        source = str(scene_snapshot.get("source") or ("browser" if "browser" in list(task_spec.preferred_capabilities or []) else "runtime"))
        page_type = str(scene_snapshot.get("page_type") or task_payload.get("page_type") or "runtime_scene")
        return EnvironmentSnapshotCreate(
            task_spec_id=task_spec.id,
            execution_plan_id=plan.id,
            execution_episode_id=episode.id,
            source=source,
            environment_key=str(scene_snapshot.get("environment_key") or f"{task_spec.domain}:{page_type}"),
            status=str(scene_snapshot.get("status") or "captured"),
            url=scene_snapshot.get("url") or task_payload.get("url"),
            title=scene_snapshot.get("title") or task_payload.get("title") or task_spec.title,
            page_type=page_type,
            capability_hints=list(scene_snapshot.get("capability_hints") or list(task_spec.preferred_capabilities or [])),
            observed_entities=list(scene_snapshot.get("observed_entities") or []),
            affordances=list(scene_snapshot.get("affordances") or []),
            runtime_metadata=dict(scene_snapshot.get("runtime_metadata") or {}),
        )

    def _managed_observations(self, *, episode, trace: dict[str, Any], result: AgentResult) -> list[dict[str, Any]]:
        observations = list(episode.observations or [])
        observations.extend(list(trace.get("observations") or []))
        for error in list(trace.get("errors") or []):
            observations.append(
                {
                    "kind": "tool_error",
                    "summary": error.get("message") or "Tool execution failed.",
                    "tool_name": error.get("tool_name"),
                    "step_id": error.get("step_id"),
                }
            )
        control = dict(result.metadata.get("executor_control") or {})
        if control:
            observations.append(
                {
                    "kind": control.get("kind") or "executor_control",
                    "summary": control.get("reason") or result.content,
                }
            )
        return observations

    def _managed_actions(self, *, episode, trace: dict[str, Any]) -> list[dict[str, Any]]:
        actions = list(episode.actions or [])
        actions.extend(list(trace.get("actions") or []))
        return actions

    def _managed_metrics(self, *, plan, trace: dict[str, Any], result: AgentResult) -> dict[str, Any]:
        steps = list((plan.plan_body or {}).get("steps") or [])
        completed = list(result.metadata.get("completed_step_ids") or [])
        total_steps = len(steps)
        return {
            "step_count": total_steps,
            "completed_step_count": len(completed),
            "completion_rate": (len(completed) / total_steps) if total_steps else 1.0,
            "tool_output_count": len(result.tool_outputs),
            "observation_count": len(list(trace.get("observations") or [])),
            "action_count": len(list(trace.get("actions") or [])),
            "replan_request_count": len(list(trace.get("replan_requests") or [])),
            "human_checkpoint_count": len(list(trace.get("human_checkpoints") or [])),
        }

    def _managed_episode_status(self, result: AgentResult, *, requires_confirmation: bool = False) -> str:
        if result.status == "waiting_human":
            return "awaiting_review"
        if result.status == "replan_requested":
            return "diverged"
        if result.success and requires_confirmation:
            return "awaiting_review"
        if result.success:
            return "completed"
        if result.status in {"timeout", "failed"}:
            return "failed"
        return result.status or "completed"

    def _runtime_result_summary(self, domain: str, result: AgentResult) -> str:
        if result.content:
            return result.content
        if result.success:
            return f"Runtime execution completed for {domain}."
        return f"Runtime execution ended with {result.status} for {domain}."

    def _latest_scene_update(self, trace: dict[str, Any]) -> dict[str, Any] | None:
        updates = list(trace.get("scene_updates") or [])
        if not updates:
            return None
        latest = updates[-1]
        return dict(latest) if isinstance(latest, dict) else None

    def _simulate_managed_divergence(
        self,
        *,
        result: AgentResult,
        episode: ExecutionEpisodeRead,
        plan: ExecutionPlanRead,
    ) -> AgentResult:
        trace = dict(result.metadata.get("executor_trace") or {})
        reason = "Managed trial simulated a divergence and requested replanning."
        trace.setdefault("replan_requests", []).append(
            {
                "reason": reason,
                "trigger": "simulated_divergence",
                "step_id": trace.get("current_step_id"),
                "preferred_capabilities": [
                    str(step.get("capability") or "")
                    for step in list((plan.plan_body or {}).get("steps") or [])
                    if str(step.get("capability") or "").strip()
                ],
            }
        )
        return AgentResult(
            success=False,
            status="replan_requested",
            content=reason,
            data=dict(result.data or {}),
            skill_draft=result.skill_draft,
            messages=list(result.messages or []),
            usage=result.usage,
            tool_outputs=list(result.tool_outputs or []),
            metadata={
                **dict(result.metadata or {}),
                "executor_trace": trace,
                "executor_control": {"kind": "replan_requested", "reason": reason},
            },
        )

    def _default_steps(self, task_spec, template) -> list[dict[str, Any]]:
        if template is not None:
            template_steps = list((template.template_body or {}).get("steps") or [])
            if template_steps:
                return template_steps
        compiled_steps = list((task_spec.compiled_payload or {}).get("step_outline") or [])
        if compiled_steps:
            return compiled_steps
        capabilities = list(task_spec.preferred_capabilities or [])
        if not capabilities:
            capabilities = list((DOMAIN_PACKS.get(task_spec.domain) or DOMAIN_PACKS["general"])["default_capabilities"])
        steps = [{"id": "understand_task", "capability": "analyze", "goal": task_spec.goal}]
        if "browser" in capabilities:
            steps.append(
                {
                    "id": "assess_runtime_scene",
                    "capability": "browser",
                    "summary": "Inspect the active browser scene and confirm that the runtime is observing the right surface.",
                }
            )
        for index, capability in enumerate(capabilities, start=1):
            if capability == "browser" and any(str(step.get("capability")) == "browser" for step in steps):
                continue
            steps.append(
                {
                    "id": f"{capability}_{index}",
                    "capability": capability,
                    "summary": self._step_summary(task_spec.domain, capability),
                }
            )
        steps.append({"id": "summarize_result", "capability": "document"})
        return steps

    def _default_checkpoints(self, task_spec, template) -> list[dict[str, Any]]:
        domain_config = DOMAIN_PACKS.get(task_spec.domain) or DOMAIN_PACKS["general"]
        checkpoints = [{"kind": "approval", "label": "审查试跑输出"}]
        checkpoints.extend(list((task_spec.compiled_payload or {}).get("checkpoints") or []))
        if template is not None:
            checkpoints.append({"kind": "template", "label": template.template_key})
        if task_spec.approval_policy:
            checkpoints.append({"kind": "policy", "label": "遵守任务审批策略"})
        if "browser" in (task_spec.preferred_capabilities or []):
            checkpoints.append({"kind": "snapshot", "label": "捕获环境快照"})
            checkpoints.append({"kind": "planner", "label": "继续前验证当前运行时场景"})
        if (domain_config.get("quality_gates") or {}).get("requires_source_links"):
            checkpoints.append({"kind": "quality_gate", "label": "输出定稿前核对来源链接"})
        if (domain_config.get("quality_gates") or {}).get("requires_downstream_write_review"):
            checkpoints.append({"kind": "approval", "label": "发布前审查下游写入或交接动作"})
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for checkpoint in checkpoints:
            key = json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(checkpoint)
        return deduped

    def _default_environment_requirements(self, domain: str, capabilities: list[str]) -> dict[str, Any]:
        domain_config = DOMAIN_PACKS.get(domain) or DOMAIN_PACKS["general"]
        hints = {
            "requires_browser": "browser" in capabilities,
            "requires_network": any(cap in capabilities for cap in ("http", "search", "browser")),
            "scene_assessment_required": "browser" in capabilities,
            "scene_expectations": list(domain_config.get("scene_expectations") or []),
            "quality_gates": dict(domain_config.get("quality_gates") or {}),
        }
        if domain == "recruiting":
            hints["requires_approval_gate"] = True
        return hints

    def _resolve_domain_pack(
        self,
        domain_hint: str | None,
        instruction: str,
        preferred_domains: list[str] | None = None,
    ) -> tuple[str, dict[str, Any], list[str]]:
        notes: list[str] = []
        candidates = [domain_hint, *(preferred_domains or [])]
        for candidate in candidates:
            normalized = self._normalize_domain(candidate)
            if normalized in DOMAIN_PACKS:
                notes.append(f"Selected execution profile from explicit hint: {normalized}.")
                return normalized, DOMAIN_PACKS[normalized], notes

        normalized_instruction = instruction.lower()
        keyword_map = {
            "recruiting": ("candidate", "resume", "jd", "boss", "hiring", "recruit"),
            "archived_public_briefing": ("stock", "market", "equity", "news", "macro", "earnings"),
            "archived_repository_watch": ("github", "repository", "repo", "open source", "trending"),
            "archived_public_research": ("search", "find", "tool", "pdf", "compare", "website"),
        }
        for domain_key, keywords in keyword_map.items():
            if any(keyword in normalized_instruction for keyword in keywords):
                notes.append(f"Inferred execution profile {domain_key} from keyword match.")
                return domain_key, DOMAIN_PACKS[domain_key], notes

        notes.append("No strong domain keyword match found. Falling back to general automation.")
        return "general", DOMAIN_PACKS["general"], notes

    def _infer_capabilities(self, instruction: str, domain_key: str, preferred_capabilities: list[str]) -> list[str]:
        capabilities = list(DOMAIN_PACKS.get(domain_key, DOMAIN_PACKS["general"])["default_capabilities"])
        normalized_instruction = instruction.lower()
        keyword_to_capability = {
            "browser": ("open", "click", "page", "website", "web"),
            "search": ("find", "search", "discover", "latest"),
            "http": ("api", "fetch", "request"),
            "document": ("summary", "digest", "report", "output", "write"),
            "filesystem": ("file", "folder", "directory", "save", "export", "download"),
            "api": ("upload", "sync", "push"),
            "command": ("command", "terminal", "shell"),
        }
        for capability, keywords in keyword_to_capability.items():
            if any(keyword in normalized_instruction for keyword in keywords):
                capabilities.append(capability)
        capabilities.extend(preferred_capabilities)
        return list(dict.fromkeys(capabilities))

    def _default_success_criteria(self, domain_key: str) -> dict[str, Any]:
        if domain_key == "recruiting":
            return {"requires_resume_or_profile": True, "requires_score": True}
        if domain_key == "archived_public_briefing":
            return {"minimum_sources": 3, "include_market_impact": True}
        if domain_key == "archived_repository_watch":
            return {"minimum_repositories": 5, "include_repo_links": True}
        if domain_key == "archived_public_research":
            return {"minimum_candidates": 3, "include_comparison": True}
        return {"task_completed": True, "supervised_trial": True}

    def _derive_title(self, instruction: str, domain_name: str) -> str:
        text = " ".join(instruction.strip().split())
        if not text:
            return f"{domain_name} Task"
        pieces = re.split(r"[.!?;，。；]", text, maxsplit=1)
        seed = pieces[0].strip()
        return seed[:80] if seed else f"{domain_name} Task"

    def _derive_goal(self, instruction: str) -> str:
        text = " ".join(instruction.strip().split())
        if not text:
            return "Execute the requested automation task under supervision."
        if len(text) <= 240:
            return text
        return f"{text[:237]}..."

    def _keyword_hits(self, instruction: str) -> list[str]:
        normalized = instruction.lower()
        hits: list[str] = []
        for keyword in ("candidate", "resume", "market", "news", "github", "repo", "pdf", "search", "upload"):
            if keyword in normalized:
                hits.append(keyword)
        return hits

    def _simulate_episode(
        self,
        task_spec,
        plan,
        episode,
        payload: TrialRunExecuteRequest,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str]:
        steps = list((plan.plan_body or {}).get("steps") or [])
        observations: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        for index, step in enumerate(steps, start=1):
            capability = str(step.get("capability") or "llm")
            step_id = str(step.get("id") or f"step_{index}")
            actions.append(
                {
                    "step_id": step_id,
                    "capability": capability,
                    "status": "completed",
                    "summary": self._step_summary(task_spec.domain, capability),
                }
            )
            observations.append(
                {
                    "step_id": step_id,
                    "kind": "observation",
                    "summary": self._observation_summary(task_spec.domain, capability),
                    "evidence": step.get("summary") or self._step_summary(task_spec.domain, capability),
                }
            )

        completion_rate = 1.0 if steps else 0.0
        metrics = {
            "step_count": len(steps),
            "action_count": len(actions),
            "observation_count": len(observations),
            "completion_rate": completion_rate,
            "domain": task_spec.domain,
        }
        result_summary = self._result_summary(task_spec.domain, payload.notes)
        return observations, actions, metrics, result_summary

    def _ensure_environment_snapshot(
        self,
        *,
        task_spec_id: str,
        execution_plan_id: str,
        execution_episode_id: str,
        payload: TrialRunExecuteRequest,
        plan,
        task_spec,
    ) -> None:
        source = payload.source or ("browser" if "browser" in (task_spec.preferred_capabilities or []) else "runtime")
        snapshot_payload = EnvironmentSnapshotCreate(
            task_spec_id=task_spec_id,
            execution_plan_id=execution_plan_id,
            execution_episode_id=execution_episode_id,
            source=source,
            environment_key=payload.environment_key or f"{task_spec.domain}:{source}",
            status="captured",
            url=payload.url,
            title=payload.title or self._derive_snapshot_title(task_spec, plan, payload.url),
            page_type=payload.page_type or self._derive_page_type(task_spec.domain, payload.url),
            capability_hints=payload.capability_hints or list(task_spec.preferred_capabilities or []),
            observed_entities=payload.observed_entities,
            affordances=payload.affordances or self._default_affordances(task_spec.domain),
            runtime_metadata={"plan_name": plan.name, **dict(payload.runtime_metadata)},
        )
        self.create_environment_snapshot(snapshot_payload)

    def _materialize_template(self, *, task_spec, plan, episode):
        existing_template = self._episode_template(episode)
        if existing_template is not None:
            return existing_template
        if episode.divergence_detected:
            return None
        repo = WorkflowTemplateRepository(self.session)
        template_key = self._template_key(task_spec)
        template = repo.by_template_key(template_key)
        domain_config = DOMAIN_PACKS.get(task_spec.domain, DOMAIN_PACKS["general"])
        template_governance = self._build_episode_governance_snapshot(
            task_spec=task_spec,
            plan=plan,
            episode=episode,
            domain_config=domain_config,
        )
        governance_history = self._append_governance_history(
            list((template.template_body or {}).get("governance_history") or []) if template is not None else [],
            template_governance,
        )
        payload = {
            "template_key": template_key,
            "name": f"{task_spec.title} Template",
            "domain": task_spec.domain,
            "status": "draft" if episode.requires_confirmation else "active",
            "source_task_spec_id": task_spec.id,
            "template_body": {
                "steps": list((plan.plan_body or {}).get("steps") or []),
                "checkpoints": list(plan.checkpoints or []),
                "success_criteria": dict(task_spec.success_criteria or {}),
                "governance": template_governance,
                "governance_history": governance_history,
            },
            "activation_strategy": {
                "mode": "supervised_trial_first",
                "requires_confirmation": episode.requires_confirmation,
                "lineage": {
                    "source_task_spec_id": task_spec.id,
                    "last_materialized_episode_id": episode.id,
                    "last_materialized_plan_id": plan.id,
                },
                "governance": template_governance,
                "version_policy": {
                    "strategy": "supervised_semver",
                    "promotion_gate": "trial_confirmation" if episode.requires_confirmation else "trial_validated",
                    "history_depth": len(governance_history),
                },
            },
            "validation_summary": episode.result_summary or "Validated during supervised trial execution.",
            "last_validated_at": episode.finished_at or utcnow(),
        }
        if template is None:
            created = repo.create(payload)
            self._remember_episode_artifact(episode, "template_id", created.id)
            return created
        updated = repo.update(
            template,
            WorkflowTemplateUpdate(
                version=int(template.version) + 1,
                template_body=payload["template_body"],
                activation_strategy={
                    **dict(template.activation_strategy or {}),
                    **payload["activation_strategy"],
                    "governance": self._merge_dicts(
                        dict((template.activation_strategy or {}).get("governance") or {}),
                        template_governance,
                    ),
                    "version_policy": {
                        **dict((template.activation_strategy or {}).get("version_policy") or {}),
                        **payload["activation_strategy"]["version_policy"],
                    },
                },
                validation_summary=payload["validation_summary"],
                last_validated_at=payload["last_validated_at"],
            ),
        )
        self._remember_episode_artifact(episode, "template_id", updated.id)
        return updated

    def _materialize_patch(self, *, task_spec, plan, episode, template):
        if not episode.divergence_detected:
            return WorkflowPatchRepository(self.session).get(episode.patch_id) if episode.patch_id else None
        existing_patch = self._episode_patch(episode)
        if existing_patch is not None:
            return existing_patch

        latest_snapshot = EnvironmentSnapshotRepository(self.session).latest_for_episode(episode.id)
        snapshot_hint = latest_snapshot.page_type if latest_snapshot is not None else "runtime_state"
        patch = WorkflowPatchRepository(self.session).create(
            WorkflowPatchCreate(
                title=f"Patch {task_spec.title}",
                patch_kind="execution_divergence",
                template_id=template.id if template is not None else None,
                task_spec_id=task_spec.id,
                execution_plan_id=plan.id,
                execution_episode_id=episode.id,
                proposed_by="runtime",
                divergence_summary=f"Trial execution diverged while handling {snapshot_hint}.",
                rationale="The observed environment differed from the current execution plan.",
                patch_body={
                    "operations": [
                        {
                            "op": "review_checkpoint",
                            "target": snapshot_hint,
                            "summary": "Add or refine a supervised checkpoint before repeating this action.",
                        }
                    ]
                },
                runtime_metadata={
                    "generated_from_episode": episode.id,
                    "domain_pack_version": str((DOMAIN_PACKS.get(task_spec.domain, DOMAIN_PACKS["general"])).get("version") or "1.0.0"),
                    "plan_version": int(plan.version),
                    "episode_quality_band": self._learning_quality_band(episode),
                },
            )
        )
        self._ensure_patch_approval(patch)
        ExecutionEpisodeRepository(self.session).update(
            episode,
            {
                "patch_id": patch.id,
                "divergence_detected": True,
                "runtime_metadata": {
                    **dict(episode.runtime_metadata or {}),
                    "derived_patch_id": patch.id,
                },
            },
        )
        return patch

    def _materialize_learning(self, *, task_spec, plan, episode):
        existing_learning = self._episode_learning(episode)
        if existing_learning is not None:
            return existing_learning
        capability = self._primary_capability(plan)
        summary = episode.result_summary or f"Stable execution pattern detected for {task_spec.title}."
        content = (
            f"Task: {task_spec.title}\n"
            f"Domain: {task_spec.domain}\n"
            f"Episode: {episode.id}\n"
            f"Primary capability: {capability}\n"
            f"Summary: {summary}"
        )
        repo = AgentLearningRepository(self.session)
        learning = repo.create(
            {
                "content": content,
                "tags": [
                    task_spec.domain,
                    capability,
                    "trial" if episode.mode == "trial" else episode.mode,
                    f"episode:{episode.id}",
                    f"quality:{self._learning_quality_band(episode)}",
                    f"domain_version:{str((DOMAIN_PACKS.get(task_spec.domain, DOMAIN_PACKS['general'])).get('version') or '1.0.0')}",
                ],
                "source_task_id": task_spec.id,
                "consolidated_at": episode.finished_at or utcnow(),
                "is_active": not episode.divergence_detected,
            }
        )
        self._remember_episode_artifact(episode, "learning_id", learning.id)
        return learning

    def _materialize_skill_draft_approval(self, *, task_spec, plan, episode, learning):
        capability = self._primary_capability(plan)
        if capability in {"analyze", "llm", "document"}:
            return None

        approval_id = str((episode.runtime_metadata or {}).get("derived_skill_approval_id") or "").strip()
        if approval_id:
            approval = ApprovalRepository(self.session).get(approval_id)
            if approval is not None:
                return approval

        approval_repo = ApprovalRepository(self.session)
        existing_stmt = select(ApprovalItem).where(
            ApprovalItem.target_type == "skill_draft",
            ApprovalItem.target_id == learning.id,
        )
        existing = self.session.scalars(existing_stmt).first()
        if existing is not None:
            self._remember_episode_artifact(episode, "skill_approval_id", existing.id)
            return existing

        skill_name = f"{task_spec.domain.replace('_', ' ').title()} {capability.title()} Skill"
        version_governance = self._build_episode_governance_snapshot(
            task_spec=task_spec,
            plan=plan,
            episode=episode,
            domain_config=DOMAIN_PACKS.get(task_spec.domain, DOMAIN_PACKS["general"]),
            extra={
                "capability": capability,
                "learning_id": learning.id,
                "governance_event": "skill_draft",
            },
        )
        approval = approval_repo.create(
            {
                "target_type": "skill_draft",
                "target_id": learning.id,
                "title": f"Promote {skill_name}",
                "status": "pending",
                "requested_by": episode.requested_by or "runtime",
                "payload": {
                    "learning_id": learning.id,
                    "task_spec_id": task_spec.id,
                    "task_domain": task_spec.domain,
                    "execution_plan_id": plan.id,
                    "execution_episode_id": episode.id,
                    "workflow_node_id": self._first_actionable_step(plan),
                    "skill_draft": {
                        "kind": "skill_draft",
                        "skill_name": skill_name,
                        "skill_id": f"{task_spec.domain}_{capability}_{learning.id[:8]}",
                        "platform": task_spec.domain,
                        "summary": episode.result_summary,
                        "content": learning.content,
                        "strategy": {
                            "instruction": task_spec.goal,
                            "capability": capability,
                            "steps": list((plan.plan_body or {}).get("steps") or []),
                            "version_governance": version_governance,
                        },
                        "execution_hints": {
                            "domain": task_spec.domain,
                            "preferred_capabilities": list(task_spec.preferred_capabilities or []),
                            "version_governance": version_governance,
                        },
                        "health_check_config": {
                            "expected_result_status": "pass",
                            "minimum_overall_score": 0.5,
                            "failure_severity": "warning",
                            "governance_window": "supervised_trial",
                        },
                        "version_governance": version_governance,
                    },
                },
            }
        )
        self._remember_episode_artifact(episode, "skill_approval_id", approval.id)
        return approval

    def _evaluate_skill_health(self, *, plan, episode) -> dict[str, Any] | None:
        runtime_metadata = dict(plan.runtime_metadata or {})
        skill_id = runtime_metadata.get("skill_id")
        if not isinstance(skill_id, str) or not skill_id:
            return None
        skill = SkillRepository(self.session).by_skill_id(skill_id)
        if skill is None:
            return None

        episode_runtime_metadata = dict(episode.runtime_metadata or {})
        final_result_data = episode_runtime_metadata.get("final_result_data")
        observed_result = dict(final_result_data) if isinstance(final_result_data, dict) else {}
        final_result_status = episode_runtime_metadata.get("final_result_status")
        final_result_success = episode_runtime_metadata.get("final_result_success")
        business_status = extract_business_status(observed_result)
        normalized_business_status = business_status.lower() if isinstance(business_status, str) else None
        if business_status and normalized_business_status not in _GENERIC_EXECUTION_RESULT_STATUSES:
            observed_result["status"] = business_status
        elif isinstance(final_result_success, bool):
            observed_result["status"] = "pass" if final_result_success and not episode.divergence_detected else "fail"
        elif isinstance(final_result_status, str) and final_result_status.strip():
            observed_result["status"] = final_result_status.strip()
        elif "status" not in observed_result:
            observed_result["status"] = "pass" if not episode.divergence_detected else "fail"
        if "overall" not in observed_result and "score" not in observed_result:
            completion_rate = float((episode.metrics or {}).get("completion_rate") or 0.0)
            if isinstance(final_result_success, bool):
                observed_result["overall"] = 1.0 if final_result_success and not episode.divergence_detected else completion_rate
            else:
                observed_result["overall"] = completion_rate
        result = SkillHealthCheckService().run(skill, observed_result=observed_result)
        self.session.commit()
        self.session.refresh(skill)
        return {
            "skill_id": skill.skill_id,
            "status": skill.status,
            "health": result.health,
            "checked_at": result.checked_at.isoformat(),
            "issues": result.issues,
        }

    def _get_episode_template(self, *, plan, task_spec, patch):
        template_repo = WorkflowTemplateRepository(self.session)
        template_id = (plan.runtime_metadata or {}).get("workflow_template_id")
        if isinstance(template_id, str) and template_id:
            template = template_repo.get(template_id)
            if template is not None:
                return template
        if patch is not None and patch.template_id:
            template = template_repo.get(patch.template_id)
            if template is not None:
                return template
        stmt = (
            select(template_repo.model)
            .where(template_repo.model.source_task_spec_id == task_spec.id)
            .order_by(template_repo.model.updated_at.desc(), template_repo.model.id.desc())
        )
        return self.session.scalars(stmt).first()

    def _get_episode_patch(self, episode):
        if episode.patch_id:
            patch = WorkflowPatchRepository(self.session).get(episode.patch_id)
            if patch is not None:
                return patch
        stmt = (
            select(WorkflowPatch)
            .where(WorkflowPatch.execution_episode_id == episode.id)
            .order_by(WorkflowPatch.created_at.desc(), WorkflowPatch.id.desc())
        )
        return self.session.scalars(stmt).first()

    def _get_episode_learning(self, *, task_spec_id: str):
        stmt = (
            select(AgentLearningRepository.model)
            .where(AgentLearningRepository.model.source_task_id == task_spec_id)
            .order_by(AgentLearningRepository.model.created_at.desc(), AgentLearningRepository.model.id.desc())
        )
        return self.session.scalars(stmt).first()

    def _episode_template(self, episode):
        template_id = str((episode.runtime_metadata or {}).get("derived_template_id") or "").strip()
        if not template_id:
            return None
        return WorkflowTemplateRepository(self.session).get(template_id)

    def _episode_patch(self, episode):
        patch_id = str((episode.runtime_metadata or {}).get("derived_patch_id") or "").strip()
        if patch_id:
            patch = WorkflowPatchRepository(self.session).get(patch_id)
            if patch is not None:
                return patch
        return self._get_episode_patch(episode)

    def _episode_learning(self, episode):
        learning_id = str((episode.runtime_metadata or {}).get("derived_learning_id") or "").strip()
        if not learning_id:
            return None
        return AgentLearningRepository(self.session).get(learning_id)

    def _remember_episode_artifact(self, episode, artifact_key: str, artifact_id: str) -> None:
        normalized_key = artifact_key if artifact_key.startswith("derived_") else f"derived_{artifact_key}"
        runtime_metadata = dict(episode.runtime_metadata or {})
        if runtime_metadata.get(normalized_key) == artifact_id:
            return
        runtime_metadata[normalized_key] = artifact_id
        ExecutionEpisodeRepository(self.session).update(episode, {"runtime_metadata": runtime_metadata})

    def _get_episode_approvals(self, *, episode, patch, learning) -> list[ApprovalItem]:
        approvals: list[ApprovalItem] = []
        if patch is not None:
            patch_approval = self._get_patch_approval(patch.id)
            if patch_approval is not None:
                approvals.append(patch_approval)
        if learning is not None:
            stmt = (
                select(ApprovalItem)
                .where(
                    ApprovalItem.target_type == "skill_draft",
                    ApprovalItem.target_id == learning.id,
                )
                .order_by(ApprovalItem.created_at.asc(), ApprovalItem.id.asc())
            )
            approvals.extend(list(self.session.scalars(stmt).all()))
        template_approval = self._get_template_candidate_approval(episode.id)
        if template_approval is not None:
            approvals.append(template_approval)
        approvals.sort(key=lambda item: (item.created_at, item.id))
        return approvals

    def _merge_patch_checkpoints(
        self,
        current_checkpoints: list[dict[str, Any]],
        patch_body: dict[str, Any],
        *,
        fallback_label: str,
    ) -> list[dict[str, Any]]:
        patch_checkpoints = list(patch_body.get("checkpoints") or [])
        for operation in list(patch_body.get("operations") or []):
            if not isinstance(operation, dict):
                continue
            if str(operation.get("op") or "").strip() == "review_checkpoint":
                patch_checkpoints.append(
                    {
                        "kind": "approval",
                        "label": str(operation.get("summary") or fallback_label or "审查修订后的执行路径"),
                        "target": operation.get("target"),
                    }
                )
        return self._dedupe_dict_list([*current_checkpoints, *patch_checkpoints])

    def _merge_patch_steps(self, current_steps: list[dict[str, Any]], patch_body: dict[str, Any]) -> list[dict[str, Any]]:
        patch_steps = self._normalize_steps(list(patch_body.get("steps") or []))
        if patch_steps:
            return patch_steps

        operation_steps: list[dict[str, Any]] = []
        for index, operation in enumerate(list(patch_body.get("operations") or []), start=1):
            if not isinstance(operation, dict):
                continue
            if str(operation.get("op") or "").strip() == "review_checkpoint":
                operation_steps.append(
                    {
                        "id": f"patch_review_{index}",
                        "capability": "approval",
                        "summary": str(operation.get("summary") or "继续前先审查修订后的检查点。"),
                    }
                )
        return self._normalize_steps([*operation_steps, *current_steps])

    def _build_episode_timeline(
        self,
        *,
        task_spec,
        plan,
        episode,
        snapshots,
        template,
        patch,
        learning,
        approvals,
    ) -> list[RuntimeReplayEventRead]:
        timeline: list[RuntimeReplayEventRead] = []

        def add_event(
            kind: str,
            title: str,
            *,
            detail: str | None = None,
            occurred_at=None,
            payload: dict[str, Any] | None = None,
        ) -> None:
            timeline.append(
                RuntimeReplayEventRead(
                    sequence=len(timeline) + 1,
                    kind=kind,
                    title=title,
                    detail=detail,
                    occurred_at=occurred_at,
                    payload=dict(payload or {}),
                )
            )

        add_event(
            "task",
            task_spec.title,
            detail=task_spec.goal,
            occurred_at=task_spec.created_at,
            payload={"domain": task_spec.domain, "status": task_spec.status},
        )
        add_event(
            "plan",
            plan.name,
            detail=f"Mode={plan.mode}, status={plan.status}",
            occurred_at=plan.created_at,
            payload={"checkpoints": list(plan.checkpoints or []), "environment_requirements": dict(plan.environment_requirements or {})},
        )
        add_event(
            "episode",
            f"Episode {episode.id}",
            detail=f"Mode={episode.mode}, status={episode.status}",
            occurred_at=episode.created_at,
            payload={"requested_by": episode.requested_by, "requires_confirmation": episode.requires_confirmation},
        )

        action_time = episode.started_at or episode.updated_at or episode.created_at
        for index, action in enumerate(list(episode.actions or []), start=1):
            add_event(
                "action",
                str(action.get("step_id") or f"action_{index}"),
                detail=str(action.get("summary") or action.get("status") or "Action completed."),
                occurred_at=action_time,
                payload=dict(action),
            )
        for index, observation in enumerate(list(episode.observations or []), start=1):
            add_event(
                "observation",
                str(observation.get("step_id") or f"observation_{index}"),
                detail=str(observation.get("summary") or observation.get("evidence") or "Observation recorded."),
                occurred_at=action_time,
                payload=dict(observation),
            )
        for snapshot in snapshots:
            add_event(
                "snapshot",
                snapshot.title or snapshot.environment_key or snapshot.id,
                detail=snapshot.page_type or snapshot.status,
                occurred_at=snapshot.created_at,
                payload={
                    "source": snapshot.source,
                    "url": snapshot.url,
                    "page_type": snapshot.page_type,
                    "affordance_count": len(list(snapshot.affordances or [])),
                    "observed_entity_count": len(list(snapshot.observed_entities or [])),
                },
            )
        if template is not None:
            add_event(
                "template",
                template.name,
                detail=template.validation_summary,
                occurred_at=template.updated_at,
                payload={"status": template.status, "version": template.version, "template_key": template.template_key},
            )
        if patch is not None:
            add_event(
                "patch",
                patch.title,
                detail=patch.divergence_summary or patch.rationale,
                occurred_at=patch.updated_at,
                payload={"status": patch.status, "patch_kind": patch.patch_kind},
            )
        if learning is not None:
            add_event(
                "learning",
                "已生成学习草案",
                detail=learning.content.splitlines()[0] if learning.content else None,
                occurred_at=learning.created_at,
                payload={"learning_id": learning.id, "tags": list(learning.tags or []), "is_active": learning.is_active},
            )
        for approval in approvals:
            add_event(
                "approval",
                approval.title,
                detail=approval.status,
                occurred_at=approval.reviewed_at or approval.created_at,
                payload={"target_type": approval.target_type, "target_id": approval.target_id, "status": approval.status},
            )
        add_event(
            "episode_status",
            "实例回放已完成",
            detail=episode.result_summary,
            occurred_at=episode.finished_at or episode.updated_at,
            payload={"status": episode.status, "metrics": dict(episode.metrics or {}), "last_error": episode.last_error},
        )
        return timeline

    def _safe_float(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _learning_quality_band(self, episode) -> str:
        completion_rate = self._safe_float((episode.metrics or {}).get("completion_rate"))
        if completion_rate is None:
            completion_rate = 0.0
        if bool(episode.divergence_detected):
            return "low"
        if completion_rate >= 0.95:
            return "high"
        if completion_rate >= 0.7:
            return "medium"
        return "low"

    def _build_episode_governance_snapshot(
        self,
        *,
        task_spec,
        plan,
        episode,
        domain_config: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_domain = domain_config or DOMAIN_PACKS.get(task_spec.domain, DOMAIN_PACKS["general"])
        snapshot = {
            "domain_pack_version": str(resolved_domain.get("version") or "1.0.0"),
            "domain_pack_maturity": str(resolved_domain.get("maturity") or "experimental"),
            "quality_gates": dict(resolved_domain.get("quality_gates") or {}),
            "trial_expectations": dict(resolved_domain.get("trial_expectations") or {}),
            "episode_quality_band": self._learning_quality_band(episode),
            "last_episode_id": getattr(episode, "id", None),
            "last_plan_id": getattr(plan, "id", None),
            "last_plan_version": int(getattr(plan, "version", 1) or 1),
        }
        if extra:
            snapshot.update(dict(extra))
        return snapshot

    def _append_governance_history(
        self,
        existing_history: list[dict[str, Any]],
        snapshot: dict[str, Any],
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        normalized = [dict(item) for item in existing_history if isinstance(item, dict)]
        normalized.append({"recorded_at": utcnow().isoformat(), **dict(snapshot)})
        return normalized[-limit:]

    def _domain_pack_read(self, key: str, config: dict[str, Any]) -> DomainPackRead:
        template_repo = WorkflowTemplateRepository(self.session)
        templates = [item for item in template_repo.list(limit=500, offset=0) if item.domain == key]
        return DomainPackRead(
            key=key,
            name=str(config["name"]),
            description=str(config["description"]),
            version=str(config.get("version") or "1.0.0"),
            maturity=str(config.get("maturity") or "experimental"),
            runtime_only=bool(config.get("runtime_only", True)),
            default_capabilities=list(config.get("default_capabilities") or []),
            sample_tasks=list(config.get("sample_tasks") or []),
            default_constraints=dict(config.get("default_constraints") or {}),
            default_output_contract=dict(config.get("default_output_contract") or {}),
            template_keys=list(config.get("template_keys") or []),
            compiler_hints=list(config.get("compiler_hints") or []),
            quality_gates=dict(config.get("quality_gates") or {}),
            scene_expectations=list(config.get("scene_expectations") or []),
            trial_expectations=dict(config.get("trial_expectations") or {}),
            template_count=len(templates),
            active_template_count=sum(1 for item in templates if str(item.status) == "active"),
        )

    def _normalize_domain(self, value: str | None) -> str:
        if not value:
            return ""
        normalized = value.strip().lower().replace(" ", "_")
        aliases = {
            "research": "archived_public_research",
            "github": "archived_repository_watch",
            "market": "archived_public_briefing",
            "recruit": "recruiting",
        }
        return aliases.get(normalized, normalized)

    def _merge_dicts(self, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return slug or "runtime_task"

    def _template_key(self, task_spec) -> str:
        candidate = (task_spec.compiled_payload or {}).get("task_key") or task_spec.title
        return f"{task_spec.domain}_{self._slugify(str(candidate))}"

    def _primary_capability(self, plan) -> str:
        steps = list((plan.plan_body or {}).get("steps") or [])
        for step in steps:
            capability = str(step.get("capability") or "")
            if capability and capability not in {"analyze", "llm", "document"}:
                return capability
        return str((steps[0].get("capability") if steps else "llm") or "llm")

    def _first_actionable_step(self, plan) -> str | None:
        steps = list((plan.plan_body or {}).get("steps") or [])
        for step in steps:
            capability = str(step.get("capability") or "")
            if capability not in {"analyze", "llm", "document"}:
                return str(step.get("id") or capability)
        return str(steps[0].get("id")) if steps else None

    def _step_summary(self, domain: str, capability: str) -> str:
        match (domain, capability):
            case ("recruiting", "browser"):
                return "观察招聘工作区和候选人详情页。"
            case ("recruiting", "search"):
                return "搜索匹配的候选人档案。"
            case ("recruiting", "api"):
                return "准备经过批准的交接或同步载荷。"
            case ("archived_public_briefing", "search"):
                return "在可信来源中搜索最新市场头条。"
            case ("archived_public_briefing", "browser"):
                return "打开最相关的文章并观察上下文。"
            case ("archived_public_research", "search"):
                return "在全网搜索候选工具和参考资料。"
            case ("archived_repository_watch", "http"):
                return "抓取或检查热门仓库元数据。"
            case (_, "browser"):
                return "观察当前浏览器环境。"
            case (_, "search"):
                return "发现相关来源或目标。"
            case (_, "http"):
                return "请求外部 API 或结构化接口。"
            case (_, "api"):
                return "向已配置的下游系统发送结构化数据。"
            case (_, "document"):
                return "写出最终摘要或结构化产物。"
            case _:
                return "推理下一步自动化动作。"

    def _observation_summary(self, domain: str, capability: str) -> str:
        if domain == "recruiting" and capability == "document":
            return "已捕获候选人上下文和简历证据。"
        if domain == "archived_public_briefing" and capability == "browser":
            return "已确认来源文章页面包含可发布内容。"
        if domain == "archived_repository_watch" and capability == "browser":
            return "已核对仓库元数据和 README 上下文。"
        return self._step_summary(domain, capability)

    def _result_summary(self, domain: str, notes: str | None) -> str:
        base = {
            "recruiting": "试跑已捕获候选人证据，并生成受监督的初筛摘要。",
            "archived_public_briefing": "归档试跑已收集公开资讯，并整理出摘要草稿。",
            "archived_public_research": "归档试跑已完成公开网页探索，并生成对比摘要。",
            "archived_repository_watch": "归档试跑已收集公开仓库线索，并整理出观察摘要。",
            "general": "试跑已完成，并记录了观察到的执行模式。",
        }.get(domain, "试跑已完成，并记录了观察到的执行模式。")
        if notes:
            return f"{base} 备注：{notes}"
        return base

    def _derive_snapshot_title(self, task_spec, plan, url: str | None) -> str:
        if url:
            parsed = urlparse(url)
            if parsed.netloc:
                return f"{task_spec.title} @ {parsed.netloc}"
        return f"{plan.name} snapshot"

    def _derive_page_type(self, domain: str, url: str | None) -> str:
        if domain == "recruiting":
            return "candidate_workspace"
        if domain == "archived_public_briefing":
            return "news_page"
        if domain == "archived_repository_watch":
            return "repository_listing"
        if url:
            return "web_page"
        return "runtime_state"

    def _default_affordances(self, domain: str) -> list[dict[str, Any]]:
        if domain == "recruiting":
            return [
                {"kind": "open_profile", "label": "打开候选人档案"},
                {"kind": "capture_resume", "label": "捕获简历详情"},
            ]
        if domain == "archived_public_briefing":
            return [{"kind": "open_article", "label": "打开最新文章"}]
        if domain == "archived_repository_watch":
            return [{"kind": "open_repository", "label": "打开仓库页面"}]
        return [{"kind": "review_output", "label": "审查生成结果"}]
