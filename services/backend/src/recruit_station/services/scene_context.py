from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session, sessionmaker

from recruit_station.agent_runtime.engine import InteractionEngine, InteractionEngineConfig
from recruit_station.agent_runtime.types import InteractionOutput
from recruit_station.db.base import utcnow
from recruit_station.models.domain import AgentGlobalState
from recruit_station.plugins.host import PluginHost
from recruit_station.repositories.domain import (
    EnvironmentSnapshotRepository,
    ExecutionEpisodeRepository,
    ExecutionPlanRepository,
    TaskSpecRepository,
)
from recruit_station.product_adapters.limits import SceneExecutionLimits
from recruit_station.product_adapters.context_builder import build_scene_turn_context
from recruit_station.agents.outcome import AgentTurnOutcome
from recruit_station.agent_runtime.providers import LLMProvider
from recruit_station.product_adapters.result_semantics import (
    normalize_result_payload,
)
from recruit_station.product_adapters.target_contracts import derive_browser_target
from recruit_station.capabilities.tools import ToolDefinition, ToolRegistry, is_scene_context_tool


_SCENE_BROWSER_READ_ONLY_TOOL_NAMES = {
    "browser_list_tabs",
    "browser_get_active_tab",
    "browser_snapshot",
    "browser_query_elements",
    "browser_get_element",
    "browser_debug_dom",
    "browser_wait_for_element",
    "browser_wait_for_text",
    "browser_wait_for_navigation",
    "browser_wait_for_disappear",
    "browser_wait_for_url",
}
_SCENE_BROWSER_TARGET_IDENTIFICATION_TOOL_NAMES = {
    "browser_list_tabs",
    "browser_get_active_tab",
}
_SCENE_BROWSER_PAGE_OBSERVATION_TOOL_NAMES = _SCENE_BROWSER_READ_ONLY_TOOL_NAMES - _SCENE_BROWSER_TARGET_IDENTIFICATION_TOOL_NAMES
_SCENE_HID_BROWSER_SEQUENCE_PRIMITIVE_TYPES = {"click", "drag", "scroll", "type", "pasteText", "key"}


@dataclass(slots=True)
class SceneContextService:
    session_factory: sessionmaker[Session]
    provider: LLMProvider
    tool_registry: ToolRegistry
    plugin_host: PluginHost
    limits: SceneExecutionLimits = field(default_factory=SceneExecutionLimits)
    default_max_llm_invocations: int | None = None
    anti_detection_policy: dict[str, Any] = field(default_factory=dict)
    behavior_budget: dict[str, Any] = field(default_factory=dict)

    def delegate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = _normalize_scene_request(
            arguments,
            default_max_llm_invocations=self.default_max_llm_invocations,
            default_anti_detection_policy=self.anti_detection_policy,
            default_behavior_budget=self.behavior_budget,
        )
        with self.session_factory() as session:
            task_repo = TaskSpecRepository(session)
            plan_repo = ExecutionPlanRepository(session)
            episode_repo = ExecutionEpisodeRepository(session)
            snapshot_repo = EnvironmentSnapshotRepository(session)

            task_spec = task_repo.create(
                {
                    "title": request["title"],
                    "description": request["description"],
                    "instruction": _build_scene_instruction(request),
                    "domain": "scene",
                    "status": "running",
                    "source_kind": "scene_context",
                    "source_text": request["instruction"],
                    "inputs": {
                        "input": dict(request["input"]),
                        "context": dict(request["context"]),
                    },
                    "constraints": {
                        "persist_memory": False,
                        "scene_context": True,
                        "environment_requirements": dict(request["environment_requirements"]),
                        "approval_policy": dict(request["approval_policy"]),
                        "output_contract": dict(request["output_contract"]),
                        "anti_detection_policy": dict(request["anti_detection_policy"]),
                        "behavior_budget": dict(request["behavior_budget"]),
                    },
                    "success_criteria": dict(request["success_criteria"]),
                    "approval_policy": dict(request["approval_policy"]),
                    "output_contract": dict(request["output_contract"]),
                    "preferred_capabilities": list(request["preferred_capabilities"]),
                    "preferred_domains": ["scene"],
                    "compiled_payload": {
                        "instruction": request["instruction"],
                        "max_llm_invocations": request["max_llm_invocations"],
                    },
                }
            )
            plan = plan_repo.create(
                {
                    "task_spec_id": task_spec.id,
                    "name": request["title"],
                    "mode": "trial",
                    "status": "running",
                    "approval_state": "approved",
                    "plan_body": {
                        "instruction": request["instruction"],
                        "success_criteria": dict(request["success_criteria"]),
                        "output_contract": dict(request["output_contract"]),
                    },
                    "environment_requirements": dict(request["environment_requirements"]),
                    "checkpoints": _build_checkpoints(request),
                    "runtime_metadata": {
                        "scene_context": True,
                        "approval_policy": dict(request["approval_policy"]),
                        "anti_detection_policy": dict(request["anti_detection_policy"]),
                        "behavior_budget": dict(request["behavior_budget"]),
                    },
                }
            )
            task_spec.active_plan_id = plan.id
            session.commit()
            session.refresh(task_spec)

            episode = episode_repo.create(
                {
                    "task_spec_id": task_spec.id,
                    "execution_plan_id": plan.id,
                    "mode": "trial",
                    "status": "running",
                    "requested_by": str(request["requested_by"] or ""),
                    "requires_confirmation": bool(request["approval_policy"].get("requires_confirmation")),
                    "started_at": utcnow(),
                    "runtime_metadata": {
                        "scene_context": True,
                        "instruction": request["instruction"],
                        "preferred_capabilities": list(request["preferred_capabilities"]),
                        "execution_contract": _scene_execution_contract(request),
                        "environment_context": _scene_environment_context(request, episode_id=None),
                        "anti_detection_policy": dict(request["anti_detection_policy"]),
                        "behavior_budget": dict(request["behavior_budget"]),
                    },
                }
            )

            snapshot_ids: list[str] = []
            initial_environment_context = _scene_environment_context(request, episode_id=episode.id)
            episode.runtime_metadata = {
                **dict(episode.runtime_metadata or {}),
                "environment_context": initial_environment_context,
            }
            session.commit()
            initial_snapshot = snapshot_repo.create(
                {
                    "task_spec_id": task_spec.id,
                    "execution_plan_id": plan.id,
                    "execution_episode_id": episode.id,
                    "source": "scene_context_request",
                    "environment_key": str(
                        request["environment_requirements"].get("environment_key")
                        or request["context"].get("environment_key")
                        or episode.id
                    ),
                    "status": "requested",
                    "resource_locator": _optional_string(initial_environment_context.get("resource_locator")),
                    "display_label": _optional_string(initial_environment_context.get("display_label"), max_length=255),
                    "environment_kind": _optional_string(
                        initial_environment_context.get("environment_kind"),
                        max_length=128,
                    ),
                    "capability_hints": list(request["preferred_capabilities"]),
                    "runtime_metadata": {
                        "scene_context": True,
                        "environment_descriptor": _compact_value(
                            _environment_descriptor(initial_environment_context),
                        ),
                        "environment_requirements": _compact_value(request["environment_requirements"]),
                        "context": _compact_value(request["context"]),
                        "anti_detection_policy": _compact_value(request["anti_detection_policy"]),
                        "behavior_budget": _compact_value(request["behavior_budget"]),
                    },
                }
            )
            snapshot_ids.append(initial_snapshot.id)

            try:
                return self._run_episode(
                    session=session,
                    request=request,
                    task_spec=task_spec,
                    plan=plan,
                    episode=episode,
                    snapshot_ids=snapshot_ids,
                )
            except Exception as exc:  # pragma: no cover - defensive guard
                return self._finalize_error(
                    session=session,
                    task_spec=task_spec,
                    plan=plan,
                    episode=episode,
                    snapshot_ids=snapshot_ids,
                    message=str(exc),
                )

    def _run_episode(
        self,
        *,
        session: Session,
        request: dict[str, Any],
        task_spec: Any,
        plan: Any,
        episode: Any,
        snapshot_ids: list[str],
    ) -> dict[str, Any]:
        last_outcome = AgentTurnOutcome(status="continue", gate_signal="continue")
        blockers: list[dict[str, Any]] = []
        browser_semantics = _initial_browser_semantics(request)
        scene_tool_registry = _scene_tool_registry(
            self.tool_registry,
            request=request,
            browser_semantics=browser_semantics,
            workspace_pause_checker=lambda: _workspace_control_paused(self.session_factory),
        )
        max_llm_invocations = int(request["max_llm_invocations"] or self.limits.max_llm_invocations or 8)
        scene_turn_timeout_seconds = int(self.limits.scene_turn_timeout_seconds or 0)
        engine_events: list[dict[str, Any]] = []
        adapter_context = build_scene_turn_context(
            request=request,
            episode_id=episode.id,
            task_spec_id=task_spec.id,
            max_llm_invocations=max_llm_invocations,
            recent_events=list(episode.observations or [])[-8:],
            available_tools=sorted(scene_tool_registry.tools.keys()),
            available_mcps=_available_mcp_names(scene_tool_registry),
            instruction=_build_scene_instruction(request),
        )
        engine = InteractionEngine(
            InteractionEngineConfig(
                conversation_id=episode.id,
                provider=self.provider,
                tools=scene_tool_registry.to_agent_runtime_tools(),
                initial_messages=adapter_context.initial_messages,
                max_llm_invocations=max_llm_invocations,
                max_context_chars=90000,
                compaction_summary_max_chars=6000,
                text_format=_scene_text_format(request),
            )
        )
        last_outcome = _scene_outcome_from_engine_with_timeout(
            engine=engine,
            instruction=adapter_context.turn_input,
            engine_events=engine_events,
            browser_semantics=browser_semantics,
            workspace_pause_checker=lambda: _workspace_control_paused(self.session_factory),
            timeout_seconds=scene_turn_timeout_seconds,
        )
        blockers = _collect_blockers(last_outcome, engine_events)
        if not _is_workspace_paused_outcome(last_outcome) and _should_retry_scene_for_missing_hid(
            outcome=last_outcome,
            blockers=blockers,
            events=engine_events,
            request=request,
            available_tools=scene_tool_registry.tools.keys(),
        ):
            last_outcome = _scene_outcome_from_engine_with_timeout(
                engine=engine,
                instruction=_missing_hid_retry_instruction(),
                engine_events=engine_events,
                browser_semantics=browser_semantics,
                workspace_pause_checker=lambda: _workspace_control_paused(self.session_factory),
                timeout_seconds=scene_turn_timeout_seconds,
            )
            blockers = _collect_blockers(last_outcome, engine_events)
        raw_blockers = _collect_blockers(last_outcome, engine_events, ignore_recovered=False)
        if not _is_workspace_paused_outcome(last_outcome) and _should_retry_scene_for_recovered_tool_error(
            outcome=last_outcome,
            blockers=raw_blockers,
            events=engine_events,
        ):
            last_outcome = _scene_outcome_from_engine_with_timeout(
                engine=engine,
                instruction=_recovered_tool_error_retry_instruction(raw_blockers),
                engine_events=engine_events,
                browser_semantics=browser_semantics,
                workspace_pause_checker=lambda: _workspace_control_paused(self.session_factory),
                timeout_seconds=scene_turn_timeout_seconds,
            )
            blockers = _collect_blockers(last_outcome, engine_events)
        raw_blockers = _collect_blockers(last_outcome, engine_events, ignore_recovered=False)
        if not _is_workspace_paused_outcome(last_outcome) and _should_retry_scene_for_browser_wait_timeout(
            outcome=last_outcome,
            blockers=raw_blockers,
            events=engine_events,
        ):
            last_outcome = _scene_outcome_from_engine_with_timeout(
                engine=engine,
                instruction=_browser_wait_timeout_retry_instruction(raw_blockers),
                engine_events=engine_events,
                browser_semantics=browser_semantics,
                workspace_pause_checker=lambda: _workspace_control_paused(self.session_factory),
                timeout_seconds=scene_turn_timeout_seconds,
            )
            blockers = _collect_blockers(last_outcome, engine_events)
        raw_blockers = _collect_blockers(last_outcome, engine_events, ignore_recovered=False)
        if not _is_workspace_paused_outcome(last_outcome) and _should_retry_scene_for_transient_hid_error(
            outcome=last_outcome,
            blockers=raw_blockers,
            events=engine_events,
        ):
            last_outcome = _scene_outcome_from_engine_with_timeout(
                engine=engine,
                instruction=_transient_hid_error_retry_instruction(raw_blockers),
                engine_events=engine_events,
                browser_semantics=browser_semantics,
                workspace_pause_checker=lambda: _workspace_control_paused(self.session_factory),
                timeout_seconds=scene_turn_timeout_seconds,
            )
            blockers = _collect_blockers(last_outcome, engine_events)
        raw_blockers = _collect_blockers(last_outcome, engine_events, ignore_recovered=False)
        if not _is_workspace_paused_outcome(last_outcome) and _should_retry_scene_for_incomplete_progress(
            outcome=last_outcome,
            blockers=raw_blockers,
        ):
            last_outcome = _scene_outcome_from_engine_with_timeout(
                engine=engine,
                instruction=_incomplete_progress_retry_instruction(),
                engine_events=engine_events,
                browser_semantics=browser_semantics,
                workspace_pause_checker=lambda: _workspace_control_paused(self.session_factory),
                timeout_seconds=scene_turn_timeout_seconds,
            )
            blockers = _collect_blockers(last_outcome, engine_events)
        snapshot_ids.extend(
            _append_environment_snapshots(
                session=session,
                task_spec=task_spec,
                plan=plan,
                episode=episode,
                request=request,
                events=engine_events,
            )
        )
        _append_episode_engine_events(
            session=session,
            episode=episode,
            engine_output_count=int((last_outcome.metadata or {}).get("engine_output_count") or 0),
            events=engine_events,
            outcome=last_outcome,
            blockers=blockers,
            snapshot_count=len(snapshot_ids),
        )

        return self._finalize_success(
            session=session,
            task_spec=task_spec,
            plan=plan,
            episode=episode,
            output_contract=dict(request["output_contract"]),
            outcome=last_outcome,
            blockers=blockers,
            snapshot_ids=snapshot_ids,
        )

    def _finalize_success(
        self,
        *,
        session: Session,
        task_spec: Any,
        plan: Any,
        episode: Any,
        output_contract: dict[str, Any],
        outcome: AgentTurnOutcome,
        blockers: list[dict[str, Any]],
        snapshot_ids: list[str],
    ) -> dict[str, Any]:
        blockers = list(blockers or [])
        evidence_blocker = _missing_required_scene_browser_hid_evidence_blocker(episode)
        if evidence_blocker:
            blockers.append(evidence_blocker)
        result_data = _scene_result_data(outcome, output_contract=output_contract)
        result_data = _normalize_scene_result_contract_data(result_data, output_contract)
        contract_blockers = _scene_result_contract_blockers(result_data, output_contract)
        if contract_blockers:
            blockers.extend(contract_blockers)
            result_data = {
                **result_data,
                "contract_validation": {
                    "status": "failed",
                    "blockers": contract_blockers,
                },
            }
        public_status = _public_status(outcome, blockers, result_data=result_data)
        result_data = _align_result_data_status(result_data, public_status)
        stored_status = _stored_status(public_status)
        summary = _public_summary(outcome, blockers)
        metrics = {
            "engine_output_count": int((episode.metrics or {}).get("engine_output_count") or 0),
            "tool_call_count": int((episode.metrics or {}).get("tool_call_count") or 0),
            "tool_result_count": int((episode.metrics or {}).get("tool_result_count") or 0),
            "environment_snapshot_count": len(snapshot_ids),
            "blocker_count": len(blockers),
            "status": public_status,
        }

        episode.status = stored_status
        episode.finished_at = utcnow()
        episode.result_summary = summary
        episode.last_error = None if public_status != "error" else summary
        episode.metrics = metrics

        task_spec.status = stored_status
        plan.status = stored_status
        session.commit()

        runtime_metadata = dict(episode.runtime_metadata or {})
        result_artifacts = _scene_result_artifacts(result_data)
        return {
            "status": public_status,
            "summary": summary,
            "result_data": result_data,
            "skill_draft": dict(outcome.skill_draft or {}),
            "blockers": blockers,
            "environment_context": _as_dict(runtime_metadata.get("environment_context")),
            "execution_contract": _as_dict(runtime_metadata.get("execution_contract")),
            "artifacts": result_artifacts
            + [
                {"kind": "environment_snapshot", "snapshot_id": snapshot_id}
                for snapshot_id in _dedupe_strings(snapshot_ids)
            ],
            "metrics": metrics,
            "episode_id": episode.id,
        }

    def _finalize_error(
        self,
        *,
        session: Session,
        task_spec: Any,
        plan: Any,
        episode: Any,
        snapshot_ids: list[str],
        message: str,
    ) -> dict[str, Any]:
        task_spec.status = "failed"
        plan.status = "failed"
        episode.status = "failed"
        episode.finished_at = utcnow()
        episode.last_error = message
        episode.result_summary = message
        episode.metrics = {
            "engine_output_count": int((episode.metrics or {}).get("engine_output_count") or 0),
            "tool_call_count": int((episode.metrics or {}).get("tool_call_count") or 0),
            "tool_result_count": int((episode.metrics or {}).get("tool_result_count") or 0),
            "environment_snapshot_count": len(snapshot_ids),
            "blocker_count": 1,
            "status": "error",
        }
        session.commit()
        return {
            "status": "error",
            "summary": message,
            "result_data": {},
            "skill_draft": {},
            "blockers": [{"kind": "scene_context_error", "message": message}],
            "environment_context": _as_dict((episode.runtime_metadata or {}).get("environment_context")),
            "execution_contract": _as_dict((episode.runtime_metadata or {}).get("execution_contract")),
            "artifacts": [
                {"kind": "environment_snapshot", "snapshot_id": snapshot_id}
                for snapshot_id in _dedupe_strings(snapshot_ids)
            ],
            "metrics": dict(episode.metrics or {}),
            "episode_id": episode.id,
        }


