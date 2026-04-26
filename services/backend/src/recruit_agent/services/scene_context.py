from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.db.base import utcnow
from recruit_agent.kernel.kernel import AgentKernel
from recruit_agent.plugins.host import PluginHost
from recruit_agent.repositories.domain import (
    EnvironmentSnapshotRepository,
    ExecutionEpisodeRepository,
    ExecutionPlanRepository,
    TaskSpecRepository,
)
from recruit_agent.runtime.limits import RoundLimits
from recruit_agent.runtime.models import GoalRef, InputEnvelope, Message, Observation, RoundOutcome
from recruit_agent.runtime.providers import LLMProvider
from recruit_agent.runtime.result_semantics import (
    extract_execution_status,
    extract_structured_result_payload,
    normalize_result_payload,
)
from recruit_agent.runtime.tools import ToolRegistry


@dataclass(slots=True)
class SceneContextService:
    session_factory: sessionmaker[Session]
    provider: LLMProvider
    tool_registry: ToolRegistry
    plugin_host: PluginHost
    limits: RoundLimits = field(default_factory=RoundLimits)
    default_max_rounds: int | None = None
    _kernel: AgentKernel = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._kernel = AgentKernel(
            provider=self.provider,
            tool_registry=self.tool_registry,
            plugin_host=self.plugin_host,
            memory_service=None,
            learning_writer=None,
            limits=self.limits,
        )

    def delegate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = _normalize_scene_request(arguments, default_max_rounds=self.default_max_rounds)
        with self.session_factory() as session:
            task_repo = TaskSpecRepository(session)
            plan_repo = ExecutionPlanRepository(session)
            episode_repo = ExecutionEpisodeRepository(session)
            snapshot_repo = EnvironmentSnapshotRepository(session)

            task_spec = task_repo.create(
                {
                    "title": request["title"],
                    "description": request["description"],
                    "goal": _build_scene_goal_text(request),
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
                    },
                    "success_criteria": dict(request["success_criteria"]),
                    "approval_policy": dict(request["approval_policy"]),
                    "output_contract": dict(request["output_contract"]),
                    "preferred_capabilities": list(request["preferred_capabilities"]),
                    "preferred_domains": ["scene"],
                    "compiled_payload": {
                        "instruction": request["instruction"],
                        "max_rounds": request["max_rounds"],
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
        history_messages: list[Message] = []
        last_outcome = RoundOutcome(status="continue", gate_signal="continue")
        blockers: list[dict[str, Any]] = []
        browser_semantics = _initial_browser_semantics(request)
        scene_tool_registry = _scene_tool_registry(
            self.tool_registry,
            request=request,
            browser_semantics=browser_semantics,
        )
        kernel = AgentKernel(
            provider=self.provider,
            tool_registry=scene_tool_registry,
            plugin_host=self.plugin_host,
            memory_service=None,
            learning_writer=None,
            limits=self.limits,
        )

        round_seq = 0
        while True:
            if request["max_rounds"] is not None and round_seq >= int(request["max_rounds"]):
                blockers = blockers or [
                    {
                        "kind": "budget_exhausted",
                        "message": "scene context reached explicit round budget before producing a terminal result",
                    }
                ]
                break

            round_seq += 1
            round_events: list[dict[str, Any]] = []
            observation = Observation(
                world_snapshot={
                    "scene_request": {
                        "instruction": request["instruction"],
                        "input": _compact_value(request["input"]),
                        "context": _compact_value(request["context"]),
                        "output_contract": _compact_value(request["output_contract"]),
                        "environment_requirements": _compact_value(request["environment_requirements"]),
                    },
                    "scene_execution": {
                        "episode_id": episode.id,
                        "task_spec_id": task_spec.id,
                        "round_seq": round_seq,
                    },
                },
                scope_kind="scene_context",
                scope_ref=episode.id,
                recent_events=list(episode.observations or [])[-8:],
                available_tools=sorted(scene_tool_registry.tools.keys()),
                available_skills=[],
                available_mcps=_available_mcp_names(scene_tool_registry),
                hash=f"{episode.id}:{round_seq}",
                input=InputEnvelope(history_messages=list(history_messages)),
            )
            last_outcome = kernel.run_round(
                goal=GoalRef(
                    goal_id=episode.id,
                    scope_kind="scene_context",
                    scope_ref=episode.id,
                    title=request["title"],
                    goal_text=_build_scene_goal_text(request),
                    constraints={
                        "goal_kind": "scene_context",
                        "persist_memory": False,
                        "success_criteria": dict(request["success_criteria"]),
                        "output_contract": dict(request["output_contract"]),
                        "environment_requirements": dict(request["environment_requirements"]),
                        "approval_policy": dict(request["approval_policy"]),
                        "preferred_capabilities": list(request["preferred_capabilities"]),
                        "source_kind": "scene_context",
                    },
                ),
                observation=observation,
                limits=self.limits,
                event_sink=lambda event_type, data: _record_scene_event(
                    round_events=round_events,
                    browser_semantics=browser_semantics,
                    event_type=event_type,
                    data=data,
                ),
            )
            history_messages = list(last_outcome.metadata.get("history_messages") or [])
            blockers = _collect_blockers(last_outcome, round_events)
            snapshot_ids.extend(
                _append_environment_snapshots(
                    session=session,
                    task_spec=task_spec,
                    plan=plan,
                    episode=episode,
                    request=request,
                    round_seq=round_seq,
                    events=round_events,
                )
            )
            _append_episode_round(
                session=session,
                episode=episode,
                round_seq=round_seq,
                events=round_events,
                outcome=last_outcome,
                blockers=blockers,
                snapshot_count=len(snapshot_ids),
            )
            if not _should_continue(last_outcome):
                break

        return self._finalize_success(
            session=session,
            task_spec=task_spec,
            plan=plan,
            episode=episode,
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
        outcome: RoundOutcome,
        blockers: list[dict[str, Any]],
        snapshot_ids: list[str],
    ) -> dict[str, Any]:
        result_data = _scene_result_data(outcome)
        public_status = _public_status(outcome, blockers)
        stored_status = _stored_status(public_status)
        summary = _public_summary(outcome, blockers)
        metrics = {
            "round_count": int((episode.metrics or {}).get("round_count") or 0),
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
            "round_count": int((episode.metrics or {}).get("round_count") or 0),
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


def _normalize_scene_request(arguments: dict[str, Any], *, default_max_rounds: int | None) -> dict[str, Any]:
    instruction = str(arguments.get("instruction") or "").strip()
    if not instruction:
        raise ValueError("delegate_scene_context requires instruction")
    title = str(arguments.get("title") or instruction[:80]).strip() or "Scene context task"
    success_criteria = _as_dict(arguments.get("success_criteria"))
    output_contract = _as_dict(arguments.get("output_contract"))
    preferred_capabilities = _string_list(arguments.get("preferred_capabilities"))
    environment_requirements = _as_dict(arguments.get("environment_requirements"))
    approval_policy = _as_dict(arguments.get("approval_policy"))
    context = _as_dict(arguments.get("context"))
    input_payload = _as_dict(arguments.get("input"))
    browser_target = _normalize_browser_target(
        arguments.get("browser_target") or environment_requirements.get("browser_target") or context.get("browser_target")
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
    max_rounds = _normalize_optional_positive_int(arguments.get("max_rounds"), default=default_max_rounds)
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
        "max_rounds": max_rounds,
        "requested_by": requested_by,
    }


def _build_scene_goal_text(request: dict[str, Any]) -> str:
    parts = [
        request["instruction"],
        "只使用当前可用的 scene 工具完成任务。",
        "输出必须是业务级摘要，避免复述 DOM、页面按钮、tab 轨迹、资源定位符等环境细节，除非它们是阻塞判断所必需的证据。",
    ]
    if request["success_criteria"]:
        parts.append(f"成功标准：{request['success_criteria']}")
    if request["output_contract"]:
        parts.append(f"结果合同：{request['output_contract']}")
    if request["browser_target"]:
        parts.append(f"浏览器目标：{_compact_value(request['browser_target'])}")
        parts.append(
            "当 browser_target.url 存在时，必须以该 URL 的完整 origin（包含端口）作为目标边界。"
            "不要把同 hostname 但不同端口、不同 origin 或旧测试 tab 当成当前任务目标；"
            "如果 browser_list_tabs 没有匹配该 origin 的 tab，先用 browser_open_tab 或等价浏览器导航打开目标 URL。"
        )
    if request["computer_target"] or "computer" in _scene_capabilities(request["preferred_capabilities"]):
        parts.append(
            "如需调用电脑/HID 动作，不要自行计算屏幕绝对坐标；必须先从 browser snapshot 的 clickPoint、"
            "候选落地区域或等价观察证据构造明确的 HID primitives，并携带 browser-derived target/context host。"
            "browser 侧只提供页面语义与 viewport/document 坐标；不要让 browser 或 recruit-agent 合成 viewportInScreen。"
            "HID 目标窗口、内容视口到屏幕的映射由 VirtualHID 根据 target/geometry 自行解析。"
            "不得只传 target/context 而空缺 primitives；若缺少可执行原语，继续观察或返回结构化 blocker。"
            "外部执行层负责激活、滚动和最终落点。"
        )
    if request["target_regions"]:
        parts.append(f"候选落地区域：{_compact_value(request['target_regions'])}")
    if request["action_plan"]:
        parts.append(f"动作意图：{_compact_value(request['action_plan'])}")
    if request["artifact_expectations"]:
        parts.append(
            "若结果合同要求本地文件或附件，必须先用可用的只读下载/文件定位工具找到 artifact path 和当前状态；"
            "浏览器触发的下载优先调用 browser_locate_download 读取 Chrome 下载记录、本地路径、下载进度和 state"
            "（可能是 in_progress、interrupted 或 complete），不要用页面 JS、mock DOM 标记或下载入口本身冒充本地文件。"
            "对 browser-managed 下载，若 browser_locate_download 返回 located=true、state=complete、exists=true、"
            "本地 path/fileName、extension 或 mime，并带有 sourceUrl/finalUrl/referrer 关联证据，可把这些只读下载记录字段"
            "作为本地路径与格式证据；不要因为 scene 内没有 shell/file 工具而丢弃已定位的 Chrome 下载记录。"
            "如果 action_plan 或 artifact_expectations 已保存下载入口的 browser-derived href/source_url、download 文件名、"
            "finalUrl/referrer 线索或点击前 started_after/observed_at 时间戳，必须把这些字段传给 browser_locate_download 做来源关联，"
            "避免多次下载时误配本地文件。"
            "只有在业务层确认 path、格式和归档条件后才能结束。"
        )
    if request["output_contract"] or request["artifact_expectations"]:
        parts.append(
            "若 scene 已拿到可写回业务层的本地 artifact，最终 JSON 必须在 result_data 中保留 artifact/browser_download "
            "和 business_writeback 字段；business_writeback.arguments 应直接适配后续业务写入工具（例如 resume artifact "
            "写回时的 attach_resume_artifact），但 scene 内不要绕过合同自行编造 artifact proof。"
        )
    return "\n".join(part for part in parts if part)


def _build_checkpoints(request: dict[str, Any]) -> list[dict[str, Any]]:
    checkpoints = [
        {"label": "scene_observe", "summary": "Inspect the delegated execution environment and confirm actionable signals."},
        {"label": "scene_execute", "summary": "Use scene tools to pursue the delegated contract within the isolated environment."},
        {"label": "scene_summarize", "summary": "Return business summary, blockers, and retained environment evidence."},
    ]
    if request["approval_policy"]:
        checkpoints.append({"label": "approval_gate", "summary": "Respect approval policy before risky actions."})
    return checkpoints


def _append_episode_round(
    *,
    session: Session,
    episode: Any,
    round_seq: int,
    events: list[dict[str, Any]],
    outcome: RoundOutcome,
    blockers: list[dict[str, Any]],
    snapshot_count: int,
) -> None:
    observation_entries = list(episode.observations or [])
    action_entries = list(episode.actions or [])
    for event in events:
        event_type = str(event.get("type") or "")
        payload = _as_dict(event.get("payload"))
        entry = {
            "round_seq": round_seq,
            "type": event_type,
            "recorded_at": event.get("recorded_at"),
            "payload": payload,
        }
        if event_type == "tool_call":
            action_entries.append(entry)
        else:
            observation_entries.append(entry)
    observation_entries = observation_entries[-200:]
    action_entries = action_entries[-200:]
    episode.observations = observation_entries
    episode.actions = action_entries
    episode.result_summary = outcome.final_output or _public_summary(outcome, blockers)
    episode.metrics = {
        "round_count": max(round_seq, int((episode.metrics or {}).get("round_count") or 0)),
        "tool_call_count": len(action_entries),
        "tool_result_count": sum(1 for item in observation_entries if item.get("type") == "tool_result"),
        "environment_snapshot_count": snapshot_count,
        "blocker_count": len(blockers),
        "last_gate_signal": outcome.gate_signal,
    }
    session.commit()


def _append_environment_snapshots(
    *,
    session: Session,
    task_spec: Any,
    plan: Any,
    episode: Any,
    request: dict[str, Any],
    round_seq: int,
    events: list[dict[str, Any]],
) -> list[str]:
    snapshot_repo = EnvironmentSnapshotRepository(session)
    snapshot_ids: list[str] = []
    for event in events:
        if str(event.get("type") or "") != "tool_result":
            continue
        payload = _as_dict(event.get("payload"))
        tool_name = str(payload.get("tool_name") or "")
        output = payload.get("output")
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
                        "round_seq": round_seq,
                        "tool_name": tool_name,
                        "environment_descriptor": _compact_value(_environment_descriptor(candidate)),
                        "raw": _compact_value(candidate.get("runtime_metadata") or candidate),
                    },
                }
            )
            snapshot_ids.append(snapshot.id)
    return snapshot_ids


