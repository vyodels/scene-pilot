from __future__ import annotations

from datetime import datetime
import json
from threading import Thread
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from recruit_agent.db.base import utcnow
from recruit_agent.models.domain import (
    AgentGlobalMemory,
    AgentRun,
    AgentRunCheckpoint,
    AgentRuntimeEvent,
    AgentSession,
    AgentTurnRecord,
    ApprovalItem,
    ConversationSession,
    ConversationTurn,
    GoalSpec,
    OperatorInteraction,
    RecruitAgentProfile,
    Skill,
    TaskQueueItem,
)
from recruit_agent.repositories.domain import (
    CandidatePersonMemoryRepository,
    JobDescriptionMemoryRepository,
    RecruitAgentProfileRepository,
    SkillRepository,
    TaskQueueRepository,
)
from recruit_agent.product_adapters.business_state_projection import project_runtime_business_state
from recruit_agent.product_adapters.target_contracts import derive_browser_target
from recruit_agent.schemas.domain import (
    AgentGlobalMemoryRead,
    ApprovalRead,
    CandidateMemoryRead,
    GoalSpecRead,
    JobMemoryRead,
    McpServerRead,
    RecruitAgentProfileRead,
    RecruitAgentProfileUpdate,
    RuntimeControlledRunRead,
    RuntimeEventRead,
    RuntimeSessionRead,
    SkillRead,
)
from recruit_agent.services.container import AppContainer
from recruit_agent.services.recruit_agent import ensure_global_memory, resolve_context_policy, resolve_memory_policy
from recruit_agent.services.scene_templates import (
    SHARED_WORKSPACE_SCOPE_REF,
    serialize_scene_template,
    shared_scene_template_catalog,
)


AgentKind = Literal["assistant", "autonomous"]
MemoryScope = Literal["candidate", "job", "global"]
BUILTIN_AGENT_KINDS: tuple[AgentKind, ...] = ("assistant", "autonomous")
AUTONOMOUS_PRIMARY_CONVERSATION_ID = "autonomous-primary"
AUTONOMOUS_OPEN_RUN_STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "active",
    "waiting_human",
    "waiting_candidate",
    "blocked",
    "paused",
    "resumable",
)


class AgentTaskCreate(BaseModel):
    task_type: str
    priority: int = 100
    payload: dict[str, Any] = Field(default_factory=dict)


class AutonomousGoalCreateRequest(BaseModel):
    title: str
    goal_text: str
    goal_kind: str = "recruiting"
    requested_by: str = "desktop-user"
    summary: str | None = None
    priority: int = 100
    jd_id: str | None = Field(default=None, alias="jd_id")
    conversation_id: str | None = Field(default=None, alias="conversation_id")
    candidate_count_target: int | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    context_hints: dict[str, Any] = Field(default_factory=dict)
    trial_budget: dict[str, Any] = Field(default_factory=dict)
    run_preferences: dict[str, Any] = Field(default_factory=dict)


class RunControlRequest(BaseModel):
    reviewer: str = "desktop-user"
    reason: str | None = None


class SceneTemplateRunRequest(BaseModel):
    requested_by: str = "desktop-user"
    title: str | None = None
    goal_text: str | None = None
    jd_id: str | None = Field(default=None, alias="jd_id")
    conversation_id: str | None = Field(default=None, alias="conversation_id")
    candidate_count_target: int | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    context_hints: dict[str, Any] = Field(default_factory=dict)
    trial_budget: dict[str, Any] = Field(default_factory=dict)

class AssistantConversationCreateRequest(BaseModel):
    user_id: str = "desktop-user"
    title: str | None = None


class AssistantMessageCreateRequest(BaseModel):
    message: str
    user_id: str = "desktop-user"
    title: str | None = None


