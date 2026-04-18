from __future__ import annotations

from scene_pilot.plugins.host import PluginHost
from scene_pilot.runtime.models import Observation


def sense(observation: Observation, plugin_host: PluginHost | None = None) -> Observation:
    if plugin_host is None:
        return observation
    enriched = plugin_host.run_observation_enrichers_sync(observation)
    return Observation(**enriched)
