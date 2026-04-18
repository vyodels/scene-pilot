from __future__ import annotations

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
from scene_pilot.runtime.limits import RuntimeLimits
from scene_pilot.runtime.models import GoalRef, Observation, TickOutcome
from scene_pilot.runtime.providers import LLMProvider
from scene_pilot.runtime.tools import ToolRegistry


@dataclass(slots=True)
class AgentKernel:
    provider: LLMProvider
    tool_registry: ToolRegistry
    plugin_host: PluginHost
    memory_service: Any | None = None
    limits: RuntimeLimits = field(default_factory=RuntimeLimits)

    def run_tick(self, goal: GoalRef, observation: Observation) -> TickOutcome:
        sensed = sense(observation, self.plugin_host)
        messages = assemble_messages(
            goal,
            sensed,
            plugin_host=self.plugin_host,
            memory_service=self.memory_service,
            tool_registry=self.tool_registry,
        )
        deliberation = deliberate(
            provider=self.provider,
            messages=messages,
            tool_registry=self.tool_registry,
            observation=sensed,
            plugin_host=self.plugin_host,
            limits=self.limits,
        )
        effects = act(deliberation)
        memory_updates = update_memory(deliberation, self.memory_service)
        outcome = evaluate(deliberation, effects)
        final_guard = run_final(deliberation.final_content, sensed)
        outcome.metadata.update(
            {
                "assembled_messages": messages,
                "tool_results": deliberation.tool_results,
                "memory_updates": memory_updates,
                "final_guard": final_guard,
                "observation": sensed,
            }
        )
        if not final_guard.allowed:
            outcome.status = "escalate"
            outcome.escalate_reason = final_guard.reason
        return outcome
