from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field, field_validator

class FeatureFlags(BaseModel):
    enable_autonomy: bool = False
    enable_skill_health_autonomy: bool = False
    enable_system_commands: bool = False
    enable_intranet_sync: bool = False
    enable_outbound_messaging: bool = False


class AppSettingsBase(BaseModel):
    app_name: str = "Recruit Agent"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8741
    data_dir: str = "./data"
    database_url: str = "sqlite:///./recruit-agent.db"
    database_echo: bool = False
    scheduler_lock_timeout_seconds: int = 300
    skill_health_autonomy_interval_seconds: int = 300
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
    skill_health_autonomy_interval_seconds: int | None = None
    approval_source: str | None = None
    default_platform: str | None = None
    feature_flags: FeatureFlags | None = None
    provider_config: dict[str, Any] | None = None
    intranet_sync: dict[str, Any] | None = None


class CandidatePersonBase(BaseModel):
    name: str
    platform: str = "site"
    platform_candidate_id: str | None = None
    contact_info: dict[str, Any] = Field(default_factory=dict)
    resume_path: str | None = None
    online_resume_text: str | None = None


class CandidatePersonCreate(CandidatePersonBase):
    pass


class CandidatePersonUpdate(BaseModel):
    name: str | None = None
    platform: str | None = None
    platform_candidate_id: str | None = None
    contact_info: dict[str, Any] | None = None
    resume_path: str | None = None
    online_resume_text: str | None = None


class CandidatePersonRead(CandidatePersonBase):
    model_config = ConfigDict(from_attributes=True)

    candidate_person_id: str = Field(
        validation_alias=AliasChoices(
            "candidate_person_id",
            "candidatePersonId",
            "person_id",
            "personId",
        ),
        alias="personId",
        serialization_alias="personId",
    )
    created_at: int = Field(serialization_alias="createdAt")
    updated_at: int = Field(serialization_alias="updatedAt")


class CandidateBase(CandidatePersonBase):
    pass


class CandidateCreate(CandidatePersonCreate):
    pass


class CandidateUpdate(CandidatePersonUpdate):
    pass


class CandidateRead(CandidatePersonRead):
    pass


class JobDescriptionBase(BaseModel):
    title: str
    company_name: str | None = None
    department: str | None = None
    location: str | None = None
    employment_type: str | None = None
    headcount: int | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    compensation_text: str | None = None
    experience_requirement: str | None = None
    education_requirement: str | None = None
    summary: str | None = None
    description: str | None = None
    requirements: str | None = None
    benefit_tags: list[str] = Field(default_factory=list)
    detail_metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"
    source: str = "manual"


class JobDescriptionCreate(JobDescriptionBase):
    pass


class JobDescriptionUpdate(BaseModel):
    title: str | None = None
    company_name: str | None = None
    department: str | None = None
    location: str | None = None
    employment_type: str | None = None
    headcount: int | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    compensation_text: str | None = None
    experience_requirement: str | None = None
    education_requirement: str | None = None
    summary: str | None = None
    description: str | None = None
    requirements: str | None = None
    benefit_tags: list[str] | None = None
    detail_metadata: dict[str, Any] | None = None
    status: str | None = None
    source: str | None = None


class JobDescriptionRead(JobDescriptionBase):
    model_config = ConfigDict(from_attributes=True)

    job_description_id: str = Field(
        validation_alias=AliasChoices("job_description_id", "jobDescriptionId"),
        serialization_alias="jobDescriptionId",
    )
    created_at: int = Field(serialization_alias="createdAt")
    updated_at: int = Field(serialization_alias="updatedAt")


class JobDescriptionPageRead(BaseModel):
    items: list[JobDescriptionRead]
    total: int
    limit: int
    offset: int
    has_next: bool = Field(serialization_alias="hasNext")


class JobDescriptionFunnelStepRead(BaseModel):
    key: str
    label: str
    value: int
    percent: float


class JobDescriptionFunnelStatsRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_description_id: str = Field(serialization_alias="jobDescriptionId")
    steps: list[JobDescriptionFunnelStepRead]
    applications: int
    communicating: int
    interviewing: int
    offers: int
    hired: int
    with_contact: int = Field(serialization_alias="withContact")
    with_resume: int = Field(serialization_alias="withResume")
    with_ai_score: int = Field(serialization_alias="withAiScore")
    by_status: dict[str, int] = Field(default_factory=dict, serialization_alias="byStatus")


class CommunicationTemplateRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    template_id: str = Field(serialization_alias="templateId")
    name: str
    category: str
    message_type: str = Field(serialization_alias="messageType")
    body: str
    variables: list[str] = Field(default_factory=list)
    status: str


class CommunicationTemplateRenderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    application_id: str = Field(
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    variables: dict[str, Any] = Field(default_factory=dict)


class CommunicationTemplateRenderRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    template_id: str = Field(serialization_alias="templateId")
    name: str
    category: str
    message_type: str = Field(serialization_alias="messageType")
    content: str
    missing_variables: list[str] = Field(default_factory=list, serialization_alias="missingVariables")


class CandidateApplicationBase(BaseModel):
    person_id: str = Field(validation_alias=AliasChoices("person_id", "personId", "candidate_person_id", "candidatePersonId"))
    job_description_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("job_description_id", "jobDescriptionId"),
    )
    platform: str = "site"
    platform_application_id: str | None = None
    current_status: str = "discovered"
    current_stage_key: str | None = None
    deepest_milestone: str | None = None
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    ai_scores: dict[str, Any] = Field(default_factory=dict)
    ai_reasoning: str | None = None
    cooldown_until: datetime | None = None
    last_contacted_at: datetime | None = None
    application_metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateApplicationCreate(CandidateApplicationBase):
    application_window: str | None = None


class CandidateApplicationUpdate(BaseModel):
    job_description_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("job_description_id", "jobDescriptionId"),
    )
    platform: str | None = None
    platform_application_id: str | None = None
    current_status: str | None = None
    current_stage_key: str | None = None
    deepest_milestone: str | None = None
    state_snapshot: dict[str, Any] | None = None
    ai_scores: dict[str, Any] | None = None
    ai_reasoning: str | None = None
    cooldown_until: datetime | None = None
    last_contacted_at: datetime | None = None
    application_metadata: dict[str, Any] | None = None


class CandidateApplicationRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    candidate_application_id: str = Field(
        validation_alias=AliasChoices(
            "candidate_application_id",
            "candidateApplicationId",
            "application_id",
            "applicationId",
        ),
        serialization_alias="applicationId",
    )
    candidate_person_id: str = Field(
        validation_alias=AliasChoices(
            "candidate_person_id",
            "candidatePersonId",
            "person_id",
            "personId",
        ),
        serialization_alias="personId",
    )
    job_description_id: str | None = Field(
        default=None,
        serialization_alias="jobDescriptionId",
    )
    source_platform: str = Field(
        default="site",
        serialization_alias="sourcePlatform",
    )
    source_platform_candidate_person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "source_platform_candidate_person_id",
            "sourcePlatformCandidatePersonId",
            "source_platform_person_id",
            "sourcePlatformPersonId",
        ),
        serialization_alias="sourcePlatformPersonId",
    )
    application_window: str = Field(serialization_alias="applicationWindow")
    current_status: str = Field(serialization_alias="currentStatus")
    current_stage_key: str | None = Field(default=None, serialization_alias="currentStageKey")
    deepest_milestone: str | None = Field(default=None, serialization_alias="deepestMilestone")
    state_snapshot: dict[str, Any] = Field(default_factory=dict, serialization_alias="stateSnapshot")
    ai_scores: dict[str, Any] = Field(default_factory=dict, serialization_alias="aiScores")
    ai_reasoning: str | None = Field(default=None, serialization_alias="aiReasoning")
    cooldown_until: int | None = Field(default=None, serialization_alias="cooldownUntil")
    last_contacted_at: int | None = Field(default=None, serialization_alias="lastContactedAt")
    application_metadata: dict[str, Any] = Field(default_factory=dict, serialization_alias="applicationMetadata")
    person_name: str | None = Field(default=None, serialization_alias="personName")
    contact_info: dict[str, Any] = Field(default_factory=dict, serialization_alias="contactInfo")
    resume_path: str | None = Field(default=None, serialization_alias="resumePath")
    online_resume_text: str | None = Field(default=None, serialization_alias="onlineResumeText")
    contact_snapshot: dict[str, Any] = Field(default_factory=dict, serialization_alias="contactSnapshot")
    resume_snapshot: dict[str, Any] = Field(default_factory=dict, serialization_alias="resumeSnapshot")
    resume_available: bool = Field(default=False, serialization_alias="resumeAvailable")
    created_at: int = Field(serialization_alias="createdAt")
    updated_at: int = Field(serialization_alias="updatedAt")


class ApplicationPersonSummaryRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("person_id", "personId", "candidate_person_id", "candidatePersonId"),
        serialization_alias="personId",
    )
    platform_candidate_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("platform_candidate_id", "platformCandidateId"),
        serialization_alias="platformCandidateId",
    )
    name: str = ""
    title: str = "候选人"
    location: str = "未知"
    experience_years: int = Field(default=0, serialization_alias="experienceYears")
    tags: list[str] = Field(default_factory=list)
    contact_info: dict[str, Any] = Field(default_factory=dict, serialization_alias="contactInfo")
    resume_path: str | None = Field(default=None, serialization_alias="resumePath")
    online_resume_text: str | None = Field(default=None, serialization_alias="onlineResumeText")


class JobDescriptionSummaryRead(JobDescriptionBase):
    model_config = ConfigDict(populate_by_name=True)

    job_description_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("job_description_id", "jobDescriptionId"),
        serialization_alias="jobDescriptionId",
    )


class ApplicationSubjectRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    application_id: str = Field(
        validation_alias=AliasChoices("application_id", "applicationId", "candidate_application_id", "candidateApplicationId"),
        serialization_alias="applicationId",
    )
    person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("person_id", "personId", "candidate_person_id", "candidatePersonId"),
        serialization_alias="personId",
    )
    job_description_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("job_description_id", "jobDescriptionId"),
        serialization_alias="jobDescriptionId",
    )
    platform: str = "site"
    source_platform_candidate_person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "source_platform_candidate_person_id",
            "sourcePlatformCandidatePersonId",
            "source_platform_person_id",
            "sourcePlatformPersonId",
        ),
        serialization_alias="sourcePlatformPersonId",
    )
    current_status: str = Field(default="discovered", serialization_alias="currentStatus")
    stage_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("stage_key", "stageKey", "current_stage_key", "currentStageKey"),
        serialization_alias="stageKey",
    )
    deepest_milestone: str | None = Field(default=None, serialization_alias="deepestMilestone")
    match_score: int = Field(default=0, serialization_alias="matchScore")
    next_action: str = Field(default="查看申请并决定下一步动作。", serialization_alias="nextAction")
    summary: str = "申请档案正在等待审查。"
    resume_available: bool = Field(default=False, serialization_alias="resumeAvailable")
    state_snapshot: dict[str, Any] = Field(default_factory=dict, serialization_alias="stateSnapshot")
    ai_scores: dict[str, Any] = Field(default_factory=dict, serialization_alias="aiScores")
    ai_reasoning: str | None = Field(default=None, serialization_alias="aiReasoning")
    application_metadata: dict[str, Any] = Field(default_factory=dict, serialization_alias="applicationMetadata")
    contact_snapshot: dict[str, Any] = Field(default_factory=dict, serialization_alias="contactSnapshot")
    resume_snapshot: dict[str, Any] = Field(default_factory=dict, serialization_alias="resumeSnapshot")
    person: ApplicationPersonSummaryRead | None = None
    job_description: JobDescriptionSummaryRead | None = Field(
        default=None,
        validation_alias=AliasChoices("job_description", "jobDescription"),
        serialization_alias="jobDescription",
    )
    cooldown_until: int | None = Field(default=None, serialization_alias="cooldownUntil")
    last_contacted_at: int | None = Field(default=None, serialization_alias="lastContactedAt")
    created_at: int | None = Field(default=None, serialization_alias="createdAt")
    updated_at: int | None = Field(default=None, serialization_alias="updatedAt")


class AgentDefinitionBase(BaseModel):
    definition_key: str = Field(
        validation_alias=AliasChoices("definition_key", "definitionKey"),
        serialization_alias="definitionKey",
    )
    name: str
    status: str = "draft"
    description: str | None = None
    is_primary: bool = False
    role_definition: dict[str, Any] = Field(default_factory=dict)
    prompt_config: dict[str, Any] = Field(default_factory=dict)
    playbook_blueprint: dict[str, Any] = Field(default_factory=dict)
    memory_policy: dict[str, Any] = Field(default_factory=dict)
    dashboard_config: dict[str, Any] = Field(default_factory=dict)
    channel_config: dict[str, Any] = Field(default_factory=dict)
    product_bindings: dict[str, Any] = Field(default_factory=dict)
    product_config: dict[str, Any] = Field(default_factory=dict)
    product_projections: dict[str, Any] = Field(default_factory=dict)
    agent_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentDefinitionCreate(AgentDefinitionBase):
    pass


