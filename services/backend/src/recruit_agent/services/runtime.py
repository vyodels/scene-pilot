from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from pydantic import AliasChoices, BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from recruit_agent.db.base import utcnow
from recruit_agent.models import ApprovalItem, Skill, WorkflowPatch
from recruit_agent.repositories import (
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
from recruit_agent.schemas import (
    ApprovalRead,
    DomainPackRead,
    EpisodeConfirmRequest,
    EnvironmentSnapshotCreate,
    EnvironmentSnapshotRead,
    ExecutionEpisodeCreate,
    ExecutionEpisodeRead,
    ExecutionEpisodeUpdate,
    ExecutionPlanRead,
    LearningDraftRead,
    RuntimeEpisodeReplayRead,
    RuntimeReplayDiagnosticsRead,
    RuntimeReplayEventRead,
    RuntimeLearningOutcomeRead,
    TaskCompileRequest,
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
from recruit_agent.runtime.models import Message
from recruit_agent.runtime.providers import ProviderError, ProviderRegistry, ScriptedProvider
from recruit_agent.runtime.prompts import PromptBuilder
from recruit_agent.services.skills import SkillHealthCheckService


DOMAIN_PACKS: dict[str, dict[str, Any]] = {
    "general": {
        "name": "General Automation",
        "description": "A generic supervised automation pack for exploratory browser or desktop tasks.",
        "default_capabilities": ["analyze", "browser", "llm", "document"],
        "sample_tasks": [
            "Open a site, inspect the page, and summarize the useful information.",
            "Try a new workflow once under supervision and propose follow-up fixes.",
        ],
        "default_constraints": {"requires_human_supervision": True},
        "default_output_contract": {"kind": "summary", "format": "markdown"},
        "template_keys": ["general_supervised_trial", "patch_review_loop"],
    },
    "recruiting": {
        "name": "Recruiting",
        "description": "Source candidates, capture profile context, screen resumes, and prepare approved handoffs.",
        "default_capabilities": ["browser", "search", "document", "llm", "api"],
        "sample_tasks": [
            "Find matching candidates, extract resumes, and score them before upload.",
            "Review candidate profiles, capture evidence, and prepare recruiter notes.",
        ],
        "default_constraints": {"requires_human_supervision": True, "respect_messaging_approval": True},
        "default_output_contract": {"kind": "candidate_bundle", "fields": ["resume", "score", "notes"]},
        "template_keys": ["recruiting_trial_screening"],
    },
    "market_news": {
        "name": "Market News",
        "description": "Collect the newest market news, compare sources, and generate a concise daily digest.",
        "default_capabilities": ["search", "http", "browser", "llm", "document"],
        "sample_tasks": [
            "Find the latest stock market news and prepare a digest with sources.",
            "Summarize the biggest market-moving headlines and why they matter.",
        ],
        "default_constraints": {"requires_source_links": True},
        "default_output_contract": {"kind": "news_digest", "format": "bullet_summary"},
        "template_keys": ["market_news_digest"],
    },
    "web_research": {
        "name": "Web Research",
        "description": "Search the web, evaluate options, and produce shortlists with reasons and links.",
        "default_capabilities": ["search", "browser", "http", "llm", "document"],
        "sample_tasks": [
            "Find useful PDF converters, compare them, and return the shortlist.",
            "Research tools across the web and explain why they are worth trying.",
        ],
        "default_constraints": {"requires_source_links": True},
        "default_output_contract": {"kind": "research_shortlist", "format": "table"},
        "template_keys": ["web_research_shortlist"],
    },
    "github_trends": {
        "name": "GitHub Trends",
        "description": "Inspect GitHub activity, identify trending repositories, and summarize why they matter.",
        "default_capabilities": ["http", "search", "browser", "llm", "document"],
        "sample_tasks": [
            "List today's hot GitHub repositories with links and one-line summaries.",
            "Watch trending open-source projects and prepare a lightweight briefing.",
        ],
        "default_constraints": {"requires_source_links": True},
        "default_output_contract": {"kind": "repository_digest", "format": "table"},
        "template_keys": ["github_trends_digest"],
    },
}


CAPABILITY_DRIVERS: dict[str, dict[str, Any]] = {
    "analyze": {
        "description": "Reason about a task, compare evidence, or decide the next step without changing the environment.",
        "risk": "low",
    },
    "browser": {
        "description": "Observe or interact with websites and web apps as runtime scenes.",
        "risk": "medium",
    },
    "search": {
        "description": "Discover relevant targets, sources, candidates, or options across search surfaces.",
        "risk": "low",
    },
    "http": {
        "description": "Call structured HTTP or API endpoints to read or write machine-facing data.",
        "risk": "medium",
    },
    "document": {
        "description": "Draft, summarize, or format durable output artifacts.",
        "risk": "low",
    },
    "api": {
        "description": "Write structured data into a downstream system or service.",
        "risk": "high",
    },
    "command": {
        "description": "Run local system commands under approval and policy controls.",
        "risk": "high",
    },
    "llm": {
        "description": "Delegate reasoning, synthesis, or classification to the language model runtime.",
        "risk": "low",
    },
    "approval": {
        "description": "Pause for a human review or approval checkpoint.",
        "risk": "low",
    },
}


DEFAULT_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_key": "general_supervised_trial",
        "name": "General Supervised Trial",
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
        "validation_summary": "Seeded baseline supervised runtime workflow.",
    },
    {
        "template_key": "patch_review_loop",
        "name": "Patch Review Loop",
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
        "validation_summary": "Seeded workflow patch review template.",
    },
    {
        "template_key": "recruiting_trial_screening",
        "name": "Recruiting Trial Screening",
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
        "validation_summary": "Seeded recruiting workflow for supervised screening runs.",
    },
    {
        "template_key": "market_news_digest",
        "name": "Market News Digest",
        "domain": "market_news",
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
        "validation_summary": "Seeded template for supervised market-news digests.",
    },
    {
        "template_key": "web_research_shortlist",
        "name": "Web Research Shortlist",
        "domain": "web_research",
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
        "validation_summary": "Seeded template for web tool research and shortlisting.",
    },
    {
        "template_key": "github_trends_digest",
        "name": "GitHub Trends Digest",
        "domain": "github_trends",
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
        "validation_summary": "Seeded template for GitHub trends monitoring.",
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
class PersistedRuntimeService:
    session: Session
    providers: ProviderRegistry | None = None
    prompt_builder: PromptBuilder = field(default_factory=PromptBuilder)

    def list_domain_packs(self) -> list[DomainPackRead]:
        return [self._domain_pack_read(key, config) for key, config in DOMAIN_PACKS.items()]

    def compile_task(self, payload: TaskCompileRequest) -> TaskCompileResponse:
        compiled = self._compile_task_spec(payload)
        domain_config = DOMAIN_PACKS[compiled.domain_key]
        task = self.create_task_spec(compiled.task_spec)

        plan = None
        if payload.auto_plan:
            plan = self.compile_plan(
                CompilePlanRequest(
                    task_spec_id=task.id,
                    name=f"{task.title} Trial Plan",
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
        llm_draft = self._compile_task_spec_with_llm(payload)
        if llm_draft is not None:
            return llm_draft
        return self._compile_task_spec_heuristic(payload)

    def _compile_task_spec_with_llm(self, payload: TaskCompileRequest) -> CompiledTaskDraft | None:
        if self.providers is None:
            return None

        errors: list[str] = []
        for provider_name in self._semantic_compiler_provider_names():
            provider = self.providers.providers.get(provider_name)
            if provider is None:
                continue
            response = None
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
                compiler_notes = list(draft.compiler_notes or [])
                compiler_notes.append(f"Semantic task compiler succeeded via provider: {provider_name}.")
                return self._materialize_compiled_task_draft(
                    payload=payload,
                    draft=draft,
                    compiler_name="llm_structured",
                    compiler_notes=compiler_notes,
                    provider_name=provider_name,
                )
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                if response is None:
                    errors.append(f"LLM semantic compiler via {provider_name} failed: {exc}.")
                    continue
                try:
                    repaired_response = provider.generate(
                        self._build_semantic_compile_repair_messages(payload, response, str(exc)),
                        task={
                            "task_type": "semantic_task_compile_repair",
                            "instruction": payload.instruction,
                            "output_schema": "SemanticTaskCompileDraft",
                        },
                        max_tokens=1_400,
                        temperature=0.0,
                    )
                    draft = self._parse_semantic_compile_response(repaired_response)
                    compiler_notes = list(draft.compiler_notes or [])
                    compiler_notes.append(
                        f"Semantic task compiler succeeded via provider: {provider_name} after one repair pass."
                    )
                    return self._materialize_compiled_task_draft(
                        payload=payload,
                        draft=draft,
                        compiler_name="llm_structured",
                        compiler_notes=compiler_notes,
                        provider_name=provider_name,
                    )
                except (ProviderError, ValidationError, ValueError, json.JSONDecodeError) as repair_exc:
                    errors.append(
                        f"LLM semantic compiler via {provider_name} failed initial validation ({exc}) "
                        f"and repair ({repair_exc})."
                    )
            except ProviderError as exc:
                errors.append(f"LLM semantic compiler via {provider_name} failed: {exc}.")

        if not errors:
            return None
        return self._compile_task_spec_heuristic(payload, notes=errors)

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
        compiler_notes.append("Fell back to heuristic task compiler.")
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
            }
            for key, value in DOMAIN_PACKS.items()
        }
        capability_catalog = {
            key: {
                "description": value["description"],
                "risk": value["risk"],
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
            return SemanticTaskCompileDraft.model_validate(response.result_data)

        content = (response.content or "").strip()
        if not content:
            raise ValueError("Compiler returned an empty response")
        return SemanticTaskCompileDraft.model_validate(self._extract_json_object(content))

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
            notes.append(f"Selected domain pack from semantic compiler output: {normalized}.")
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

    def list_plans(self, *, task_spec_id: str | None = None, limit: int = 100, offset: int = 0) -> list[ExecutionPlanRead]:
        repo = ExecutionPlanRepository(self.session)
        items = repo.by_task_spec(task_spec_id, limit=limit, offset=offset) if task_spec_id else repo.list(limit=limit, offset=offset)
        return [ExecutionPlanRead.model_validate(item) for item in items]

    def compile_plan(self, payload: CompilePlanRequest) -> ExecutionPlanRead:
        task_spec = TaskSpecRepository(self.session).get(payload.task_spec_id)
        if task_spec is None:
            raise ValueError("Task spec not found")

        template = None
        if payload.workflow_template_id is not None:
            template = WorkflowTemplateRepository(self.session).get(payload.workflow_template_id)
            if template is None:
                raise ValueError("Workflow template not found")

        steps = list(payload.steps) or self._default_steps(task_spec, template)
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
        template = self._get_episode_template(plan=plan, task_spec=task_spec, patch=patch)
        learning = self._get_episode_learning(task_spec_id=task_spec.id)
        approvals = self._get_episode_approvals(patch=patch, learning=learning)

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
            approval=ApprovalRead.model_validate(approval) if approval is not None else None,
            skill_health=skill_health,
        )

    def confirm_episode(self, episode_id: str, payload: EpisodeConfirmRequest) -> RuntimeLearningOutcomeRead:
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
        if outcome.template is not None:
            template_repo = WorkflowTemplateRepository(self.session)
            template_model = template_repo.get(outcome.template.id)
            if template_model is not None:
                template = template_repo.update(
                    template_model,
                    WorkflowTemplateUpdate(
                        name=payload.template_name or template_model.name,
                        status="active" if payload.activate_template else template_model.status,
                        validation_summary=payload.reason or template_model.validation_summary or "Confirmed from supervised trial run.",
                        last_validated_at=utcnow(),
                    ),
                )

        plan_repo.update(
            plan,
            {
                "status": "active" if payload.activate_template else "validated",
                "approval_state": "approved",
                "runtime_metadata": {
                    **dict(plan.runtime_metadata or {}),
                    "confirmed_by": payload.reviewer,
                    "confirmed_reason": payload.reason,
                },
            },
        )
        task_repo.update(
            task,
            {
                "status": "production_ready" if payload.activate_template else "validated",
                "active_plan_id": plan.id,
            },
        )
        episode = episode_repo.update(
            episode,
            ExecutionEpisodeUpdate(
                status="confirmed",
                requires_confirmation=False,
                runtime_metadata={
                    **dict(episode.runtime_metadata or {}),
                    "confirmed_by": payload.reviewer,
                    "confirmed_reason": payload.reason,
                },
            ),
        )

        return RuntimeLearningOutcomeRead(
            episode=ExecutionEpisodeRead.model_validate(episode),
            template=WorkflowTemplateRead.model_validate(template) if template is not None else outcome.template,
            patch=outcome.patch,
            learning_draft=outcome.learning_draft,
            approval=outcome.approval,
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

        status = "applied" if approve and payload.apply_immediately else "approved" if approve else "rejected"
        updated = repo.mark_review(
            item,
            status=status,
            reviewer=payload.reviewer,
            rationale=payload.reason,
            applied_at=utcnow() if approve and payload.apply_immediately else None,
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

    def _seed_template(self, repo: WorkflowTemplateRepository, payload: dict[str, Any]):
        existing = repo.by_template_key(payload["template_key"])
        if existing is not None:
            return existing
        return repo.create(payload)

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
        for index, capability in enumerate(capabilities, start=1):
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
        checkpoints = [{"kind": "approval", "label": "Review trial output"}]
        checkpoints.extend(list((task_spec.compiled_payload or {}).get("checkpoints") or []))
        if template is not None:
            checkpoints.append({"kind": "template", "label": template.template_key})
        if task_spec.approval_policy:
            checkpoints.append({"kind": "policy", "label": "Respect task approval policy"})
        if "browser" in (task_spec.preferred_capabilities or []):
            checkpoints.append({"kind": "snapshot", "label": "Capture environment snapshot"})
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
        hints = {"requires_browser": "browser" in capabilities, "requires_network": any(cap in capabilities for cap in ("http", "search", "browser"))}
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
                notes.append(f"Selected domain pack from explicit hint: {normalized}.")
                return normalized, DOMAIN_PACKS[normalized], notes

        normalized_instruction = instruction.lower()
        keyword_map = {
            "recruiting": ("candidate", "resume", "jd", "boss", "hiring", "recruit"),
            "market_news": ("stock", "market", "equity", "news", "macro", "earnings"),
            "github_trends": ("github", "repository", "repo", "open source", "trending"),
            "web_research": ("search", "find", "tool", "pdf", "compare", "website"),
        }
        for domain_key, keywords in keyword_map.items():
            if any(keyword in normalized_instruction for keyword in keywords):
                notes.append(f"Inferred domain pack {domain_key} from keyword match.")
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
        if domain_key == "market_news":
            return {"minimum_sources": 3, "include_market_impact": True}
        if domain_key == "github_trends":
            return {"minimum_repositories": 5, "include_repo_links": True}
        if domain_key == "web_research":
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
        if episode.divergence_detected:
            return None
        repo = WorkflowTemplateRepository(self.session)
        template_key = self._template_key(task_spec)
        template = repo.by_template_key(template_key)
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
            },
            "activation_strategy": {
                "mode": "supervised_trial_first",
                "requires_confirmation": episode.requires_confirmation,
            },
            "validation_summary": episode.result_summary or "Validated during supervised trial execution.",
            "last_validated_at": episode.finished_at or utcnow(),
        }
        if template is None:
            return repo.create(payload)
        return repo.update(
            template,
            WorkflowTemplateUpdate(
                version=int(template.version) + 1,
                template_body=payload["template_body"],
                activation_strategy=payload["activation_strategy"],
                validation_summary=payload["validation_summary"],
                last_validated_at=payload["last_validated_at"],
            ),
        )

    def _materialize_patch(self, *, task_spec, plan, episode, template):
        if not episode.divergence_detected:
            return WorkflowPatchRepository(self.session).get(episode.patch_id) if episode.patch_id else None
        if episode.patch_id:
            return WorkflowPatchRepository(self.session).get(episode.patch_id)

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
                runtime_metadata={"generated_from_episode": episode.id},
            )
        )
        self._ensure_patch_approval(patch)
        ExecutionEpisodeRepository(self.session).update(episode, {"patch_id": patch.id, "divergence_detected": True})
        return patch

    def _materialize_learning(self, *, task_spec, plan, episode):
        capability = self._primary_capability(plan)
        summary = episode.result_summary or f"Stable execution pattern detected for {task_spec.title}."
        content = (
            f"Task: {task_spec.title}\n"
            f"Domain: {task_spec.domain}\n"
            f"Primary capability: {capability}\n"
            f"Summary: {summary}"
        )
        repo = AgentLearningRepository(self.session)
        return repo.create(
            {
                "content": content,
                "tags": [task_spec.domain, capability, "trial" if episode.mode == "trial" else episode.mode],
                "source_task_id": task_spec.id,
                "consolidated_at": episode.finished_at or utcnow(),
                "is_active": not episode.divergence_detected,
            }
        )

    def _materialize_skill_draft_approval(self, *, task_spec, plan, episode, learning):
        capability = self._primary_capability(plan)
        if capability in {"analyze", "llm", "document"}:
            return None

        approval_repo = ApprovalRepository(self.session)
        existing_stmt = select(ApprovalItem).where(
            ApprovalItem.target_type == "skill_draft",
            ApprovalItem.target_id == learning.id,
        )
        existing = self.session.scalars(existing_stmt).first()
        if existing is not None:
            return existing

        skill_name = f"{task_spec.domain.replace('_', ' ').title()} {capability.title()} Skill"
        return approval_repo.create(
            {
                "target_type": "skill_draft",
                "target_id": learning.id,
                "title": f"Promote {skill_name}",
                "status": "pending",
                "requested_by": episode.requested_by or "runtime",
                "payload": {
                    "learning_id": learning.id,
                    "task_spec_id": task_spec.id,
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
                        },
                        "execution_hints": {
                            "domain": task_spec.domain,
                            "preferred_capabilities": list(task_spec.preferred_capabilities or []),
                        },
                        "health_check_config": {
                            "expected_result_status": "pass",
                            "minimum_overall_score": 0.5,
                            "failure_severity": "warning",
                        },
                    },
                },
            }
        )

    def _evaluate_skill_health(self, *, plan, episode) -> dict[str, Any] | None:
        runtime_metadata = dict(plan.runtime_metadata or {})
        skill_id = runtime_metadata.get("skill_id")
        if not isinstance(skill_id, str) or not skill_id:
            return None
        skill = SkillRepository(self.session).by_skill_id(skill_id)
        if skill is None:
            return None

        observed_result = {
            "status": "pass" if not episode.divergence_detected else "fail",
            "overall": float((episode.metrics or {}).get("completion_rate") or 0.0),
        }
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

    def _get_episode_approvals(self, *, patch, learning) -> list[ApprovalItem]:
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
        approvals.sort(key=lambda item: (item.created_at, item.id))
        return approvals

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
                "Learning draft generated",
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
            "Episode replay complete",
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

    def _domain_pack_read(self, key: str, config: dict[str, Any]) -> DomainPackRead:
        return DomainPackRead(
            key=key,
            name=str(config["name"]),
            description=str(config["description"]),
            default_capabilities=list(config.get("default_capabilities") or []),
            sample_tasks=list(config.get("sample_tasks") or []),
            default_constraints=dict(config.get("default_constraints") or {}),
            default_output_contract=dict(config.get("default_output_contract") or {}),
            template_keys=list(config.get("template_keys") or []),
        )

    def _normalize_domain(self, value: str | None) -> str:
        if not value:
            return ""
        normalized = value.strip().lower().replace(" ", "_")
        aliases = {
            "research": "web_research",
            "github": "github_trends",
            "market": "market_news",
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
                return "Inspect the recruiting workspace and candidate detail page."
            case ("recruiting", "search"):
                return "Search for matching candidate profiles."
            case ("recruiting", "api"):
                return "Prepare the approved handoff or intranet sync payload."
            case ("market_news", "search"):
                return "Search recent market headlines across trusted sources."
            case ("market_news", "browser"):
                return "Open the most relevant articles to inspect context."
            case ("web_research", "search"):
                return "Search the web for candidate tools and references."
            case ("github_trends", "http"):
                return "Fetch or inspect trending repository metadata."
            case (_, "browser"):
                return "Inspect the active browser environment."
            case (_, "search"):
                return "Discover relevant sources or targets."
            case (_, "http"):
                return "Query an external API or structured endpoint."
            case (_, "api"):
                return "Send structured data to a configured downstream system."
            case (_, "document"):
                return "Write the final summary or structured artifact."
            case _:
                return "Reason about the next automation step."

    def _observation_summary(self, domain: str, capability: str) -> str:
        if domain == "recruiting" and capability == "document":
            return "Captured candidate context and resume evidence."
        if domain == "market_news" and capability == "browser":
            return "Validated that the source article page contains publishable content."
        if domain == "github_trends" and capability == "browser":
            return "Verified repository metadata and README context."
        return self._step_summary(domain, capability)

    def _result_summary(self, domain: str, notes: str | None) -> str:
        base = {
            "recruiting": "Trial run captured candidate evidence and produced a supervised screening summary.",
            "market_news": "Trial run collected recent market headlines and assembled a draft digest.",
            "web_research": "Trial run explored the web and produced a shortlist-oriented summary.",
            "github_trends": "Trial run gathered trending repositories and prepared a digest.",
            "general": "Trial run completed and recorded the observed execution pattern.",
        }.get(domain, "Trial run completed and recorded the observed execution pattern.")
        if notes:
            return f"{base} Notes: {notes}"
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
        if domain == "market_news":
            return "news_page"
        if domain == "github_trends":
            return "repository_listing"
        if url:
            return "web_page"
        return "runtime_state"

    def _default_affordances(self, domain: str) -> list[dict[str, Any]]:
        if domain == "recruiting":
            return [
                {"kind": "open_profile", "label": "Open candidate profile"},
                {"kind": "capture_resume", "label": "Capture resume details"},
            ]
        if domain == "market_news":
            return [{"kind": "open_article", "label": "Open latest article"}]
        if domain == "github_trends":
            return [{"kind": "open_repository", "label": "Open repository page"}]
        return [{"kind": "review_output", "label": "Review generated output"}]