def build_router(container: AppContainer) -> APIRouter:
    router = APIRouter(prefix="/api/agents", tags=["agents"])

    @router.post("/tasks")
    def enqueue_task(payload: AgentTaskCreate) -> dict[str, Any]:
        with container.session_factory() as session:
            task = TaskQueueRepository(session).enqueue(
                task_id=str(payload.payload.get("task_id") or payload.task_type),
                task_type=payload.task_type,
                priority=payload.priority,
                payload=dict(payload.payload or {}),
            )
            return {"task_id": task.id, "task_type": task.task_type, "priority": task.priority}

    @router.post("/run-once")
    def run_once() -> dict[str, Any]:
        return container.heartbeat.run_once()

    @router.get("/queue")
    def list_queue() -> list[dict[str, Any]]:
        with container.session_factory() as session:
            return [
                {
                    "task_id": item.id,
                    "task_type": item.task_type,
                    "status": item.status,
                    "priority": item.priority,
                    "payload": dict(item.payload or {}),
                }
                for item in TaskQueueRepository(session).list(limit=500, offset=0)
            ]

    @router.post("/queue/recover")
    def recover_queue() -> dict[str, Any]:
        with container.session_factory() as session:
            recovered = TaskQueueRepository(session).recover_stale_running()
            return {"recovered_count": recovered}

    @router.get("/heartbeat/status")
    def heartbeat_status() -> dict[str, Any]:
        return container.heartbeat.status()

    @router.post("/heartbeat/pause")
    def pause_heartbeat() -> dict[str, Any]:
        state = container.heartbeat.pause(reason="manual")
        return {"autonomous_paused": state.autonomous_paused, "pause_reason": state.pause_reason}

    @router.post("/heartbeat/resume")
    def resume_heartbeat() -> dict[str, Any]:
        state = container.heartbeat.resume()
        return {"autonomous_paused": state.autonomous_paused, "pause_reason": state.pause_reason}

    @router.get("")
    def list_agents() -> list[dict[str, Any]]:
        with container.session_factory() as session:
            return [_serialize_profile(_resolve_profile(session, kind)) for kind in BUILTIN_AGENT_KINDS]

    @router.get("/autonomous/goals")
    def list_autonomous_goals(
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            profile = _resolve_profile(session, "autonomous")
            from recruit_agent.models.domain import GoalSpec

            query = select(GoalSpec).where(GoalSpec.agent_profile_id == profile.id)
            if status is not None:
                query = query.where(GoalSpec.status == status)
            query = query.order_by(
                GoalSpec.last_activity_at.desc().nullslast(),
                GoalSpec.created_at.desc(),
                GoalSpec.id.desc(),
            ).offset(offset).limit(limit)
            return [GoalSpecRead.model_validate(item).model_dump(by_alias=True) for item in session.scalars(query).all()]

    @router.post("/autonomous/goals", status_code=201)
    def create_autonomous_goal(payload: AutonomousGoalCreateRequest) -> dict[str, Any]:
        with container.session_factory() as session:
            profile = _resolve_profile(session, "autonomous")
            agent_session = _ensure_agent_session(session, profile)
            open_run = _find_open_autonomous_run(session, session_id=agent_session.id)
            if open_run is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Autonomous already has an open run. Wait for it to finish or resume it before creating a new goal.",
                )

            constraints = dict(payload.constraints or {})
            scope_kind = str(constraints.get("scope_kind") or "").strip().lower()
            memory_scope_kind = str(constraints.get("memory_scope_kind") or "").strip().lower()
            if payload.jd_id:
                constraints.setdefault("jd_id", payload.jd_id)
            if payload.candidate_count_target is not None:
                constraints.setdefault("candidate_count_target", payload.candidate_count_target)
            if scope_kind == "global" or memory_scope_kind == "global":
                constraints.setdefault("scope_kind", "global")
                constraints.setdefault("scope_ref", SHARED_WORKSPACE_SCOPE_REF)
                constraints.setdefault("memory_scope_kind", "global")
                constraints.setdefault("memory_scope_ref", SHARED_WORKSPACE_SCOPE_REF)
                constraints.setdefault("global_scope_ref", SHARED_WORKSPACE_SCOPE_REF)
            requested_conversation_id = str(payload.conversation_id or "").strip() or None
            conversation_id = AUTONOMOUS_PRIMARY_CONVERSATION_ID
            parent_conversation_id = (
                requested_conversation_id
                if requested_conversation_id not in {None, "", AUTONOMOUS_PRIMARY_CONVERSATION_ID}
                else None
            )
            context_hints = dict(payload.context_hints or {})
            browser_target = derive_browser_target(
                existing=context_hints.get("browser_target"),
                structured_sources=(context_hints, constraints),
                text_sources=(payload.goal_text, payload.title),
            )
            if browser_target:
                context_hints["browser_target"] = browser_target
                constraints.setdefault("browser_target", browser_target)

            goal = GoalSpec(
                agent_profile_id=profile.id,
                title=payload.title,
                goal_text=payload.goal_text,
                goal_kind=payload.goal_kind,
                status="queued",
                source="operator",
                source_text=payload.goal_text,
                requested_by=payload.requested_by,
                constraints=constraints,
                success_criteria=dict(payload.success_criteria or {}),
                context_hints=context_hints,
                trial_budget=dict(payload.trial_budget or {}),
                run_preferences=dict(payload.run_preferences or {}),
                summary=payload.summary or f"围绕目标“{payload.title}”启动 Autonomous run。",
                last_activity_at=utcnow(),
                goal_metadata={
                    "created_from": "agents_api",
                    "agent_kind": "autonomous",
                    "overlay_parent_conversation_id": parent_conversation_id,
                },
            )
            session.add(goal)
            session.flush()

            run = AgentRun(
                session_id=agent_session.id,
                goal_spec_id=goal.id,
                job_description_id=payload.jd_id,
                platform="site",
                lane="agent",
                run_type=payload.goal_kind,
                status="queued",
                priority=payload.priority,
                context_manifest={
                    "goal": payload.goal_text,
                    "title": payload.title,
                    "requested_by": payload.requested_by,
                    "candidate_count_target": payload.candidate_count_target,
                    "conversation_id": conversation_id,
                    "parent_conversation_id": parent_conversation_id,
                    "goal_id": goal.id,
                    **({"browser_target": browser_target} if browser_target else {}),
                },
                runtime_metadata={
                    "goal_title": payload.title,
                    "goal_requested_by": payload.requested_by,
                    "jd_id": payload.jd_id,
                    "candidate_count_target": payload.candidate_count_target,
                    "conversation_id": conversation_id,
                    "parent_conversation_id": parent_conversation_id,
                    "goal_id": goal.id,
                    **({"browser_target": browser_target} if browser_target else {}),
                },
                run_id=uuid4().hex,
                agent_kind="autonomous",
            )
            session.add(run)
            session.flush()

            goal.latest_run_id = run.run_id
            agent_session.current_goal_id = goal.id
            agent_session.current_lane = run.lane
            agent_session.last_active_at = utcnow()

            envelope = _default_run_envelope(run=run, profile=profile, goal=goal)
            task = _enqueue_run_task(session, run=run, envelope=envelope)
            session.commit()
            session.refresh(goal)
            session.refresh(run)
            session.refresh(agent_session)
            return {
                "conversation_id": conversation_id,
                "conversationId": conversation_id,
                "goal_id": goal.id,
                "goalId": goal.id,
                "run_id": run.run_id,
                "runId": run.run_id,
                "status": goal.status,
                "goal": GoalSpecRead.model_validate(goal).model_dump(by_alias=True),
                "run": _serialize_run(run),
                "session": RuntimeSessionRead.model_validate(agent_session).model_dump(by_alias=True),
                "task_id": task.id,
            }

    @router.get("/shared-scene-templates")
    @router.get("/scene-templates")
    def list_scene_templates() -> list[dict[str, Any]]:
        return [serialize_scene_template(template) for template in shared_scene_template_catalog().values()]

    @router.post("/scene-templates/{template_key}/runs", status_code=202)
    def run_scene_template(template_key: str, payload: SceneTemplateRunRequest) -> dict[str, Any]:
        template = shared_scene_template_catalog().get(template_key)
        if template is None:
            raise HTTPException(status_code=404, detail=f"Unknown scene template: {template_key}")
        if bool(template.get("requires_jd")) and not str(payload.jd_id or "").strip():
            raise HTTPException(status_code=400, detail=f"Scene template requires jd_id: {template_key}")

        goal_title = str(payload.title or template["title"])
        goal_text = str(payload.goal_text or template["default_goal_text"])

        merged_constraints = {
            **dict(template.get("constraints") or {}),
            **dict(payload.constraints or {}),
        }
        merged_success_criteria = {
            **dict(template.get("success_criteria") or {}),
            **dict(payload.success_criteria or {}),
        }
        merged_context_hints = {
            **dict(template.get("context_hints") or {}),
            **dict(payload.context_hints or {}),
            "scene_template_key": template_key,
        }
        merged_trial_budget = {
            **dict(template.get("trial_budget") or {}),
            **dict(payload.trial_budget or {}),
        }
        action_payload = AutonomousGoalCreateRequest(
            title=goal_title,
            goal_text=goal_text,
            goal_kind=str(template["goal_kind"]),
            requested_by=payload.requested_by,
            jd_id=payload.jd_id,
            conversation_id=payload.conversation_id,
            candidate_count_target=(
                payload.candidate_count_target
                if payload.candidate_count_target is not None
                else template.get("default_candidate_count_target")
            ),
            summary=goal_text,
            constraints=merged_constraints,
            success_criteria=merged_success_criteria,
            context_hints=merged_context_hints,
            trial_budget=merged_trial_budget,
        )
        return create_autonomous_goal(action_payload)

    @router.get("/{kind}")
    def get_agent(kind: AgentKind) -> dict[str, Any]:
        with container.session_factory() as session:
            return _serialize_profile(_resolve_profile(session, kind))

    @router.patch("/{kind}")
    def update_agent(kind: AgentKind, payload: RecruitAgentProfileUpdate) -> dict[str, Any]:
        with container.session_factory() as session:
            repo = RecruitAgentProfileRepository(session)
            profile = _resolve_profile(session, kind)
            patch = payload.model_dump(exclude_unset=True)
            requested_key = patch.get("agent_key")
            if requested_key is not None and requested_key != kind:
                raise HTTPException(status_code=400, detail="Built-in agent key is immutable.")
            expected_primary = kind == "autonomous"
            requested_primary = patch.get("is_primary")
            if requested_primary is not None and bool(requested_primary) != expected_primary:
                raise HTTPException(status_code=400, detail="Built-in agent primary state is immutable.")
            patch["agent_key"] = kind
            patch["is_primary"] = expected_primary
            if isinstance(patch.get("role_definition"), dict):
                role_definition = dict(profile.role_definition or {})
                role_definition.update(dict(patch["role_definition"] or {}))
                patch["role_definition"] = role_definition
            if isinstance(patch.get("prompt_config"), dict):
                prompt_config = dict(profile.prompt_config or {})
                prompt_config.update(dict(patch["prompt_config"] or {}))
                prompt_config["context_policy"] = resolve_context_policy(prompt_config)
                patch["prompt_config"] = prompt_config
            if isinstance(patch.get("memory_policy"), dict):
                memory_policy = dict(profile.memory_policy or {})
                memory_policy.update(dict(patch["memory_policy"] or {}))
                patch["memory_policy"] = resolve_memory_policy(memory_policy)
            updated = repo.update(profile, patch)
            session.commit()
            session.refresh(updated)
            return _serialize_profile(updated)

    @router.get("/{kind}/workspace")
    def get_agent_workspace(kind: AgentKind) -> dict[str, Any]:
        with container.session_factory() as session:
            profile = _resolve_profile(session, kind)
            return _serialize_workspace(session, container=container, profile=profile, kind=kind)

    @router.post("/assistant/conversations", status_code=201)
    def create_assistant_conversation(payload: AssistantConversationCreateRequest) -> dict[str, Any]:
        conversation = container.assistant_adapter.create_conversation(user_id=payload.user_id, title=payload.title)
        return _serialize_assistant_conversation_summary(
            container=container,
            conversation=conversation,
        )

    @router.post("/assistant/conversations/{conversation_id}/messages", status_code=202)
    def send_assistant_message(conversation_id: str, payload: AssistantMessageCreateRequest) -> dict[str, Any]:
        with container.session_factory() as session:
            _resolve_profile(session, "assistant")
            active_turn = container.assistant_adapter.active_turns.get(conversation_id)
            if active_turn is not None and active_turn.worker.is_alive():
                raise HTTPException(status_code=409, detail="Assistant conversation already has an active turn.")
            conversation = _ensure_assistant_conversation(
                session,
                container=container,
                conversation_id=conversation_id,
                user_id=payload.user_id,
                title=payload.title or _trim_title(payload.message),
            )
            session.commit()
            resolved_conversation_id = conversation.conversation_id

        request_id = uuid4().hex
        Thread(
            target=_drain_assistant_turn_stream,
            kwargs={
                "container": container,
                "conversation_id": resolved_conversation_id,
                "message": payload.message,
            },
            daemon=True,
        ).start()
        return {
            "conversation_id": resolved_conversation_id,
            "conversationId": resolved_conversation_id,
            "request_id": request_id,
            "requestId": request_id,
            "status": "accepted",
        }

    @router.get("/{kind}/conversations/{conversation_id}")
    def get_agent_conversation(kind: AgentKind, conversation_id: str) -> dict[str, Any]:
        with container.session_factory() as session:
            _resolve_profile(session, kind)
            return _serialize_conversation_record(
                session,
                container=container,
                kind=kind,
                conversation_id=conversation_id,
            )

    @router.get("/{kind}/runs")
    def list_runs(
        kind: AgentKind,
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            profile = _resolve_profile(session, kind)
            agent_session = _get_agent_session(session, profile)
            if agent_session is None:
                return []
            stmt = (
                select(AgentRun)
                .where(
                    AgentRun.session_id == agent_session.id,
                    AgentRun.agent_kind == kind,
                )
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .offset(offset)
                .limit(limit)
            )
            if status is not None:
                stmt = stmt.where(AgentRun.status == status)
            return [_serialize_run(item) for item in session.scalars(stmt).all()]

    @router.get("/{kind}/runs/{run_id}")
    def get_run(kind: AgentKind, run_id: str) -> dict[str, Any]:
        with container.session_factory() as session:
            run = _resolve_run_for_kind(session, kind, run_id)
            turns = _list_turns(session, run)
            events = _list_run_events(session, run)
            return {
                "run": _serialize_run(run),
                "turns": turns,
                "events": events,
            }

    @router.get("/{kind}/runs/{run_id}/turns")
    def list_turns(kind: AgentKind, run_id: str) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            run = _resolve_run_for_kind(session, kind, run_id)
            return _list_turns(session, run)

    @router.post("/autonomous/runs/{run_id}/cancel")
    def cancel_run(run_id: str, payload: RunControlRequest) -> dict[str, Any]:
        with container.session_factory() as session:
            run = _resolve_run_for_kind(session, "autonomous", run_id)
            if run.status == "completed":
                raise HTTPException(status_code=409, detail="Completed run cannot be cancelled.")
            run.status = "cancelled"
            run.finished_at = utcnow()
            run.blocked_reason = payload.reason or run.blocked_reason
            _cancel_open_queue_tasks(session, run=run, reviewer=payload.reviewer, reason=payload.reason)
            _resolve_run_gate_records(
                session,
                run=run,
                reviewer=payload.reviewer,
                reason=payload.reason or "cancelled",
                approval_status="rejected",
                interaction_action="cancel",
            )
            _update_goal_status(session, run=run, status="cancelled")
            session.commit()
            session.refresh(run)
            return {"run": _serialize_run(run)}

    @router.post("/autonomous/runs/{run_id}/resume")
    def resume_run(run_id: str, payload: RunControlRequest) -> dict[str, Any]:
        with container.session_factory() as session:
            run = _resolve_run_for_kind(session, "autonomous", run_id)
            if run.status == "completed":
                raise HTTPException(status_code=409, detail="Completed run cannot be resumed.")
            if str(run.status or "").strip().lower() in {"queued", "running", "active"}:
                raise HTTPException(status_code=409, detail="Active run does not need resume.")
            conflicting_run = _find_open_autonomous_run(session, session_id=run.session_id, exclude_run_id=run.id)
            if conflicting_run is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Autonomous already has another open run. Resolve it before resuming this one.",
                )
            checkpoint = _resolve_run_gate_records(
                session,
                run=run,
                reviewer=payload.reviewer,
                reason=payload.reason or "manual resume",
                approval_status="approved",
                interaction_action="resume",
            )
            profile = _resolve_profile(session, "autonomous")
            goal = _get_goal(session, run.goal_spec_id)
            envelope = _resume_envelope_for_run(run=run, profile=profile, checkpoint=checkpoint, goal=goal)
            run.status = "queued"
            run.finished_at = None
            run.blocked_reason = None
            run.checkpoint_status = "resolved" if checkpoint is not None else "none"
            run.wakeup_state = {
                "resumed_at": utcnow().isoformat(),
                "resumed_by": payload.reviewer,
                "checkpoint_id": None if checkpoint is None else checkpoint.id,
            }
            _update_goal_status(session, run=run, status="queued")
            task = _enqueue_run_task(session, run=run, envelope=envelope)
            session.commit()
            session.refresh(run)
            return {"run": _serialize_run(run), "task_id": task.id}

    @router.get("/{kind}/approvals")
    def list_agent_approvals(
        kind: AgentKind,
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            _resolve_profile(session, kind)
            stmt = select(ApprovalItem).order_by(ApprovalItem.created_at.desc(), ApprovalItem.id.desc())
            if status is None:
                stmt = stmt.where(ApprovalItem.status == "pending")
            else:
                stmt = stmt.where(ApprovalItem.status == status)
            items = [
                item
                for item in session.scalars(stmt).all()
                if _approval_belongs_to_kind(session, item, kind)
            ]
            return [_serialize_approval(item) for item in items[offset : offset + limit]]

    @router.get("/{kind}/memory/{scope}")
    def list_memory(
        kind: AgentKind,
        scope: MemoryScope,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            profile = _resolve_profile(session, kind)
            if scope == "candidate":
                candidate_items = CandidatePersonMemoryRepository(session).list_for_agent(profile.id, limit=limit, offset=offset)
                return [CandidateMemoryRead.model_validate(item).model_dump(by_alias=True) for item in candidate_items]
            if scope == "job":
                job_items = JobDescriptionMemoryRepository(session).list_for_agent(profile.id, limit=limit, offset=offset)
                return [JobMemoryRead.model_validate(item).model_dump(by_alias=True) for item in job_items]

            stmt = (
                select(AgentGlobalMemory)
                .where(AgentGlobalMemory.agent_profile_id == profile.id)
                .order_by(AgentGlobalMemory.updated_at.desc(), AgentGlobalMemory.id.asc())
                .offset(offset)
                .limit(limit)
            )
            if kind == "autonomous":
                ensure_global_memory(session, agent_profile_id=profile.id)
            global_items = session.scalars(stmt).all()
            return [AgentGlobalMemoryRead.model_validate(item).model_dump(by_alias=True) for item in global_items]

    @router.get("/{kind}/skills")
    def list_agent_skills(kind: AgentKind) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            _resolve_profile(session, kind)
            stmt = (
                select(Skill)
                .where(Skill.status.in_(("trial", "active")))
                .order_by(Skill.name.asc(), Skill.id.asc())
            )
            return [SkillRead.model_validate(item).model_dump(by_alias=True) for item in session.scalars(stmt).all()]

    @router.get("/{kind}/mcp")
    def list_agent_mcps(kind: AgentKind) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            _resolve_profile(session, kind)
        return [
            McpServerRead.model_validate(item).model_dump(by_alias=True)
            for item in container.mcp_registry.list_servers()
            if bool(item.get("enabled"))
        ]

    return router


def _serialize_profile(profile: RecruitAgentProfile) -> dict[str, Any]:
    payload = RecruitAgentProfileRead.model_validate(
        {
            "id": profile.id,
            "agent_key": profile.agent_key,
            "name": profile.name,
            "status": profile.status,
            "description": profile.description,
            "is_primary": profile.is_primary,
            "role_definition": dict(profile.role_definition or {}),
            "prompt_config": dict(profile.prompt_config or {}),
            "playbook_blueprint": dict(profile.playbook_blueprint or {}),
            "memory_policy": dict(profile.memory_policy or {}),
            "dashboard_config": dict(profile.dashboard_config or {}),
            "channel_config": dict(profile.channel_config or {}),
            "agent_metadata": dict(profile.agent_metadata or {}),
            "created_at": int(_timestamp_sort_value(profile.created_at)),
            "updated_at": int(_timestamp_sort_value(profile.updated_at)),
        }
    ).model_dump(by_alias=True)
    payload["kind"] = profile.agent_key
    return payload


def _serialize_run(run: AgentRun) -> dict[str, Any]:
    payload = RuntimeControlledRunRead.model_validate(run).model_dump(by_alias=True)
    payload["run_id"] = run.run_id
    payload["runId"] = run.run_id
    payload["agent_kind"] = run.agent_kind
    payload["turns_count"] = run.turns_count
    payload["prompt_tokens"] = run.prompt_tokens
    payload["completion_tokens"] = run.completion_tokens
    payload["cache_hit_tokens"] = run.cache_hit_tokens
    payload["wakeup_state"] = dict(run.wakeup_state or {})
    payload["title"] = _run_title(run)
    payload["summary"] = _run_summary(run)
    if run.agent_kind == "autonomous":
        payload["conversation_id"] = AUTONOMOUS_PRIMARY_CONVERSATION_ID
        payload["conversationId"] = AUTONOMOUS_PRIMARY_CONVERSATION_ID
        payload["ref_id"] = AUTONOMOUS_PRIMARY_CONVERSATION_ID
        payload["refId"] = AUTONOMOUS_PRIMARY_CONVERSATION_ID
    else:
        payload["ref_id"] = run.run_id
        payload["refId"] = run.run_id
    return payload


def _serialize_approval(approval: ApprovalItem) -> dict[str, Any]:
    payload = ApprovalRead.model_validate(approval).model_dump(by_alias=True)
    payload["source_kind"] = approval.source_kind
    payload["run_pk"] = approval.run_pk
    payload["turn_pk"] = approval.turn_pk
    payload["tool_name"] = approval.tool_name
    return payload


def _serialize_turn(turn: AgentTurnRecord) -> dict[str, Any]:
    return {
        "id": turn.id,
        "turn_id": turn.turn_id,
        "turnId": turn.turn_id,
        "seq": turn.seq,
        "trigger_type": turn.trigger_type,
        "status": turn.status,
        "phase": turn.phase,
        "outcome_kind": turn.outcome_kind,
        "prompt_tokens": turn.prompt_tokens,
        "completion_tokens": turn.completion_tokens,
        "cache_hit_tokens": turn.cache_hit_tokens,
        "turn_metadata": dict(turn.turn_metadata or {}),
        "created_at": turn.created_at,
        "updated_at": turn.updated_at,
    }


def _list_turns(session: Session, run: AgentRun) -> list[dict[str, Any]]:
    stmt = select(AgentTurnRecord).where(AgentTurnRecord.run_pk == run.id).order_by(AgentTurnRecord.seq.asc())
    return [_serialize_turn(item) for item in session.scalars(stmt).all()]


def _list_run_events(session: Session, run: AgentRun) -> list[dict[str, Any]]:
    stmt = (
        select(AgentRuntimeEvent)
        .where(AgentRuntimeEvent.run_id == run.id)
        .order_by(AgentRuntimeEvent.occurred_at.desc(), AgentRuntimeEvent.id.desc())
        .limit(100)
    )
    items = list(session.scalars(stmt).all())
    items.reverse()
    return [RuntimeEventRead.model_validate(item).model_dump(by_alias=True) for item in items]


def _resolve_profile(session: Session, kind: str) -> RecruitAgentProfile:
    if kind not in BUILTIN_AGENT_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown agent kind: {kind}")
    profile = RecruitAgentProfileRepository(session).by_agent_key(kind)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Agent profile not found: {kind}")
    return profile


def _get_agent_session(session: Session, profile: RecruitAgentProfile) -> AgentSession | None:
    stmt = (
        select(AgentSession)
        .where(
            AgentSession.agent_profile_id == profile.id,
            AgentSession.session_key == "primary",
        )
        .order_by(AgentSession.updated_at.desc(), AgentSession.id.asc())
    )
    return session.scalars(stmt).first()


def _ensure_agent_session(session: Session, profile: RecruitAgentProfile) -> AgentSession:
    existing = _get_agent_session(session, profile)
    if existing is not None:
        return existing
    item = AgentSession(agent_profile_id=profile.id, session_key="primary", status="active")
    session.add(item)
    session.flush()
    return item


def _resolve_run_for_kind(session: Session, kind: AgentKind, run_id: str) -> AgentRun:
    stmt = select(AgentRun).where(AgentRun.run_id == run_id)
    run = session.scalars(stmt).first()
    if run is None:
        run = session.get(AgentRun, run_id)
    if run is None or run.agent_kind != kind:
        raise HTTPException(status_code=404, detail=f"Run not found for agent kind: {kind}")
    profile = _resolve_profile(session, kind)
    agent_session = session.get(AgentSession, run.session_id)
    if agent_session is None or agent_session.agent_profile_id != profile.id:
        raise HTTPException(status_code=404, detail=f"Run not found for agent kind: {kind}")
    return run


def _find_open_autonomous_run(
    session: Session,
    *,
    session_id: str,
    exclude_run_id: str | None = None,
) -> AgentRun | None:
    stmt = (
        select(AgentRun)
        .where(
            AgentRun.session_id == session_id,
            AgentRun.agent_kind == "autonomous",
            AgentRun.status.in_(AUTONOMOUS_OPEN_RUN_STATUSES),
        )
        .order_by(AgentRun.updated_at.desc(), AgentRun.id.desc())
    )
    if exclude_run_id is not None:
        stmt = stmt.where(AgentRun.id != exclude_run_id)
    return session.scalars(stmt).first()


def _approval_belongs_to_kind(session: Session, approval: ApprovalItem, kind: AgentKind) -> bool:
    if approval.source_kind == kind:
        return True
    if approval.run_pk:
        run = session.get(AgentRun, approval.run_pk)
        if run is not None and run.agent_kind == kind:
            return True
    payload = dict(approval.payload or {})
    return str(payload.get("agent_kind") or payload.get("source_kind") or "").strip() == kind


def _default_run_envelope(
    *,
    run: AgentRun,
    profile: RecruitAgentProfile,
    goal: Any,
) -> dict[str, Any]:
    constraints = dict(getattr(goal, "constraints", {}) or {})
    context_hints = dict(getattr(goal, "context_hints", {}) or {})
    browser_target = derive_browser_target(
        existing=context_hints.get("browser_target") or constraints.get("browser_target") or (run.context_manifest or {}).get("browser_target"),
        structured_sources=(context_hints, constraints, run.context_manifest, run.runtime_metadata),
        text_sources=((run.context_manifest or {}).get("goal"), getattr(goal, "goal_text", None), getattr(goal, "title", None)),
    )
    scope_kind = "job" if run.job_description_id else str(constraints.get("scope_kind") or "global")
    scope_ref = (
        run.job_description_id
        or str(constraints.get("scope_ref") or "")
        or profile.id
    )
    return {
        "run_pk": run.id,
        "run_id": run.run_id,
        "scope_kind": scope_kind,
        "scope_ref": scope_ref,
        "trigger_type": "goal_created",
        "world_snapshot": {
            "goal_id": goal.id,
            "goal_title": goal.title,
            "requested_by": goal.requested_by,
            **({"browser_target": browser_target} if browser_target else {}),
        },
        "metadata": {
            "agent_kind": run.agent_kind,
            "goal_spec_id": goal.id,
            **({"browser_target": browser_target} if browser_target else {}),
        },
    }


def _resume_envelope_for_run(
    *,
    run: AgentRun,
    profile: RecruitAgentProfile,
    checkpoint: AgentRunCheckpoint | None,
    goal: Any | None,
) -> dict[str, Any]:
    if checkpoint is not None:
        checkpoint_payload = dict(checkpoint.payload or {})
        resume_task = checkpoint_payload.get("resume_task")
        if isinstance(resume_task, dict) and isinstance(resume_task.get("payload"), dict):
            payload = dict(resume_task.get("payload") or {})
            payload["trigger_type"] = "resume"
            return payload
    if goal is not None:
        return _default_run_envelope(run=run, profile=profile, goal=goal)
    return {
        "run_pk": run.id,
        "run_id": run.run_id,
        "scope_kind": "global",
        "scope_ref": profile.id,
        "trigger_type": "resume",
    }


def _enqueue_run_task(session: Session, *, run: AgentRun, envelope: dict[str, Any]) -> TaskQueueItem:
    task_id = run.queue_task_id or f"run-{run.id}"
    task = TaskQueueRepository(session).enqueue(
        task_id=task_id,
        task_type="autonomous_turn",
        priority=int(run.priority or 100),
        payload=envelope,
    )
    run.queue_task_id = task.id
    return task


def _cancel_open_queue_tasks(session: Session, *, run: AgentRun, reviewer: str, reason: str | None) -> None:
    stmt = select(TaskQueueItem).where(TaskQueueItem.status.in_(("pending", "running")))
    for task in session.scalars(stmt).all():
        payload = dict(task.payload or {})
        if str(payload.get("run_pk") or "") == run.id or str(payload.get("run_id") or "") == str(run.run_id or ""):
            task.status = "failed"
            task.locked_at = None
            task.locked_by = None
            audit = dict((payload.get("queue_audit") or {})) if isinstance(payload.get("queue_audit"), dict) else {}
            history = list(audit.get("history") or [])
            history.append(
                {
                    "kind": "cancelled",
                    "at": utcnow().isoformat(),
                    "reviewer": reviewer,
                    "reason": reason,
                }
            )
            audit["history"] = history[-20:]
            audit["last_event"] = "cancelled"
            audit["last_event_at"] = history[-1]["at"]
            payload["queue_audit"] = audit
            task.payload = payload


def _resolve_run_gate_records(
    session: Session,
    *,
    run: AgentRun,
    reviewer: str,
    reason: str,
    approval_status: Literal["approved", "rejected"],
    interaction_action: str,
) -> AgentRunCheckpoint | None:
    checkpoint = session.scalars(
        select(AgentRunCheckpoint)
        .where(AgentRunCheckpoint.run_id == run.id, AgentRunCheckpoint.status == "open")
        .order_by(AgentRunCheckpoint.created_at.desc(), AgentRunCheckpoint.id.desc())
    ).first()
    if checkpoint is None:
        return None

    checkpoint.status = "resolved"
    checkpoint.resolved_at = utcnow()
    checkpoint.resolved_by = reviewer

    if checkpoint.approval_id:
        approval = session.get(ApprovalItem, checkpoint.approval_id)
        if approval is not None:
            approval.status = approval_status
            approval.reviewed_by = reviewer
            approval.reviewed_at = utcnow()
            approval.notes = reason
            approval_payload = dict(approval.payload or {})
            approval_payload["resolution"] = {
                "status": approval_status,
                "reviewer": reviewer,
                "reason": reason,
                "approved": approval_status == "approved",
                "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None,
            }
            approval.payload = approval_payload

    interaction = session.scalars(
        select(OperatorInteraction)
        .where(OperatorInteraction.checkpoint_id == checkpoint.id, OperatorInteraction.status == "pending")
        .order_by(OperatorInteraction.created_at.desc(), OperatorInteraction.id.desc())
    ).first()
    if interaction is not None:
        interaction.status = "resolved"
        interaction.operator_response = {"action": interaction_action, "comment": reason}
        interaction.effect_summary = reason
        interaction.resolved_at = utcnow()
        interaction.resolved_by = reviewer

    return checkpoint


def _update_goal_status(session: Session, *, run: AgentRun, status: str) -> None:
    goal = _get_goal(session, run.goal_spec_id)
    if goal is None:
        return
    goal.status = status
    goal.latest_run_id = run.run_id
    goal.last_activity_at = utcnow()


def _get_goal(session: Session, goal_id: str | None) -> Any | None:
    if not goal_id:
        return None

    return session.get(GoalSpec, goal_id)


def _serialize_workspace(
    session: Session,
    *,
    container: AppContainer,
    profile: RecruitAgentProfile,
    kind: AgentKind,
) -> dict[str, Any]:
    provider_label, model_label = _overlay_provider_labels(container)
    approvals = _list_pending_approvals(session, kind)
    memories = _list_memory_summaries(session, profile)
    if kind == "assistant":
        conversations = session.scalars(
            select(ConversationSession)
            .order_by(
                ConversationSession.last_active_at.desc().nullslast(),
                ConversationSession.updated_at.desc(),
                ConversationSession.id.desc(),
            )
            .limit(20)
        ).all()
        serialized_conversations = [
            _assistant_conversation_summary_from_session(session, conversation)
            for conversation in conversations
        ]
        latest = serialized_conversations[0] if serialized_conversations else None
        return {
            "agent": _workspace_agent_payload(
                profile=profile,
                status=None if latest is None else latest["status"],
                active_task=None if latest is None else latest.get("preview"),
                active_goal=None if latest is None else latest.get("title"),
                default_model=model_label,
                pending_approvals=len(approvals),
            ),
            "conversations": serialized_conversations,
            "runs": [_assistant_run_from_conversation(item) for item in serialized_conversations[:8]],
            "approvals": approvals,
            "memories": memories,
            "skills": _list_workspace_skills(session),
            "tools": _list_workspace_tools(container),
            "config": _workspace_config(profile, provider_label=provider_label, model_label=model_label),
        }

    latest_goal = session.scalars(
        select(GoalSpec)
        .where(GoalSpec.agent_profile_id == profile.id)
        .order_by(
            GoalSpec.last_activity_at.desc().nullslast(),
            GoalSpec.created_at.desc(),
            GoalSpec.id.desc(),
        )
        .limit(1)
    ).first()
    runs = _list_workspace_runs(session, profile, kind)
    latest_run = runs[0] if runs else None
    return {
        "agent": _workspace_agent_payload(
            profile=profile,
            status=None if latest_run is None else latest_run["status"],
            active_task=None if latest_run is None else latest_run.get("summary"),
            active_goal=(
                latest_goal.title
                if latest_goal is not None
                else None if latest_run is None else str(latest_run.get("title") or "")
            ),
            default_model=model_label,
            pending_approvals=len(approvals),
        ),
        "conversations": [
            _autonomous_primary_conversation_summary(
                profile=profile,
                latest_goal=latest_goal,
                latest_run=latest_run,
            )
        ],
        "runs": runs,
        "approvals": approvals,
        "memories": memories,
        "skills": _list_workspace_skills(session),
        "tools": _list_workspace_tools(container),
        "config": _workspace_config(profile, provider_label=provider_label, model_label=model_label),
    }


def _serialize_conversation_record(
    session: Session,
    *,
    container: AppContainer,
    kind: AgentKind,
    conversation_id: str,
) -> dict[str, Any]:
    if kind == "assistant":
        conversation = session.scalars(
            select(ConversationSession).where(ConversationSession.conversation_id == conversation_id)
        ).first()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found for agent kind: assistant")
        turns = session.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_pk == conversation.id)
            .order_by(ConversationTurn.seq.asc(), ConversationTurn.id.asc())
        ).all()
        return {
            "conversation": _assistant_conversation_summary_from_session(session, conversation),
            "messages": [
                _assistant_conversation_message(conversation.conversation_id, turn)
                for turn in turns
            ],
        }

    profile = _resolve_profile(session, "autonomous")
    if conversation_id == AUTONOMOUS_PRIMARY_CONVERSATION_ID:
        return _serialize_autonomous_primary_conversation_record(session, profile=profile)

    goal = session.get(GoalSpec, conversation_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Conversation not found for agent kind: autonomous")
    messages: list[dict[str, Any]] = [_autonomous_goal_message(conversation_id, goal)]
    run = None if not goal.latest_run_id else _resolve_run_for_kind(session, "autonomous", goal.latest_run_id)
    if run is not None:
        messages.append(_autonomous_run_message(goal.id, run, goal))
        messages = sorted(messages, key=_agent_message_sort_key)
    return {
        "conversation": _autonomous_goal_conversation_summary(goal),
        "messages": messages,
    }


def _serialize_assistant_conversation_summary(
    *,
    container: AppContainer,
    conversation: ConversationSession,
) -> dict[str, Any]:
    with container.session_factory() as session:
        refreshed = session.get(ConversationSession, conversation.id) or session.scalars(
            select(ConversationSession).where(ConversationSession.conversation_id == conversation.conversation_id)
        ).first()
        if refreshed is None:
            raise HTTPException(status_code=404, detail="Conversation not found for agent kind: assistant")
        return _assistant_conversation_summary_from_session(session, refreshed)


def _workspace_agent_payload(
    *,
    profile: RecruitAgentProfile,
    status: str | None,
    active_task: str | None,
    active_goal: str | None,
    default_model: str | None,
    pending_approvals: int,
) -> dict[str, Any]:
    payload = _serialize_profile(profile)
    resolved_status = str(status or profile.status or "idle")
    payload["status"] = resolved_status
    payload["health"] = _workspace_health(resolved_status)
    payload["active_task"] = active_task
    payload["activeTask"] = active_task
    payload["active_goal"] = active_goal
    payload["activeGoal"] = active_goal
    payload["default_model"] = default_model
    payload["defaultModel"] = default_model
    payload["pending_approvals"] = pending_approvals
    payload["pendingApprovals"] = pending_approvals
    payload["unread_count"] = 0
    payload["unreadCount"] = 0
    return payload


def _workspace_config(
    profile: RecruitAgentProfile,
    *,
    provider_label: str | None,
    model_label: str | None,
) -> dict[str, Any]:
    prompt_config = dict(profile.prompt_config or {})
    role_definition = dict(profile.role_definition or {})
    boundaries = role_definition.get("boundaries")
    if not isinstance(boundaries, list):
        boundaries = role_definition.get("forbiddenActions") or role_definition.get("forbidden_actions") or prompt_config.get("boundaries") or []
    return {
        "system_prompt": str(
            prompt_config.get("systemPrompt")
            or prompt_config.get("system_prompt")
            or prompt_config.get("prompt")
            or profile.description
            or ""
        ),
        "goal_template": str(
            role_definition.get("goalTemplate")
            or role_definition.get("goal_template")
            or prompt_config.get("goalTemplate")
            or prompt_config.get("goal_template")
            or ""
        ),
        "scoring_rubric": str(
            prompt_config.get("scoringRubric")
            or prompt_config.get("scoring_rubric")
            or prompt_config.get("rubric")
            or prompt_config.get("rubric_text")
            or ""
        ),
        "boundaries": [str(item) for item in list(boundaries or []) if str(item).strip()],
        "provider_label": provider_label,
        "providerLabel": provider_label,
        "model_label": model_label,
        "modelLabel": model_label,
    }


def _overlay_provider_labels(container: AppContainer) -> tuple[str | None, str | None]:
    settings = container.settings.provider_runtime_settings()
    if settings.openai_api_key:
        return "OpenAI Compatible", settings.openai_model
    if settings.anthropic_api_key:
        return "Anthropic", settings.anthropic_model
    if settings.openai_model:
        return "OpenAI Compatible", settings.openai_model
    if settings.anthropic_model:
        return "Anthropic", settings.anthropic_model
    return None, None


def _workspace_health(status: str) -> str:
    normalized = status.strip().lower()
    if normalized in {"failed", "cancelled", "error", "interrupted"}:
        return "critical"
    if normalized in {"waiting_human", "blocked", "idle", "draft"}:
        return "warning"
    return "healthy"


def _workspace_status(status: str | None) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"queued", "running", "active"}:
        return "active"
    if normalized in {"waiting_human", "pending"}:
        return "waiting_human"
    if normalized in {"blocked", "paused"}:
        return "blocked"
    if normalized in {"completed", "approved", "resolved"}:
        return "completed"
    if normalized in {"failed", "cancelled", "rejected", "interrupted", "error"}:
        return "failed"
    if normalized in {"draft", "idle"}:
        return normalized
    return str(status or "idle")


