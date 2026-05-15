from __future__ import annotations

from datetime import datetime
import json
from threading import Thread
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from recruit_station.agents.autonomous import AutonomousRunInterrupted
from recruit_station.db.base import utcnow
from recruit_station.models.domain import (
    AgentRun,
    AgentRunCheckpoint,
    AgentRuntimeEvent,
    AgentSession,
    AgentTurnRecord,
    ApprovalItem,
    ConversationSession,
    ConversationTurn,
    OperatorInteraction,
    AgentDefinition,
    Skill,
    TaskQueueItem,
)
from recruit_station.repositories.domain import (
    AgentDefinitionRepository,
    SkillRepository,
    TaskQueueRepository,
)
from recruit_station.product_adapters.business_state_projection import project_runtime_business_state
from recruit_station.product_adapters.target_contracts import derive_browser_target
from recruit_station.schemas.domain import (
    ApprovalRead,
    AgentDefinitionRead,
    AgentDefinitionUpdate,
    McpServerRead,
    RuntimeControlledRunRead,
    RuntimeEventRead,
    RuntimeSessionRead,
    SkillRead,
)
from recruit_station.services.container import AppContainer
from recruit_station.services.recruit_station import normalize_prompt_config, resolve_context_policy, resolve_memory_policy


AgentKind = Literal["assistant", "autonomous"]
MemoryScope = Literal["candidate", "job", "global"]
BUILTIN_AGENT_KINDS: tuple[AgentKind, ...] = ("assistant", "autonomous")
AUTONOMOUS_PRIMARY_CONVERSATION_ID = "autonomous-primary"
SHARED_WORKSPACE_SCOPE_REF = "workspace:shared"
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

DEFAULT_RECRUITING_POLICY: dict[str, Any] = {
    "jdStandards": "拆解岗位目标、团队阶段、核心职责、硬性门槛、加分项、排除项和交付预期；所有候选人判断必须明确引用对应 JD 要求。",
    "perJdEvaluation": "不同 JD 可以覆盖通用权重、硬性门槛和优先级。评估时先读取当前 JD 的专属标准，再应用通用招聘规则。",
    "onlineResumeCriteria": "在线简历优先判断 JD 匹配度、最近岗位相关性、核心技能证据、项目深度、稳定性和明显风险；不足以判断时进入补充材料环节。",
    "offlineResumeCriteria": "离线简历用于补齐在线资料缺失的信息，重点检查项目细节、影响指标、职责边界、联系方式和时间线一致性。",
    "communicationEvidence": "沟通记录用于判断候选人意向、可联系性、薪资/城市/到岗约束、简历获取结果和风险信号；不得跨候选人或跨 JD 混用沟通事实。",
    "compositeScoring": "AI 综合评分基于在线简历、离线简历、沟通记录和 JD 标准生成，必须输出维度分、证据引用、通过/淘汰建议和下一步动作。",
    "screeningRules": "人工筛选阶段必须已具备在线简历评估、离线简历评估和 AI 综合评分。综合分达到阈值且无硬性排除项时建议通过，否则给出淘汰或补充材料建议。",
    "interviewScheduling": "进入待预约面试前必须有可用联系方式、明确意向和可解释的通过理由。面试安排应记录时间、轮次、联系人和确认状态。",
    "offerHandoff": "Offer 阶段只处理已通过面试的候选人；需要记录薪资期望、风险点、候选人反馈和交接备注。",
    "scoreWeights": {
        "jdMatch": 30,
        "onlineResume": 20,
        "offlineResume": 25,
        "communication": 15,
        "stability": 10,
    },
    "thresholds": {
        "onlinePass": 70,
        "offlinePass": 72,
        "compositePass": 75,
        "manualReviewMin": 60,
        "interviewRecommend": 80,
    },
}


class AgentTaskCreate(BaseModel):
    task_type: str
    priority: int = 100
    payload: dict[str, Any] = Field(default_factory=dict)


class AutonomousTriggerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = None
    instruction: str
    kind: str = "recruiting"
    requested_by: str = "desktop-user"
    summary: str | None = None
    priority: int = 100
    jd_id: str | None = Field(default=None, validation_alias=AliasChoices("jd_id", "jdId"), serialization_alias="jdId")
    conversation_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("conversation_id", "conversationId"),
        serialization_alias="conversationId",
    )
    candidate_count_target: int | None = Field(
        default=None,
        validation_alias=AliasChoices("candidate_count_target", "candidateCountTarget"),
        serialization_alias="candidateCountTarget",
    )
    constraints: dict[str, Any] = Field(default_factory=dict)
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    context_hints: dict[str, Any] = Field(default_factory=dict)
    trial_budget: dict[str, Any] = Field(default_factory=dict)
    run_preferences: dict[str, Any] = Field(default_factory=dict)

    @field_validator("instruction")
    @classmethod
    def _instruction_must_not_be_empty(cls, value: str) -> str:
        instruction = str(value or "").strip()
        if not instruction:
            raise ValueError("instruction must not be empty")
        return instruction


class RunControlRequest(BaseModel):
    reviewer: str = "desktop-user"
    reason: str | None = None


