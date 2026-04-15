from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .models import AgentResult, LLMUsage, Message, ToolCall
from .prompts import PromptBuilder
from .providers import LLMProvider
from .result_semantics import normalize_result_payload
from .tools import ToolRegistry


@dataclass(slots=True)
class AgentLoopConfig:
    max_turns: int = 8
    token_budget: int = 8_192
    preferred_provider: str | None = None
    max_tool_errors_before_replan: int = 2


@dataclass(slots=True)
class AgentLoop:
    provider: LLMProvider
    tools: ToolRegistry
    prompt_builder: PromptBuilder = field(default_factory=PromptBuilder)
    config: AgentLoopConfig = field(default_factory=AgentLoopConfig)

    def run(
        self,
        task: Any,
        *,
        session: dict[str, Any] | None = None,
        skill: dict[str, Any] | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> AgentResult:
        messages = self.prompt_builder.build_messages(
            task,
            session=session,
            skill=skill,
            extra_context=extra_context,
        )
        token_budget = getattr(task, "token_budget", None) or self.config.token_budget
        max_turns = getattr(task, "max_turns", None) or self.config.max_turns
        usage = LLMUsage()
        tool_outputs = []
        execution_contract = self._extract_execution_contract(extra_context)
        trace = self._build_executor_trace(execution_contract)
        consecutive_tool_errors = 0
        if execution_contract is not None:
            messages.append(
                Message(
                    role="user",
                    content=self._executor_turn_prompt(trace, execution_contract),
                )
            )

        for turn in range(max_turns):
            trace["turn_count"] = turn + 1
            active_capability = self._current_capability(trace)
            preferred_tools = self._current_step_preferred_tools(trace)
            response = self.provider.generate(
                messages,
                tools=self.tools.describe(
                    capabilities=[active_capability] if active_capability else None,
                    preferred_tool_names=preferred_tools,
                ),
                task=self._provider_task_payload(
                    task=task,
                    execution_contract=execution_contract,
                    active_capability=active_capability,
                    preferred_tools=preferred_tools,
                    trace=trace,
                ),
            )
            usage.prompt_tokens += response.usage.prompt_tokens
            usage.completion_tokens += response.usage.completion_tokens
            usage.total_tokens += response.usage.total_tokens

            if usage.total_tokens > token_budget:
                return AgentResult(
                    success=False,
                    status="timeout",
                    content="Token budget exceeded",
                    messages=messages,
                    usage=usage,
                    tool_outputs=tool_outputs,
                    metadata=self._result_metadata(trace, extra_context, error="token_budget_exceeded"),
                )

            if response.requires_human_input:
                return AgentResult(
                    success=False,
                    status="waiting_human",
                    content=response.content,
                    messages=messages,
                    usage=usage,
                    tool_outputs=tool_outputs,
                    metadata=self._result_metadata(trace, extra_context, control={"kind": "waiting_human", "reason": response.content}),
                )

            if response.tool_calls:
                messages.append(
                    Message(
                        role="assistant",
                        content=response.content or "",
                        metadata={"tool_calls": [tool_call.to_provider_payload() for tool_call in response.tool_calls]},
                    )
                )
                submitted_result: tuple[dict[str, Any], dict[str, Any] | None] | None = None
                control_outcome: dict[str, Any] | None = None
                for tool_call in response.tool_calls:
                    result = self.tools.execute(tool_call.name, tool_call.arguments)
                    tool_outputs.append(result)
                    control_outcome = self._apply_tool_trace(
                        trace,
                        tool_call=tool_call,
                        output=result.output,
                        is_error=result.is_error,
                    ) or control_outcome
                    if self._is_terminal_result_submission(tool_call, result.output, result.is_error):
                        submitted_result = self._normalize_submitted_result(tool_call, result.output)
                    if result.is_error:
                        consecutive_tool_errors += 1
                    else:
                        consecutive_tool_errors = 0
                    messages.append(
                        Message(
                            role="tool",
                            content=result.to_message_content(),
                            name=tool_call.name,
                            tool_call_id=tool_call.id,
                            metadata={"is_error": result.is_error},
                        )
                    )
                    if (
                        control_outcome is None
                        and execution_contract is not None
                        and result.is_error
                        and consecutive_tool_errors >= self.config.max_tool_errors_before_replan
                    ):
                        control_outcome = {
                            "kind": "replan_requested",
                            "reason": f"Repeated tool failures while executing {tool_call.name}.",
                        }
                        trace["replan_requests"].append(
                            {
                                "reason": control_outcome["reason"],
                                "trigger": "tool_error_threshold",
                                "tool_name": tool_call.name,
                            }
                        )
                        break
                if control_outcome is not None:
                    return AgentResult(
                        success=False,
                        status=str(control_outcome["kind"]),
                        content=str(control_outcome.get("reason") or response.content or ""),
                        messages=messages,
                        usage=usage,
                        tool_outputs=tool_outputs,
                        metadata=self._result_metadata(trace, extra_context, control=control_outcome),
                    )
                if submitted_result is not None:
                    self._mark_open_step_completed(trace)
                    result_data, skill_draft = submitted_result
                    return AgentResult(
                        success=True,
                        status="completed",
                        content=response.content,
                        data=result_data,
                        skill_draft=skill_draft,
                        messages=messages,
                        usage=usage,
                        tool_outputs=tool_outputs,
                        metadata=self._result_metadata(trace, extra_context, result_data=result_data),
                    )
                synthesized_result = self._auto_submit_completed_step(
                    trace=trace,
                    tool_calls=response.tool_calls,
                    tool_outputs=tool_outputs,
                    extra_context=extra_context,
                )
                if synthesized_result is not None:
                    return AgentResult(
                        success=True,
                        status="completed",
                        content=response.content,
                        data=synthesized_result,
                        messages=messages,
                        usage=usage,
                        tool_outputs=tool_outputs,
                        metadata=self._result_metadata(trace, extra_context, result_data=synthesized_result),
                    )
                continue

            if response.result_data is not None:
                messages.append(Message(role="assistant", content=response.content or ""))
                self._mark_open_step_completed(trace)
                result_data, _ = normalize_result_payload(response.result_data)
                return AgentResult(
                    success=True,
                    status="completed",
                    content=response.content,
                    data=result_data,
                    skill_draft=response.skill_draft,
                    messages=messages,
                    usage=usage,
                    tool_outputs=tool_outputs,
                    metadata=self._result_metadata(trace, extra_context, result_data=result_data),
                )

            if response.finish_reason in {"stop", "completed", "result"} and response.content:
                messages.append(Message(role="assistant", content=response.content))
                if execution_contract is not None and trace.get("current_step_id"):
                    messages.append(
                        Message(
                            role="user",
                            content=self._continuation_prompt(trace, execution_contract),
                        )
                    )
                    continue
                self._mark_open_step_completed(trace)
                return AgentResult(
                    success=True,
                    status="completed",
                    content=response.content,
                    messages=messages,
                    usage=usage,
                    tool_outputs=tool_outputs,
                    metadata=self._result_metadata(trace, extra_context),
                )

            messages.append(
                Message(
                    role="user",
                    content=self._continuation_prompt(trace, execution_contract),
                )
            )

        return AgentResult(
            success=False,
            status="timeout",
            content="Max turns reached",
            messages=messages,
            usage=usage,
            tool_outputs=tool_outputs,
            metadata=self._result_metadata(trace, extra_context, error="max_turns_reached"),
        )

    def _provider_task_payload(
        self,
        *,
        task: Any,
        execution_contract: Mapping[str, Any] | None,
        active_capability: str | None,
        preferred_tools: list[str],
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        payload = getattr(task, "payload", {}) or {}
        goal = payload.get("goal") or payload.get("instruction") or (execution_contract or {}).get("goal")
        domain = payload.get("domain") or (execution_contract or {}).get("domain")
        return {
            "task_type": getattr(task, "task_type", None),
            "goal": goal,
            "domain": domain,
            "plan_name": (execution_contract or {}).get("plan_name"),
            "current_step_id": trace.get("current_step_id") or (execution_contract or {}).get("current_step_id"),
            "current_capability": active_capability,
            "preferred_tools": preferred_tools,
            "blockers": list((execution_contract or {}).get("blockers") or [])[:6],
        }

    def _is_terminal_result_submission(
        self,
        tool_call: ToolCall,
        output: Any,
        is_error: bool,
    ) -> bool:
        if is_error:
            return False
        tool = self.tools.tools.get(tool_call.name)
        if tool is None:
            return False
        if tool.metadata.get("terminal_result_submission"):
            return True
        return tool_call.name == "submit_result"

    def _normalize_submitted_result(
        self,
        tool_call: ToolCall,
        output: Any,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if isinstance(output, dict) and isinstance(output.get("payload"), dict):
            payload = dict(output["payload"])
        else:
            payload = dict(tool_call.arguments or {})
        return normalize_result_payload(payload)

    def _extract_execution_contract(self, extra_context: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(extra_context, Mapping):
            return None
        contract = extra_context.get("execution_contract")
        if isinstance(contract, Mapping):
            return dict(contract)
        return None

    def _build_executor_trace(self, execution_contract: dict[str, Any] | None) -> dict[str, Any]:
        step_states: list[dict[str, Any]] = []
        for raw_step in list((execution_contract or {}).get("steps") or []):
            if not isinstance(raw_step, Mapping):
                continue
            step_states.append(
                {
                    "step_id": str(raw_step.get("id") or "").strip(),
                    "capability": str(raw_step.get("capability") or "analyze").strip(),
                    "summary": str(raw_step.get("summary") or "").strip(),
                    "preferred_tools": list(raw_step.get("preferred_tools") or []),
                    "replan_on_error": bool(raw_step.get("replan_on_error", False)),
                    "status": "pending",
                }
            )
        return {
            "contract_version": "runtime-executor-v2",
            "plan_id": (execution_contract or {}).get("execution_plan_id"),
            "task_spec_id": (execution_contract or {}).get("task_spec_id"),
            "turn_count": 0,
            "step_states": step_states,
            "actions": [],
            "observations": [],
            "replan_requests": [],
            "human_checkpoints": [],
            "errors": [],
            "scene_updates": [],
            "current_step_id": step_states[0]["step_id"] if step_states else None,
        }

    def _apply_tool_trace(
        self,
        trace: dict[str, Any],
        *,
        tool_call: ToolCall,
        output: Any,
        is_error: bool,
    ) -> dict[str, Any] | None:
        tool = self.tools.tools.get(tool_call.name)
        metadata = dict(tool.metadata or {}) if tool is not None else {}
        payload = dict(output.get("payload") or {}) if isinstance(output, Mapping) and isinstance(output.get("payload"), Mapping) else dict(tool_call.arguments or {})
        if is_error:
            trace["errors"].append(
                {
                    "tool_name": tool_call.name,
                    "step_id": payload.get("step_id"),
                    "message": str(output),
                }
            )
            return None

        if metadata.get("observation_capture") or metadata.get("executor_observation_submission"):
            observation = {
                "tool_name": tool_call.name,
                "step_id": payload.get("step_id"),
                "capability": payload.get("capability"),
                "summary": payload.get("summary"),
                "signals": list(payload.get("signals") or []),
                "evidence": payload.get("evidence"),
            }
            trace["observations"].append(observation)
            self._merge_scene_update(trace, payload.get("scene_update") or payload.get("scene_delta"))
            return None

        if metadata.get("plan_progress") or metadata.get("executor_step_completion"):
            status = str(payload.get("status") or "completed")
            action = {
                "tool_name": tool_call.name,
                "step_id": payload.get("step_id"),
                "capability": payload.get("capability"),
                "status": status,
                "summary": payload.get("summary"),
                "artifacts": dict(payload.get("artifacts") or {}),
            }
            trace["actions"].append(action)
            step_id = str(payload.get("step_id") or "")
            self._set_step_state(trace, step_id=step_id, status=status)
            if status == "blocked":
                step_state = next(
                    (item for item in trace["step_states"] if item.get("step_id") == step_id),
                    None,
                )
                if step_state is not None and step_state.get("replan_on_error"):
                    reason = str(payload.get("summary") or payload.get("reason") or "The current plan step is blocked and requires replanning.")
                    trace["replan_requests"].append(
                        {
                            "reason": reason,
                            "step_id": step_id,
                            "trigger": "blocked_step",
                        }
                    )
                    return {"kind": "replan_requested", "reason": reason}
            return None

        if metadata.get("replan_request") or metadata.get("executor_replan_request"):
            request = {
                "reason": str(payload.get("reason") or "Execution diverged from the current plan."),
                "step_id": payload.get("step_id"),
                "blockers": list(payload.get("blockers") or ([payload.get("blocker")] if payload.get("blocker") else [])),
                "preferred_capabilities": list(payload.get("preferred_capabilities") or payload.get("recommended_capabilities") or []),
                "suggested_steps": list(payload.get("suggested_steps") or []),
            }
            trace["replan_requests"].append(request)
            self._merge_scene_update(trace, payload.get("scene_update") or payload.get("scene_delta"))
            return {"kind": "replan_requested", "reason": request["reason"]}

        if metadata.get("human_checkpoint"):
            checkpoint = {
                "reason": str(payload.get("reason") or "Human checkpoint requested."),
                "step_id": payload.get("step_id"),
                "review_kind": payload.get("review_kind"),
                "summary": payload.get("summary"),
                "payload": dict(payload.get("payload") or {}),
            }
            trace["human_checkpoints"].append(checkpoint)
            return {"kind": "waiting_human", "reason": checkpoint["reason"]}

        return None

    def _merge_scene_update(self, trace: dict[str, Any], scene_update: Any) -> None:
        if not isinstance(scene_update, Mapping):
            return
        trace["scene_updates"].append(dict(scene_update))

    def _set_step_state(self, trace: dict[str, Any], *, step_id: str, status: str) -> None:
        if not step_id:
            return
        for item in trace["step_states"]:
            if item.get("step_id") == step_id:
                item["status"] = status
                break
        pending = [item.get("step_id") for item in trace["step_states"] if item.get("status") not in {"completed", "skipped"}]
        trace["current_step_id"] = pending[0] if pending else None

    def _mark_open_step_completed(self, trace: dict[str, Any]) -> None:
        current_step_id = str(trace.get("current_step_id") or "").strip()
        if current_step_id:
            self._set_step_state(trace, step_id=current_step_id, status="completed")

    def _current_capability(self, trace: dict[str, Any]) -> str | None:
        current_step_id = str(trace.get("current_step_id") or "").strip()
        if not current_step_id:
            return None
        for item in trace["step_states"]:
            if item.get("step_id") == current_step_id:
                capability = str(item.get("capability") or "").strip()
                return capability or None
        return None

    def _current_step_preferred_tools(self, trace: dict[str, Any]) -> list[str]:
        current_step_id = str(trace.get("current_step_id") or "").strip()
        if not current_step_id:
            return []
        for item in trace["step_states"]:
            if item.get("step_id") == current_step_id:
                return [str(tool_name) for tool_name in list(item.get("preferred_tools") or []) if str(tool_name).strip()]
        return []

    def _executor_turn_prompt(
        self,
        trace: dict[str, Any],
        execution_contract: dict[str, Any],
    ) -> str:
        current_step_id = str(trace.get("current_step_id") or "").strip()
        current_step = next(
            (item for item in trace["step_states"] if item.get("step_id") == current_step_id),
            None,
        )
        remaining = [
            item.get("step_id")
            for item in trace["step_states"]
            if item.get("status") not in {"completed", "skipped"}
        ]
        plan_name = str(execution_contract.get("plan_name") or execution_contract.get("execution_plan_id") or "runtime plan")
        scene_type = str(execution_contract.get("scene_type") or execution_contract.get("page_type") or "runtime_scene")
        posture = str(execution_contract.get("planner_posture") or "verify")
        capability = str(current_step.get("capability") or "").strip() if isinstance(current_step, dict) else ""
        tool_names = [
            str(tool_name)
            for tool_name in list(current_step.get("preferred_tools") or [])
            if str(tool_name).strip()
        ] if isinstance(current_step, dict) else []
        if capability:
            registry_tools = self.tools.capability_tool_names(capability)
            if tool_names:
                tool_names = [tool_name for tool_name in tool_names if tool_name in registry_tools] or registry_tools
            else:
                tool_names = registry_tools
        parts = [
            f"Execute the active runtime plan `{plan_name}` one step at a time.",
            f"Current scene: `{scene_type}`. Planner posture: `{posture}`.",
        ]
        if current_step is not None:
            parts.append(
                f"Focus on step `{current_step_id}` using capability `{capability or 'analyze'}`."
            )
            if current_step.get("summary"):
                parts.append(f"Step summary: {current_step['summary']}")
        if tool_names:
            parts.append(f"Preferred tools for this step: {', '.join(tool_names)}.")
        if remaining:
            parts.append(f"Remaining steps: {', '.join(str(item) for item in remaining if item)}.")
        parts.append(
            "Record observations explicitly, complete steps explicitly, request replanning when the scene diverges, "
            "and request a human checkpoint for approvals or operator takeover."
        )
        return " ".join(part for part in parts if part)

    def _continuation_prompt(
        self,
        trace: dict[str, Any],
        execution_contract: dict[str, Any] | None = None,
    ) -> str:
        current_step = trace.get("current_step_id")
        if current_step:
            if execution_contract is not None:
                return self._executor_turn_prompt(trace, execution_contract)
            return (
                f"Continue executing the active plan. Focus on step `{current_step}`. "
                "Record observations, advance or block steps explicitly, request replanning when needed, "
                "and submit the structured result when the task is complete."
            )
        return "Please continue. If the task is complete, submit the structured result."

    def _result_metadata(
        self,
        trace: dict[str, Any],
        extra_context: dict[str, Any] | None,
        *,
        control: dict[str, Any] | None = None,
        result_data: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        completed = [item["step_id"] for item in trace["step_states"] if item.get("status") == "completed"]
        pending = [
            item["step_id"]
            for item in trace["step_states"]
            if item.get("status") not in {"completed", "skipped"}
        ]
        metadata = {
            "executor_trace": trace,
            "completed_step_ids": completed,
            "pending_step_ids": pending,
            "action_count": len(trace["actions"]),
            "observation_count": len(trace["observations"]),
            "replan_request_count": len(trace["replan_requests"]),
            "human_checkpoint_count": len(trace["human_checkpoints"]),
        }
        if isinstance(extra_context, Mapping):
            execution_contract = extra_context.get("execution_contract")
            if isinstance(execution_contract, Mapping):
                metadata["execution_contract"] = dict(execution_contract)
        if control is not None:
            metadata["executor_control"] = dict(control)
        if result_data is not None:
            metadata["result_status"] = result_data.get("status")
        if error is not None:
            metadata["executor_error"] = error
        return metadata

    def _auto_submit_completed_step(
        self,
        *,
        trace: dict[str, Any],
        tool_calls: list[ToolCall],
        tool_outputs: list[Any],
        extra_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        completed_statuses = {"completed", "complete", "done", "success", "passed"}
        if not any(tool_call.name == "advance_plan_step" for tool_call in tool_calls):
            return None

        actions = list(trace.get("actions") or [])
        if not actions:
            return None
        last_action = dict(actions[-1] or {})
        if str(last_action.get("status") or "").strip().lower() not in completed_statuses:
            return None

        observations = [
            dict(item)
            for item in list(trace.get("observations") or [])
            if str(item.get("step_id") or "") == str(last_action.get("step_id") or "")
        ]
        if not observations:
            return None

        candidate = self._latest_candidate_from_tool_outputs(tool_outputs)
        if candidate is None:
            return None
        execution_contract = self._extract_execution_contract(extra_context)
        source_scene = None
        if isinstance(execution_contract, Mapping):
            scene_type = str(execution_contract.get("scene_type") or "").strip()
            plan_name = str(execution_contract.get("plan_name") or "").strip()
            source_scene = " | ".join(part for part in [scene_type, plan_name] if part)

        result: dict[str, Any] = {
            "status": "step_completed",
            "step_id": last_action.get("step_id"),
            "next_step": trace.get("current_step_id"),
            "notes": str(last_action.get("summary") or observations[-1].get("summary") or "").strip(),
        }
        if source_scene:
            result["source_scene"] = source_scene

        candidate_name = str(candidate.get("name") or candidate.get("candidate_id") or "").strip()
        candidate_id = str(candidate.get("candidate_id") or candidate.get("platform_candidate_id") or "").strip()
        identifier = " / ".join(part for part in [candidate_id, candidate_name] if part)
        evidence = candidate.get("profile_or_resume_evidence") if isinstance(candidate.get("profile_or_resume_evidence"), Mapping) else {}
        result.update(
            {
                "candidate_name_or_identifier": identifier or candidate_name or candidate_id,
                "profile_or_resume_evidence": str(
                    evidence.get("summary")
                    or evidence.get("text_excerpt")
                    or candidate.get("online_resume_text")
                    or ""
                )[:320],
                "resume_artifact_status": candidate.get("resume_artifact_status") or "profile_evidence_available",
                "score": candidate.get("score") or "not_scored",
                "score_rationale": candidate.get("score_rationale") or "Current runtime step completed before formal scoring.",
                "upload_status": candidate.get("upload_status") or "not_started",
            }
        )
        return result

    def _latest_candidate_from_tool_outputs(self, tool_outputs: list[Any]) -> dict[str, Any] | None:
        for item in reversed(list(tool_outputs or [])):
            output = getattr(item, "output", None)
            if isinstance(output, Mapping) and (
                "candidate_id" in output or "platform_candidate_id" in output
            ):
                return dict(output)
            if isinstance(output, list):
                for candidate in output:
                    if isinstance(candidate, Mapping) and (
                        "candidate_id" in candidate or "platform_candidate_id" in candidate
                    ):
                        return dict(candidate)
        return None


def run_agent_loop(
    provider: LLMProvider,
    tools: ToolRegistry,
    task: Any,
    *,
    prompt_builder: PromptBuilder | None = None,
    config: AgentLoopConfig | None = None,
    session: dict[str, Any] | None = None,
    skill: dict[str, Any] | None = None,
    extra_context: dict[str, Any] | None = None,
) -> AgentResult:
    loop = AgentLoop(
        provider=provider,
        tools=tools,
        prompt_builder=prompt_builder or PromptBuilder(),
        config=config or AgentLoopConfig(),
    )
    return loop.run(task, session=session, skill=skill, extra_context=extra_context)