def _serialize_timestamp(value: Any) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int)):
        return value
    return str(value)


def _assistant_conversation_summary_from_session(session: Session, conversation: ConversationSession) -> dict[str, Any]:
    latest_turn = session.scalars(
        select(ConversationTurn)
        .where(ConversationTurn.conversation_pk == conversation.id)
        .order_by(ConversationTurn.seq.desc(), ConversationTurn.id.desc())
    ).first()
    preview = None if latest_turn is None else _assistant_turn_text(latest_turn)
    title = str(conversation.title or preview or "Assistant").strip() or "Assistant"
    status = _workspace_status(conversation.status if latest_turn is None else latest_turn.status)
    return {
        "id": conversation.conversation_id,
        "conversation_id": conversation.conversation_id,
        "conversationId": conversation.conversation_id,
        "agent_kind": "assistant",
        "agentKind": "assistant",
        "title": title,
        "preview": preview or conversation.context_summary,
        "status": status,
        "unread_count": 0,
        "unreadCount": 0,
        "updated_at": _serialize_timestamp(conversation.last_active_at or conversation.updated_at),
        "updatedAt": _serialize_timestamp(conversation.last_active_at or conversation.updated_at),
        "ref_id": None if latest_turn is None else latest_turn.turn_id,
        "refId": None if latest_turn is None else latest_turn.turn_id,
    }


