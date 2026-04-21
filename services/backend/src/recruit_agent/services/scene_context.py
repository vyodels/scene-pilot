from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
from recruit_agent.runtime.tools import ToolRegistry


@dataclass(slots=True)
class SceneContextService:
    session_factory: sessionmaker[Session]
    provider: LLMProvider
    tool_registry: ToolRegistry
    plugin_host: PluginHost
    limits: RoundLimits = field(default_factory=RoundLimits)
    default_max_rounds: int = 6
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
                        "execution_contract": _scene_execution_contract(),
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

        for round_seq in range(1, int(request["max_rounds"]) + 1):
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
                available_tools=sorted(self.tool_registry.tools.keys()),
                available_skills=[],
                available_mcps=_available_mcp_names(self.tool_registry),
                hash=f"{episode.id}:{round_seq}",
                input=InputEnvelope(history_messages=list(history_messages)),
            )
            last_outcome = self._kernel.run_round(
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
                event_sink=lambda event_type, data: round_events.append(
                    {
                        "type": event_type,
                        "payload": _compact_value(data),
                        "recorded_at": utcnow().isoformat(),
                    }
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
        else:
            blockers = blockers or [
                {
                    "kind": "budget_exhausted",
                    "message": "scene context reached round budget before producing a terminal result",
                }
            ]

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

        return {
            "status": public_status,
            "summary": summary,
            "blockers": blockers,
            "artifacts": [
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
            "blockers": [{"kind": "scene_context_error", "message": message}],
            "artifacts": [
                {"kind": "environment_snapshot", "snapshot_id": snapshot_id}
                for snapshot_id in _dedupe_strings(snapshot_ids)
            ],
            "metrics": dict(episode.metrics or {}),
            "episode_id": episode.id,
        }


def _normalize_scene_request(arguments: dict[str, Any], *, default_max_rounds: int) -> dict[str, Any]:
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
    max_rounds = int(arguments.get("max_rounds") or default_max_rounds)
    max_rounds = max(1, min(max_rounds, 32))
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
        blockers.append({"kind": "budget_exhausted", "message": "scene context reached round budget"})
    if outcome.status == "escalate":
        blockers.append({"kind": "escalate", "message": outcome.escalate_reason or "scene context escalated"})
    return blockers


def _should_continue(outcome: RoundOutcome) -> bool:
    return outcome.status == "continue" and outcome.gate_signal == "continue"


def _public_status(outcome: RoundOutcome, blockers: list[dict[str, Any]]) -> str:
    if outcome.status in {"error", "cancelled"}:
        return "error"
    if outcome.status == "complete":
        return "completed"
    if outcome.status in {"wait_human", "escalate"} or blockers:
        return "blocked"
    return "incomplete"


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
    if blockers:
        return str(blockers[0].get("message") or "scene context reported a blocker")
    if outcome.gate_signal == "budget_exhausted":
        return "scene context reached round budget before producing a terminal result"
    return "scene context finished without a terminal summary"


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
    for raw in list(value or []) if isinstance(value, list) else []:
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


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [_as_dict(item) for item in list(value or []) if isinstance(item, dict)][:8]


def _scene_execution_contract() -> dict[str, Any]:
    return {
        "execution_kind": "generic_environment_execution",
        "summary_scope": "business_summary_only",
        "evidence_scope": "episode_scoped",
        "memory_policy": "disabled",
        "learning_policy": "disabled",
    }


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
    }


def _environment_descriptor(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "environment_kind": _optional_string(candidate.get("environment_kind"), max_length=128) or "generic_environment",
        "display_label": _optional_string(candidate.get("display_label"), max_length=255),
        "resource_locator": _optional_string(candidate.get("resource_locator")),
        "action_hints": _list_of_dicts(candidate.get("action_hints")),
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
    }
    if any(
        candidate.get(key)
        for key in ("resource_locator", "display_label", "environment_kind", "observed_entities", "action_hints")
    ):
        return candidate
    if candidate.get("runtime_metadata"):
        return candidate
    return None
