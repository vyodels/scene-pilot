from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class FeatureFlags(BaseModel):
    enable_autonomy: bool = False
    enable_system_commands: bool = False
    enable_intranet_sync: bool = False
    enable_outbound_messaging: bool = False


class AppSettingsBase(BaseModel):
    app_name: str = "RecruitAgent"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8741
    data_dir: str = "./data"
    database_url: str = "sqlite:///./recruit-agent.db"
    database_echo: bool = False
    scheduler_lock_timeout_seconds: int = 300
    approval_source: str = "desktop_app"
    default_platform: str = "site"
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)
    provider_config: dict[str, Any] = Field(default_factory=dict)
    intranet_sync: dict[str, Any] = Field(default_factory=dict)


class AppSettingsRead(AppSettingsBase):
    model_config = ConfigDict(from_attributes=True)


class AppSettingsUpdate(BaseModel):
    app_name: str | None = None
    environment: str | None = None
    host: str | None = None
    port: int | None = None
    data_dir: str | None = None
    database_url: str | None = None
    database_echo: bool | None = None
    scheduler_lock_timeout_seconds: int | None = None
    approval_source: str | None = None
    default_platform: str | None = None
    feature_flags: FeatureFlags | None = None
    provider_config: dict[str, Any] | None = None
    intranet_sync: dict[str, Any] | None = None


class CandidateBase(BaseModel):
    name: str
    platform: str = "site"
    platform_candidate_id: str | None = None
    status: str = "discovered"
    current_workflow_node: str | None = None
    jd_id: str | None = None
    contact_info: dict[str, Any] = Field(default_factory=dict)
    resume_path: str | None = None
    online_resume_text: str | None = None
    ai_scores: dict[str, Any] = Field(default_factory=dict)
    ai_reasoning: str | None = None
    cooldown_until: datetime | None = None
    last_contacted_at: datetime | None = None


class CandidateCreate(CandidateBase):
    pass


class CandidateUpdate(BaseModel):
    name: str | None = None
    platform: str | None = None
    platform_candidate_id: str | None = None
    status: str | None = None
    current_workflow_node: str | None = None
    jd_id: str | None = None
    contact_info: dict[str, Any] | None = None
    resume_path: str | None = None
    online_resume_text: str | None = None
    ai_scores: dict[str, Any] | None = None
    ai_reasoning: str | None = None
    cooldown_until: datetime | None = None
    last_contacted_at: datetime | None = None