def _assistant_conversation_message(conversation_id: str, turn: ConversationTurn) -> dict[str, Any]:
    kind = "message"
    if turn.tool_results and not str((turn.content or {}).get("text") or "").strip():
        kind = "tool_result"
    if turn.status in {"waiting_human", "failed", "cancelled"} and turn.role != "user":
        kind = "status"
    return {
        "id": turn.turn_id,
        "conversation_id": conversation_id,
        "conversationId": conversation_id,
        "role": turn.role,
        "kind": kind,
        "content": _assistant_turn_text(turn),
        "created_at": _serialize_timestamp(turn.created_at),
        "createdAt": _serialize_timestamp(turn.created_at),
        "status": turn.status,
        "metadata": {
            "turn_id": turn.turn_id,
            "seq": turn.seq,
            "tool_calls": list(turn.tool_calls or []),
            "tool_results": list(turn.tool_results or []),
            "turn_metadata": dict(turn.turn_metadata or {}),
        },
    }


def _assistant_turn_text(turn: ConversationTurn) -> str:
    text = str((turn.content or {}).get("text") or "").strip()
    if text:
        return text
    if turn.status == "waiting_human":
        return "Assistant is waiting for desktop approval before continuing."
    if turn.status == "running":
        return "Assistant is processing the request."
    if turn.status == "failed":
        return str((turn.turn_metadata or {}).get("error") or "Assistant request failed.")
    if turn.status == "cancelled":
        return str(turn.cancel_reason or "Assistant request was cancelled.")
    if turn.tool_results:
        first = turn.tool_results[0]
        if isinstance(first, dict):
            return str(first.get("output") or first.get("tool_name") or "Assistant tool call completed.")
    if turn.tool_calls:
        first = turn.tool_calls[0]
        if isinstance(first, dict):
            return f"Assistant requested tool {first.get('name') or first.get('tool_name') or 'call'}."
    return "Assistant message recorded."


