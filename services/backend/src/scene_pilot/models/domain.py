from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from scene_pilot.db.base import Base, TimestampMixin, generate_id, utcnow


class Candidate(Base, TimestampMixin):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="site", index=True)
    platform_candidate_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="discovered", index=True)
    current_stage_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    jd_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    contact_info: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    state_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
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
    message_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CandidateStageEvent(Base, TimestampMixin):
    __tablename__ = "candidate_stage_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="stage_transition")
    from_status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    to_status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    phase_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    phase_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stage_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stage_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="agent", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    __table_args__ = (
        Index("ix_candidate_stage_events_candidate_occurred_at", "candidate_id", "occurred_at"),
    )


class CandidateAssessment(Base, TimestampMixin):
    __tablename__ = "candidate_assessments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="ai")
    stage_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", index=True)
    decision: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    assessment_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_candidate_assessments_candidate_created_at", "candidate_id", "created_at"),
    )


class CandidateAssignment(Base, TimestampMixin):
    __tablename__ = "candidate_assignments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    assignee: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    owner_role: Mapped[str] = mapped_column(String(64), nullable=False, default="operator", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignment_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_candidate_assignments_candidate_assigned_at", "candidate_id", "assigned_at"),
    )


class ResumeArtifact(Base, TimestampMixin):
    __tablename__ = "resume_artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="site", index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False, default="resume", index=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    __table_args__ = (
        Index("ix_resume_artifacts_candidate_captured_at", "candidate_id", "captured_at"),
    )


class CandidateScorecard(Base, TimestampMixin):
    __tablename__ = "candidate_scorecards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="ai", index=True)
    rubric_version: Mapped[str] = mapped_column(String(64), nullable=False, default="recruit-scorecard-v1")
    score_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimension_scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    scorecard_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_candidate_scorecards_candidate_created_at", "candidate_id", "created_at"),
    )


class CandidateReviewDecision(Base, TimestampMixin):
    __tablename__ = "candidate_review_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    decision: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scorecard_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidate_scorecards.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    review_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    __table_args__ = (
        Index("ix_candidate_review_decisions_candidate_decided_at", "candidate_id", "decided_at"),
    )


class TalentPoolSyncRecord(Base, TimestampMixin):
    __tablename__ = "talent_pool_sync_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String(128), nullable=False, default="talent_pool", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payload_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_talent_pool_sync_records_candidate_created_at", "candidate_id", "created_at"),
    )


