from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from scene_pilot.kernel.act import act
from scene_pilot.kernel.assemble import assemble_messages
from scene_pilot.kernel.deliberate import deliberate
from scene_pilot.kernel.evaluate import evaluate
from scene_pilot.kernel.guard import run_final
from scene_pilot.kernel.sense import sense
from scene_pilot.kernel.update_memory import update_memory
from scene_pilot.plugins.host import PluginHost
from scene_pilot.runtime.limits import RoundLimits
from scene_pilot.runtime.models import CancellationToken, GoalRef, Message, Observation, RoundOutcome
from scene_pilot.runtime.providers import LLMProvider
from scene_pilot.runtime.tools import ToolRegistry


EventSink = Callable[[str, dict[str, Any]], None]


@dataclass(slots=True)
class AgentKernel:
    provider: LLMProvider
    tool_registry: ToolRegistry
    plugin_host: PluginHost
    memory_service: Any | None = None
    learning_writer: Any | None = None
    limits: RoundLimits = field(default_factory=RoundLimits)

    def run_round(
        self,
        *,
        goal: GoalRef,
        observation: Observation,
        limits: RoundLimits | None = None,
        cancel_token: CancellationToken | None = None,
        event_sink: EventSink | None = None,
        memory_service: Any | None = None,
        learning_writer: Any | None = None,
    ) -> RoundOutcome:
        active_limits = limits or self.limits
        active_memory = memory_service if memory_service is not None else self.memory_service
        persist_memory = bool(goal.constraints.get("persist_memory", True))
        active_learning_writer = learning_writer if learning_writer is not None else self.learning_writer
        sensed = sense(observation, self.plugin_host)
        messages = assemble_messages(
            goal,
            sensed,
            plugin_host=self.plugin_host,
            memory_service=active_memory,
            tool_registry=self.tool_registry,
        )
        deliberation = deliberate(
            provider=self.provider,
            messages=messages,
            tool_registry=self.tool_registry,
            observation=sensed,
            plugin_host=self.plugin_host,
            limits=active_limits,
            cancel_token=cancel_token,
            event_sink=event_sink,
        )
        effects = act(deliberation)
        outcome = evaluate(deliberation, effects, limits=active_limits)
        if outcome.status == "complete" and outcome.final_output:
            final_guard = run_final(deliberation.final_content, sensed)
            if not final_guard.allowed:
                outcome.status = "escalate"
                outcome.gate_signal = "escalate"
                outcome.escalate_reason = final_guard.reason
            outcome.metadata["final_guard"] = final_guard
        memory_updates = update_memory(
            deliberation,
            active_memory if persist_memory else None,
            round_status=outcome.status,
            learning_writer=active_learning_writer,
            scope_kind=str(goal.constraints.get("memory_scope_kind") or goal.scope_kind),
            scope_ref=str(goal.constraints.get("memory_scope_ref") or goal.scope_ref),
            agent_profile_id=str(goal.constraints.get("agent_profile_id") or "") or None,
            run_pk=str(goal.constraints.get("run_pk") or "") or None,
            conversation_pk=str(goal.constraints.get("conversation_pk") or "") or None,
            source_kind=str(goal.constraints.get("source_kind") or "autonomous"),
            goal_kind=str(goal.constraints.get("goal_kind") or "") or None,
            goal_title=goal.title,
        )
        outcome.memory_updates = memory_updates
        outcome.metadata.update(
            {
                "assembled_messages": messages,
                "tool_results": deliberation.tool_results,
                "memory_updates": memory_updates,
                "observation": sensed,
                "history_messages": [
                    message
                    for message in deliberation.messages
                    if not (message.role == "system" and message.content == messages[0].content)
                ],
                "pending_tool_calls": deliberation.metadata.get("pending_tool_calls", []),
            }
        )
        return outcome