def _assistant_run_from_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": conversation["id"],
        "run_id": conversation["id"],
        "runId": conversation["id"],
        "agent_kind": "assistant",
        "agentKind": "assistant",
        "title": conversation["title"],
        "status": conversation["status"],
        "summary": conversation.get("preview"),
        "started_at": None,
        "startedAt": None,
        "updated_at": conversation.get("updated_at"),
        "updatedAt": conversation.get("updatedAt"),
        "ref_id": conversation["id"],
        "refId": conversation["id"],
    }


def _autonomous_goal_conversation_summary(goal: GoalSpec) -> dict[str, Any]:
    updated_at = _serialize_timestamp(goal.last_activity_at or goal.updated_at)
    status = _workspace_status(goal.status)
    preview = _goal_summary(goal)
    return {
        "id": goal.id,
        "conversation_id": goal.id,
        "conversationId": goal.id,
        "agent_kind": "autonomous",
        "agentKind": "autonomous",
        "title": goal.title,
        "preview": preview,
        "status": status,
        "unread_count": 0,
        "unreadCount": 0,
        "updated_at": updated_at,
        "updatedAt": updated_at,
        "ref_id": goal.latest_run_id or goal.id,
        "refId": goal.latest_run_id or goal.id,
    }


def _autonomous_primary_conversation_summary(
    *,
    profile: RecruitAgentProfile,
    latest_goal: GoalSpec | None,
    latest_run: dict[str, Any] | None,
) -> dict[str, Any]:
    updated_at = (
        None if latest_run is None else latest_run.get("updatedAt")
    ) or _serialize_timestamp(
        None if latest_goal is None else (latest_goal.last_activity_at or latest_goal.updated_at)
    ) or _serialize_timestamp(profile.updated_at)
    status = _workspace_status(None if latest_run is None else latest_run.get("status"))
    if status == "idle" and latest_goal is not None:
        status = _workspace_status(latest_goal.status)
    preview = (
        None if latest_run is None else str(latest_run.get("summary") or "").strip()
    ) or (
        None if latest_goal is None else _goal_summary(latest_goal)
    ) or str(profile.description or "").strip() or None
    return {
        "id": AUTONOMOUS_PRIMARY_CONVERSATION_ID,
        "conversation_id": AUTONOMOUS_PRIMARY_CONVERSATION_ID,
        "conversationId": AUTONOMOUS_PRIMARY_CONVERSATION_ID,
        "agent_kind": "autonomous",
        "agentKind": "autonomous",
        "title": str(profile.name or "Autonomous").strip() or "Autonomous",
        "preview": preview,
        "status": status,
        "unread_count": 0,
        "unreadCount": 0,
        "updated_at": updated_at,
        "updatedAt": updated_at,
        "ref_id": None if latest_run is None else latest_run.get("runId"),
        "refId": None if latest_run is None else latest_run.get("runId"),
    }