def _record_scene_event(
    *,
    round_events: list[dict[str, Any]],
    browser_semantics: dict[str, Any],
    event_type: str,
    data: dict[str, Any],
) -> None:
    if event_type == "tool_result":
        payload = _as_dict(data)
        _remember_browser_semantics(
            browser_semantics,
            tool_name=str(payload.get("tool_name") or ""),
            output=payload.get("output"),
        )
    round_events.append(
        {
            "type": event_type,
            "payload": _compact_value(data),
            "recorded_at": utcnow().isoformat(),
        }
    )


def _scene_tool_registry(
    tool_registry: ToolRegistry,
    *,
    request: dict[str, Any],
    browser_semantics: dict[str, Any],
) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tool_registry.tools.values():
        cloned = tool.clone()
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
                return _mask_scene_browser_target_mismatch(
                    tool_name=_tool_name,
                    result=result,
                    request=request,
                )

            cloned.handler = _browser_handler
        elif cloned.name == "hid_action":
            original_handler = cloned.handler

            def _handler(arguments: dict[str, Any], *, _original_handler=original_handler) -> Any:
                normalized = _normalize_scene_hid_action_arguments(
                    arguments,
                    request=request,
                    browser_semantics=browser_semantics,
                )
                arguments.clear()
                arguments.update(normalized)
                return _original_handler(arguments)

            cloned.handler = _handler
        registry.register(cloned)
    return registry