class AgentDefinitionUpdate(BaseModel):
    definition_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("definition_key", "definitionKey"),
        serialization_alias="definitionKey",
    )
    name: str | None = None
    status: str | None = None
    description: str | None = None
    is_primary: bool | None = None
    role_definition: dict[str, Any] | None = None
    prompt_config: dict[str, Any] | None = None
    playbook_blueprint: dict[str, Any] | None = None
    memory_policy: dict[str, Any] | None = None
    dashboard_config: dict[str, Any] | None = None
    channel_config: dict[str, Any] | None = None
    product_bindings: dict[str, Any] | None = None
    product_config: dict[str, Any] | None = None
    product_projections: dict[str, Any] | None = None
    agent_metadata: dict[str, Any] | None = None


class AgentDefinitionRead(AgentDefinitionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: int
    updated_at: int

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _timestamp_to_int(cls, value: Any) -> int:
        if isinstance(value, datetime):
            return int(value.timestamp())
        return int(value or 0)


class CandidateConversationEntryBase(BaseModel):
    direction: str
    content: str
    message_type: str = "text"
    platform: str = "site"
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime | None = None


class CandidateConversationEntryCreate(CandidateConversationEntryBase):
    model_config = ConfigDict(populate_by_name=True)


class CandidateConversationEntryRead(CandidateConversationEntryBase):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    timestamp: int | None = None
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )


class CandidateStateSnapshotRead(BaseModel):
    current_phase_key: str | None = None
    current_phase_label: str | None = None
    current_stage_key: str | None = None
    current_stage_label: str | None = None
    contact_status: str | None = None
    contact_channels: list[str] = Field(default_factory=list)
    contact_acquired: bool = False
    resume_status: str | None = None
    ai_assessment_status: str | None = None
    human_assessment_status: str | None = None
    operator_flags: list[str] = Field(default_factory=list)
    next_recommended_stages: list[str] = Field(default_factory=list)
    interview_plan: dict[str, Any] = Field(default_factory=dict)
    latest_note: str | None = None
    latest_transition_at: int | None = None
    latest_transition_source: str | None = None
    snapshot_metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateStateTransitionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    to_status: str = Field(validation_alias=AliasChoices("to_status", "toStatus"))
    phase_key: str | None = Field(default=None, validation_alias=AliasChoices("phase_key", "phaseKey"))
    phase_label: str | None = Field(default=None, validation_alias=AliasChoices("phase_label", "phaseLabel"))
    stage_key: str | None = Field(default=None, validation_alias=AliasChoices("stage_key", "stageKey"))
    stage_label: str | None = Field(default=None, validation_alias=AliasChoices("stage_label", "stageLabel"))
    note: str | None = None
    source: str = "operator"
    actor: str | None = "desktop-user"
    actor_id: str | None = Field(default=None, validation_alias=AliasChoices("actor_id", "actorId"))
    trigger: str | None = None
    override_reason: str | None = Field(default=None, validation_alias=AliasChoices("override_reason", "overrideReason"))
    metadata: dict[str, Any] = Field(default_factory=dict)
    interview_round: int | None = Field(default=None, validation_alias=AliasChoices("interview_round", "interviewRound"))
    contact_channels: list[str] | None = Field(default=None, validation_alias=AliasChoices("contact_channels", "contactChannels"))


class CandidateStatusTransitionBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    person_id: str | None = Field(default=None, exclude=True)
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    from_status: str
    to_status: str
    from_status_label: str
    to_status_label: str
    actor: Literal["agent", "agent_override", "system", "recruiter", "recruiter_override"]
    actor_id: str | None = None
    trigger: str
    note: str | None = None
    override_reason: str | None = None
    is_override: bool = False
    milestone_updated: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("transition_metadata", "metadata"))


class CandidateStatusTransitionCreate(CandidateStatusTransitionBase):
    pass


class CandidateStatusTransitionRead(CandidateStatusTransitionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: int
    updated_at: int


class CandidateAssessmentBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    person_id: str | None = Field(default=None, exclude=True)
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    assessment_type: str = "ai"
    stage_key: str | None = Field(default=None, serialization_alias="stageKey")
    status: str = "completed"
    decision: str | None = None
    score: int | None = None
    summary: str | None = None
    evidence_refs: list[Any] = Field(default_factory=list, serialization_alias="evidenceRefs")
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("assessment_metadata", "metadata"))
    created_by: str | None = Field(default=None, serialization_alias="createdBy")
    reviewed_by: str | None = Field(default=None, serialization_alias="reviewedBy")
    reviewed_at: datetime | None = Field(default=None, serialization_alias="reviewedAt")


class CandidateAssessmentCreate(CandidateAssessmentBase):
    pass


class CandidateAssessmentRead(CandidateAssessmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reviewed_at: int | None = Field(default=None, serialization_alias="reviewedAt")
    created_at: int
    updated_at: int


class CandidateAssignmentBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    person_id: str | None = Field(default=None, exclude=True)
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    assignee: str
    owner_role: str = "operator"
    status: str = "active"
    note: str | None = None
    assignment_metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("assignment_metadata", "metadata"),
        serialization_alias="assignmentMetadata",
    )
    assigned_at: datetime | None = Field(default=None, serialization_alias="assignedAt")
    released_at: datetime | None = Field(default=None, serialization_alias="releasedAt")


class CandidateAssignmentCreate(CandidateAssignmentBase):
    pass


class CandidateAssignmentRead(CandidateAssignmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    assigned_at: int | None = Field(default=None, serialization_alias="assignedAt")
    released_at: int | None = Field(default=None, serialization_alias="releasedAt")
    created_at: int
    updated_at: int


class ResumeArtifactBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    person_id: str | None = Field(default=None, exclude=True)
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    source: str = "site"
    artifact_type: str = "resume"
    file_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("file_name", "fileName"),
        serialization_alias="fileName",
    )
    file_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("file_path", "filePath"),
        serialization_alias="filePath",
    )
    extracted_text: str | None = Field(
        default=None,
        validation_alias=AliasChoices("extracted_text", "extractedText"),
        serialization_alias="extractedText",
    )
    contact_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("contact_snapshot", "contactSnapshot"),
        serialization_alias="contactSnapshot",
    )
    artifact_metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("artifact_metadata", "metadata"),
        serialization_alias="artifactMetadata",
    )
    captured_at: datetime | None = Field(default=None, serialization_alias="capturedAt")


class ResumeArtifactCreate(ResumeArtifactBase):
    pass


