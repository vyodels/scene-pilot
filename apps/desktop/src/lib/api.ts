import type {
  CandidateStatusTransition,
  CandidateTransitionPayload,
  RecruitmentStateMachine,
  StateCriteriaOptimizationReport,
  RecruitmentStateMachineVersionRecord,
  RecruitmentStateMachineUpdatePayload,
} from "@scene-pilot/shared";
import type {
  ApplicationAssessmentRecord,
  ApplicationConversationEntry,
  ApplicationFollowUpSummaryDefinition,
  ApplicationRecord,
  ApplicationStageEventRecord,
  ApplicationStateSnapshotRecord,
  ApplicationThreadRecord,
  AgentGlobalMemoryRecord,
  ApprovalItem,
  AgentEvent,
  AgentQueueItem,
  AgentSnapshot,
  AgentRunResult,
  AgentTaskEnqueueResult,
  AgentTaskRequest,
  CompileTaskRequest,
  CompileTaskResponse,
  DashboardSummary,
  DomainPackRecord,
  ExecutionGraphProjectionRecord,
  ExecutionTraceRecord,
  EvolutionArtifactRecord,
  GoalSpecRecord,
  ApplicationAssignmentRecord,
  JobMemoryRecord,
  McpPresetTemplateRecord,
  McpServerRecord,
  McpToolRecord,
  OperatorInteractionRecord,
  RecruitAgentProfileRecord,
  ResumeArtifactRecord,
  RuntimeCapabilityDriver,
  RuntimeCompilerContract,
  RuntimeEnvironmentAssessment,
  RuntimeEnvironmentAssessmentRequest,
  RuntimeEpisode,
  RuntimeEpisodeReplay,
  RuntimeLearningOutcome,
  RuntimePatch,
  RuntimePlanLaunchResult,
  RuntimePlanReplanRequest,
  RuntimePlanReplanResult,
  RuntimeSnapshot,
  RuntimeTaskSpec,
  RuntimeTemplate,
  RuntimeWorkspaceData,
  SettingsSnapshot,
  SkillRecord,
  StrategyFragmentRecord,
  SyncBacklogItem,
  SyncFlushResult,
  TalentPoolSyncRecord,
  SyncStatusSnapshot,
  PlaybookDefinition,
  ApplicationReviewDecisionRecord,
  ApplicationScorecardRecord,
  JobDescriptionSummaryRecord,
  PersonMemoryRecord,
  PersonSummaryRecord,
} from "./types";

export interface DesktopApiClient {
  getDashboardSummary(): Promise<DashboardSummary>;
  getRuntimeWorkspaceData(): Promise<RuntimeWorkspaceData>;
  getTaskCompilerContract(): Promise<RuntimeCompilerContract>;
  listDomainPacks(): Promise<DomainPackRecord[]>;
  listRuntimeTasks(): Promise<RuntimeTaskSpec[]>;
  compileRuntimeTask(payload: CompileTaskRequest): Promise<CompileTaskResponse>;
  listRuntimePlans(): Promise<RuntimeWorkspaceData["plans"]>;
  launchRuntimePlan(planId: string, taskSpecId: string, mode?: "trial" | "production"): Promise<RuntimePlanLaunchResult>;
  createTrialRun(taskSpecId: string, executionPlanId: string, notes?: string): Promise<RuntimeEpisode>;
  listRuntimeEpisodes(): Promise<RuntimeEpisode[]>;
  executeTrialRun(episodeId: string, notes?: string): Promise<RuntimeLearningOutcome>;
  refreshRuntimeLearning(episodeId: string): Promise<RuntimeLearningOutcome>;
  confirmTrialRun(episodeId: string, reason?: string): Promise<RuntimeLearningOutcome>;
  getRuntimeReplay(episodeId: string): Promise<RuntimeEpisodeReplay>;
  listRuntimeSnapshots(): Promise<RuntimeSnapshot[]>;
  listCapabilityDrivers(): Promise<RuntimeCapabilityDriver[]>;
  listRuntimeEnvironmentAssessments(): Promise<RuntimeEnvironmentAssessment[]>;
  assessRuntimeEnvironment(payload: RuntimeEnvironmentAssessmentRequest): Promise<RuntimeEnvironmentAssessment>;
  listRuntimeTemplates(): Promise<RuntimeTemplate[]>;
  listRuntimePatches(): Promise<RuntimePatch[]>;
  listRuntimeReplans(): Promise<RuntimePlanReplanResult[]>;
  replanRuntimePlan(payload: RuntimePlanReplanRequest): Promise<RuntimePlanReplanResult>;
  approveRuntimePatch(id: string, reason?: string): Promise<RuntimePatch>;
  rejectRuntimePatch(id: string, reason?: string): Promise<RuntimePatch>;
  getRecruitAgentProfile(): Promise<RecruitAgentProfileRecord>;
  updateRecruitAgentProfile(payload: Partial<RecruitAgentProfileRecord>): Promise<RecruitAgentProfileRecord>;
  listGoals(): Promise<GoalSpecRecord[]>;
  createGoal(payload: {
    title: string;
    goalText: string;
    goalKind?: string;
    requestedBy?: string;
    constraints?: Record<string, unknown>;
    successCriteria?: Record<string, unknown>;
    contextHints?: Record<string, unknown>;
    trialBudget?: Record<string, unknown>;
    runPreferences?: Record<string, unknown>;
    summary?: string;
    priority?: number;
  }): Promise<GoalSpecRecord>;
  listExecutionTraces(goalId?: string): Promise<ExecutionTraceRecord[]>;
  listExecutionGraphs(goalId?: string): Promise<ExecutionGraphProjectionRecord[]>;
  listStrategyFragments(): Promise<StrategyFragmentRecord[]>;
  listOperatorInteractions(candidateId?: string): Promise<OperatorInteractionRecord[]>;
  resolveOperatorInteraction(
    interactionId: string,
    payload: { action: string; comment?: string; operator?: string; scope?: string },
  ): Promise<OperatorInteractionRecord>;
  listPersonMemories(): Promise<PersonMemoryRecord[]>;
  getPersonMemory(personId: string): Promise<PersonMemoryRecord>;
  updatePersonMemory(personId: string, payload: Partial<PersonMemoryRecord>): Promise<PersonMemoryRecord>;
  compactPersonMemory(personId: string, reason?: string, force?: boolean): Promise<PersonMemoryRecord>;
  listJobMemories(): Promise<JobMemoryRecord[]>;
  getJobMemory(jobDescriptionId: string): Promise<JobMemoryRecord>;
  updateJobMemory(jobDescriptionId: string, payload: Partial<JobMemoryRecord>): Promise<JobMemoryRecord>;
  compactJobMemory(jobDescriptionId: string, reason?: string, force?: boolean): Promise<JobMemoryRecord>;
  getAgentGlobalMemory(): Promise<AgentGlobalMemoryRecord>;
  updateAgentGlobalMemory(payload: Partial<AgentGlobalMemoryRecord>): Promise<AgentGlobalMemoryRecord>;
  compactAgentGlobalMemory(reason?: string, force?: boolean): Promise<AgentGlobalMemoryRecord>;
  listApplicationThreads(): Promise<ApplicationThreadRecord[]>;
  getApplicationThread(applicationId: string): Promise<ApplicationThreadRecord>;
  getStateMachine(): Promise<RecruitmentStateMachine>;
  listStateMachineCriteriaSuggestions(): Promise<StateCriteriaOptimizationReport[]>;
  listStateMachineVersions(limit?: number): Promise<RecruitmentStateMachineVersionRecord[]>;
  getStateMachineVersion(version: number): Promise<RecruitmentStateMachineVersionRecord>;
  updateStateMachine(payload: RecruitmentStateMachineUpdatePayload): Promise<RecruitmentStateMachine>;
  listApplicationTransitions(applicationId: string): Promise<CandidateStatusTransition[]>;
  createApplicationEntry(applicationId: string, payload: { direction: string; content: string; messageType?: string; platform?: string }): Promise<ApplicationConversationEntry>;
  transitionApplicationState(applicationId: string, payload: CandidateTransitionPayload): Promise<ApplicationThreadRecord>;
  createApplicationAssessment(applicationId: string, payload: { assessmentType: string; stageKey?: string; status?: string; decision?: string; score?: number; summary?: string; evidenceRefs?: unknown[]; metadata?: Record<string, unknown>; createdBy?: string; reviewedBy?: string }): Promise<ApplicationAssessmentRecord>;
  listEvolutionArtifacts(): Promise<EvolutionArtifactRecord[]>;
  updateEvolutionArtifact(artifactId: string, payload: Partial<EvolutionArtifactRecord>): Promise<EvolutionArtifactRecord>;
  getSyncStatus(): Promise<SyncStatusSnapshot>;
  listSyncBacklog(): Promise<SyncBacklogItem[]>;
  flushSyncBacklog(): Promise<SyncFlushResult>;
  listApplications(): Promise<ApplicationRecord[]>;
  listPlaybooks(): Promise<PlaybookDefinition[]>;
  listSkills(): Promise<SkillRecord[]>;
  updateSkill(skillId: string, payload: Partial<SkillRecord>): Promise<SkillRecord>;
  deleteSkill(skillId: string): Promise<void>;
  listApprovals(): Promise<ApprovalItem[]>;
  listMcpPresets(): Promise<McpPresetTemplateRecord[]>;
  listMcpServers(): Promise<McpServerRecord[]>;
  installMcpPreset(
    presetKey: string,
    payload?: { serverKey?: string; name?: string; endpoint?: string },
  ): Promise<McpServerRecord>;
  createMcpServer(payload: {
    serverKey: string;
    name: string;
    transportKind: string;
    protocol: string;
    endpoint: string;
    enabled?: boolean;
    presetKey?: string | null;
    authConfig?: Record<string, unknown>;
    serverMetadata?: Record<string, unknown>;
    tools?: Array<{
      name: string;
      description: string;
      parameters?: Record<string, unknown>;
      capabilities?: string[];
      enabled?: boolean;
      riskLevel?: string;
      remoteName?: string | null;
      toolMetadata?: Record<string, unknown>;
    }>;
  }): Promise<McpServerRecord>;
  updateMcpServer(
    serverId: string,
    payload: Partial<{
      serverKey: string;
      name: string;
      transportKind: string;
      protocol: string;
      endpoint: string;
      enabled: boolean;
      presetKey: string | null;
      authConfig: Record<string, unknown>;
      serverMetadata: Record<string, unknown>;
      tools: Array<{
        name: string;
        description: string;
        parameters?: Record<string, unknown>;
        capabilities?: string[];
        enabled?: boolean;
        riskLevel?: string;
        remoteName?: string | null;
        toolMetadata?: Record<string, unknown>;
      }>;
    }>,
  ): Promise<McpServerRecord>;
  deleteMcpServer(serverId: string): Promise<void>;
  healthcheckMcpServer(serverId: string): Promise<McpServerRecord>;
  getSettings(): Promise<SettingsSnapshot>;
  getAgentSnapshot(): Promise<AgentSnapshot>;
  listAgentQueue(): Promise<AgentQueueItem[]>;
  approveItem(id: string): Promise<void>;
  rejectItem(id: string, reason?: string): Promise<void>;
  updateSettings(settings: Partial<SettingsSnapshot>): Promise<SettingsSnapshot>;
  runAgentOnce(): Promise<AgentRunResult>;
  queueTask(task: AgentTaskRequest): Promise<AgentTaskEnqueueResult>;
  subscribeToAgentStream(onEvent: (event: AgentEvent) => void): () => void;
}

export interface ApiDescription {
  baseUrl: string;
  transport: "http" | "offline";
}

type JsonRecord = Record<string, unknown>;

function isOfflineError(error: unknown): boolean {
  return error instanceof Error && /fetch|network|failed|offline/i.test(error.message);
}

function isMissingEndpointError(error: unknown): boolean {
  return error instanceof Error && /:\s*(404|405)\b/.test(error.message);
}

async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`);
  }

  return (await response.json()) as T;
}

async function requestOptionalJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T | undefined> {
  try {
    return await requestJson<T>(baseUrl, path, init);
  } catch (error) {
    if (isMissingEndpointError(error)) {
      return undefined;
    }
    throw error;
  }
}

async function requestVoid(baseUrl: string, path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(`${baseUrl}${path}`, {
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`);
  }
}