def _autonomous_goal_message(conversation_id: str, goal: GoalSpec) -> dict[str, Any]:
    created_at = _serialize_timestamp(goal.created_at)
    return {
        "id": f"{goal.id}:goal",
        "conversation_id": conversation_id,
        "conversationId": conversation_id,
        "role": "system",
        "kind": "status",
        "title": goal.title,
        "content": _goal_summary(goal) or goal.title,
        "created_at": created_at,
        "createdAt": created_at,
        "status": _workspace_status(goal.status),
        "metadata": {
            "message_type": "goal",
            "goal_id": goal.id,
            "goal_kind": goal.goal_kind,
            "requested_by": goal.requested_by,
            "latest_run_id": goal.latest_run_id,
            "constraints": dict(goal.constraints or {}),
        },
    }


def _autonomous_run_message(conversation_id: str, run: AgentRun, goal: GoalSpec | None) -> dict[str, Any]:
    created_at = _serialize_timestamp(run.created_at)
    return {
        "id": f"{conversation_id}:run:{run.run_id or run.id}",
        "conversation_id": conversation_id,
        "conversationId": conversation_id,
        "role": "system",
        "kind": "status",
        "title": goal.title if goal is not None else _run_title(run),
        "content": _run_summary(run) or _autonomous_run_status_text(run),
        "created_at": created_at,
        "createdAt": created_at,
        "status": run.status,
        "metadata": {
            "message_type": "run",
            "run_id": run.run_id,
            "goal_id": None if goal is None else goal.id,
            "lane": run.lane,
            "priority": run.priority,
        },
    }