class ResumeArtifactRead(ResumeArtifactBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    captured_at: int | None = Field(default=None, serialization_alias="capturedAt")
    created_at: int
    updated_at: int


class CandidateScorecardBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    person_id: str | None = Field(default=None, exclude=True)
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    stage_key: str | None = Field(default=None, serialization_alias="stageKey")
    source: str = "ai"
    rubric_version: str = Field(default="recruit-scorecard-v1", serialization_alias="rubricVersion")
    score_total: int | None = Field(default=None, serialization_alias="scoreTotal")
    verdict: str | None = None
    summary: str | None = None
    dimension_scores: dict[str, Any] = Field(default_factory=dict, serialization_alias="dimensionScores")
    evidence_refs: list[Any] = Field(default_factory=list, serialization_alias="evidenceRefs")
    scorecard_metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("scorecard_metadata", "metadata"),
        serialization_alias="scorecardMetadata",
    )


class CandidateScorecardCreate(CandidateScorecardBase):
    pass


class CandidateScorecardRead(CandidateScorecardBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: int
    updated_at: int


class CandidateReviewDecisionBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    person_id: str | None = Field(default=None, exclude=True)
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    stage_key: str | None = Field(default=None, serialization_alias="stageKey")
    decision: str
    rationale: str | None = None
    decision_source: str = Field(default="manual", serialization_alias="decisionSource")
    decided_by: str | None = Field(default=None, serialization_alias="decidedBy")
    scorecard_id: str | None = Field(default=None, serialization_alias="scorecardId")
    review_metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("review_metadata", "metadata"),
        serialization_alias="reviewMetadata",
    )
    decided_at: datetime | None = Field(default=None, serialization_alias="decidedAt")


class CandidateReviewDecisionCreate(CandidateReviewDecisionBase):
    pass


class CandidateReviewDecisionRead(CandidateReviewDecisionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    decided_at: int | None = Field(default=None, serialization_alias="decidedAt")
    created_at: int
    updated_at: int


class TalentPoolSyncRecordBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    person_id: str | None = Field(default=None, exclude=True)
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    destination: str = "talent_pool"
    status: str = "pending"
    external_ref: str | None = Field(default=None, serialization_alias="externalRef")
    payload_snapshot: dict[str, Any] = Field(default_factory=dict, serialization_alias="payloadSnapshot")
    error_message: str | None = Field(default=None, serialization_alias="errorMessage")
    synced_at: datetime | None = Field(default=None, serialization_alias="syncedAt")
    last_attempted_at: datetime | None = Field(default=None, serialization_alias="lastAttemptedAt")
    sync_metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("sync_metadata", "metadata"),
        serialization_alias="syncMetadata",
    )


class TalentPoolSyncRecordCreate(TalentPoolSyncRecordBase):
    pass


class TalentPoolSyncRecordRead(TalentPoolSyncRecordBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    synced_at: int | None = Field(default=None, serialization_alias="syncedAt")
    last_attempted_at: int | None = Field(default=None, serialization_alias="lastAttemptedAt")
    created_at: int
    updated_at: int


class EvolutionArtifactBase(BaseModel):
    agent_definition_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("agent_definition_id", "agentDefinitionId"),
        serialization_alias="agentDefinitionId",
    )
    artifact_kind: Literal["skill_draft", "prompt_patch", "memory_policy_patch", "playbook_patch", "playbook_patch"]
    title: str
    summary: str | None = None
    status: Literal["draft", "pending_review", "approved", "applied", "rejected", "archived"] = "pending_review"
    related_candidate_id: str | None = None
    related_skill_id: str | None = None
    proposed_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    applied_at: datetime | None = None
    artifact_body: dict[str, Any] = Field(default_factory=dict)
    artifact_metadata: dict[str, Any] = Field(default_factory=dict)


class EvolutionArtifactCreate(EvolutionArtifactBase):
    pass


class EvolutionArtifactUpdate(BaseModel):
    summary: str | None = None
    status: Literal["draft", "pending_review", "approved", "applied", "rejected", "archived"] | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    applied_at: datetime | None = None
    artifact_body: dict[str, Any] | None = None
    artifact_metadata: dict[str, Any] | None = None


class EvolutionArtifactRead(EvolutionArtifactBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reviewed_at: int | None = None
    applied_at: int | None = None
    created_at: int
    updated_at: int


class CandidateThreadRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("person_id", "personId"),
        serialization_alias="personId",
    )
    job_description_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("job_description_id", "jobDescriptionId"),
        serialization_alias="jobDescriptionId",
    )
    application: ApplicationSubjectRead = Field(
        validation_alias=AliasChoices("application", "candidate"),
    )
    session_status: str = Field(default="active", serialization_alias="sessionStatus")
    context_summary: str | None = Field(default=None, serialization_alias="contextSummary")
    facts: dict[str, Any] = Field(default_factory=dict)
    recent_messages: list[dict[str, Any]] = Field(default_factory=list, serialization_alias="recentMessages")
    communication_logs: list[CandidateConversationEntryRead] = Field(
        default_factory=list,
        serialization_alias="communicationLogs",
    )
    state_snapshot: CandidateStateSnapshotRead = Field(
        default_factory=CandidateStateSnapshotRead,
        serialization_alias="stateSnapshot",
    )
    status_transitions: list[CandidateStatusTransitionRead] = Field(
        default_factory=list,
        serialization_alias="statusTransitions",
    )
    assessments: list[CandidateAssessmentRead] = Field(default_factory=list)
    assignments: list[CandidateAssignmentRead] = Field(default_factory=list)
    resume_artifacts: list[ResumeArtifactRead] = Field(default_factory=list, serialization_alias="resumeArtifacts")
    scorecards: list[CandidateScorecardRead] = Field(default_factory=list)
    review_decisions: list[CandidateReviewDecisionRead] = Field(
        default_factory=list,
        serialization_alias="reviewDecisions",
    )
    sync_records: list[TalentPoolSyncRecordRead] = Field(default_factory=list, serialization_alias="syncRecords")
    available_statuses: list[str] = Field(default_factory=list, serialization_alias="availableStatuses")
    available_transitions: list[dict[str, Any]] = Field(default_factory=list, serialization_alias="availableTransitions")
    runtime_approvals: list["ApprovalRead"] = Field(default_factory=list, serialization_alias="runtimeApprovals")
    runtime_interactions: list["OperatorInteractionRead"] = Field(
        default_factory=list,
        serialization_alias="runtimeInteractions",
    )


class RecruitmentStateMachineBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    updated_by: str = Field(validation_alias=AliasChoices("updated_by", "updatedBy"))
    change_summary: str | None = Field(default=None, validation_alias=AliasChoices("change_summary", "changeSummary"))
    nodes: list[dict[str, Any]]
    transitions: list[dict[str, Any]]
    global_transitions: list[dict[str, Any]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("global_transitions", "globalTransitions"),
    )
    version_metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("version_metadata", "versionMetadata"),
    )