class WorkspaceControlRequest(BaseModel):
    reviewer: str = "desktop-user"
    reason: str | None = None


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
        try:
            return container.heartbeat.run_once()
        except AutonomousRunInterrupted as exc:
            return {"status": "interrupted", "reason": str(exc)}

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

    @router.get("/autonomous/workspace-control")
    def get_autonomous_workspace_control() -> dict[str, Any]:
        return _workspace_control_payload(container.heartbeat.status())

    @router.post("/autonomous/workspace-control/start")
    def start_autonomous_workspace(payload: WorkspaceControlRequest) -> dict[str, Any]:
        container.heartbeat.start(updated_by=payload.reviewer, reason=payload.reason or "manual start")
        return _workspace_control_payload(container.heartbeat.status())

    @router.post("/autonomous/workspace-control/pause")
    def pause_autonomous_workspace(payload: WorkspaceControlRequest) -> dict[str, Any]:
        container.heartbeat.pause(reason=payload.reason or "manual pause", updated_by=payload.reviewer)
        return _workspace_control_payload(container.heartbeat.status())

    @router.post("/autonomous/workspace-control/continue")
    def continue_autonomous_workspace(payload: WorkspaceControlRequest) -> dict[str, Any]:
        container.heartbeat.resume(updated_by=payload.reviewer)
        return _workspace_control_payload(container.heartbeat.status())

    @router.post("/autonomous/workspace-control/terminate")
    def terminate_autonomous_workspace(payload: WorkspaceControlRequest) -> dict[str, Any]:
        container.heartbeat.terminate(reason=payload.reason or "manual terminate", updated_by=payload.reviewer)
        terminated_run_ids = container.autonomous_adapter.terminate_open_runs(
            reviewer=payload.reviewer,
            reason=payload.reason or "manual terminate",
        )
        control = _workspace_control_payload(container.heartbeat.status())
        control["terminated_run_ids"] = terminated_run_ids
        control["terminatedRunIds"] = terminated_run_ids
        return control

    @router.get("")
    def list_agents() -> list[dict[str, Any]]:
        with container.session_factory() as session:
            return [
                _serialize_agent_projection(_resolve_agent_definition(session, kind), kind=kind)
                for kind in BUILTIN_AGENT_KINDS
            ]

    @router.post("/autonomous/runs", status_code=201)
    def create_autonomous_run(payload: AutonomousTriggerRequest) -> dict[str, Any]:
        with container.session_factory() as session:
            definition = _resolve_agent_definition(session, "autonomous")
            agent_session = _ensure_agent_session(session, definition, kind="autonomous")
            open_run = _find_open_autonomous_run(session, session_id=agent_session.id)
            if open_run is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Autonomous already has an open run. Wait for it to finish or resume it before starting another run.",
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
                text_sources=(payload.instruction, payload.title),
            )
            if browser_target:
                context_hints["browser_target"] = browser_target
                constraints.setdefault("browser_target", browser_target)

            instruction = str(payload.instruction or "").strip()
            title = str(payload.title or _trim_title(instruction) or "Autonomous run").strip()

            run = AgentRun(
                session_id=agent_session.id,
                job_description_id=payload.jd_id,
                platform="site",
                lane="agent",
                run_type=payload.kind,
                status="queued",
                priority=payload.priority,
                context_manifest={
                    "instruction": instruction,
                    "title": title,
                    "kind": payload.kind,
                    "requested_by": payload.requested_by,
                    "candidate_count_target": payload.candidate_count_target,
                    "conversation_id": conversation_id,
                    "parent_conversation_id": parent_conversation_id,
                    "constraints": constraints,
                    "success_criteria": dict(payload.success_criteria or {}),
                    "context_hints": context_hints,
                    "trial_budget": dict(payload.trial_budget or {}),
                    "run_preferences": dict(payload.run_preferences or {}),
                    **({"browser_target": browser_target} if browser_target else {}),
                },
                runtime_metadata={
                    "instruction": instruction,
                    "title": title,
                    "summary": payload.summary or instruction,
                    "requested_by": payload.requested_by,
                    "jd_id": payload.jd_id,
                    "candidate_count_target": payload.candidate_count_target,
                    "conversation_id": conversation_id,
                    "parent_conversation_id": parent_conversation_id,
                    "constraints": constraints,
                    "success_criteria": dict(payload.success_criteria or {}),
                    "context_hints": context_hints,
                    "trial_budget": dict(payload.trial_budget or {}),
                    "run_preferences": dict(payload.run_preferences or {}),
                    **({"browser_target": browser_target} if browser_target else {}),
                },
                run_id=uuid4().hex,
                agent_kind="autonomous",
            )
            session.add(run)
            session.flush()

            agent_session.current_lane = run.lane
            agent_session.last_active_at = utcnow()

            envelope = _default_run_envelope(run=run, definition=definition)
            task = _enqueue_run_task(session, run=run, envelope=envelope)
            session.commit()
            session.refresh(run)
            session.refresh(agent_session)
            return {
                "conversation_id": conversation_id,
                "conversationId": conversation_id,
                "run_id": run.run_id,
                "runId": run.run_id,
                "status": run.status,
                "run": _serialize_run(run),
                "session": RuntimeSessionRead.model_validate(agent_session).model_dump(by_alias=True),
                "task_id": task.id,
            }

    @router.get("/{kind}")
    def get_agent(kind: AgentKind) -> dict[str, Any]:
        with container.session_factory() as session:
            return _serialize_agent_projection(_resolve_agent_definition(session, kind), kind=kind)

    @router.patch("/{kind}")
    def update_agent(kind: AgentKind, payload: AgentDefinitionUpdate) -> dict[str, Any]:
        with container.session_factory() as session:
            repo = AgentDefinitionRepository(session)
            definition = _resolve_agent_definition(session, kind)
            patch = payload.model_dump(exclude_unset=True)
            if patch.get("definition_key") is not None:
                raise HTTPException(status_code=400, detail="Agent definition key is immutable for product projections.")
            if patch.get("is_primary") is not None:
                raise HTTPException(status_code=400, detail="Agent definition primary state is immutable for product projections.")
            definition_patch: dict[str, Any] = {}
            projection_patch: dict[str, Any] = {}
            config_patch: dict[str, Any] = {}
            for key in ("name", "status", "description", "dashboard_config", "channel_config", "agent_metadata"):
                if key in patch:
                    projection_patch[key] = patch.pop(key)
            for key in ("prompt_config", "memory_policy"):
                if key in patch:
                    config_patch[key] = patch.pop(key)
            if isinstance(patch.get("role_definition"), dict):
                role_definition = dict(definition.role_definition or {})
                role_definition.update(dict(patch["role_definition"] or {}))
                definition_patch["role_definition"] = role_definition
            if isinstance(config_patch.get("prompt_config"), dict):
                prompt_config = dict(_product_config(definition, kind).get("prompt_config") or {})
                prompt_config.update(dict(config_patch["prompt_config"] or {}))
                prompt_config = normalize_prompt_config(prompt_config)
                prompt_config["context_policy"] = resolve_context_policy(prompt_config)
                config_patch["prompt_config"] = prompt_config
            if isinstance(config_patch.get("memory_policy"), dict):
                memory_policy = dict(_product_config(definition, kind).get("memory_policy") or {})
                memory_policy.update(dict(config_patch["memory_policy"] or {}))
                config_patch["memory_policy"] = resolve_memory_policy(memory_policy)
            for key in ("playbook_blueprint", "product_bindings", "product_config", "product_projections"):
                if key in patch:
                    definition_patch[key] = patch[key]
            if projection_patch:
                product_projections = dict(definition.product_projections or {})
                projection = dict(product_projections.get(kind) or {})
                projection.update(projection_patch)
                product_projections[kind] = projection
                definition_patch["product_projections"] = product_projections
            if config_patch:
                product_config = dict(definition.product_config or {})
                config = dict(product_config.get(kind) or {})
                config.update(config_patch)
                product_config[kind] = config
                definition_patch["product_config"] = product_config
            updated = repo.update(definition, definition_patch)
            session.commit()
            session.refresh(updated)
            return _serialize_agent_projection(updated, kind=kind)

    @router.get("/{kind}/workspace")
    def get_agent_workspace(kind: AgentKind) -> dict[str, Any]:
        with container.session_factory() as session:
            definition = _resolve_agent_definition(session, kind)
            return _serialize_workspace(session, container=container, definition=definition, kind=kind)

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
            _resolve_agent_definition(session, "assistant")
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
            _resolve_agent_definition(session, kind)
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
            definition = _resolve_agent_definition(session, kind)
            agent_session = _get_agent_session(session, definition, kind=kind)
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
        try:
            run_pk = container.autonomous_adapter.cancel_run(
                run_id,
                reviewer=payload.reviewer,
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Run not found for agent kind: autonomous") from exc
        with container.session_factory() as session:
            run = session.get(AgentRun, run_pk)
            if run is None:
                raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
            return {"run": _serialize_run(run)}

    @router.post("/autonomous/runs/{run_id}/resume")
    def resume_run(run_id: str, payload: RunControlRequest) -> dict[str, Any]:
        with container.session_factory() as session:
            run = _resolve_run_for_kind(session, "autonomous", run_id)
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
            definition = _resolve_agent_definition(session, "autonomous")
            envelope = _resume_envelope_for_run(run=run, definition=definition, checkpoint=checkpoint)
            run.status = "queued"
            run.finished_at = None
            run.blocked_reason = None
            run.checkpoint_status = "resolved" if checkpoint is not None else "none"
            run.wakeup_state = {
                "resumed_at": utcnow().isoformat(),
                "resumed_by": payload.reviewer,
                "checkpoint_id": None if checkpoint is None else checkpoint.id,
            }
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
            _resolve_agent_definition(session, kind)
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
            definition = _resolve_agent_definition(session, kind)
            return [
                _serialize_memory_file_summary(item)
                for item in container.memory_file_store.list_scope_files(
                    scope_kind=scope,
                    agent_definition_id=definition.id,
                    limit=limit,
                    offset=offset,
                )
            ]

    @router.get("/{kind}/skills")
    def list_agent_skills(kind: AgentKind) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            _resolve_agent_definition(session, kind)
            stmt = (
                select(Skill)
                .where(Skill.status.in_(("trial", "active")))
                .order_by(Skill.name.asc(), Skill.id.asc())
            )
            return [SkillRead.model_validate(item).model_dump(by_alias=True) for item in session.scalars(stmt).all()]

    @router.get("/{kind}/mcp")
    def list_agent_mcps(kind: AgentKind) -> list[dict[str, Any]]:
        with container.session_factory() as session:
            _resolve_agent_definition(session, kind)
        return [
            McpServerRead.model_validate(item).model_dump(by_alias=True)
            for item in container.mcp_registry.list_servers()
            if bool(item.get("enabled"))
        ]

    return router


def _serialize_agent_projection(definition: AgentDefinition, *, kind: AgentKind) -> dict[str, Any]:
    projection = _product_projection(definition, kind)
    config = _product_config(definition, kind)
    definition_payload = AgentDefinitionRead.model_validate(
        {
            "id": definition.id,
            "definition_key": definition.definition_key,
            "name": definition.name,
            "status": definition.status,
            "description": definition.description,
            "is_primary": definition.is_primary,
            "role_definition": dict(definition.role_definition or {}),
            "prompt_config": dict(definition.prompt_config or {}),
            "playbook_blueprint": dict(definition.playbook_blueprint or {}),
            "memory_policy": dict(definition.memory_policy or {}),
            "dashboard_config": dict(definition.dashboard_config or {}),
            "channel_config": dict(definition.channel_config or {}),
            "product_bindings": dict(definition.product_bindings or {}),
            "product_config": dict(definition.product_config or {}),
            "product_projections": dict(definition.product_projections or {}),
            "agent_metadata": dict(definition.agent_metadata or {}),
            "created_at": int(_timestamp_sort_value(definition.created_at)),
            "updated_at": int(_timestamp_sort_value(definition.updated_at)),
        }
    ).model_dump(by_alias=True)
    payload = {
        "id": kind,
        "kind": kind,
        "agent_definition_id": definition.id,
        "agentDefinitionId": definition.id,
        "definition_key": definition.definition_key,
        "definitionKey": definition.definition_key,
        "name": str(projection.get("name") or definition.name),
        "status": str(projection.get("status") or definition.status),
        "description": projection.get("description", definition.description),
        "is_primary": kind == "autonomous",
        "isPrimary": kind == "autonomous",
        "role_definition": dict(definition.role_definition or {}),
        "roleDefinition": dict(definition.role_definition or {}),
        "prompt_config": dict(config.get("prompt_config") or definition.prompt_config or {}),
        "promptConfig": dict(config.get("prompt_config") or definition.prompt_config or {}),
        "playbook_blueprint": dict(definition.playbook_blueprint or {}),
        "playbookBlueprint": dict(definition.playbook_blueprint or {}),
        "memory_policy": dict(config.get("memory_policy") or definition.memory_policy or {}),
        "memoryPolicy": dict(config.get("memory_policy") or definition.memory_policy or {}),
        "dashboard_config": dict(projection.get("dashboard_config") or definition.dashboard_config or {}),
        "dashboardConfig": dict(projection.get("dashboard_config") or definition.dashboard_config or {}),
        "channel_config": dict(projection.get("channel_config") or definition.channel_config or {}),
        "channelConfig": dict(projection.get("channel_config") or definition.channel_config or {}),
        "agent_metadata": dict(projection.get("agent_metadata") or definition.agent_metadata or {}),
        "agentMetadata": dict(projection.get("agent_metadata") or definition.agent_metadata or {}),
        "product_binding": _product_binding(definition, kind),
        "productBinding": _product_binding(definition, kind),
        "agent_definition": definition_payload,
        "agentDefinition": definition_payload,
        "created_at": definition_payload["created_at"],
        "createdAt": definition_payload.get("createdAt", definition_payload["created_at"]),
        "updated_at": definition_payload["updated_at"],
        "updatedAt": definition_payload.get("updatedAt", definition_payload["updated_at"]),
    }
    return payload


def _product_binding(definition: AgentDefinition, kind: AgentKind) -> dict[str, Any]:
    return dict((definition.product_bindings or {}).get(kind) or {})


def _product_config(definition: AgentDefinition, kind: AgentKind) -> dict[str, Any]:
    return dict((definition.product_config or {}).get(kind) or {})


def _product_projection(definition: AgentDefinition, kind: AgentKind) -> dict[str, Any]:
    return dict((definition.product_projections or {}).get(kind) or {})


def _agent_session_key(definition: AgentDefinition, kind: AgentKind) -> str:
    binding = _product_binding(definition, kind)
    return str(binding.get("session_key") or kind).strip() or kind


def _serialize_run(run: AgentRun) -> dict[str, Any]:
    payload = RuntimeControlledRunRead.model_validate(
        {
            "id": run.id,
            "session_id": run.session_id,
            "execution_episode_id": run.execution_episode_id,
            "person_id": run.person_id,
            "application_id": run.application_id,
            "job_description_id": run.job_description_id,
            "platform": run.platform,
            "lane": run.lane,
            "run_type": run.run_type,
            "status": run.status,
            "priority": run.priority,
            "queue_task_id": run.queue_task_id,
            "checkpoint_status": run.checkpoint_status,
            "context_manifest": dict(run.context_manifest or {}),
            "runtime_metadata": dict(run.runtime_metadata or {}),
            "started_at": _serialize_unix_timestamp(run.started_at),
            "finished_at": _serialize_unix_timestamp(run.finished_at),
            "blocked_reason": run.blocked_reason,
            "last_error": run.last_error,
            "created_at": _serialize_unix_timestamp(run.created_at) or 0,
            "updated_at": _serialize_unix_timestamp(run.updated_at) or 0,
        }
    ).model_dump(by_alias=True)
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
    payload = ApprovalRead.model_validate(
        {
            "id": approval.id,
            "target_type": approval.target_type,
            "target_id": approval.target_id,
            "title": approval.title,
            "status": approval.status,
            "requested_by": approval.requested_by,
            "reviewed_by": approval.reviewed_by,
            "reviewed_at": _serialize_unix_timestamp(approval.reviewed_at),
            "payload": dict(approval.payload or {}),
            "notes": approval.notes,
            "created_at": _serialize_unix_timestamp(approval.created_at) or 0,
            "updated_at": _serialize_unix_timestamp(approval.updated_at) or 0,
        }
    ).model_dump(by_alias=True)
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


def _resolve_agent_definition(session: Session, kind: str) -> AgentDefinition:
    if kind not in BUILTIN_AGENT_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown agent kind: {kind}")
    definition = AgentDefinitionRepository(session).by_product_kind(kind)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Agent definition not found for product kind: {kind}")
    return definition


def _get_agent_session(session: Session, definition: AgentDefinition, *, kind: AgentKind) -> AgentSession | None:
    stmt = (
        select(AgentSession)
        .where(
            AgentSession.agent_definition_id == definition.id,
            AgentSession.session_key == _agent_session_key(definition, kind),
        )
        .order_by(AgentSession.updated_at.desc(), AgentSession.id.asc())
    )
    return session.scalars(stmt).first()


def _ensure_agent_session(session: Session, definition: AgentDefinition, *, kind: AgentKind) -> AgentSession:
    existing = _get_agent_session(session, definition, kind=kind)
    if existing is not None:
        return existing
    item = AgentSession(
        agent_definition_id=definition.id,
        session_key=_agent_session_key(definition, kind),
        status="active",
        runtime_metadata={"agent_definition_key": definition.definition_key, "agent_kind": kind},
    )
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
    definition = _resolve_agent_definition(session, kind)
    agent_session = session.get(AgentSession, run.session_id)
    if agent_session is None or agent_session.agent_definition_id != definition.id:
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
    definition: AgentDefinition,
) -> dict[str, Any]:
    constraints = dict((run.context_manifest or {}).get("constraints") or (run.runtime_metadata or {}).get("constraints") or {})
    context_hints = dict((run.context_manifest or {}).get("context_hints") or (run.runtime_metadata or {}).get("context_hints") or {})
    browser_target = derive_browser_target(
        existing=context_hints.get("browser_target") or constraints.get("browser_target") or (run.context_manifest or {}).get("browser_target"),
        structured_sources=(context_hints, constraints, run.context_manifest, run.runtime_metadata),
        text_sources=((run.context_manifest or {}).get("instruction"), (run.context_manifest or {}).get("title")),
    )
    scope_kind = "job" if run.job_description_id else str(constraints.get("scope_kind") or "global")
    scope_ref = (
        run.job_description_id
        or str(constraints.get("scope_ref") or "")
        or definition.id
    )
    return {
        "run_pk": run.id,
        "run_id": run.run_id,
        "scope_kind": scope_kind,
        "scope_ref": scope_ref,
        "trigger_type": "run_triggered",
        "world_snapshot": {
            "instruction": (run.context_manifest or {}).get("instruction"),
            "title": _run_title(run),
            "requested_by": (run.context_manifest or {}).get("requested_by") or (run.runtime_metadata or {}).get("requested_by"),
            "constraints": constraints,
            "success_criteria": dict((run.context_manifest or {}).get("success_criteria") or (run.runtime_metadata or {}).get("success_criteria") or {}),
            "context_hints": context_hints,
            "trial_budget": dict((run.context_manifest or {}).get("trial_budget") or (run.runtime_metadata or {}).get("trial_budget") or {}),
            "run_preferences": dict((run.context_manifest or {}).get("run_preferences") or (run.runtime_metadata or {}).get("run_preferences") or {}),
            **({"browser_target": browser_target} if browser_target else {}),
        },
        "metadata": {
            "agent_kind": run.agent_kind,
            "instruction": (run.context_manifest or {}).get("instruction"),
            "title": _run_title(run),
            "kind": run.run_type,
            "constraints": constraints,
            "success_criteria": dict((run.context_manifest or {}).get("success_criteria") or (run.runtime_metadata or {}).get("success_criteria") or {}),
            "context_hints": context_hints,
            "trial_budget": dict((run.context_manifest or {}).get("trial_budget") or (run.runtime_metadata or {}).get("trial_budget") or {}),
            "run_preferences": dict((run.context_manifest or {}).get("run_preferences") or (run.runtime_metadata or {}).get("run_preferences") or {}),
            **({"browser_target": browser_target} if browser_target else {}),
        },
    }