def _autonomous_turn_message(conversation_id: str, run: AgentRun, turn: AgentTurnRecord) -> dict[str, Any]:
    final_output = str((turn.turn_metadata or {}).get("final_output") or "").strip()
    created_at = _serialize_timestamp(turn.created_at)
    return {
        "id": turn.turn_id,
        "conversation_id": conversation_id,
        "conversationId": conversation_id,
        "role": "assistant" if final_output else "system",
        "kind": "message" if final_output else "status",
        "content": final_output or _autonomous_turn_text(turn),
        "created_at": created_at,
        "createdAt": created_at,
        "status": turn.status,
        "metadata": {
            "message_type": "turn",
            "turn_id": turn.turn_id,
            "run_id": run.run_id,
            "seq": turn.seq,
            "trigger_type": turn.trigger_type,
            "phase": turn.phase,
            "outcome_kind": turn.outcome_kind,
            "turn_metadata": dict(turn.turn_metadata or {}),
        },
    }


def _autonomous_event_message(conversation_id: str, event: dict[str, Any]) -> dict[str, Any]:
    created_at = event.get("occurredAt") or event.get("occurred_at")
    event_type = str(event.get("event_type") or event.get("eventType") or "")
    return {
        "id": str(event.get("id") or uuid4().hex),
        "conversation_id": conversation_id,
        "conversationId": conversation_id,
        "role": "system",
        "kind": "status",
        "content": str(event.get("message") or event.get("event_type") or "Autonomous event"),
        "created_at": created_at,
        "createdAt": created_at,
        "status": _event_message_status(event_type),
        "metadata": {
            "message_type": "event",
            "event_type": event_type,
            "payload": dict(event.get("payload") or {}),
        },
    }


def _autonomous_run_status_text(run: AgentRun) -> str:
    status = run.status.strip().lower()
    if status == "queued":
        return "Autonomous goal is queued in the backend."
    if status == "waiting_human":
        return "Autonomous goal is waiting for desktop approval."
    if status == "completed":
        return "Autonomous goal completed."
    if status in {"failed", "cancelled", "interrupted"}:
        return f"Autonomous goal {status}."
    return f"Autonomous goal status: {run.status}."


def _autonomous_turn_text(turn: AgentTurnRecord) -> str:
    if turn.status == "waiting_human":
        return "Autonomous turn is waiting for desktop approval before continuing."
    if turn.status == "failed":
        return str((turn.turn_metadata or {}).get("error") or "Autonomous turn failed.")
    if turn.status == "cancelled":
        return "Autonomous turn was cancelled."
    if turn.status == "completed":
        return "Autonomous turn completed."
    return f"Autonomous turn {turn.seq} is {turn.status}."


def _event_message_status(event_type: str) -> str:
    normalized = event_type.strip().lower()
    if normalized in {
        "turn_started",
        "llm_invocation_started",
        "llm_invocation_completed",
        "tool_event",
    }:
        return "active"
    if normalized == "turn_completed":
        return "completed"
    if normalized == "permission_requested":
        return "waiting_human"
    if normalized in {"turn_failed", "turn_interrupted"}:
        return "failed"
    return _workspace_status(normalized)


def _agent_message_sort_key(message: dict[str, Any]) -> tuple[float, str, str]:
    created_at = message.get("createdAt") or message.get("created_at")
    return (
        _timestamp_sort_value(created_at),
        _message_sort_rank(message),
        str(message.get("id") or ""),
    )


def _message_sort_rank(message: dict[str, Any]) -> str:
    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        message_type = str(metadata.get("message_type") or "").strip().lower()
        if message_type == "goal":
            return "0"
        if message_type == "run":
            return "1"
        if message_type == "turn":
            return "2"
        if message_type == "event":
            return "3"
    return "9"


