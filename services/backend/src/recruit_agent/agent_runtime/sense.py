from __future__ import annotations

from recruit_agent.plugins.host import PluginHost
from recruit_agent.agent_runtime.models import Observation


def sense(observation: Observation, plugin_host: PluginHost | None = None) -> Observation:
    if plugin_host is None:
        return observation
    enriched = plugin_host.run_observation_enrichers_sync(observation)
    return Observation(**enriched)
