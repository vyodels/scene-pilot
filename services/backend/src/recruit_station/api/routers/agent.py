from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time
from threading import Thread
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from recruit_station.agents.autonomous import AutonomousRunInterrupted
from recruit_station.assistant.stream import format_sse_event
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
    AgentPendingUserInput,
    Skill,
    TaskQueueItem,
)
from recruit_station.repositories.domain import (
    AgentPendingUserInputRepository,
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


AgentKind = Literal["assistant", "autonomous", "jd_sync"]
MemoryScope = Literal["candidate", "job", "global"]
BUILTIN_AGENT_KINDS: tuple[AgentKind, ...] = ("assistant", "autonomous", "jd_sync")
RUNTIME_AGENT_KINDS: tuple[AgentKind, ...] = ("autonomous", "jd_sync")
AUTONOMOUS_PRIMARY_CONVERSATION_ID = "autonomous-primary"
JD_SYNC_PRIMARY_CONVERSATION_ID = "jd-sync-primary"
SHARED_WORKSPACE_SCOPE_REF = "workspace:shared"
DEFAULT_JD_SYNC_POLICY_TEXT = "从配置的招聘网站目标网页出发，根据页面可见导航和内容自行找到职位列表与职位详情，识别新增、更新和下架职位；只有确认职位详情已完整采集且没有阻塞时，才同步到本地 JD 库，列表页摘要只能作为发现线索。同步过程只处理职位信息，不处理候选人；如果只完成部分职位详情读取，可以记录已确认的职位作为进度，但不能把本轮视为完成，必须继续恢复并完成全量同步，或明确说明还需要恢复的条件。"
TECHNICAL_JD_SYNC_TEXT_MARKERS = (
    "upsert_job_description",
    "platform/external_id",
    "external_id",
)
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
AUTOMATION_RECRUITING_RUN_KINDS: set[str] = {
    "recruiting",
    "automation_recruiting",
    "multi_jd_recruiting",
}
JD_SYNC_RUN_KINDS: set[str] = {
    "jd_sync",
    "job_description_sync",
    "recruiting_jd_sync",
}
AUTOMATION_REQUIRED_SCHEDULER_FIELDS: tuple[str, ...] = (
    "scanIntervalMinutes",
    "candidatePoolTarget",
    "backlogThreshold",
    "priorityDiscoveryWeight",
    "priorityUnreadMessageWeight",
    "priorityScoringBacklogWeight",
    "priorityApprovalWeight",
    "priorityJdGapWeight",
    "messageSlaMinutes",
    "siteCooldownMinutes",
    "retryCooldownMinutes",
    "maxActionsPerHour",
    "maxConsecutiveErrors",
)

SITE_ENTRY_URL_KEYS: tuple[str, ...] = ("siteEntryUrl", "site_entry_url", "entryUrl", "entry_url")

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
    request_message: str | None = Field(
        default=None,
        validation_alias=AliasChoices("request_message", "requestMessage"),
        serialization_alias="requestMessage",
    )
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
    message: str | None = None
    priority: str = "next"


class ConversationClearRequest(BaseModel):
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
    priority: str = "next"


class AgentPendingUserInputAfterNextToolCallCreateRequest(BaseModel):
    message: str
    user_id: str = "desktop-user"
    title: str | None = None
    priority: str = "next"


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

    def _process_next_agent_queue_task() -> dict[str, Any]:
        try:
            return container.heartbeat.run_once()
        except AutonomousRunInterrupted as exc:
            return {"status": "interrupted", "reason": str(exc)}

    @router.post("/task-queue/process-next")
    def process_next_agent_queue_task() -> dict[str, Any]:
        return _process_next_agent_queue_task()

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
        started_run: dict[str, Any] | None = None
        start_blocker: dict[str, Any] | None = None
        with container.session_factory() as session:
            definition = _resolve_agent_definition(session, "autonomous")
            agent_session = _ensure_agent_session(session, definition, kind="autonomous")
            if _find_open_autonomous_run(session, session_id=agent_session.id, agent_kind="autonomous") is None:
                try:
                    started_run = _create_saved_automation_run(
                        session,
                        definition=definition,
                        requested_by=payload.reviewer or "desktop-user",
                    )
                except ValueError as exc:
                    start_blocker = {"reason": str(exc)}
        if start_blocker is None:
            container.heartbeat.start(updated_by=payload.reviewer, reason=payload.reason or "manual start")
        control = _workspace_control_payload(container.heartbeat.status())
        if started_run is not None:
            control["run"] = started_run["run"]
            control["run_id"] = started_run["run_id"]
            control["runId"] = started_run["runId"]
            control["task_id"] = started_run["task_id"]
            control["taskId"] = started_run["task_id"]
        if start_blocker is not None:
            control["run_start_blocked"] = start_blocker
            control["runStartBlocked"] = start_blocker
        return control

    @router.post("/autonomous/workspace-control/pause")
    def pause_autonomous_workspace(payload: WorkspaceControlRequest) -> dict[str, Any]:
        container.heartbeat.pause(reason=payload.reason or "manual pause", updated_by=payload.reviewer)
        paused_run_ids = container.autonomous_adapter.pause_active_runs(
            reviewer=payload.reviewer,
            reason=payload.reason or "manual pause",
        )
        control = _workspace_control_payload(container.heartbeat.status())
        control["paused_active_run_ids"] = paused_run_ids
        control["pausedActiveRunIds"] = paused_run_ids
        return control

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
            return _create_autonomous_run(session, definition=definition, payload=payload, agent_kind="autonomous")

    @router.post("/{kind}/runs", status_code=201)
    def create_runtime_agent_run(kind: AgentKind, payload: AutonomousTriggerRequest) -> dict[str, Any]:
        if kind not in RUNTIME_AGENT_KINDS:
            raise HTTPException(status_code=404, detail=f"Run creation is not supported for agent kind: {kind}")
        if kind == "jd_sync":
            payload.kind = "jd_sync"
        with container.session_factory() as session:
            definition = _resolve_agent_definition(session, kind)
            return _create_autonomous_run(session, definition=definition, payload=payload, agent_kind=kind)

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
            product_config_patch: dict[str, Any] = {}
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
            if isinstance(patch.get("product_config"), dict):
                product_config_patch = dict(patch.pop("product_config") or {})
            for key in ("playbook_blueprint", "product_bindings", "product_projections"):
                if key in patch:
                    definition_patch[key] = patch[key]
            if projection_patch:
                product_projections = dict(definition.product_projections or {})
                projection = dict(product_projections.get(kind) or {})
                projection.update(projection_patch)
                product_projections[kind] = projection
                definition_patch["product_projections"] = product_projections
            if product_config_patch or config_patch:
                product_config = dict(definition.product_config or {})
                for config_key, config_value in product_config_patch.items():
                    if isinstance(config_value, dict):
                        existing_config = dict(product_config.get(config_key) or {})
                        product_config[config_key] = _merge_product_config_patch(
                            existing_config,
                            dict(config_value),
                            config_key=config_key,
                        )
                    else:
                        product_config[config_key] = config_value
            if config_patch:
                config = dict(product_config.get(kind) or {})
                config.update(config_patch)
                product_config[kind] = config
            if product_config_patch or config_patch:
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
            conversation = _ensure_assistant_conversation(
                session,
                container=container,
                conversation_id=conversation_id,
                user_id=payload.user_id,
                title=payload.title or _trim_title(payload.message),
            )
            if active_turn is not None and active_turn.worker.is_alive():
                pending_user_input = AgentPendingUserInputRepository(session).enqueue_prompt(
                    agent_kind="assistant",
                    conversation_id=conversation.conversation_id,
                    message=payload.message,
                    priority=payload.priority,
                    queued_by=payload.user_id,
                    metadata={"source": "assistant_active_turn"},
                )
                session.commit()
                session.refresh(pending_user_input)
                return {
                    "conversation_id": conversation.conversation_id,
                    "conversationId": conversation.conversation_id,
                    "input_id": pending_user_input.input_id,
                    "inputId": pending_user_input.input_id,
                    "request_id": pending_user_input.input_id,
                    "requestId": pending_user_input.input_id,
                    "status": "queued",
                    "pending_user_input": _serialize_agent_pending_user_input(pending_user_input),
                }
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

    @router.post("/{kind}/conversations/{conversation_id}/pending-user-input-after-next-tool-call", status_code=202)
    def queue_pending_user_input_after_next_tool_call(
        kind: AgentKind,
        conversation_id: str,
        payload: AgentPendingUserInputAfterNextToolCallCreateRequest,
    ) -> dict[str, Any]:
        if kind == "assistant":
            return send_assistant_message(
                conversation_id,
                AssistantMessageCreateRequest(
                    message=payload.message,
                    user_id=payload.user_id,
                    title=payload.title,
                    priority=payload.priority,
                ),
            )
        if kind not in RUNTIME_AGENT_KINDS:
            raise HTTPException(status_code=404, detail=f"Messages are not supported for agent kind: {kind}")
        with container.session_factory() as session:
            definition = _resolve_agent_definition(session, kind)
            agent_session = _ensure_agent_session(session, definition, kind=kind)
            open_run = _find_open_autonomous_run(session, session_id=agent_session.id, agent_kind=kind)
            if open_run is not None:
                pending_user_input = AgentPendingUserInputRepository(session).enqueue_prompt(
                    agent_kind=kind,
                    conversation_id=conversation_id or _primary_conversation_id(kind),
                    run=open_run,
                    message=payload.message,
                    priority=payload.priority,
                    queued_by=payload.user_id,
                    metadata={"source": "runtime_active_turn"},
                )
                session.commit()
                session.refresh(pending_user_input)
                return {
                    "conversation_id": pending_user_input.conversation_id,
                    "conversationId": pending_user_input.conversation_id,
                    "run_id": open_run.run_id,
                    "runId": open_run.run_id,
                    "input_id": pending_user_input.input_id,
                    "inputId": pending_user_input.input_id,
                    "request_id": pending_user_input.input_id,
                    "requestId": pending_user_input.input_id,
                    "status": "queued",
                    "pending_user_input": _serialize_agent_pending_user_input(pending_user_input),
                }

            raise HTTPException(
                status_code=409,
                detail="Agent must have an open run before pending user input can be queued after the next tool call.",
            )

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

    @router.get("/{kind}/conversations/{conversation_id}/stream")
    def stream_agent_conversation(kind: AgentKind, conversation_id: str) -> StreamingResponse:
        if kind not in RUNTIME_AGENT_KINDS:
            raise HTTPException(status_code=404, detail=f"Conversation stream is not supported for agent kind: {kind}")

        def _stream():
            last_signature: str | None = None
            idle_ticks = 0
            max_idle_ticks = 300
            while idle_ticks < max_idle_ticks:
                with container.session_factory() as session:
                    _resolve_agent_definition(session, kind)
                    record = _serialize_conversation_record(
                        session,
                        container=container,
                        kind=kind,
                        conversation_id=conversation_id,
                    )
                signature = _conversation_stream_signature(record)
                if signature != last_signature:
                    last_signature = signature
                    idle_ticks = 0
                    yield format_sse_event("conversation_snapshot", record)
                else:
                    idle_ticks += 1
                    if idle_ticks % 40 == 0:
                        yield ": keep-alive\n\n"
                time.sleep(0.25)

        return StreamingResponse(_stream(), media_type="text/event-stream")

    @router.post("/{kind}/conversations/{conversation_id}/clear")
    def clear_agent_conversation(kind: AgentKind, conversation_id: str, payload: ConversationClearRequest) -> dict[str, Any]:
        if kind == "assistant":
            container.assistant_adapter.cancel_turn(conversation_id)
            with container.session_factory() as session:
                conversation = session.scalars(
                    select(ConversationSession).where(ConversationSession.conversation_id == conversation_id)
                ).first()
                if conversation is None:
                    raise HTTPException(status_code=404, detail="Conversation not found for agent kind: assistant")
                session.execute(delete(ConversationTurn).where(ConversationTurn.conversation_pk == conversation.id))
                jsonl_path = Path(conversation.jsonl_path)
                if jsonl_path.exists():
                    jsonl_path.write_text("", encoding="utf-8")
                conversation.context_summary = None
                conversation.messages_token_count = 0
                conversation.last_compact_at = None
                conversation.status = "active"
                conversation.last_active_at = utcnow()
                session.commit()
                session.refresh(conversation)
                return {
                    "conversation": _assistant_conversation_summary_from_session(session, conversation),
                    "messages": [],
                    "cleared": True,
                }

        if kind not in RUNTIME_AGENT_KINDS:
            raise HTTPException(status_code=404, detail=f"Conversation clear is not supported for agent kind: {kind}")
        primary_conversation_id = _primary_conversation_id(kind)
        if conversation_id != primary_conversation_id:
            raise HTTPException(status_code=404, detail=f"Only the primary conversation can be cleared for agent kind: {kind}")

        open_run_ids: list[str] = []
        with container.session_factory() as session:
            definition = _resolve_agent_definition(session, kind)
            agent_session = _ensure_agent_session(session, definition, kind=kind)
            open_runs = session.scalars(
                select(AgentRun).where(
                    AgentRun.session_id == agent_session.id,
                    AgentRun.agent_kind == kind,
                    AgentRun.status.in_(AUTONOMOUS_OPEN_RUN_STATUSES),
                )
            ).all()
            open_run_ids = [str(run.run_id or run.id) for run in open_runs]

        cancelled_run_ids: list[str] = []
        for run_id in open_run_ids:
            try:
                container.autonomous_adapter.cancel_run(
                    run_id,
                    reviewer=payload.reviewer,
                    reason=payload.reason or "conversation cleared",
                    agent_kind=kind,
                )
                cancelled_run_ids.append(run_id)
            except (KeyError, ValueError):
                continue

        with container.session_factory() as session:
            definition = _resolve_agent_definition(session, kind)
            agent_session = _ensure_agent_session(session, definition, kind=kind)
            cleared_at = utcnow()
            cleared_run_ids = [
                str(run_id)
                for run_id in session.scalars(
                    select(AgentRun.id).where(
                        AgentRun.session_id == agent_session.id,
                        AgentRun.agent_kind == kind,
                    )
                ).all()
            ]
            metadata = dict(agent_session.runtime_metadata or {})
            metadata["conversation_cleared_at"] = cleared_at.isoformat()
            metadata["conversation_cleared_by"] = payload.reviewer
            metadata["conversation_cleared_run_ids"] = cleared_run_ids
            if payload.reason:
                metadata["conversation_clear_reason"] = payload.reason
            agent_session.runtime_metadata = metadata
            agent_session.last_active_at = cleared_at
            pending_inputs = session.scalars(
                select(AgentPendingUserInput).where(
                    AgentPendingUserInput.agent_kind == kind,
                    AgentPendingUserInput.conversation_id == primary_conversation_id,
                    AgentPendingUserInput.status.in_(("pending", "claimed")),
                )
            ).all()
            for pending_input in pending_inputs:
                pending_input.status = "cancelled"
                pending_input.completed_at = cleared_at
                input_metadata = dict(pending_input.input_metadata or {})
                input_metadata["cancelled_by"] = payload.reviewer
                input_metadata["cancel_reason"] = payload.reason or "conversation cleared"
                pending_input.input_metadata = input_metadata
            session.commit()
            return {
                **_serialize_autonomous_primary_conversation_record(session, definition=definition, kind=kind),
                "cleared": True,
                "cancelledRunIds": cancelled_run_ids,
                "cancelled_run_ids": cancelled_run_ids,
            }

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
            hidden_run_ids = _agent_session_conversation_hidden_run_ids(agent_session)
            if hidden_run_ids:
                stmt = stmt.where(AgentRun.id.not_in(hidden_run_ids))
            elif (clear_after := _agent_session_conversation_cleared_at(agent_session)) is not None:
                stmt = stmt.where(AgentRun.created_at > clear_after)
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

    @router.post("/{kind}/runs/{run_id}/cancel")
    def cancel_run(kind: AgentKind, run_id: str, payload: RunControlRequest) -> dict[str, Any]:
        if kind not in RUNTIME_AGENT_KINDS:
            raise HTTPException(status_code=404, detail=f"Run control is not supported for agent kind: {kind}")
        try:
            run_pk = container.autonomous_adapter.cancel_run(
                run_id,
                reviewer=payload.reviewer,
                reason=payload.reason,
                agent_kind=kind,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Run not found for agent kind: {kind}") from exc
        with container.session_factory() as session:
            run = session.get(AgentRun, run_pk)
            if run is None:
                raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
            return {"run": _serialize_run(run)}

    @router.post("/{kind}/runs/{run_id}/resume")
    def resume_run(kind: AgentKind, run_id: str, payload: RunControlRequest) -> dict[str, Any]:
        if kind not in RUNTIME_AGENT_KINDS:
            raise HTTPException(status_code=404, detail=f"Run control is not supported for agent kind: {kind}")
        with container.session_factory() as session:
            run = _resolve_run_for_kind(session, kind, run_id)
            if str(run.status or "").strip().lower() in {"queued", "running", "active"}:
                raise HTTPException(status_code=409, detail="Active run does not need resume.")
            conflicting_run = _find_open_autonomous_run(session, session_id=run.session_id, agent_kind=kind, exclude_run_id=run.id)
            if conflicting_run is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"{kind} already has another open run. Resolve it before resuming this one.",
                )
            checkpoint = _resolve_run_gate_records(
                session,
                run=run,
                reviewer=payload.reviewer,
                reason=payload.reason or "manual resume",
                approval_status="approved",
                interaction_action="resume",
            )
            definition = _resolve_agent_definition(session, kind)
            envelope = _resume_envelope_for_run(run=run, definition=definition, checkpoint=checkpoint)
            envelope["trigger_type"] = "resume"
            resume_message = str(payload.message or "").strip()
            if resume_message:
                pending_input = list(envelope.get("pending_input") or []) if isinstance(envelope.get("pending_input"), list) else []
                pending_input.append(
                    {
                        "input_id": None,
                        "priority": str(payload.priority or "next").strip().lower() or "next",
                        "queued_by": payload.reviewer,
                        "message": resume_message,
                    }
                )
                envelope["pending_input"] = pending_input
                metadata = dict(envelope.get("metadata") or {}) if isinstance(envelope.get("metadata"), dict) else {}
                metadata["resumed_with_user_message"] = True
                metadata["resume_message"] = resume_message
                envelope["metadata"] = metadata
                world_snapshot = dict(envelope.get("world_snapshot") or {}) if isinstance(envelope.get("world_snapshot"), dict) else {}
                world_snapshot["pending_input"] = pending_input
                envelope["world_snapshot"] = world_snapshot
                session.add(
                    AgentRuntimeEvent(
                        session_id=run.session_id,
                        run_id=run.id,
                        source="operator",
                        event_type="runtime_event",
                        message="run_resume_user_message",
                        seq=0,
                        payload={
                            "type": "runtime_event",
                            "data": {
                                "kind": "run_resume_user_message",
                                "message": resume_message,
                                "priority": str(payload.priority or "next").strip().lower() or "next",
                                "queued_by": payload.reviewer,
                            },
                        },
                    )
                )
            run.status = "queued"
            run.finished_at = None
            run.blocked_reason = None
            run.checkpoint_status = "resolved" if checkpoint is not None else "none"
            run.wakeup_state = {
                "resumed_at": utcnow().isoformat(),
                "resumed_by": payload.reviewer,
                "checkpoint_id": None if checkpoint is None else checkpoint.id,
                **({"resume_message": resume_message} if resume_message else {}),
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


def _preserve_existing_site_entry_url_on_empty_patch(
    existing_config: dict[str, Any],
    incoming_config: dict[str, Any],
    *,
    config_key: str,
) -> dict[str, Any]:
    business_config_keys = {
        "autonomous": ("automation_recruiting_config", "automationRecruitingConfig", "automation_config", "automationConfig"),
        "jd_sync": ("jd_sync_config", "jdSyncConfig", "automation_config", "automationConfig"),
    }.get(config_key)
    if not business_config_keys:
        return incoming_config
    existing_url = _first_nested_site_entry_url(existing_config, business_config_keys)
    if not existing_url:
        return incoming_config
    for business_config_key in business_config_keys:
        business_config = incoming_config.get(business_config_key)
        if not isinstance(business_config, dict):
            continue
        execution_sop = business_config.get("executionSop") or business_config.get("execution_sop")
        if not isinstance(execution_sop, dict):
            continue
        for site_entry_key in SITE_ENTRY_URL_KEYS:
            if site_entry_key in execution_sop and isinstance(execution_sop[site_entry_key], str) and not execution_sop[site_entry_key].strip():
                execution_sop[site_entry_key] = existing_url
    return incoming_config


def _merge_product_config_patch(existing_config: dict[str, Any], incoming_config: dict[str, Any], *, config_key: str) -> dict[str, Any]:
    incoming = _preserve_existing_site_entry_url_on_empty_patch(
        existing_config,
        dict(incoming_config),
        config_key=config_key,
    )
    return _deep_merge_product_config(existing_config, incoming)


def _deep_merge_product_config(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in incoming.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_product_config(dict(current), dict(value))
        else:
            merged[key] = value
    return merged


def _first_nested_site_entry_url(config: dict[str, Any], business_config_keys: tuple[str, ...]) -> str | None:
    for business_config_key in business_config_keys:
        business_config = config.get(business_config_key)
        if not isinstance(business_config, dict):
            continue
        execution_sop = business_config.get("executionSop") or business_config.get("execution_sop")
        if not isinstance(execution_sop, dict):
            continue
        for site_entry_key in SITE_ENTRY_URL_KEYS:
            value = execution_sop.get(site_entry_key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _serialize_agent_projection(definition: AgentDefinition, *, kind: AgentKind) -> dict[str, Any]:
    projection = _product_projection(definition, kind)
    config = _product_config(definition, kind)
    role_definition = _projected_role_definition(definition, kind=kind, projection=projection, config=config)
    definition_payload = AgentDefinitionRead.model_validate(
        {
            "id": definition.id,
            "definition_key": definition.definition_key,
            "name": definition.name,
            "status": definition.status,
            "description": definition.description,
            "is_primary": definition.is_primary,
            "role_definition": role_definition,
            "prompt_config": dict(config.get("prompt_config") or definition.prompt_config or {}),
            "playbook_blueprint": dict(definition.playbook_blueprint or {}),
            "memory_policy": dict(config.get("memory_policy") or definition.memory_policy or {}),
            "dashboard_config": dict(projection.get("dashboard_config") or definition.dashboard_config or {}),
            "channel_config": dict(projection.get("channel_config") or definition.channel_config or {}),
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
        "role_definition": role_definition,
        "roleDefinition": role_definition,
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
        "product_config": dict(definition.product_config or {}),
        "productConfig": dict(definition.product_config or {}),
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


def _projected_role_definition(
    definition: AgentDefinition,
    *,
    kind: AgentKind,
    projection: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    configured = (
        projection.get("role_definition")
        or projection.get("roleDefinition")
        or config.get("role_definition")
        or config.get("roleDefinition")
    )
    if isinstance(configured, dict):
        return dict(configured)
    if kind == "jd_sync":
        return {
            "identity": "JD 同步 Agent",
            "positioning": "在人工已登录招聘网站的前提下，从配置的目标网页出发同步职位信息到本地 JD 库的受限 Agent。",
            "duties": [
                "从配置的招聘网站目标网页出发，根据页面可见导航和内容找到职位列表与职位详情。",
                "根据职位标题、团队、地点和页面可见来源信息识别新增、更新和下架职位。",
                "将确认后的职位信息同步到本地 JD 库，并记录同步结果和异常。",
            ],
            "tone": "professional, concise, evidence-driven",
            "boundaries": [
                "不处理登录、验证码、账号切换或绕过风控。",
                "不筛选候选人、不评分、不外联、不推进投递流程。",
                "只处理招聘站点中的职位信息，不读取或操作候选人数据。",
            ],
            "success_criteria": [
                "本地 JD 库与招聘网站可见职位保持一致。",
                "新增、更新、下架结果可追踪。",
                "无法同步的职位有明确原因和证据。",
            ],
            "forbidden_actions": [
                "擅自处理账号登录或安全校验。",
                "擅自联系候选人或修改候选人状态。",
                "将 JD 同步任务扩展为候选人筛选或招聘执行任务。",
            ],
        }
    return dict(definition.role_definition or {})


def _agent_session_key(definition: AgentDefinition, kind: AgentKind) -> str:
    binding = _product_binding(definition, kind)
    return str(binding.get("session_key") or kind).strip() or kind


def _primary_conversation_id(kind: AgentKind) -> str:
    return JD_SYNC_PRIMARY_CONVERSATION_ID if kind == "jd_sync" else AUTONOMOUS_PRIMARY_CONVERSATION_ID


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
    if run.agent_kind in RUNTIME_AGENT_KINDS:
        conversation_id = _primary_conversation_id(run.agent_kind)  # type: ignore[arg-type]
        payload["conversation_id"] = conversation_id
        payload["conversationId"] = conversation_id
        payload["ref_id"] = conversation_id
        payload["refId"] = conversation_id
    else:
        payload["ref_id"] = run.run_id
        payload["refId"] = run.run_id
    return payload


def _serialize_agent_pending_user_input(pending_user_input: AgentPendingUserInput) -> dict[str, Any]:
    return {
        "id": pending_user_input.id,
        "input_id": pending_user_input.input_id,
        "inputId": pending_user_input.input_id,
        "agent_kind": pending_user_input.agent_kind,
        "agentKind": pending_user_input.agent_kind,
        "conversation_id": pending_user_input.conversation_id,
        "conversationId": pending_user_input.conversation_id,
        "run_pk": pending_user_input.run_pk,
        "runPk": pending_user_input.run_pk,
        "run_id": pending_user_input.run_id,
        "runId": pending_user_input.run_id,
        "mode": pending_user_input.mode,
        "priority": pending_user_input.priority,
        "delivery": pending_user_input.delivery,
        "status": pending_user_input.status,
        "message": pending_user_input.message,
        "queued_by": pending_user_input.queued_by,
        "queuedBy": pending_user_input.queued_by,
        "claimed_at": _serialize_unix_timestamp(pending_user_input.claimed_at),
        "claimedAt": _serialize_unix_timestamp(pending_user_input.claimed_at),
        "claimed_by": pending_user_input.claimed_by,
        "claimedBy": pending_user_input.claimed_by,
        "completed_at": _serialize_unix_timestamp(pending_user_input.completed_at),
        "completedAt": _serialize_unix_timestamp(pending_user_input.completed_at),
        "metadata": dict(pending_user_input.input_metadata or {}),
        "created_at": _serialize_unix_timestamp(pending_user_input.created_at) or 0,
        "createdAt": _serialize_unix_timestamp(pending_user_input.created_at) or 0,
        "updated_at": _serialize_unix_timestamp(pending_user_input.updated_at) or 0,
        "updatedAt": _serialize_unix_timestamp(pending_user_input.updated_at) or 0,
    }


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


def _create_autonomous_run(
    session: Session,
    *,
    definition: AgentDefinition,
    payload: AutonomousTriggerRequest,
    agent_kind: AgentKind = "autonomous",
) -> dict[str, Any]:
    requested_message = str(payload.request_message or "").strip()
    requested_instruction = str(payload.instruction or "").strip()
    requested_title = str(payload.title or "").strip()
    _validate_autonomous_run_contract(definition, payload)
    agent_session = _ensure_agent_session(session, definition, kind=agent_kind)
    open_run = _find_open_autonomous_run(session, session_id=agent_session.id, agent_kind=agent_kind)
    if open_run is not None:
        raise HTTPException(
            status_code=409,
            detail=f"{agent_kind} already has an open run. Wait for it to finish or resume it before starting another run.",
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
    conversation_id = _primary_conversation_id(agent_kind)
    parent_conversation_id = (
        requested_conversation_id
        if requested_conversation_id not in {None, "", conversation_id}
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
            "requested_message": requested_message,
            "requested_instruction": requested_instruction,
            "requested_title": requested_title,
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
            "requested_message": requested_message,
            "requested_instruction": requested_instruction,
            "requested_title": requested_title,
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
        agent_kind=agent_kind,
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


def _validate_autonomous_run_contract(definition: AgentDefinition, payload: AutonomousTriggerRequest) -> None:
    run_kind = str(payload.kind or "").strip().lower()
    if run_kind in JD_SYNC_RUN_KINDS:
        jd_sync_config = _validated_jd_sync_config(definition)
        _merge_jd_sync_payload(payload, config=jd_sync_config)
        return
    if run_kind in AUTOMATION_RECRUITING_RUN_KINDS:
        _validated_automation_recruiting_config(definition)


def _validated_jd_sync_config(definition: AgentDefinition) -> dict[str, Any]:
    automation_config = _jd_sync_config(definition)
    execution_sop = dict(
        automation_config.get("executionSop")
        or automation_config.get("execution_sop")
        or {}
    )
    target_recruiting_site = _target_recruiting_site_from_sop(execution_sop)
    if not target_recruiting_site.get("entry_url"):
        raise HTTPException(
            status_code=409,
            detail="automation_recruiting_config missing target recruiting site fields: siteEntryUrl",
        )
    return {
        "automation_config": automation_config,
        "execution_sop": execution_sop,
        "target_recruiting_site": target_recruiting_site,
    }


def _merge_jd_sync_payload(payload: AutonomousTriggerRequest, *, config: dict[str, Any]) -> None:
    target_recruiting_site = dict(config["target_recruiting_site"])
    execution_sop = dict(config["execution_sop"])
    sync_policy = dict(config["automation_config"].get("syncPolicy") or config["automation_config"].get("sync_policy") or {})
    constraints = dict(payload.constraints or {})
    constraints.setdefault("scope_kind", "global")
    constraints.setdefault("plan_kind", "jd_sync")
    constraints.setdefault("target_recruiting_site", target_recruiting_site)
    constraints.setdefault("execution_sop", execution_sop)
    constraints.setdefault("sync_policy", sync_policy)
    payload.constraints = constraints
    context_hints = dict(payload.context_hints or {})
    context_hints.setdefault(
        "launch_plan",
        {
            "plan_kind": "jd_sync",
            "target_recruiting_site": target_recruiting_site,
            "requires_selected_jd": False,
            "next_step_after_success": "select synced JD and configure JD strategy before full recruiting run",
        },
    )
    payload.context_hints = context_hints
    if not str(payload.title or "").strip():
        payload.title = "同步招聘站点 JD"
    user_instruction = _normalize_jd_sync_extra_instruction(
        payload.instruction,
        entry_url=str(target_recruiting_site.get("entry_url") or "").strip(),
        title=payload.title,
        request_message=payload.request_message,
    )
    payload.instruction = _build_jd_sync_user_instruction(
        target_recruiting_site=target_recruiting_site,
        execution_sop=execution_sop,
        sync_policy=sync_policy,
        user_instruction=user_instruction,
    )


def _build_jd_sync_user_instruction(
    *,
    target_recruiting_site: dict[str, Any],
    execution_sop: dict[str, Any],
    sync_policy: dict[str, Any],
    user_instruction: str,
) -> str:
    entry_url = str(target_recruiting_site.get("entry_url") or "").strip()
    access_rules = _config_text_lines(
        execution_sop.get("siteAccessRulesText")
        or execution_sop.get("site_access_rules_text")
        or execution_sop.get("siteAccessRules")
        or execution_sop.get("site_access_rules")
    )
    sync_policy_lines = _product_jd_sync_policy_lines(
        sync_policy.get("jdSyncText")
        or sync_policy.get("jd_sync_text")
    )
    instruction_parts = [
        "同步招聘站点 JD",
        "",
        "任务范围：",
        "- 从配置的招聘网站目标网页出发，目标网页可以是该网站任意可访问页面。",
        "- 根据页面可见导航和内容自行找到职位列表与职位详情。",
        "- 职位列表只用于发现待同步职位，不能把列表页摘要或职位数量当作完成。",
        "- 对每个仍在招聘的职位，必须进入或打开职位详情并完整读取岗位详情后，才能同步到本地 JD 库。",
        "- 如果只读到列表但尚未读取详情，应继续执行；只有遇到登录、权限、必要执行工具缺失或页面不可达等明确问题才标记为阻塞。",
        "- 进入详情页、翻页或返回列表等页面动作应使用系统提供的浏览器观察和电脑/HID执行链路；不得因为浏览器观察工具只读就结束任务。",
        "- 如果页面动作失败但仍处于同源站点，应先恢复后继续：重新观察页面、等待页面稳定、释放异常按键状态、选择页面上的其他同源入口、滚动到稳定位置，或使用页面内导航控件继续。",
        "- 恢复执行不是重复同一失败动作；每次恢复都应根据最新页面证据切换页面内路径，例如从当前详情返回职位列表、滚动到目标职位入口、或选择已观察到的下一个同源详情入口。",
        "- 不得主动聚焦浏览器地址栏、输入 URL 或粘贴 URL 作为恢复路径；如果缺少页面内可执行证据，应说明 blocker 和需要恢复的页面条件。",
        "- 单次点击、返回、滚动或注入超时不是任务终局；只要目标站点仍可访问且还有职位详情未完整读取，就应在本轮继续恢复和推进。",
        "- 如果已经从列表发现多个职位，但本地写回数量少于发现数量或仍有任一职位缺少详情页证据，应继续打开剩余职位详情，不能输出最终总结。",
        "- 可以先写入已经完整读取详情的职位作为进度；但在没有完成全量职位发现、全量详情读取、更新/下架识别和生效 JD 选择前，不得用“已完成部分同步”结束本轮。",
        "- 只发现和同步 JD。",
        "- 不处理候选人筛选、评分、外联或投递推进。",
        "",
        "目标网页：",
        f"- URL：{entry_url}",
    ]
    if access_rules:
        instruction_parts.extend(["", "站点访问规则：", *[f"- {line}" for line in access_rules]])
    if sync_policy_lines:
        instruction_parts.extend(["", "JD 同步策略：", *[f"- {line}" for line in sync_policy_lines]])
    instruction_parts.extend(
        [
            "",
            "同步完成后：",
            "- 在配置页选择生效 JD。",
            "- 为选中的 JD 配置策略、评分标准和完整执行 SOP 后，才能启动完整自动化招聘。",
        ]
    )
    if user_instruction:
        instruction_parts.extend(["", "补充指令：", user_instruction])
    return _dedupe_jd_sync_instruction("\n".join(instruction_parts), entry_url=entry_url)


def _config_text_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        candidates = [str(item).strip() for item in value]
    else:
        candidates = [line.strip() for line in str(value).splitlines()]
    return [line for line in candidates if line]


def _product_jd_sync_policy_lines(value: Any) -> list[str]:
    lines = _config_text_lines(value)
    if not lines:
        return [DEFAULT_JD_SYNC_POLICY_TEXT]
    product_lines: list[str] = []
    for line in lines:
        normalized = line.lower()
        if any(marker in normalized for marker in TECHNICAL_JD_SYNC_TEXT_MARKERS):
            if DEFAULT_JD_SYNC_POLICY_TEXT not in product_lines:
                product_lines.append(DEFAULT_JD_SYNC_POLICY_TEXT)
            continue
        product_lines.append(line)
    return product_lines or [DEFAULT_JD_SYNC_POLICY_TEXT]


def _dedupe_jd_sync_instruction(instruction: str, *, entry_url: str) -> str:
    raw = str(instruction or "").strip()
    if not raw:
        return ""
    seen: set[str] = set()
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        key = _jd_sync_instruction_line_key(stripped, entry_url=entry_url)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def _jd_sync_instruction_line_key(line: str, *, entry_url: str) -> str | None:
    if not line:
        return None
    if entry_url and line.startswith(f"目标网页 URL：{entry_url}"):
        return "entry_url"
    if entry_url and line in {f"- URL：{entry_url}", f"URL：{entry_url}"}:
        return "entry_url"
    if line in {
        "- 只读取职位列表和职位详情。",
        "- 只发现和同步 JD。",
    }:
        return "jd_sync_boundary"
    if line in {
        "同步完成后，用户需要在配置页选择生效 JD，并为选中的 JD 配置策略、评分标准和执行 SOP 后，才能启动完整自动化招聘。",
        "同步完成后，再选择生效 JD 并配置 JD 策略、评分标准和完整执行 SOP。",
        "- 在配置页选择生效 JD。",
        "- 为选中的 JD 配置策略、评分标准和完整执行 SOP 后，才能启动完整自动化招聘。",
    }:
        return "next_step"
    return None


def _normalize_jd_sync_extra_instruction(
    instruction: str,
    *,
    entry_url: str,
    title: str | None,
    request_message: str | None,
) -> str:
    raw = str(instruction or "").strip()
    if not raw:
        return ""
    launch_texts = {
        str(title or "").strip(),
        str(request_message or "").strip(),
        "同步招聘站点 JD",
    }
    if raw in {text for text in launch_texts if text}:
        return ""
    legacy_template_lines = {
        "从已保存的目标网页同步 JD。只发现和同步职位，不处理候选人筛选、评分、外联或投递推进。",
        "同步完成后，用户需要在配置页选择生效 JD，并为选中的 JD 配置策略、评分标准和执行 SOP 后，才能启动完整自动化招聘。",
        "同步完成后，再选择生效 JD 并配置 JD 策略、评分标准和完整执行 SOP。",
    }
    if entry_url:
        legacy_template_lines.add(f"目标网页 URL：{entry_url}")
        legacy_template_lines.add(f"目标网页 URL：{entry_url}；复用人工已登录的浏览器会话。")
    remaining_lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and line.strip() not in legacy_template_lines
    ]
    normalized = "\n".join(remaining_lines).strip()
    if normalized in {text for text in launch_texts if text}:
        return ""
    return normalized


def _validated_automation_recruiting_config(definition: AgentDefinition) -> dict[str, Any]:
    automation_config = _automation_recruiting_config(definition)
    errors = _automation_recruiting_config_errors(automation_config)
    if errors:
        raise HTTPException(
            status_code=409,
            detail="automation_recruiting_config incomplete: " + "; ".join(errors),
        )
    return automation_config


def _automation_recruiting_config_errors(automation_config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    selected_job_ids = _selected_automation_job_ids(automation_config)
    if not selected_job_ids:
        errors.append("select at least one JD")
    execution_sop = dict(
        automation_config.get("executionSop")
        or automation_config.get("execution_sop")
        or {}
    )
    target_recruiting_site = _target_recruiting_site_from_sop(execution_sop)
    if not target_recruiting_site.get("entry_url"):
        errors.append("configure executionSop.siteEntryUrl")
    if not str(execution_sop.get("stepsText") or execution_sop.get("steps_text") or "").strip():
        errors.append("configure executionSop.stepsText")
    activation_policy = dict(
        automation_config.get("activationPolicy")
        or automation_config.get("activation_policy")
        or {}
    )
    missing_scheduler_fields = [
        field
        for field in AUTOMATION_REQUIRED_SCHEDULER_FIELDS
        if not _has_config_value(activation_policy.get(field), _snake_case_value(activation_policy, field))
    ]
    if missing_scheduler_fields:
        errors.append("configure activationPolicy fields: " + ", ".join(missing_scheduler_fields))
    job_strategies = dict(
        automation_config.get("jobStrategies")
        or automation_config.get("job_strategies")
        or {}
    )
    missing_strategy_jobs: list[str] = []
    for job_id in selected_job_ids:
        strategy = dict(job_strategies.get(job_id) or {})
        missing = _missing_job_strategy_fields(strategy)
        if missing:
            missing_strategy_jobs.append(f"{job_id} ({', '.join(missing)})")
    if missing_strategy_jobs:
        errors.append("configure JD strategies: " + "; ".join(missing_strategy_jobs))
    return errors


def _selected_automation_job_ids(automation_config: dict[str, Any]) -> list[str]:
    return [
        str(item).strip()
        for item in list(
            automation_config.get("defaultRunJobIds")
            or automation_config.get("default_run_job_ids")
            or automation_config.get("selectedRunJobIds")
            or automation_config.get("selected_run_job_ids")
            or []
        )
        if str(item).strip()
    ]


def _missing_job_strategy_fields(strategy: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    text_fields = (
        ("screeningCriteria", "screening_criteria"),
        ("manualReviewRules", "manual_review_rules"),
    )
    for camel, snake in text_fields:
        if not _has_config_value(strategy.get(camel), strategy.get(snake)):
            missing.append(camel)
    resume_scoring = _dict_config_value(strategy.get("resumeScoring"), strategy.get("resume_scoring"))
    online_resume = _dict_config_value(resume_scoring.get("online"), resume_scoring.get("onlineResume"), resume_scoring.get("online_resume"))
    offline_resume = _dict_config_value(resume_scoring.get("offline"), resume_scoring.get("offlineResume"), resume_scoring.get("offline_resume"))
    composite_scoring = _dict_config_value(strategy.get("compositeScoring"), strategy.get("composite_scoring"))
    composite_scoring_text = (
        strategy.get("compositeScoring")
        if isinstance(strategy.get("compositeScoring"), str)
        else strategy.get("composite_scoring")
        if isinstance(strategy.get("composite_scoring"), str)
        else None
    )
    if not _has_config_value(strategy.get("onlineResumeCriteria"), strategy.get("online_resume_criteria"), online_resume.get("criteria")):
        missing.append("onlineResumeCriteria")
    if not _has_config_value(online_resume.get("passThreshold"), online_resume.get("pass_threshold"), strategy.get("onlineResumePass")):
        missing.append("onlineResumePass")
    if not _has_config_value(strategy.get("offlineResumeCriteria"), strategy.get("offline_resume_criteria"), offline_resume.get("criteria")):
        missing.append("offlineResumeCriteria")
    if not _has_config_value(offline_resume.get("passThreshold"), offline_resume.get("pass_threshold"), strategy.get("offlineResumePass")):
        missing.append("offlineResumePass")
    if not _has_config_value(composite_scoring_text, strategy.get("composite_scoring_text"), composite_scoring.get("criteria")):
        missing.append("compositeScoring")
    if not _has_config_value(composite_scoring.get("passThreshold"), composite_scoring.get("pass_threshold"), strategy.get("compositePass")):
        missing.append("compositePass")
    if not _has_config_value(composite_scoring.get("manualReviewMin"), composite_scoring.get("manual_review_min"), strategy.get("manualReviewMin")):
        missing.append("manualReviewMin")
    return missing


def _has_config_value(*values: Any) -> bool:
    return any(value is not None and str(value).strip() for value in values)


def _dict_config_value(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return dict(value)
    return {}


def _snake_case_value(record: dict[str, Any], camel_key: str) -> Any:
    snake_key = "".join(
        f"_{char.lower()}" if char.isupper() else char
        for char in camel_key
    )
    return record.get(snake_key)


def _create_saved_automation_run(
    session: Session,
    *,
    definition: AgentDefinition,
    requested_by: str,
) -> dict[str, Any]:
    automation_config = _automation_recruiting_config(definition)
    errors = _automation_recruiting_config_errors(automation_config)
    if errors:
        raise ValueError("automation_recruiting_config incomplete: " + "; ".join(errors))
    selected_job_ids = _selected_automation_job_ids(automation_config)

    job_strategies = dict(
        automation_config.get("jobStrategies")
        or automation_config.get("job_strategies")
        or {}
    )
    job_plans = [
        {
            "job_description_id": job_id,
            "strategy": dict(job_strategies.get(job_id) or {}),
        }
        for job_id in selected_job_ids
    ]
    tool_approval_policy = dict(
        automation_config.get("toolApprovalPolicy")
        or automation_config.get("tool_approval_policy")
        or {}
    )
    execution_sop = dict(
        automation_config.get("executionSop")
        or automation_config.get("execution_sop")
        or {}
    )
    activation_policy = _structured_activation_policy(automation_config)
    resume_policy = dict(
        automation_config.get("resumePolicy")
        or automation_config.get("resume_policy")
        or {}
    )
    sync_policy = dict(
        automation_config.get("syncPolicy")
        or automation_config.get("sync_policy")
        or {}
    )
    target_recruiting_site = _target_recruiting_site_from_sop(execution_sop)
    missing_site_fields = [
        label
        for key, label in (
            ("entry_url", "siteEntryUrl"),
        )
        if not target_recruiting_site.get(key)
    ]
    if missing_site_fields:
        raise ValueError(
            "automation_recruiting_config missing target recruiting site fields: "
            + ", ".join(missing_site_fields)
        )
    compiled_sop_prompt = _compiled_automation_sop_prompt(
        execution_sop=execution_sop,
        target_recruiting_site=target_recruiting_site,
        job_plans=job_plans,
    )
    execution_sop["compiledPrompt"] = compiled_sop_prompt
    site_instruction = (
        f"招聘网站目标网页 URL：{target_recruiting_site.get('entry_url')}；"
        "复用人工已登录的浏览器会话，并由 Agent 根据页面可见导航和内容进入正确业务页面。"
    )
    payload = AutonomousTriggerRequest(
        title=f"多 JD 自动化招聘 · {len(selected_job_ids)} 个 JD",
        request_message=f"启动多 JD 自动化招聘：{len(selected_job_ids)} 个 JD",
        instruction=(
            "按已保存的自动化招聘配置启动 Agent。\n"
            f"本次运行覆盖 {len(selected_job_ids)} 个 JD；"
            f"{site_instruction}\n"
            "执行时必须遵守 JD 策略、执行 SOP、站点边界、审批规则和同步规则；"
            "模型负责生成评分、证据和建议，阈值、权限和节奏由产品配置控制。\n\n"
            "## 自动化招聘执行 SOP\n"
            f"{compiled_sop_prompt}"
        ),
        kind="multi_jd_recruiting",
        requested_by=requested_by,
        constraints={
            "scope_kind": "global",
            "plan_kind": "multi_jd_recruiting",
            "selected_job_description_ids": selected_job_ids,
            "execution_sop": execution_sop,
            "target_recruiting_site": target_recruiting_site,
            "activation_policy": activation_policy,
            "resume_policy": resume_policy,
            "sync_policy": sync_policy,
            "business_policy_overlay": {"job_plans": job_plans},
            "runtime_controls": _automation_runtime_controls(
                automation_config,
                activation_policy=activation_policy,
            ),
            "tool_approval_policy": tool_approval_policy,
        },
        success_criteria={
            "requires_online_resume_score": True,
            "requires_offline_resume_score_for_complete_candidates": True,
            "requires_composite_score": True,
            "pass_decision_source": "score_thresholds",
            "executable_job_source": "saved_automation_recruiting_config",
        },
        context_hints={
            "launch_plan": {
                "plan_kind": "multi_jd_recruiting",
                "selected_job_description_ids": selected_job_ids,
                "job_count": len(selected_job_ids),
                "target_recruiting_site": target_recruiting_site,
            }
        },
    )
    return _create_autonomous_run(session, definition=definition, payload=payload, agent_kind="autonomous")


def _automation_recruiting_config(definition: AgentDefinition) -> dict[str, Any]:
    config = _product_config(definition, "autonomous")
    raw = (
        config.get("automation_recruiting_config")
        or config.get("automationRecruitingConfig")
        or config.get("automation_config")
        or {}
    )
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _jd_sync_config(definition: AgentDefinition) -> dict[str, Any]:
    config = _product_config(definition, "jd_sync")
    raw = (
        config.get("jd_sync_config")
        or config.get("jdSyncConfig")
        or config.get("automation_config")
        or {}
    )
    if isinstance(raw, dict) and raw:
        return dict(raw)
    return _automation_recruiting_config(definition)


_LEGACY_ACTIVATION_POLICY_KEYS = {
    "priorityPreset",
    "priority_preset",
    "startConditionsText",
    "start_conditions_text",
    "stopConditionsText",
    "stop_conditions_text",
    "priorityWeightsText",
    "priority_weights_text",
    "cooldownRulesText",
    "cooldown_rules_text",
}


def _structured_activation_policy(automation_config: dict[str, Any]) -> dict[str, Any]:
    raw = (
        automation_config.get("activationPolicy")
        or automation_config.get("activation_policy")
        or {}
    )
    if not isinstance(raw, dict):
        raw = {}
    activation_policy = {
        key: value
        for key, value in dict(raw).items()
        if key not in _LEGACY_ACTIVATION_POLICY_KEYS
    }
    activation_policy["programmaticAuthority"] = True
    return activation_policy


def _target_recruiting_site_from_sop(execution_sop: dict[str, Any]) -> dict[str, Any]:
    def _text(*keys: str) -> str | None:
        for key in keys:
            value = execution_sop.get(key)
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized:
                return normalized
        return None

    access_rules_raw = _text("siteAccessRulesText", "site_access_rules_text", "siteAccessRules", "site_access_rules")
    access_rules = [
        line.strip()
        for line in (access_rules_raw or "").splitlines()
        if line.strip()
    ]
    return {
        "entry_url": _text("siteEntryUrl", "site_entry_url", "entryUrl", "entry_url"),
        "access_rules": access_rules,
    }


def _compiled_automation_sop_prompt(
    *,
    execution_sop: dict[str, Any],
    target_recruiting_site: dict[str, Any],
    job_plans: list[dict[str, Any]],
) -> str:
    steps_text = str(
        execution_sop.get("stepsText")
        or execution_sop.get("steps_text")
        or ""
    ).strip()
    selected_job_lines = [
        f"{index}. {plan.get('job_description_id')}"
        for index, plan in enumerate(job_plans, start=1)
        if plan.get("job_description_id")
    ]
    return "\n".join(
        [
            "## 本次运行目标网页与范围",
            f"招聘网站目标网页 URL：{target_recruiting_site.get('entry_url') or '未配置'}",
            "浏览器会话：复用人工已登录的浏览器会话；Agent 不处理登录、验证码、账号切换或绕过风控。",
            "选中 JD：",
            "\n".join(selected_job_lines) if selected_job_lines else "- 未选择 JD",
            "JD 策略来源：使用本次运行随附的逐 JD 筛选、在线简历评分、离线简历评分、综合评分和人工复核规则。",
            "",
            "## 执行 SOP",
            steps_text,
        ]
    )


def _automation_runtime_controls(
    automation_config: dict[str, Any],
    *,
    activation_policy: dict[str, Any],
) -> dict[str, Any]:
    job_strategies = dict(
        automation_config.get("jobStrategies")
        or automation_config.get("job_strategies")
        or {}
    )
    thresholds: dict[str, Any] = {}
    for job_id, strategy in job_strategies.items():
        if not isinstance(strategy, dict):
            continue
        thresholds[str(job_id)] = {
            "resume_scoring": dict(strategy.get("resumeScoring") or strategy.get("resume_scoring") or {}),
            "composite_scoring": dict(strategy.get("compositeScoring") or strategy.get("composite_scoring") or {}),
        }
    return {
        "decision_authority": "programmatic_thresholds_and_approval_gates",
        "activation_policy": dict(activation_policy),
        "score_thresholds_by_job": thresholds,
    }


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


def _agent_session_conversation_cleared_at(agent_session: AgentSession) -> datetime | None:
    metadata = dict(agent_session.runtime_metadata or {})
    raw_value = metadata.get("conversation_cleared_at")
    if isinstance(raw_value, datetime):
        return raw_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        return None


def _agent_session_conversation_hidden_run_ids(agent_session: AgentSession) -> list[str]:
    metadata = dict(agent_session.runtime_metadata or {})
    raw_ids = metadata.get("conversation_cleared_run_ids")
    if not isinstance(raw_ids, list):
        return []
    return [str(item) for item in raw_ids if str(item or "").strip()]


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
    agent_kind: AgentKind,
    exclude_run_id: str | None = None,
) -> AgentRun | None:
    stmt = (
        select(AgentRun)
        .where(
            AgentRun.session_id == session_id,
            AgentRun.agent_kind == agent_kind,
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
            "mcps": _list_workspace_mcps(container),
            "config": _workspace_config(definition, kind=kind, provider_label=provider_label, model_label=model_label),
            "workspace_control": None,
            "workspaceControl": None,
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
                kind=kind,
                latest_run=latest_run,
            )
        ],
        "runs": runs,
        "approvals": approvals,
        "memories": memories,
        "skills": _list_workspace_skills(session),
        "tools": _list_workspace_tools(container),
        "mcps": _list_workspace_mcps(container),
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

    definition = _resolve_agent_definition(session, kind)
    primary_conversation_id = _primary_conversation_id(kind)
    if conversation_id == primary_conversation_id:
        return _serialize_autonomous_primary_conversation_record(session, definition=definition, kind=kind)

    run = _resolve_run_for_kind(session, kind, conversation_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Conversation not found for agent kind: {kind}")
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
    kind: AgentKind = "autonomous",
    latest_run: dict[str, Any] | None,
) -> dict[str, Any]:
    projection = _product_projection(definition, kind)
    conversation_id = _primary_conversation_id(kind)
    updated_at = (
        None if latest_run is None else latest_run.get("updatedAt")
    ) or _serialize_timestamp(definition.updated_at)
    status = _workspace_status(None if latest_run is None else latest_run.get("status"))
    preview = (
        None if latest_run is None else str(latest_run.get("summary") or "").strip()
    ) or str(projection.get("description") or definition.description or "").strip() or None
    return {
        "id": conversation_id,
        "conversation_id": conversation_id,
        "conversationId": conversation_id,
        "agent_kind": kind,
        "agentKind": kind,
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
        "agent_kind": run.agent_kind,
        "agentKind": run.agent_kind,
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


def _autonomous_run_input_message(conversation_id: str, run: AgentRun) -> dict[str, Any] | None:
    context_manifest = dict(run.context_manifest or {})
    runtime_metadata = dict(run.runtime_metadata or {})
    content = _display_run_input_content(
        run=run,
        context_manifest=context_manifest,
        runtime_metadata=runtime_metadata,
    )
    if not content:
        return None
    title = str(
        context_manifest.get("requested_title")
        or runtime_metadata.get("requested_title")
        or context_manifest.get("title")
        or runtime_metadata.get("title")
        or _run_title(run)
    ).strip()
    created_at = _serialize_timestamp(run.created_at)
    return {
        "id": f"{conversation_id}:run:{run.run_id or run.id}:input",
        "conversation_id": conversation_id,
        "conversationId": conversation_id,
        "role": "user",
        "kind": "message",
        "title": title or None,
        "content": content,
        "created_at": created_at,
        "createdAt": created_at,
        "status": "sent",
        "metadata": {
            "eventKind": "human",
            "itemType": "runtime_run_request",
            "message_type": "run_input",
            "run_id": run.run_id,
            "lane": run.lane,
            "priority": run.priority,
            "requested_by": context_manifest.get("requested_by") or runtime_metadata.get("requested_by"),
        },
    }


def _display_run_input_content(
    *,
    run: AgentRun,
    context_manifest: dict[str, Any],
    runtime_metadata: dict[str, Any],
) -> str:
    content = str(
        runtime_metadata.get("instruction")
        or context_manifest.get("instruction")
        or runtime_metadata.get("requested_instruction")
        or context_manifest.get("requested_instruction")
        or context_manifest.get("requested_message")
        or runtime_metadata.get("requested_message")
        or ""
    ).strip()
    if str(run.run_type or "").strip().lower() in JD_SYNC_RUN_KINDS:
        entry_url = _run_instruction_entry_url(run, context_manifest=context_manifest, runtime_metadata=runtime_metadata)
        return _dedupe_jd_sync_instruction(content, entry_url=entry_url)
    return content


def _run_instruction_entry_url(
    run: AgentRun,
    *,
    context_manifest: dict[str, Any],
    runtime_metadata: dict[str, Any],
) -> str:
    sources = [
        dict(runtime_metadata.get("constraints") or {}),
        dict(context_manifest.get("constraints") or {}),
    ]
    for source in sources:
        target_site = dict(source.get("target_recruiting_site") or {})
        entry_url = str(target_site.get("entry_url") or "").strip()
        if entry_url:
            return entry_url
    return ""


def _autonomous_turn_message(conversation_id: str, run: AgentRun, turn: AgentTurnRecord) -> dict[str, Any]:
    final_output = str((turn.turn_metadata or {}).get("final_output") or "").strip()
    created_at = _serialize_timestamp(turn.updated_at or turn.created_at)
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
    data = dict(payload.get("data") or {})
    tool_name = str(data.get("tool_name") or data.get("name") or "").strip()
    payload_kind = str(data.get("kind") or "").strip()
    role = _runtime_event_role(event_type, data)
    kind = "message" if role in {"user", "assistant"} else "status"
    return {
        "id": str(event.get("id") or uuid4().hex),
        "conversation_id": conversation_id,
        "conversationId": conversation_id,
        "role": role,
        "kind": kind,
        "title": _runtime_event_title(event_type, data),
        "content": _runtime_event_content(event_type, data) or str(event.get("message") or event.get("event_type") or "Autonomous event"),
        "created_at": created_at,
        "createdAt": created_at,
        "status": _runtime_event_message_status(event_type, data),
        "metadata": {
            "eventKind": _runtime_event_kind(event_type, payload),
            "traceKind": _runtime_event_trace_kind(event_type, payload),
            "itemType": event_type,
            "message_type": "event",
            "event_type": event_type,
            "payloadKind": payload_kind,
            "toolName": tool_name or None,
            "toolUseId": data.get("tool_use_id"),
            "toolCallId": data.get("tool_call_id"),
            "isError": data.get("is_error"),
            "payload": payload,
        },
    }


def _runtime_event_role(event_type: str, data: dict[str, Any]) -> str:
    normalized = str(event_type or "").strip().lower()
    payload_kind = str(data.get("kind") or "").strip().lower()
    if normalized in {"assistant_message_delta", "assistant_message_completed"}:
        return "assistant"
    if normalized == "runtime_event" and payload_kind in {"pending_user_input_after_next_tool_call_injected", "run_resume_user_message"}:
        return "user"
    return "system"


def _runtime_event_title(event_type: str, data: dict[str, Any]) -> str | None:
    tool_name = str(data.get("tool_name") or data.get("name") or "").strip()
    kind = str(data.get("kind") or event_type or "").strip().lower()
    if str(event_type or "").strip().lower() in {"assistant_message_delta", "assistant_message_completed"}:
        return None
    if kind == "pending_user_input_after_next_tool_call_injected":
        return None
    if kind == "run_resume_user_message":
        return None
    if kind == "provider_retry_scheduled":
        return "模型调用重试"
    if kind == "provider_retry_exhausted":
        return "模型调用失败"
    if kind == "provider_error_terminal":
        return "模型调用异常"
    if kind in {"turn_failed", "adapter_failed", "turn_interrupted"}:
        return "运行失败"
    if kind == "tool_input_streamed":
        return f"准备工具调用：{tool_name}" if tool_name else "准备工具调用"
    if kind == "tool_use_completed":
        return f"工具输入完成：{tool_name}" if tool_name else "工具输入完成"
    if kind == "tool_call_started":
        return f"调用工具：{tool_name}" if tool_name else "调用工具"
    if kind == "tool_result_ready":
        return f"工具结果：{tool_name}" if tool_name else "工具结果"
    if kind == "tool_error":
        return f"工具异常：{tool_name}" if tool_name else "工具异常"
    if event_type == "permission_requested":
        return f"等待确认：{tool_name}" if tool_name else "等待确认"
    return None


def _runtime_event_content(event_type: str, data: dict[str, Any]) -> str | None:
    tool_name = str(data.get("tool_name") or data.get("name") or "").strip()
    kind = str(data.get("kind") or event_type or "").strip().lower()
    normalized_event_type = str(event_type or "").strip().lower()
    if normalized_event_type == "assistant_message_delta":
        return str(data.get("message") or data.get("delta") or "").strip() or None
    if normalized_event_type == "assistant_message_completed":
        return str(data.get("message") or "").strip() or None
    if kind == "pending_user_input_after_next_tool_call_injected":
        messages = data.get("messages")
        if isinstance(messages, list):
            lines: list[str] = []
            for item in messages:
                if not isinstance(item, dict):
                    continue
                metadata = item.get("metadata")
                pending_input = metadata.get("pending_input") if isinstance(metadata, dict) else None
                if isinstance(pending_input, list):
                    lines.extend(
                        str(pending.get("message") or "").strip()
                        for pending in pending_input
                        if isinstance(pending, dict) and str(pending.get("message") or "").strip()
                    )
                    continue
                content = str(item.get("content") or "").strip()
                if content:
                    lines.append(content)
            if lines:
                return "\n".join(lines)
        return None
    if kind == "run_resume_user_message":
        return str(data.get("message") or "").strip() or None
    if kind in {"provider_retry_scheduled", "provider_retry_exhausted", "provider_error_terminal"}:
        error = str(data.get("error") or "").strip()
        attempt = data.get("attempt")
        max_attempts = data.get("max_attempts")
        delay = data.get("delay_seconds")
        lines: list[str] = []
        if kind == "provider_retry_scheduled":
            lines.append(f"模型调用失败，准备重试（{attempt}/{max_attempts}）。")
            if delay is not None:
                lines.append(f"等待：{delay} 秒")
        elif kind == "provider_retry_exhausted":
            lines.append(f"模型调用重试后仍失败（{attempt}/{max_attempts}）。")
        else:
            lines.append("模型调用失败，错误不可重试。")
        if error:
            lines.append(f"错误：{error}")
        return "\n".join(lines)
    if kind in {"turn_failed", "adapter_failed", "turn_interrupted"}:
        error = str(data.get("error") or data.get("reason") or "").strip()
        return error or None
    if kind == "tool_input_streamed":
        content = _compact_event_payload(data.get("content"))
        lines = [f"工具：{tool_name}" if tool_name else "工具输入生成中"]
        if content:
            lines.append(f"参数草稿：{content}")
        return "\n".join(lines)
    if kind in {"tool_call_started", "tool_use_completed"}:
        arguments = data.get("input")
        if isinstance(arguments, dict) and arguments:
            label = "最终参数" if kind == "tool_use_completed" else "参数"
            return f"工具：{tool_name}\n{label}：{json.dumps(arguments, ensure_ascii=False, default=str)}"
        fallback = "工具输入完成" if kind == "tool_use_completed" else "工具调用已开始"
        return f"工具：{tool_name}" if tool_name else fallback
    if kind in {"tool_result_ready", "tool_error"}:
        content = _compact_event_payload(data.get("content"))
        status = "异常" if bool(data.get("is_error")) or kind == "tool_error" else "完成"
        lines = [f"工具：{tool_name}" if tool_name else "工具结果", f"状态：{status}"]
        if content:
            lines.append(f"结果：{content}")
        return "\n".join(lines)
    if event_type == "permission_requested":
        reason = str(data.get("reason") or "").strip()
        lines = [f"工具：{tool_name}" if tool_name else "工具请求人工确认"]
        if reason:
            lines.append(f"原因：{reason}")
        return "\n".join(lines)
    return None


def _compact_event_payload(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:640] if text else None


def _autonomous_run_status_text(run: AgentRun) -> str:
    status = run.status.strip().lower()
    if status == "queued":
        return "Autonomous run is queued in the backend."
    if status == "waiting_human":
        return "Autonomous run is waiting for the next runtime event."
    if status == "completed":
        return "Autonomous run completed."
    if status in {"failed", "cancelled", "interrupted"}:
        return f"Autonomous run {status}."
    return f"Autonomous run status: {run.status}."


def _autonomous_run_event_kind(run: AgentRun) -> str:
    status = run.status.strip().lower()
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
    data = dict(payload.get("data") or {})
    payload_kind = str(data.get("kind") or payload.get("kind") or "").strip().lower()
    source = f"{normalized} {payload_kind}"
    if normalized == "assistant_message_delta":
        return "thinking"
    if normalized == "assistant_message_completed":
        return "execution_result"
    if payload_kind in {"pending_user_input_after_next_tool_call_injected", "run_resume_user_message"}:
        return "human"
    if payload_kind in {"provider_retry_scheduled", "provider_retry_exhausted", "provider_error_terminal"}:
        return "execution_result"
    if normalized in {"turn_failed", "adapter_failed", "turn_interrupted"}:
        return "execution_result"
    if "permission" in source or "waiting_human" in source or "blocked" in source:
        return "confirmation"
    if payload_kind in {"tool_input_streamed", "tool_call_started", "tool_use_completed"}:
        return "tool_call"
    if payload_kind in {"tool_result_ready", "tool_error"}:
        return "execution_result"
    if "tool_call" in source or "tool_use" in source or "pending_user_input_after_next_tool_call" in source or "web_search" in source:
        return "tool_call"
    if "tool_result" in source or "turn_completed" in source:
        return "execution_result"
    if "llm_invocation" in source or "reasoning" in source or "thinking" in source:
        return "thinking"
    return "thinking"


def _runtime_event_trace_kind(event_type: str, payload: dict[str, Any]) -> str:
    normalized = event_type.strip().lower()
    data = dict(payload.get("data") or {})
    payload_kind = str(data.get("kind") or payload.get("kind") or "").strip().lower()
    if normalized in {"assistant_message_delta", "assistant_message_completed"}:
        return "assistant_message"
    if payload_kind in {"pending_user_input_after_next_tool_call_injected", "run_resume_user_message"}:
        return "user_message"
    if normalized == "permission_requested":
        return "permission_requested"
    if payload_kind in {"tool_input_streamed", "tool_call_started", "tool_use_completed"}:
        return "tool_call"
    if payload_kind in {"tool_result_ready", "tool_error"}:
        return "tool_result"
    if payload_kind in {"provider_retry_scheduled", "provider_retry_exhausted", "provider_error_terminal"}:
        return payload_kind
    if normalized in {"turn_failed", "adapter_failed", "turn_interrupted"}:
        return normalized
    return _runtime_event_kind(event_type, payload)


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
    if normalized == "assistant_message_delta":
        return "streaming"
    if normalized == "assistant_message_completed":
        return "sent"
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
    if normalized in {"turn_failed", "turn_interrupted", "adapter_failed"}:
        return "failed"
    return _workspace_status(normalized)


def _runtime_event_message_status(event_type: str, data: dict[str, Any]) -> str:
    kind = str(data.get("kind") or "").strip().lower()
    if kind == "provider_retry_scheduled":
        return "active"
    if kind in {"provider_retry_exhausted", "provider_error_terminal"}:
        return "failed"
    return _event_message_status(event_type)


def _agent_message_sort_key(message: dict[str, Any]) -> tuple[float, str, str]:
    created_at = message.get("createdAt") or message.get("created_at")
    return (
        _timestamp_sort_value(created_at),
        _message_sort_rank(message),
        str(message.get("id") or ""),
    )


def _conversation_stream_signature(record: dict[str, Any]) -> str:
    conversation = dict(record.get("conversation") or {})
    messages = list(record.get("messages") or [])
    payload = {
        "conversation": {
            "id": conversation.get("id") or conversation.get("conversationId"),
            "status": conversation.get("status"),
            "updatedAt": conversation.get("updatedAt") or conversation.get("updated_at"),
            "preview": conversation.get("preview"),
            "refId": conversation.get("refId") or conversation.get("ref_id"),
        },
        "messages": [
            {
                "id": message.get("id"),
                "role": message.get("role"),
                "kind": message.get("kind"),
                "status": message.get("status"),
                "title": message.get("title"),
                "content": message.get("content"),
                "metadata": _conversation_stream_metadata_signature(message.get("metadata")),
            }
            for message in messages
        ],
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _conversation_stream_metadata_signature(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {
        "message_type": metadata.get("message_type") or metadata.get("messageType"),
        "event_type": metadata.get("event_type") or metadata.get("eventType"),
        "eventKind": metadata.get("eventKind"),
        "traceKind": metadata.get("traceKind"),
        "runStatus": metadata.get("runStatus") or metadata.get("run_status"),
        "turnStatus": metadata.get("turnStatus") or metadata.get("turn_status"),
    }


def _message_sort_rank(message: dict[str, Any]) -> str:
    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        message_type = str(metadata.get("message_type") or "").strip().lower()
        if message_type == "run_input":
            return "0"
        if message_type == "run":
            return "1"
        if message_type == "event":
            return "2"
        if message_type == "turn":
            return "3"
    role = str(message.get("role") or "").strip().lower()
    if role == "user":
        return "0"
    if role == "assistant":
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
    kind: AgentKind = "autonomous",
) -> dict[str, Any]:
    agent_session = _get_agent_session(session, definition, kind=kind)
    conversation_id = _primary_conversation_id(kind)
    if agent_session is None:
        return {
            "conversation": _autonomous_primary_conversation_summary(
                definition=definition,
                kind=kind,
                latest_run=None,
            ),
            "messages": [],
        }

    hidden_run_ids = _agent_session_conversation_hidden_run_ids(agent_session)
    clear_after = None if hidden_run_ids else _agent_session_conversation_cleared_at(agent_session)
    recent_runs = list(
        session.scalars(
            select(AgentRun)
            .where(
                AgentRun.session_id == agent_session.id,
                AgentRun.agent_kind == kind,
                *(() if not hidden_run_ids else (AgentRun.id.not_in(hidden_run_ids),)),
                *(() if clear_after is None else (AgentRun.created_at > clear_after,)),
            )
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(20)
        ).all()
    )
    recent_runs.reverse()
    run_ids = [run.id for run in recent_runs]
    turns_by_run_id: dict[str, list[AgentTurnRecord]] = {run_id: [] for run_id in run_ids}
    events_by_run_id: dict[str, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
    if run_ids:
        turns = session.scalars(
            select(AgentTurnRecord)
            .where(AgentTurnRecord.run_pk.in_(run_ids))
            .order_by(AgentTurnRecord.created_at.asc(), AgentTurnRecord.seq.asc(), AgentTurnRecord.id.asc())
        ).all()
        for turn in turns:
            turns_by_run_id.setdefault(turn.run_pk, []).append(turn)
        runtime_events = session.scalars(
            select(AgentRuntimeEvent)
            .where(
                AgentRuntimeEvent.run_id.in_(run_ids),
                AgentRuntimeEvent.event_type.in_((
                    "assistant_message_delta",
                    "assistant_message_completed",
                    "adapter_failed",
                    "runtime_event",
                    "turn_failed",
                    "turn_interrupted",
                    "tool_event",
                    "permission_requested",
                )),
            )
            .order_by(AgentRuntimeEvent.occurred_at.asc(), AgentRuntimeEvent.seq.asc(), AgentRuntimeEvent.id.asc())
            .limit(2000)
        ).all()
        raw_events_by_run_id: dict[str, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
        for event in runtime_events:
            if not event.run_id:
                continue
            event_payload = RuntimeEventRead.model_validate(event).model_dump(by_alias=True)
            raw_events_by_run_id.setdefault(event.run_id, []).append(event_payload)
        for run_id, raw_events in raw_events_by_run_id.items():
            events_by_run_id[run_id] = _project_primary_timeline_runtime_events(raw_events)
    latest_run_payload = None if not recent_runs else _serialize_run(recent_runs[-1])

    messages: list[dict[str, Any]] = []
    for run in recent_runs:
        run_input_message = _autonomous_run_input_message(conversation_id, run)
        if run_input_message is not None:
            messages.append(run_input_message)
        run_message = _autonomous_run_message(conversation_id, run)
        messages.append(run_message)
        assistant_event_contents: set[str] = set()
        for event in events_by_run_id.get(run.id, []):
            event_message = _autonomous_event_message(conversation_id, event)
            messages.append(event_message)
            if event_message.get("role") == "assistant":
                content = str(event_message.get("content") or "").strip()
                if content:
                    assistant_event_contents.add(content)
        for turn in turns_by_run_id.get(run.id, []):
            turn_message = _autonomous_turn_message(conversation_id, run, turn)
            turn_content = str(turn_message.get("content") or "").strip()
            if not turn_content or turn_content == str(run_message.get("content") or "").strip():
                continue
            if turn_message.get("role") == "assistant" and turn_content in assistant_event_contents:
                continue
            turn_status = str(turn.status or "").strip().lower()
            has_final_output = bool(str((turn.turn_metadata or {}).get("final_output") or "").strip())
            if has_final_output or turn_status in {"waiting_human", "failed", "cancelled", "interrupted"}:
                messages.append(turn_message)

    return {
        "conversation": _autonomous_primary_conversation_summary(
            definition=definition,
            kind=kind,
            latest_run=latest_run_payload,
        ),
        "messages": sorted(messages, key=_agent_message_sort_key),
    }


def _project_primary_timeline_runtime_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    stream_groups: dict[str, dict[str, Any]] = {}
    assistant_delta_groups: dict[str, dict[str, Any]] = {}
    completed_assistant_keys: set[str] = set()
    for event in events:
        event_type = str(event.get("event_type") or event.get("eventType") or "").strip().lower()
        payload = dict(event.get("payload") or {})
        data = dict(payload.get("data") or {})
        kind = str(data.get("kind") or "").strip().lower()
        if event_type == "assistant_message_completed":
            completed_assistant_keys.add(_assistant_stream_key(event))
        if event_type == "assistant_message_delta":
            stream_key = _assistant_stream_key(event)
            group = assistant_delta_groups.setdefault(
                stream_key,
                {
                    "event": event,
                    "deltas": [],
                },
            )
            delta = str(data.get("delta") or data.get("message") or "")
            if delta:
                group["deltas"].append(delta)
            continue
        if event_type == "tool_event" and kind == "tool_use_delta":
            stream_key = str(data.get("id") or data.get("tool_use_id") or event.get("turn_id") or event.get("id") or "")
            if not stream_key:
                continue
            group = stream_groups.setdefault(
                stream_key,
                {
                    "event": event,
                    "name": "",
                    "deltas": [],
                },
            )
            if str(data.get("name") or "").strip():
                group["name"] = str(data.get("name") or "").strip()
            delta = str(data.get("delta") or "")
            if delta:
                group["deltas"].append(delta)
            continue
        if _is_primary_timeline_runtime_event(event):
            projected.append(event)

    for group in stream_groups.values():
        aggregated = _aggregated_tool_stream_event(group)
        aggregated_data = dict(dict(aggregated.get("payload") or {}).get("data") or {})
        if str(aggregated_data.get("content") or "").strip():
            projected.append(aggregated)
    for stream_key, group in assistant_delta_groups.items():
        if stream_key in completed_assistant_keys:
            continue
        aggregated = _aggregated_assistant_delta_event(group)
        aggregated_data = dict(dict(aggregated.get("payload") or {}).get("data") or {})
        if str(aggregated_data.get("message") or aggregated_data.get("delta") or "").strip():
            projected.append(aggregated)
    return sorted(projected, key=lambda item: (_timestamp_sort_value(item.get("occurredAt") or item.get("occurred_at")), int(item.get("seq") or 0), str(item.get("id") or "")))


def _assistant_stream_key(event: dict[str, Any]) -> str:
    payload = dict(event.get("payload") or {})
    data = dict(payload.get("data") or {})
    return str(data.get("invocation_id") or event.get("turn_id") or event.get("id") or "")


def _aggregated_assistant_delta_event(group: dict[str, Any]) -> dict[str, Any]:
    event = dict(group.get("event") or {})
    payload = dict(event.get("payload") or {})
    data = dict(payload.get("data") or {})
    message = "".join(str(item) for item in group.get("deltas") or [])
    data.update({"message": message, "delta": message})
    payload["data"] = data
    event["id"] = f"{event.get('id') or uuid4().hex}:assistant-stream"
    event["message"] = "assistant_message_delta"
    event["payload"] = payload
    return event


def _aggregated_tool_stream_event(group: dict[str, Any]) -> dict[str, Any]:
    event = dict(group.get("event") or {})
    payload = dict(event.get("payload") or {})
    data = dict(payload.get("data") or {})
    name = str(group.get("name") or data.get("name") or data.get("tool_name") or "").strip()
    arguments_text = "".join(str(item) for item in group.get("deltas") or []).strip()
    data.update(
        {
            "kind": "tool_input_streamed",
            "tool_name": name,
            "name": name,
            "content": arguments_text,
        }
    )
    payload["data"] = data
    event["id"] = f"{event.get('id') or uuid4().hex}:stream"
    event["message"] = "tool_input_streamed"
    event["payload"] = payload
    return event


def _is_primary_timeline_runtime_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or event.get("eventType") or "").strip().lower()
    if event_type in {"assistant_message_delta", "assistant_message_completed", "permission_requested"}:
        return True
    payload = dict(event.get("payload") or {})
    data = dict(payload.get("data") or {})
    kind = str(data.get("kind") or "").strip().lower()
    if event_type == "runtime_event":
        return (
            kind in {"pending_user_input_after_next_tool_call_injected", "run_resume_user_message"}
            and bool(_runtime_event_content(event_type, data))
        ) or kind in {"provider_retry_scheduled", "provider_retry_exhausted", "provider_error_terminal"}
    if event_type in {"turn_failed", "adapter_failed", "turn_interrupted"}:
        return True
    if event_type != "tool_event":
        return False
    return kind in {
        "tool_input_streamed",
        "tool_call_started",
        "tool_use_completed",
        "tool_result_ready",
        "tool_error",
    }


def _list_workspace_runs(session: Session, definition: AgentDefinition, kind: AgentKind) -> list[dict[str, Any]]:
    agent_session = _get_agent_session(session, definition, kind=kind)
    if agent_session is None:
        return []
    hidden_run_ids = _agent_session_conversation_hidden_run_ids(agent_session)
    clear_after = None if hidden_run_ids else _agent_session_conversation_cleared_at(agent_session)
    runs = session.scalars(
        select(AgentRun)
        .where(
            AgentRun.session_id == agent_session.id,
            AgentRun.agent_kind == kind,
            *(() if not hidden_run_ids else (AgentRun.id.not_in(hidden_run_ids),)),
            *(() if clear_after is None else (AgentRun.created_at > clear_after,)),
        )
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


def _list_workspace_mcps(container: AppContainer) -> list[dict[str, Any]]:
    return [
        McpServerRead.model_validate(item).model_dump(by_alias=True)
        for item in container.mcp_registry.list_servers()
        if bool(item.get("enabled", True) if isinstance(item, dict) else getattr(item, "enabled", True))
    ]


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