def _timestamp_sort_value(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    raw = str(value).strip()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _serialize_autonomous_primary_conversation_record(
    session: Session,
    *,
    profile: RecruitAgentProfile,
) -> dict[str, Any]:
    agent_session = _get_agent_session(session, profile)
    if agent_session is None:
        return {
            "conversation": _autonomous_primary_conversation_summary(
                profile=profile,
                latest_goal=None,
                latest_run=None,
            ),
            "messages": [],
        }

    recent_runs = list(
        session.scalars(
            select(AgentRun)
            .where(
                AgentRun.session_id == agent_session.id,
                AgentRun.agent_kind == "autonomous",
            )
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(20)
        ).all()
    )
    recent_runs.reverse()
    goal_ids = [run.goal_spec_id for run in recent_runs if run.goal_spec_id]
    goals = (
        session.scalars(select(GoalSpec).where(GoalSpec.id.in_(goal_ids))).all()
        if goal_ids
        else []
    )
    goal_by_id = {goal.id: goal for goal in goals}
    latest_run_payload = None if not recent_runs else _serialize_run(recent_runs[-1])
    latest_goal = (
        None
        if not recent_runs or not recent_runs[-1].goal_spec_id
        else goal_by_id.get(recent_runs[-1].goal_spec_id)
    )
    if latest_goal is None:
        latest_goal = session.scalars(
            select(GoalSpec)
            .where(GoalSpec.agent_profile_id == profile.id)
            .order_by(
                GoalSpec.last_activity_at.desc().nullslast(),
                GoalSpec.created_at.desc(),
                GoalSpec.id.desc(),
            )
            .limit(1)
        ).first()

    messages: list[dict[str, Any]] = []
    seen_goal_ids: set[str] = set()
    for run in recent_runs:
        goal = None if not run.goal_spec_id else goal_by_id.get(run.goal_spec_id)
        if goal is not None and goal.id not in seen_goal_ids:
            messages.append(_autonomous_goal_message(AUTONOMOUS_PRIMARY_CONVERSATION_ID, goal))
            seen_goal_ids.add(goal.id)
        messages.append(_autonomous_run_message(AUTONOMOUS_PRIMARY_CONVERSATION_ID, run, goal))

    return {
        "conversation": _autonomous_primary_conversation_summary(
            profile=profile,
            latest_goal=latest_goal,
            latest_run=latest_run_payload,
        ),
        "messages": sorted(messages, key=_agent_message_sort_key),
    }


def _list_workspace_runs(session: Session, profile: RecruitAgentProfile, kind: AgentKind) -> list[dict[str, Any]]:
    agent_session = _get_agent_session(session, profile)
    if agent_session is None:
        return []
    runs = session.scalars(
        select(AgentRun)
        .where(AgentRun.session_id == agent_session.id, AgentRun.agent_kind == kind)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(20)
    ).all()
    return [_serialize_run(run) for run in runs]


def _list_pending_approvals(session: Session, kind: AgentKind) -> list[dict[str, Any]]:
    stmt = (
        select(ApprovalItem)
        .where(ApprovalItem.status == "pending")
        .order_by(ApprovalItem.created_at.desc(), ApprovalItem.id.desc())
    )
    items = [item for item in session.scalars(stmt).all() if _approval_belongs_to_kind(session, item, kind)]
    return [_serialize_approval(item) for item in items[:20]]


def _list_memory_summaries(session: Session, profile: RecruitAgentProfile) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if profile.agent_key == "autonomous":
        global_memories = [ensure_global_memory(session, agent_profile_id=profile.id)]
    else:
        global_memories = session.scalars(
            select(AgentGlobalMemory)
            .where(AgentGlobalMemory.agent_profile_id == profile.id)
            .order_by(AgentGlobalMemory.updated_at.desc(), AgentGlobalMemory.id.asc())
            .limit(1)
        ).all()
    items.extend(
        {
            "id": memory.id,
            "scope": "global",
            "title": "Global memory",
            "summary": memory.summary or "",
            "status": memory.status,
            "updated_at": _serialize_timestamp(memory.updated_at),
            "updatedAt": _serialize_timestamp(memory.updated_at),
        }
        for memory in global_memories
    )
    items.extend(
        {
            "id": memory.id,
            "scope": "candidate",
            "title": memory.person_id,
            "summary": memory.summary or "",
            "status": memory.status,
            "updated_at": _serialize_timestamp(memory.updated_at),
            "updatedAt": _serialize_timestamp(memory.updated_at),
        }
        for memory in CandidatePersonMemoryRepository(session).list_for_agent(profile.id, limit=3, offset=0)
    )
    items.extend(
        {
            "id": memory.id,
            "scope": "job",
            "title": memory.job_description_id,
            "summary": memory.summary or "",
            "status": memory.status,
            "updated_at": _serialize_timestamp(memory.updated_at),
            "updatedAt": _serialize_timestamp(memory.updated_at),
        }
        for memory in JobDescriptionMemoryRepository(session).list_for_agent(profile.id, limit=3, offset=0)
    )
    return items


def _list_workspace_skills(session: Session) -> list[dict[str, Any]]:
    stmt = (
        select(Skill)
        .where(Skill.status.in_(("trial", "active")))
        .order_by(Skill.name.asc(), Skill.id.asc())
        .limit(20)
    )
    return [SkillRead.model_validate(item).model_dump(by_alias=True) for item in session.scalars(stmt).all()]


def _list_workspace_tools(container: AppContainer) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for tool in container.plugin_host.tool_registry.tools.values():
        if str(tool.category or "").strip().lower() != "business":
            continue
        metadata = dict(tool.metadata or {})
        tools.append(
            {
                "id": f"business:{tool.name}",
                "server_id": f"business:{tool.category}",
                "serverId": f"business:{tool.category}",
                "server_name": "Recruit Business Tools",
                "serverName": "Recruit Business Tools",
                "name": tool.name,
                "risk_level": str(metadata.get("risk_level") or "medium"),
                "riskLevel": str(metadata.get("risk_level") or "medium"),
                "business_tool": bool(metadata.get("business_tool")),
                "businessTool": bool(metadata.get("business_tool")),
                "business_domain": metadata.get("business_domain"),
                "businessDomain": metadata.get("business_domain"),
                "resource_target_kind": tool.resource_target_kind,
                "resourceTargetKind": tool.resource_target_kind,
                "permission_scope": metadata.get("permission_scope"),
                "permissionScope": metadata.get("permission_scope"),
                "enabled": True,
                "endpoint": None,
            }
        )
        seen_names.add(tool.name)

    for tool in container.tool_registry.tools.values():
        if tool.name in seen_names:
            continue
        if str(tool.category or "").strip().lower() != "memory":
            continue
        metadata = dict(tool.metadata or {})
        tools.append(
            {
                "id": f"memory:{tool.name}",
                "server_id": "memory:files",
                "serverId": "memory:files",
                "server_name": "Memory Files",
                "serverName": "Memory Files",
                "name": tool.name,
                "risk_level": str(metadata.get("risk_level") or "low"),
                "riskLevel": str(metadata.get("risk_level") or "low"),
                "business_tool": False,
                "businessTool": False,
                "business_domain": None,
                "businessDomain": None,
                "resource_target_kind": tool.resource_target_kind,
                "resourceTargetKind": tool.resource_target_kind,
                "permission_scope": metadata.get("permission_scope"),
                "permissionScope": metadata.get("permission_scope"),
                "enabled": True,
                "endpoint": None,
            }
        )
        seen_names.add(tool.name)

    for server in container.mcp_registry.list_servers():
        payload = McpServerRead.model_validate(server).model_dump(by_alias=True)
        if not bool(payload.get("enabled")):
            continue
        server_tools = list(payload.get("tools") or [])
        if not server_tools:
            tools.append(
                {
                    "id": payload.get("id"),
                    "server_id": payload.get("id"),
                    "serverId": payload.get("id"),
                    "server_name": payload.get("name"),
                    "serverName": payload.get("name"),
                    "name": payload.get("server_key") or payload.get("name"),
                    "risk_level": "medium",
                    "riskLevel": "medium",
                    "enabled": True,
                    "endpoint": payload.get("endpoint"),
                }
            )
            continue
        for tool in server_tools:
            tool_name = str(tool.get("name") or "").strip()
            if tool_name in seen_names:
                continue
            risk_level = str(tool.get("risk_level") or "medium")
            tools.append(
                {
                    "id": tool.get("id"),
                    "server_id": payload.get("id"),
                    "serverId": payload.get("id"),
                    "server_name": payload.get("name"),
                    "serverName": payload.get("name"),
                    "name": tool_name,
                    "risk_level": risk_level,
                    "riskLevel": risk_level,
                    "enabled": bool(tool.get("enabled", True)),
                    "endpoint": payload.get("endpoint"),
                }
            )
            seen_names.add(tool_name)
    return tools


def _run_title(run: AgentRun) -> str:
    goal_title = str((run.runtime_metadata or {}).get("goal_title") or "").strip()
    if goal_title:
        return goal_title
    title = str((run.context_manifest or {}).get("title") or "").strip()
    if title:
        return title
    run_type = str(run.run_type or "").replace("_", " ").strip()
    return run_type.title() if run_type else "Run"


def _run_summary(run: AgentRun) -> str | None:
    projected = project_runtime_business_state(
        content=dict(run.runtime_metadata or {}),
        goal_kind=str(run.run_type or "").strip() or None,
        goal_title=_run_title(run),
        run_status=str(run.status or "").strip() or None,
    )
    summary = str(projected.get("summary") or "").strip()
    return summary or None


def _goal_summary(goal: GoalSpec) -> str | None:
    projected = project_runtime_business_state(
        content=dict(goal.goal_metadata or {}),
        goal_kind=str(goal.goal_kind or "").strip() or None,
        goal_title=str(goal.title or "").strip() or None,
        run_status=str(goal.status or "").strip() or None,
    )
    summary = str(projected.get("summary") or "").strip()
    return summary or None


def _ensure_assistant_conversation(
    session: Session,
    *,
    container: AppContainer,
    conversation_id: str,
    user_id: str,
    title: str | None,
) -> ConversationSession:
    conversation = session.scalars(
        select(ConversationSession).where(ConversationSession.conversation_id == conversation_id)
    ).first()
    if conversation is not None:
        return conversation
    safe_name = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in conversation_id).strip("_")
    safe_name = safe_name or uuid4().hex
    conversation = ConversationSession(
        conversation_id=conversation_id,
        user_id=user_id,
        assistant_id="assistant",
        assistant_assembly_id="assistant-default",
        title=title,
        status="active",
        jsonl_path=str(container.session_store.base_dir / f"{safe_name}.jsonl"),
        started_at=utcnow(),
        last_active_at=utcnow(),
    )
    session.add(conversation)
    session.flush()
    return conversation


def _trim_title(text: str, limit: int = 72) -> str:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return "Assistant"
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _drain_assistant_turn_stream(*, container: AppContainer, conversation_id: str, message: str) -> None:
    try:
        for _event, _payload in container.assistant_adapter.run_turn_stream(conversation_id, message):
            pass
    except Exception:
        return
