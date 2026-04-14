from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from scene_pilot.core.settings import AppSettings
from scene_pilot.repositories import (
    AgentLearningRepository,
    ApprovalRepository,
    CandidateRepository,
    MetricsRepository,
    SettingsRepository,
    SkillRepository,
    WorkflowRepository,
)
from scene_pilot.schemas.domain import AgentStatusRead, DashboardRead
from scene_pilot.services.events import EventStreamService
from scene_pilot.services.sync import SyncService


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sync_setting(settings: AppSettings, key: str, default: Any = None) -> Any:
    sync_settings = getattr(settings, "intranet_sync", None)
    if isinstance(sync_settings, dict):
        return sync_settings.get(key, default)
    return getattr(sync_settings, key, default)


def _runtime_scene_account(settings: AppSettings) -> str:
    provider_config = settings.provider_config or {}
    return str(provider_config.get("site_account") or provider_config.get("boss_account") or "runtime-scene-01")


def _workflow_nodes_for_dashboard(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_nodes = config.get("nodes") or []
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
                    "description": "Workflow node.",
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
                "description": str(raw_node.get("description") or "Workflow node."),
            }
        )
    return normalized


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
            active_task="Awaiting queued task" if not queue_depth else "Processing queued recruiting task",
            browser_lock="held" if queue_depth else "free",
            uptime="00:00:00",
            queue_depth=queue_depth,
            token_budget_used=0,
            health=health,
        )

    def build_dashboard(self, session: Session, *, queue_depth: int = 0) -> DashboardRead:
        candidate_repo = CandidateRepository(session)
        workflow_repo = WorkflowRepository(session)
        skill_repo = SkillRepository(session)
        approval_repo = ApprovalRepository(session)
        learning_repo = AgentLearningRepository(session)
        metrics_repo = MetricsRepository(session)
        settings_repo = SettingsRepository(session)

        metrics = metrics_repo.summary()
        settings = AppSettings.model_validate(settings_repo.load(self.settings).model_dump())
        candidates = candidate_repo.list(limit=50)
        workflows = workflow_repo.list(limit=50)
        skills = skill_repo.list(limit=50)
        approvals = approval_repo.list(limit=50)
        learnings = learning_repo.list(limit=50)

        pipeline_map = {
            "Discovery": 0,
            "Screening": 0,
            "Communication": 0,
            "Scoring": 0,
            "Human review": 0,
        }
        for candidate in candidates:
            status = candidate.status
            if status in {"discovered"}:
                pipeline_map["Discovery"] += 1
            elif status in {"screening"}:
                pipeline_map["Screening"] += 1
            elif status in {"pending_communication", "communicating", "waiting_reply", "pending_resume"}:
                pipeline_map["Communication"] += 1
            elif status in {"scoring", "passed_to_talent_pool"}:
                pipeline_map["Scoring"] += 1
            elif status in {"hr_review", "team_review"}:
                pipeline_map["Human review"] += 1

        dashboard_payload: dict[str, Any] = {
            "metrics": [
                {
                    "label": "Candidates",
                    "value": str(metrics.candidate_count),
                    "delta": f"{metrics.by_status.get('screening', 0)} screening",
                    "tone": "positive" if metrics.candidate_count else "neutral",
                    "caption": "Tracked in local SQLite",
                },
                {
                    "label": "Workflows",
                    "value": str(metrics.workflow_count),
                    "delta": f"{metrics.by_status.get('passed_to_talent_pool', 0)} passed",
                    "tone": "neutral",
                    "caption": "Configured workflow graphs",
                },
                {
                    "label": "Skills",
                    "value": str(metrics.skill_count),
                    "delta": f"{metrics.active_skill_count} active · {sum(1 for skill in skills if skill.status == 'pending_review')} pending review",
                    "tone": "warning" if metrics.pending_approval_count else "positive",
                    "caption": "Skill lifecycle inventory",
                },
                {
                    "label": "Pending approvals",
                    "value": str(metrics.pending_approval_count),
                    "delta": f"{self.sync_service.pending_count()} waiting for sync",
                    "tone": "warning" if metrics.pending_approval_count else "neutral",
                    "caption": "Desktop-only approvals",
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
                    "at": event.at,
                    "tone": "warning" if event.level == "warning" else "critical" if event.level == "error" else "positive",
                }
                for event in self.events.snapshot()[-10:]
            ],
            "alerts": [
                {
                    "id": approval.id,
                    "label": "Approval pending",
                    "detail": approval.title,
                    "at": approval.created_at.isoformat(),
                    "tone": "warning",
                }
                for approval in approvals
                if approval.status == "pending"
            ]
            + [
                {
                    "id": skill.id,
                    "label": "Skill health degraded",
                    "detail": skill.name,
                    "at": (skill.last_health_check.isoformat() if skill.last_health_check else _utcnow()),
                    "tone": "critical" if skill.last_health_status == "critical" else "warning",
                }
                for skill in skills
                if skill.status == "degraded"
            ]
            + [
                {
                    "id": learning.id,
                    "label": "Learning draft available",
                    "detail": learning.content[:120],
                    "at": learning.created_at.isoformat(),
                    "tone": "positive" if learning.is_active else "neutral",
                }
                for learning in learnings[:5]
            ],
            "candidates": [
                {
                    "id": item.id,
                    "name": item.name,
                    "title": item.contact_info.get("title", "Candidate"),
                    "platform": item.platform,
                    "location": item.contact_info.get("location", "Unknown"),
                    "status": item.status,
                    "workflowNode": item.current_workflow_node or "discover_candidate",
                    "jdTitle": item.jd_id or "Unassigned JD",
                    "matchScore": int(item.ai_scores.get("overall", 0) or 0),
                    "experienceYears": int(item.contact_info.get("experience_years", 0) or 0),
                    "nextAction": item.contact_info.get("next_action", "Review candidate."),
                    "summary": item.ai_reasoning or item.online_resume_text or "Candidate profile is awaiting review.",
                    "tags": item.contact_info.get("tags", []),
                    "resumeAvailable": bool(item.resume_path),
                    "cooldownUntil": item.cooldown_until.isoformat() if item.cooldown_until else None,
                    "lastContactedAt": item.last_contacted_at.isoformat() if item.last_contacted_at else None,
                }
                for item in candidates
            ],
            "workflows": [
                {
                    "id": item.id,
                    "name": item.name,
                    "jdTitle": item.jd_id or "Unassigned JD",
                    "status": item.status,
                    "version": f"v{item.version}",
                    "updatedAt": item.updated_at.isoformat(),
                    "nodes": _workflow_nodes_for_dashboard(item.config),
                }
                for item in workflows
            ],
            "skills": [
                {
                    "id": item.id,
                    "name": item.name,
                    "version": str(item.version),
                    "status": item.status,
                    "boundNode": item.bound_to_workflow_node or "unbound",
                    "platform": item.platform,
                    "health": item.last_health_status or "warning",
                    "lastCheckedAt": item.last_health_check.isoformat() if item.last_health_check else _utcnow(),
                    "summary": item.strategy.get("summary", "Skill strategy scaffolded from the local-first runtime."),
                }
                for item in skills
            ],
            "approvals": [
                {
                    "id": item.id,
                    "kind": item.target_type,
                    "title": item.title,
                    "detail": item.notes or item.payload.get("summary", "Pending human review."),
                    "requester": item.requested_by or "agent",
                    "status": item.status,
                    "createdAt": item.created_at.isoformat(),
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
                        "name": "Primary OpenAI API",
                        "model": settings.provider_config.get("openai_model", "gpt-5.4"),
                        "enabled": True,
                        "temperature": 0.2,
                        "baseUrl": settings.provider_config.get("openai_base_url", "https://api.openai.com/v1"),
                    },
                    {
                        "kind": "anthropic",
                        "name": "Fallback Anthropic",
                        "model": settings.provider_config.get("anthropic_model", "claude-sonnet-4"),
                        "enabled": False,
                        "temperature": 0.2,
                        "baseUrl": settings.provider_config.get("anthropic_base_url", "https://api.anthropic.com"),
                    },
                ],
                "intranetSync": {
                    "enabled": settings.feature_flags.enable_intranet_sync,
                    "baseUrl": _sync_setting(settings, "base_url"),
                    "apiPath": _sync_setting(settings, "api_path", "/api/scene-pilot/sync"),
                    "timeoutSeconds": _sync_setting(settings, "timeout_seconds", 10),
                },
                "platform": {
                    "name": "Runtime scene profile",
                    "account": _runtime_scene_account(settings),
                    "cooldownDays": settings.provider_config.get("cooldown_days", 30),
                    "allowOutboundMessaging": settings.feature_flags.enable_outbound_messaging,
                },
            },
        }
        return DashboardRead.model_validate(dashboard_payload)