def _resume_envelope_for_run(
    *,
    run: AgentRun,
    definition: AgentDefinition,
    checkpoint: AgentRunCheckpoint | None,
) -> dict[str, Any]:
    if checkpoint is not None:
        checkpoint_payload = dict(checkpoint.payload or {})
        resume_task = checkpoint_payload.get("resume_task")
        if isinstance(resume_task, dict) and isinstance(resume_task.get("payload"), dict):
            payload = dict(resume_task.get("payload") or {})
            payload["trigger_type"] = "resume"
            return payload
    return _default_run_envelope(run=run, definition=definition)


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


def _workspace_control_payload(status: dict[str, Any]) -> dict[str, Any]:
    control = status.get("workspace_control") or status.get("workspaceControl") or {}
    if not isinstance(control, dict):
        control = {}
    state = str(control.get("state") or "").strip().lower()
    if state not in {"stopped", "running", "paused", "terminating"}:
        state = "stopped"
    reason = control.get("reason") or status.get("pause_reason")
    updated_by = control.get("updated_by") or control.get("updatedBy")
    updated_at = control.get("updated_at") or control.get("updatedAt")
    payload = {
        "state": state,
        "reason": reason,
        "updated_by": updated_by,
        "updatedBy": updated_by,
        "updated_at": updated_at,
        "updatedAt": updated_at,
        "autonomous_paused": bool(status.get("autonomous_paused")),
        "autonomousPaused": bool(status.get("autonomous_paused")),
    }
    return payload


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


