from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.plugins.host import PluginHost
from scene_pilot.plugins.recruit.guard import build_guard_check
from scene_pilot.plugins.recruit.observation import build_observation_enricher
from scene_pilot.plugins.recruit.persona import RECRUIT_PERSONA_FRAGMENT
from scene_pilot.plugins.recruit.router import build_router
from scene_pilot.plugins.recruit.toolkit import list_locked_candidates, release_candidate, take_over_candidate
from scene_pilot.runtime.tools import ToolDefinition


@dataclass(slots=True)
class RecruitPluginManifest:
    session_factory: sessionmaker[Session]
    namespace: str = "recruit"

    def install(self, plugin_host: PluginHost) -> None:
        plugin_host.register_tools(
            self.namespace,
            [
                ToolDefinition(
                    name="take_over_candidate",
                    description="Take over a candidate from autonomous handling.",
                    parameters={"type": "object"},
                    handler=lambda arguments: take_over_candidate(self.session_factory, **arguments),
                    category="plugin",
                    external_target=False,
                    resource_target_kind="candidate",
                ),
                ToolDefinition(
                    name="release_candidate",
                    description="Release a candidate back to autonomous handling.",
                    parameters={"type": "object"},
                    handler=lambda arguments: release_candidate(self.session_factory, **arguments),
                    category="plugin",
                    external_target=False,
                    resource_target_kind="candidate",
                ),
                ToolDefinition(
                    name="list_locked_candidates",
                    description="List currently locked candidates.",
                    parameters={"type": "object"},
                    handler=lambda _arguments: list_locked_candidates(self.session_factory),
                    category="plugin",
                    external_target=False,
                    resource_target_kind="candidate",
                ),
            ],
        )
        plugin_host.register_observation_enricher(self.namespace, build_observation_enricher(self.session_factory))
        plugin_host.register_guard_check(self.namespace, build_guard_check(self.session_factory))
        plugin_host.register_persona_fragment(self.namespace, "handover", RECRUIT_PERSONA_FRAGMENT)
        plugin_host.register_router(self.namespace, build_router(self.session_factory))