def _validate_scene_browser_tool_target(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    request: dict[str, Any],
    browser_semantics: dict[str, Any],
) -> dict[str, Any] | None:
    if tool_name not in {"browser_select_tab", "browser_snapshot"}:
        return None
    target_origin = _scene_target_origin(request)
    if target_origin is None:
        return None
    tab_id = _optional_int(arguments.get("tabId") or arguments.get("tab_id"))
    if tab_id is None:
        return None
    tab_info = dict((browser_semantics.get("tabs") or {}).get(tab_id) or {})
    tab_url = _optional_string(tab_info.get("url"))
    if tab_url is None or _scene_url_matches_target_origin(tab_url, target_origin=target_origin):
        return None
    return {
        "success": False,
        "error": "scene_browser_target_mismatch",
        "message": "Selected browser tab does not match the scene browser_target origin. Open or select the target URL from the scene contract before observing or acting.",
        "targetOrigin": target_origin,
        "tab": {"tabId": tab_id, "url": tab_url},
    }


def _mask_scene_browser_target_mismatch(
    *,
    tool_name: str,
    result: Any,
    request: dict[str, Any],
) -> Any:
    if tool_name not in {"browser_get_active_tab", "browser_select_tab", "browser_snapshot"} or not isinstance(result, dict):
        return result
    target_origin = _scene_target_origin(request)
    if target_origin is None:
        return result
    observed_url = _browser_result_url(result)
    if observed_url is None or _scene_url_matches_target_origin(observed_url, target_origin=target_origin):
        return result
    return {
        "success": False,
        "error": "scene_browser_target_mismatch",
        "message": "Observed browser target does not match the scene browser_target origin. Use browser_open_tab or browser navigation to reach the requested target URL before continuing.",
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


def _scene_url_matches_target_origin(value: Any, *, target_origin: str) -> bool:
    observed_origin = _origin_from_url(value) or _host_from_url(value)
    return observed_origin == target_origin


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
            target.setdefault("host", host)
            normalized["target"] = target
        context.setdefault("host", host)
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

    if geometry:
        _apply_browser_viewport_geometry(geometry, browser_semantics=browser_semantics, tab_id=tab_id)
        normalized["geometry"] = geometry

    return normalized


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
    if host:
        browser_semantics["last_host"] = host
    if url:
        browser_semantics["last_url"] = url
    if viewport:
        browser_semantics["last_viewport"] = viewport
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
                "title": _optional_string(tab.get("title")),
                "windowId": _optional_int(tab.get("windowId") or tab.get("window_id")),
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
    candidates = [
        context.get("host"),
        target.get("host"),
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
    tab_info = dict((browser_semantics.get("tabs") or {}).get(tab_id) or {}) if tab_id is not None else {}
    viewport = _as_dict(tab_info.get("viewport")) or _as_dict(browser_semantics.get("last_viewport"))
    width = _optional_number(viewport.get("innerWidth"))
    height = _optional_number(viewport.get("innerHeight"))
    geometry.setdefault("scrollOffset", {"x": _optional_number(viewport.get("scrollX")) or 0, "y": _optional_number(viewport.get("scrollY")) or 0})
    if width is not None and height is not None:
        geometry.setdefault("viewportSize", {"x": 0, "y": 0, "width": width, "height": height})
    visual_viewport = _as_dict(viewport.get("visualViewport"))
    if "pageScale" not in geometry and "page_scale" not in geometry:
        geometry["pageScale"] = _optional_number(visual_viewport.get("scale")) or 1


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


def _collect_blockers(outcome: RoundOutcome, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("type") or "")
        payload = _as_dict(event.get("payload"))
        if event_type == "tool_blocked":
            blockers.append(
                {
                    "kind": "tool_blocked",
                    "tool_name": payload.get("tool_name"),
                    "message": str(payload.get("reason") or "tool blocked"),
                    "severity": payload.get("severity"),
                }
            )
        if event_type == "tool_result" and bool(payload.get("is_error")):
            blockers.append(
                {
                    "kind": "tool_error",
                    "tool_name": payload.get("tool_name"),
                    "message": str(payload.get("output") or "tool execution failed"),
                }
            )
    if outcome.gate_signal == "budget_exhausted":
        blockers.append({"kind": "budget_exhausted", "message": "scene context reached explicit safety budget"})
    if outcome.status == "escalate":
        blockers.append({"kind": "escalate", "message": outcome.escalate_reason or "scene context escalated"})
    return blockers


def _should_continue(outcome: RoundOutcome) -> bool:
    return outcome.status == "continue" and outcome.gate_signal == "continue"


def _public_status(outcome: RoundOutcome, blockers: list[dict[str, Any]]) -> str:
    result_status = _scene_result_status(outcome)
    if result_status in {"completed", "complete", "success", "succeeded"}:
        return "completed"
    if result_status in {"blocked", "wait_human", "waiting_human", "paused"} or result_status.startswith("blocked_"):
        return "blocked"
    if result_status in {"error", "failed", "failure", "fail"} or result_status.startswith("failed_") or result_status.startswith("failure_"):
        return "error"
    if outcome.status in {"error", "cancelled"}:
        return "error"
    if outcome.status == "complete":
        return "completed"
    if outcome.status in {"wait_human", "escalate"} or blockers:
        return "blocked"
    return "incomplete"


def _scene_result_status(outcome: RoundOutcome) -> str:
    result_status = str((outcome.result_data or {}).get("status") or "").strip().lower()
    if result_status:
        return result_status
    structured = extract_structured_result_payload(outcome.final_output)
    return str(extract_execution_status(structured) or "").strip().lower()


def _stored_status(public_status: str) -> str:
    return {
        "completed": "completed",
        "blocked": "blocked",
        "error": "failed",
        "incomplete": "interrupted",
    }.get(public_status, "interrupted")


def _public_summary(outcome: RoundOutcome, blockers: list[dict[str, Any]]) -> str:
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


def _scene_result_data(outcome: RoundOutcome) -> dict[str, Any]:
    if isinstance(outcome.result_data, dict) and outcome.result_data:
        return dict(outcome.result_data)
    structured = extract_structured_result_payload(outcome.final_output)
    if not structured:
        return {}
    result_data, _skill_draft = normalize_result_payload(structured)
    return result_data


def _scene_result_artifacts(result_data: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for key in ("artifact", "resume_artifact", "download_artifact", "resume_download_record", "browser_download"):
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