def _serialize_workspace(
    session: Session,
    *,
    container: AppContainer,
    definition: AgentDefinition,
    kind: AgentKind,
) -> dict[str, Any]:
    provider_label, model_label = _overlay_provider_labels(container)
    approvals = _list_pending_approvals(session, kind)
    memories = _list_memory_summaries(container, definition)
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
                definition=definition,
                kind=kind,
                status=None if latest is None else latest["status"],
                active_task=None if latest is None else latest.get("preview"),
                active_instruction=None if latest is None else latest.get("title"),
                default_model=model_label,
                pending_approvals=len(approvals),
            ),
            "conversations": serialized_conversations,
            "runs": [_assistant_run_from_conversation(item) for item in serialized_conversations[:8]],
            "approvals": approvals,
            "memories": memories,
            "skills": _list_workspace_skills(session),
            "tools": _list_workspace_tools(container),
            "config": _workspace_config(definition, kind=kind, provider_label=provider_label, model_label=model_label),
            "workspace_control": _workspace_control_payload(container.heartbeat.status()) if kind == "autonomous" else None,
            "workspaceControl": _workspace_control_payload(container.heartbeat.status()) if kind == "autonomous" else None,
        }

    runs = _list_workspace_runs(session, definition, kind)
    latest_run = runs[0] if runs else None
    return {
        "agent": _workspace_agent_payload(
            definition=definition,
            kind=kind,
            status=None if latest_run is None else latest_run["status"],
            active_task=None if latest_run is None else latest_run.get("summary"),
            active_instruction=None if latest_run is None else str(latest_run.get("title") or ""),
            default_model=model_label,
            pending_approvals=len(approvals),
        ),
        "conversations": [
            _autonomous_primary_conversation_summary(
                definition=definition,
                latest_run=latest_run,
            )
        ],
        "runs": runs,
        "approvals": approvals,
        "memories": memories,
        "skills": _list_workspace_skills(session),
        "tools": _list_workspace_tools(container),
        "config": _workspace_config(definition, kind=kind, provider_label=provider_label, model_label=model_label),
        "workspace_control": _workspace_control_payload(container.heartbeat.status()),
        "workspaceControl": _workspace_control_payload(container.heartbeat.status()),
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

    definition = _resolve_agent_definition(session, "autonomous")
    if conversation_id == AUTONOMOUS_PRIMARY_CONVERSATION_ID:
        return _serialize_autonomous_primary_conversation_record(session, definition=definition)

    run = _resolve_run_for_kind(session, "autonomous", conversation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Conversation not found for agent kind: autonomous")
    return {
        "conversation": _autonomous_run_conversation_summary(run),
        "messages": [_autonomous_run_message(conversation_id, run)],
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
    definition: AgentDefinition,
    kind: AgentKind,
    status: str | None,
    active_task: str | None,
    active_instruction: str | None,
    default_model: str | None,
    pending_approvals: int,
) -> dict[str, Any]:
    projection = _product_projection(definition, kind)
    payload = _serialize_agent_projection(definition, kind=kind)
    resolved_status = str(status or projection.get("status") or definition.status or "idle")
    payload["status"] = resolved_status
    payload["health"] = _workspace_health(resolved_status)
    payload["active_task"] = active_task
    payload["activeTask"] = active_task
    payload["active_instruction"] = active_instruction
    payload["activeInstruction"] = active_instruction
    payload["default_model"] = default_model
    payload["defaultModel"] = default_model
    payload["pending_approvals"] = pending_approvals
    payload["pendingApprovals"] = pending_approvals
    payload["unread_count"] = 0
    payload["unreadCount"] = 0
    return payload


def _workspace_config(
    definition: AgentDefinition,
    *,
    kind: AgentKind,
    provider_label: str | None,
    model_label: str | None,
) -> dict[str, Any]:
    config = _product_config(definition, kind)
    projection = _product_projection(definition, kind)
    prompt_config = dict(config.get("prompt_config") or definition.prompt_config or {})
    role_definition = dict(definition.role_definition or {})
    boundaries = role_definition.get("boundaries")
    if not isinstance(boundaries, list):
        boundaries = role_definition.get("forbiddenActions") or role_definition.get("forbidden_actions") or prompt_config.get("boundaries") or []
    return {
        "system_prompt": str(
            prompt_config.get("systemPrompt")
            or prompt_config.get("system_prompt")
            or prompt_config.get("prompt")
            or projection.get("description")
            or definition.description
            or ""
        ),
        "scoring_rubric": str(
            prompt_config.get("scoringRubric")
            or prompt_config.get("scoring_rubric")
            or prompt_config.get("rubric")
            or prompt_config.get("rubric_text")
            or ""
        ),
        "recruiting_policy": _workspace_recruiting_policy(prompt_config.get("recruitingPolicy") or prompt_config.get("recruiting_policy")),
        "recruitingPolicy": _workspace_recruiting_policy(prompt_config.get("recruitingPolicy") or prompt_config.get("recruiting_policy")),
        "boundaries": [str(item) for item in list(boundaries or []) if str(item).strip()],
        "provider_label": provider_label,
        "providerLabel": provider_label,
        "model_label": model_label,
        "modelLabel": model_label,
    }


def _workspace_recruiting_policy(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    policy = {**DEFAULT_RECRUITING_POLICY, **raw}
    score_weights = raw.get("scoreWeights") or raw.get("score_weights")
    thresholds = raw.get("thresholds")
    if not isinstance(score_weights, dict):
        score_weights = {}
    if not isinstance(thresholds, dict):
        thresholds = {}
    policy["scoreWeights"] = {
        **dict(DEFAULT_RECRUITING_POLICY["scoreWeights"]),
        **score_weights,
    }
    policy["thresholds"] = {
        **dict(DEFAULT_RECRUITING_POLICY["thresholds"]),
        **thresholds,
    }
    return policy


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
    event_kind = _assistant_turn_event_kind(turn)
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
            "eventKind": event_kind,
            "itemType": "conversation_turn",
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


def _assistant_turn_event_kind(turn: ConversationTurn) -> str:
    if turn.status == "waiting_human":
        return "confirmation"
    if turn.status in {"failed", "cancelled"}:
        return "execution_result"
    if turn.role == "user":
        return "human"
    if turn.tool_calls:
        return "tool_call"
    if turn.tool_results:
        return "execution_result"
    return "thinking"


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


def _autonomous_primary_conversation_summary(
    *,
    definition: AgentDefinition,
    latest_run: dict[str, Any] | None,
) -> dict[str, Any]:
    projection = _product_projection(definition, "autonomous")
    updated_at = (
        None if latest_run is None else latest_run.get("updatedAt")
    ) or _serialize_timestamp(definition.updated_at)
    status = _workspace_status(None if latest_run is None else latest_run.get("status"))
    preview = (
        None if latest_run is None else str(latest_run.get("summary") or "").strip()
    ) or str(projection.get("description") or definition.description or "").strip() or None
    return {
        "id": AUTONOMOUS_PRIMARY_CONVERSATION_ID,
        "conversation_id": AUTONOMOUS_PRIMARY_CONVERSATION_ID,
        "conversationId": AUTONOMOUS_PRIMARY_CONVERSATION_ID,
        "agent_kind": "autonomous",
        "agentKind": "autonomous",
        "title": str(projection.get("name") or "Autonomous").strip() or "Autonomous",
        "preview": preview,
        "status": status,
        "unread_count": 0,
        "unreadCount": 0,
        "updated_at": updated_at,
        "updatedAt": updated_at,
        "ref_id": None if latest_run is None else latest_run.get("runId"),
        "refId": None if latest_run is None else latest_run.get("runId"),
    }


def _autonomous_run_conversation_summary(run: AgentRun) -> dict[str, Any]:
    updated_at = _serialize_timestamp(run.updated_at or run.created_at)
    status = _workspace_status(run.status)
    return {
        "id": run.run_id or run.id,
        "conversation_id": run.run_id or run.id,
        "conversationId": run.run_id or run.id,
        "agent_kind": "autonomous",
        "agentKind": "autonomous",
        "title": _run_title(run),
        "preview": _run_summary(run),
        "status": status,
        "unread_count": 0,
        "unreadCount": 0,
        "updated_at": updated_at,
        "updatedAt": updated_at,
        "ref_id": run.run_id or run.id,
        "refId": run.run_id or run.id,
    }


def _autonomous_run_message(conversation_id: str, run: AgentRun) -> dict[str, Any]:
    created_at = _serialize_timestamp(run.created_at)
    return {
        "id": f"{conversation_id}:run:{run.run_id or run.id}",
        "conversation_id": conversation_id,
        "conversationId": conversation_id,
        "role": "system",
        "kind": "status",
        "title": _run_title(run),
        "content": _run_summary(run) or _autonomous_run_status_text(run),
        "created_at": created_at,
        "createdAt": created_at,
        "status": run.status,
        "metadata": {
            "eventKind": _autonomous_run_event_kind(run),
            "itemType": "agent_run",
            "message_type": "run",
            "run_id": run.run_id,
            "lane": run.lane,
            "priority": run.priority,
        },
    }


def _autonomous_turn_message(conversation_id: str, run: AgentRun, turn: AgentTurnRecord) -> dict[str, Any]:
    final_output = str((turn.turn_metadata or {}).get("final_output") or "").strip()
    created_at = _serialize_timestamp(turn.created_at)
    event_kind = _autonomous_turn_event_kind(turn, final_output=final_output)
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
            "eventKind": event_kind,
            "itemType": "agent_turn",
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
    payload = dict(event.get("payload") or {})
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
            "eventKind": _runtime_event_kind(event_type, payload),
            "itemType": event_type,
            "message_type": "event",
            "event_type": event_type,
            "payload": payload,
        },
    }


def _autonomous_run_status_text(run: AgentRun) -> str:
    status = run.status.strip().lower()
    if status == "queued":
        return "Autonomous run is queued in the backend."
    if status == "waiting_human":
        return "Autonomous run is waiting for desktop approval."
    if status == "completed":
        return "Autonomous run completed."
    if status in {"failed", "cancelled", "interrupted"}:
        return f"Autonomous run {status}."
    return f"Autonomous run status: {run.status}."


def _autonomous_run_event_kind(run: AgentRun) -> str:
    status = run.status.strip().lower()
    if status == "waiting_human":
        return "confirmation"
    if status in {"completed", "failed", "cancelled", "interrupted"}:
        return "execution_result"
    return "thinking"


def _autonomous_turn_event_kind(turn: AgentTurnRecord, *, final_output: str) -> str:
    status = turn.status.strip().lower()
    if status == "waiting_human":
        return "confirmation"
    if status in {"failed", "cancelled", "interrupted"}:
        return "execution_result"
    if final_output or status == "completed":
        return "execution_result"
    return "thinking"


def _runtime_event_kind(event_type: str, payload: dict[str, Any]) -> str:
    normalized = event_type.strip().lower()
    payload_kind = str(payload.get("kind") or "").strip().lower()
    source = f"{normalized} {payload_kind}"
    if "permission" in source or "waiting_human" in source or "blocked" in source:
        return "confirmation"
    if payload_kind in {"tool_call_started", "tool_use_completed"}:
        return "tool_call"
    if payload_kind in {"tool_result_ready", "tool_error"}:
        return "execution_result"
    if "tool_call" in source or "tool_use" in source or "command_execution" in source or "web_search" in source:
        return "tool_call"
    if "tool_result" in source or "turn_completed" in source:
        return "execution_result"
    if "llm_invocation" in source or "reasoning" in source or "thinking" in source:
        return "thinking"
    return "thinking"


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


def _serialize_unix_timestamp(value: Any) -> int | None:
    if value is None:
        return None
    return int(_timestamp_sort_value(value))


def _serialize_autonomous_primary_conversation_record(
    session: Session,
    *,
    definition: AgentDefinition,
) -> dict[str, Any]:
    agent_session = _get_agent_session(session, definition, kind="autonomous")
    if agent_session is None:
        return {
            "conversation": _autonomous_primary_conversation_summary(
                definition=definition,
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
    run_ids = [run.id for run in recent_runs]
    turns_by_run_id: dict[str, list[AgentTurnRecord]] = {run_id: [] for run_id in run_ids}
    if run_ids:
        turns = session.scalars(
            select(AgentTurnRecord)
            .where(AgentTurnRecord.run_pk.in_(run_ids))
            .order_by(AgentTurnRecord.created_at.asc(), AgentTurnRecord.seq.asc(), AgentTurnRecord.id.asc())
        ).all()
        for turn in turns:
            turns_by_run_id.setdefault(turn.run_pk, []).append(turn)
    latest_run_payload = None if not recent_runs else _serialize_run(recent_runs[-1])

    messages: list[dict[str, Any]] = []
    for run in recent_runs:
        run_message = _autonomous_run_message(AUTONOMOUS_PRIMARY_CONVERSATION_ID, run)
        messages.append(run_message)
        for turn in turns_by_run_id.get(run.id, []):
            turn_message = _autonomous_turn_message(AUTONOMOUS_PRIMARY_CONVERSATION_ID, run, turn)
            turn_content = str(turn_message.get("content") or "").strip()
            if not turn_content or turn_content == str(run_message.get("content") or "").strip():
                continue
            turn_status = str(turn.status or "").strip().lower()
            has_final_output = bool(str((turn.turn_metadata or {}).get("final_output") or "").strip())
            if has_final_output or turn_status in {"waiting_human", "failed", "cancelled", "interrupted"}:
                messages.append(turn_message)

    return {
        "conversation": _autonomous_primary_conversation_summary(
            definition=definition,
            latest_run=latest_run_payload,
        ),
        "messages": sorted(messages, key=_agent_message_sort_key),
    }


def _list_workspace_runs(session: Session, definition: AgentDefinition, kind: AgentKind) -> list[dict[str, Any]]:
    agent_session = _get_agent_session(session, definition, kind=kind)
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


def _list_memory_summaries(container: AppContainer, definition: AgentDefinition) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for scope in ("global", "conversation", "candidate", "job"):
        for item in container.memory_file_store.list_scope_files(scope_kind=scope, agent_definition_id=definition.id, limit=3, offset=0):
            items.append(_serialize_memory_file_summary(item))
    return items


def _serialize_memory_file_summary(item: dict[str, Any]) -> dict[str, Any]:
    updated_at = str(item.get("updated_at") or "")
    scope = str(item.get("scope_kind") or "")
    scope_ref = str(item.get("scope_ref") or "")
    path = str(item.get("path") or "")
    preview = str(item.get("preview") or "").strip()
    return {
        "id": f"{scope}:{scope_ref}:{path}",
        "scope": scope,
        "scope_kind": scope,
        "scope_ref": scope_ref,
        "title": path or scope_ref,
        "summary": preview or path or scope_ref,
        "status": "active",
        "path": path,
        "size": item.get("size"),
        "updated_at": updated_at,
        "updatedAt": updated_at,
    }


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
        server_payload = dict(server) if isinstance(server, dict) else {
            "id": getattr(server, "id", ""),
            "server_key": getattr(server, "server_key", ""),
            "name": getattr(server, "name", ""),
            "transport_kind": getattr(server, "transport_kind", "unix_socket"),
            "protocol": getattr(server, "protocol", "mcp_jsonrpc"),
            "endpoint": getattr(server, "endpoint", ""),
            "enabled": getattr(server, "enabled", True),
            "preset_key": getattr(server, "preset_key", None),
            "auth_config": dict(getattr(server, "auth_config", {}) or {}),
            "server_metadata": dict(getattr(server, "server_metadata", {}) or {}),
            "health_status": getattr(server, "health_status", "unknown"),
            "health_error": getattr(server, "health_error", None),
            "last_health_at": getattr(server, "last_health_at", None),
            "tools": list(getattr(server, "tools", []) or []),
            "created_at": getattr(server, "created_at", None),
            "updated_at": getattr(server, "updated_at", None),
        }
        server_payload["last_health_at"] = _serialize_unix_timestamp(server_payload.get("last_health_at"))
        server_payload["created_at"] = _serialize_unix_timestamp(server_payload.get("created_at")) or 0
        server_payload["updated_at"] = _serialize_unix_timestamp(server_payload.get("updated_at")) or 0
        server_payload["tools"] = [_normalize_mcp_tool_payload(tool) for tool in list(server_payload.get("tools") or [])]
        payload = McpServerRead.model_validate(server_payload).model_dump(by_alias=True)
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


def _normalize_mcp_tool_payload(tool: Any) -> dict[str, Any]:
    payload = dict(tool) if isinstance(tool, dict) else {
        "id": getattr(tool, "id", ""),
        "server_id": getattr(tool, "server_id", ""),
        "name": getattr(tool, "name", ""),
        "description": getattr(tool, "description", ""),
        "parameters": dict(getattr(tool, "parameters", {}) or {}),
        "capabilities": list(getattr(tool, "capabilities", []) or []),
        "enabled": getattr(tool, "enabled", True),
        "risk_level": getattr(tool, "risk_level", "medium"),
        "remote_name": getattr(tool, "remote_name", None),
        "tool_metadata": dict(getattr(tool, "tool_metadata", {}) or {}),
        "created_at": getattr(tool, "created_at", None),
        "updated_at": getattr(tool, "updated_at", None),
    }
    payload["created_at"] = _serialize_unix_timestamp(payload.get("created_at")) or 0
    payload["updated_at"] = _serialize_unix_timestamp(payload.get("updated_at")) or 0
    return payload


def _run_title(run: AgentRun) -> str:
    title = str((run.context_manifest or {}).get("title") or "").strip()
    if title:
        return title
    title = str((run.runtime_metadata or {}).get("title") or "").strip()
    if title:
        return title
    run_type = str(run.run_type or "").replace("_", " ").strip()
    return run_type.title() if run_type else "Run"


def _run_summary(run: AgentRun) -> str | None:
    projected = project_runtime_business_state(
        content=dict(run.runtime_metadata or {}),
        run_kind=str(run.run_type or "").strip() or None,
        run_title=_run_title(run),
        run_status=str(run.status or "").strip() or None,
    )
    summary = str(projected.get("summary") or "").strip()
    if not summary:
        summary = str((run.runtime_metadata or {}).get("summary") or "").strip()
    if not summary:
        summary = str((run.context_manifest or {}).get("instruction") or "").strip()
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