class RecruitmentStateMachineUpdate(RecruitmentStateMachineBase):
    pass


class RecruitmentStateMachineRead(RecruitmentStateMachineBase):
    version: int
    published_at: int = Field(validation_alias=AliasChoices("published_at", "publishedAt"))
    created_at: int = Field(validation_alias=AliasChoices("created_at", "createdAt"))
    updated_at: int = Field(validation_alias=AliasChoices("updated_at", "updatedAt"))


class StateCriteriaOptimizationMetricsRead(BaseModel):
    sample_size: int = Field(validation_alias=AliasChoices("sample_size", "sampleSize"))
    ai_decision_count: int = Field(validation_alias=AliasChoices("ai_decision_count", "aiDecisionCount"))
    recruiter_override_count: int = Field(
        validation_alias=AliasChoices("recruiter_override_count", "recruiterOverrideCount"),
    )
    accuracy_rate: float | None = Field(default=None, validation_alias=AliasChoices("accuracy_rate", "accuracyRate"))
    override_rate: float | None = Field(default=None, validation_alias=AliasChoices("override_rate", "overrideRate"))
    deeper_override_count: int = Field(
        validation_alias=AliasChoices("deeper_override_count", "deeperOverrideCount"),
    )
    shallower_override_count: int = Field(
        validation_alias=AliasChoices("shallower_override_count", "shallowerOverrideCount"),
    )


class StateCriteriaOptimizationSuggestionRead(BaseModel):
    kind: Literal["adjust_threshold", "switch_skill"]
    summary: str
    rationale: str
    confidence: Literal["low", "medium", "high"] = "medium"
    proposed_criteria_ref: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("proposed_criteria_ref", "proposedCriteriaRef"),
    )
    suggested_skill_id: str | None = Field(default=None, validation_alias=AliasChoices("suggested_skill_id", "suggestedSkillId"))
    suggested_skill_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("suggested_skill_name", "suggestedSkillName"),
    )


class StateCriteriaOptimizationReportRead(BaseModel):
    node_id: str = Field(validation_alias=AliasChoices("node_id", "nodeId"))
    node_label: str = Field(validation_alias=AliasChoices("node_label", "nodeLabel"))
    current_criteria_ref: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("current_criteria_ref", "currentCriteriaRef"),
    )
    current_skill_id: str | None = Field(default=None, validation_alias=AliasChoices("current_skill_id", "currentSkillId"))
    current_skill_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("current_skill_name", "currentSkillName"),
    )
    metrics: StateCriteriaOptimizationMetricsRead
    suggestions: list[StateCriteriaOptimizationSuggestionRead] = Field(default_factory=list)
    summary: str


class PlaybookBase(BaseModel):
    name: str
    description: str | None = None
    scope_kind: str = "global"
    scope_ref: str | None = None
    blueprint: dict[str, Any] = Field(default_factory=dict)
    strategy_defaults: dict[str, Any] = Field(default_factory=dict)
    context_overrides: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
    version: int = 1
    playbook_metadata: dict[str, Any] = Field(default_factory=dict)


class PlaybookCreate(PlaybookBase):
    pass


class PlaybookUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    scope_kind: str | None = None
    scope_ref: str | None = None
    blueprint: dict[str, Any] | None = None
    strategy_defaults: dict[str, Any] | None = None
    context_overrides: dict[str, Any] | None = None
    status: str | None = None
    version: int | None = None
    playbook_metadata: dict[str, Any] | None = None