class EvolutionArtifact(Base, TimestampMixin):
    __tablename__ = "evolution_artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    agent_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("recruit_agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    artifact_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review", index=True)
    related_candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    related_skill_id: Mapped[str | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), nullable=True, index=True)
    proposed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    artifact_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class McpServer(Base, TimestampMixin):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("server_key", name="uq_mcp_servers_server_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    server_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    transport_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="unix_socket", index=True)
    protocol: Mapped[str] = mapped_column(String(64), nullable=False, default="json_socket_tool_call", index=True)
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    preset_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    auth_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    server_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    health_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class McpTool(Base, TimestampMixin):
    __tablename__ = "mcp_tools"
    __table_args__ = (
        UniqueConstraint("server_id", "name", name="uq_mcp_tools_server_name"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    server_id: Mapped[str] = mapped_column(ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium", index=True)
    remote_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tool_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


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


class RecruitAgentProfile(Base, TimestampMixin):
    __tablename__ = "recruit_agent_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    agent_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    role_definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    prompt_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    workflow_definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    memory_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dashboard_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    channel_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    agent_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class CandidateMemory(Base, TimestampMixin):
    __tablename__ = "candidate_memories"
    __table_args__ = (
        UniqueConstraint("agent_profile_id", "candidate_id", name="uq_candidate_memories_agent_candidate"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    agent_profile_id: Mapped[str] = mapped_column(
        ForeignKey("recruit_agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    memory_schema_version: Mapped[str] = mapped_column(String(64), nullable=False, default="candidate-memory-v1")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    disclosure: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    compacted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class JobMemory(Base, TimestampMixin):
    __tablename__ = "job_memories"
    __table_args__ = (
        UniqueConstraint("agent_profile_id", "jd_id", name="uq_job_memories_agent_jd"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    agent_profile_id: Mapped[str] = mapped_column(
        ForeignKey("recruit_agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    jd_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    memory_schema_version: Mapped[str] = mapped_column(String(64), nullable=False, default="job-memory-v1")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    disclosure: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    compacted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AgentGlobalMemory(Base, TimestampMixin):
    __tablename__ = "agent_global_memories"
    __table_args__ = (
        UniqueConstraint("agent_profile_id", name="uq_agent_global_memories_agent"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    agent_profile_id: Mapped[str] = mapped_column(
        ForeignKey("recruit_agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    memory_schema_version: Mapped[str] = mapped_column(String(64), nullable=False, default="agent-global-memory-v1")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    disclosure: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    compacted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AgentSession(Base, TimestampMixin):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint("agent_profile_id", "session_key", name="uq_agent_sessions_agent_session_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    agent_profile_id: Mapped[str] = mapped_column(
        ForeignKey("recruit_agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="primary")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    current_goal_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    current_lane: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    execution_episode_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_episodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    goal_spec_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    jd_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="site", index=True)
    lane: Mapped[str] = mapped_column(String(32), nullable=False, default="agent", index=True)
    run_type: Mapped[str] = mapped_column(String(64), nullable=False, default="generic", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, index=True)
    queue_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    checkpoint_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none", index=True)
    context_manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_agent_runs_session_status_priority", "session_id", "status", "priority"),
        Index("ix_agent_runs_candidate_status", "candidate_id", "status"),
    )


class AgentWorkItem(Base, TimestampMixin):
    __tablename__ = "agent_work_items"
    __table_args__ = (
        UniqueConstraint("queue_task_id", name="uq_agent_work_items_queue_task_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    queue_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    goal_spec_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="site", index=True)
    lane: Mapped[str] = mapped_column(String(32), nullable=False, default="agent", index=True)
    item_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deferred_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentRunCheckpoint(Base, TimestampMixin):
    __tablename__ = "agent_run_checkpoints"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approval_items.id", ondelete="SET NULL"), nullable=True, index=True)
    checkpoint_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_run_checkpoints_run_status", "run_id", "status"),
    )


class AgentRuntimeEvent(Base, TimestampMixin):
    __tablename__ = "agent_runtime_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(32), nullable=False, default="info", index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    __table_args__ = (
        Index("ix_agent_runtime_events_session_occurred_at", "session_id", "occurred_at"),
        Index("ix_agent_runtime_events_run_occurred_at", "run_id", "occurred_at"),
    )


class GoalSpec(Base, TimestampMixin):
    __tablename__ = "goal_specs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    agent_profile_id: Mapped[str] = mapped_column(
        ForeignKey("recruit_agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    goal_text: Mapped[str] = mapped_column(Text, nullable=False)
    goal_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="recruiting", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="operator", index=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    success_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    context_hints: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    trial_budget: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    run_preferences: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    goal_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_goal_specs_agent_status", "agent_profile_id", "status"),
    )


class ExecutionTrace(Base, TimestampMixin):
    __tablename__ = "execution_traces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    goal_spec_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    lane: Mapped[str] = mapped_column(String(32), nullable=False, default="agent", index=True)
    trace_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="adaptive_run", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="captured", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_trace: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    distilled_trace: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    trace_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        Index("ix_execution_traces_goal_created_at", "goal_spec_id", "created_at"),
        Index("ix_execution_traces_run_created_at", "run_id", "created_at"),
    )


class StrategyFragment(Base, TimestampMixin):
    __tablename__ = "strategy_fragments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    agent_profile_id: Mapped[str] = mapped_column(
        ForeignKey("recruit_agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    goal_spec_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    jd_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="agent", index=True)
    fragment_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="strategy", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    adoption_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fragment_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_strategy_fragments_agent_status", "agent_profile_id", "status"),
        Index("ix_strategy_fragments_kind_scope", "fragment_kind", "scope"),
    )


class ExecutionGraphProjection(Base, TimestampMixin):
    __tablename__ = "execution_graph_projections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    goal_spec_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    graph_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="execution_projection", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    nodes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    edges: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    rendered_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    graph_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_execution_graph_projections_goal_created_at", "goal_spec_id", "created_at"),
        Index("ix_execution_graph_projections_run_created_at", "run_id", "created_at"),
    )


class OperatorInteraction(Base, TimestampMixin):
    __tablename__ = "operator_interactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=generate_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    checkpoint_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approval_items.id", ondelete="SET NULL"), nullable=True, index=True)
    goal_spec_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    lane: Mapped[str] = mapped_column(String(32), nullable=False, default="agent", index=True)
    interaction_type: Mapped[str] = mapped_column(String(64), nullable=False, default="confirm", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    operator_response: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    effect_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="run_only", index=True)
    interaction_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    surfaced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_operator_interactions_status_surfaced_at", "status", "surfaced_at"),
        Index("ix_operator_interactions_candidate_status", "candidate_id", "status"),
        Index("ix_operator_interactions_approval_status", "approval_id", "status"),
    )


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
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    bound_to_stage: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="site", index=True)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    strategy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    execution_hints: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium", index=True)
    health_check_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    skill_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
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