function asRecord(value: unknown): JsonRecord {
  return typeof value === "object" && value !== null ? (value as JsonRecord) : {};
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function humanizeKey(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function labelFromSignal(value: unknown): string | null {
  const record = asRecord(value);
  const label = record.label ?? record.kind ?? record.name ?? record.id;
  return label ? String(label) : null;
}

function normalizeAgentSnapshot(raw: unknown): AgentSnapshot {
  const record = asRecord(raw);
  return {
    status: String(record.status ?? "idle") as AgentSnapshot["status"],
    activeTask: String(record.activeTask ?? record.active_task ?? "Idle"),
    browserLock: String(record.browserLock ?? record.browser_lock ?? "free") as AgentSnapshot["browserLock"],
    uptime: String(record.uptime ?? "00:00:00"),
    queueDepth: Number(record.queueDepth ?? record.queue_depth ?? 0),
    tokenBudgetUsed: Number(record.tokenBudgetUsed ?? record.token_budget_used ?? 0),
    health: String(record.health ?? "warning") as AgentSnapshot["health"],
  };
}

function normalizeAgentQueueItem(raw: unknown): AgentQueueItem {
  const record = asRecord(raw);
  return {
    taskId: String(record.taskId ?? record.task_id ?? ""),
    taskType: String(record.taskType ?? record.task_type ?? ""),
    adaptiveStage: String(record.adaptiveStage ?? record.adaptive_stage ?? record.taskType ?? record.task_type ?? ""),
    priority: Number(record.priority ?? 0),
    status: String(record.status ?? "pending"),
    attempts: Number(record.attempts ?? 0),
    scheduledFor: record.scheduledFor ? String(record.scheduledFor) : record.scheduled_for ? String(record.scheduled_for) : null,
    lockedAt: record.lockedAt ? String(record.lockedAt) : record.locked_at ? String(record.locked_at) : null,
    lockedBy: record.lockedBy ? String(record.lockedBy) : record.locked_by ? String(record.locked_by) : null,
    candidateId: record.candidateId ? String(record.candidateId) : record.candidate_id ? String(record.candidate_id) : null,
    payload: asRecord(record.payload),
    queueAudit: asArray(record.queueAudit ?? record.queue_audit).map((entry) => {
      const audit = asRecord(entry);
      return {
        kind: String(audit.kind ?? "unknown"),
        at: String(audit.at ?? new Date().toISOString()),
        status: audit.status ? String(audit.status) : null,
        priority: audit.priority != null ? Number(audit.priority) : null,
        attempts: audit.attempts != null ? Number(audit.attempts) : null,
        lockedBy: audit.lockedBy ? String(audit.lockedBy) : audit.locked_by ? String(audit.locked_by) : null,
        error: audit.error ? String(audit.error) : null,
      };
    }),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeSettings(raw: unknown): SettingsSnapshot {
  const record = asRecord(raw);
  const platform = asRecord(record.platform);
  const intranetSync = asRecord(record.intranetSync ?? record.intranet_sync);
  return {
    locale: String(record.locale ?? "en-US"),
    timezone: String(record.timezone ?? "Asia/Shanghai"),
    intranetEnabled: Boolean(record.intranetEnabled ?? record.intranet_enabled ?? false),
    desktopApprovalsOnly: Boolean(record.desktopApprovalsOnly ?? (record.approval_source ?? "desktop_app") === "desktop_app"),
    autonomyEnabled: Boolean(
      record.autonomyEnabled ??
        record.autonomy_enabled ??
        asRecord(record.featureFlags ?? record.feature_flags).enableAutonomy ??
        asRecord(record.featureFlags ?? record.feature_flags).enable_autonomy ??
        false,
    ),
    skillHealthAutonomyEnabled: Boolean(
      asRecord(record.featureFlags ?? record.feature_flags).enableSkillHealthAutonomy ??
        asRecord(record.featureFlags ?? record.feature_flags).enable_skill_health_autonomy ??
        false,
    ),
    skillHealthAutonomyIntervalSeconds: Number(
      record.skillHealthAutonomyIntervalSeconds ??
        record.skill_health_autonomy_interval_seconds ??
        300,
    ),
    providers: asArray<JsonRecord>(record.providers).map((provider) => ({
      kind: String(provider.kind ?? "openai-compatible") as SettingsSnapshot["providers"][number]["kind"],
      name: String(provider.name ?? "Provider"),
      model: String(provider.model ?? "unknown"),
      baseUrl: provider.baseUrl ? String(provider.baseUrl) : undefined,
      apiKey: provider.apiKey ? String(provider.apiKey) : provider.api_key ? String(provider.api_key) : undefined,
      timeoutSeconds: Number(provider.timeoutSeconds ?? provider.timeout_seconds ?? 180),
      enabled: Boolean(provider.enabled ?? false),
      temperature: Number(provider.temperature ?? 0.2),
    })),
    intranetSync: {
      enabled: Boolean(intranetSync.enabled ?? false),
      baseUrl: intranetSync.baseUrl ? String(intranetSync.baseUrl) : intranetSync.base_url ? String(intranetSync.base_url) : undefined,
      apiPath: String(intranetSync.apiPath ?? intranetSync.api_path ?? "/sync/runtime"),
      timeoutSeconds: Number(intranetSync.timeoutSeconds ?? intranetSync.timeout_seconds ?? 15),
    },
    platform: {
      name: String(platform.name ?? "本地执行配置"),
      account: String(platform.account ?? "本机场景 01"),
      cooldownDays: Number(platform.cooldownDays ?? platform.cooldown_days ?? 30),
      allowOutboundMessaging: Boolean(platform.allowOutboundMessaging ?? platform.allow_outbound_messaging ?? false),
      maxConcurrentRuns: Number(platform.maxConcurrentRuns ?? platform.max_concurrent_runs ?? 1),
      minFunnelCandidates: Number(platform.minFunnelCandidates ?? platform.min_funnel_candidates ?? 0),
    },
  };
}

function normalizeMcpTool(raw: unknown): McpToolRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    serverId: String(record.serverId ?? record.server_id ?? ""),
    name: String(record.name ?? ""),
    description: String(record.description ?? ""),
    parameters: asRecord(record.parameters),
    capabilities: asArray<string>(record.capabilities),
    enabled: Boolean(record.enabled ?? true),
    riskLevel: String(record.riskLevel ?? record.risk_level ?? "medium"),
    remoteName: record.remoteName ? String(record.remoteName) : record.remote_name ? String(record.remote_name) : null,
    toolMetadata: asRecord(record.toolMetadata ?? record.tool_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeMcpServer(raw: unknown): McpServerRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    serverKey: String(record.serverKey ?? record.server_key ?? ""),
    name: String(record.name ?? ""),
    transportKind: String(record.transportKind ?? record.transport_kind ?? "unix_socket"),
    protocol: String(record.protocol ?? "mcp_jsonrpc"),
    endpoint: String(record.endpoint ?? ""),
    enabled: Boolean(record.enabled ?? true),
    presetKey: record.presetKey ? String(record.presetKey) : record.preset_key ? String(record.preset_key) : null,
    authConfig: asRecord(record.authConfig ?? record.auth_config),
    serverMetadata: asRecord(record.serverMetadata ?? record.server_metadata),
    healthStatus: String(record.healthStatus ?? record.health_status ?? "unknown"),
    healthError: record.healthError ? String(record.healthError) : record.health_error ? String(record.health_error) : null,
    lastHealthAt: record.lastHealthAt ? String(record.lastHealthAt) : record.last_health_at ? String(record.last_health_at) : null,
    tools: asArray(record.tools).map(normalizeMcpTool),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeMcpPreset(raw: unknown): McpPresetTemplateRecord {
  const record = asRecord(raw);
  return {
    key: String(record.key ?? ""),
    name: String(record.name ?? ""),
    description: String(record.description ?? ""),
    transportKind: String(record.transportKind ?? record.transport_kind ?? "unix_socket"),
    protocol: String(record.protocol ?? "mcp_jsonrpc"),
    endpointExample: String(record.endpointExample ?? record.endpoint_example ?? ""),
    tools: asArray(record.tools).map((tool) => {
      const normalized = normalizeMcpTool({ ...asRecord(tool), id: "", server_id: "" });
      return {
        name: normalized.name,
        description: normalized.description,
        parameters: normalized.parameters,
        capabilities: normalized.capabilities,
        enabled: normalized.enabled,
        riskLevel: normalized.riskLevel,
        remoteName: normalized.remoteName,
        toolMetadata: normalized.toolMetadata,
      };
    }),
  };
}

function normalizeDashboard(raw: unknown): DashboardSummary {
  const record = asRecord(raw);
  return {
    metrics: asArray(record.metrics) as DashboardSummary["metrics"],
    pipeline: asArray(record.pipeline) as DashboardSummary["pipeline"],
    timeline: asArray(record.timeline) as DashboardSummary["timeline"],
    alerts: asArray(record.alerts) as DashboardSummary["alerts"],
    applications: asArray(record.applications ?? record.candidates).map(normalizeApplicationRecord),
    applicationFollowUpSummaryDefinitions: asArray(
      record.applicationFollowUpSummaryDefinitions ??
        record.application_follow_up_summary_definitions,
    ).map(normalizeApplicationFollowUpSummaryDefinition),
    playbooks: asArray(record.playbooks) as PlaybookDefinition[],
    skills: asArray(record.skills).map(normalizeSkillRecord),
    approvals: asArray(record.approvals).map(normalizeApprovalItem),
    agent: normalizeAgentSnapshot(record.agent),
    settings: normalizeSettings(record.settings),
  };
}

function normalizeApplicationFollowUpSummaryDefinition(raw: unknown): ApplicationFollowUpSummaryDefinition {
  const record = asRecord(raw);
  return {
    key: String(record.key ?? "all") as ApplicationFollowUpSummaryDefinition["key"],
    label: String(record.label ?? ""),
    summary: String(record.summary ?? ""),
    relation: record.relation ? String(record.relation) : null,
    matchingMode: String(record.matchingMode ?? record.matching_mode ?? "all") as ApplicationFollowUpSummaryDefinition["matchingMode"],
    includeStatuses: asArray<string>(record.includeStatuses ?? record.include_statuses),
    excludeStatuses: asArray<string>(record.excludeStatuses ?? record.exclude_statuses),
    includeLabels: asArray<string>(record.includeLabels ?? record.include_labels),
    excludeLabels: asArray<string>(record.excludeLabels ?? record.exclude_labels),
  };
}

function normalizePersonSummary(raw: unknown, fallbackContactInfo?: Record<string, unknown>): PersonSummaryRecord {
  const record = asRecord(raw);
  const contactInfo = asRecord(record.contactInfo ?? record.contact_info ?? fallbackContactInfo);
  return {
    personId:
      record.personId != null ? String(record.personId) : record.person_id != null ? String(record.person_id) : null,
    platformCandidateId:
      record.platformCandidateId != null
        ? String(record.platformCandidateId)
        : record.platform_candidate_id != null
          ? String(record.platform_candidate_id)
          : null,
    name: String(record.name ?? "Unknown candidate"),
    title: String(record.title ?? contactInfo.title ?? "候选人"),
    location: String(record.location ?? contactInfo.location ?? "未知"),
    experienceYears: Number(record.experienceYears ?? record.experience_years ?? contactInfo.experience_years ?? 0),
    tags: asArray<string>(record.tags ?? contactInfo.tags),
    contactInfo,
  };
}

function normalizeJobDescriptionSummary(raw: unknown, fallbackId?: string | null): JobDescriptionSummaryRecord {
  const record = asRecord(raw);
  return {
    jobDescriptionId:
      record.jobDescriptionId != null
        ? String(record.jobDescriptionId)
        : record.job_description_id != null
          ? String(record.job_description_id)
          : fallbackId,
    title: String(record.title ?? fallbackId ?? "未分配岗位"),
  };
}

function normalizeApplicationRecord(raw: unknown): ApplicationRecord {
  const record = asRecord(raw);
  const aiScores = asRecord(record.aiScores ?? record.ai_scores);
  const applicationId = String(record.applicationId ?? record.application_id ?? record.id ?? "");
  const personId =
    record.personId != null ? String(record.personId) : record.person_id != null ? String(record.person_id) : null;
  const jobDescriptionId =
    record.jobDescriptionId != null
      ? String(record.jobDescriptionId)
      : record.job_description_id != null
        ? String(record.job_description_id)
        : null;
  return {
    id: applicationId,
    applicationId,
    personId,
    jobDescriptionId,
    platform: String(record.platform ?? "site"),
    currentStatus: String(record.currentStatus ?? record.current_status ?? "discovered") as ApplicationRecord["currentStatus"],
    stageKey: String(record.stageKey ?? record.stage_key ?? record.currentStageKey ?? record.current_stage_key ?? "candidate_probe"),
    deepestMilestone:
      record.deepestMilestone
        ? String(record.deepestMilestone)
        : record.deepest_milestone
          ? String(record.deepest_milestone)
          : null,
    matchScore: Number(record.matchScore ?? record.match_score ?? aiScores.overall ?? 0),
    nextAction: String(
      record.nextAction ??
        record.next_action ??
        "等待 Recruit Agent 选择下一步动作。",
    ),
    summary: String(
      record.summary ??
        record.aiReasoning ??
        record.ai_reasoning ??
        record.onlineResumeText ??
        record.online_resume_text ??
        "候选人档案等待补充。",
    ),
    resumeAvailable: Boolean(record.resumeAvailable ?? record.resume_available ?? false),
    person: normalizePersonSummary(
      record.person ?? {},
    ),
    jobDescription: normalizeJobDescriptionSummary(
      record.jobDescription ?? record.job_description ?? {},
      jobDescriptionId,
    ),
    stateSnapshot:
      record.stateSnapshot ?? record.state_snapshot
        ? normalizeApplicationStateSnapshot(record.stateSnapshot ?? record.state_snapshot)
        : undefined,
    aiScores,
    cooldownUntil: record.cooldownUntil
      ? String(record.cooldownUntil)
      : record.cooldown_until
        ? String(record.cooldown_until)
        : undefined,
    lastContactedAt: record.lastContactedAt
      ? String(record.lastContactedAt)
      : record.last_contacted_at
        ? String(record.last_contacted_at)
        : undefined,
  };
}

function normalizeApplicationStateSnapshot(raw: unknown): ApplicationStateSnapshotRecord {
  const record = asRecord(raw);
  return {
    currentPhaseKey: record.currentPhaseKey ? String(record.currentPhaseKey) : record.current_phase_key ? String(record.current_phase_key) : null,
    currentPhaseLabel: record.currentPhaseLabel ? String(record.currentPhaseLabel) : record.current_phase_label ? String(record.current_phase_label) : null,
    currentStageKey: record.currentStageKey ? String(record.currentStageKey) : record.current_stage_key ? String(record.current_stage_key) : null,
    currentStageLabel: record.currentStageLabel ? String(record.currentStageLabel) : record.current_stage_label ? String(record.current_stage_label) : null,
    contactStatus: record.contactStatus ? String(record.contactStatus) : record.contact_status ? String(record.contact_status) : null,
    contactChannels: asArray<string>(record.contactChannels ?? record.contact_channels),
    contactAcquired: Boolean(record.contactAcquired ?? record.contact_acquired ?? false),
    resumeStatus: record.resumeStatus ? String(record.resumeStatus) : record.resume_status ? String(record.resume_status) : null,
    aiAssessmentStatus: record.aiAssessmentStatus ? String(record.aiAssessmentStatus) : record.ai_assessment_status ? String(record.ai_assessment_status) : null,
    humanAssessmentStatus: record.humanAssessmentStatus ? String(record.humanAssessmentStatus) : record.human_assessment_status ? String(record.human_assessment_status) : null,
    operatorFlags: asArray<string>(record.operatorFlags ?? record.operator_flags),
    nextRecommendedStages: asArray<string>(record.nextRecommendedStages ?? record.next_recommended_stages),
    interviewPlan: asRecord(record.interviewPlan ?? record.interview_plan),
    latestNote: record.latestNote ? String(record.latestNote) : record.latest_note ? String(record.latest_note) : null,
    latestTransitionAt: record.latestTransitionAt ? String(record.latestTransitionAt) : record.latest_transition_at ? String(record.latest_transition_at) : null,
    latestTransitionSource: record.latestTransitionSource ? String(record.latestTransitionSource) : record.latest_transition_source ? String(record.latest_transition_source) : null,
    snapshotMetadata: asRecord(record.snapshotMetadata ?? record.snapshot_metadata),
  };
}

function normalizeSkillRecord(raw: unknown): SkillRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    skillId: String(record.skillId ?? record.skill_id ?? record.id ?? ""),
    name: String(record.name ?? "Skill"),
    description: record.description ? String(record.description) : undefined,
    category: record.category ? String(record.category) : undefined,
    version: String(record.version ?? "1"),
    status: String(record.status ?? "draft") as SkillRecord["status"],
    boundStage: String(record.boundStage ?? record.bound_to_stage ?? "unbound"),
    platform: String(record.platform ?? "site"),
    inputSchema: asRecord(record.inputSchema ?? record.input_schema),
    outputSchema: asRecord(record.outputSchema ?? record.output_schema),
    strategy: asRecord(record.strategy),
    executionHints: asRecord(record.executionHints ?? record.execution_hints),
    healthCheckConfig: asRecord(record.healthCheckConfig ?? record.health_check_config),
    riskLevel: record.riskLevel ? String(record.riskLevel) : record.risk_level ? String(record.risk_level) : undefined,
    skillMetadata: asRecord(record.skillMetadata ?? record.skill_metadata),
    health: String(record.health ?? record.lastHealthStatus ?? record.last_health_status ?? "warning") as SkillRecord["health"],
    lastCheckedAt: String(record.lastCheckedAt ?? record.last_health_check ?? new Date().toISOString()),
    summary: String(record.summary ?? record.description ?? "Skill strategy managed by Recruit Agent."),
  };
}

function summarizeApprovalPayload(payload: Record<string, unknown>): string {
  const lines: string[] = [];
  const stepId = payload.step_id ?? payload.stepId;
  const executionPlanId = payload.execution_plan_id ?? payload.executionPlanId;
  const executionEpisodeId = payload.execution_episode_id ?? payload.executionEpisodeId;
  const reason = payload.reason;
  const summary = payload.summary;
  const candidate =
    payload.candidate_name_or_identifier ??
    payload.candidateNameOrIdentifier ??
    payload.candidate_id ??
    payload.candidateId;
  const command = Array.isArray(payload.command) ? payload.command.join(" ") : null;

  if (summary) {
    lines.push(String(summary));
  }
  if (reason) {
    lines.push(String(reason));
  }
  if (candidate) {
    lines.push(`Candidate: ${String(candidate)}`);
  }
  if (stepId) {
    lines.push(`Step: ${String(stepId)}`);
  }
  if (executionPlanId) {
    lines.push(`Plan: ${String(executionPlanId)}`);
  }
  if (executionEpisodeId) {
    lines.push(`Episode: ${String(executionEpisodeId)}`);
  }
  if (command) {
    lines.push(`Command: ${command}`);
  }
  return lines.join(" · ");
}

function normalizeApprovalItem(raw: unknown): ApprovalItem {
  const record = asRecord(raw);
  const payload = asRecord(record.payload);
  const targetType = String(record.targetType ?? record.target_type ?? record.kind ?? "approval");
  const targetId = record.targetId ? String(record.targetId) : record.target_id ? String(record.target_id) : undefined;
  const relatedCandidateId =
    record.relatedCandidateId != null
      ? String(record.relatedCandidateId)
      : record.related_candidate_id != null
        ? String(record.related_candidate_id)
        : payload.candidateId != null
          ? String(payload.candidateId)
          : payload.candidate_id != null
            ? String(payload.candidate_id)
            : /candidate|communication|message|outreach/i.test(targetType) && targetId
              ? String(targetId)
              : undefined;
  const explicitSurface =
    record.surface === "runtime" || record.surface === "evolution"
      ? (record.surface as ApprovalItem["surface"])
      : null;
  const surface: ApprovalItem["surface"] =
    explicitSurface ?? (targetType === "blocked_task" || relatedCandidateId ? "runtime" : "evolution");
  const detail =
    record.detail != null
      ? String(record.detail)
      : record.notes != null
        ? String(record.notes)
        : summarizeApprovalPayload(payload) || "Awaiting operator review.";
  return {
    id: String(record.id ?? ""),
    kind: String(record.kind ?? targetType),
    title: String(record.title ?? humanizeKey(targetType)),
    detail,
    requester: String(record.requester ?? record.requestedBy ?? record.requested_by ?? "system"),
    status: String(record.status ?? "pending") as ApprovalItem["status"],
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    targetType: targetType,
    targetId,
    reviewedBy: record.reviewedBy ? String(record.reviewedBy) : record.reviewed_by ? String(record.reviewed_by) : null,
    reviewedAt: record.reviewedAt ? String(record.reviewedAt) : record.reviewed_at ? String(record.reviewed_at) : null,
    payload,
    notes: record.notes ? String(record.notes) : null,
    updatedAt: record.updatedAt ? String(record.updatedAt) : record.updated_at ? String(record.updated_at) : undefined,
    surface,
    relatedCandidateId: relatedCandidateId ?? null,
  };
}

function normalizeGoalSpec(raw: unknown): GoalSpecRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    agentProfileId: String(record.agentProfileId ?? record.agent_profile_id ?? ""),
    title: String(record.title ?? ""),
    goalText: String(record.goalText ?? record.goal_text ?? ""),
    goalKind: String(record.goalKind ?? record.goal_kind ?? "recruiting"),
    status: String(record.status ?? "draft"),
    source: String(record.source ?? "operator"),
    sourceText: record.sourceText ? String(record.sourceText) : record.source_text ? String(record.source_text) : null,
    requestedBy: record.requestedBy ? String(record.requestedBy) : record.requested_by ? String(record.requested_by) : null,
    constraints: asRecord(record.constraints),
    successCriteria: asRecord(record.successCriteria ?? record.success_criteria),
    contextHints: asRecord(record.contextHints ?? record.context_hints),
    trialBudget: asRecord(record.trialBudget ?? record.trial_budget),
    runPreferences: asRecord(record.runPreferences ?? record.run_preferences),
    summary: record.summary ? String(record.summary) : null,
    latestRunId: record.latestRunId ? String(record.latestRunId) : record.latest_run_id ? String(record.latest_run_id) : null,
    lastActivityAt: record.lastActivityAt ? String(record.lastActivityAt) : record.last_activity_at ? String(record.last_activity_at) : null,
    goalMetadata: asRecord(record.goalMetadata ?? record.goal_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeExecutionTrace(raw: unknown): ExecutionTraceRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    sessionId: String(record.sessionId ?? record.session_id ?? ""),
    runId: record.runId ? String(record.runId) : record.run_id ? String(record.run_id) : null,
    goalSpecId: record.goalSpecId ? String(record.goalSpecId) : record.goal_spec_id ? String(record.goal_spec_id) : null,
    candidateId: record.candidateId ? String(record.candidateId) : record.candidate_id ? String(record.candidate_id) : null,
    lane: String(record.lane ?? "agent"),
    traceKind: String(record.traceKind ?? record.trace_kind ?? "adaptive_run"),
    status: String(record.status ?? "captured"),
    title: String(record.title ?? ""),
    summary: record.summary ? String(record.summary) : null,
    rawTrace: asRecord(record.rawTrace ?? record.raw_trace),
    distilledTrace: asRecord(record.distilledTrace ?? record.distilled_trace),
    outcome: asRecord(record.outcome),
    traceMetadata: asRecord(record.traceMetadata ?? record.trace_metadata),
    startedAt: record.startedAt ? String(record.startedAt) : record.started_at ? String(record.started_at) : null,
    finishedAt: record.finishedAt ? String(record.finishedAt) : record.finished_at ? String(record.finished_at) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeExecutionGraph(raw: unknown): ExecutionGraphProjectionRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    goalSpecId: record.goalSpecId ? String(record.goalSpecId) : record.goal_spec_id ? String(record.goal_spec_id) : null,
    runId: record.runId ? String(record.runId) : record.run_id ? String(record.run_id) : null,
    candidateId: record.candidateId ? String(record.candidateId) : record.candidate_id ? String(record.candidate_id) : null,
    graphKind: String(record.graphKind ?? record.graph_kind ?? "execution_projection"),
    title: String(record.title ?? ""),
    summary: record.summary ? String(record.summary) : null,
    nodes: asArray<Record<string, unknown>>(record.nodes),
    edges: asArray<Record<string, unknown>>(record.edges),
    renderedText: record.renderedText ? String(record.renderedText) : record.rendered_text ? String(record.rendered_text) : null,
    graphMetadata: asRecord(record.graphMetadata ?? record.graph_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeStrategyFragment(raw: unknown): StrategyFragmentRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    agentProfileId: String(record.agentProfileId ?? record.agent_profile_id ?? ""),
    goalSpecId: record.goalSpecId ? String(record.goalSpecId) : record.goal_spec_id ? String(record.goal_spec_id) : null,
    runId: record.runId ? String(record.runId) : record.run_id ? String(record.run_id) : null,
    candidateId: record.candidateId ? String(record.candidateId) : record.candidate_id ? String(record.candidate_id) : null,
    jdId: record.jdId ? String(record.jdId) : record.jd_id ? String(record.jd_id) : null,
    scope: String(record.scope ?? "agent"),
    fragmentKind: String(record.fragmentKind ?? record.fragment_kind ?? "strategy"),
    title: String(record.title ?? ""),
    summary: record.summary ? String(record.summary) : null,
    content: asRecord(record.content),
    evidence: asRecord(record.evidence),
    status: String(record.status ?? "draft"),
    adoptionCount: Number(record.adoptionCount ?? record.adoption_count ?? 0),
    lastAppliedAt: record.lastAppliedAt ? String(record.lastAppliedAt) : record.last_applied_at ? String(record.last_applied_at) : null,
    fragmentMetadata: asRecord(record.fragmentMetadata ?? record.fragment_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeOperatorInteraction(raw: unknown): OperatorInteractionRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    sessionId: String(record.sessionId ?? record.session_id ?? ""),
    runId: record.runId ? String(record.runId) : record.run_id ? String(record.run_id) : null,
    checkpointId: record.checkpointId ? String(record.checkpointId) : record.checkpoint_id ? String(record.checkpoint_id) : null,
    approvalId: record.approvalId ? String(record.approvalId) : record.approval_id ? String(record.approval_id) : null,
    goalSpecId: record.goalSpecId ? String(record.goalSpecId) : record.goal_spec_id ? String(record.goal_spec_id) : null,
    candidateId: record.candidateId ? String(record.candidateId) : record.candidate_id ? String(record.candidate_id) : null,
    lane: String(record.lane ?? "agent"),
    interactionType: String(record.interactionType ?? record.interaction_type ?? "confirm"),
    status: String(record.status ?? "pending"),
    title: String(record.title ?? ""),
    agentPrompt: String(record.agentPrompt ?? record.agent_prompt ?? ""),
    suggestedOptions: asArray<Record<string, unknown>>(record.suggestedOptions ?? record.suggested_options),
    operatorResponse: asRecord(record.operatorResponse ?? record.operator_response),
    effectSummary: record.effectSummary ? String(record.effectSummary) : record.effect_summary ? String(record.effect_summary) : null,
    scope: String(record.scope ?? "run_only"),
    interactionMetadata: asRecord(record.interactionMetadata ?? record.interaction_metadata),
    surfacedAt: String(record.surfacedAt ?? record.surfaced_at ?? new Date().toISOString()),
    resolvedAt: record.resolvedAt ? String(record.resolvedAt) : record.resolved_at ? String(record.resolved_at) : null,
    resolvedBy: record.resolvedBy ? String(record.resolvedBy) : record.resolved_by ? String(record.resolved_by) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeRecruitAgentProfile(raw: unknown): RecruitAgentProfileRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    agentKey: String(record.agentKey ?? record.agent_key ?? "recruit-agent"),
    name: String(record.name ?? "Recruit Agent"),
    status: String(record.status ?? "draft"),
    description: record.description ? String(record.description) : undefined,
    isPrimary: Boolean(record.isPrimary ?? record.is_primary ?? false),
    roleDefinition: asRecord(record.roleDefinition ?? record.role_definition),
    promptConfig: asRecord(record.promptConfig ?? record.prompt_config),
    playbookBlueprint: asRecord(record.playbookBlueprint ?? record.playbook_blueprint),
    memoryPolicy: asRecord(record.memoryPolicy ?? record.memory_policy),
    dashboardConfig: asRecord(record.dashboardConfig ?? record.dashboard_config),
    channelConfig: asRecord(record.channelConfig ?? record.channel_config),
    agentMetadata: asRecord(record.agentMetadata ?? record.agent_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizePersonMemory(raw: unknown): PersonMemoryRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    agentProfileId: String(record.agentProfileId ?? record.agent_profile_id ?? ""),
    personId: String(record.personId ?? record.person_id ?? ""),
    status: String(record.status ?? "active"),
    memorySchemaVersion: String(record.memorySchemaVersion ?? record.memory_schema_version ?? "candidate-person-memory-v1"),
    summary: record.summary ? String(record.summary) : undefined,
    rawContent: asRecord(record.rawContent ?? record.raw_content),
    content: asRecord(record.content),
    disclosure: normalizeMemoryDisclosure(record.disclosure),
    tokenEstimate: Number(record.tokenEstimate ?? record.token_estimate ?? 0),
    sourceCount: Number(record.sourceCount ?? record.source_count ?? 0),
    compactedAt: record.compactedAt ? String(record.compactedAt) : record.compacted_at ? String(record.compacted_at) : null,
    compactedReason: record.compactedReason ? String(record.compactedReason) : record.compacted_reason ? String(record.compacted_reason) : null,
    memoryMetadata: asRecord(record.memoryMetadata ?? record.memory_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeJobMemory(raw: unknown): JobMemoryRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    agentProfileId: String(record.agentProfileId ?? record.agent_profile_id ?? ""),
    jobDescriptionId: String(record.jobDescriptionId ?? record.job_description_id ?? ""),
    status: String(record.status ?? "active"),
    memorySchemaVersion: String(record.memorySchemaVersion ?? record.memory_schema_version ?? "job-description-memory-v1"),
    summary: record.summary ? String(record.summary) : undefined,
    rawContent: asRecord(record.rawContent ?? record.raw_content),
    content: asRecord(record.content),
    disclosure: normalizeMemoryDisclosure(record.disclosure),
    tokenEstimate: Number(record.tokenEstimate ?? record.token_estimate ?? 0),
    sourceCount: Number(record.sourceCount ?? record.source_count ?? 0),
    compactedAt: record.compactedAt ? String(record.compactedAt) : record.compacted_at ? String(record.compacted_at) : null,
    compactedReason: record.compactedReason ? String(record.compactedReason) : record.compacted_reason ? String(record.compacted_reason) : null,
    memoryMetadata: asRecord(record.memoryMetadata ?? record.memory_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeAgentGlobalMemory(raw: unknown): AgentGlobalMemoryRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    agentProfileId: String(record.agentProfileId ?? record.agent_profile_id ?? ""),
    status: String(record.status ?? "active"),
    memorySchemaVersion: String(record.memorySchemaVersion ?? record.memory_schema_version ?? "agent-global-memory-v1"),
    summary: record.summary ? String(record.summary) : undefined,
    rawContent: asRecord(record.rawContent ?? record.raw_content),
    content: asRecord(record.content),
    disclosure: normalizeMemoryDisclosure(record.disclosure),
    tokenEstimate: Number(record.tokenEstimate ?? record.token_estimate ?? 0),
    sourceCount: Number(record.sourceCount ?? record.source_count ?? 0),
    compactedAt: record.compactedAt ? String(record.compactedAt) : record.compacted_at ? String(record.compacted_at) : null,
    compactedReason: record.compactedReason ? String(record.compactedReason) : record.compacted_reason ? String(record.compacted_reason) : null,
    memoryMetadata: asRecord(record.memoryMetadata ?? record.memory_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeMemoryDisclosure(raw: unknown): PersonMemoryRecord["disclosure"] {
  const record = asRecord(raw);
  return {
    preview: record.preview ? String(record.preview) : undefined,
    operatorSummary: record.operatorSummary ? String(record.operatorSummary) : record.operator_summary ? String(record.operator_summary) : undefined,
    modelContext: record.modelContext ? String(record.modelContext) : record.model_context ? String(record.model_context) : undefined,
    tiers: asArray<Record<string, unknown>>(record.tiers),
  };
}

function normalizeApplicationConversationEntry(raw: unknown): ApplicationConversationEntry {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    applicationId:
      record.applicationId != null
        ? String(record.applicationId)
        : record.application_id != null
          ? String(record.application_id)
          : null,
    direction: String(record.direction ?? "system"),
    content: String(record.content ?? ""),
    messageType: String(record.messageType ?? record.message_type ?? "text"),
    platform: String(record.platform ?? "site"),
    metadata: asRecord(record.metadata),
    timestamp: record.timestamp ? String(record.timestamp) : null,
  };
}

function normalizeApplicationStageEvent(raw: unknown): ApplicationStageEventRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    applicationId: String(record.applicationId ?? record.application_id ?? ""),
    personId:
      record.personId != null ? String(record.personId) : record.person_id != null ? String(record.person_id) : null,
    eventType: String(record.eventType ?? record.event_type ?? "stage_transition"),
    fromStatus: record.fromStatus ? String(record.fromStatus) : record.from_status ? String(record.from_status) : null,
    toStatus: String(record.toStatus ?? record.to_status ?? ""),
    phaseKey: record.phaseKey ? String(record.phaseKey) : record.phase_key ? String(record.phase_key) : null,
    phaseLabel: record.phaseLabel ? String(record.phaseLabel) : record.phase_label ? String(record.phase_label) : null,
    stageKey: record.stageKey ? String(record.stageKey) : record.stage_key ? String(record.stage_key) : null,
    stageLabel: record.stageLabel ? String(record.stageLabel) : record.stage_label ? String(record.stage_label) : null,
    actor: record.actor ? String(record.actor) : null,
    source: String(record.source ?? "agent"),
    note: record.note ? String(record.note) : null,
    payload: asRecord(record.payload),
    occurredAt: record.occurredAt ? String(record.occurredAt) : record.occurred_at ? String(record.occurred_at) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeCandidateStatusTransition(raw: unknown): CandidateStatusTransition {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    candidateId: String(record.candidateId ?? record.candidate_id ?? ""),
    fromStatus: String(record.fromStatus ?? record.from_status ?? ""),
    toStatus: String(record.toStatus ?? record.to_status ?? ""),
    fromStatusLabel: String(record.fromStatusLabel ?? record.from_status_label ?? ""),
    toStatusLabel: String(record.toStatusLabel ?? record.to_status_label ?? ""),
    actor: String(record.actor ?? "system") as CandidateStatusTransition["actor"],
    actorId: record.actorId ? String(record.actorId) : record.actor_id ? String(record.actor_id) : undefined,
    trigger: String(record.trigger ?? ""),
    note: record.note ? String(record.note) : undefined,
    overrideReason: record.overrideReason ? String(record.overrideReason) : record.override_reason ? String(record.override_reason) : undefined,
    isOverride: Boolean(record.isOverride ?? record.is_override ?? false),
    milestoneUpdated:
      record.milestoneUpdated
        ? String(record.milestoneUpdated)
        : record.milestone_updated
          ? String(record.milestone_updated)
          : undefined,
    metadata: asRecord(record.metadata ?? record.transition_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
  };
}

function normalizeRecruitmentStateMachine(raw: unknown): RecruitmentStateMachine {
  const record = asRecord(raw);
  return {
    version: Number(record.version ?? 1),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
    updatedBy: String(record.updatedBy ?? record.updated_by ?? "system"),
    nodes: asArray<Record<string, unknown>>(record.nodes).map(
      (item) => item as unknown as RecruitmentStateMachine["nodes"][number],
    ),
    transitions: asArray<Record<string, unknown>>(record.transitions).map(
      (item) => item as unknown as RecruitmentStateMachine["transitions"][number],
    ),
    globalTransitions: asArray<Record<string, unknown>>(record.globalTransitions ?? record.global_transitions).map(
      (item) => item as unknown as RecruitmentStateMachine["globalTransitions"][number],
    ),
  };
}

function normalizeStateCriteriaOptimizationReport(raw: unknown): StateCriteriaOptimizationReport {
  const record = asRecord(raw);
  const metrics = asRecord(record.metrics);
  return {
    nodeId: String(record.nodeId ?? record.node_id ?? ""),
    nodeLabel: String(record.nodeLabel ?? record.node_label ?? ""),
    currentCriteriaRef: Object.keys(asRecord(record.currentCriteriaRef ?? record.current_criteria_ref)).length
      ? (asRecord(record.currentCriteriaRef ?? record.current_criteria_ref) as unknown as StateCriteriaOptimizationReport["currentCriteriaRef"])
      : undefined,
    currentSkillId: record.currentSkillId ? String(record.currentSkillId) : record.current_skill_id ? String(record.current_skill_id) : undefined,
    currentSkillName: record.currentSkillName ? String(record.currentSkillName) : record.current_skill_name ? String(record.current_skill_name) : undefined,
    metrics: {
      sampleSize: Number(metrics.sampleSize ?? metrics.sample_size ?? 0),
      aiDecisionCount: Number(metrics.aiDecisionCount ?? metrics.ai_decision_count ?? 0),
      recruiterOverrideCount: Number(metrics.recruiterOverrideCount ?? metrics.recruiter_override_count ?? 0),
      accuracyRate:
        metrics.accuracyRate != null || metrics.accuracy_rate != null
          ? Number(metrics.accuracyRate ?? metrics.accuracy_rate)
          : undefined,
      overrideRate:
        metrics.overrideRate != null || metrics.override_rate != null
          ? Number(metrics.overrideRate ?? metrics.override_rate)
          : undefined,
      deeperOverrideCount: Number(metrics.deeperOverrideCount ?? metrics.deeper_override_count ?? 0),
      shallowerOverrideCount: Number(metrics.shallowerOverrideCount ?? metrics.shallower_override_count ?? 0),
    },
    suggestions: asArray(record.suggestions).map((item) => {
      const suggestion = asRecord(item);
      return {
        kind: String(suggestion.kind ?? "adjust_threshold") as StateCriteriaOptimizationReport["suggestions"][number]["kind"],
        summary: String(suggestion.summary ?? ""),
        rationale: String(suggestion.rationale ?? ""),
        confidence: String(suggestion.confidence ?? "medium") as StateCriteriaOptimizationReport["suggestions"][number]["confidence"],
        proposedCriteriaRef: asRecord(
          suggestion.proposedCriteriaRef ?? suggestion.proposed_criteria_ref,
        ) as unknown as StateCriteriaOptimizationReport["suggestions"][number]["proposedCriteriaRef"],
        suggestedSkillId:
          suggestion.suggestedSkillId ? String(suggestion.suggestedSkillId) : suggestion.suggested_skill_id ? String(suggestion.suggested_skill_id) : undefined,
        suggestedSkillName:
          suggestion.suggestedSkillName ? String(suggestion.suggestedSkillName) : suggestion.suggested_skill_name ? String(suggestion.suggested_skill_name) : undefined,
      };
    }),
    summary: String(record.summary ?? ""),
  };
}

function normalizeRecruitmentStateMachineVersion(raw: unknown): RecruitmentStateMachineVersionRecord {
  const record = asRecord(raw);
  return {
    ...normalizeRecruitmentStateMachine(raw),
    changeSummary: record.changeSummary ? String(record.changeSummary) : record.change_summary ? String(record.change_summary) : null,
    versionMetadata: asRecord(record.versionMetadata ?? record.version_metadata),
    publishedAt: String(record.publishedAt ?? record.published_at ?? new Date().toISOString()),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
  };
}

function normalizeApplicationAssessment(raw: unknown): ApplicationAssessmentRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    applicationId: String(record.applicationId ?? record.application_id ?? ""),
    personId:
      record.personId != null ? String(record.personId) : record.person_id != null ? String(record.person_id) : null,
    assessmentType: String(record.assessmentType ?? record.assessment_type ?? "ai"),
    stageKey: record.stageKey ? String(record.stageKey) : record.stage_key ? String(record.stage_key) : null,
    status: String(record.status ?? "completed"),
    decision: record.decision ? String(record.decision) : null,
    score: record.score != null ? Number(record.score) : null,
    summary: record.summary ? String(record.summary) : null,
    evidenceRefs: asArray(record.evidenceRefs ?? record.evidence_refs),
    metadata: asRecord(record.metadata),
    createdBy: record.createdBy ? String(record.createdBy) : record.created_by ? String(record.created_by) : null,
    reviewedBy: record.reviewedBy ? String(record.reviewedBy) : record.reviewed_by ? String(record.reviewed_by) : null,
    reviewedAt: record.reviewedAt ? String(record.reviewedAt) : record.reviewed_at ? String(record.reviewed_at) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeApplicationAssignment(raw: unknown): ApplicationAssignmentRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    applicationId: String(record.applicationId ?? record.application_id ?? ""),
    personId:
      record.personId != null ? String(record.personId) : record.person_id != null ? String(record.person_id) : null,
    assignee: String(record.assignee ?? ""),
    ownerRole: String(record.ownerRole ?? record.owner_role ?? "operator"),
    status: String(record.status ?? "active"),
    note: record.note ? String(record.note) : null,
    assignmentMetadata: asRecord(record.assignmentMetadata ?? record.assignment_metadata ?? record.metadata),
    assignedAt: record.assignedAt ? String(record.assignedAt) : record.assigned_at ? String(record.assigned_at) : null,
    releasedAt: record.releasedAt ? String(record.releasedAt) : record.released_at ? String(record.released_at) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeResumeArtifact(raw: unknown): ResumeArtifactRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    applicationId: String(record.applicationId ?? record.application_id ?? ""),
    personId:
      record.personId != null ? String(record.personId) : record.person_id != null ? String(record.person_id) : null,
    source: String(record.source ?? "site"),
    artifactType: String(record.artifactType ?? record.artifact_type ?? "resume"),
    fileName: record.fileName ? String(record.fileName) : record.file_name ? String(record.file_name) : null,
    filePath: record.filePath ? String(record.filePath) : record.file_path ? String(record.file_path) : null,
    extractedText: record.extractedText ? String(record.extractedText) : record.extracted_text ? String(record.extracted_text) : null,
    contactSnapshot: asRecord(record.contactSnapshot ?? record.contact_snapshot),
    artifactMetadata: asRecord(record.artifactMetadata ?? record.artifact_metadata ?? record.metadata),
    capturedAt: record.capturedAt ? String(record.capturedAt) : record.captured_at ? String(record.captured_at) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeApplicationScorecard(raw: unknown): ApplicationScorecardRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    applicationId: String(record.applicationId ?? record.application_id ?? ""),
    personId:
      record.personId != null ? String(record.personId) : record.person_id != null ? String(record.person_id) : null,
    stageKey: record.stageKey ? String(record.stageKey) : record.stage_key ? String(record.stage_key) : null,
    source: String(record.source ?? "ai"),
    rubricVersion: String(record.rubricVersion ?? record.rubric_version ?? "recruit-scorecard-v1"),
    scoreTotal: record.scoreTotal != null ? Number(record.scoreTotal) : record.score_total != null ? Number(record.score_total) : null,
    verdict: record.verdict ? String(record.verdict) : null,
    summary: record.summary ? String(record.summary) : null,
    dimensionScores: asRecord(record.dimensionScores ?? record.dimension_scores),
    evidenceRefs: asArray(record.evidenceRefs ?? record.evidence_refs),
    scorecardMetadata: asRecord(record.scorecardMetadata ?? record.scorecard_metadata ?? record.metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeApplicationReviewDecision(raw: unknown): ApplicationReviewDecisionRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    applicationId: String(record.applicationId ?? record.application_id ?? ""),
    personId:
      record.personId != null ? String(record.personId) : record.person_id != null ? String(record.person_id) : null,
    stageKey: record.stageKey ? String(record.stageKey) : record.stage_key ? String(record.stage_key) : null,
    decision: String(record.decision ?? "review"),
    rationale: record.rationale ? String(record.rationale) : null,
    decisionSource: String(record.decisionSource ?? record.decision_source ?? "manual"),
    decidedBy: record.decidedBy ? String(record.decidedBy) : record.decided_by ? String(record.decided_by) : null,
    scorecardId: record.scorecardId ? String(record.scorecardId) : record.scorecard_id ? String(record.scorecard_id) : null,
    reviewMetadata: asRecord(record.reviewMetadata ?? record.review_metadata ?? record.metadata),
    decidedAt: record.decidedAt ? String(record.decidedAt) : record.decided_at ? String(record.decided_at) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeTalentPoolSyncRecord(raw: unknown): TalentPoolSyncRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    applicationId: String(record.applicationId ?? record.application_id ?? ""),
    personId:
      record.personId != null ? String(record.personId) : record.person_id != null ? String(record.person_id) : null,
    destination: String(record.destination ?? "talent_pool"),
    status: String(record.status ?? "pending"),
    externalRef: record.externalRef ? String(record.externalRef) : record.external_ref ? String(record.external_ref) : null,
    payloadSnapshot: asRecord(record.payloadSnapshot ?? record.payload_snapshot),
    errorMessage: record.errorMessage ? String(record.errorMessage) : record.error_message ? String(record.error_message) : null,
    syncedAt: record.syncedAt ? String(record.syncedAt) : record.synced_at ? String(record.synced_at) : null,
    lastAttemptedAt: record.lastAttemptedAt ? String(record.lastAttemptedAt) : record.last_attempted_at ? String(record.last_attempted_at) : null,
    syncMetadata: asRecord(record.syncMetadata ?? record.sync_metadata ?? record.metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeEvolutionArtifact(raw: unknown): EvolutionArtifactRecord {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    agentProfileId: record.agentProfileId ? String(record.agentProfileId) : record.agent_profile_id ? String(record.agent_profile_id) : null,
    artifactKind: String(record.artifactKind ?? record.artifact_kind ?? "playbook_patch") as EvolutionArtifactRecord["artifactKind"],
    title: String(record.title ?? ""),
    summary: record.summary ? String(record.summary) : null,
    status: String(record.status ?? "pending_review") as EvolutionArtifactRecord["status"],
    relatedCandidateId: record.relatedCandidateId ? String(record.relatedCandidateId) : record.related_candidate_id ? String(record.related_candidate_id) : null,
    relatedSkillId: record.relatedSkillId ? String(record.relatedSkillId) : record.related_skill_id ? String(record.related_skill_id) : null,
    proposedBy: record.proposedBy ? String(record.proposedBy) : record.proposed_by ? String(record.proposed_by) : null,
    reviewedBy: record.reviewedBy ? String(record.reviewedBy) : record.reviewed_by ? String(record.reviewed_by) : null,
    reviewedAt: record.reviewedAt ? String(record.reviewedAt) : record.reviewed_at ? String(record.reviewed_at) : null,
    appliedAt: record.appliedAt ? String(record.appliedAt) : record.applied_at ? String(record.applied_at) : null,
    artifactBody: asRecord(record.artifactBody ?? record.artifact_body),
    artifactMetadata: asRecord(record.artifactMetadata ?? record.artifact_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeApplicationThread(raw: unknown): ApplicationThreadRecord {
  const record = asRecord(raw);
  return {
    applicationId:
      record.applicationId != null
        ? String(record.applicationId)
        : record.application_id != null
          ? String(record.application_id)
          : null,
    personId:
      record.personId != null ? String(record.personId) : record.person_id != null ? String(record.person_id) : null,
    jobDescriptionId:
      record.jobDescriptionId != null
        ? String(record.jobDescriptionId)
        : record.job_description_id != null
          ? String(record.job_description_id)
          : null,
    application: normalizeApplicationRecord(record.application ?? {}),
    sessionStatus: String(record.sessionStatus ?? record.session_status ?? "active"),
    contextSummary: record.contextSummary ? String(record.contextSummary) : record.context_summary ? String(record.context_summary) : undefined,
    facts: asRecord(record.facts),
    recentMessages: asArray(record.recentMessages ?? record.recent_messages).map((item) => asRecord(item)),
    communicationLogs: asArray(record.communicationLogs ?? record.communication_logs).map(normalizeApplicationConversationEntry),
    stateSnapshot: normalizeApplicationStateSnapshot(record.stateSnapshot ?? record.state_snapshot),
    stageEvents: asArray(record.stageEvents ?? record.stage_events).map(normalizeApplicationStageEvent),
    statusTransitions: asArray(record.statusTransitions ?? record.status_transitions).map(normalizeCandidateStatusTransition),
    assessments: asArray(record.assessments).map(normalizeApplicationAssessment),
    assignments: asArray(record.assignments).map(normalizeApplicationAssignment),
    resumeArtifacts: asArray(record.resumeArtifacts ?? record.resume_artifacts).map(normalizeResumeArtifact),
    scorecards: asArray(record.scorecards).map(normalizeApplicationScorecard),
    reviewDecisions: asArray(record.reviewDecisions ?? record.review_decisions).map(normalizeApplicationReviewDecision),
    syncRecords: asArray(record.syncRecords ?? record.sync_records).map(normalizeTalentPoolSyncRecord),
    availableStatuses: asArray<string>(record.availableStatuses ?? record.available_statuses),
    runtimeApprovals: asArray(record.runtimeApprovals ?? record.runtime_approvals).map(normalizeApprovalItem),
    runtimeInteractions: asArray(record.runtimeInteractions ?? record.runtime_interactions).map(normalizeOperatorInteraction),
  };
}

function normalizeAgentRunResult(raw: unknown): AgentRunResult {
  const record = asRecord(raw);
  return {
    processed: Boolean(record.processed ?? false),
    status: String(record.status ?? "idle"),
    taskId: record.taskId ? String(record.taskId) : record.task_id ? String(record.task_id) : undefined,
    enqueuedFollowUps: Number(record.enqueuedFollowUps ?? record.enqueued_follow_ups ?? 0),
    error: record.error ? String(record.error) : null,
  };
}

function normalizeAgentTaskEnqueueResult(raw: unknown): AgentTaskEnqueueResult {
  const record = asRecord(raw);
  return {
    taskId: String(record.taskId ?? record.task_id ?? ""),
    taskType: String(record.taskType ?? record.task_type ?? ""),
    priority: Number(record.priority ?? 0),
    queueDepth: Number(record.queueDepth ?? record.queue_depth ?? 0),
  };
}

function normalizeDomainPack(raw: unknown): DomainPackRecord {
  const record = asRecord(raw);
  return {
    key: String(record.key ?? "general"),
    name: String(record.name ?? "General Automation"),
    description: String(record.description ?? ""),
    version: String(record.version ?? "1.0.0"),
    maturity: String(record.maturity ?? "experimental"),
    runtimeOnly: Boolean(record.runtimeOnly ?? record.runtime_only ?? true),
    defaultCapabilities: asArray<string>(record.defaultCapabilities ?? record.default_capabilities),
    sampleTasks: asArray<string>(record.sampleTasks ?? record.sample_tasks),
    defaultConstraints: asRecord(record.defaultConstraints ?? record.default_constraints),
    defaultOutputContract: asRecord(record.defaultOutputContract ?? record.default_output_contract),
    templateKeys: asArray<string>(record.templateKeys ?? record.template_keys),
    compilerHints: asArray<string>(record.compilerHints ?? record.compiler_hints),
    qualityGates: asRecord(record.qualityGates ?? record.quality_gates),
    sceneExpectations: asArray<string>(record.sceneExpectations ?? record.scene_expectations),
    trialExpectations: asRecord(record.trialExpectations ?? record.trial_expectations),
    templateCount: Number(record.templateCount ?? record.template_count ?? asArray(record.templateKeys ?? record.template_keys).length),
    activeTemplateCount: Number(record.activeTemplateCount ?? record.active_template_count ?? 0),
  };
}

function normalizeRuntimeCompilerContract(raw: unknown): RuntimeCompilerContract {
  const record = asRecord(raw);
  return {
    contractVersion: String(record.contractVersion ?? record.contract_version ?? "runtime-task-compiler-v3"),
    strategy: String(record.strategy ?? "llm_first_structured_semantic_compiler"),
    fallbackStrategy: String(record.fallbackStrategy ?? record.fallback_strategy ?? "none"),
    promptAsset: String(record.promptAsset ?? record.prompt_asset ?? "tasks/runtime_task_compiler.md"),
    requiredFields: asArray<string>(record.requiredFields ?? record.required_fields),
    optionalFields: asArray<string>(record.optionalFields ?? record.optional_fields),
    invariants: asArray<string>(record.invariants),
    qualityGates: asArray<string>(record.qualityGates ?? record.quality_gates),
    repairPolicy: asRecord(record.repairPolicy ?? record.repair_policy),
    availableDomains: asArray(record.availableDomains ?? record.available_domains).map(normalizeDomainPack),
    availableCapabilities: asArray(record.availableCapabilities ?? record.available_capabilities).map(normalizeRuntimeCapabilityDriver),
  };
}

function normalizeRuntimeTask(raw: unknown): RuntimeTaskSpec {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    title: String(record.title ?? "Untitled task"),
    description: record.description ? String(record.description) : null,
    goal: String(record.goal ?? ""),
    domain: String(record.domain ?? "general"),
    status: String(record.status ?? "draft"),
    sourceKind: String(record.sourceKind ?? record.source_kind ?? "natural_language"),
    sourceText: record.sourceText ? String(record.sourceText) : record.source_text ? String(record.source_text) : null,
    inputs: asRecord(record.inputs),
    constraints: asRecord(record.constraints),
    successCriteria: asRecord(record.successCriteria ?? record.success_criteria),
    approvalPolicy: asRecord(record.approvalPolicy ?? record.approval_policy),
    outputContract: asRecord(record.outputContract ?? record.output_contract),
    preferredCapabilities: asArray<string>(record.preferredCapabilities ?? record.preferred_capabilities),
    preferredDomains: asArray<string>(record.preferredDomains ?? record.preferred_domains),
    compiledPayload: asRecord(record.compiledPayload ?? record.compiled_payload),
    activePlanId: record.activePlanId ? String(record.activePlanId) : record.active_plan_id ? String(record.active_plan_id) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeRuntimePlan(raw: unknown): RuntimeWorkspaceData["plans"][number] {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    taskSpecId: String(record.taskSpecId ?? record.task_spec_id ?? ""),
    name: String(record.name ?? "Untitled plan"),
    mode: String(record.mode ?? "trial"),
    status: String(record.status ?? "draft"),
    version: Number(record.version ?? 1),
    approvalState: String(record.approvalState ?? record.approval_state ?? "unreviewed"),
    planBody: {
      steps: asArray<Record<string, unknown>>(asRecord(record.planBody ?? record.plan_body).steps),
      instruction: asRecord(record.planBody ?? record.plan_body).instruction
        ? String(asRecord(record.planBody ?? record.plan_body).instruction)
        : undefined,
      domain: asRecord(record.planBody ?? record.plan_body).domain
        ? String(asRecord(record.planBody ?? record.plan_body).domain)
        : undefined,
    },
    environmentRequirements: asRecord(record.environmentRequirements ?? record.environment_requirements),
    checkpoints: asArray<Record<string, unknown>>(record.checkpoints),
    runtimeMetadata: asRecord(record.runtimeMetadata ?? record.runtime_metadata),
    compiledFromPatchId: record.compiledFromPatchId ? String(record.compiledFromPatchId) : record.compiled_from_patch_id ? String(record.compiled_from_patch_id) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeRuntimeEpisode(raw: unknown): RuntimeEpisode {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    taskSpecId: String(record.taskSpecId ?? record.task_spec_id ?? ""),
    executionPlanId: String(record.executionPlanId ?? record.execution_plan_id ?? ""),
    mode: String(record.mode ?? "trial"),
    status: String(record.status ?? "pending"),
    requestedBy: record.requestedBy ? String(record.requestedBy) : record.requested_by ? String(record.requested_by) : null,
    requiresConfirmation: Boolean(record.requiresConfirmation ?? record.requires_confirmation ?? true),
    startedAt: record.startedAt ? String(record.startedAt) : record.started_at ? String(record.started_at) : null,
    finishedAt: record.finishedAt ? String(record.finishedAt) : record.finished_at ? String(record.finished_at) : null,
    resultSummary: record.resultSummary ? String(record.resultSummary) : record.result_summary ? String(record.result_summary) : null,
    observations: asArray<Record<string, unknown>>(record.observations),
    actions: asArray<Record<string, unknown>>(record.actions),
    metrics: asRecord(record.metrics),
    divergenceDetected: Boolean(record.divergenceDetected ?? record.divergence_detected ?? false),
    patchId: record.patchId ? String(record.patchId) : record.patch_id ? String(record.patch_id) : null,
    runtimeMetadata: asRecord(record.runtimeMetadata ?? record.runtime_metadata),
    lastError: record.lastError ? String(record.lastError) : record.last_error ? String(record.last_error) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeRuntimeSnapshot(raw: unknown): RuntimeSnapshot {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    taskSpecId: record.taskSpecId ? String(record.taskSpecId) : record.task_spec_id ? String(record.task_spec_id) : null,
    executionPlanId: record.executionPlanId ? String(record.executionPlanId) : record.execution_plan_id ? String(record.execution_plan_id) : null,
    executionEpisodeId: record.executionEpisodeId ? String(record.executionEpisodeId) : record.execution_episode_id ? String(record.execution_episode_id) : null,
    source: String(record.source ?? "browser"),
    environmentKey: record.environmentKey ? String(record.environmentKey) : record.environment_key ? String(record.environment_key) : null,
    status: String(record.status ?? "observed"),
    url: record.url ? String(record.url) : null,
    title: record.title ? String(record.title) : null,
    pageType: record.pageType ? String(record.pageType) : record.page_type ? String(record.page_type) : null,
    capabilityHints: asArray<string>(record.capabilityHints ?? record.capability_hints),
    observedEntities: asArray<Record<string, unknown>>(record.observedEntities ?? record.observed_entities),
    affordances: asArray<Record<string, unknown>>(record.affordances),
    runtimeMetadata: asRecord(record.runtimeMetadata ?? record.runtime_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeRuntimeCapabilityDriver(raw: unknown): RuntimeCapabilityDriver {
  const record = asRecord(raw);
  const supportedDomains = asArray<string>(record.supportedDomains ?? record.supported_domains);
  const requiresSupervision = Boolean(record.requiresSupervision ?? record.requires_supervision ?? false);
  const supportsWrite = Boolean(record.supportsWrite ?? record.supports_write ?? record.writesState ?? record.writes_state ?? false);
  const key = String(record.key ?? record.driver_key ?? "");
  return {
    id: String(record.id ?? key),
    key,
    name: String(record.name ?? humanizeKey(key || "capability driver")),
    category: String(record.category ?? record.kind ?? record.risk ?? "general"),
    status: String(record.status ?? "ready"),
    scope: String(record.scope ?? (supportedDomains.length ? supportedDomains.join(", ") : "general")),
    description: String(record.description ?? ""),
    safetyMode: String(record.safetyMode ?? record.safety_mode ?? (requiresSupervision ? "supervised" : "self-serve")),
    supportsWrite,
    sceneTypes: asArray<string>(
      record.sceneTypes ?? record.scene_types ?? record.recommendedSceneTypes ?? record.recommended_scene_types,
    ),
    signalLabels: asArray<string>(record.signalLabels ?? record.signal_labels ?? record.auditTags ?? record.audit_tags),
    supportedDomains,
    requiresSupervision,
    executorMode: record.executorMode ? String(record.executorMode) : record.executor_mode ? String(record.executor_mode) : undefined,
    replanOnError:
      record.replanOnError !== undefined
        ? Boolean(record.replanOnError)
        : record.replan_on_error !== undefined
          ? Boolean(record.replan_on_error)
          : undefined,
    sceneRequired:
      record.sceneRequired !== undefined
        ? Boolean(record.sceneRequired)
        : record.scene_required !== undefined
          ? Boolean(record.scene_required)
          : undefined,
    preferredTools: asArray<string>(record.preferredTools ?? record.preferred_tools),
    checkpointPolicy: asRecord(record.checkpointPolicy ?? record.checkpoint_policy),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeRuntimePlanLaunchResult(raw: unknown): RuntimePlanLaunchResult {
  const record = asRecord(raw);
  return {
    taskId: String(record.taskId ?? record.task_id ?? ""),
    taskType: String(record.taskType ?? record.task_type ?? ""),
    priority: Number(record.priority ?? 0),
    queueDepth: Number(record.queueDepth ?? record.queue_depth ?? 0),
    taskSpecId: String(record.taskSpecId ?? record.task_spec_id ?? ""),
    executionPlanId: String(record.executionPlanId ?? record.execution_plan_id ?? ""),
    executionEpisode: normalizeRuntimeEpisode(record.executionEpisode ?? record.execution_episode),
  };
}

function normalizeRuntimeEnvironmentAssessment(raw: unknown): RuntimeEnvironmentAssessment {
  const record = asRecord(raw);
  const snapshot = asRecord(record.snapshot);
  const taskSpec = asRecord(record.taskSpec ?? record.task_spec);
  const executionPlan = asRecord(record.executionPlan ?? record.execution_plan);
  const executionEpisode = asRecord(record.executionEpisode ?? record.execution_episode);
  const blockers = asArray<string>(record.blockers);
  const assessmentNotes = asArray<string>(record.assessmentNotes ?? record.assessment_notes);
  const checkpoints = asArray<Record<string, unknown>>(record.checkpoints);
  const environmentRequirements = asRecord(record.environmentRequirements ?? record.environment_requirements);
  const sceneType = String(record.sceneType ?? record.scene_type ?? snapshot.pageType ?? snapshot.page_type ?? "unknown");
  const sceneKey = String(record.sceneKey ?? record.scene_key ?? snapshot.environmentKey ?? snapshot.environment_key ?? "runtime");
  const normalizedObservedEntities = asArray<Record<string, unknown>>(record.observedEntities ?? record.observed_entities).map((entity) => ({
    kind: String(entity.kind ?? entity.type ?? "entity"),
    label: String(entity.label ?? entity.name ?? entity.text ?? "Observed entity"),
    entityId: entity.entityId ? String(entity.entityId) : entity.entity_id ? String(entity.entity_id) : entity.id ? String(entity.id) : null,
    role: entity.role ? String(entity.role) : null,
    confidence: typeof entity.confidence === "number" ? entity.confidence : null,
    state: entity.state ? String(entity.state) : null,
    interactive: Boolean(entity.interactive ?? entity.clickable ?? false),
    signals: asArray<string>(entity.signals),
    locator: asRecord(entity.locator),
    attributes: asRecord(entity.attributes),
  }));
  const normalizedAffordances = asArray<Record<string, unknown>>(record.affordances).map((affordance) => ({
    kind: String(affordance.kind ?? affordance.type ?? "action"),
    label: String(affordance.label ?? affordance.name ?? affordance.text ?? "Affordance"),
    action: String(affordance.action ?? affordance.intent ?? affordance.kind ?? "inspect"),
    target: affordance.target ? String(affordance.target) : affordance.href ? String(affordance.href) : null,
    confidence: typeof affordance.confidence === "number" ? affordance.confidence : null,
    enabled: Boolean(affordance.enabled ?? true),
    requiresConfirmation: Boolean(affordance.requiresConfirmation ?? affordance.requires_confirmation ?? false),
    signals: asArray<string>(affordance.signals),
    locator: asRecord(affordance.locator),
    metadata: asRecord(affordance.metadata),
  }));
  const observedLabels = normalizedObservedEntities.map((entity) => entity.label).filter((item): item is string => Boolean(item));
  const affordanceLabels = normalizedAffordances.map((affordance) => affordance.label).filter((item): item is string => Boolean(item));
  const recommendedActions = [
    ...checkpoints
      .map((item) => labelFromSignal(item))
      .filter((item): item is string => Boolean(item)),
    ...assessmentNotes,
  ];
  const sceneProfileRecord = asRecord(record.sceneProfile ?? record.scene_profile);
  const plannerGuidanceRecord = asRecord(record.plannerGuidance ?? record.planner_guidance);
  return {
    id: String(record.id ?? snapshot.id ?? `${sceneKey}:${sceneType}`),
    taskSpecId: taskSpec.id ? String(taskSpec.id) : record.taskSpecId ? String(record.taskSpecId) : record.task_spec_id ? String(record.task_spec_id) : null,
    executionPlanId:
      executionPlan.id
        ? String(executionPlan.id)
        : record.executionPlanId
          ? String(record.executionPlanId)
          : record.execution_plan_id
            ? String(record.execution_plan_id)
            : null,
    executionEpisodeId:
      executionEpisode.id
        ? String(executionEpisode.id)
        : record.executionEpisodeId
          ? String(record.executionEpisodeId)
          : record.execution_episode_id
            ? String(record.execution_episode_id)
            : null,
    snapshotId: snapshot.id ? String(snapshot.id) : record.snapshotId ? String(record.snapshotId) : record.snapshot_id ? String(record.snapshot_id) : null,
    environmentKey: sceneKey,
    sceneLabel: String(record.sceneLabel ?? record.scene_label ?? snapshot.title ?? humanizeKey(sceneType)),
    sceneType,
    status: String(record.status ?? record.planFit ?? record.plan_fit ?? "observed"),
    confidence: Number(record.confidence ?? 0),
    summary: String(
      record.summary ??
        record.detail ??
        assessmentNotes[0] ??
        (blockers.length ? `Detected ${blockers.join(", ")}.` : `Assessed scene ${sceneType}.`),
    ),
    observedEntities: normalizedObservedEntities,
    affordances: normalizedAffordances,
    sceneProfile: {
      source: String(sceneProfileRecord.source ?? snapshot.source ?? "runtime"),
      sceneType: String(sceneProfileRecord.sceneType ?? sceneProfileRecord.scene_type ?? sceneType),
      interactionMode: String(sceneProfileRecord.interactionMode ?? sceneProfileRecord.interaction_mode ?? "inspect"),
      volatility: String(sceneProfileRecord.volatility ?? "medium"),
      authState: String(sceneProfileRecord.authState ?? sceneProfileRecord.auth_state ?? "unknown"),
      entityCount: Number(sceneProfileRecord.entityCount ?? sceneProfileRecord.entity_count ?? normalizedObservedEntities.length),
      affordanceCount: Number(sceneProfileRecord.affordanceCount ?? sceneProfileRecord.affordance_count ?? normalizedAffordances.length),
      primaryTargets: asArray<string>(sceneProfileRecord.primaryTargets ?? sceneProfileRecord.primary_targets),
      signals: asArray<string>(sceneProfileRecord.signals),
      blockers: asArray<string>(sceneProfileRecord.blockers ?? blockers),
      evidence: asRecord(sceneProfileRecord.evidence),
    },
    plannerGuidance: {
      posture: String(plannerGuidanceRecord.posture ?? "advance"),
      requiredCapabilities: asArray<string>(plannerGuidanceRecord.requiredCapabilities ?? plannerGuidanceRecord.required_capabilities),
      insertedCapabilities: asArray<string>(plannerGuidanceRecord.insertedCapabilities ?? plannerGuidanceRecord.inserted_capabilities),
      preferredNextActions: asArray<string>(plannerGuidanceRecord.preferredNextActions ?? plannerGuidanceRecord.preferred_next_actions),
      requiresSceneAssessment: Boolean(plannerGuidanceRecord.requiresSceneAssessment ?? plannerGuidanceRecord.requires_scene_assessment ?? false),
      requiresHumanReview: Boolean(plannerGuidanceRecord.requiresHumanReview ?? plannerGuidanceRecord.requires_human_review ?? false),
      shouldCheckpoint: Boolean(plannerGuidanceRecord.shouldCheckpoint ?? plannerGuidanceRecord.should_checkpoint ?? true),
      rationale: asArray<string>(plannerGuidanceRecord.rationale),
    },
    capabilityKeys: asArray<string>(
      record.capabilityKeys ?? record.capability_keys ?? record.recommendedCapabilities ?? record.recommended_capabilities,
    ),
    observedLabels,
    affordanceLabels,
    driftSignals: asArray<string>(record.driftSignals ?? record.drift_signals ?? blockers),
    recommendedActions,
    checkpoints,
    environmentRequirements,
    notes: assessmentNotes,
    auditMetadata: asRecord(record.auditMetadata ?? record.audit_metadata),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeRuntimeTemplate(raw: unknown): RuntimeTemplate {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    templateKey: String(record.templateKey ?? record.template_key ?? ""),
    name: String(record.name ?? "Unnamed template"),
    domain: String(record.domain ?? "general"),
    status: String(record.status ?? "draft"),
    version: Number(record.version ?? 1),
    sourceTaskSpecId: record.sourceTaskSpecId ? String(record.sourceTaskSpecId) : record.source_task_spec_id ? String(record.source_task_spec_id) : null,
    templateBody: asRecord(record.templateBody ?? record.template_body),
    activationStrategy: asRecord(record.activationStrategy ?? record.activation_strategy),
    validationSummary: record.validationSummary ? String(record.validationSummary) : record.validation_summary ? String(record.validation_summary) : null,
    lastValidatedAt: record.lastValidatedAt ? String(record.lastValidatedAt) : record.last_validated_at ? String(record.last_validated_at) : null,
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeRuntimePatch(raw: unknown): RuntimePatch {
  const record = asRecord(raw);
  return {
    id: String(record.id ?? ""),
    title: String(record.title ?? ""),
    patchKind: String(record.patchKind ?? record.patch_kind ?? "execution_divergence"),
    status: String(record.status ?? "pending_review"),
    templateId: record.templateId ? String(record.templateId) : record.template_id ? String(record.template_id) : null,
    taskSpecId: record.taskSpecId ? String(record.taskSpecId) : record.task_spec_id ? String(record.task_spec_id) : null,
    executionPlanId: record.executionPlanId ? String(record.executionPlanId) : record.execution_plan_id ? String(record.execution_plan_id) : null,
    executionEpisodeId: record.executionEpisodeId ? String(record.executionEpisodeId) : record.execution_episode_id ? String(record.execution_episode_id) : null,
    proposedBy: record.proposedBy ? String(record.proposedBy) : record.proposed_by ? String(record.proposed_by) : null,
    reviewedBy: record.reviewedBy ? String(record.reviewedBy) : record.reviewed_by ? String(record.reviewed_by) : null,
    reviewedAt: record.reviewedAt ? String(record.reviewedAt) : record.reviewed_at ? String(record.reviewed_at) : null,
    appliedAt: record.appliedAt ? String(record.appliedAt) : record.applied_at ? String(record.applied_at) : null,
    divergenceSummary: record.divergenceSummary ? String(record.divergenceSummary) : record.divergence_summary ? String(record.divergence_summary) : null,
    rationale: record.rationale ? String(record.rationale) : record.reason ? String(record.reason) : null,
    patchBody: asRecord(record.patchBody ?? record.patch_body),
    runtimeMetadata: asRecord(record.runtimeMetadata ?? record.runtime_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeRuntimeReplanResult(raw: unknown): RuntimePlanReplanResult {
  const record = asRecord(raw);
  const executionPlan = normalizeRuntimePlan(record.executionPlan ?? record.execution_plan);
  const previousPlan = asRecord(record.previousPlan ?? record.previous_plan);
  const environmentAssessment =
    record.environmentAssessment ?? record.environment_assessment ?? record.assessment
      ? normalizeRuntimeEnvironmentAssessment(record.environmentAssessment ?? record.environment_assessment ?? record.assessment)
      : null;
  const runtimeMetadata = asRecord(executionPlan.runtimeMetadata);
  return {
    id: String(record.id ?? executionPlan.id),
    taskSpecId:
      executionPlan.taskSpecId ||
      (record.taskSpecId ? String(record.taskSpecId) : record.task_spec_id ? String(record.task_spec_id) : null),
    baseExecutionPlanId: String(
      record.baseExecutionPlanId ??
        record.base_execution_plan_id ??
        previousPlan.id ??
        runtimeMetadata.replanned_from_plan_id ??
        "",
    ),
    executionPlan,
    status: String(record.status ?? executionPlan.status ?? "proposed"),
    trigger: String(record.trigger ?? asRecord(runtimeMetadata.replan_assessment).plan_fit ?? "replanned"),
    summary: String(
      record.summary ??
        record.detail ??
        runtimeMetadata.replan_reason ??
        environmentAssessment?.summary ??
        "已根据最新运行时场景生成新的计划修订。",
    ),
    compilerNotes: asArray<string>(record.compilerNotes ?? record.compiler_notes),
    recommendedCapabilityKeys: asArray<string>(
      record.recommendedCapabilityKeys ??
        record.recommended_capability_keys ??
        environmentAssessment?.capabilityKeys,
    ),
    environmentAssessment,
    patch: record.patch ? normalizeRuntimePatch(record.patch) : null,
    auditMetadata: asRecord(record.auditMetadata ?? record.audit_metadata),
    createdAt: String(record.createdAt ?? record.created_at ?? new Date().toISOString()),
  };
}

function normalizeRuntimeLearningOutcome(raw: unknown): RuntimeLearningOutcome {
  const record = asRecord(raw);
  const approval = asRecord(record.approval);
  const templateApproval = asRecord(record.templateApproval ?? record.template_approval);
  const learningDraft = asRecord(record.learningDraft ?? record.learning_draft);
  return {
    episode: normalizeRuntimeEpisode(record.episode),
    template: record.template ? normalizeRuntimeTemplate(record.template) : null,
    patch: record.patch ? normalizeRuntimePatch(record.patch) : null,
    learningDraft: Object.keys(learningDraft).length
      ? {
          id: String(learningDraft.id ?? ""),
          content: String(learningDraft.content ?? ""),
          tags: asArray<string>(learningDraft.tags),
          sourceTaskId: learningDraft.sourceTaskId ? String(learningDraft.sourceTaskId) : learningDraft.source_task_id ? String(learningDraft.source_task_id) : null,
          consolidatedAt: learningDraft.consolidatedAt ? String(learningDraft.consolidatedAt) : learningDraft.consolidated_at ? String(learningDraft.consolidated_at) : null,
          isActive: Boolean(learningDraft.isActive ?? learningDraft.is_active ?? true),
          createdAt: String(learningDraft.createdAt ?? learningDraft.created_at ?? new Date().toISOString()),
          updatedAt: String(learningDraft.updatedAt ?? learningDraft.updated_at ?? new Date().toISOString()),
        }
      : null,
    approval: Object.keys(approval).length
      ? {
          id: String(approval.id ?? ""),
          targetType: String(approval.targetType ?? approval.target_type ?? ""),
          targetId: String(approval.targetId ?? approval.target_id ?? ""),
          title: String(approval.title ?? ""),
          status: String(approval.status ?? "pending"),
          requestedBy: approval.requestedBy ? String(approval.requestedBy) : approval.requested_by ? String(approval.requested_by) : null,
        }
      : null,
    templateApproval: Object.keys(templateApproval).length
      ? {
          id: String(templateApproval.id ?? ""),
          targetType: String(templateApproval.targetType ?? templateApproval.target_type ?? ""),
          targetId: String(templateApproval.targetId ?? templateApproval.target_id ?? ""),
          title: String(templateApproval.title ?? ""),
          status: String(templateApproval.status ?? "pending"),
          requestedBy: templateApproval.requestedBy
            ? String(templateApproval.requestedBy)
            : templateApproval.requested_by
              ? String(templateApproval.requested_by)
              : null,
          reviewedBy: templateApproval.reviewedBy
            ? String(templateApproval.reviewedBy)
            : templateApproval.reviewed_by
              ? String(templateApproval.reviewed_by)
              : null,
          reviewedAt: templateApproval.reviewedAt
            ? String(templateApproval.reviewedAt)
            : templateApproval.reviewed_at
              ? String(templateApproval.reviewed_at)
              : null,
          payload: asRecord(templateApproval.payload),
          notes: templateApproval.notes ? String(templateApproval.notes) : null,
          createdAt: templateApproval.createdAt
            ? String(templateApproval.createdAt)
            : templateApproval.created_at
              ? String(templateApproval.created_at)
              : undefined,
          updatedAt: templateApproval.updatedAt
            ? String(templateApproval.updatedAt)
            : templateApproval.updated_at
              ? String(templateApproval.updated_at)
              : undefined,
        }
      : null,
    skillHealth: record.skillHealth ? asRecord(record.skillHealth) : record.skill_health ? asRecord(record.skill_health) : null,
  };
}

function toneFromStatus(value: string): "positive" | "neutral" | "warning" | "critical" {
  if (/(error|failed|diverg|drift|critical)/i.test(value)) {
    return "critical";
  }
  if (/(pending|review|await|warning)/i.test(value)) {
    return "warning";
  }
  if (/(active|ready|success|completed|confirmed|applied)/i.test(value)) {
    return "positive";
  }
  return "neutral";
}

function normalizeTimelineEvent(raw: unknown, fallbackId: string): AgentEvent & { tone: "positive" | "neutral" | "warning" | "critical" } {
  const record = asRecord(raw);
  const tone = String(record.tone ?? "");
  const level = String(record.level ?? "");
  const resolvedTone =
    tone === "positive" || tone === "warning" || tone === "critical" || tone === "neutral"
      ? tone
      : level === "success"
        ? "positive"
        : level === "warning"
          ? "warning"
          : level === "error"
            ? "critical"
            : "neutral";
  return {
    id: String(record.id ?? fallbackId),
    source: String(record.source ?? "runtime"),
    message: String(record.detail ?? record.message ?? record.label ?? "Runtime event"),
    at: String(record.at ?? new Date().toISOString()),
    level:
      resolvedTone === "critical"
        ? "error"
        : resolvedTone === "warning"
          ? "warning"
          : resolvedTone === "positive"
            ? "success"
            : "info",
    tone: resolvedTone,
  };
}

function normalizeRuntimeReplay(raw: unknown): RuntimeEpisodeReplay {
  const record = asRecord(raw);
  const replayRecord = asRecord(record.replay);
  const payload = Object.keys(replayRecord).length ? replayRecord : record;
  const approvals = asArray(payload.approvals)
    .map((approval) => normalizeRuntimeLearningOutcome({ episode: payload.episode ?? {}, approval }).approval)
    .filter((approval): approval is NonNullable<RuntimeEpisodeReplay["approval"]> => Boolean(approval));
  const timelineSource = asArray(payload.timeline).length ? asArray(payload.timeline) : asArray(payload.diagnostics);
  const diagnostics = timelineSource.map((event, index) => {
    const entry = asRecord(event);
    const toneValue = String(entry.tone ?? "");
    const tone =
      toneValue === "positive" || toneValue === "warning" || toneValue === "critical" || toneValue === "neutral"
        ? toneValue
        : toneFromStatus(String(entry.status ?? entry.kind ?? entry.detail ?? entry.title ?? entry.label ?? "runtime"));
    return {
      id: String(entry.id ?? entry.sequence ?? `diagnostic-${index}`),
      label: String(entry.label ?? entry.title ?? entry.kind ?? `Event ${index + 1}`),
      detail: String(entry.detail ?? entry.message ?? entry.status ?? "Runtime replay event."),
      at: String(entry.at ?? entry.occurred_at ?? new Date().toISOString()),
      tone,
    };
  });
  const diagnosticsRecord = asRecord(payload.diagnostics);
  const notes = asArray<string>(payload.notes);
  if (!notes.length && Object.keys(diagnosticsRecord).length) {
    const summaryParts = [
      diagnosticsRecord.domain ? `Domain ${String(diagnosticsRecord.domain)}` : null,
      diagnosticsRecord.status ? `status ${String(diagnosticsRecord.status)}` : null,
      diagnosticsRecord.snapshot_count !== undefined ? `${Number(diagnosticsRecord.snapshot_count)} snapshots` : null,
      diagnosticsRecord.action_count !== undefined ? `${Number(diagnosticsRecord.action_count)} actions` : null,
    ].filter((value): value is string => Boolean(value));
    if (summaryParts.length) {
      notes.push(summaryParts.join(" · "));
    }
    if (diagnosticsRecord.latest_error) {
      notes.push(`Latest error: ${String(diagnosticsRecord.latest_error)}`);
    }
    if (Number(diagnosticsRecord.pending_approval_count ?? 0) > 0) {
      notes.push(`${Number(diagnosticsRecord.pending_approval_count)} approvals are still pending review.`);
    }
  }
  return {
    episode: normalizeRuntimeEpisode(payload.episode ?? payload.executionEpisode ?? payload.execution_episode),
    taskSpec: payload.taskSpec ?? payload.task_spec ? normalizeRuntimeTask(payload.taskSpec ?? payload.task_spec) : null,
    executionPlan:
      payload.executionPlan ?? payload.execution_plan
        ? normalizeRuntimePlan(payload.executionPlan ?? payload.execution_plan)
        : null,
    snapshots: asArray(payload.snapshots).map(normalizeRuntimeSnapshot),
    patch: payload.patch ? normalizeRuntimePatch(payload.patch) : null,
    template: payload.template ? normalizeRuntimeTemplate(payload.template) : null,
    approval:
      approvals.find((approval) => approval.status === "pending") ??
      approvals[0] ??
      (payload.approval ? normalizeRuntimeLearningOutcome({ episode: payload.episode ?? {}, approval: payload.approval }).approval : null),
    diagnostics,
    notes,
  };
}

function normalizeSyncBacklogItem(raw: unknown): SyncBacklogItem {
  const record = asRecord(raw);
  const payload = asRecord(record.payload);
  const delivery = asRecord(payload.delivery);
  const body = asRecord(payload.body);
  const entityType = String(record.entityType ?? record.entity_type ?? record.item_type ?? record.kind ?? "sync_item");
  const entityId = record.entityId
    ? String(record.entityId)
    : record.entity_id
      ? String(record.entity_id)
      : record.item_id
        ? String(record.item_id)
        : null;
  return {
    id: String(record.id ?? ""),
    target: String(record.target ?? record.destination ?? asRecord(payload.target).kind ?? "intranet"),
    entityType,
    entityId,
    status: String(record.status ?? "pending"),
    attemptCount: Number(record.attemptCount ?? record.attempt_count ?? 0),
    protocolVersion: record.protocolVersion
      ? String(record.protocolVersion)
      : record.protocol_version
        ? String(record.protocol_version)
        : payload.protocol_version
          ? String(payload.protocol_version)
          : null,
    deliveryMode: record.deliveryMode
      ? String(record.deliveryMode)
      : record.delivery_mode
        ? String(record.delivery_mode)
        : delivery.mode
          ? String(delivery.mode)
          : null,
    lastAttemptedAt: record.lastAttemptedAt
      ? String(record.lastAttemptedAt)
      : record.last_attempted_at
        ? String(record.last_attempted_at)
        : delivery.last_attempt_at
          ? String(delivery.last_attempt_at)
          : null,
    nextAttemptAt: record.nextAttemptAt
      ? String(record.nextAttemptAt)
      : record.next_attempt_at
        ? String(record.next_attempt_at)
        : delivery.next_attempt_at
          ? String(delivery.next_attempt_at)
          : null,
    payloadSummary: record.payloadSummary
      ? String(record.payloadSummary)
      : record.payload_summary
        ? String(record.payload_summary)
        : record.summary
          ? String(record.summary)
          : body.summary
            ? String(body.summary)
            : body.status
              ? `${entityType} ${entityId ?? ""}`.trim() + ` · ${String(body.status)}`
              : entityId
                ? `${entityType} ${entityId}`
                : entityType,
    lastError: record.lastError
      ? String(record.lastError)
      : record.last_error
        ? String(record.last_error)
        : delivery.last_error
          ? String(delivery.last_error)
          : null,
    payload,
    targetMetadata: asRecord(payload.target),
    updatedAt: String(record.updatedAt ?? record.updated_at ?? new Date().toISOString()),
  };
}

function normalizeSyncStatus(raw: unknown): SyncStatusSnapshot {
  const record = asRecord(raw);
  const remoteAvailable = Boolean(record.remoteAvailable ?? record.remote_available ?? false);
  const enabled = Boolean(record.enabled ?? record.sync_enabled ?? false);
  const modeValue = String(record.mode ?? (enabled ? (remoteAvailable ? "remote_ready" : "remote_unavailable") : "local_only"));
  const recentErrors = asArray<string>(record.recentErrors ?? record.recent_errors);
  if (!recentErrors.length && record.latest_error) {
    recentErrors.push(String(record.latest_error));
  }
  return {
    enabled,
    mode:
      modeValue === "remote_ready" || modeValue === "remote_unavailable" || modeValue === "local_only"
        ? modeValue
        : enabled
          ? remoteAvailable
            ? "remote_ready"
            : "remote_unavailable"
          : "local_only",
    remoteAvailable,
    protocolVersion: record.protocolVersion ? String(record.protocolVersion) : record.protocol_version ? String(record.protocol_version) : null,
    source: record.source ? String(record.source) : null,
    target: asRecord(record.target),
    pendingCount: Number(record.pendingCount ?? record.pending_count ?? 0),
    syncedCount: Number(record.syncedCount ?? record.synced_count ?? 0),
    failedDeliveryCount: Number(record.failedDeliveryCount ?? record.failed_delivery_count ?? 0),
    deferredCount: Number(record.deferredCount ?? record.deferred_count ?? 0),
    backlogTotal: Number(record.backlogTotal ?? record.backlog_total ?? 0),
    lastAttemptAt: record.lastAttemptAt ? String(record.lastAttemptAt) : record.last_attempt_at ? String(record.last_attempt_at) : null,
    lastSuccessAt: record.lastSuccessAt ? String(record.lastSuccessAt) : record.last_success_at ? String(record.last_success_at) : null,
    latestError: record.latestError ? String(record.latestError) : record.latest_error ? String(record.latest_error) : null,
    nextAttemptAt: record.nextAttemptAt ? String(record.nextAttemptAt) : record.next_attempt_at ? String(record.next_attempt_at) : null,
    byStatus: Object.fromEntries(
      Object.entries(asRecord(record.byStatus ?? record.by_status)).map(([key, value]) => [key, Number(value ?? 0)]),
    ),
    recentErrors,
  };
}

function normalizeSyncFlushResult(raw: unknown): SyncFlushResult {
  const record = asRecord(raw);
  return {
    attempted: Number(record.attempted ?? record.total_attempted ?? 0),
    synced: Number(record.synced ?? record.succeeded ?? record.flushed ?? 0),
    failed: Number(record.failed ?? 0),
    remoteAvailable: Boolean(record.remoteAvailable ?? record.remote_available ?? false),
    message: String(record.message ?? "Sync flush finished."),
  };
}

function normalizeCompileTaskResponse(raw: unknown): CompileTaskResponse {
  const record = asRecord(raw);
  return {
    domainPack: normalizeDomainPack(record.domainPack ?? record.domain_pack),
    compilerNotes: asArray<string>(record.compilerNotes ?? record.compiler_notes),
    taskSpec: normalizeRuntimeTask(record.taskSpec ?? record.task_spec),
    executionPlan: record.executionPlan ?? record.execution_plan ? normalizeRuntimePlan(record.executionPlan ?? record.execution_plan) : null,
  };
}

function resolveWebSocketUrl(baseUrl: string): string {
  const url = new URL(baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/agent-stream";
  url.search = "";
  return url.toString();
}

const recruitAgentExecutionApiBase = "/api/recruit-agent/execution";

async function requestRuntimeReplay(baseUrl: string, episodeId: string): Promise<RuntimeEpisodeReplay> {
  return normalizeRuntimeReplay(await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/runs/${episodeId}/replay`));
}

function createFetchClient(baseUrl: string): DesktopApiClient {
  return {
    getDashboardSummary: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")),
    getRuntimeWorkspaceData: async () => {
      const [compilerContract, domainPacks, taskSpecs, plans, episodes, snapshots, capabilityDrivers, environmentAssessments, templates, patches, replans] =
        await Promise.all([
        requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/compiler-contract`),
        requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/profiles`),
        requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/playbooks`),
        requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/plans`),
        requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/runs`),
        requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/snapshots`),
        requestOptionalJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/capabilities`),
        requestOptionalJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/environment-assessments`),
        requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/playbook-versions`),
        requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/adjustments`),
        requestOptionalJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/replans`),
      ]);
      return {
        compilerContract: normalizeRuntimeCompilerContract(compilerContract),
        domainPacks: asArray(domainPacks).map(normalizeDomainPack),
        taskSpecs: asArray(taskSpecs).map(normalizeRuntimeTask),
        plans: asArray(plans).map(normalizeRuntimePlan),
        episodes: asArray(episodes).map(normalizeRuntimeEpisode),
        snapshots: asArray(snapshots).map(normalizeRuntimeSnapshot),
        capabilityDrivers: capabilityDrivers ? asArray(capabilityDrivers).map(normalizeRuntimeCapabilityDriver) : [],
        environmentAssessments: environmentAssessments ? asArray(environmentAssessments).map(normalizeRuntimeEnvironmentAssessment) : [],
        templates: asArray(templates).map(normalizeRuntimeTemplate),
        patches: asArray(patches).map(normalizeRuntimePatch),
        replans: replans ? asArray(replans).map(normalizeRuntimeReplanResult) : [],
      };
    },
    getTaskCompilerContract: async () =>
      normalizeRuntimeCompilerContract(await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/compiler-contract`)),
    listDomainPacks: async () => asArray(await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/profiles`)).map(normalizeDomainPack),
    listRuntimeTasks: async () => asArray(await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/playbooks`)).map(normalizeRuntimeTask),
    compileRuntimeTask: async (payload) =>
      normalizeCompileTaskResponse(
        await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/playbooks/compile`, {
          method: "POST",
          body: JSON.stringify({
            instruction: payload.instruction,
            title: payload.title,
            description: payload.description,
            domain_hint: payload.domainHint,
            inputs: payload.inputs ?? {},
            constraints: payload.constraints ?? {},
            preferred_capabilities: payload.preferredCapabilities ?? [],
          }),
        }),
      ),
    listRuntimePlans: async () => asArray(await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/plans`)).map(normalizeRuntimePlan),
    launchRuntimePlan: async (planId, taskSpecId, mode = "production") =>
      normalizeRuntimePlanLaunchResult(
        await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/plans/${planId}/launch`, {
          method: "POST",
          body: JSON.stringify({
            task_spec_id: taskSpecId,
            requested_by: "desktop-user",
            mode,
            runtime_metadata: { launched_from: "desktop_control_plane" },
          }),
        }),
      ),
    createTrialRun: async (taskSpecId, executionPlanId, notes) =>
      normalizeRuntimeEpisode(
        await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/runs`, {
          method: "POST",
          body: JSON.stringify({
            task_spec_id: taskSpecId,
            execution_plan_id: executionPlanId,
            requested_by: "desktop-user",
            notes,
          }),
        }),
      ),
    listRuntimeEpisodes: async () => asArray(await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/runs`)).map(normalizeRuntimeEpisode),
    executeTrialRun: async (episodeId, notes) =>
      normalizeRuntimeLearningOutcome(
        await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/runs/${episodeId}/execute`, {
          method: "POST",
          body: JSON.stringify({
            operator: "desktop-user",
            notes,
            source: "desktop",
          }),
        }),
      ),
    refreshRuntimeLearning: async (episodeId) =>
      normalizeRuntimeLearningOutcome(
        await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/runs/${episodeId}/learn`, {
          method: "POST",
        }),
      ),
    confirmTrialRun: async (episodeId, reason) =>
      normalizeRuntimeLearningOutcome(
        await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/runs/${episodeId}/confirm`, {
          method: "POST",
          body: JSON.stringify({
            reviewer: "desktop-user",
            reason,
            activate_template: true,
          }),
        }),
      ),
    getRuntimeReplay: async (episodeId) => requestRuntimeReplay(baseUrl, episodeId),
    listRuntimeSnapshots: async () => asArray(await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/snapshots`)).map(normalizeRuntimeSnapshot),
    listCapabilityDrivers: async () => {
      const payload = await requestOptionalJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/capabilities`);
      return payload ? asArray(payload).map(normalizeRuntimeCapabilityDriver) : [];
    },
    listRuntimeEnvironmentAssessments: async () => {
      const payload = await requestOptionalJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/environment-assessments`);
      return payload ? asArray(payload).map(normalizeRuntimeEnvironmentAssessment) : [];
    },
    assessRuntimeEnvironment: async (payload) =>
      normalizeRuntimeEnvironmentAssessment(
        await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/environment-assessments`, {
          method: "POST",
          body: JSON.stringify({
            task_spec_id: payload.taskSpecId,
            execution_plan_id: payload.executionPlanId,
            execution_episode_id: payload.executionEpisodeId,
            environment_snapshot_id: payload.snapshotId,
            snapshot: payload.snapshot
              ? {
                  source: payload.snapshot.source ?? "browser",
                  environment_key: payload.snapshot.environmentKey,
                  status: payload.snapshot.status ?? "captured",
                  url: payload.snapshot.url,
                  title: payload.snapshot.title,
                  page_type: payload.snapshot.pageType,
                  capability_hints: payload.snapshot.capabilityHints ?? [],
                  observed_entities: payload.snapshot.observedEntities ?? [],
                  affordances: payload.snapshot.affordances ?? [],
                  runtime_metadata: payload.snapshot.runtimeMetadata ?? {},
                }
              : undefined,
            compiler_payload: payload.compilerPayload ?? {},
            plan_context: payload.planContext ?? {},
          }),
        }),
      ),
    listRuntimeTemplates: async () => asArray(await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/playbook-versions`)).map(normalizeRuntimeTemplate),
    listRuntimePatches: async () => asArray(await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/adjustments`)).map(normalizeRuntimePatch),
    listRuntimeReplans: async () => {
      const payload = await requestOptionalJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/replans`);
      return payload ? asArray(payload).map(normalizeRuntimeReplanResult) : [];
    },
    replanRuntimePlan: async (payload) =>
      normalizeRuntimeReplanResult(
        await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/plans/${payload.executionPlanId}/replan`, {
          method: "POST",
          body: JSON.stringify({
            task_spec_id: payload.taskSpecId,
            reason: payload.reason ?? payload.notes ?? payload.trigger,
            requested_by: payload.requestedBy ?? "desktop-user",
            execution_episode_id: payload.executionEpisodeId,
            environment_snapshot_id: payload.snapshotId,
            snapshot: payload.snapshot
              ? {
                  source: payload.snapshot.source ?? "browser",
                  environment_key: payload.snapshot.environmentKey,
                  status: payload.snapshot.status ?? "captured",
                  url: payload.snapshot.url,
                  title: payload.snapshot.title,
                  page_type: payload.snapshot.pageType,
                  capability_hints: payload.snapshot.capabilityHints ?? [],
                  observed_entities: payload.snapshot.observedEntities ?? [],
                  affordances: payload.snapshot.affordances ?? [],
                  runtime_metadata: payload.snapshot.runtimeMetadata ?? {},
                }
              : undefined,
            compiler_payload: {
              preferred_capabilities: payload.preferredCapabilityKeys ?? [],
              ...(payload.compilerPayload ?? {}),
            },
            plan_context: payload.planContext ?? {},
            runtime_metadata: payload.runtimeMetadata ?? {},
            checkpoints: payload.checkpoints ?? [],
            preserve_active_plan: payload.preserveActivePlan ?? true,
          }),
        }),
      ),
    approveRuntimePatch: async (id, reason) =>
      normalizeRuntimePatch(
        await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/adjustments/${id}/approve`, {
          method: "POST",
          body: JSON.stringify({ reviewer: "desktop-user", reason, apply_immediately: true }),
        }),
      ),
    rejectRuntimePatch: async (id, reason) =>
      normalizeRuntimePatch(
        await requestJson<unknown>(baseUrl, `${recruitAgentExecutionApiBase}/adjustments/${id}/reject`, {
          method: "POST",
          body: JSON.stringify({ reviewer: "desktop-user", reason }),
        }),
      ),
    getRecruitAgentProfile: async () => normalizeRecruitAgentProfile(await requestJson<unknown>(baseUrl, "/api/recruit-agent/profile")),
    updateRecruitAgentProfile: async (payload) =>
      normalizeRecruitAgentProfile(
        await requestJson<unknown>(baseUrl, "/api/recruit-agent/profile", {
          method: "PATCH",
          body: JSON.stringify({
            agent_key: payload.agentKey,
            name: payload.name,
            status: payload.status,
            description: payload.description,
            is_primary: payload.isPrimary,
            role_definition: payload.roleDefinition,
            prompt_config: payload.promptConfig,
            playbook_blueprint: payload.playbookBlueprint,
            memory_policy: payload.memoryPolicy,
            dashboard_config: payload.dashboardConfig,
            channel_config: payload.channelConfig,
            agent_metadata: payload.agentMetadata,
          }),
        }),
      ),
    listGoals: async () => asArray(await requestJson<unknown>(baseUrl, "/api/recruit-agent/goals")).map(normalizeGoalSpec),
    createGoal: async (payload) =>
      normalizeGoalSpec(
        await requestJson<unknown>(baseUrl, "/api/recruit-agent/goals", {
          method: "POST",
          body: JSON.stringify({
            title: payload.title,
            goal_text: payload.goalText,
            goal_kind: payload.goalKind ?? "recruiting",
            requested_by: payload.requestedBy ?? "desktop-user",
            constraints: payload.constraints ?? {},
            success_criteria: payload.successCriteria ?? {},
            context_hints: payload.contextHints ?? {},
            trial_budget: payload.trialBudget ?? {},
            run_preferences: payload.runPreferences ?? {},
            summary: payload.summary,
            priority: payload.priority ?? 100,
          }),
        }),
      ),
    listExecutionTraces: async (goalId) =>
      asArray(
        await requestJson<unknown>(
          baseUrl,
          `/api/recruit-agent/runtime/traces${goalId ? `?goal_id=${encodeURIComponent(goalId)}` : ""}`,
        ),
      ).map(normalizeExecutionTrace),
    listExecutionGraphs: async (goalId) =>
      asArray(
        await requestJson<unknown>(
          baseUrl,
          `/api/recruit-agent/runtime/graphs${goalId ? `?goal_id=${encodeURIComponent(goalId)}` : ""}`,
        ),
      ).map(normalizeExecutionGraph),
    listStrategyFragments: async () =>
      asArray(await requestJson<unknown>(baseUrl, "/api/recruit-agent/runtime/strategy-fragments")).map(normalizeStrategyFragment),
    listOperatorInteractions: async (candidateId) =>
      asArray(
        await requestJson<unknown>(
          baseUrl,
          `/api/recruit-agent/runtime/operator-interactions${candidateId ? `?candidate_id=${encodeURIComponent(candidateId)}` : ""}`,
        ),
      ).map(normalizeOperatorInteraction),
    resolveOperatorInteraction: async (interactionId, payload) =>
      normalizeOperatorInteraction(
        await requestJson<unknown>(baseUrl, `/api/recruit-agent/runtime/operator-interactions/${interactionId}/resolve`, {
          method: "POST",
          body: JSON.stringify({
            action: payload.action,
            comment: payload.comment,
            operator: payload.operator ?? "desktop-user",
            scope: payload.scope,
          }),
        }),
      ),
    listPersonMemories: async () =>
      asArray(await requestJson<unknown>(baseUrl, "/api/candidate-persons/memories")).map(normalizePersonMemory),
    getPersonMemory: async (personId) =>
      normalizePersonMemory(await requestJson<unknown>(baseUrl, `/api/candidate-persons/${personId}/memory`)),
    updatePersonMemory: async (personId, payload) =>
      normalizePersonMemory(
        await requestJson<unknown>(baseUrl, `/api/candidate-persons/${personId}/memory`, {
          method: "PATCH",
          body: JSON.stringify({
            status: payload.status,
            memory_schema_version: payload.memorySchemaVersion,
            summary: payload.summary,
            raw_content: payload.rawContent,
            content: payload.content,
            disclosure: payload.disclosure,
            token_estimate: payload.tokenEstimate,
            source_count: payload.sourceCount,
            memory_metadata: payload.memoryMetadata,
          }),
        }),
      ),
    compactPersonMemory: async (personId, reason, force = false) =>
      normalizePersonMemory(
        await requestJson<unknown>(baseUrl, `/api/candidate-persons/${personId}/memory/compact`, {
          method: "POST",
          body: JSON.stringify({ reason, force }),
        }),
      ),
    listJobMemories: async () =>
      asArray(await requestJson<unknown>(baseUrl, "/api/job-descriptions/memories")).map(normalizeJobMemory),
    getJobMemory: async (jobDescriptionId) =>
      normalizeJobMemory(await requestJson<unknown>(baseUrl, `/api/job-descriptions/${jobDescriptionId}/memory`)),
    updateJobMemory: async (jobDescriptionId, payload) =>
      normalizeJobMemory(
        await requestJson<unknown>(baseUrl, `/api/job-descriptions/${jobDescriptionId}/memory`, {
          method: "PATCH",
          body: JSON.stringify({
            status: payload.status,
            memory_schema_version: payload.memorySchemaVersion,
            summary: payload.summary,
            raw_content: payload.rawContent,
            content: payload.content,
            disclosure: payload.disclosure,
            token_estimate: payload.tokenEstimate,
            source_count: payload.sourceCount,
            memory_metadata: payload.memoryMetadata,
          }),
        }),
      ),
    compactJobMemory: async (jobDescriptionId, reason, force = false) =>
      normalizeJobMemory(
        await requestJson<unknown>(baseUrl, `/api/job-descriptions/${jobDescriptionId}/memory/compact`, {
          method: "POST",
          body: JSON.stringify({ reason, force }),
        }),
      ),
    getAgentGlobalMemory: async () =>
      normalizeAgentGlobalMemory(await requestJson<unknown>(baseUrl, "/api/recruit-agent/global-memory")),
    updateAgentGlobalMemory: async (payload) =>
      normalizeAgentGlobalMemory(
        await requestJson<unknown>(baseUrl, "/api/recruit-agent/global-memory", {
          method: "PATCH",
          body: JSON.stringify({
            status: payload.status,
            memory_schema_version: payload.memorySchemaVersion,
            summary: payload.summary,
            raw_content: payload.rawContent,
            content: payload.content,
            disclosure: payload.disclosure,
            token_estimate: payload.tokenEstimate,
            source_count: payload.sourceCount,
            memory_metadata: payload.memoryMetadata,
          }),
        }),
      ),
    compactAgentGlobalMemory: async (reason, force = false) =>
      normalizeAgentGlobalMemory(
        await requestJson<unknown>(baseUrl, "/api/recruit-agent/global-memory/compact", {
          method: "POST",
          body: JSON.stringify({ reason, force }),
        }),
      ),
    listApplicationThreads: async () =>
      asArray(await requestJson<unknown>(baseUrl, "/api/candidate-applications/threads")).map(normalizeApplicationThread),
    getApplicationThread: async (applicationId) =>
      normalizeApplicationThread(await requestJson<unknown>(baseUrl, `/api/candidate-applications/${applicationId}/thread`)),
    getStateMachine: async () =>
      normalizeRecruitmentStateMachine(await requestJson<unknown>(baseUrl, "/api/state-machine")),
    listStateMachineCriteriaSuggestions: async () =>
      asArray(await requestJson<unknown>(baseUrl, "/api/state-machine/criteria-suggestions")).map(
        normalizeStateCriteriaOptimizationReport,
      ),
    listStateMachineVersions: async (limit = 50) =>
      asArray(await requestJson<unknown>(baseUrl, `/api/state-machine/versions?limit=${limit}`)).map(
        normalizeRecruitmentStateMachineVersion,
      ),
    getStateMachineVersion: async (version) =>
      normalizeRecruitmentStateMachineVersion(await requestJson<unknown>(baseUrl, `/api/state-machine/versions/${version}`)),
    updateStateMachine: async (payload) =>
      normalizeRecruitmentStateMachine(
        await requestJson<unknown>(baseUrl, "/api/state-machine", {
          method: "PUT",
          body: JSON.stringify({
            updated_by: payload.updatedBy,
            change_summary: payload.changeSummary,
            nodes: payload.nodes,
            transitions: payload.transitions,
            global_transitions: payload.globalTransitions,
            version_metadata: payload.versionMetadata ?? {},
          }),
        }),
      ),
    listApplicationTransitions: async (applicationId) =>
      asArray(await requestJson<unknown>(baseUrl, `/api/candidate-applications/${applicationId}/transitions`)).map(
        normalizeCandidateStatusTransition,
      ),
    createApplicationEntry: async (applicationId, payload) =>
      normalizeApplicationConversationEntry(
        await requestJson<unknown>(baseUrl, `/api/candidate-applications/${applicationId}/entries`, {
          method: "POST",
          body: JSON.stringify({
            direction: payload.direction,
            content: payload.content,
            message_type: payload.messageType ?? "text",
            platform: payload.platform ?? "site",
            metadata: {},
          }),
        }),
      ),
    transitionApplicationState: async (applicationId, payload) =>
      normalizeApplicationThread(
        await requestJson<unknown>(baseUrl, `/api/candidate-applications/${applicationId}/transitions`, {
          method: "POST",
          body: JSON.stringify({
            to_status: payload.toStatus,
            phase_key: payload.phaseKey,
            phase_label: payload.phaseLabel,
            stage_key: payload.stageKey,
            stage_label: payload.stageLabel,
            note: payload.note,
            source: "operator",
            actor: payload.actor,
            actor_id: payload.actorId,
            trigger: payload.trigger,
            override_reason: "overrideReason" in payload ? payload.overrideReason : undefined,
            metadata: payload.metadata ?? {},
            interview_round: payload.interviewRound,
            contact_channels: payload.contactChannels ?? [],
          }),
        }),
      ),
    createApplicationAssessment: async (applicationId, payload) =>
      normalizeApplicationAssessment(
        await requestJson<unknown>(baseUrl, `/api/candidate-applications/${applicationId}/assessments`, {
          method: "POST",
          body: JSON.stringify({
            assessment_type: payload.assessmentType,
            stage_key: payload.stageKey,
            status: payload.status ?? "completed",
            decision: payload.decision,
            score: payload.score,
            summary: payload.summary,
            evidence_refs: payload.evidenceRefs ?? [],
            metadata: payload.metadata ?? {},
            created_by: payload.createdBy ?? "desktop-user",
            reviewed_by: payload.reviewedBy,
          }),
        }),
      ),
    listEvolutionArtifacts: async () =>
      asArray(await requestJson<unknown>(baseUrl, "/api/recruit-agent/evolution-artifacts")).map(normalizeEvolutionArtifact),
    updateEvolutionArtifact: async (artifactId, payload) =>
      normalizeEvolutionArtifact(
        await requestJson<unknown>(baseUrl, `/api/recruit-agent/evolution-artifacts/${artifactId}`, {
          method: "PATCH",
          body: JSON.stringify({
            summary: payload.summary,
            status: payload.status,
            reviewed_by: payload.reviewedBy,
            reviewed_at: payload.reviewedAt,
            applied_at: payload.appliedAt,
            artifact_body: payload.artifactBody,
            artifact_metadata: payload.artifactMetadata,
          }),
        }),
      ),
    getSyncStatus: async () => normalizeSyncStatus(await requestJson<unknown>(baseUrl, "/api/sync/status")),
    listSyncBacklog: async () => asArray(await requestJson<unknown>(baseUrl, "/api/sync/backlog")).map(normalizeSyncBacklogItem),
    flushSyncBacklog: async () =>
      normalizeSyncFlushResult(
        await requestJson<unknown>(baseUrl, "/api/sync/flush", {
          method: "POST",
          body: JSON.stringify({ initiated_by: "desktop-user" }),
        }),
      ),
    listApplications: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).applications,
    listPlaybooks: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).playbooks,
    listSkills: async () => asArray(await requestJson<unknown>(baseUrl, "/api/skills")).map(normalizeSkillRecord),
    updateSkill: async (skillId, payload) =>
      normalizeSkillRecord(
        await requestJson<unknown>(baseUrl, `/api/skills/${skillId}`, {
          method: "PATCH",
          body: JSON.stringify({
            skill_id: payload.skillId,
            name: payload.name,
            description: payload.description,
            category: payload.category,
            version: payload.version != null ? Number(payload.version) : undefined,
            status: payload.status,
            bound_to_stage: payload.boundStage,
            platform: payload.platform,
            input_schema: payload.inputSchema,
            output_schema: payload.outputSchema,
            strategy: payload.strategy,
            execution_hints: payload.executionHints,
            risk_level: payload.riskLevel,
            health_check_config: payload.healthCheckConfig,
            skill_metadata: payload.skillMetadata,
          }),
        }),
      ),
    deleteSkill: async (skillId) => {
      await requestVoid(baseUrl, `/api/skills/${skillId}`, { method: "DELETE" });
    },
    listApprovals: async () => asArray(await requestJson<unknown>(baseUrl, "/api/approvals")).map(normalizeApprovalItem),
    listMcpPresets: async () => asArray(await requestJson<unknown>(baseUrl, "/api/mcp/presets")).map(normalizeMcpPreset),
    listMcpServers: async () => asArray(await requestJson<unknown>(baseUrl, "/api/mcp/servers")).map(normalizeMcpServer),
    installMcpPreset: async (presetKey, payload) =>
      normalizeMcpServer(
        await requestJson<unknown>(baseUrl, `/api/mcp/presets/${encodeURIComponent(presetKey)}/install`, {
          method: "POST",
          body: JSON.stringify({
            server_key: payload?.serverKey,
            name: payload?.name,
            endpoint: payload?.endpoint,
          }),
        }),
      ),
    createMcpServer: async (payload) =>
      normalizeMcpServer(
        await requestJson<unknown>(baseUrl, "/api/mcp/servers", {
          method: "POST",
          body: JSON.stringify({
            server_key: payload.serverKey,
            name: payload.name,
            transport_kind: payload.transportKind,
            protocol: payload.protocol,
            endpoint: payload.endpoint,
            enabled: payload.enabled ?? true,
            preset_key: payload.presetKey,
            auth_config: payload.authConfig ?? {},
            server_metadata: payload.serverMetadata ?? {},
            tools: (payload.tools ?? []).map((tool) => ({
              name: tool.name,
              description: tool.description,
              parameters: tool.parameters ?? {},
              capabilities: tool.capabilities ?? [],
              enabled: tool.enabled ?? true,
              risk_level: tool.riskLevel ?? "medium",
              remote_name: tool.remoteName,
              tool_metadata: tool.toolMetadata ?? {},
            })),
          }),
        }),
      ),
    updateMcpServer: async (serverId, payload) =>
      normalizeMcpServer(
        await requestJson<unknown>(baseUrl, `/api/mcp/servers/${serverId}`, {
          method: "PATCH",
          body: JSON.stringify({
            server_key: payload.serverKey,
            name: payload.name,
            transport_kind: payload.transportKind,
            protocol: payload.protocol,
            endpoint: payload.endpoint,
            enabled: payload.enabled,
            preset_key: payload.presetKey,
            auth_config: payload.authConfig,
            server_metadata: payload.serverMetadata,
            tools: payload.tools?.map((tool) => ({
              name: tool.name,
              description: tool.description,
              parameters: tool.parameters ?? {},
              capabilities: tool.capabilities ?? [],
              enabled: tool.enabled ?? true,
              risk_level: tool.riskLevel ?? "medium",
              remote_name: tool.remoteName,
              tool_metadata: tool.toolMetadata ?? {},
            })),
          }),
        }),
      ),
    deleteMcpServer: async (serverId) => {
      await requestVoid(baseUrl, `/api/mcp/servers/${serverId}`, { method: "DELETE" });
    },
    healthcheckMcpServer: async (serverId) =>
      normalizeMcpServer(
        await requestJson<unknown>(baseUrl, `/api/mcp/servers/${serverId}/healthcheck`, {
          method: "POST",
        }),
      ),
    getSettings: async () => normalizeSettings(await requestJson<unknown>(baseUrl, "/api/settings")),
    getAgentSnapshot: async () => normalizeAgentSnapshot(await requestJson<unknown>(baseUrl, "/api/agent")),
    listAgentQueue: async () => asArray(await requestJson<unknown>(baseUrl, "/api/agent/queue")).map(normalizeAgentQueueItem),
    approveItem: async (id) => {
      await requestJson<unknown>(baseUrl, `/api/approvals/${id}/approve`, {
        method: "POST",
        body: JSON.stringify({ reviewer: "desktop-user" }),
      });
    },
    rejectItem: async (id, reason) => {
      await requestJson<unknown>(baseUrl, `/api/approvals/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reviewer: "desktop-user", reason }),
      });
    },
    updateSettings: async (settings) => {
      const payload: Record<string, unknown> = { ...settings };
      const featureFlags: Record<string, unknown> = {};
      if ("autonomyEnabled" in payload) {
        featureFlags.enable_autonomy = Boolean(payload.autonomyEnabled);
        delete payload.autonomyEnabled;
      }
      if ("skillHealthAutonomyEnabled" in payload) {
        featureFlags.enable_skill_health_autonomy = Boolean(payload.skillHealthAutonomyEnabled);
        delete payload.skillHealthAutonomyEnabled;
      }
      if (Object.keys(featureFlags).length > 0) {
        payload.feature_flags = {
          ...(asRecord(payload.feature_flags) as Record<string, unknown>),
          ...featureFlags,
        };
      }
      if ("skillHealthAutonomyIntervalSeconds" in payload) {
        payload.skill_health_autonomy_interval_seconds = payload.skillHealthAutonomyIntervalSeconds;
        delete payload.skillHealthAutonomyIntervalSeconds;
      }
      return normalizeSettings(
        await requestJson<unknown>(baseUrl, "/api/settings", {
          method: "PATCH",
          body: JSON.stringify(payload),
        }),
      );
    },
    runAgentOnce: async () =>
      normalizeAgentRunResult(
        await requestJson<unknown>(baseUrl, "/api/agent/run-once", {
          method: "POST",
        }),
      ),
    queueTask: async (task) =>
      normalizeAgentTaskEnqueueResult(
        await requestJson<unknown>(baseUrl, "/api/agent/tasks", {
          method: "POST",
          body: JSON.stringify({
            task_type: task.taskType,
            payload: task.payload ?? {},
            priority: task.priority ?? 100,
            application_id: task.applicationId,
          }),
        }),
      ),
    subscribeToAgentStream(onEvent) {
      let disposed = false;
      let socket: WebSocket | null = null;
      const timer = window.setTimeout(() => {
        if (disposed) {
          return;
        }
        socket = new WebSocket(resolveWebSocketUrl(baseUrl));
        socket.addEventListener("message", (event) => {
          try {
            const payload = JSON.parse(String(event.data)) as JsonRecord;
            if (payload.type === "heartbeat") {
              return;
            }
            onEvent({
              id: String(payload.id ?? `stream-${Date.now()}`),
              level: String(payload.level ?? "info") as AgentEvent["level"],
              source: String(payload.source ?? "agent"),
              message: String(payload.message ?? ""),
              at: String(payload.at ?? new Date().toISOString()),
            });
          } catch {
            return;
          }
        });
        socket.addEventListener("error", () => {
          return;
        });
      }, 0);
      return () => {
        disposed = true;
        window.clearTimeout(timer);
        if (socket !== null && socket.readyState < WebSocket.CLOSING) {
          socket.close();
        }
      };
    },
  };
}

export function createDesktopApiClient(baseUrl?: string): DesktopApiClient {
  return createFetchClient(baseUrl ?? "http://127.0.0.1:8741");
}

const runtimeBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8741";

export const apiClient = Object.assign(createDesktopApiClient(runtimeBaseUrl), {
  describe(): ApiDescription {
    return {
      baseUrl: runtimeBaseUrl,
      transport: "http",
    };
  },
});