class PlaybookRead(PlaybookBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: int
    updated_at: int


class TaskSpecBase(BaseModel):
    title: str
    description: str | None = None
    instruction: str
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
    instruction: str | None = None
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
    created_at: int
    updated_at: int


class DomainPackRead(BaseModel):
    key: str
    name: str
    description: str
    version: str = "1.0.0"
    maturity: str = "experimental"
    runtime_only: bool = True
    default_capabilities: list[str] = Field(default_factory=list)
    sample_tasks: list[str] = Field(default_factory=list)
    default_constraints: dict[str, Any] = Field(default_factory=dict)
    default_output_contract: dict[str, Any] = Field(default_factory=dict)
    template_keys: list[str] = Field(default_factory=list)
    compiler_hints: list[str] = Field(default_factory=list)
    quality_gates: dict[str, Any] = Field(default_factory=dict)
    scene_expectations: list[str] = Field(default_factory=list)
    trial_expectations: dict[str, Any] = Field(default_factory=dict)
    template_count: int = 0
    active_template_count: int = 0


class TaskCompilerContractRead(BaseModel):
    contract_version: str = "runtime-task-compiler-v3"
    strategy: str
    fallback_strategy: str
    prompt_asset: str
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    quality_gates: list[str] = Field(default_factory=list)
    repair_policy: dict[str, Any] = Field(default_factory=dict)
    available_domains: list[DomainPackRead] = Field(default_factory=list)
    available_capabilities: list["CapabilityDriverRead"] = Field(default_factory=list)


class CapabilityDriverRead(BaseModel):
    key: str
    description: str
    risk: str
    supported_domains: list[str] = Field(default_factory=list)
    recommended_scene_types: list[str] = Field(default_factory=list)
    signal_labels: list[str] = Field(default_factory=list)
    executor_mode: str = "tool_loop"
    replan_on_error: bool = False
    scene_required: bool = False
    preferred_tools: list[str] = Field(default_factory=list)
    checkpoint_policy: dict[str, Any] = Field(default_factory=dict)
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
    created_at: int
    updated_at: int


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
    execution_contract: dict[str, Any] = Field(default_factory=dict)
    execution_kind: str = "generic_environment_execution"
    summary_scope: str = "business_summary_only"
    evidence_scope: str = "episode_scoped"
    memory_policy: str = "disabled"
    learning_policy: str = "disabled"
    started_at: int | None = None
    finished_at: int | None = None
    created_at: int
    updated_at: int


class TrialRunExecuteRequest(BaseModel):
    operator: str = "desktop-user"
    notes: str | None = None
    source: str = "browser"
    environment_key: str | None = None
    resource_locator: str | None = None
    display_label: str | None = None
    environment_kind: str | None = None
    observed_entities: list[dict[str, Any]] = Field(default_factory=list)
    action_hints: list[dict[str, Any]] = Field(default_factory=list)
    capability_hints: list[str] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    simulate_divergence: bool | None = None


class EpisodeConfirmRequest(BaseModel):
    reviewer: str = Field(default="desktop-user", validation_alias=AliasChoices("reviewer", "reviewed_by"))
    reason: str | None = Field(default=None, validation_alias=AliasChoices("reason", "notes"))
    activate_template: bool = True
    template_name: str | None = None


class PlaybookVersionBase(BaseModel):
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


class PlaybookVersionCreate(PlaybookVersionBase):
    pass


class PlaybookVersionUpdate(BaseModel):
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


class PlaybookVersionRead(PlaybookVersionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    last_validated_at: int | None = None
    created_at: int
    updated_at: int


class PlaybookPatchBase(BaseModel):
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


class PlaybookPatchCreate(PlaybookPatchBase):
    pass


class PlaybookPatchUpdate(BaseModel):
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


class PlaybookPatchRead(PlaybookPatchBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reviewed_at: int | None = None
    applied_at: int | None = None
    created_at: int
    updated_at: int


class EnvironmentSnapshotBase(BaseModel):
    task_spec_id: str | None = None
    execution_plan_id: str | None = None
    execution_episode_id: str | None = None
    source: str = "browser"
    environment_key: str | None = None
    status: str = "observed"
    resource_locator: str | None = None
    display_label: str | None = None
    environment_kind: str | None = None
    capability_hints: list[str] = Field(default_factory=list)
    observed_entities: list[dict[str, Any]] = Field(default_factory=list)
    action_hints: list[dict[str, Any]] = Field(default_factory=list)
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
    resource_locator: str | None = None
    display_label: str | None = None
    environment_kind: str | None = None
    capability_hints: list[str] | None = None
    observed_entities: list[dict[str, Any]] | None = None
    action_hints: list[dict[str, Any]] | None = None
    runtime_metadata: dict[str, Any] | None = None


class EnvironmentSnapshotRead(EnvironmentSnapshotBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: int
    updated_at: int


class EnvironmentSnapshotContextRead(BaseModel):
    persisted: bool = False
    id: str | None = None
    source: str = "browser"
    environment_key: str | None = None
    status: str = "observed"
    resource_locator: str | None = None
    display_label: str | None = None
    environment_kind: str = "generic_environment"
    capability_hints: list[str] = Field(default_factory=list)
    observed_entities: list[dict[str, Any]] = Field(default_factory=list)
    action_hints: list[dict[str, Any]] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class ObservedEntityRead(BaseModel):
    kind: str
    label: str
    entity_id: str | None = None
    role: str | None = None
    confidence: float | None = None
    state: str | None = None
    interactive: bool = False
    signals: list[str] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ActionAffordanceRead(BaseModel):
    kind: str
    label: str
    action: str
    target: str | None = None
    confidence: float | None = None
    enabled: bool = True
    requires_confirmation: bool = False
    signals: list[str] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SceneProfileRead(BaseModel):
    source: str
    scene_type: str
    interaction_mode: str = "inspect"
    volatility: str = "medium"
    auth_state: str = "unknown"
    entity_count: int = 0
    affordance_count: int = 0
    primary_targets: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class PlannerGuidanceRead(BaseModel):
    posture: str
    required_capabilities: list[str] = Field(default_factory=list)
    inserted_capabilities: list[str] = Field(default_factory=list)
    preferred_next_actions: list[str] = Field(default_factory=list)
    requires_scene_assessment: bool = False
    requires_human_review: bool = False
    should_checkpoint: bool = True
    rationale: list[str] = Field(default_factory=list)


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
    observed_entities: list[ObservedEntityRead] = Field(default_factory=list)
    affordances: list[ActionAffordanceRead] = Field(default_factory=list)
    scene_profile: SceneProfileRead
    planner_guidance: PlannerGuidanceRead
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
    id: str | None = None
    task_spec_id: str | None = None
    base_execution_plan_id: str | None = None
    previous_plan: ExecutionPlanRead
    execution_plan: ExecutionPlanRead
    assessment: EnvironmentAssessmentRead
    status: str = "replanned"
    summary: str | None = None
    compiler_notes: list[str] = Field(default_factory=list)
    recommended_capability_keys: list[str] = Field(default_factory=list)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: int | None = None


class SkillBase(BaseModel):
    skill_id: str
    name: str
    description: str | None = None
    category: str = "general"
    version: int = 1
    status: str = "draft"
    bound_to_stage: str | None = None
    platform: str = "site"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    strategy: dict[str, Any] = Field(default_factory=dict)
    execution_hints: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "medium"
    health_check_config: dict[str, Any] = Field(default_factory=dict)
    skill_metadata: dict[str, Any] = Field(default_factory=dict)
    last_health_check: datetime | None = None
    last_health_status: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


class SkillCreate(SkillBase):
    pass


class SkillUpdate(BaseModel):
    skill_id: str | None = None
    name: str | None = None
    description: str | None = None
    category: str | None = None
    version: int | None = None
    status: str | None = None
    bound_to_stage: str | None = None
    platform: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    strategy: dict[str, Any] | None = None
    execution_hints: dict[str, Any] | None = None
    risk_level: str | None = None
    health_check_config: dict[str, Any] | None = None
    skill_metadata: dict[str, Any] | None = None
    last_health_check: datetime | None = None
    last_health_status: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


class SkillRead(SkillBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    last_health_check: int | None = None
    confirmed_at: int | None = None
    created_at: int
    updated_at: int


class SkillHealthCheckRequest(BaseModel):
    observed_result: dict[str, Any] = Field(default_factory=dict)


class SkillHealthCheckRead(BaseModel):
    skill_id: str
    status: str
    health: str
    checked_at: int
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
    consolidated_at: int | None = None
    created_at: int
    updated_at: int


class RuntimeLearningOutcomeRead(BaseModel):
    episode: ExecutionEpisodeRead
    template: "PlaybookVersionRead | None" = None
    patch: "PlaybookPatchRead | None" = None
    learning_draft: LearningDraftRead | None = None
    approval: "ApprovalRead | None" = None
    template_approval: "ApprovalRead | None" = None
    skill_health: dict[str, Any] | None = None


class RuntimeReplayEventRead(BaseModel):
    sequence: int
    kind: str
    title: str
    detail: str | None = None
    occurred_at: int | None = None
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
    latest_snapshot_environment_kind: str | None = None
    latest_error: str | None = None


class RuntimeEpisodeReplayRead(BaseModel):
    task_spec: TaskSpecRead
    execution_plan: ExecutionPlanRead
    episode: ExecutionEpisodeRead
    snapshots: list[EnvironmentSnapshotRead] = Field(default_factory=list)
    template: "PlaybookVersionRead | None" = None
    patch: "PlaybookPatchRead | None" = None
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
    last_attempted_at: int | None = None
    next_attempt_at: int | None = None
    last_error: str | None = None
    delivery_mode: str | None = None
    synced_at: int | None = None
    created_at: int
    updated_at: int

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
    deferred_count: int = 0
    backlog_total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    latest_error: str | None = None
    next_attempt_at: int | None = None


class SyncFlushRead(BaseModel):
    attempted: int = 0
    synced: int = 0
    failed: int = 0
    deferred: int = 0
    pending: int = 0
    remote_available: bool = False
    target: dict[str, Any] = Field(default_factory=dict)
    next_attempt_at: int | None = None


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
    reviewed_at: int | None = None
    created_at: int
    updated_at: int


class MetricsSummary(BaseModel):
    candidate_count: int
    playbook_count: int
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


class PlaybookPatchDecisionRequest(BaseModel):
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
    apiKey: str | None = None
    timeoutSeconds: int = 180


class ProviderConfigUpdate(BaseModel):
    kind: str
    name: str
    model: str
    enabled: bool
    temperature: float = 0.2
    baseUrl: str | None = None
    apiKey: str | None = None
    timeoutSeconds: int | None = None


class ProviderHealthcheckRead(BaseModel):
    ok: bool
    status: str
    latencyMs: int | None = None
    message: str | None = None


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
    maxConcurrentRuns: int = 1
    minFunnelCandidates: int = 0


class PlatformSettingsUpdate(BaseModel):
    name: str | None = None
    account: str | None = None
    cooldownDays: int | None = None
    allowOutboundMessaging: bool | None = None
    maxConcurrentRuns: int | None = None
    minFunnelCandidates: int | None = None


class UserProfileSettingsRead(BaseModel):
    nickname: str
    avatarUrl: str | None = None


class UserProfileSettingsUpdate(BaseModel):
    nickname: str | None = None
    avatarUrl: str | None = None


class SettingsSnapshotRead(BaseModel):
    locale: str
    timezone: str
    intranetEnabled: bool
    desktopApprovalsOnly: bool
    autonomyEnabled: bool = False
    skill_health_autonomy_interval_seconds: int | None = None
    providers: list[ProviderConfigRead]
    intranetSync: IntranetSyncConfigRead
    platform: PlatformSettingsRead
    userProfile: UserProfileSettingsRead
    approval_source: str | None = None
    feature_flags: FeatureFlags | None = None
    provider_config: dict[str, Any] = Field(default_factory=dict)


class SettingsSnapshotUpdate(BaseModel):
    locale: str | None = None
    timezone: str | None = None
    intranetEnabled: bool | None = None
    desktopApprovalsOnly: bool | None = None
    autonomyEnabled: bool | None = None
    skill_health_autonomy_interval_seconds: int | None = None
    approval_source: str | None = None
    feature_flags: FeatureFlags | None = None
    provider_config: dict[str, Any] | None = None
    providers: list[ProviderConfigUpdate] | None = None
    intranetSync: IntranetSyncConfigUpdate | None = None
    platform: PlatformSettingsUpdate | None = None
    userProfile: UserProfileSettingsUpdate | None = None


class McpToolBase(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    enabled: bool = True
    risk_level: str = "medium"
    remote_name: str | None = None
    tool_metadata: dict[str, Any] = Field(default_factory=dict)


class McpToolCreate(McpToolBase):
    pass


class McpToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    parameters: dict[str, Any] | None = None
    capabilities: list[str] | None = None
    enabled: bool | None = None
    risk_level: str | None = None
    remote_name: str | None = None
    tool_metadata: dict[str, Any] | None = None


class McpToolRead(McpToolBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    server_id: str
    created_at: int
    updated_at: int


class McpServerBase(BaseModel):
    server_key: str
    name: str
    transport_kind: str = "unix_socket"
    protocol: str = "mcp_jsonrpc"
    endpoint: str
    enabled: bool = True
    preset_key: str | None = None
    auth_config: dict[str, Any] = Field(default_factory=dict)
    server_metadata: dict[str, Any] = Field(default_factory=dict)


class McpServerCreate(McpServerBase):
    tools: list[McpToolCreate] = Field(default_factory=list)


class McpServerUpdate(BaseModel):
    server_key: str | None = None
    name: str | None = None
    transport_kind: str | None = None
    protocol: str | None = None
    endpoint: str | None = None
    enabled: bool | None = None
    preset_key: str | None = None
    auth_config: dict[str, Any] | None = None
    server_metadata: dict[str, Any] | None = None
    tools: list[McpToolCreate] | None = None


class McpServerRead(McpServerBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    health_status: str
    health_error: str | None = None
    last_health_at: int | None = None
    tools: list[McpToolRead] = Field(default_factory=list)
    created_at: int
    updated_at: int


class McpPresetTemplateRead(BaseModel):
    key: str
    name: str
    description: str
    transport_kind: str
    protocol: str
    endpoint_example: str
    tools: list[McpToolCreate] = Field(default_factory=list)


class McpPresetInstallRequest(BaseModel):
    server_key: str | None = None
    name: str | None = None
    endpoint: str | None = None


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
    at: int
    tone: str


class ApplicationDashboardRead(BaseModel):
    applicationId: str | None = None
    personId: str | None = None
    jobDescriptionId: str | None = None
    platform: str
    currentStatus: str
    stageKey: str
    deepestMilestone: str | None = None
    matchScore: int
    nextAction: str
    summary: str
    resumeAvailable: bool
    person: ApplicationPersonSummaryRead
    jobDescription: JobDescriptionSummaryRead
    stateSnapshot: dict[str, Any] = Field(default_factory=dict)
    aiScores: dict[str, Any] = Field(default_factory=dict)
    cooldownUntil: int | None = None
    lastContactedAt: int | None = None


class ApplicationFollowUpSummaryDefinitionRead(BaseModel):
    key: str
    label: str
    summary: str
    relation: str | None = None
    matchingMode: str
    includeStatuses: list[str] = Field(default_factory=list)
    excludeStatuses: list[str] = Field(default_factory=list)
    includeLabels: list[str] = Field(default_factory=list)
    excludeLabels: list[str] = Field(default_factory=list)


class BlueprintNodeSummaryRead(BaseModel):
    id: str
    name: str
    kind: str
    status: str
    owner: str
    description: str


class PlaybookDashboardRead(BaseModel):
    id: str
    name: str
    description: str | None = None
    scopeKind: str
    scopeRef: str | None = None
    status: str
    version: str
    updatedAt: int
    nodes: list[BlueprintNodeSummaryRead]


class SkillDashboardRead(BaseModel):
    id: str
    name: str
    version: str
    status: str
    boundStage: str
    platform: str
    health: str
    lastCheckedAt: int
    summary: str


class ApprovalDashboardRead(BaseModel):
    id: str
    kind: str
    title: str
    detail: str
    requester: str
    status: str
    createdAt: int


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
    applications: list[ApplicationDashboardRead]
    applicationFollowUpSummaryDefinitions: list[ApplicationFollowUpSummaryDefinitionRead] = Field(default_factory=list)
    playbooks: list[PlaybookDashboardRead]
    skills: list[SkillDashboardRead]
    approvals: list[ApprovalDashboardRead]
    agent: AgentStatusRead
    settings: SettingsSnapshotRead


class AgentTaskCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    application_id: str | None = Field(default=None, validation_alias=AliasChoices("application_id", "applicationId"))
    task_spec_id: str | None = None
    execution_plan_id: str | None = None
    execution_episode_id: str | None = None
    requested_by: str = "desktop-user"
    mode: str = "production"


class AgentTaskEnqueueRead(BaseModel):
    task_id: str
    task_type: str
    priority: int
    queue_depth: int


class AgentQueueAuditEventRead(BaseModel):
    kind: str
    at: int | None = None
    status: str | None = None
    priority: int | None = None
    attempts: int | None = None
    locked_by: str | None = None
    error: str | None = None


class AgentQueueItemRead(BaseModel):
    task_id: str
    task_type: str
    adaptive_stage: str
    priority: int
    status: str
    attempts: int
    scheduled_for: int | None = None
    locked_at: int | None = None
    locked_by: str | None = None
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "application_id",
            "applicationId",
            AliasPath("payload", "application_id"),
            AliasPath("payload", "applicationId"),
        ),
        serialization_alias="applicationId",
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    queue_audit: list[AgentQueueAuditEventRead] = Field(default_factory=list)
    created_at: int
    updated_at: int


class AgentQueueRecoveryRead(BaseModel):
    recovered_count: int
    by_status: dict[str, int] = Field(default_factory=dict)


class RuntimeSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_definition_id: str = Field(
        validation_alias=AliasChoices("agent_definition_id", "agentDefinitionId"),
        serialization_alias="agentDefinitionId",
    )
    session_key: str
    status: str
    current_lane: str | None = None
    last_active_at: int | None = None
    last_run_at: int | None = None
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: int
    updated_at: int


class RuntimeControlledRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    execution_episode_id: str | None = None
    person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("person_id", "personId"),
        serialization_alias="personId",
    )
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    job_description_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("job_description_id", "jobDescriptionId", "jd_id"),
        serialization_alias="jobDescriptionId",
    )
    platform: str
    lane: str
    run_type: str
    status: str
    priority: int
    queue_task_id: str | None = None
    checkpoint_status: str
    context_manifest: dict[str, Any] = Field(default_factory=dict)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: int | None = None
    finished_at: int | None = None
    blocked_reason: str | None = None
    last_error: str | None = None
    created_at: int
    updated_at: int


class RuntimeCheckpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    run_id: str
    person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("person_id", "personId"),
        serialization_alias="personId",
    )
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    approval_id: str | None = None
    checkpoint_kind: str
    status: str
    title: str
    summary: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    resolved_by: str | None = None
    resolved_at: int | None = None
    created_at: int
    updated_at: int


class RuntimeEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    run_id: str | None = None
    turn_id: str | None = None
    conversation_id: str | None = None
    seq: int
    person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("person_id", "personId"),
        serialization_alias="personId",
    )
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    level: str
    source: str
    event_type: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: int
    created_at: int
    updated_at: int


class ExecutionTraceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    run_id: str | None = None
    person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("person_id", "personId"),
        serialization_alias="personId",
    )
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "application_id",
            "applicationId",
            AliasPath("trace_metadata", "application_id"),
            AliasPath("trace_metadata", "applicationId"),
        ),
        serialization_alias="applicationId",
    )
    lane: str
    trace_kind: str
    status: str
    title: str
    summary: str | None = None
    raw_trace: dict[str, Any] = Field(default_factory=dict)
    distilled_trace: dict[str, Any] = Field(default_factory=dict)
    outcome: dict[str, Any] = Field(default_factory=dict)
    trace_metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: int | None = None
    finished_at: int | None = None
    created_at: int
    updated_at: int


class StrategyFragmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_definition_id: str = Field(
        validation_alias=AliasChoices("agent_definition_id", "agentDefinitionId"),
        serialization_alias="agentDefinitionId",
    )
    run_id: str | None = None
    person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("person_id", "personId"),
        serialization_alias="personId",
    )
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "application_id",
            "applicationId",
            AliasPath("fragment_metadata", "application_id"),
            AliasPath("fragment_metadata", "applicationId"),
        ),
        serialization_alias="applicationId",
    )
    job_description_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("job_description_id", "jobDescriptionId", "jd_id"),
        serialization_alias="jobDescriptionId",
    )
    scope: str
    fragment_kind: str
    title: str
    summary: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str
    adoption_count: int = 0
    last_applied_at: int | None = None
    fragment_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: int
    updated_at: int


class ExecutionGraphProjectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str | None = None
    person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("person_id", "personId"),
        serialization_alias="personId",
    )
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "application_id",
            "applicationId",
            AliasPath("graph_metadata", "application_id"),
            AliasPath("graph_metadata", "applicationId"),
        ),
        serialization_alias="applicationId",
    )
    graph_kind: str
    title: str
    summary: str | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    rendered_text: str | None = None
    graph_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: int
    updated_at: int


class OperatorInteractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    run_id: str | None = None
    checkpoint_id: str | None = None
    approval_id: str | None = None
    person_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("person_id", "personId"),
        serialization_alias="personId",
    )
    application_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("application_id", "applicationId"),
        serialization_alias="applicationId",
    )
    lane: str
    interaction_type: str
    status: str
    title: str
    agent_prompt: str
    suggested_options: list[dict[str, Any]] = Field(default_factory=list)
    operator_response: dict[str, Any] = Field(default_factory=dict)
    effect_summary: str | None = None
    scope: str = "run_only"
    interaction_metadata: dict[str, Any] = Field(default_factory=dict)
    surfaced_at: int
    resolved_at: int | None = None
    resolved_by: str | None = None
    created_at: int
    updated_at: int


class OperatorInteractionResolveRequest(BaseModel):
    action: str
    comment: str | None = None
    operator: str = "desktop-user"
    scope: str | None = None


class TrialRunRequest(BaseModel):
    task_spec_id: str
    execution_plan_id: str
    requested_by: str = "desktop-user"
    notes: str | None = None
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimePlanEnqueueRequest(BaseModel):
    task_spec_id: str | None = None
    priority: int = 120
    requested_by: str = "desktop-user"
    mode: str = "production"
    payload: dict[str, Any] = Field(default_factory=dict)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimePlanEnqueueRead(BaseModel):
    task_id: str
    task_type: str
    priority: int
    queue_depth: int
    task_spec_id: str
    execution_plan_id: str
    execution_episode: ExecutionEpisodeRead
