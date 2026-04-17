from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from scene_pilot.core.settings import AppSettings
from scene_pilot.repositories import (
    AgentLearningRepository,
    PlaybookRepository,
    ApprovalRepository,
    CandidateApplicationRepository,
    CandidateRepository,
    JobDescriptionRepository,
    MetricsRepository,
    SettingsRepository,
    SkillRepository,
)
from scene_pilot.schemas.domain import AgentStatusRead, DashboardRead
from scene_pilot.services.application_subjects import application_payload_from_application
from scene_pilot.services.events import EventStreamService
from scene_pilot.services.state_machine import ensure_latest_state_machine
from scene_pilot.services.sync import SyncService


def _timestamp(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    return None


def _utcnow() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _sync_setting(settings: AppSettings, key: str, default: Any = None) -> Any:
    sync_settings = getattr(settings, "intranet_sync", None)
    if isinstance(sync_settings, dict):
        return sync_settings.get(key, default)
    return getattr(sync_settings, key, default)


def _runtime_scene_account(settings: AppSettings) -> str:
    provider_config = settings.provider_config or {}
    return str(provider_config.get("site_account") or "本机场景 01")


def _blueprint_nodes_for_dashboard(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    raw_nodes = blueprint.get("nodes")
    if not isinstance(raw_nodes, list):
        graph = blueprint.get("graph")
        if isinstance(graph, dict):
            raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list):
        raw_nodes = []
    normalized: list[dict[str, Any]] = []
    for raw_node in raw_nodes:
        if isinstance(raw_node, str):
            node_id = raw_node
            normalized.append(
                {
                    "id": node_id,
                    "name": node_id.replace("_", " ").title(),
                    "kind": "screen",
                    "status": "idle",
                    "owner": "Agent",
                    "description": "执行节点。",
                }
            )
            continue
        if not isinstance(raw_node, dict):
            continue
        node_id = str(raw_node.get("id") or raw_node.get("node_id") or raw_node.get("task_type") or "node")
        normalized.append(
            {
                "id": node_id,
                "name": str(raw_node.get("name") or node_id.replace("_", " ").title()),
                "kind": str(raw_node.get("kind") or raw_node.get("task_type") or "screen"),
                "status": str(raw_node.get("status") or "idle"),
                "owner": str(raw_node.get("owner") or "Agent"),
                "description": str(raw_node.get("description") or "执行节点。"),
            }
        )
    return normalized


def _candidate_followup_summary_definitions(session: Session) -> list[dict[str, Any]]:
    machine = ensure_latest_state_machine(session)
    node_by_id = {
        str(node.get("id")): dict(node)
        for node in machine.get("nodes", [])
        if node.get("id")
    }

    def label_for(status_id: str) -> str:
        node = node_by_id.get(status_id)
        return str((node or {}).get("label") or status_id)

    visible_statuses = [
        status_id
        for status_id, node in node_by_id.items()
        if node.get("uiConfig", {}).get("showInKanban", True) is not False and not node.get("isTransient")
    ]
    closure_statuses = [
        status_id for status_id in ("no_response", "cooldown", "archived", "candidate_withdrew") if status_id in node_by_id
    ]
    active_statuses = [
        status_id
        for status_id, node in node_by_id.items()
        if status_id in visible_statuses
        and node.get("phase") != "Z"
        and (((not node.get("isTerminal")) and (not node.get("isSoftTerminal"))) or node.get("isSuccess"))
        and status_id not in closure_statuses
    ]
    human_required_statuses = [
        status_id
        for status_id in active_statuses
        if str((node_by_id.get(status_id) or {}).get("executionConfig", {}).get("mode") or "") == "human_required"
    ]

    def build_definition(
        *,
        key: str,
        label: str,
        summary: str,
        relation: str | None,
        matching_mode: str,
        include_statuses: list[str],
        exclude_statuses: list[str] | None = None,
    ) -> dict[str, Any]:
        exclude = list(exclude_statuses or [])
        return {
            "key": key,
            "label": label,
            "summary": summary,
            "relation": relation,
            "matchingMode": matching_mode,
            "includeStatuses": include_statuses,
            "excludeStatuses": exclude,
            "includeLabels": [label_for(status_id) for status_id in include_statuses],
            "excludeLabels": [label_for(status_id) for status_id in exclude],
        }

    return [
        build_definition(
            key="all",
            label="全部状态",
            summary="当前岗位与时间筛选下可见的全部候选人。",
            relation="基准池",
            matching_mode="all",
            include_statuses=visible_statuses,
        ),
        build_definition(
            key="active",
            label="跟进中",
            summary="仍在主流程里活跃推进的候选人总池。",
            relation="主流程总池",
            matching_mode="status_set",
            include_statuses=active_statuses,
            exclude_statuses=closure_statuses,
        ),
        build_definition(
            key="human",
            label="等待人工",
            summary="当前停在需要招聘员处理或确认节点的候选人。",
            relation="跟进中的子集",
            matching_mode="status_set",
            include_statuses=human_required_statuses,
            exclude_statuses=closure_statuses,
        ),
        build_definition(
            key="no_response",
            label="无回复·可重试",
            summary="已发送跟进但尚未回复，仍处于可自动重试窗口内的候选人。",
            relation="独立等待池",
            matching_mode="status_set",
            include_statuses=[status_id for status_id in ["no_response"] if status_id in node_by_id],
        ),
        build_definition(
            key="cooldown",
            label="冷却中",
            summary="已暂时暂停推进，等待冷却期结束或人工重新激活的候选人。",
            relation="暂停池",
            matching_mode="status_set",
            include_statuses=[status_id for status_id in ["cooldown"] if status_id in node_by_id],
        ),
        build_definition(
            key="archived",
            label="已归档",
            summary="流程已收口，仅做记录保留的候选人。",
            relation="收口态",
            matching_mode="status_set",
            include_statuses=[status_id for status_id in ["archived"] if status_id in node_by_id],
        ),
        build_definition(
            key="candidate_withdrew",
            label="候选人主动放弃",
            summary="候选人明确表示退出当前流程，不再继续推进。",
            relation="收口态",
            matching_mode="status_set",
            include_statuses=[status_id for status_id in ["candidate_withdrew"] if status_id in node_by_id],
        ),
    ]


class DashboardService:
    def __init__(
        self,
        settings: AppSettings,
        events: EventStreamService,
        sync_service: SyncService,
    ) -> None:
        self.settings = settings
        self.events = events
        self.sync_service = sync_service

    def build_agent_status(self, *, queue_depth: int = 0) -> AgentStatusRead:
        health = "warning" if queue_depth > 0 else "healthy"
        return AgentStatusRead(
            status="running" if queue_depth else "idle",
            active_task="等待队列任务" if not queue_depth else "正在处理已排队的招聘任务",
            browser_lock="held" if queue_depth else "free",
            uptime="00:00:00",
            queue_depth=queue_depth,
            token_budget_used=0,
            health=health,
        )

    def build_dashboard(self, session: Session, *, queue_depth: int = 0) -> DashboardRead:
        candidate_repo = CandidateRepository(session)
        application_repo = CandidateApplicationRepository(session)
        job_description_repo = JobDescriptionRepository(session)
        playbook_repo = PlaybookRepository(session)
        skill_repo = SkillRepository(session)
        approval_repo = ApprovalRepository(session)
        learning_repo = AgentLearningRepository(session)
        metrics_repo = MetricsRepository(session)
        settings_repo = SettingsRepository(session)

        metrics = metrics_repo.summary()
        settings = AppSettings.model_validate(settings_repo.load(self.settings).model_dump())
        applications = application_repo.list(limit=50)
        playbooks = playbook_repo.list(limit=50)
        skills = skill_repo.list(limit=50)
        approvals = approval_repo.list(limit=50)
        learnings = learning_repo.list(limit=50)
        application_count = application_repo.count()
        application_by_status = application_repo.count_by_status()

        pipeline_map = {
            "发现": 0,
            "初筛": 0,
            "联系方式/沟通": 0,
            "简历/评估": 0,
            "面试/结果": 0,
        }
        for application in applications:
            status = application.current_status
            if status in {"discovered", "ai_online_pending", "ai_online_passed", "ai_online_rejected", "outreach_pending"}:
                pipeline_map["发现"] += 1
            elif status in {"offline_scoring", "offline_score_passed", "offline_score_rejected", "human_review_pending", "human_review_passed", "human_review_rejected"}:
                pipeline_map["初筛"] += 1
            elif status in {"outreach_sent", "in_conversation", "resume_requested", "contact_requested", "contact_acquired", "cooldown", "candidate_withdrew", "no_response"}:
                pipeline_map["联系方式/沟通"] += 1
            elif status in {"resume_received"}:
                pipeline_map["简历/评估"] += 1
            elif status in {"interview_pending", "interview_scheduled", "interview_completed", "interview_passed", "interview_rejected", "offer_pending", "offer_sent", "offer_accepted", "offer_declined"}:
                pipeline_map["面试/结果"] += 1

        dashboard_payload: dict[str, Any] = {
            "metrics": [
                {
                    "label": "候选人",
                    "value": str(application_count),
                    "delta": f"{application_by_status.get('offline_scoring', 0) + application_by_status.get('human_review_pending', 0)} 个正在初筛",
                    "tone": "positive" if application_count else "neutral",
                    "caption": "已记录到本地 SQLite",
                },
                {
                    "label": "执行蓝图",
                    "value": str(metrics.playbook_count),
                    "delta": f"{application_by_status.get('offer_accepted', 0)} 位已进入后续交接",
                    "tone": "neutral",
                    "caption": "Recruit Agent 当前可用的 Playbook 蓝图",
                },
                {
                    "label": "Skills",
                    "value": str(metrics.skill_count),
                    "delta": f"{metrics.active_skill_count} 个已激活 · {sum(1 for skill in skills if skill.status == 'pending_review')} 个待审查",
                    "tone": "warning" if metrics.pending_approval_count else "positive",
                    "caption": "Skill 生命周期清单",
                },
                {
                    "label": "待审批",
                    "value": str(metrics.pending_approval_count),
                    "delta": f"{self.sync_service.pending_count()} 条等待同步",
                    "tone": "warning" if metrics.pending_approval_count else "neutral",
                    "caption": "仅桌面端审批",
                },
            ],
            "pipeline": [
                {"label": key, "value": value, "target": max(value, 1) + 2}
                for key, value in pipeline_map.items()
            ],
            "timeline": [
                {
                    "id": event.id,
                    "label": event.source,
                    "detail": event.message,
                    "at": _timestamp(event.at) or _utcnow(),
                    "tone": "warning" if event.level == "warning" else "critical" if event.level == "error" else "positive",
                }
                for event in self.events.snapshot()[-10:]
            ],
            "alerts": [
                {
                    "id": approval.id,
                    "label": "审批待处理",
                    "detail": approval.title,
                    "at": _timestamp(approval.created_at) or _utcnow(),
                    "tone": "warning",
                }
                for approval in approvals
                if approval.status == "pending"
            ]
            + [
                {
                    "id": skill.id,
                    "label": "Skill health 已降级",
                    "detail": skill.name,
                    "at": _timestamp(skill.last_health_check) or _utcnow(),
                    "tone": "critical" if skill.last_health_status == "critical" else "warning",
                }
                for skill in skills
                if skill.status == "degraded"
            ]
            + [
                {
                    "id": learning.id,
                    "label": "可用学习草案",
                    "detail": learning.content[:120],
                    "at": _timestamp(learning.created_at) or _utcnow(),
                    "tone": "positive" if learning.is_active else "neutral",
                }
                for learning in learnings[:5]
            ],
            "applications": [
                {
                    "id": payload["id"],
                    "applicationId": payload["application_id"],
                    "personId": payload["person_id"],
                    "jobDescriptionId": payload["job_description_id"],
                    "platform": payload["platform"],
                    "currentStatus": payload["current_status"],
                    "stageKey": payload["stage_key"],
                    "deepestMilestone": payload.get("deepest_milestone"),
                    "matchScore": payload["match_score"],
                    "nextAction": payload["next_action"],
                    "summary": payload["summary"],
                    "resumeAvailable": payload["resume_available"],
                    "person": payload["person"],
                    "jobDescription": payload["job_description"],
                    "stateSnapshot": payload["state_snapshot"],
                    "aiScores": payload["ai_scores"],
                    "cooldownUntil": _timestamp(payload["cooldown_until"]),
                    "lastContactedAt": _timestamp(payload["last_contacted_at"]),
                }
                for payload in (
                    application_payload_from_application(
                        application,
                        person=candidate_repo.resolve(application.person_id),
                        job_description=(
                            job_description_repo.get(application.job_description_id)
                            if getattr(application, "job_description_id", None)
                            else None
                        ),
                    )
                    for application in applications
                )
            ],
            "applicationFollowUpSummaryDefinitions": _candidate_followup_summary_definitions(session),
            "playbooks": [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "scopeKind": item.scope_kind,
                    "scopeRef": item.scope_ref,
                    "status": item.status,
                    "version": f"v{item.version}",
                    "updatedAt": _timestamp(item.updated_at) or _utcnow(),
                    "nodes": _blueprint_nodes_for_dashboard(item.blueprint),
                }
                for item in playbooks
            ],
            "skills": [
                {
                    "id": item.id,
                    "name": item.name,
                    "version": str(item.version),
                    "status": item.status,
                    "boundStage": item.bound_to_stage or "unbound",
                    "platform": item.platform,
                    "health": item.last_health_status or "warning",
                    "lastCheckedAt": _timestamp(item.last_health_check) or _utcnow(),
                    "summary": item.strategy.get("summary", "Skill 策略由本地优先运行时生成。"),
                }
                for item in skills
            ],
            "approvals": [
                {
                    "id": item.id,
                    "kind": item.target_type,
                    "title": item.title,
                    "detail": item.notes or item.payload.get("summary", "等待人工审查。"),
                    "requester": item.requested_by or "agent",
                    "status": item.status,
                    "createdAt": _timestamp(item.created_at) or _utcnow(),
                }
                for item in approvals
            ],
            "agent": self.build_agent_status(queue_depth=queue_depth).model_dump(),
            "settings": {
                "locale": "en-US",
                "timezone": "Asia/Shanghai",
                "intranetEnabled": settings.feature_flags.enable_intranet_sync,
                "desktopApprovalsOnly": settings.approval_source == "desktop_app",
                "providers": [
                    {
                        "kind": "openai-compatible",
                        "name": "主 OpenAI 接口",
                        "model": settings.provider_config.get("openai_model", "gpt-5.4"),
                        "enabled": True,
                        "temperature": 0.2,
                        "baseUrl": settings.provider_config.get("openai_base_url", "https://api.openai.com/v1"),
                        "timeoutSeconds": int(settings.provider_config.get("openai_timeout_seconds", 180) or 180),
                    },
                    {
                        "kind": "anthropic",
                        "name": "备用 Anthropic 接口",
                        "model": settings.provider_config.get("anthropic_model", "claude-sonnet-4"),
                        "enabled": False,
                        "temperature": 0.2,
                        "baseUrl": settings.provider_config.get("anthropic_base_url", "https://api.anthropic.com"),
                        "timeoutSeconds": int(settings.provider_config.get("anthropic_timeout_seconds", 180) or 180),
                    },
                ],
                "intranetSync": {
                    "enabled": settings.feature_flags.enable_intranet_sync,
                    "baseUrl": _sync_setting(settings, "base_url"),
                    "apiPath": _sync_setting(settings, "api_path", "/api/recruit-agent/sync"),
                    "timeoutSeconds": _sync_setting(settings, "timeout_seconds", 10),
                },
                "platform": {
                    "name": "本地执行配置",
                    "account": _runtime_scene_account(settings),
                    "cooldownDays": settings.provider_config.get("cooldown_days", 30),
                    "allowOutboundMessaging": settings.feature_flags.enable_outbound_messaging,
                },
            },
        }
        return DashboardRead.model_validate(dashboard_payload)
