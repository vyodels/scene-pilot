from __future__ import annotations

from scene_pilot.plugins.host import PluginHost
from scene_pilot.runtime.models import GuardVerdict, Observation


def run_preflight(
    tool_name: str,
    arguments: dict[str, object],
    observation: Observation,
    *,
    plugin_host: PluginHost | None = None,
) -> list[GuardVerdict]:
    if plugin_host is None:
        return []
    return plugin_host.run_guard_checks_sync(tool_name, arguments, observation)


def run_final(final_output: str, observation: Observation) -> GuardVerdict:
    if not final_output and not observation.world_snapshot:
        return GuardVerdict(allowed=False, reason="empty_outcome", severity="warning")
    return GuardVerdict(allowed=True)
