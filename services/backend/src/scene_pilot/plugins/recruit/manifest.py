from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.plugins.host import PluginHost
from scene_pilot.plugins.recruit.guard import build_guard_check
from scene_pilot.plugins.recruit.observation import build_observation_enricher
from scene_pilot.plugins.recruit.persona import RECRUIT_PERSONA_FRAGMENT
from scene_pilot.plugins.recruit.router import build_router
from scene_pilot.plugins.recruit.toolkit import (
    list_job_descriptions,
    list_locked_candidates,
    release_candidate,
    take_over_candidate,
    upsert_job_description,
)
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
                    parameters={
                        "type": "object",
                        "properties": {
                            "candidate_person_id": {"type": "string"},
                            "locked_by": {"type": "string"},
                            "reason": {"type": "string"},
                            "expires_at": {
                                "type": ["string", "null"],
                                "description": "Optional ISO-8601 timestamp for automatic lock expiry.",
                            },
                        },
                        "required": ["candidate_person_id", "locked_by"],
                        "additionalProperties": False,
                    },
                    handler=lambda arguments: take_over_candidate(self.session_factory, **arguments),
                    category="plugin",
                    external_target=False,
                    resource_target_kind="candidate",
                ),
                ToolDefinition(
                    name="release_candidate",
                    description="Release a candidate back to autonomous handling.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "candidate_person_id": {"type": "string"},
                            "released_by": {"type": "string"},
                            "handover_note": {"type": "string"},
                            "handover_next_hint": {"type": "string"},
                        },
                        "required": ["candidate_person_id", "released_by"],
                        "additionalProperties": False,
                    },
                    handler=lambda arguments: release_candidate(self.session_factory, **arguments),
                    category="plugin",
                    external_target=False,
                    resource_target_kind="candidate",
                ),
                ToolDefinition(
                    name="list_locked_candidates",
                    description="List currently locked candidates.",
                    parameters={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    handler=lambda _arguments: list_locked_candidates(self.session_factory),
                    category="plugin",
                    external_target=False,
                    resource_target_kind="candidate",
                ),
                ToolDefinition(
                    name="list_job_descriptions",
                    description="List job descriptions already stored in the local recruiting workspace.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                            "offset": {"type": "integer", "minimum": 0},
                            "status": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                    handler=lambda arguments: list_job_descriptions(self.session_factory, **arguments),
                    category="plugin",
                    external_target=False,
                    resource_target_kind="job",
                ),
                ToolDefinition(
                    name="upsert_job_description",
                    description=(
                        "Create or update a job description in the local recruiting workspace using generic recruiting fields. "
                        "Use platform/external identity when syncing from an external site."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "job_description_id": {"type": "string"},
                            "title": {"type": "string"},
                            "company_name": {"type": "string"},
                            "department": {"type": "string"},
                            "location": {"type": "string"},
                            "employment_type": {"type": "string"},
                            "headcount": {"type": "integer"},
                            "salary_min": {"type": "integer"},
                            "salary_max": {"type": "integer"},
                            "compensation_text": {"type": "string"},
                            "experience_requirement": {"type": "string"},
                            "education_requirement": {"type": "string"},
                            "summary": {"type": "string"},
                            "description": {"type": "string"},
                            "requirements": {"type": "string"},
                            "benefit_tags": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "detail_metadata": {"type": "object"},
                            "status": {"type": "string"},
                            "source": {"type": "string"},
                            "platform": {"type": "string"},
                            "external_id": {"type": "string"},
                            "external_url": {"type": "string"},
                            "sync_status": {"type": "string"},
                            "sync_metadata": {"type": "object"},
                        },
                        "required": ["title"],
                        "additionalProperties": False,
                    },
                    handler=lambda arguments: upsert_job_description(self.session_factory, **arguments),
                    category="plugin",
                    external_target=False,
                    resource_target_kind="job",
                    metadata={
                        "capabilities": ["job_description", "recruit_write"],
                    },
                ),
            ],
        )
        plugin_host.register_observation_enricher(self.namespace, build_observation_enricher(self.session_factory))
        plugin_host.register_guard_check(self.namespace, build_guard_check(self.session_factory))
        plugin_host.register_persona_fragment(self.namespace, "handover", RECRUIT_PERSONA_FRAGMENT)
        plugin_host.register_router(self.namespace, build_router(self.session_factory))
