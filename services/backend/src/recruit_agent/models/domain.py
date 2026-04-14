from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from recruit_agent.db.base import Base, TimestampMixin, generate_id


class Candidate(Base, TimestampMixin):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="site", index=True)
    platform_candidate_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="discovered", index=True)
    current_workflow_node: Mapped[str | None] = mapped_column(String(128), nullable=True)
    jd_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    contact_info: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    resume_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    online_resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ai_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CandidateSession(Base, TimestampMixin):
    __tablename__ = "candidate_sessions"
    __table_args__ = (UniqueConstraint("candidate_id", name="uq_candidate_sessions_candidate_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recent_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    suspend_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CommunicationLog(Base):
    __tablename__ = "communication_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="site", index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    jd_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", index=True)
    current_node: Mapped[str | None] = mapped_column(String(128), nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskSpec(Base, TimestampMixin):
    __tablename__ = "task_specs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="general", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="natural_language", index=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    success_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    approval_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_contract: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    preferred_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    preferred_domains: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    compiled_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    active_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)


class ExecutionPlan(Base, TimestampMixin):
    __tablename__ = "execution_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    task_spec_id: Mapped[str] = mapped_column(ForeignKey("task_specs.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="trial", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approval_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed", index=True)
    plan_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    environment_requirements: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    checkpoints: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    compiled_from_patch_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)


class ExecutionEpisode(Base, TimestampMixin):
    __tablename__ = "execution_episodes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    task_spec_id: Mapped[str] = mapped_column(ForeignKey("task_specs.id", ondelete="CASCADE"), nullable=False, index=True)
    execution_plan_id: Mapped[str] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="trial", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    observations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    divergence_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    patch_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkflowTemplate(Base, TimestampMixin):
    __tablename__ = "workflow_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    template_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="general", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_task_spec_id: Mapped[str | None] = mapped_column(
        ForeignKey("task_specs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    activation_strategy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowPatch(Base, TimestampMixin):
    __tablename__ = "workflow_patches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    patch_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="execution_divergence", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review", index=True)
    template_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_spec_id: Mapped[str | None] = mapped_column(
        ForeignKey("task_specs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    execution_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    execution_episode_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_episodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    proposed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    divergence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    patch_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class EnvironmentSnapshot(Base, TimestampMixin):
    __tablename__ = "environment_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    task_spec_id: Mapped[str | None] = mapped_column(
        ForeignKey("task_specs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    execution_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    execution_episode_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_episodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="browser", index=True)
    environment_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="observed", index=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page_type: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    capability_hints: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    observed_entities: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    affordances: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class TaskQueueItem(Base, TimestampMixin):
    __tablename__ = "task_queue"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_task_queue_status_priority", "status", "priority"),
    )


class SyncBacklogEntry(Base, TimestampMixin):
    __tablename__ = "sync_backlog"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    protocol_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    destination: Mapped[str] = mapped_column(String(64), nullable=False, default="intranet", index=True)
    item_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    skill_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    bound_to_workflow_node: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="site", index=True)
    strategy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    execution_hints: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    health_check_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalItem(Base, TimestampMixin):
    __tablename__ = "approval_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppSetting(Base, TimestampMixin):
    __tablename__ = "app_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="singleton")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class DecisionLog(Base):
    __tablename__ = "decision_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    hr_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hr_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentLearning(Base, TimestampMixin):
    __tablename__ = "agent_learnings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    consolidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
