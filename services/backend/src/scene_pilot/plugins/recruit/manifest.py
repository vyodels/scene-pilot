from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.plugins.host import PluginHost
from scene_pilot.plugins.recruit.guard import build_guard_check
from scene_pilot.plugins.recruit.observation import build_observation_enricher
from scene_pilot.plugins.recruit.persona import RECRUIT_PERSONA_FRAGMENT
from scene_pilot.plugins.recruit.router import build_router
from scene_pilot.plugins.recruit.toolkit import (
    archive_candidate,
    attach_resume_artifact,
    create_candidate_review_decision,
    create_candidate_scorecard,
    create_candidate_sync_record,
    delete_candidate,
    delete_resume_artifact,
    get_candidate_thread,
    get_goal_progress,
    list_candidates,
    list_candidate_threads,
    list_job_descriptions,
    list_locked_candidates,
    record_outbound_message,
    release_candidate,
    request_human_approval,
    score_candidate,
    take_over_candidate,
    transition_application,
    upsert_candidate,
    upsert_job_description,
)
from scene_pilot.runtime.tools import ToolDefinition


@dataclass(slots=True)
class RecruitPluginManifest:
    session_factory: sessionmaker[Session]
    namespace: str = "recruit"

    def install(self, plugin_host: PluginHost) -> None:
        def _tool(
            *,
            name: str,
            description: str,
            parameters: dict,
            handler,
            resource_target_kind: str,
            metadata: dict | None = None,
        ) -> ToolDefinition:
            return ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                handler=handler,
                category="plugin",
                external_target=False,
                resource_target_kind=resource_target_kind,
                metadata=metadata or {},
            )

        tools = [
            _tool(
                name="take_over_candidate",
                description="Take over a candidate from autonomous handling.",
                parameters={
                    "type": "object",
                    "properties": {
                        "candidate_person_id": {"type": "string"},
                        "locked_by": {"type": "string"},
                        "reason": {"type": "string"},
                        "expires_at": {"type": ["string", "null"], "description": "Optional ISO-8601 timestamp."},
                    },
                    "required": ["candidate_person_id", "locked_by"],
                    "additionalProperties": False,
                },
                handler=lambda arguments: take_over_candidate(self.session_factory, **arguments),
                resource_target_kind="candidate",
            ),
            _tool(
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
                resource_target_kind="candidate",
            ),
            _tool(
                name="list_locked_candidates",
                description="List candidates currently locked for human takeover.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=lambda _arguments: list_locked_candidates(self.session_factory),
                resource_target_kind="candidate",
            ),
            _tool(
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
                resource_target_kind="job",
                metadata={"capabilities": ["job_description", "recruit_read"]},
            ),
            _tool(
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
                        "benefit_tags": {"type": "array", "items": {"type": "string"}},
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
                resource_target_kind="job",
                metadata={"capabilities": ["job_description", "recruit_write"]},
            ),
            _tool(
                name="list_candidates",
                description=(
                    "List candidates already written into the local recruiting workspace, optionally filtered by platform, "
                    "job description, or application status."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "offset": {"type": "integer", "minimum": 0},
                        "platform": {"type": "string"},
                        "job_description_id": {"type": "string"},
                        "application_status": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                handler=lambda arguments: list_candidates(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "recruit_read"]},
            ),
            _tool(
                name="upsert_candidate",
                description=(
                    "Create or update a candidate, optionally link the candidate to a job description, and persist source-side "
                    "signals such as viewed/communicated/interested counters for downstream recruiting decisions."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "platform": {"type": "string"},
                        "platform_candidate_id": {"type": "string"},
                        "contact_info": {"type": "object"},
                        "resume_path": {"type": "string"},
                        "online_resume_text": {"type": "string"},
                        "profile_url": {"type": "string"},
                        "raw_profile": {"type": "object"},
                        "first_seen_at": {"type": ["string", "number"]},
                        "last_seen_at": {"type": ["string", "number"]},
                        "job_description_id": {"type": "string"},
                        "platform_application_id": {"type": "string"},
                        "current_status": {"type": "string"},
                        "current_stage_key": {"type": "string"},
                        "deepest_milestone": {"type": "string"},
                        "state_snapshot": {"type": "object"},
                        "application_metadata": {"type": "object"},
                        "source_platform": {"type": "string"},
                        "source_observation": {"type": "object"},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                handler=lambda arguments: upsert_candidate(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "recruit_write"]},
            ),
            _tool(
                name="delete_candidate",
                description="Delete a candidate person and cascade associated local application records.",
                parameters={
                    "type": "object",
                    "properties": {"candidate_person_id": {"type": "string"}},
                    "required": ["candidate_person_id"],
                    "additionalProperties": False,
                },
                handler=lambda arguments: delete_candidate(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "recruit_write"]},
            ),
            _tool(
                name="archive_candidate",
                description="Archive a candidate application by transitioning it to archived status.",
                parameters={
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                handler=lambda arguments: archive_candidate(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "recruit_write"]},
            ),
            _tool(
                name="list_candidate_threads",
                description="List isolated candidate application threads so each candidate keeps separate communication context.",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                        "offset": {"type": "integer", "minimum": 0},
                        "application_id": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                handler=lambda arguments: list_candidate_threads(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "thread", "recruit_read"]},
            ),
            _tool(
                name="get_candidate_thread",
                description="Fetch one isolated candidate application thread by application or candidate+job identity.",
                parameters={
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                handler=lambda arguments: get_candidate_thread(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "thread", "recruit_read"]},
            ),
            _tool(
                name="score_candidate",
                description="Persist AI scoring for a candidate application, including evidence and rubric dimensions.",
                parameters={
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                        "score": {"type": "integer"},
                        "decision": {"type": "string"},
                        "summary": {"type": "string"},
                        "stage_key": {"type": "string"},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "created_by": {"type": "string"},
                        "rubric_version": {"type": "string"},
                        "dimension_scores": {"type": "object"},
                        "metadata": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                handler=lambda arguments: score_candidate(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "assessment", "recruit_write"]},
            ),
            _tool(
                name="create_candidate_scorecard",
                description="Create a scorecard for a candidate application using structured recruiting rubric fields.",
                parameters={
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                        "stage_key": {"type": "string"},
                        "source": {"type": "string"},
                        "rubric_version": {"type": "string"},
                        "score_total": {"type": "integer"},
                        "verdict": {"type": "string"},
                        "summary": {"type": "string"},
                        "dimension_scores": {"type": "object"},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "metadata": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                handler=lambda arguments: create_candidate_scorecard(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "assessment", "recruit_write"]},
            ),
            _tool(
                name="create_candidate_review_decision",
                description="Create a structured review decision for a candidate application after scoring or human review.",
                parameters={
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string"},
                        "application_id": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                        "stage_key": {"type": "string"},
                        "rationale": {"type": "string"},
                        "decision_source": {"type": "string"},
                        "decided_by": {"type": "string"},
                        "scorecard_id": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["decision"],
                    "additionalProperties": False,
                },
                handler=lambda arguments: create_candidate_review_decision(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "assessment", "recruit_write"]},
            ),
            _tool(
                name="record_outbound_message",
                description="Write one outbound message draft or sent record into the candidate's isolated communication thread.",
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "application_id": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                        "channel_hint": {"type": "string"},
                        "status": {"type": "string"},
                        "message_type": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["content"],
                    "additionalProperties": False,
                },
                handler=lambda arguments: record_outbound_message(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "communication", "recruit_write"]},
            ),
            _tool(
                name="attach_resume_artifact",
                description="Attach an offline resume or related artifact to a candidate application and refresh contact snapshots.",
                parameters={
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                        "source": {"type": "string"},
                        "artifact_type": {"type": "string"},
                        "file_name": {"type": "string"},
                        "file_path": {"type": "string"},
                        "extracted_text": {"type": "string"},
                        "contact_snapshot": {"type": "object"},
                        "metadata": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                handler=lambda arguments: attach_resume_artifact(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "resume", "recruit_write"]},
            ),
            _tool(
                name="delete_resume_artifact",
                description="Delete a previously stored resume artifact from the local recruiting workspace.",
                parameters={
                    "type": "object",
                    "properties": {"artifact_id": {"type": "string"}},
                    "required": ["artifact_id"],
                    "additionalProperties": False,
                },
                handler=lambda arguments: delete_resume_artifact(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "resume", "recruit_write"]},
            ),
            _tool(
                name="transition_application",
                description="Move a candidate application through the recruiting state machine with stage, note, and channel context.",
                parameters={
                    "type": "object",
                    "properties": {
                        "to_status": {"type": "string"},
                        "application_id": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                        "phase_key": {"type": "string"},
                        "phase_label": {"type": "string"},
                        "stage_key": {"type": "string"},
                        "stage_label": {"type": "string"},
                        "note": {"type": "string"},
                        "actor": {"type": "string"},
                        "actor_id": {"type": "string"},
                        "trigger": {"type": "string"},
                        "override_reason": {"type": "string"},
                        "metadata": {"type": "object"},
                        "interview_round": {"type": "integer"},
                        "contact_channels": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["to_status"],
                    "additionalProperties": False,
                },
                handler=lambda arguments: transition_application(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "state_transition", "recruit_write"]},
            ),
            _tool(
                name="create_candidate_sync_record",
                description="Persist downstream sync tracking for a candidate application, such as talent pool or CRM sync state.",
                parameters={
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                        "destination": {"type": "string"},
                        "status": {"type": "string"},
                        "external_ref": {"type": "string"},
                        "payload_snapshot": {"type": "object"},
                        "error_message": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                handler=lambda arguments: create_candidate_sync_record(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["candidate", "sync", "recruit_write"]},
            ),
            _tool(
                name="get_goal_progress",
                description="Summarize candidate progress for one JD, including by-status counts and how many already have contact, resume, or AI score.",
                parameters={
                    "type": "object",
                    "properties": {"job_description_id": {"type": "string"}},
                    "required": ["job_description_id"],
                    "additionalProperties": False,
                },
                handler=lambda arguments: get_goal_progress(self.session_factory, **arguments),
                resource_target_kind="job",
                metadata={"capabilities": ["candidate", "progress", "recruit_read"]},
            ),
            _tool(
                name="request_human_approval",
                description=(
                    "Pause the Autonomous run and request human approval before continuing a high-risk recruiting action. "
                    "Use this before contacting candidates for sensitive follow-up such as asking for resume or contact details."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "action_kind": {"type": "string"},
                        "candidate_person_id": {"type": "string"},
                        "application_id": {"type": "string"},
                        "job_description_id": {"type": "string"},
                        "payload": {"type": "object"},
                    },
                    "required": ["title"],
                    "additionalProperties": False,
                },
                handler=lambda arguments: request_human_approval(self.session_factory, **arguments),
                resource_target_kind="candidate",
                metadata={"capabilities": ["approval"], "requires_confirmation": True},
            ),
        ]

        plugin_host.register_tools(self.namespace, tools)
        plugin_host.register_observation_enricher(self.namespace, build_observation_enricher(self.session_factory))
        plugin_host.register_guard_check(self.namespace, build_guard_check(self.session_factory))
        plugin_host.register_persona_fragment(self.namespace, "handover", RECRUIT_PERSONA_FRAGMENT)
        plugin_host.register_router(self.namespace, build_router(self.session_factory))