def _normalize_optional_positive_int(value: Any, *, default: int | None = None) -> int | None:
    raw_value = default if value is None else value
    if raw_value is None:
        return None
    if isinstance(raw_value, str) and raw_value.strip().lower() in {"", "none", "null", "unlimited", "disabled"}:
        return None
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _normalize_scene_request(
    arguments: dict[str, Any],
    *,
    default_max_llm_invocations: int | None,
    default_anti_detection_policy: dict[str, Any] | None = None,
    default_behavior_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    instruction = str(arguments.get("instruction") or "").strip()
    if not instruction:
        raise ValueError("delegate_scene_context requires instruction")
    title = str(arguments.get("title") or instruction[:80]).strip() or "Scene context task"
    success_criteria = _as_dict(arguments.get("success_criteria"))
    output_contract = _as_dict(arguments.get("output_contract"))
    preferred_capabilities = _normalize_preferred_scene_capabilities(arguments.get("preferred_capabilities"))
    environment_requirements = _as_dict(arguments.get("environment_requirements"))
    approval_policy = _as_dict(arguments.get("approval_policy"))
    context = _as_dict(arguments.get("context"))
    input_payload = _as_dict(arguments.get("input"))
    anti_detection_policy = _merge_policy_dicts(
        default_anti_detection_policy,
        context.get("anti_detection_policy"),
        environment_requirements.get("anti_detection_policy"),
        arguments.get("anti_detection_policy"),
    )
    behavior_budget = _merge_policy_dicts(
        default_behavior_budget,
        context.get("behavior_budget"),
        environment_requirements.get("behavior_budget"),
        arguments.get("behavior_budget"),
    )
    browser_target = _normalize_browser_target(
        derive_browser_target(
            existing=arguments.get("browser_target")
            or environment_requirements.get("browser_target")
            or context.get("browser_target"),
            structured_sources=(arguments, environment_requirements, context, input_payload, success_criteria, output_contract),
            text_sources=(
                instruction,
                title,
                arguments.get("description"),
            ),
        )
    )
    computer_target = _normalize_computer_target(
        arguments.get("computer_target") or environment_requirements.get("computer_target") or context.get("computer_target")
    )
    target_regions = _normalize_target_regions(
        arguments.get("target_regions") or environment_requirements.get("target_regions") or context.get("target_regions")
    )
    action_plan = _normalize_action_plan(
        arguments.get("action_plan") or environment_requirements.get("action_plan") or context.get("action_plan")
    )
    artifact_expectations = _normalize_artifact_expectations(
        arguments.get("artifact_expectations")
        or output_contract.get("artifact_expectations")
        or environment_requirements.get("artifact_expectations")
        or context.get("artifact_expectations")
    )
    if browser_target:
        context["browser_target"] = browser_target
        environment_requirements["browser_target"] = browser_target
    if computer_target:
        context["computer_target"] = computer_target
        environment_requirements["computer_target"] = computer_target
    if target_regions:
        context["target_regions"] = target_regions
        environment_requirements["target_regions"] = target_regions
    if action_plan:
        context["action_plan"] = action_plan
        environment_requirements["action_plan"] = action_plan
    if artifact_expectations:
        context["artifact_expectations"] = artifact_expectations
        environment_requirements["artifact_expectations"] = artifact_expectations
        output_contract["artifact_expectations"] = artifact_expectations
    if anti_detection_policy:
        context["anti_detection_policy"] = anti_detection_policy
        environment_requirements["anti_detection_policy"] = anti_detection_policy
    if behavior_budget:
        context["behavior_budget"] = behavior_budget
        environment_requirements["behavior_budget"] = behavior_budget
    max_llm_invocations = _normalize_optional_positive_int(
        arguments.get("max_llm_invocations"),
        default=default_max_llm_invocations,
    )
    requested_by = str(arguments.get("requested_by") or context.get("requested_by") or "").strip() or None
    approval_policy.setdefault("requires_confirmation", bool(approval_policy.get("requires_confirmation")))
    return {
        "title": title,
        "description": str(arguments.get("description") or "").strip() or None,
        "instruction": instruction,
        "success_criteria": success_criteria,
        "output_contract": output_contract,
        "preferred_capabilities": preferred_capabilities,
        "environment_requirements": environment_requirements,
        "approval_policy": approval_policy,
        "context": context,
        "input": input_payload,
        "browser_target": browser_target,
        "computer_target": computer_target,
        "target_regions": target_regions,
        "action_plan": action_plan,
        "artifact_expectations": artifact_expectations,
        "anti_detection_policy": anti_detection_policy,
        "behavior_budget": behavior_budget,
        "max_llm_invocations": max_llm_invocations,
        "requested_by": requested_by,
    }


def _build_scene_instruction(request: dict[str, Any]) -> str:
    parts = [
        request["instruction"],
        "只使用当前可用的 scene 工具完成任务。",
        "输出必须是业务级摘要，避免复述 DOM、页面按钮、tab 轨迹、资源定位符等环境细节，除非它们是阻塞判断所必需的证据。",
    ]
    context = _as_dict(request.get("context"))
    must_target = _dedupe_strings(
        _string_list(
            context.get("must_target_remaining")
            or context.get("remaining_targets")
            or context.get("remaining_jobs")
            or context.get("target_jobs")
            or context.get("known_jobs")
            or context.get("remaining_job_titles")
        )
    )
    must_ignore = _dedupe_strings(
        _string_list(
            context.get("must_ignore_already_synced")
            or context.get("already_synced_or_verified")
            or context.get("already_completed_jobs")
            or context.get("already_verified")
            or context.get("synced_job_titles")
            or context.get("synced_job_external_ids")
        )
    )
    if must_target:
        parts.append(
            "本 scene 的强制目标集合："
            f"{_compact_value(must_target)}。必须优先完成这些目标；"
            "如果 browser_snapshot 返回了目标对应的链接但 inViewport=false，不能点击其他相似职位替代，"
            "必须先使用 hid_action 执行页面滚动/滚轮使该目标链接进入 viewport，随后重新 browser_snapshot/query 确认，"
            "再基于新的 in-viewport clickPoint 执行 HID click。"
            "若只完成目标集合的一部分，overall_status/status 不得为 completed。"
        )
    if must_ignore:
        parts.append(
            "本 scene 的已完成/禁止重复目标集合："
            f"{_compact_value(must_ignore)}。除非任务明确要求复核这些目标，否则不要打开、读取、总结或写回这些目标；"
            "如果当前页面落在已完成目标详情页，应通过页面内返回/列表导航/滚动恢复到列表，并继续强制目标集合。"
        )
    if request["success_criteria"]:
        parts.append(f"成功标准：{request['success_criteria']}")
    if request["output_contract"]:
        parts.append(f"结果合同：{request['output_contract']}")
        if request["output_contract"].get("result_data_required"):
            parts.append(
                "结果合同要求结构化 result_data：最终回答必须是单个有效 JSON object（json object），不要使用 Markdown 代码块或额外解释。"
                "JSON/json 必须直接包含 output_contract.required_fields 中列出的字段；不要把这些字段藏在 summary、business_summary、"
                "current_real_progress 或其他自由文本字段中。若任一必需字段缺失、为空或未被证据支持，status 不得为 completed。"
            )
    if request["browser_target"]:
        parts.append(f"浏览器目标：{_compact_value(request['browser_target'])}")
        parts.append(
            "当 browser_target.url 存在时，必须以该 URL 的完整 origin（包含端口）作为目标边界。"
            "browser_target.url 只是入口提示，不是要求当前活动页路径必须完全等于该 URL；同 origin 下的路径可随工作流跳转。"
            "不要把同 hostname 但不同端口、不同 origin 或旧测试 tab 当成当前任务目标；"
            "browser 侧只允许只读 snapshot/query/wait/target-identification；不得把 browser 工具当作点击、导航、下载、Cookie 或外壳维护执行器。"
            "如果 browser_get_active_tab 返回的活动页不是目标 origin，这只是当前活动页不匹配，不是终局阻塞；"
            "必须继续用 browser_list_tabs 查找同 origin 页签，找到后基于该 tabId 观察目标页，或通过 VirtualHID 切换到同 origin 页签。"
            "只有 browser_list_tabs 也找不到同 origin 页签，或同 origin 页签不可观察/不可切换时，才返回结构化 blocker 或请求 human 处理。"
        )
    if request["anti_detection_policy"] or request["behavior_budget"]:
        parts.append(
            "通用反检测与行为预算：必须遵守 anti_detection_policy 与 behavior_budget 中的通用节奏、停留、重试和 HID 动作上限；"
            "这些字段只允许表达通用 human-paced 执行约束，不允许推导站点专用选择器、站点工作流分支、JS stealth 或 fingerprint 覆盖逻辑。"
        )
    if request["computer_target"] or "computer" in _scene_capabilities(request["preferred_capabilities"]):
        parts.append(
            "如需调用电脑/HID 动作，不要自行计算屏幕绝对坐标；必须先从 browser snapshot 的 clickPoint、"
            "候选落地区域或等价观察证据构造明确的 HID primitives，并携带 browser-derived target/context host。"
            "browser 侧只提供页面语义与 viewport/document 坐标；不要让 browser 或 recruit-station 合成 viewportInScreen。"
            "HID 目标窗口、内容视口到屏幕的映射由 VirtualHID 根据 target/geometry 自行解析。"
            "不得只传 target/context 而空缺 primitives；若缺少可执行原语，继续观察或返回结构化 blocker。"
            "网页 HID 动作必须把目标浏览器窗口置前：hid_action.target 应携带 browser 观察得到的 tabId/windowId/windowTitle/host，"
            "如果 browser 观察返回窗口 bounds，也必须原样携带 browserWindowBounds 作为原生窗口消歧证据；"
            "由 VirtualHID 在执行计划中 activateTarget；不要对当前前台窗口或当前活动页做模糊点击。"
            "Chrome 外壳遮挡 preflight 由 hid_action options.browserChromeOverlayPolicy 启用，证据来自 result.preflight.browserChromeOverlay；若 preflight 结果为 blocked 或 unknown，停止当前动作，改为重新观察、等待或进入 human handling。"
            "外部执行层负责激活、滚动和最终落点。"
        )
        parts.append(
            "当 scene 可用工具包含 hid_action 时，只读 browser 工具不代表不能点击或导航；"
            "browser 负责观察，hid_action 负责执行点击、滚动、输入、返回等页面动作。"
            "如果任务需要进入详情页、翻页或返回列表，必须先基于 browser 观察到的 link/button/clickPoint 构造 hid_action 尝试执行，"
            "如果目标 link/button 在 browser 观察中存在但 inViewport=false，必须先用 hid_action 进行页面滚动，"
            "滚动后重新 browser 观察并使用新的 viewport 内 clickPoint；不得使用 offscreen clickPoint，也不得改点其他已完成目标。"
            "随后再用 browser 观察确认结果。只有 hid_action 缺失、缺少可执行观察证据，或 hid_action 返回明确 blocked/error 后，"
            "才可以把页面交互能力作为 blocker。不得在未尝试 hid_action 的情况下声称当前能力仅支持只读观察。"
        )
        parts.append(
            "如果 hid_action 返回 E_CURSOR_INTERFERENCE 或等价的光标/人工输入干扰错误，"
            "这属于可恢复的瞬时执行干扰：先用 hid_state 或 browser 观察确认环境，再重试同一业务动作；"
            "至少完成一次重新观察后的重试，仍连续失败时才把它作为 human recovery blocker。"
        )
        parts.append(
            "如果 hid_action 返回 E_NOT_FRONTMOST、E_TIMEOUT 或等价的焦点/导航恢复失败，"
            "不要把这一次工具失败直接当作业务终局。应先重新观察目标 origin 的页签、确认当前 URL/标题/可点击入口，"
            "释放异常修饰键状态并基于页面内可见入口、返回、滚动或其他同源页面导航控件重试同一业务动作。"
            "禁止主动聚焦浏览器地址栏、输入 URL 或粘贴 URL 作为恢复路径；只有页面内连续恢复后目标仍不可操作，才返回 human recovery blocker。"
        )
        parts.append(
            "如果同源站点内的点击、返回、滚动或单次 HID 注入超时失败，不要直接结束场景。"
            "应先重新观察页面状态，释放异常按键状态，等待或滚动到稳定位置，尝试页面上其他同源链接/导航入口，"
            "或回到页面内已观察到的列表/详情入口后继续原始业务目标。"
            "浏览器地址栏、直接输入 URL、粘贴 URL 和浏览器外壳导航不属于招聘网站页面内业务动作，除非用户显式要求，否则不得作为恢复路径。"
            "如果原始目标只完成一部分且仍存在 blockers、limitations 或未完成项，最终 status 不得写 completed；"
            "应继续恢复执行，或返回 blocked 并写明恢复条件。"
        )
    if request["target_regions"]:
        parts.append(f"候选落地区域：{_compact_value(request['target_regions'])}")
    if request["action_plan"]:
        parts.append(f"动作意图：{_compact_value(request['action_plan'])}")
    if request["artifact_expectations"]:
        parts.append(
            "若结果合同要求本地文件或附件，不要用页面 JS、mock DOM 标记或下载入口本身冒充本地文件。"
            "浏览器触发下载前，必须先调用 local_download_create_attempt，记录 downloadAttemptId、candidate、source URL、href/download、startedAt 和下载目录快照。"
            "HID 点击下载后，必须先进行 browser 观察/等待，再用 local_download_attribute(downloadAttemptId) 归因本地新增文件。"
            "local_download_attribute 只可接受 completed、timeout 或 ambiguous；timeout/ambiguous 不能当作本地 artifact proof。"
            "只有在业务层确认 path、格式和归档条件后才能结束。"
        )
    if request["output_contract"] or request["artifact_expectations"]:
        parts.append(
            "若 scene 已拿到可写回业务层的本地 artifact，结构化 result_data 必须保留 artifact/download_attribution "
            "和 business_writeback 字段；business_writeback.arguments 应直接适配后续业务写入工具（例如 resume artifact "
            "写回时的 attach_resume_artifact），但 scene 内不要绕过合同自行编造 artifact proof。"
        )
    return "\n".join(part for part in parts if part)


def _scene_text_format(request: dict[str, Any]) -> dict[str, Any] | None:
    output_contract = _as_dict(request.get("output_contract"))
    if output_contract.get("result_data_required"):
        return {"type": "json_object"}
    return None


def _build_checkpoints(request: dict[str, Any]) -> list[dict[str, Any]]:
    checkpoints = [
        {"label": "scene_observe", "summary": "Inspect the delegated execution environment and confirm actionable signals."},
        {"label": "scene_execute", "summary": "Use scene tools to pursue the delegated contract within the isolated environment."},
        {"label": "scene_summarize", "summary": "Return business summary, blockers, and retained environment evidence."},
    ]
    if request["approval_policy"]:
        checkpoints.append({"label": "approval_gate", "summary": "Respect approval policy before risky actions."})
    return checkpoints


def _append_episode_engine_events(
    *,
    session: Session,
    episode: Any,
    engine_output_count: int,
    events: list[dict[str, Any]],
    outcome: AgentTurnOutcome,
    blockers: list[dict[str, Any]],
    snapshot_count: int,
) -> None:
    observation_entries = list(episode.observations or [])
    action_entries = list(episode.actions or [])
    for event in events:
        event_type = str(event.get("type") or "")
        payload = _as_dict(event.get("payload"))
        kind = str(payload.get("kind") or "")
        entry = {
            "engine_output_seq": event.get("engine_output_seq"),
            "type": event_type,
            "recorded_at": event.get("recorded_at"),
            "payload": payload,
        }
        if event_type == "tool_event" and kind in {"tool_call_started", "tool_use_completed", "tool_result_ready"}:
            action_entries.append(entry)
        if not (event_type == "tool_event" and kind in {"tool_call_started", "tool_use_completed"}):
            observation_entries.append(entry)
    observation_entries = observation_entries[-200:]
    action_entries = action_entries[-200:]
    episode.observations = observation_entries
    episode.actions = action_entries
    episode.result_summary = outcome.final_output or _public_summary(outcome, blockers)
    episode.metrics = {
        "engine_output_count": max(engine_output_count, int((episode.metrics or {}).get("engine_output_count") or 0)),
        "tool_call_count": len(action_entries),
        "tool_result_count": sum(
            1
            for item in action_entries
            if item.get("type") == "tool_event" and _as_dict(item.get("payload")).get("kind") == "tool_result_ready"
        )
        or sum(
            1
            for item in observation_entries
            if item.get("type") == "tool_event" and _as_dict(item.get("payload")).get("kind") == "tool_result_ready"
        ),
        "environment_snapshot_count": snapshot_count,
        "blocker_count": len(blockers),
        "last_gate_signal": outcome.gate_signal,
    }
    session.commit()


def _missing_required_scene_browser_hid_evidence_blocker(episode: Any) -> dict[str, Any] | None:
    runtime_metadata = _as_dict(getattr(episode, "runtime_metadata", None))
    execution_contract = _as_dict(runtime_metadata.get("execution_contract"))
    browser_target = _as_dict(execution_contract.get("browser_target"))
    if not browser_target:
        return None
    if _episode_has_successful_browser_or_hid_tool_result(episode):
        return None
    return {
        "kind": "missing_browser_hid_evidence",
        "message": (
            "scene context has a browser target but produced no successful browser/HID tool result; "
            "the scene cannot be marked completed without observed browser or computer execution evidence."
        ),
    }


def _episode_has_successful_browser_or_hid_tool_result(episode: Any) -> bool:
    for entry in list(getattr(episode, "actions", None) or []) + list(getattr(episode, "observations", None) or []):
        if not isinstance(entry, dict) or str(entry.get("type") or "") != "tool_event":
            continue
        payload = _as_dict(entry.get("payload"))
        tool_name = str(payload.get("tool_name") or "").strip()
        if not (tool_name.startswith("browser_") or tool_name.startswith("hid_")):
            continue
        if _tool_event_result_succeeded(entry):
            return True
    return False


def _append_environment_snapshots(
    *,
    session: Session,
    task_spec: Any,
    plan: Any,
    episode: Any,
    request: dict[str, Any],
    events: list[dict[str, Any]],
) -> list[str]:
    snapshot_repo = EnvironmentSnapshotRepository(session)
    snapshot_ids: list[str] = []
    for event in events:
        if str(event.get("type") or "") != "tool_event":
            continue
        payload = _as_dict(event.get("payload"))
        if payload.get("kind") != "tool_result_ready":
            continue
        tool_name = str(payload.get("tool_name") or "")
        output = payload.get("content")
        for candidate in _snapshot_candidates(tool_name=tool_name, output=output):
            snapshot = snapshot_repo.create(
                {
                    "task_spec_id": task_spec.id,
                    "execution_plan_id": plan.id,
                    "execution_episode_id": episode.id,
                    "source": str(candidate.get("source") or tool_name or "scene_tool"),
                    "environment_key": str(
                        candidate.get("environment_key")
                        or request["environment_requirements"].get("environment_key")
                        or episode.id
                    ),
                    "status": str(candidate.get("status") or "observed"),
                    "resource_locator": _optional_string(candidate.get("resource_locator")),
                    "display_label": _optional_string(candidate.get("display_label"), max_length=255),
                    "environment_kind": _optional_string(candidate.get("environment_kind"), max_length=128),
                    "capability_hints": _dedupe_strings(
                        [
                            *request["preferred_capabilities"],
                            *_string_list(candidate.get("capability_hints")),
                        ]
                    ),
                    "observed_entities": _list_of_dicts(candidate.get("observed_entities")),
                    "action_hints": _list_of_dicts(candidate.get("action_hints")),
                    "runtime_metadata": {
                        "engine_output_seq": event.get("engine_output_seq"),
                        "tool_name": tool_name,
                        "environment_descriptor": _compact_value(_environment_descriptor(candidate)),
                        "raw": _compact_value(candidate.get("runtime_metadata") or candidate),
                    },
                }
            )
            snapshot_ids.append(snapshot.id)
    return snapshot_ids


def _scene_outcome_from_engine(
    *,
    engine: InteractionEngine,
    instruction: str,
    engine_events: list[dict[str, Any]],
    browser_semantics: dict[str, Any],
    workspace_pause_checker: Any | None = None,
) -> AgentTurnOutcome:
    if callable(workspace_pause_checker) and workspace_pause_checker():
        engine.interrupt("workspace_paused")
        return _workspace_paused_scene_outcome(engine_events, engine_output_count=0)
    final_output = ""
    status = "complete"
    gate_signal = "run_done"
    result_data: dict[str, Any] | None = None
    engine_output_count = 0
    for output in engine.submitMessage(instruction):
        engine_output_count += 1
        engine_events.append(_runtime_output_event(output))
        if output.type == "tool_event" and output.data.get("kind") == "tool_result_ready":
            _remember_browser_semantics(
                browser_semantics,
                tool_name=str(output.data.get("tool_name") or ""),
                output=output.data.get("content"),
            )
        if output.type == "assistant_message_completed":
            final_output = str(output.data.get("message") or "")
        elif output.type == "llm_invocation_completed":
            provider_result_data = _as_dict(output.data.get("result_data"))
            if provider_result_data:
                result_data, _skill_draft = normalize_result_payload(provider_result_data)
        elif output.type == "permission_requested":
            status = "wait_human"
            gate_signal = "wait_human"
        elif output.type == "turn_failed":
            status = "error"
            gate_signal = "escalate"
        elif output.type == "turn_interrupted":
            status = "cancelled"
            gate_signal = "paused"
        if callable(workspace_pause_checker) and workspace_pause_checker():
            engine.interrupt("workspace_paused")
            return _workspace_paused_scene_outcome(engine_events, engine_output_count=engine_output_count)
    if status == "complete" and not str(final_output or "").strip() and not result_data:
        status = "escalate"
        gate_signal = "budget_exhausted"
    return AgentTurnOutcome(
        status=status,  # type: ignore[arg-type]
        gate_signal=gate_signal,  # type: ignore[arg-type]
        final_output=final_output,
        result_data=result_data,
        metadata={"interaction_engine": True, "engine_output_count": engine_output_count},
    )


def _scene_outcome_from_engine_with_timeout(
    *,
    engine: InteractionEngine,
    instruction: str,
    engine_events: list[dict[str, Any]],
    browser_semantics: dict[str, Any],
    workspace_pause_checker: Any | None = None,
    timeout_seconds: int | None,
) -> AgentTurnOutcome:
    effective_timeout = int(timeout_seconds or 0)
    if effective_timeout <= 0:
        return _scene_outcome_from_engine(
            engine=engine,
            instruction=instruction,
            engine_events=engine_events,
            browser_semantics=browser_semantics,
            workspace_pause_checker=workspace_pause_checker,
        )

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scene-context-turn")
    future = executor.submit(
        _scene_outcome_from_engine,
        engine=engine,
        instruction=instruction,
        engine_events=engine_events,
        browser_semantics=browser_semantics,
        workspace_pause_checker=workspace_pause_checker,
    )
    try:
        return future.result(timeout=effective_timeout)
    except FutureTimeoutError:
        engine.interrupt("scene_context_timeout")
        future.cancel()
        message = f"E_SCENE_TIMEOUT: scene_context turn exceeded timeoutSeconds={effective_timeout}"
        engine_events.append(
            {
                "type": "runtime_event",
                "engine_output_seq": len(engine_events) + 1,
                "payload": {
                    "kind": "scene_context_timeout",
                    "status": "blocked",
                    "message": message,
                    "timeout_seconds": effective_timeout,
                },
                "recorded_at": utcnow().isoformat(),
            }
        )
        return AgentTurnOutcome(
            status="escalate",
            gate_signal="escalate",
            final_output=message,
            result_data={
                "status": "blocked",
                "blockers": [{"kind": "scene_context_timeout", "message": message}],
                "remaining_work": ["resume_scene_after_timeout"],
            },
            metadata={"interaction_engine": True, "engine_output_count": len(engine_events), "timeout_seconds": effective_timeout},
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _workspace_paused_scene_outcome(engine_events: list[dict[str, Any]], *, engine_output_count: int) -> AgentTurnOutcome:
    message = "workspace is paused; scene execution stopped before issuing another action."
    blocker = {"kind": "workspace_paused", "message": message}
    engine_events.append(
        {
            "type": "runtime_event",
            "engine_output_seq": len(engine_events) + 1,
            "payload": {
                "kind": "workspace_paused",
                "status": "blocked",
                "message": message,
            },
            "recorded_at": utcnow().isoformat(),
        }
    )
    return AgentTurnOutcome(
        status="escalate",
        gate_signal="paused",
        final_output=message,
        result_data={
            "status": "paused",
            "blockers": [blocker],
            "remaining_work": ["continue_workspace_to_resume_scene"],
        },
        metadata={"interaction_engine": True, "engine_output_count": engine_output_count},
    )


def _is_workspace_paused_outcome(outcome: AgentTurnOutcome) -> bool:
    result_data = _as_dict(outcome.result_data)
    if str(result_data.get("status") or "").strip().lower() == "paused" and any(
        str(item.get("kind") or "") == "workspace_paused" for item in _list_of_dicts(result_data.get("blockers"))
    ):
        return True
    return any(str(item.get("kind") or "") == "workspace_paused" for item in _list_of_dicts(result_data.get("blockers")))


def _should_retry_scene_for_missing_hid(
    *,
    outcome: AgentTurnOutcome,
    blockers: list[dict[str, Any]],
    events: list[dict[str, Any]],
    request: dict[str, Any],
    available_tools: Any,
) -> bool:
    if _has_terminal_scene_result_data(outcome):
        return False
    if _is_scene_context_timeout(outcome, blockers):
        return False
    if "hid_action" not in set(available_tools):
        return False
    if "computer" not in _scene_capabilities(request.get("preferred_capabilities")):
        return False
    if _public_status(outcome, blockers) != "blocked":
        return False
    if _has_scene_hid_attempt(events):
        return False
    return _has_actionable_browser_signal(events)


def _missing_hid_retry_instruction() -> str:
    return (
        "你的上一轮只使用 browser 观察后准备返回 blocked，但本 scene 可用 hid_action，"
        "不能在未尝试 HID 的情况下把“需要页面点击、滚动、返回、进入详情或翻页”报告为能力不足。"
        "请继续当前场景：基于最近 browser 观察到的 link/button/clickPoint 构造 hid_action。"
        "如果目标元素 inViewport=false，先执行 HID scroll 或等价可恢复动作，再重新 browser 观察；"
        "如果元素在 viewport 内，执行 HID click 后重新 browser 观察确认结果。"
        "hid_action.target 必须携带 browser 观察得到的 tabId/windowId/windowTitle/host。"
        "只有在至少一次 hid_action 返回明确 blocked/error，或确实没有任何可执行页面证据后，才可以报告 blocker。"
    )


def _should_retry_scene_for_recovered_tool_error(
    *,
    outcome: AgentTurnOutcome,
    blockers: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> bool:
    if _has_terminal_scene_result_data(outcome):
        return False
    if _is_scene_context_timeout(outcome, blockers):
        return False
    if not any(str(item.get("kind") or "") == "tool_error" for item in blockers):
        return False
    if _scene_result_status(outcome) in {"completed", "complete", "success", "succeeded"}:
        return False
    return _has_recovered_tool_error(events)


def _recovered_tool_error_retry_instruction(blockers: list[dict[str, Any]]) -> str:
    tool_names = _dedupe_strings(str(item.get("tool_name") or "") for item in blockers if item.get("tool_name"))
    tool_label = ", ".join(tool_names) if tool_names else "某个工具"
    return (
        f"上一轮曾出现 {tool_label} 的临时错误，但后续工具调用已经恢复并取得新的页面观察结果。"
        "不要把已经被后续成功动作恢复的历史错误作为最终 blocker。"
        "请基于最新 browser 观察继续完成原始场景目标；如果已经进入详情页，继续读取详情并推进下一步。"
        "只有当前最新动作仍失败、页面不可达、登录/权限阻断，或没有可执行证据时，才可以返回 blocked。"
        "请返回结构化 JSON，总结当前真实进度、已恢复的错误、下一步执行结果和剩余 blocker。"
    )


def _should_retry_scene_for_browser_wait_timeout(
    *,
    outcome: AgentTurnOutcome,
    blockers: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> bool:
    if _has_terminal_scene_result_data(outcome):
        return False
    if _is_scene_context_timeout(outcome, blockers):
        return False
    if _public_status(outcome, blockers) != "blocked":
        return False
    if not _has_browser_wait_timeout_blocker(blockers):
        return False
    return _has_successful_tool_result(events, "hid_action") or _has_actionable_browser_signal(events)


def _browser_wait_timeout_retry_instruction(blockers: list[dict[str, Any]]) -> str:
    tool_names = _dedupe_strings(str(item.get("tool_name") or "") for item in blockers if item.get("tool_name"))
    tool_label = ", ".join(tool_names) if tool_names else "browser wait"
    return (
        f"上一轮 {tool_label} 超时只能说明等待确认失败，不能直接作为当前 scene 的终局 blocker。"
        "不要再次用同一个 wait 工具空等；请立即用 browser_snapshot 或 browser_list_tabs 重新确认当前 tab URL、标题和页面内容。"
        "如果已经进入详情页，继续读取详情并完成原始目标；如果仍在列表页，基于最新 clickPoint/同源详情入口继续用 hid_action 重试。"
        "只有 browser_snapshot/list_tabs 也失败、页面不可达、登录/权限阻断，或 HID 最新动作明确失败时，才可以返回 blocked。"
        "请返回结构化 JSON，说明 wait 超时后的实际页面状态、恢复动作和剩余 blocker。"
    )


def _should_retry_scene_for_incomplete_progress(
    *,
    outcome: AgentTurnOutcome,
    blockers: list[dict[str, Any]],
) -> bool:
    result_data = _as_dict(outcome.result_data)
    status = str(result_data.get("status") or _scene_result_status(outcome)).strip().lower()
    if status not in {"in_progress", "partial", "incomplete", "continuable", "continue", "pending"}:
        return False
    if _is_scene_context_timeout(outcome, blockers):
        return False
    if any(str(item.get("kind") or "") in {"login_required", "captcha", "permission_denied"} for item in blockers):
        return False
    text = _compact_value(result_data).lower()
    return any(marker in text for marker in ("滚动", "scroll", "进入详情", "detail", "needs_retry"))


def _incomplete_progress_retry_instruction() -> str:
    return (
        "你刚才返回的是未完成进度，不是本 scene 的终局。不要把 in_progress/partial 当作最终输出交回。"
        "如果页面仍可访问、仍有详情入口未进入、或只是需要滚动/重新观察/重试点击，请现在继续执行："
        "先 browser_snapshot/query 确认当前页面；对 inViewport=false 的目标用 hid_action 执行页面滚动，"
        "重新观察后再用新的 clickPoint 点击详情入口；进入详情页后读取职责、要求等详情证据。"
        "只有登录、验证码、权限、目标站点不可达或必要执行工具缺失才可返回 blocked。"
        "最终只在 completed/partial/blocked 三者中选择 status；没有完成全部强制目标时不得 completed。"
    )


def _should_retry_scene_for_transient_hid_error(
    *,
    outcome: AgentTurnOutcome,
    blockers: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> bool:
    if _has_terminal_scene_result_data(outcome):
        return False
    if _is_scene_context_timeout(outcome, blockers):
        return False
    if _public_status(outcome, blockers) != "blocked":
        return False
    if not _has_transient_hid_blocker(blockers) and not _has_transient_hid_text(outcome.final_output):
        return False
    if _has_recovered_tool_error(events):
        return False
    return _has_actionable_browser_signal(events) or _has_any_successful_browser_observation(events)


def _transient_hid_error_retry_instruction(blockers: list[dict[str, Any]]) -> str:
    messages = _dedupe_strings(str(item.get("message") or "")[:160] for item in blockers if item.get("message"))
    blocker_label = "；".join(messages[:2]) if messages else "HID 瞬时执行异常"
    return (
        f"上一轮遇到 {blocker_label}，这类 HID/前台/超时/光标状态问题不能直接作为当前 scene 的终局 blocker。"
        "请继续当前场景而不是总结结束：先用 browser_snapshot 或 browser_list_tabs 重新确认同 origin 页签的 URL、标题、页面内容和可点击入口；"
        "必要时调用 hid_state 或释放异常修饰键状态，然后基于最新 browser 证据重试同一业务动作。"
        "禁止主动聚焦浏览器地址栏、输入 URL 或粘贴 URL 作为恢复路径；应只使用页面内可见链接、按钮、滚动、返回或导航控件恢复。"
        "只有重试后仍连续失败、目标页面不可达、登录/权限阻断，或缺少任何页面内可执行证据，才可以返回 blocked。"
    )


def _is_scene_context_timeout(outcome: AgentTurnOutcome, blockers: list[dict[str, Any]]) -> bool:
    if any(str(item.get("kind") or "") == "scene_context_timeout" for item in blockers):
        return True
    result_data = _as_dict(outcome.result_data)
    if any(str(item.get("kind") or "") == "scene_context_timeout" for item in _list_of_dicts(result_data.get("blockers"))):
        return True
    return "e_scene_timeout" in str(outcome.final_output or "").lower()


def _has_terminal_scene_result_data(outcome: AgentTurnOutcome) -> bool:
    if not isinstance(outcome.result_data, dict) or not outcome.result_data:
        return False
    return _scene_result_status(outcome) in {
        "blocked",
        "wait_human",
        "waiting_human",
        "paused",
        "error",
        "failed",
        "failure",
        "fail",
    }


def _has_transient_hid_blocker(blockers: list[dict[str, Any]]) -> bool:
    transient_markers = (
        "e_timeout",
        "timeout",
        "timed out",
        "超时",
        "e_not_frontmost",
        "not frontmost",
        "frontmost",
        "未置前",
        "e_cursor_interference",
        "cursor interference",
        "光标",
        "modifier",
        "修饰键",
        "daemon 无响应",
        "daemon unreachable",
        "native host unavailable",
        "native-host",
        "hid",
        "virtualhid",
    )
    for blocker in blockers:
        tool_name = str(blocker.get("tool_name") or "").lower()
        message = str(blocker.get("message") or "").lower()
        if tool_name != "hid_action" and "hid" not in message and "virtualhid" not in message:
            continue
        if any(marker in message for marker in transient_markers):
            return True
    return False


def _has_transient_hid_text(value: Any) -> bool:
    text = str(value or "").lower()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "e_timeout",
            "e_not_frontmost",
            "e_cursor_interference",
            "injector action exceeded",
            "not frontmost",
            "daemon 无响应",
            "virtualhid",
            "电脑执行链路",
        )
    )


def _has_browser_wait_timeout_blocker(blockers: list[dict[str, Any]]) -> bool:
    for blocker in blockers:
        tool_name = str(blocker.get("tool_name") or "")
        message = str(blocker.get("message") or "").lower()
        if tool_name in {"browser_wait_for_url", "browser_wait_for_navigation"} and (
            "timed out" in message or "timeout" in message or "超时" in message
        ):
            return True
    return False


def _has_successful_tool_result(events: list[dict[str, Any]], tool_name: str) -> bool:
    for event in events:
        if str(event.get("type") or "") != "tool_event":
            continue
        payload = _as_dict(event.get("payload"))
        if payload.get("kind") != "tool_result_ready":
            continue
        if str(payload.get("tool_name") or "") != tool_name:
            continue
        if not bool(payload.get("is_error")) and _tool_result_content_succeeded(payload.get("content")):
            return True
    return False


def _has_scene_hid_attempt(events: list[dict[str, Any]]) -> bool:
    return any(
        str(_as_dict(event.get("payload")).get("tool_name") or "") == "hid_action"
        for event in events
        if str(event.get("type") or "") == "tool_event"
    )


def _has_actionable_browser_signal(events: list[dict[str, Any]]) -> bool:
    for event in reversed(events):
        if str(event.get("type") or "") != "tool_event":
            continue
        payload = _as_dict(event.get("payload"))
        if payload.get("kind") != "tool_result_ready":
            continue
        tool_name = str(payload.get("tool_name") or "")
        if not tool_name.startswith("browser_"):
            continue
        if _browser_content_has_actionable_signal(payload.get("content")):
            return True
    return False


def _has_any_successful_browser_observation(events: list[dict[str, Any]]) -> bool:
    return any(
        str(_as_dict(event.get("payload")).get("tool_name") or "").startswith("browser_")
        and _tool_event_result_succeeded(event)
        for event in events
        if str(event.get("type") or "") == "tool_event"
    )


def _has_recovered_tool_error(events: list[dict[str, Any]]) -> bool:
    failed_at: dict[str, int] = {}
    recovered_at: dict[str, int] = {}
    for event in events:
        if str(event.get("type") or "") != "tool_event":
            continue
        payload = _as_dict(event.get("payload"))
        if payload.get("kind") != "tool_result_ready":
            continue
        tool_name = str(payload.get("tool_name") or "")
        if not tool_name:
            continue
        seq = _safe_int(event.get("engine_output_seq"))
        if bool(payload.get("is_error")) or not _tool_result_content_succeeded(payload.get("content")):
            failed_at[tool_name] = seq
            continue
        if tool_name in failed_at and seq > failed_at[tool_name] and _tool_result_content_succeeded(payload.get("content")):
            recovered_at[tool_name] = seq
    if not recovered_at:
        return False
    latest_recovery = max(recovered_at.values())
    has_later_browser_observation = any(
        str(_as_dict(event.get("payload")).get("tool_name") or "").startswith("browser_")
        and _safe_int(event.get("engine_output_seq")) > latest_recovery
        and _tool_event_result_succeeded(event)
        for event in events
        if str(event.get("type") or "") == "tool_event"
    )
    return has_later_browser_observation or bool(recovered_at)


def _tool_event_result_succeeded(event: dict[str, Any]) -> bool:
    payload = _as_dict(event.get("payload"))
    return (
        payload.get("kind") == "tool_result_ready"
        and not bool(payload.get("is_error"))
        and _tool_result_content_succeeded(payload.get("content"))
    )


def _tool_result_content_succeeded(content: Any) -> bool:
    if isinstance(content, dict):
        status = str(content.get("status") or "").strip().lower()
        if status in {"error", "failed", "failure", "blocked", "timeout"} or status.startswith(("failed_", "blocked_")):
            return False
        if content.get("success") is False or content.get("ok") is False or content.get("isError") is True:
            return False
        error_text = str(content.get("error") or content.get("message") or "").lower()
        if any(marker in error_text for marker in ("e_timeout", "e_not_frontmost", "e_cursor_interference")):
            return False
    return True


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _browser_content_has_actionable_signal(value: Any) -> bool:
    if isinstance(value, dict):
        for key in ("clickables", "matches", "elements", "action_hints", "affordances"):
            items = value.get(key)
            if isinstance(items, list) and any(_is_actionable_browser_item(item) for item in items):
                return True
        snapshot = value.get("snapshot")
        if isinstance(snapshot, dict) and _browser_content_has_actionable_signal(snapshot):
            return True
    if isinstance(value, list):
        return any(_browser_content_has_actionable_signal(item) for item in value)
    return False


def _is_actionable_browser_item(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("disabled") is True:
        return False
    role = str(value.get("role") or "").strip().lower()
    tag = str(value.get("tag") or "").strip().lower()
    kind = str(value.get("kind") or "").strip().lower()
    if role in {"button", "link", "menuitem", "tab", "combobox"}:
        return True
    if tag in {"a", "button", "select", "input"}:
        return True
    if kind in {"button", "link", "navigation", "action"}:
        return True
    return bool(value.get("href") or value.get("clickPoint") or value.get("selector") or value.get("ref"))


def _runtime_output_event(output: InteractionOutput) -> dict[str, Any]:
    return {
        "type": output.type,
        "engine_output_seq": output.seq,
        "payload": _compact_value(dict(output.data or {})),
        "recorded_at": utcnow().isoformat(),
    }


def _scene_tool_registry(
    tool_registry: ToolRegistry,
    *,
    request: dict[str, Any],
    browser_semantics: dict[str, Any],
    workspace_pause_checker: Any | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tool_registry.tools.values():
        if not _is_allowed_scene_tool(tool):
            continue
        cloned = tool.clone()
        cloned.external_target = False
        cloned.metadata = {
            **dict(cloned.metadata or {}),
            "external_target": False,
            "requires_confirmation": False,
        }
        if cloned.name.startswith("browser_"):
            original_handler = cloned.handler

            def _browser_handler(
                arguments: dict[str, Any],
                *,
                _tool_name=cloned.name,
                _original_handler=original_handler,
            ) -> Any:
                precheck = _validate_scene_browser_tool_target(
                    tool_name=_tool_name,
                    arguments=arguments,
                    request=request,
                    browser_semantics=browser_semantics,
                )
                if precheck is not None:
                    return precheck
                result = _original_handler(arguments)
                _record_scene_browser_observation(
                    browser_semantics,
                    tool_name=_tool_name,
                    result=result,
                    request=request,
                )
                return _mask_scene_browser_target_mismatch(
                    tool_name=_tool_name,
                    result=result,
                    request=request,
                )

            cloned.handler = _browser_handler
        elif cloned.name == "hid_action":
            original_handler = cloned.handler

            def _handler(arguments: dict[str, Any], *, _original_handler=original_handler) -> Any:
                if callable(workspace_pause_checker) and workspace_pause_checker():
                    return {
                        "status": "blocked",
                        "error": "workspace_paused",
                        "message": "workspace is paused; new HID actions are blocked until the workspace is continued.",
                    }
                normalized = _normalize_scene_hid_action_arguments(
                    arguments,
                    request=request,
                    browser_semantics=browser_semantics,
                )
                precheck = _validate_scene_hid_action_target(
                    normalized,
                    request=request,
                )
                if precheck is not None:
                    return precheck
                precheck = _validate_scene_browser_hid_sequence(
                    normalized,
                    request=request,
                    browser_semantics=browser_semantics,
                )
                if precheck is not None:
                    return precheck
                arguments.clear()
                arguments.update(normalized)
                result = _original_handler(arguments)
                _record_scene_hid_action(
                    browser_semantics,
                    arguments=normalized,
                    request=request,
                    result=result,
                )
                return _mask_scene_hid_overlay_blocker(result)

            cloned.handler = _handler
        registry.register(cloned)
    return registry


def _is_allowed_scene_tool(tool: ToolDefinition) -> bool:
    if tool.name.startswith("browser_") or tool.name == "hid_action":
        return True
    return is_scene_context_tool(tool)


def _workspace_control_paused(session_factory: sessionmaker[Session]) -> bool:
    with session_factory() as session:
        state = session.get(AgentGlobalState, "singleton")
        if state is None:
            return False
        metadata = dict(state.state_metadata or {})
        control = metadata.get("workspace_control")
        control_state = str((control or {}).get("state") or "").strip().lower() if isinstance(control, dict) else ""
        return bool(state.autonomous_paused) or control_state == "paused"


def _validate_scene_browser_hid_sequence(
    arguments: dict[str, Any],
    *,
    request: dict[str, Any],
    browser_semantics: dict[str, Any],
) -> dict[str, Any] | None:
    if not _scene_hid_action_targets_browser(arguments):
        return None
    scope_key = _scene_sequence_scope_key(arguments, request=request)
    state = _scene_sequence_state(browser_semantics, scope_key)
    if state.get("pending_browser_observation_after_hid"):
        return _scene_sequence_blocker(
            scope_key=scope_key,
            reason="pending_browser_observation_after_hid",
            message="hid_action is blocked because the previous browser-targeted hid_action has not been followed by a browser observation inside this scene_context.",
        )
    if not state.get("last_browser_observation"):
        observed_state = _compatible_scene_observation_state(browser_semantics, scope_key)
        if observed_state is not None:
            state["last_browser_observation"] = observed_state.get("last_browser_observation")
        else:
            return _scene_sequence_blocker(
                scope_key=scope_key,
                reason="missing_prior_browser_observation",
                message="hid_action is blocked because scene_context requires browser observe/wait/query before browser-targeted HID actions.",
            )
    if not state.get("last_browser_observation"):
        return _scene_sequence_blocker(
            scope_key=scope_key,
            reason="missing_prior_browser_observation",
            message="hid_action is blocked because scene_context requires browser observe/wait/query before browser-targeted HID actions.",
        )
    return None


def _record_scene_browser_observation(
    browser_semantics: dict[str, Any],
    *,
    tool_name: str,
    result: Any,
    request: dict[str, Any],
) -> None:
    if tool_name not in _SCENE_BROWSER_PAGE_OBSERVATION_TOOL_NAMES:
        return
    if not _scene_observation_result_is_valid(result):
        return
    scope_key = _scene_sequence_scope_key({}, request=request, result=result)
    state = _scene_sequence_state(browser_semantics, scope_key)
    state["last_browser_observation"] = tool_name
    state["pending_browser_observation_after_hid"] = None
    _append_scene_sequence_audit(state, event="browser_observed", tool_name=tool_name, scope_key=scope_key)
    if isinstance(result, dict):
        result.setdefault("sequence_audit", _scene_sequence_audit_summary(scope_key, state))


def _record_scene_hid_action(
    browser_semantics: dict[str, Any],
    *,
    arguments: dict[str, Any],
    request: dict[str, Any],
    result: Any,
) -> None:
    if not _scene_hid_action_targets_browser(arguments):
        return
    scope_key = _scene_sequence_scope_key(arguments, request=request)
    state = _scene_sequence_state(browser_semantics, scope_key)
    state["pending_browser_observation_after_hid"] = "hid_action"
    _append_scene_sequence_audit(state, event="hid_action", tool_name="hid_action", scope_key=scope_key)
    if isinstance(result, dict):
        result.setdefault("sequence_audit", _scene_sequence_audit_summary(scope_key, state))


def _scene_hid_action_targets_browser(arguments: dict[str, Any]) -> bool:
    target = _as_dict(arguments.get("target"))
    context = _as_dict(arguments.get("context"))
    geometry = _as_dict(arguments.get("geometry"))
    primitives = list(arguments.get("primitives") or []) if isinstance(arguments.get("primitives"), list) else []
    if not any(isinstance(item, dict) and str(item.get("type") or "").strip() in _SCENE_HID_BROWSER_SEQUENCE_PRIMITIVE_TYPES for item in primitives):
        return False
    if str(target.get("host") or context.get("host") or "").strip():
        return True
    if str(target.get("url") or context.get("url") or "").strip():
        return True
    if target.get("tabId") is not None or target.get("tab_id") is not None:
        return True
    return str(geometry.get("coordSpace") or geometry.get("coord_space") or "").strip().lower() in {"viewport", "document"}


def _scene_sequence_scope_key(arguments: dict[str, Any], *, request: dict[str, Any], result: Any | None = None) -> str:
    target = _as_dict(arguments.get("target"))
    context = _as_dict(arguments.get("context"))
    request_context = _as_dict(request.get("context"))
    browser_target = _as_dict(request.get("browser_target"))
    run_id = _first_non_empty(request_context.get("run_id"), request_context.get("runId"), request.get("run_id"))
    episode_id = _first_non_empty(request_context.get("episode_id"), request_context.get("episodeId"), request.get("episode_id"))
    account = _first_non_empty(
        request_context.get("account"),
        request_context.get("site_account"),
        _as_dict(request.get("environment_requirements")).get("account"),
        _as_dict(request.get("environment_requirements")).get("site_account"),
    )
    host = _first_non_empty(
        target.get("host"),
        context.get("host"),
        _host_from_url(target.get("url")),
        _host_from_url(context.get("url")),
        browser_target.get("host"),
        _host_from_url(browser_target.get("url")),
        _browser_result_url(result) if isinstance(result, dict) else None,
    )
    return "|".join(
        (
            f"run={run_id or 'scene'}",
            f"episode={episode_id or 'scene'}",
            f"account={account or 'unspecified'}",
            f"host={_normalize_host_boundary(_host_from_url(host) or host) or 'unspecified'}",
        )
    )


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = _optional_string(value)
        if text:
            return text
    return None


def _scene_sequence_state(browser_semantics: dict[str, Any], scope_key: str) -> dict[str, Any]:
    states = browser_semantics.setdefault("sequence_state", {})
    return states.setdefault(scope_key, {"last_browser_observation": None, "pending_browser_observation_after_hid": None, "audit": []})


def _compatible_scene_observation_state(browser_semantics: dict[str, Any], scope_key: str) -> dict[str, Any] | None:
    host_suffix = scope_key.rsplit("|host=", 1)[-1]
    states = browser_semantics.get("sequence_state")
    if not isinstance(states, dict) or not host_suffix:
        return None
    for key, state in states.items():
        if not isinstance(state, dict):
            continue
        if not str(key).endswith(f"|host={host_suffix}"):
            continue
        if state.get("last_browser_observation") and not state.get("pending_browser_observation_after_hid"):
            return state
    return None


def _append_scene_sequence_audit(state: dict[str, Any], *, event: str, tool_name: str, scope_key: str, reason: str | None = None) -> None:
    audit = list(state.get("audit") or [])
    audit.append({"event": event, "tool_name": tool_name, "scope": scope_key, "reason": reason, "at": utcnow().isoformat()})
    state["audit"] = audit[-50:]


def _scene_sequence_audit_summary(scope_key: str, state: dict[str, Any]) -> dict[str, Any]:
    audit = list(state.get("audit") or [])
    return {
        "scope": scope_key,
        "last_browser_observation": state.get("last_browser_observation"),
        "pending_browser_observation_after_hid": state.get("pending_browser_observation_after_hid"),
        "event_count": len(audit),
        "last_events": audit[-5:],
    }


def _scene_sequence_blocker(*, scope_key: str, reason: str, message: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": "scene_browser_hid_sequence_blocked",
        "message": message,
        "sequence_audit": {
            "scope": scope_key,
            "reason": reason,
        },
    }


def _scene_observation_result_is_valid(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    if result.get("success") is False or result.get("ok") is False or bool(result.get("isError")):
        return False
    if _optional_string(result.get("error")):
        return False
    return str(result.get("status") or "").strip().lower() not in {"blocked", "error", "failed", "failure", "timeout"}


def _validate_scene_hid_action_target(
    arguments: dict[str, Any],
    *,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    allowed_host = _scene_target_host(request)
    if allowed_host is None:
        return None
    target = _as_dict(arguments.get("target"))
    context = _as_dict(arguments.get("context"))
    for candidate in (target.get("host"), context.get("host"), _host_from_url(context.get("url")), _host_from_url(target.get("url"))):
        host = _optional_string(candidate, max_length=255)
        if host and _normalize_host_boundary(host) != allowed_host:
            return {
                "success": False,
                "error": "scene_browser_host_not_allowed",
                "message": "hid_action target host is outside the scene single target host allowlist. Stop the current action and re-observe or request human handling.",
                "allowedHost": allowed_host,
                "requestedHost": host,
            }
    return None


def _mask_scene_hid_overlay_blocker(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    preflight = _as_dict(result.get("preflight")) or _as_dict(_as_dict(result.get("result")).get("preflight"))
    overlay = _as_dict(preflight.get("browserChromeOverlay"))
    policy = _as_dict(preflight.get("browserChromeOverlayPolicy"))
    status = str(overlay.get("status") or overlay.get("state") or policy.get("status") or policy.get("state") or "").strip().lower()
    decision = str(overlay.get("decision") or policy.get("decision") or "").strip().lower()
    if status not in {"blocked", "unknown"} and decision not in {"blocked", "unknown"}:
        return result
    return {
        **result,
        "success": False,
        "error": "scene_hid_overlay_blocked",
        "message": "hid_action preflight reported browserChromeOverlayPolicy as blocked or unknown. Stop the current action and re-observe, wait, or enter human handling.",
        "evidence": {
            "preflight": preflight,
            "browserChromeOverlay": overlay,
            "browserChromeOverlayPolicy": policy,
        },
    }


def _validate_scene_browser_tool_target(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    request: dict[str, Any],
    browser_semantics: dict[str, Any],
) -> dict[str, Any] | None:
    if tool_name not in _SCENE_BROWSER_READ_ONLY_TOOL_NAMES:
        return {
            "success": False,
            "error": "scene_browser_mutation_not_allowed",
            "message": (
                "Browser tools are read-only in autonomous scene execution. "
                "Use browser snapshot/query/wait/target-identification for observation and VirtualHID for mutating execution."
            ),
            "toolName": tool_name,
        }
    target_origin = _scene_target_origin(request)
    host_precheck = _validate_scene_browser_tool_host(arguments, request=request)
    if host_precheck is not None:
        return host_precheck
    if target_origin is None or tool_name not in _SCENE_BROWSER_PAGE_OBSERVATION_TOOL_NAMES:
        return None
    tab_id = _browser_tab_id_from_arguments(arguments)
    if tab_id is None:
        return None
    tab_info = dict((browser_semantics.get("tabs") or {}).get(tab_id) or {})
    tab_url = _optional_string(tab_info.get("url"))
    tab_host = _optional_string(tab_info.get("host"), max_length=255)
    if tab_url and _scene_url_matches_target_origin(tab_url, target_origin=target_origin):
        return None
    if not tab_url and tab_host and _scene_url_matches_target_origin(tab_host, target_origin=target_origin):
        return None
    if not tab_info or (not tab_url and not tab_host):
        return _scene_browser_tab_blocker(
            error="scene_browser_target_not_established",
            message=(
                "Browser tab target is not known for this scene. Call browser_list_tabs and then "
                "browser_snapshot on the allowlisted scene target before using query/get/debug/wait tools."
            ),
            target_origin=target_origin,
            tab_id=tab_id,
            tab_url=tab_url,
            tab_host=tab_host,
        )
    return {
        "success": False,
        "error": "scene_browser_target_mismatch",
        "message": (
            "Selected browser tab does not match the scene browser_target origin. Call browser_list_tabs "
            "and browser_snapshot to establish the allowlisted target before observing or acting."
        ),
        "targetOrigin": target_origin,
        "tab": {"tabId": tab_id, "url": tab_url, "host": tab_host},
    }


def _validate_scene_browser_tool_host(arguments: dict[str, Any], *, request: dict[str, Any]) -> dict[str, Any] | None:
    allowed_host = _scene_target_host(request)
    if allowed_host is None:
        return None
    for candidate in (arguments.get("url"), arguments.get("href"), arguments.get("sourceUrl"), arguments.get("source_url"), arguments.get("pattern")):
        host = _host_from_url(candidate)
        if host and _normalize_host_boundary(host) != allowed_host:
            return {
                "success": False,
                "error": "scene_browser_host_not_allowed",
                "message": "Browser tool target is outside the scene single target host allowlist.",
                "allowedHost": allowed_host,
                "requestedHost": host,
            }
    return None


def _browser_tab_id_from_arguments(arguments: dict[str, Any]) -> int | None:
    if "tabId" in arguments:
        return _optional_int(arguments.get("tabId"))
    return _optional_int(arguments.get("tab_id"))


def _scene_browser_tab_blocker(
    *,
    error: str,
    message: str,
    target_origin: str,
    tab_id: int,
    tab_url: str | None,
    tab_host: str | None,
) -> dict[str, Any]:
    return {
        "success": False,
        "error": error,
        "message": message,
        "targetOrigin": target_origin,
        "tab": {"tabId": tab_id, "url": tab_url, "host": tab_host},
    }


def _mask_scene_browser_target_mismatch(
    *,
    tool_name: str,
    result: Any,
    request: dict[str, Any],
) -> Any:
    if tool_name not in (_SCENE_BROWSER_PAGE_OBSERVATION_TOOL_NAMES | {"browser_get_active_tab", "browser_select_tab"}) or not isinstance(result, dict):
        return result
    if result.get("success") is False or result.get("ok") is False or _optional_string(result.get("error")):
        return result
    target_origin = _scene_target_origin(request)
    if target_origin is None:
        return result
    observed_url = _browser_result_url(result)
    if observed_url is None or _scene_url_matches_target_origin(observed_url, target_origin=target_origin):
        return result
    if tool_name == "browser_get_active_tab":
        return {
            **result,
            "success": True,
            "targetMatch": False,
            "sceneTarget": {"origin": target_origin},
            "observedUrl": observed_url,
            "message": (
                "Current active tab is outside the scene browser_target origin. "
                "This is not a terminal blocker; call browser_list_tabs to locate an allowlisted same-origin tab, "
                "then observe that tab or use VirtualHID to switch to it."
            ),
        }
    return {
        "success": False,
        "error": "scene_browser_target_mismatch",
        "message": "Observed browser target does not match the scene browser_target origin. Stop the current action and re-observe an allowlisted target or request human handling.",
        "targetOrigin": target_origin,
        "observedUrl": observed_url,
    }


def _browser_result_url(result: dict[str, Any]) -> str | None:
    for candidate in (
        _as_dict(result.get("snapshot")).get("url"),
        _as_dict(result.get("tab")).get("url"),
        _as_dict(result.get("target")).get("url"),
        result.get("url"),
    ):
        url = _optional_string(candidate)
        if url:
            return url
    return None


def _scene_target_origin(request: dict[str, Any]) -> str | None:
    browser_target = _as_dict(request.get("browser_target"))
    url_origin = _origin_from_url(browser_target.get("url"))
    if url_origin:
        return url_origin
    host = _optional_string(browser_target.get("host"), max_length=255)
    return host.lower() if host else None


def _scene_target_host(request: dict[str, Any]) -> str | None:
    browser_target = _as_dict(request.get("browser_target"))
    host = _host_from_url(browser_target.get("url")) or _optional_string(browser_target.get("host"), max_length=255)
    return _normalize_host_boundary(host) if host else None


def _scene_url_matches_target_origin(value: Any, *, target_origin: str) -> bool:
    normalized_target = str(target_origin or "").strip().lower()
    observed_origin = _origin_from_url(value)
    if "://" in normalized_target:
        return observed_origin == normalized_target
    observed_host = _host_from_url(value) or _optional_string(value, max_length=255)
    return _normalize_host_boundary(observed_host) == _normalize_host_boundary(normalized_target)


def _normalize_host_boundary(value: Any) -> str | None:
    text = _optional_string(value, max_length=255)
    if not text:
        return None
    return text.lower()


def _normalize_scene_hid_action_arguments(
    arguments: dict[str, Any],
    *,
    request: dict[str, Any],
    browser_semantics: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(arguments or {})
    target = _as_dict(normalized.get("target"))
    context = _as_dict(normalized.get("context"))
    geometry = _as_dict(normalized.get("geometry"))
    tab_id = _optional_int(target.get("tabId") or target.get("tab_id"))
    host = _resolve_web_host(
        context=context,
        target=target,
        request=request,
        browser_semantics=browser_semantics,
        tab_id=tab_id,
    )
    url = _resolve_web_url(
        context=context,
        target=target,
        request=request,
        browser_semantics=browser_semantics,
        tab_id=tab_id,
    )

    if host:
        if target or tab_id is not None:
            target["host"] = host
            target.setdefault("bundleId", "com.google.Chrome")
            tab_info = dict((browser_semantics.get("tabs") or {}).get(tab_id) or {}) if tab_id is not None else {}
            window_id = _optional_int(target.get("windowId") or target.get("window_id") or tab_info.get("windowId") or tab_info.get("window_id"))
            if window_id is not None:
                target.setdefault("windowId", window_id)
            window_bounds = _resolve_browser_window_bounds(target=target, context=context, tab_info=tab_info)
            if window_bounds:
                target.setdefault("browserWindowBounds", window_bounds)
            window_title = _resolve_web_window_title(
                context=context,
                target=target,
                request=request,
                browser_semantics=browser_semantics,
                tab_id=tab_id,
                desired_host=host,
            )
            if window_title:
                target.setdefault("windowTitle", window_title)
            normalized["target"] = target
        context["host"] = host
        if url:
            context.setdefault("url", url)
        normalized["context"] = context

    if "primitives" not in normalized:
        primitive = _primitive_from_legacy_point(normalized)
        if primitive:
            normalized["primitives"] = [primitive]
            normalized.pop("x", None)
            normalized.pop("y", None)
            normalized.pop("button", None)

    if geometry or (
        _scene_hid_action_targets_browser(normalized)
        and _browser_viewport_has_size(browser_semantics=browser_semantics, tab_id=tab_id)
    ):
        _apply_browser_viewport_geometry(geometry, browser_semantics=browser_semantics, tab_id=tab_id)
        normalized["geometry"] = geometry
    _strip_scene_hid_humanization_overrides(normalized)
    _normalize_scene_hid_post_mode(normalized)

    return normalized


def _strip_scene_hid_humanization_overrides(arguments: dict[str, Any]) -> None:
    options = arguments.get("options")
    if isinstance(options, dict):
        options.pop("behaviorMode", None)
        options.pop("behavior_mode", None)
        options.pop("profile", None)
        arguments["options"] = options
    primitives = arguments.get("primitives")
    if isinstance(primitives, list):
        for primitive in primitives:
            if isinstance(primitive, dict):
                primitive.pop("profile", None)


def _normalize_scene_hid_post_mode(arguments: dict[str, Any]) -> None:
    if not _scene_hid_action_targets_browser(arguments):
        return
    primitives = [item for item in list(arguments.get("primitives") or []) if isinstance(item, dict)]
    if not any(str(item.get("type") or "").strip() in {"click", "drag", "type", "pasteText", "key"} for item in primitives):
        return
    options = _as_dict(arguments.get("options"))
    requested = str(options.get("postMode") or options.get("post_mode") or "").strip().lower()
    if requested in {"", "global"}:
        options.pop("post_mode", None)
        options["postMode"] = "auto"
        arguments["options"] = options


def _initial_browser_semantics(request: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {"tabs": {}}
    browser_target = dict(request.get("browser_target") or {})
    url = _optional_string(browser_target.get("url"))
    host = _optional_string(browser_target.get("host")) or _host_from_url(url)
    tab_id = _optional_int(browser_target.get("tab_id") or browser_target.get("tabId"))
    if host:
        state["last_host"] = host
    if url:
        state["last_url"] = url
    if tab_id is not None and (host or url):
        state["tabs"][tab_id] = {"tabId": tab_id, "host": host, "url": url}
    return state


def _remember_browser_semantics(browser_semantics: dict[str, Any], *, tool_name: str, output: Any) -> None:
    if not str(tool_name or "").startswith("browser_") or not isinstance(output, dict):
        return
    for item in _browser_tabs_from_output(output):
        _remember_browser_tab(browser_semantics, item)
    snapshot = output.get("snapshot")
    if isinstance(snapshot, dict):
        tab_id = _optional_int(output.get("tabId") or output.get("tab_id") or _as_dict(output.get("target")).get("tabId"))
        _remember_browser_tab(
            browser_semantics,
            {
                "id": tab_id,
                "url": snapshot.get("url"),
                "title": snapshot.get("title"),
                "active": True,
                "viewport": snapshot.get("viewport"),
            },
        )
    target = _as_dict(output.get("target"))
    if target:
        _remember_browser_tab(browser_semantics, target)


def _browser_tabs_from_output(output: dict[str, Any]) -> list[dict[str, Any]]:
    tabs: list[dict[str, Any]] = []
    tab = output.get("tab")
    if isinstance(tab, dict):
        tabs.append(tab)
    tabs.extend(item for item in list(output.get("tabs") or []) if isinstance(item, dict))
    if any(key in output for key in ("id", "tabId", "url", "title", "active", "windowId")):
        tabs.append(output)
    return tabs


def _remember_browser_tab(browser_semantics: dict[str, Any], tab: dict[str, Any]) -> None:
    tab_id = _optional_int(tab.get("tabId") or tab.get("tab_id") or tab.get("id"))
    url = _optional_string(tab.get("url"))
    host = _optional_string(tab.get("host")) or _host_from_url(url)
    viewport = _as_dict(tab.get("viewport"))
    window = _as_dict(tab.get("window"))
    window_bounds = _browser_window_bounds_from_window(window) or _browser_window_bounds_from_viewport(viewport)
    if host:
        browser_semantics["last_host"] = host
    if url:
        browser_semantics["last_url"] = url
    title = _optional_string(tab.get("title"))
    window_title = _optional_string(tab.get("windowTitle") or tab.get("window_title") or title)
    if title:
        browser_semantics["last_title"] = title
        browser_semantics["last_title_host"] = host
    if window_title:
        browser_semantics["last_window_title"] = window_title
        browser_semantics["last_window_title_host"] = host
    if viewport:
        browser_semantics["last_viewport"] = viewport
    if window_bounds:
        browser_semantics["last_window_bounds"] = window_bounds
    if tab_id is None:
        return
    tabs = browser_semantics.setdefault("tabs", {})
    current = dict(tabs.get(tab_id) or {})
    current.update(
        {
            key: value
            for key, value in {
                "tabId": tab_id,
                "url": url,
                "host": host,
                "title": title,
                "windowTitle": window_title,
                "windowId": _optional_int(tab.get("windowId") or tab.get("window_id")),
                "window": window or None,
                "browserWindowBounds": window_bounds,
                "active": bool(tab.get("active")),
                "viewport": viewport or None,
            }.items()
            if value not in (None, "", {})
        }
    )
    tabs[tab_id] = current
    if bool(tab.get("active")):
        browser_semantics["active_tab_id"] = tab_id


def _resolve_web_host(
    *,
    context: dict[str, Any],
    target: dict[str, Any],
    request: dict[str, Any],
    browser_semantics: dict[str, Any],
    tab_id: int | None,
) -> str | None:
    browser_target = dict(request.get("browser_target") or {})
    tab_info = dict((browser_semantics.get("tabs") or {}).get(tab_id) or {}) if tab_id is not None else {}
    allowed_host = _scene_target_host(request)
    for candidate in (context.get("host"), target.get("host")):
        host = _optional_string(candidate, max_length=255)
        if not host:
            continue
        if _can_coerce_to_scene_host(host, allowed_host):
            return allowed_host
        return host
    candidates = [
        allowed_host,
        browser_target.get("host"),
        tab_info.get("host"),
        _host_from_url(context.get("url")),
        _host_from_url(target.get("url")),
        _host_from_url(browser_target.get("url")),
        _host_from_url(tab_info.get("url")),
        browser_semantics.get("last_host"),
    ]
    for candidate in candidates:
        host = _optional_string(candidate, max_length=255)
        if host:
            return host
    return None


def _resolve_browser_window_bounds(*, target: dict[str, Any], context: dict[str, Any], tab_info: dict[str, Any]) -> dict[str, Any] | None:
    for candidate in (
        target.get("browserWindowBounds"),
        target.get("browser_window_bounds"),
        target.get("windowBounds"),
        target.get("window_bounds"),
        context.get("browserWindowBounds"),
        context.get("browser_window_bounds"),
        tab_info.get("browserWindowBounds"),
        tab_info.get("browser_window_bounds"),
        tab_info.get("windowBounds"),
        tab_info.get("window_bounds"),
        _browser_window_bounds_from_window(_as_dict(tab_info.get("window"))),
    ):
        bounds = _normalize_browser_window_bounds(candidate)
        if bounds:
            return bounds
    return None


def _browser_window_bounds_from_window(window: dict[str, Any]) -> dict[str, Any] | None:
    if not window:
        return None
    return _normalize_browser_window_bounds(
        {
            "x": window.get("left"),
            "y": window.get("top"),
            "width": window.get("width"),
            "height": window.get("height"),
        }
    )


def _browser_window_bounds_from_viewport(viewport: dict[str, Any]) -> dict[str, Any] | None:
    if not viewport:
        return None
    return _normalize_browser_window_bounds(
        {
            "x": viewport.get("screenX"),
            "y": viewport.get("screenY"),
            "width": viewport.get("outerWidth"),
            "height": viewport.get("outerHeight"),
        }
    )


def _normalize_browser_window_bounds(value: Any) -> dict[str, Any] | None:
    bounds = _as_dict(value)
    if not bounds:
        return None
    x = _optional_number(bounds.get("x") if bounds.get("x") is not None else bounds.get("left"))
    y = _optional_number(bounds.get("y") if bounds.get("y") is not None else bounds.get("top"))
    width = _optional_number(bounds.get("width"))
    height = _optional_number(bounds.get("height"))
    if x is None or y is None or width is None or height is None or width <= 0 or height <= 0:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _can_coerce_to_scene_host(candidate: Any, allowed_host: str | None) -> bool:
    normalized_candidate = _normalize_host_boundary(_host_from_url(candidate) or candidate)
    normalized_allowed = _normalize_host_boundary(_host_from_url(allowed_host) or allowed_host)
    if not normalized_candidate or not normalized_allowed:
        return False
    if normalized_candidate == normalized_allowed:
        return True
    candidate_name = _hostname_part(normalized_candidate)
    allowed_name = _hostname_part(normalized_allowed)
    return bool(
        candidate_name
        and allowed_name
        and candidate_name == allowed_name
        and not _host_has_explicit_port(normalized_candidate)
        and _host_has_explicit_port(normalized_allowed)
    )


def _hostname_part(value: Any) -> str | None:
    host = _normalize_host_boundary(_host_from_url(value) or value)
    if not host:
        return None
    try:
        parsed = urlparse(f"//{host}")
        return parsed.hostname.lower() if parsed.hostname else None
    except ValueError:
        return host.split(":", 1)[0].lower() if ":" in host else host.lower()


def _host_has_explicit_port(value: Any) -> bool:
    host = _normalize_host_boundary(_host_from_url(value) or value)
    if not host:
        return False
    try:
        parsed = urlparse(f"//{host}")
        return parsed.port is not None
    except ValueError:
        return False


def _resolve_web_url(
    *,
    context: dict[str, Any],
    target: dict[str, Any],
    request: dict[str, Any],
    browser_semantics: dict[str, Any],
    tab_id: int | None,
) -> str | None:
    browser_target = dict(request.get("browser_target") or {})
    tab_info = dict((browser_semantics.get("tabs") or {}).get(tab_id) or {}) if tab_id is not None else {}
    for candidate in (
        context.get("url"),
        target.get("url"),
        browser_target.get("url"),
        tab_info.get("url"),
        browser_semantics.get("last_url"),
    ):
        url = _optional_string(candidate)
        if url:
            return url
    return None


def _resolve_web_window_title(
    *,
    context: dict[str, Any],
    target: dict[str, Any],
    request: dict[str, Any],
    browser_semantics: dict[str, Any],
    tab_id: int | None,
    desired_host: str | None,
) -> str | None:
    browser_target = dict(request.get("browser_target") or {})
    tab_info = dict((browser_semantics.get("tabs") or {}).get(tab_id) or {}) if tab_id is not None else {}
    candidates = (
        (target.get("windowTitle"), target),
        (target.get("window_title"), target),
        (context.get("windowTitle"), context),
        (context.get("window_title"), context),
        (browser_target.get("windowTitle"), browser_target),
        (browser_target.get("window_title"), browser_target),
        (tab_info.get("windowTitle"), tab_info),
        (tab_info.get("window_title"), tab_info),
        (tab_info.get("title"), tab_info),
        (browser_semantics.get("last_window_title"), {"host": browser_semantics.get("last_window_title_host")}),
        (browser_semantics.get("last_title"), {"host": browser_semantics.get("last_title_host")}),
    )
    for candidate, source in candidates:
        if not _browser_title_source_matches_host(source, desired_host=desired_host):
            continue
        title = _optional_string(candidate, max_length=255)
        if title:
            return title
    return None


def _browser_title_source_matches_host(source: dict[str, Any], *, desired_host: str | None) -> bool:
    normalized_desired = _normalize_host_boundary(_host_from_url(desired_host) or desired_host)
    if not normalized_desired:
        return True
    source_host = _normalize_host_boundary(_host_from_url(source.get("host")) or source.get("host") or _host_from_url(source.get("url")))
    return not source_host or source_host == normalized_desired


def _primitive_from_legacy_point(arguments: dict[str, Any]) -> dict[str, Any] | None:
    x = _optional_number(arguments.get("x"))
    y = _optional_number(arguments.get("y"))
    if x is None or y is None:
        return None
    primitive = {
        "type": "click",
        "at": {"x": x, "y": y},
        "button": _optional_string(arguments.get("button"), max_length=32) or "left",
    }
    profile = _as_dict(arguments.get("profile"))
    if profile:
        primitive["profile"] = profile
    return primitive


def _apply_browser_viewport_geometry(
    geometry: dict[str, Any],
    *,
    browser_semantics: dict[str, Any],
    tab_id: int | None,
) -> None:
    coord_space = str(geometry.get("coordSpace") or geometry.get("coord_space") or "viewport").strip().lower()
    if coord_space == "screen" or geometry.get("viewportInScreen") or geometry.get("viewport_in_screen"):
        return
    viewport = _browser_viewport_from_semantics(browser_semantics=browser_semantics, tab_id=tab_id)
    width = _optional_number(viewport.get("innerWidth"))
    height = _optional_number(viewport.get("innerHeight"))
    geometry.setdefault("scrollOffset", {"x": _optional_number(viewport.get("scrollX")) or 0, "y": _optional_number(viewport.get("scrollY")) or 0})
    if width is not None and height is not None:
        viewport_size = _as_dict(geometry.get("viewportSize") or geometry.get("viewport_size"))
        geometry["viewportSize"] = {
            "x": _optional_number(viewport_size.get("x")) or 0,
            "y": _optional_number(viewport_size.get("y")) or 0,
            "width": _optional_number(viewport_size.get("width")) or width,
            "height": _optional_number(viewport_size.get("height")) or height,
        }
        geometry.pop("viewport_size", None)
    visual_viewport = _as_dict(viewport.get("visualViewport"))
    if "pageScale" not in geometry and "page_scale" not in geometry:
        geometry["pageScale"] = _optional_number(visual_viewport.get("scale")) or 1


def _browser_viewport_from_semantics(*, browser_semantics: dict[str, Any], tab_id: int | None) -> dict[str, Any]:
    tab_info = dict((browser_semantics.get("tabs") or {}).get(tab_id) or {}) if tab_id is not None else {}
    return _as_dict(tab_info.get("viewport")) or _as_dict(browser_semantics.get("last_viewport"))


def _browser_viewport_has_size(*, browser_semantics: dict[str, Any], tab_id: int | None) -> bool:
    viewport = _browser_viewport_from_semantics(browser_semantics=browser_semantics, tab_id=tab_id)
    return _optional_number(viewport.get("innerWidth")) is not None and _optional_number(viewport.get("innerHeight")) is not None


def _snapshot_candidates(*, tool_name: str, output: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(output, dict):
        normalized_output = _normalize_environment_candidate(output, default_source=tool_name or "scene_tool")
        if normalized_output is not None:
            candidates.append(normalized_output)
        nested_snapshot = output.get("snapshot")
        if isinstance(nested_snapshot, dict):
            normalized_snapshot = _normalize_environment_candidate(
                nested_snapshot,
                default_source=tool_name or "scene_tool",
            )
            if normalized_snapshot is not None:
                candidates.append(normalized_snapshot)
        tab = output.get("tab")
        if isinstance(tab, dict) and (tab.get("url") or tab.get("title")):
            candidates.append(
                {
                    "source": tool_name or "browser_tab",
                    "status": "observed",
                    "resource_locator": tab.get("url"),
                    "display_label": tab.get("title") or tab.get("url"),
                    "environment_kind": "browser_tab",
                    "runtime_metadata": {"tab": _compact_value(tab)},
                }
            )
        tabs = [item for item in list(output.get("tabs") or []) if isinstance(item, dict)]
        active_tabs = [item for item in tabs if item.get("active")] or tabs[:1]
        for item in active_tabs[:2]:
            candidates.append(
                {
                    "source": tool_name or "browser_tab",
                    "status": "observed",
                    "resource_locator": item.get("url"),
                    "display_label": item.get("title") or item.get("url"),
                    "environment_kind": "browser_tab",
                    "runtime_metadata": {"tab": _compact_value(item)},
                }
            )
        frames = [item for item in list(output.get("frames") or []) if isinstance(item, dict)]
        for item in frames[:2]:
            candidates.append(
                {
                    "source": tool_name or "browser_frame",
                    "status": "observed",
                    "resource_locator": item.get("url"),
                    "display_label": item.get("title") or item.get("url"),
                    "environment_kind": "browser_frame",
                    "runtime_metadata": {"frame": _compact_value(item)},
                }
            )
    return [
        candidate
        for candidate in candidates
        if any(
            candidate.get(key)
            for key in (
                "resource_locator",
                "display_label",
                "environment_kind",
                "observed_entities",
                "action_hints",
                "runtime_metadata",
            )
        )
    ]


def _collect_blockers(
    outcome: AgentTurnOutcome,
    events: list[dict[str, Any]],
    *,
    ignore_recovered: bool = True,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    recovered_tools = _recovered_error_tools(events) if ignore_recovered else set()
    for event in events:
        event_type = str(event.get("type") or "")
        payload = _as_dict(event.get("payload"))
        if event_type == "permission_requested":
            blockers.append(
                {
                    "kind": "tool_blocked",
                    "tool_name": payload.get("tool_name"),
                    "message": str(payload.get("reason") or "tool blocked"),
                    "severity": payload.get("severity"),
                }
            )
        if event_type == "tool_event" and payload.get("kind") == "tool_result_ready" and (
            bool(payload.get("is_error")) or not _tool_result_content_succeeded(payload.get("content"))
        ):
            tool_name = str(payload.get("tool_name") or "")
            if tool_name in recovered_tools:
                continue
            blockers.append(
                {
                    "kind": "tool_error",
                    "tool_name": payload.get("tool_name"),
                    "message": str(payload.get("content") or "tool execution failed"),
                }
            )
    if outcome.gate_signal == "budget_exhausted":
        blockers.append({"kind": "budget_exhausted", "message": "scene context reached explicit safety budget"})
    if outcome.status == "escalate":
        blockers.append({"kind": "escalate", "message": outcome.escalate_reason or "scene context escalated"})
    return blockers


def _recovered_error_tools(events: list[dict[str, Any]]) -> set[str]:
    failed_at: dict[str, int] = {}
    recovered: set[str] = set()
    for event in events:
        if str(event.get("type") or "") != "tool_event":
            continue
        payload = _as_dict(event.get("payload"))
        if payload.get("kind") != "tool_result_ready":
            continue
        tool_name = str(payload.get("tool_name") or "")
        if not tool_name:
            continue
        seq = _safe_int(event.get("engine_output_seq"))
        if bool(payload.get("is_error")) or not _tool_result_content_succeeded(payload.get("content")):
            failed_at[tool_name] = seq
        elif tool_name in failed_at and seq > failed_at[tool_name] and _tool_result_content_succeeded(payload.get("content")):
            recovered.add(tool_name)
    return recovered


def _should_continue(outcome: AgentTurnOutcome) -> bool:
    return outcome.status == "continue" and outcome.gate_signal == "continue"


def _public_status(
    outcome: AgentTurnOutcome,
    blockers: list[dict[str, Any]],
    *,
    result_data: dict[str, Any] | None = None,
) -> str:
    result_status = str((_as_dict(result_data).get("status") or "")).strip().lower() or _scene_result_status(outcome)
    if result_status in {"completed", "complete", "success", "succeeded"}:
        if blockers:
            return "blocked"
        return "completed"
    if result_status in {"partial", "incomplete", "continuable", "continue", "pending"}:
        if blockers:
            return "blocked"
        return "incomplete"
    if result_status in {"blocked", "wait_human", "waiting_human", "paused"} or result_status.startswith("blocked_"):
        return "blocked"
    if result_status in {"error", "failed", "failure", "fail"} or result_status.startswith("failed_") or result_status.startswith("failure_"):
        return "error"
    if blockers:
        return "blocked"
    if outcome.status == "error":
        return "error"
    if outcome.status == "cancelled":
        return "blocked"
    if outcome.status == "complete":
        return "completed"
    if outcome.status in {"wait_human", "escalate"}:
        return "blocked"
    return "incomplete"


def _scene_result_status(outcome: AgentTurnOutcome) -> str:
    result_status = str((outcome.result_data or {}).get("status") or "").strip().lower()
    if result_status:
        return result_status
    final_status = str((_scene_final_control_payload(outcome) or {}).get("status") or "").strip().lower()
    if _is_scene_non_success_status(final_status):
        return final_status
    return ""


def _stored_status(public_status: str) -> str:
    return {
        "completed": "completed",
        "blocked": "blocked",
        "error": "failed",
        "incomplete": "interrupted",
    }.get(public_status, "interrupted")


def _public_summary(outcome: AgentTurnOutcome, blockers: list[dict[str, Any]]) -> str:
    final_payload = _scene_final_control_payload(outcome)
    final_status = str((final_payload or {}).get("status") or "").strip().lower()
    if _is_scene_non_success_status(final_status):
        final_summary = str((final_payload or {}).get("summary") or (final_payload or {}).get("message") or "").strip()
        if final_summary:
            return final_summary
    final_output = str(outcome.final_output or "").strip()
    if final_output:
        return final_output
    result_summary = str((outcome.result_data or {}).get("summary") or (outcome.result_data or {}).get("message") or "").strip()
    if result_summary:
        return result_summary
    if blockers:
        return str(blockers[0].get("message") or "scene context reported a blocker")
    if outcome.gate_signal == "budget_exhausted":
        return "scene context reached explicit safety budget before producing a terminal result"
    return "scene context finished without a terminal summary"


def _scene_result_data(outcome: AgentTurnOutcome, *, output_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(outcome.result_data, dict) and outcome.result_data:
        return dict(outcome.result_data)
    contract = _as_dict(output_contract)
    if contract.get("result_data_required"):
        final_payload = _scene_final_control_payload(outcome)
        if isinstance(final_payload, dict) and final_payload:
            return dict(final_payload)
    return {}


def _normalize_scene_result_contract_data(
    result_data: dict[str, Any],
    output_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    contract = _as_dict(output_contract)
    if not contract.get("result_data_required") or not result_data:
        return result_data
    required_fields = {
        str(item).strip()
        for item in contract.get("required_fields") or []
        if str(item or "").strip()
    }
    if not required_fields:
        return result_data

    normalized = dict(result_data)
    summary = _as_dict(normalized.get("summary"))
    result = _as_dict(normalized.get("result"))
    sources = [normalized, summary, result]
    synthesized: list[str] = []

    def first_list(*keys: str) -> list[Any]:
        for source in sources:
            for key in keys:
                value = source.get(key)
                if isinstance(value, list):
                    return list(value)
        return []

    completed_details = first_list(
        "completed_job_details",
        "completedJobDetails",
        "job_details",
        "jobDetails",
        "active_recruiting_jobs",
        "activeRecruitingJobs",
        "verified_jobs",
        "verifiedJobs",
        "details",
    )
    if "completed_job_details" in required_fields and not normalized.get("completed_job_details") and completed_details:
        normalized["completed_job_details"] = completed_details
        synthesized.append("completed_job_details")

    observed_jobs = first_list(
        "observed_jobs",
        "observedJobs",
        "discovered_jobs",
        "discoveredJobs",
        "jobs_reviewed",
        "jobsReviewed",
        "active_recruiting_jobs",
        "activeRecruitingJobs",
        "active_jobs",
        "activeJobs",
    )
    if not observed_jobs and isinstance(normalized.get("completed_job_details"), list):
        observed_jobs = [
            {
                key: item.get(key)
                for key in ("title", "job_title", "external_id", "external_url", "status")
                if isinstance(item, dict) and item.get(key) not in (None, "", [], {})
            }
            for item in normalized["completed_job_details"]
            if isinstance(item, dict)
        ]
        observed_jobs = [item for item in observed_jobs if item]
    if "observed_jobs" in required_fields and not normalized.get("observed_jobs") and observed_jobs:
        normalized["observed_jobs"] = observed_jobs
        synthesized.append("observed_jobs")

    if "inactive_or_closed_jobs" in required_fields and "inactive_or_closed_jobs" not in normalized:
        normalized["inactive_or_closed_jobs"] = first_list(
            "inactive_or_closed_jobs",
            "inactiveOrClosedJobs",
            "closed_jobs",
            "closedJobs",
            "inactive_jobs",
            "inactiveJobs",
        )
    if "blockers" in required_fields and "blockers" not in normalized:
        normalized["blockers"] = first_list("blockers")
    if "limitations" in required_fields and "limitations" not in normalized:
        normalized["limitations"] = first_list("limitations")
    if "activation_entry_observed" in required_fields and "activation_entry_observed" not in normalized:
        activation = None
        for source in sources:
            if "activation_entry_observed" in source:
                activation = source.get("activation_entry_observed")
                break
            if "activationEntryObserved" in source:
                activation = source.get("activationEntryObserved")
                break
        normalized["activation_entry_observed"] = bool(activation)

    evidence = first_list("evidence", "evidence_refs", "evidenceRefs", "observations", "notes")
    if not evidence:
        for source in sources:
            value = source.get("evidence") or source.get("blocker") or source.get("limitation")
            if str(value or "").strip():
                evidence = [str(value).strip()]
                break
    if not evidence and normalized.get("completed_job_details"):
        evidence = ["scene returned structured job detail data"]
    if "evidence" in required_fields and not normalized.get("evidence") and evidence:
        normalized["evidence"] = evidence
        synthesized.append("evidence")

    status = str(normalized.get("status") or "").strip().lower()
    if synthesized and status in {"completed", "complete", "success", "succeeded"}:
        normalized["reported_status"] = normalized.get("status")
        normalized["status"] = "partial"
        normalized["contract_normalization"] = {
            "status": "applied",
            "synthesized_fields": synthesized,
            "reason": "scene returned recognizable business fields with non-canonical contract keys",
        }
    return normalized


def _scene_result_contract_blockers(result_data: dict[str, Any], output_contract: dict[str, Any] | None) -> list[dict[str, Any]]:
    contract = _as_dict(output_contract)
    if not contract.get("result_data_required"):
        return []
    required_fields = [
        str(item).strip()
        for item in contract.get("required_fields") or []
        if str(item or "").strip()
    ]
    missing_fields = [
        field
        for field in required_fields
        if field not in result_data or result_data.get(field) in (None, "", {})
    ]
    blockers: list[dict[str, Any]] = []
    if missing_fields:
        blockers.append(
            {
                "kind": "output_contract_incomplete",
                "message": "scene result_data is missing required output_contract fields",
                "missing_fields": missing_fields,
            }
        )
    status = str(result_data.get("status") or "").strip().lower()
    completed_details = result_data.get("completed_job_details")
    if "completed_job_details" in required_fields and status in {"completed", "complete", "success", "succeeded"}:
        if not isinstance(completed_details, list) or not completed_details:
            blockers.append(
                {
                    "kind": "output_contract_incomplete",
                    "message": "scene cannot be completed without completed_job_details",
                    "missing_fields": ["completed_job_details"],
                }
            )
    return blockers


def _align_result_data_status(result_data: dict[str, Any], public_status: str) -> dict[str, Any]:
    if public_status == "completed" or not result_data:
        return result_data
    reported_status = str(result_data.get("status") or "").strip().lower()
    if reported_status in {"completed", "complete", "success", "succeeded"}:
        return {
            **result_data,
            "reported_status": result_data.get("status"),
            "status": public_status,
        }
    return result_data


def _scene_final_control_payload(outcome: AgentTurnOutcome) -> dict[str, Any] | None:
    return _parse_scene_final_output_json(outcome.final_output)


def _is_scene_non_success_status(value: str) -> bool:
    terminal_values = {"blocked", "wait_human", "waiting_human", "paused", "error", "failed", "failure", "fail"}
    return value in terminal_values or value.startswith(("blocked_", "failed_", "failure_"))


def _parse_scene_final_output_json(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _scene_result_artifacts(result_data: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for key in ("artifact", "resume_artifact", "download_artifact", "resume_download_record", "download_attribution", "browser_download"):
        candidate = _as_dict(result_data.get(key))
        artifact = _normalize_scene_result_artifact(candidate, source_key=key)
        if artifact:
            artifacts.append(artifact)
    return artifacts


def _normalize_scene_result_artifact(payload: dict[str, Any], *, source_key: str) -> dict[str, Any]:
    browser_filename = _optional_string(payload.get("filename"))
    file_path = _optional_string(
        payload.get("file_path")
        or payload.get("filePath")
        or payload.get("path")
        or payload.get("local_path")
        or payload.get("localPath")
        or (browser_filename if _looks_like_local_path(browser_filename) else None)
    )
    if not file_path:
        return {}
    state = _optional_string(payload.get("state") or payload.get("status"), max_length=64)
    verified = bool(
        payload.get("verified")
        or payload.get("pdf_verified")
        or payload.get("format_verified")
        or payload.get("exists")
        or (state and state.lower() in {"complete", "completed", "verified"})
    )
    return {
        key: value
        for key, value in {
            "kind": "local_artifact",
            "source_key": source_key,
            "file_path": file_path,
            "file_name": _optional_string(
                payload.get("file_name") or payload.get("fileName") or payload.get("name"),
                max_length=255,
            ),
            "artifact_type": _optional_string(payload.get("artifact_type") or payload.get("artifactType"), max_length=64),
            "format": _optional_string(payload.get("format") or payload.get("mime") or payload.get("mime_type"), max_length=128),
            "state": state,
            "verified": verified,
            "source_url": _optional_string(payload.get("source_url") or payload.get("sourceUrl") or payload.get("url")),
            "final_url": _optional_string(payload.get("final_url") or payload.get("finalUrl")),
            "referrer": _optional_string(payload.get("referrer")),
        }.items()
        if value not in (None, "", [])
    }


def _looks_like_local_path(value: str | None) -> bool:
    if not value:
        return False
    return value.startswith(("/", "~/")) or ":\\" in value or value.startswith("\\\\")


def _available_mcp_names(tool_registry: ToolRegistry) -> list[str]:
    names = {
        str(tool.metadata.get("mcp_server_key") or "").strip()
        for tool in tool_registry.tools.values()
        if str(tool.metadata.get("mcp_server_key") or "").strip()
    }
    return sorted(names)


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, str):
        limit = 320 if depth < 2 else 180
        return value if len(value) <= limit else f"{value[: limit - 3]}..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        items = [_compact_value(item, depth=depth + 1) for item in value[:4]]
        if len(value) > 4:
            items.append(f"... {len(value) - 4} more items omitted")
        return items
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for raw_key in list(value.keys())[:12]:
            key = str(raw_key)
            compact[key] = _compact_value(value[raw_key], depth=depth + 1)
        if len(value) > 12:
            compact["_truncated_keys"] = len(value) - 12
        return compact
    return str(value)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _merge_policy_dicts(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update({str(key): item for key, item in value.items() if str(key).strip()})
    return merged


def _string_list(value: Any) -> list[str]:
    items: list[str] = []
    raw_values = list(value or []) if isinstance(value, list) else ([value] if value not in (None, "") else [])
    for raw in raw_values:
        text = str(raw).strip()
        if text and text not in items:
            items.append(text)
    return items


def _dedupe_strings(values: list[str]) -> list[str]:
    items: list[str] = []
    for raw in values:
        text = str(raw).strip()
        if text and text not in items:
            items.append(text)
    return items


def _optional_string(value: Any, *, max_length: int = 2048) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:max_length]


def _host_from_url(value: Any) -> str | None:
    url = _optional_string(value)
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed.netloc.rsplit("@", 1)[-1].lower()[:255]


def _origin_from_url(value: Any) -> str | None:
    url = _optional_string(value)
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = parsed.netloc.rsplit("@", 1)[-1].lower()
    return f"{parsed.scheme.lower()}://{host}"[:2048]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [_as_dict(item) for item in list(value or []) if isinstance(item, dict)][:8]


def _scene_capabilities(value: Any) -> set[str]:
    capabilities = {str(item).strip().lower().replace("-", "_") for item in list(value or []) if str(item).strip()}
    if capabilities & {"hid", "virtual_hid", "virtualhid", "computer_hid", "computer_write"}:
        capabilities.add("computer")
    if capabilities & {"browser_mcp", "browser_read", "document"}:
        capabilities.add("browser")
    return capabilities


def _normalize_preferred_scene_capabilities(value: Any) -> list[str]:
    capabilities = _scene_capabilities(value)
    ordered: list[str] = []
    if "browser" in capabilities:
        ordered.append("browser")
    if "computer" in capabilities:
        ordered.append("computer")
    for item in _string_list(value):
        normalized = item.strip().lower().replace("-", "_")
        if normalized in {"browser", "browser_mcp", "browser_read", "document", "computer", "hid", "virtual_hid", "virtualhid", "computer_hid", "computer_write"}:
            continue
        if item not in ordered:
            ordered.append(item)
    return ordered


def _scene_execution_contract(request: dict[str, Any]) -> dict[str, Any]:
    capabilities = _scene_capabilities(request["preferred_capabilities"])
    if "browser" in capabilities and "computer" in capabilities:
        execution_kind = "browser_computer_scene_execution"
    elif "computer" in capabilities:
        execution_kind = "computer_scene_execution"
    elif "browser" in capabilities:
        execution_kind = "browser_scene_execution"
    else:
        execution_kind = "generic_environment_execution"
    contract = {
        "execution_kind": execution_kind,
        "summary_scope": "business_summary_only",
        "evidence_scope": "episode_scoped",
        "memory_policy": "disabled",
        "learning_policy": "disabled",
        "preferred_capabilities": list(request["preferred_capabilities"]),
    }
    if "computer" in capabilities:
        contract["coordinate_policy"] = "delegate_to_hid"
    if request["browser_target"]:
        contract["browser_target"] = dict(request["browser_target"])
    if request["computer_target"]:
        contract["computer_target"] = dict(request["computer_target"])
    if request["target_regions"]:
        contract["target_regions"] = [dict(item) for item in request["target_regions"]]
    if request["action_plan"]:
        contract["action_plan"] = [dict(item) for item in request["action_plan"]]
    if request["artifact_expectations"]:
        contract["artifact_expectations"] = dict(request["artifact_expectations"])
    if request["anti_detection_policy"]:
        contract["anti_detection_policy"] = dict(request["anti_detection_policy"])
    if request["behavior_budget"]:
        contract["behavior_budget"] = dict(request["behavior_budget"])
    return contract


def _scene_environment_context(request: dict[str, Any], *, episode_id: str | None) -> dict[str, Any]:
    environment_requirements = _as_dict(request.get("environment_requirements"))
    context = _as_dict(request.get("context"))
    return {
        "environment_key": str(
            environment_requirements.get("environment_key")
            or context.get("environment_key")
            or episode_id
            or ""
        ).strip()
        or None,
        "environment_kind": _optional_string(
            environment_requirements.get("environment_kind") or context.get("environment_kind"),
            max_length=128,
        )
        or "generic_environment",
        "display_label": _optional_string(
            environment_requirements.get("display_label") or context.get("display_label") or request.get("title"),
            max_length=255,
        ),
        "resource_locator": _optional_string(
            environment_requirements.get("resource_locator") or context.get("resource_locator"),
        ),
        "action_hints": _list_of_dicts(
            environment_requirements.get("action_hints") or context.get("action_hints"),
        ),
        "browser_target": dict(request["browser_target"]) if request["browser_target"] else {},
        "computer_target": dict(request["computer_target"]) if request["computer_target"] else {},
        "target_regions": [dict(item) for item in request["target_regions"]],
        "action_plan": [dict(item) for item in request["action_plan"]],
        "artifact_expectations": dict(request["artifact_expectations"]) if request["artifact_expectations"] else {},
        "anti_detection_policy": dict(request["anti_detection_policy"]) if request["anti_detection_policy"] else {},
        "behavior_budget": dict(request["behavior_budget"]) if request["behavior_budget"] else {},
    }


def _environment_descriptor(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "environment_kind": _optional_string(candidate.get("environment_kind"), max_length=128) or "generic_environment",
        "display_label": _optional_string(candidate.get("display_label"), max_length=255),
        "resource_locator": _optional_string(candidate.get("resource_locator")),
        "action_hints": _list_of_dicts(candidate.get("action_hints")),
        "browser_target": _as_dict(candidate.get("browser_target")),
        "computer_target": _as_dict(candidate.get("computer_target")),
        "target_regions": _list_of_dicts(candidate.get("target_regions")),
        "artifact_expectations": _as_dict(candidate.get("artifact_expectations")),
    }


def _normalize_environment_candidate(payload: dict[str, Any], *, default_source: str) -> dict[str, Any] | None:
    candidate = {
        "source": str(payload.get("source") or default_source or "scene_tool"),
        "status": str(payload.get("status") or "observed"),
        "environment_key": payload.get("environment_key"),
        "resource_locator": payload.get("resource_locator") or payload.get("url"),
        "display_label": payload.get("display_label") or payload.get("title"),
        "environment_kind": payload.get("environment_kind") or payload.get("page_type"),
        "capability_hints": payload.get("capability_hints"),
        "observed_entities": payload.get("observed_entities"),
        "action_hints": payload.get("action_hints") or payload.get("affordances"),
        "runtime_metadata": payload.get("runtime_metadata"),
        "browser_target": payload.get("browser_target"),
        "computer_target": payload.get("computer_target"),
        "target_regions": payload.get("target_regions"),
        "artifact_expectations": payload.get("artifact_expectations"),
    }
    if any(
        candidate.get(key)
        for key in (
            "resource_locator",
            "display_label",
            "environment_kind",
            "observed_entities",
            "action_hints",
            "browser_target",
            "computer_target",
            "target_regions",
            "artifact_expectations",
        )
    ):
        return candidate
    if candidate.get("runtime_metadata"):
        return candidate
    return None


def _normalize_browser_target(value: Any) -> dict[str, Any]:
    payload = _as_dict(value)
    url = _optional_string(payload.get("url"))
    url_host = _host_from_url(url)
    host = _optional_string(payload.get("host"), max_length=255)
    if url_host and (not host or (":" in url_host and ":" not in host and url_host.startswith(f"{host}:"))):
        host = url_host
    target = {
        "application": _optional_string(payload.get("application") or payload.get("app"), max_length=128),
        "window_title": _optional_string(payload.get("window_title") or payload.get("window"), max_length=255),
        "tab_id": _optional_int(payload.get("tab_id") or payload.get("tabId")),
        "host": host,
        "url": url,
        "url_pattern": _optional_string(payload.get("url_pattern") or payload.get("urlPattern")),
        "site_label": _optional_string(payload.get("site_label") or payload.get("site")),
    }
    return {key: item for key, item in target.items() if item not in (None, "", [])}


def _normalize_computer_target(value: Any) -> dict[str, Any]:
    payload = _as_dict(value)
    target = {
        "application": _optional_string(payload.get("application") or payload.get("app"), max_length=128),
        "window_title": _optional_string(payload.get("window_title") or payload.get("window"), max_length=255),
        "post_mode": _optional_string(payload.get("post_mode") or payload.get("postMode"), max_length=64),
        "activation_policy": _optional_string(payload.get("activation_policy") or payload.get("activationPolicy"), max_length=128),
    }
    return {key: item for key, item in target.items() if item not in (None, "", [])}


def _normalize_target_regions(value: Any) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for raw in list(value or []) if isinstance(value, list) else []:
        payload = _as_dict(raw)
        region_payload = _as_dict(payload.get("region") or payload.get("viewport") or payload.get("area"))
        normalized = {
            "id": _optional_string(payload.get("id") or payload.get("name"), max_length=128),
            "name": _optional_string(payload.get("name"), max_length=128),
            "ref": _optional_string(payload.get("ref"), max_length=128),
            "signature": _optional_string(payload.get("signature") or payload.get("sig"), max_length=255),
            "label": _optional_string(payload.get("label") or payload.get("name"), max_length=255),
            "role": _optional_string(payload.get("role"), max_length=128),
            "href": _optional_string(payload.get("href") or payload.get("source_url") or payload.get("sourceUrl")),
            "download": _optional_string(
                payload.get("download") or payload.get("file_name") or payload.get("fileName") or payload.get("filename"),
                max_length=255,
            ),
            "visibility": _optional_string(payload.get("visibility") or payload.get("viewport_hint"), max_length=128),
            "required": bool(payload.get("required")),
            "hint": _optional_string(payload.get("hint"), max_length=255),
            "note": _optional_string(payload.get("note") or payload.get("text") or payload.get("hint"), max_length=255),
            "region": {
                key: number
                for key, number in (
                    ("x", _optional_number(region_payload.get("x"))),
                    ("y", _optional_number(region_payload.get("y"))),
                    ("width", _optional_number(region_payload.get("width"))),
                    ("height", _optional_number(region_payload.get("height"))),
                )
                if number is not None
            },
        }
        normalized = {
            key: item
            for key, item in normalized.items()
            if item not in (None, "", []) and not (key == "region" and not item)
        }
        if normalized:
            regions.append(normalized)
    return regions[:8]


def _normalize_action_plan(value: Any) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    raw_items = list(value or []) if isinstance(value, list) else ([value] if isinstance(value, dict) else [])
    for raw in raw_items:
        if isinstance(raw, str):
            note = _optional_string(raw, max_length=255)
            if note:
                plans.append({"note": note})
            continue
        payload = _as_dict(raw)
        normalized = {
            "action": _optional_string(payload.get("action") or payload.get("intent"), max_length=128),
            "steps": _string_list(payload.get("steps")),
            "if_visible": _optional_string(payload.get("if_visible") or payload.get("on_visible"), max_length=128),
            "if_not_visible": _optional_string(
                payload.get("if_not_visible") or payload.get("offscreen_policy"),
                max_length=128,
            ),
            "max_attempts": _optional_int(payload.get("max_attempts") or payload.get("retries")),
            "scroll_direction": _optional_string(
                payload.get("scroll_direction") or payload.get("preferred_scroll_direction"),
                max_length=64,
            ),
            "download_source": _normalize_download_lookup(
                payload.get("download_source") or payload.get("downloadSource") or payload
            ),
            "note": _optional_string(payload.get("note"), max_length=255),
        }
        normalized = {
            key: item
            for key, item in normalized.items()
            if item not in (None, "", []) and not (isinstance(item, dict) and not item)
        }
        if normalized:
            plans.append(normalized)
    return plans[:8]


def _string_list_from_aliases(payload: dict[str, Any], *keys: str, max_length: int = 2048) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = payload.get(key)
        raw_values = value if isinstance(value, list) else [value]
        for raw in raw_values:
            text = _optional_string(raw, max_length=max_length)
            if text and text not in values:
                values.append(text)
    return values


def _normalize_download_lookup(value: Any) -> dict[str, Any]:
    payload = _as_dict(value)
    source_urls = _string_list_from_aliases(
        payload,
        "source_url",
        "sourceUrl",
        "source_urls",
        "sourceUrls",
        "sourceUrlCandidates",
        "download_url",
        "downloadUrl",
        "downloadUrls",
        "href",
        "url",
    )
    source_url_regexes = _string_list_from_aliases(
        payload,
        "source_url_regex",
        "sourceUrlRegex",
        "sourceUrlRegexes",
        "download_url_regex",
        "downloadUrlRegex",
        "hrefRegex",
    )
    final_urls = _string_list_from_aliases(payload, "final_url", "finalUrl", "finalUrls")
    final_url_regexes = _string_list_from_aliases(payload, "final_url_regex", "finalUrlRegex", "finalUrlRegexes")
    referrers = _string_list_from_aliases(payload, "referrer", "referrers")
    referrer_regexes = _string_list_from_aliases(payload, "referrer_regex", "referrerRegex", "referrerRegexes")
    expected_filename = _optional_string(
        payload.get("expected_filename")
        or payload.get("expectedFileName")
        or payload.get("file_name")
        or payload.get("fileName")
        or payload.get("filename")
        or payload.get("download"),
        max_length=255,
    )
    lookup = {
        "source_url": source_urls[0] if source_urls else None,
        "source_urls": source_urls if len(source_urls) > 1 else [],
        "source_url_regex": source_url_regexes[0] if source_url_regexes else None,
        "source_url_regexes": source_url_regexes if len(source_url_regexes) > 1 else [],
        "final_url": final_urls[0] if final_urls else None,
        "final_urls": final_urls if len(final_urls) > 1 else [],
        "final_url_regex": final_url_regexes[0] if final_url_regexes else None,
        "final_url_regexes": final_url_regexes if len(final_url_regexes) > 1 else [],
        "referrer": referrers[0] if referrers else None,
        "referrers": referrers if len(referrers) > 1 else [],
        "referrer_regex": referrer_regexes[0] if referrer_regexes else None,
        "referrer_regexes": referrer_regexes if len(referrer_regexes) > 1 else [],
        "expected_filename": expected_filename,
        "filename_regex": _optional_string(
            payload.get("filename_regex") or payload.get("filenameRegex"),
            max_length=255,
        ),
        "started_after": _optional_string(
            payload.get("started_after")
            or payload.get("startedAfter")
            or payload.get("started_at")
            or payload.get("startedAt")
            or payload.get("observed_at")
            or payload.get("observedAt")
            or payload.get("snapshot_at")
            or payload.get("snapshotAt"),
            max_length=128,
        ),
        "tab_id": _optional_int(payload.get("tab_id") or payload.get("tabId")),
        "source_ref": _optional_string(payload.get("ref"), max_length=128),
        "source_signature": _optional_string(payload.get("signature") or payload.get("sig"), max_length=255),
        "match_on": _string_list(payload.get("match_on") or payload.get("matchOn")),
        "acceptable_states": _string_list(payload.get("acceptable_states") or payload.get("acceptableStates")),
        "required": bool(payload.get("required")),
        "require_source_correlation": bool(payload.get("require_source_correlation") or payload.get("requireSourceCorrelation")),
        "require_unique": bool(payload.get("require_unique") or payload.get("requireUnique")),
    }
    if any(
        lookup.get(key)
        for key in (
            "source_url",
            "source_urls",
            "source_url_regex",
            "source_url_regexes",
            "final_url",
            "final_urls",
            "final_url_regex",
            "final_url_regexes",
            "referrer",
            "referrers",
            "referrer_regex",
            "referrer_regexes",
        )
    ):
        lookup["require_source_correlation"] = True
    return {
        key: item
        for key, item in lookup.items()
        if item not in (None, "", [])
        and not (isinstance(item, bool) and item is False)
        and not (isinstance(item, dict) and not item)
    }


def _normalize_artifact_expectations(value: Any) -> dict[str, Any]:
    payload = _as_dict(value)
    expectations = {
        "requires_local_artifact": bool(
            payload.get("requires_local_artifact")
            or payload.get("requiresLocalArtifact")
            or payload.get("requires_local_path")
            or payload.get("require_verified_local_artifact_path")
            or payload.get("requireVerifiedLocalArtifactPath")
        ),
        "download_expected": bool(payload.get("download_expected")),
        "upload_expected": bool(payload.get("upload_expected")),
        "verify_path": bool(
            payload.get("verify_path")
            or payload.get("verifyPath")
            or payload.get("requires_local_artifact")
            or payload.get("require_verified_local_artifact_path")
        ),
        "verify_format": bool(
            payload.get("verify_format")
            or payload.get("verifyFormat")
            or payload.get("expected_format")
            or payload.get("required_format")
            or payload.get("allowed_extensions")
        ),
        "expected_kind": _optional_string(
            payload.get("expected_kind")
            or payload.get("expectedKind")
            or payload.get("artifact_kind")
            or payload.get("resume_artifact_type"),
            max_length=128,
        ),
        "preferred_directory": _optional_string(payload.get("preferred_directory") or payload.get("directory")),
        "allowed_extensions": _string_list(
            payload.get("allowed_extensions")
            or payload.get("extensions")
            or payload.get("accepted_file_kinds")
            or payload.get("expected_file_kinds")
            or payload.get("required_format")
            or payload.get("expected_format")
        ),
        "download_lookup": _normalize_download_lookup(
            payload.get("download_lookup") or payload.get("downloadLookup") or payload.get("download_source") or payload
        ),
    }
    if expectations["download_lookup"]:
        expectations["download_expected"] = True
    if bool(payload.get("require_download_source_correlation") or payload.get("requireDownloadSourceCorrelation")):
        expectations["download_expected"] = True
        download_lookup = dict(expectations.get("download_lookup") or {})
        download_lookup["require_source_correlation"] = True
        expectations["download_lookup"] = download_lookup
    return {
        key: item
        for key, item in expectations.items()
        if item not in (None, "", [])
        and not (isinstance(item, bool) and item is False)
        and not (isinstance(item, dict) and not item)
    }


def _optional_int(value: Any) -> int | None:
    number = _optional_number(value)
    if number is None:
        return None
    try:
        return int(number)
    except (TypeError, ValueError):
        return None


def _optional_number(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number