class CandidateRead(CandidateBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class WorkflowBase(BaseModel):
    name: str
    jd_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
    version: int = 1


class WorkflowCreate(WorkflowBase):
    pass


class WorkflowUpdate(BaseModel):
    name: str | None = None
    jd_id: str | None = None
    config: dict[str, Any] | None = None
    status: str | None = None
    version: int | None = None


class WorkflowRead(WorkflowBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class TaskSpecBase(BaseModel):
    title: str
    description: str | None = None
    goal: str
    domain: str = "general"
    status: str = "draft"
    source_kind: str = "natural_language"
    source_text: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    approval_policy: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    preferred_capabilities: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)
    compiled_payload: dict[str, Any] = Field(default_factory=dict)
    active_plan_id: str | None = None


class TaskSpecCreate(TaskSpecBase):
    pass


class TaskSpecUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    goal: str | None = None
    domain: str | None = None
    status: str | None = None
    source_kind: str | None = None
    source_text: str | None = None
    inputs: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None
    success_criteria: dict[str, Any] | None = None
    approval_policy: dict[str, Any] | None = None
    output_contract: dict[str, Any] | None = None
    preferred_capabilities: list[str] | None = None
    preferred_domains: list[str] | None = None
    compiled_payload: dict[str, Any] | None = None
    active_plan_id: str | None = None


class TaskSpecRead(TaskSpecBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class DomainPackRead(BaseModel):
    key: str
    name: str
    description: str
    default_capabilities: list[str] = Field(default_factory=list)
    sample_tasks: list[str] = Field(default_factory=list)
    default_constraints: dict[str, Any] = Field(default_factory=dict)
    default_output_contract: dict[str, Any] = Field(default_factory=dict)
    template_keys: list[str] = Field(default_factory=list)


class CapabilityDriverRead(BaseModel):
    key: str
    description: str
    risk: str
    supported_domains: list[str] = Field(default_factory=list)
    recommended_scene_types: list[str] = Field(default_factory=list)
    writes_state: bool = False
    requires_supervision: bool = False
    audit_tags: list[str] = Field(default_factory=list)


class TaskCompileRequest(BaseModel):
    instruction: str = Field(validation_alias=AliasChoices("instruction", "source_text", "prompt"))
    title: str | None = None
    description: str | None = None
    domain_hint: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    approval_policy: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    preferred_capabilities: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)
    auto_plan: bool = True
    requested_by: str = "desktop-user"


class TaskCompileResponse(BaseModel):
    domain_pack: DomainPackRead
    compiler_notes: list[str] = Field(default_factory=list)
    task_spec: TaskSpecRead
    execution_plan: "ExecutionPlanRead | None" = None


class ExecutionPlanBase(BaseModel):
    task_spec_id: str
    name: str
    mode: str = "trial"
    status: str = "draft"
    version: int = 1
    approval_state: str = "unreviewed"
    plan_body: dict[str, Any] = Field(default_factory=dict)
    environment_requirements: dict[str, Any] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    compiled_from_patch_id: str | None = None


class ExecutionPlanCreate(ExecutionPlanBase):
    pass


class ExecutionPlanUpdate(BaseModel):
    task_spec_id: str | None = None
    name: str | None = None
    mode: str | None = None
    status: str | None = None
    version: int | None = None
    approval_state: str | None = None
    plan_body: dict[str, Any] | None = None
    environment_requirements: dict[str, Any] | None = None
    checkpoints: list[dict[str, Any]] | None = None
    runtime_metadata: dict[str, Any] | None = None
    compiled_from_patch_id: str | None = None


class ExecutionPlanRead(ExecutionPlanBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class ExecutionEpisodeBase(BaseModel):
    task_spec_id: str
    execution_plan_id: str
    mode: str = "trial"
    status: str = "pending"
    requested_by: str | None = None
    requires_confirmation: bool = True
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_summary: str | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    divergence_detected: bool = False
    patch_id: str | None = None
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None


class ExecutionEpisodeCreate(ExecutionEpisodeBase):
    pass


class ExecutionEpisodeUpdate(BaseModel):
    task_spec_id: str | None = None
    execution_plan_id: str | None = None
    mode: str | None = None
    status: str | None = None
    requested_by: str | None = None
    requires_confirmation: bool | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_summary: str | None = None
    observations: list[dict[str, Any]] | None = None
    actions: list[dict[str, Any]] | None = None
    metrics: dict[str, Any] | None = None
    divergence_detected: bool | None = None
    patch_id: str | None = None
    runtime_metadata: dict[str, Any] | None = None
    last_error: str | None = None


class ExecutionEpisodeRead(ExecutionEpisodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class TrialRunExecuteRequest(BaseModel):
    operator: str = "desktop-user"
    notes: str | None = None
    source: str = "browser"
    environment_key: str | None = None
    url: str | None = None
    title: str | None = None
    page_type: str | None = None
    observed_entities: list[dict[str, Any]] = Field(default_factory=list)
    affordances: list[dict[str, Any]] = Field(default_factory=list)
    capability_hints: list[str] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    simulate_divergence: bool | None = None


class EpisodeConfirmRequest(BaseModel):
    reviewer: str = Field(default="desktop-user", validation_alias=AliasChoices("reviewer", "reviewed_by"))
    reason: str | None = Field(default=None, validation_alias=AliasChoices("reason", "notes"))
    activate_template: bool = True
    template_name: str | None = None


class WorkflowTemplateBase(BaseModel):
    template_key: str
    name: str
    domain: str = "general"
    status: str = "draft"
    version: int = 1
    source_task_spec_id: str | None = None
    template_body: dict[str, Any] = Field(default_factory=dict)
    activation_strategy: dict[str, Any] = Field(default_factory=dict)
    validation_summary: str | None = None
    last_validated_at: datetime | None = None


class WorkflowTemplateCreate(WorkflowTemplateBase):
    pass


class WorkflowTemplateUpdate(BaseModel):
    template_key: str | None = None
    name: str | None = None
    domain: str | None = None
    status: str | None = None
    version: int | None = None
    source_task_spec_id: str | None = None
    template_body: dict[str, Any] | None = None
    activation_strategy: dict[str, Any] | None = None
    validation_summary: str | None = None
    last_validated_at: datetime | None = None


class WorkflowTemplateRead(WorkflowTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class WorkflowPatchBase(BaseModel):
    title: str
    patch_kind: str = "execution_divergence"
    status: str = "pending_review"
    template_id: str | None = None
    task_spec_id: str | None = None
    execution_plan_id: str | None = None
    execution_episode_id: str | None = None
    proposed_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    applied_at: datetime | None = None
    divergence_summary: str | None = None
    rationale: str | None = Field(default=None, validation_alias=AliasChoices("rationale", "reason"))
    patch_body: dict[str, Any] = Field(default_factory=dict)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def reason(self) -> str | None:
        return self.rationale


class WorkflowPatchCreate(WorkflowPatchBase):
    pass


class WorkflowPatchUpdate(BaseModel):
    title: str | None = None
    patch_kind: str | None = None
    status: str | None = None
    template_id: str | None = None
    task_spec_id: str | None = None
    execution_plan_id: str | None = None
    execution_episode_id: str | None = None
    proposed_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    applied_at: datetime | None = None
    divergence_summary: str | None = None
    rationale: str | None = Field(default=None, validation_alias=AliasChoices("rationale", "reason"))
    patch_body: dict[str, Any] | None = None
    runtime_metadata: dict[str, Any] | None = None

    @property
    def reason(self) -> str | None:
        return self.rationale


class WorkflowPatchRead(WorkflowPatchBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class EnvironmentSnapshotBase(BaseModel):
    task_spec_id: str | None = None
    execution_plan_id: str | None = None
    execution_episode_id: str | None = None
    source: str = "browser"
    environment_key: str | None = None
    status: str = "observed"
    url: str | None = None
    title: str | None = None
    page_type: str | None = None
    capability_hints: list[str] = Field(default_factory=list)
    observed_entities: list[dict[str, Any]] = Field(default_factory=list)
    affordances: list[dict[str, Any]] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class EnvironmentSnapshotCreate(EnvironmentSnapshotBase):
    pass


class EnvironmentSnapshotUpdate(BaseModel):
    task_spec_id: str | None = None
    execution_plan_id: str | None = None
    execution_episode_id: str | None = None
    source: str | None = None
    environment_key: str | None = None
    status: str | None = None
    url: str | None = None
    title: str | None = None
    page_type: str | None = None
    capability_hints: list[str] | None = None
    observed_entities: list[dict[str, Any]] | None = None
    affordances: list[dict[str, Any]] | None = None
    runtime_metadata: dict[str, Any] | None = None


class EnvironmentSnapshotRead(EnvironmentSnapshotBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class EnvironmentSnapshotContextRead(BaseModel):
    persisted: bool = False
    id: str | None = None
    source: str = "browser"
    environment_key: str | None = None
    status: str = "observed"
    url: str | None = None
    title: str | None = None
    page_type: str | None = None
    capability_hints: list[str] = Field(default_factory=list)
    observed_entities: list[dict[str, Any]] = Field(default_factory=list)
    affordances: list[dict[str, Any]] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class EnvironmentAssessmentRequest(BaseModel):
    task_spec_id: str | None = None
    execution_plan_id: str | None = None
    execution_episode_id: str | None = None
    environment_snapshot_id: str | None = None
    snapshot: EnvironmentSnapshotCreate | None = None
    compiler_payload: dict[str, Any] = Field(default_factory=dict)
    plan_context: dict[str, Any] = Field(default_factory=dict)


class EnvironmentAssessmentRead(BaseModel):
    task_spec: TaskSpecRead | None = None
    execution_plan: ExecutionPlanRead | None = None
    execution_episode: ExecutionEpisodeRead | None = None
    snapshot: EnvironmentSnapshotContextRead | None = None
    scene_type: str
    scene_key: str
    confidence: float
    plan_fit: str
    recommended_capabilities: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    environment_requirements: dict[str, Any] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    assessment_notes: list[str] = Field(default_factory=list)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlanReplanRequest(BaseModel):
    name: str | None = None
    reason: str | None = Field(default=None, validation_alias=AliasChoices("reason", "rationale"))
    requested_by: str = "desktop-user"
    execution_episode_id: str | None = None
    environment_snapshot_id: str | None = None
    snapshot: EnvironmentSnapshotCreate | None = None
    compiler_payload: dict[str, Any] = Field(default_factory=dict)
    plan_context: dict[str, Any] = Field(default_factory=dict)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    preserve_active_plan: bool = True


class ExecutionPlanReplanRead(BaseModel):
    previous_plan: ExecutionPlanRead
    execution_plan: ExecutionPlanRead
    assessment: EnvironmentAssessmentRead
    compiler_notes: list[str] = Field(default_factory=list)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)


class SkillBase(BaseModel):
    skill_id: str
    name: str
    version: int = 1
    status: str = "draft"
    bound_to_workflow_node: str | None = None
    platform: str = "site"
    strategy: dict[str, Any] = Field(default_factory=dict)
    execution_hints: dict[str, Any] = Field(default_factory=dict)
    health_check_config: dict[str, Any] = Field(default_factory=dict)
    last_health_check: datetime | None = None
    last_health_status: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


class SkillCreate(SkillBase):
    pass


class SkillUpdate(BaseModel):
    skill_id: str | None = None
    name: str | None = None
    version: int | None = None
    status: str | None = None
    bound_to_workflow_node: str | None = None
    platform: str | None = None
    strategy: dict[str, Any] | None = None
    execution_hints: dict[str, Any] | None = None
    health_check_config: dict[str, Any] | None = None
    last_health_check: datetime | None = None
    last_health_status: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


class SkillRead(SkillBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class SkillHealthCheckRequest(BaseModel):
    observed_result: dict[str, Any] = Field(default_factory=dict)


class SkillHealthCheckRead(BaseModel):
    skill_id: str
    status: str
    health: str
    checked_at: datetime
    issues: list[str] = Field(default_factory=list)


class SkillHealthSweepRequest(BaseModel):
    skill_ids: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=lambda: ["active", "approved"])
    platform: str | None = None
    observed_results_by_skill: dict[str, dict[str, Any]] = Field(default_factory=dict)


class SkillHealthSweepItemRead(SkillHealthCheckRead):
    degraded: bool = False


class SkillHealthSweepRead(BaseModel):
    checked_count: int
    degraded_count: int
    statuses: list[str] = Field(default_factory=list)
    platform: str | None = None
    results: list[SkillHealthSweepItemRead] = Field(default_factory=list)


class LearningDraftBase(BaseModel):
    content: str
    tags: list[str] = Field(default_factory=list)
    source_task_id: str | None = None
    consolidated_at: datetime | None = None
    is_active: bool = True


class LearningDraftCreate(LearningDraftBase):
    pass


class LearningDraftUpdate(BaseModel):
    content: str | None = None
    tags: list[str] | None = None
    source_task_id: str | None = None
    consolidated_at: datetime | None = None
    is_active: bool | None = None


class LearningDraftRead(LearningDraftBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class RuntimeLearningOutcomeRead(BaseModel):
    episode: ExecutionEpisodeRead
    template: "WorkflowTemplateRead | None" = None
    patch: "WorkflowPatchRead | None" = None
    learning_draft: LearningDraftRead | None = None
    approval: "ApprovalRead | None" = None
    skill_health: dict[str, Any] | None = None


class RuntimeReplayEventRead(BaseModel):
    sequence: int
    kind: str
    title: str
    detail: str | None = None
    occurred_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RuntimeReplayDiagnosticsRead(BaseModel):
    domain: str
    status: str
    requires_confirmation: bool
    divergence_detected: bool
    action_count: int
    observation_count: int
    snapshot_count: int
    approval_count: int
    pending_approval_count: int
    completion_rate: float | None = None
    latest_snapshot_page_type: str | None = None
    latest_error: str | None = None


class RuntimeEpisodeReplayRead(BaseModel):
    task_spec: TaskSpecRead
    execution_plan: ExecutionPlanRead
    episode: ExecutionEpisodeRead
    snapshots: list[EnvironmentSnapshotRead] = Field(default_factory=list)
    template: "WorkflowTemplateRead | None" = None
    patch: "WorkflowPatchRead | None" = None
    learning_draft: LearningDraftRead | None = None
    approvals: list["ApprovalRead"] = Field(default_factory=list)
    diagnostics: RuntimeReplayDiagnosticsRead
    timeline: list[RuntimeReplayEventRead] = Field(default_factory=list)


class SyncBacklogRead(BaseModel):
    id: str
    protocol_version: str
    destination: str
    item_type: str
    item_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str
    attempt_count: int = 0
    last_attempted_at: datetime | None = None
    last_error: str | None = None
    synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SyncStatusRead(BaseModel):
    enabled: bool
    remote_available: bool
    protocol_version: str
    source: str
    target: dict[str, Any] = Field(default_factory=dict)
    pending_count: int = 0
    synced_count: int = 0
    failed_delivery_count: int = 0
    backlog_total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    latest_error: str | None = None


class SyncFlushRead(BaseModel):
    attempted: int = 0
    synced: int = 0
    failed: int = 0
    pending: int = 0
    remote_available: bool = False
    target: dict[str, Any] = Field(default_factory=dict)


class ApprovalBase(BaseModel):
    target_type: str
    target_id: str
    title: str
    status: str = "pending"
    requested_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class ApprovalCreate(ApprovalBase):
    pass


class ApprovalUpdate(BaseModel):
    target_type: str | None = None
    target_id: str | None = None
    title: str | None = None
    status: str | None = None
    requested_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    payload: dict[str, Any] | None = None
    notes: str | None = None


class ApprovalRead(ApprovalBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class MetricsSummary(BaseModel):
    candidate_count: int
    workflow_count: int
    skill_count: int
    approval_count: int
    pending_approval_count: int
    active_skill_count: int
    by_status: dict[str, int] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str = "ready"


class ApprovalDecisionRequest(BaseModel):
    reviewer: str = Field(default="desktop-user", validation_alias=AliasChoices("reviewer", "reviewed_by"))
    reason: str | None = Field(default=None, validation_alias=AliasChoices("reason", "notes"))


class WorkflowPatchDecisionRequest(BaseModel):
    reviewer: str = Field(default="desktop-user", validation_alias=AliasChoices("reviewer", "reviewed_by"))
    reason: str | None = Field(default=None, validation_alias=AliasChoices("reason", "notes"))
    apply_immediately: bool = False


class ProviderConfigRead(BaseModel):
    kind: str
    name: str
    model: str
    enabled: bool
    temperature: float = 0.2
    baseUrl: str | None = None


class ProviderConfigUpdate(BaseModel):
    kind: str
    name: str
    model: str
    enabled: bool
    temperature: float = 0.2
    baseUrl: str | None = None


class IntranetSyncConfigRead(BaseModel):
    enabled: bool
    baseUrl: str | None = None
    apiPath: str
    timeoutSeconds: int


class IntranetSyncConfigUpdate(BaseModel):
    enabled: bool | None = None
    baseUrl: str | None = None
    apiPath: str | None = None
    timeoutSeconds: int | None = None


class PlatformSettingsRead(BaseModel):
    name: str
    account: str
    cooldownDays: int
    allowOutboundMessaging: bool


class PlatformSettingsUpdate(BaseModel):
    name: str | None = None
    account: str | None = None
    cooldownDays: int | None = None
    allowOutboundMessaging: bool | None = None


class SettingsSnapshotRead(BaseModel):
    locale: str
    timezone: str
    intranetEnabled: bool
    desktopApprovalsOnly: bool
    providers: list[ProviderConfigRead]
    intranetSync: IntranetSyncConfigRead
    platform: PlatformSettingsRead
    approval_source: str | None = None
    feature_flags: FeatureFlags | None = None
    provider_config: dict[str, Any] = Field(default_factory=dict)


class SettingsSnapshotUpdate(BaseModel):
    locale: str | None = None
    timezone: str | None = None
    intranetEnabled: bool | None = None
    desktopApprovalsOnly: bool | None = None
    approval_source: str | None = None
    feature_flags: FeatureFlags | None = None
    provider_config: dict[str, Any] | None = None
    providers: list[ProviderConfigUpdate] | None = None
    intranetSync: IntranetSyncConfigUpdate | None = None
    platform: PlatformSettingsUpdate | None = None


class MetricCardRead(BaseModel):
    label: str
    value: str
    delta: str
    tone: str
    caption: str


class PipelineStageRead(BaseModel):
    label: str
    value: int
    target: int | None = None


class TimelineEventRead(BaseModel):
    id: str
    label: str
    detail: str
    at: str
    tone: str


class CandidateDashboardRead(BaseModel):
    id: str
    name: str
    title: str
    platform: str
    location: str
    status: str
    workflowNode: str
    jdTitle: str
    matchScore: int
    experienceYears: int
    nextAction: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    resumeAvailable: bool
    cooldownUntil: str | None = None
    lastContactedAt: str | None = None


class WorkflowNodeSummaryRead(BaseModel):
    id: str
    name: str
    kind: str
    status: str
    owner: str
    description: str


class WorkflowDashboardRead(BaseModel):
    id: str
    name: str
    jdTitle: str
    status: str
    version: str
    updatedAt: str
    nodes: list[WorkflowNodeSummaryRead]


class SkillDashboardRead(BaseModel):
    id: str
    name: str
    version: str
    status: str
    boundNode: str
    platform: str
    health: str
    lastCheckedAt: str
    summary: str


class ApprovalDashboardRead(BaseModel):
    id: str
    kind: str
    title: str
    detail: str
    requester: str
    status: str
    createdAt: str


class AgentStatusRead(BaseModel):
    status: str
    active_task: str = Field(serialization_alias="activeTask")
    browser_lock: str = Field(serialization_alias="browserLock")
    uptime: str
    queue_depth: int = Field(serialization_alias="queueDepth")
    token_budget_used: int = Field(serialization_alias="tokenBudgetUsed")
    health: str

    model_config = ConfigDict(populate_by_name=True)


class DashboardRead(BaseModel):
    metrics: list[MetricCardRead]
    pipeline: list[PipelineStageRead]
    timeline: list[TimelineEventRead]
    alerts: list[TimelineEventRead]
    candidates: list[CandidateDashboardRead]
    workflows: list[WorkflowDashboardRead]
    skills: list[SkillDashboardRead]
    approvals: list[ApprovalDashboardRead]
    agent: AgentStatusRead
    settings: SettingsSnapshotRead


class AgentTaskCreate(BaseModel):
    task_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    candidate_id: str | None = None
    workflow_id: str | None = None
    workflow_node_id: str | None = None


class AgentTaskEnqueueRead(BaseModel):
    task_id: str
    task_type: str
    priority: int
    queue_depth: int


class AgentRunRead(BaseModel):
    processed: bool
    status: str
    task_id: str | None = None
    enqueued_follow_ups: int = 0
    error: str | None = None


class TrialRunRequest(BaseModel):
    task_spec_id: str
    execution_plan_id: str
    requested_by: str = "desktop-user"
    notes: str | None = None
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
