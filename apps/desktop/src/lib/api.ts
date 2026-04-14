import { desktopAgentQueueMock, desktopMockSnapshot, desktopReplayMockByEpisode, desktopRuntimeMock, desktopSyncBacklogMock, desktopSyncStatusMock } from "./mockData";
import type {
  ApprovalItem,
  AgentEvent,
  AgentQueueItem,
  AgentSnapshot,
  AgentRunResult,
  AgentTaskEnqueueResult,
  AgentTaskRequest,
  CandidateRecord,
  CompileTaskRequest,
  CompileTaskResponse,
  DashboardSummary,
  DomainPackRecord,
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
  SyncBacklogItem,
  SyncFlushResult,
  SyncStatusSnapshot,
  WorkflowDefinition,
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
  getSyncStatus(): Promise<SyncStatusSnapshot>;
  listSyncBacklog(): Promise<SyncBacklogItem[]>;
  flushSyncBacklog(): Promise<SyncFlushResult>;
  listCandidates(): Promise<CandidateRecord[]>;
  listWorkflows(): Promise<WorkflowDefinition[]>;
  listSkills(): Promise<SkillRecord[]>;
  listApprovals(): Promise<ApprovalItem[]>;
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
  transport: "mock" | "http";
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
    priority: Number(record.priority ?? 0),
    status: String(record.status ?? "pending"),
    attempts: Number(record.attempts ?? 0),
    scheduledFor: record.scheduledFor ? String(record.scheduledFor) : record.scheduled_for ? String(record.scheduled_for) : null,
    lockedAt: record.lockedAt ? String(record.lockedAt) : record.locked_at ? String(record.locked_at) : null,
    lockedBy: record.lockedBy ? String(record.lockedBy) : record.locked_by ? String(record.locked_by) : null,
    candidateId: record.candidateId ? String(record.candidateId) : record.candidate_id ? String(record.candidate_id) : null,
    workflowId: record.workflowId ? String(record.workflowId) : record.workflow_id ? String(record.workflow_id) : null,
    workflowNodeId: record.workflowNodeId ? String(record.workflowNodeId) : record.workflow_node_id ? String(record.workflow_node_id) : null,
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
      name: String(platform.name ?? "Runtime scene profile"),
      account: String(platform.account ?? "runtime-scene-01"),
      cooldownDays: Number(platform.cooldownDays ?? platform.cooldown_days ?? 30),
      allowOutboundMessaging: Boolean(platform.allowOutboundMessaging ?? platform.allow_outbound_messaging ?? false),
    },
  };
}

function normalizeDashboard(raw: unknown): DashboardSummary {
  const record = asRecord(raw);
  return {
    metrics: asArray(record.metrics) as DashboardSummary["metrics"],
    pipeline: asArray(record.pipeline) as DashboardSummary["pipeline"],
    timeline: asArray(record.timeline) as DashboardSummary["timeline"],
    alerts: asArray(record.alerts) as DashboardSummary["alerts"],
    candidates: asArray(record.candidates) as CandidateRecord[],
    workflows: asArray(record.workflows) as WorkflowDefinition[],
    skills: asArray(record.skills) as SkillRecord[],
    approvals: asArray(record.approvals) as ApprovalItem[],
    agent: normalizeAgentSnapshot(record.agent),
    settings: normalizeSettings(record.settings),
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
    fallbackStrategy: String(record.fallbackStrategy ?? record.fallback_strategy ?? "heuristic"),
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
        "Generated a new plan revision from the latest runtime scene.",
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

async function requestRuntimeReplay(baseUrl: string, episodeId: string): Promise<RuntimeEpisodeReplay> {
  try {
    return normalizeRuntimeReplay(await requestJson<unknown>(baseUrl, `/api/runtime/trial-runs/${episodeId}/replay`));
  } catch (error) {
    if (error instanceof Error && /404/.test(error.message)) {
      return normalizeRuntimeReplay(await requestJson<unknown>(baseUrl, `/api/runtime/episodes/${episodeId}/replay`));
    }
    throw error;
  }
}

function createFetchClient(baseUrl: string): DesktopApiClient {
  return {
    getDashboardSummary: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")),
    getRuntimeWorkspaceData: async () => {
      const [compilerContract, domainPacks, taskSpecs, plans, episodes, snapshots, capabilityDrivers, environmentAssessments, templates, patches, replans] =
        await Promise.all([
        requestJson<unknown>(baseUrl, "/api/runtime/compiler-contract"),
        requestJson<unknown>(baseUrl, "/api/runtime/domain-packs"),
        requestJson<unknown>(baseUrl, "/api/runtime/task-specs"),
        requestJson<unknown>(baseUrl, "/api/runtime/plans"),
        requestJson<unknown>(baseUrl, "/api/runtime/trial-runs"),
        requestJson<unknown>(baseUrl, "/api/runtime/environment-snapshots"),
        requestOptionalJson<unknown>(baseUrl, "/api/runtime/capability-drivers"),
        requestOptionalJson<unknown>(baseUrl, "/api/runtime/environment-assessments"),
        requestJson<unknown>(baseUrl, "/api/runtime/templates"),
        requestJson<unknown>(baseUrl, "/api/runtime/workflow-patches"),
        requestOptionalJson<unknown>(baseUrl, "/api/runtime/replans"),
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
      normalizeRuntimeCompilerContract(await requestJson<unknown>(baseUrl, "/api/runtime/compiler-contract")),
    listDomainPacks: async () => asArray(await requestJson<unknown>(baseUrl, "/api/runtime/domain-packs")).map(normalizeDomainPack),
    listRuntimeTasks: async () => asArray(await requestJson<unknown>(baseUrl, "/api/runtime/task-specs")).map(normalizeRuntimeTask),
    compileRuntimeTask: async (payload) =>
      normalizeCompileTaskResponse(
        await requestJson<unknown>(baseUrl, "/api/runtime/task-specs/compile", {
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
    listRuntimePlans: async () => asArray(await requestJson<unknown>(baseUrl, "/api/runtime/plans")).map(normalizeRuntimePlan),
    launchRuntimePlan: async (planId, taskSpecId, mode = "production") =>
      normalizeRuntimePlanLaunchResult(
        await requestJson<unknown>(baseUrl, `/api/runtime/plans/${planId}/enqueue`, {
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
        await requestJson<unknown>(baseUrl, "/api/runtime/trial-runs", {
          method: "POST",
          body: JSON.stringify({
            task_spec_id: taskSpecId,
            execution_plan_id: executionPlanId,
            requested_by: "desktop-user",
            notes,
          }),
        }),
      ),
    listRuntimeEpisodes: async () => asArray(await requestJson<unknown>(baseUrl, "/api/runtime/trial-runs")).map(normalizeRuntimeEpisode),
    executeTrialRun: async (episodeId, notes) =>
      normalizeRuntimeLearningOutcome(
        await requestJson<unknown>(baseUrl, `/api/runtime/trial-runs/${episodeId}/execute`, {
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
        await requestJson<unknown>(baseUrl, `/api/runtime/trial-runs/${episodeId}/learn`, {
          method: "POST",
        }),
      ),
    confirmTrialRun: async (episodeId, reason) =>
      normalizeRuntimeLearningOutcome(
        await requestJson<unknown>(baseUrl, `/api/runtime/trial-runs/${episodeId}/confirm`, {
          method: "POST",
          body: JSON.stringify({
            reviewer: "desktop-user",
            reason,
            activate_template: true,
          }),
        }),
      ),
    getRuntimeReplay: async (episodeId) => requestRuntimeReplay(baseUrl, episodeId),
    listRuntimeSnapshots: async () => asArray(await requestJson<unknown>(baseUrl, "/api/runtime/environment-snapshots")).map(normalizeRuntimeSnapshot),
    listCapabilityDrivers: async () => {
      const payload = await requestOptionalJson<unknown>(baseUrl, "/api/runtime/capability-drivers");
      return payload ? asArray(payload).map(normalizeRuntimeCapabilityDriver) : [];
    },
    listRuntimeEnvironmentAssessments: async () => {
      const payload = await requestOptionalJson<unknown>(baseUrl, "/api/runtime/environment-assessments");
      return payload ? asArray(payload).map(normalizeRuntimeEnvironmentAssessment) : [];
    },
    assessRuntimeEnvironment: async (payload) =>
      normalizeRuntimeEnvironmentAssessment(
        await requestJson<unknown>(baseUrl, "/api/runtime/environment-assessments", {
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
    listRuntimeTemplates: async () => asArray(await requestJson<unknown>(baseUrl, "/api/runtime/templates")).map(normalizeRuntimeTemplate),
    listRuntimePatches: async () => asArray(await requestJson<unknown>(baseUrl, "/api/runtime/workflow-patches")).map(normalizeRuntimePatch),
    listRuntimeReplans: async () => {
      const payload = await requestOptionalJson<unknown>(baseUrl, "/api/runtime/replans");
      return payload ? asArray(payload).map(normalizeRuntimeReplanResult) : [];
    },
    replanRuntimePlan: async (payload) =>
      normalizeRuntimeReplanResult(
        await requestJson<unknown>(baseUrl, `/api/runtime/plans/${payload.executionPlanId}/replan`, {
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
        await requestJson<unknown>(baseUrl, `/api/runtime/workflow-patches/${id}/approve`, {
          method: "POST",
          body: JSON.stringify({ reviewer: "desktop-user", reason, apply_immediately: true }),
        }),
      ),
    rejectRuntimePatch: async (id, reason) =>
      normalizeRuntimePatch(
        await requestJson<unknown>(baseUrl, `/api/runtime/workflow-patches/${id}/reject`, {
          method: "POST",
          body: JSON.stringify({ reviewer: "desktop-user", reason }),
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
    listCandidates: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).candidates,
    listWorkflows: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).workflows,
    listSkills: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).skills,
    listApprovals: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).approvals,
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
      if ("skillHealthAutonomyEnabled" in payload) {
        payload.feature_flags = {
          enable_skill_health_autonomy: Boolean(payload.skillHealthAutonomyEnabled),
        };
        delete payload.skillHealthAutonomyEnabled;
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
            candidate_id: task.candidateId,
            workflow_id: task.workflowId,
            workflow_node_id: task.workflowNodeId,
          }),
        }),
      ),
    subscribeToAgentStream(onEvent) {
      const socket = new WebSocket(resolveWebSocketUrl(baseUrl));
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
      return () => socket.close();
    },
  };
}

function createMockClient(): DesktopApiClient {
  const snapshot = desktopMockSnapshot;
  const buildMockReplan = (payload: RuntimePlanReplanRequest): RuntimePlanReplanResult => {
    const basePlan = desktopRuntimeMock.plans.find((item) => item.id === payload.executionPlanId) ?? desktopRuntimeMock.plans[0];
    const trigger = payload.trigger ?? "scene_drift";
    const assessment =
      desktopRuntimeMock.environmentAssessments.find((item) => item.executionPlanId === payload.executionPlanId) ??
      desktopRuntimeMock.environmentAssessments[0] ??
      null;
    const patch =
      desktopRuntimeMock.patches.find((item) => item.executionPlanId === payload.executionPlanId) ?? desktopRuntimeMock.patches[0] ?? null;
    const capabilitySet = new Set<string>([
      ...((payload.preferredCapabilityKeys ?? []).filter(Boolean)),
      ...(assessment?.capabilityKeys ?? []),
      ...desktopRuntimeMock.capabilityDrivers.slice(0, 3).map((driver) => driver.key),
    ]);
    const timestamp = new Date().toISOString();
    return {
      id: `replan-${payload.executionPlanId}-${Date.now()}`,
      taskSpecId: payload.taskSpecId ?? basePlan?.taskSpecId ?? null,
      baseExecutionPlanId: payload.executionPlanId,
      executionPlan: {
        ...(basePlan ?? desktopRuntimeMock.plans[0]),
        id: `${payload.executionPlanId}-replan`,
        name: `${basePlan?.name ?? "Runtime plan"} Replanned`,
        status: "proposed",
        version: (basePlan?.version ?? 0) + 1,
        approvalState: "pending_review",
        checkpoints: [
          ...(basePlan?.checkpoints ?? []),
          {
            kind: "scene_assessment",
            label: "Validate live environment before applying updated execution steps",
          },
        ],
        runtimeMetadata: {
          ...(basePlan?.runtimeMetadata ?? {}),
          replanned_at: timestamp,
          replanned_trigger: trigger,
          replanned_notes: payload.notes ?? "",
        },
        updatedAt: timestamp,
      },
      status: "proposed",
      trigger,
      summary: payload.notes
        ? `Mock replanning inserted a fresh scene assessment checkpoint. Operator notes: ${payload.notes}`
        : "Mock replanning inserted a fresh scene assessment checkpoint and proposed a safer execution order.",
      compilerNotes: [
        "Backend replanning endpoint is unavailable, so the desktop control plane generated a local proposal.",
        "Capability priority was refreshed from the current assessment and selected driver hints.",
      ],
      recommendedCapabilityKeys: Array.from(capabilitySet).slice(0, 4),
      environmentAssessment: assessment,
      patch: patch
        ? {
            ...patch,
            id: `${patch.id}-replan`,
            status: "pending_review",
            updatedAt: timestamp,
          }
        : null,
      createdAt: timestamp,
    };
  };

  return {
    getDashboardSummary: async () => snapshot,
    getRuntimeWorkspaceData: async () => desktopRuntimeMock,
    getTaskCompilerContract: async () =>
      desktopRuntimeMock.compilerContract ?? normalizeRuntimeCompilerContract({}),
    listDomainPacks: async () => desktopRuntimeMock.domainPacks,
    listRuntimeTasks: async () => desktopRuntimeMock.taskSpecs,
    compileRuntimeTask: async (payload) => ({
      domainPack: desktopRuntimeMock.domainPacks.find((item) => item.key === payload.domainHint) ?? desktopRuntimeMock.domainPacks[0],
      compilerNotes: ["Backend unavailable. Returning mock runtime compilation."],
      taskSpec: desktopRuntimeMock.taskSpecs[0],
      executionPlan: desktopRuntimeMock.plans[0],
    }),
    listRuntimePlans: async () => desktopRuntimeMock.plans,
    launchRuntimePlan: async (planId, taskSpecId, mode = "production") => ({
      taskId: `mock-runtime-${planId}`,
      taskType: "runtime_execution",
      priority: 120,
      queueDepth: desktopMockSnapshot.agent.queueDepth + 1,
      taskSpecId,
      executionPlanId: planId,
      executionEpisode: {
        ...desktopRuntimeMock.episodes[0],
        id: `mock-runtime-episode-${Date.now()}`,
        taskSpecId,
        executionPlanId: planId,
        mode,
        status: "pending",
        requiresConfirmation: mode !== "production",
      },
    }),
    createTrialRun: async (taskSpecId, executionPlanId, notes) => ({
      ...desktopRuntimeMock.episodes[0],
      id: `mock-episode-${Date.now()}`,
      taskSpecId,
      executionPlanId,
      resultSummary: notes ? `Mock trial created. Notes: ${notes}` : "Mock trial created.",
    }),
    listRuntimeEpisodes: async () => desktopRuntimeMock.episodes,
    executeTrialRun: async (episodeId, notes) => ({
      episode: {
        ...desktopRuntimeMock.episodes[0],
        id: episodeId,
        resultSummary: notes ? `Mock execution completed. Notes: ${notes}` : "Mock execution completed.",
      },
      template: desktopRuntimeMock.templates[0],
      patch: desktopRuntimeMock.patches[0] ?? null,
      learningDraft: null,
      approval: null,
      skillHealth: null,
    }),
    refreshRuntimeLearning: async (episodeId) => ({
      episode: { ...desktopRuntimeMock.episodes[0], id: episodeId },
      template: desktopRuntimeMock.templates[0],
      patch: desktopRuntimeMock.patches[0] ?? null,
      learningDraft: null,
      approval: null,
      skillHealth: null,
    }),
    confirmTrialRun: async (episodeId, reason) => ({
      episode: {
        ...desktopRuntimeMock.episodes[0],
        id: episodeId,
        status: "confirmed",
        requiresConfirmation: false,
        resultSummary: reason ? `Mock confirmation recorded. ${reason}` : desktopRuntimeMock.episodes[0].resultSummary,
      },
      template: { ...desktopRuntimeMock.templates[0], status: "active" },
      patch: null,
      learningDraft: null,
      approval: null,
      skillHealth: null,
      }),
    getRuntimeReplay: async (episodeId) => desktopReplayMockByEpisode[episodeId] ?? desktopReplayMockByEpisode["episode-001"],
    listRuntimeSnapshots: async () => desktopRuntimeMock.snapshots,
    listCapabilityDrivers: async () => desktopRuntimeMock.capabilityDrivers,
    listRuntimeEnvironmentAssessments: async () => desktopRuntimeMock.environmentAssessments,
    assessRuntimeEnvironment: async (payload) =>
      desktopRuntimeMock.environmentAssessments.find(
        (item) =>
          item.executionEpisodeId === payload.executionEpisodeId ||
          item.executionPlanId === payload.executionPlanId ||
          item.taskSpecId === payload.taskSpecId,
      ) ?? desktopRuntimeMock.environmentAssessments[0],
    listRuntimeTemplates: async () => desktopRuntimeMock.templates,
    listRuntimePatches: async () => desktopRuntimeMock.patches,
    listRuntimeReplans: async () => desktopRuntimeMock.replans,
    replanRuntimePlan: async (payload) => buildMockReplan(payload),
    approveRuntimePatch: async (id, reason) => ({
      ...desktopRuntimeMock.patches[0],
      id,
      status: "applied",
      rationale: reason ?? desktopRuntimeMock.patches[0]?.rationale ?? null,
    }),
    rejectRuntimePatch: async (id, reason) => ({
      ...desktopRuntimeMock.patches[0],
      id,
      status: "rejected",
      rationale: reason ?? desktopRuntimeMock.patches[0]?.rationale ?? null,
    }),
    getSyncStatus: async () => desktopSyncStatusMock,
    listSyncBacklog: async () => desktopSyncBacklogMock,
    flushSyncBacklog: async () => ({
      attempted: desktopSyncBacklogMock.length,
      synced: 0,
      failed: desktopSyncBacklogMock.length,
      remoteAvailable: false,
      message: "Mock flush kept the backlog locally because intranet sync is disabled.",
    }),
    listCandidates: async () => snapshot.candidates,
    listWorkflows: async () => snapshot.workflows,
    listSkills: async () => snapshot.skills,
    listApprovals: async () => snapshot.approvals,
    getSettings: async () => snapshot.settings,
    getAgentSnapshot: async () => snapshot.agent,
    listAgentQueue: async () => desktopAgentQueueMock,
    approveItem: async () => undefined,
    rejectItem: async () => undefined,
    updateSettings: async (settings) => ({ ...snapshot.settings, ...settings }),
    runAgentOnce: async () => ({ processed: false, status: "mock" }),
    queueTask: async (task) => ({
      taskId: `mock-${task.taskType}`,
      taskType: task.taskType,
      priority: task.priority ?? 100,
      queueDepth: snapshot.agent.queueDepth + 1,
    }),
    subscribeToAgentStream: () => () => undefined,
  };
}

export function createDesktopApiClient(baseUrl?: string): DesktopApiClient {
  if (!baseUrl) {
    return createMockClient();
  }

  const fetchClient = createFetchClient(baseUrl);
  return {
    async getDashboardSummary() {
      try {
        return await fetchClient.getDashboardSummary();
      } catch (error) {
        if (isOfflineError(error)) {
          return desktopMockSnapshot;
        }
        throw error;
      }
    },
    async getRuntimeWorkspaceData() {
      try {
        return await fetchClient.getRuntimeWorkspaceData();
      } catch (error) {
        if (isOfflineError(error)) {
          return desktopRuntimeMock;
        }
        throw error;
      }
    },
    async getTaskCompilerContract() {
      try {
        return await fetchClient.getTaskCompilerContract();
      } catch (error) {
        if (isOfflineError(error)) {
          return desktopRuntimeMock.compilerContract ?? normalizeRuntimeCompilerContract({});
        }
        throw error;
      }
    },
    async listDomainPacks() {
      return fetchClient.listDomainPacks().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopRuntimeMock.domainPacks;
        }
        throw error;
      });
    },
    async listRuntimeTasks() {
      return fetchClient.listRuntimeTasks().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopRuntimeMock.taskSpecs;
        }
        throw error;
      });
    },
    async compileRuntimeTask(payload) {
      return fetchClient.compileRuntimeTask(payload).catch(async (error) => {
        if (isOfflineError(error)) {
          return createMockClient().compileRuntimeTask(payload);
        }
        throw error;
      });
    },
    async listRuntimePlans() {
      return fetchClient.listRuntimePlans().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopRuntimeMock.plans;
        }
        throw error;
      });
    },
    async launchRuntimePlan(planId, taskSpecId, mode = "production") {
      return fetchClient.launchRuntimePlan(planId, taskSpecId, mode).catch(async (error) => {
        if (isOfflineError(error) || isMissingEndpointError(error)) {
          return createMockClient().launchRuntimePlan(planId, taskSpecId, mode);
        }
        throw error;
      });
    },
    async createTrialRun(taskSpecId, executionPlanId, notes) {
      return fetchClient.createTrialRun(taskSpecId, executionPlanId, notes).catch(async (error) => {
        if (isOfflineError(error)) {
          return createMockClient().createTrialRun(taskSpecId, executionPlanId, notes);
        }
        throw error;
      });
    },
    async listRuntimeEpisodes() {
      return fetchClient.listRuntimeEpisodes().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopRuntimeMock.episodes;
        }
        throw error;
      });
    },
    async executeTrialRun(episodeId, notes) {
      return fetchClient.executeTrialRun(episodeId, notes).catch(async (error) => {
        if (isOfflineError(error)) {
          return createMockClient().executeTrialRun(episodeId, notes);
        }
        throw error;
      });
    },
    async refreshRuntimeLearning(episodeId) {
      return fetchClient.refreshRuntimeLearning(episodeId).catch(async (error) => {
        if (isOfflineError(error)) {
          return createMockClient().refreshRuntimeLearning(episodeId);
        }
        throw error;
      });
    },
    async confirmTrialRun(episodeId, reason) {
      return fetchClient.confirmTrialRun(episodeId, reason).catch(async (error) => {
        if (isOfflineError(error)) {
          return createMockClient().confirmTrialRun(episodeId, reason);
        }
        throw error;
      });
    },
    async getRuntimeReplay(episodeId) {
      return fetchClient.getRuntimeReplay(episodeId).catch(async (error) => {
        if (isOfflineError(error)) {
          return createMockClient().getRuntimeReplay(episodeId);
        }
        throw error;
      });
    },
    async listRuntimeSnapshots() {
      return fetchClient.listRuntimeSnapshots().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopRuntimeMock.snapshots;
        }
        throw error;
      });
    },
    async listCapabilityDrivers() {
      return fetchClient.listCapabilityDrivers().catch(async (error) => {
        if (isOfflineError(error) || isMissingEndpointError(error)) {
          return desktopRuntimeMock.capabilityDrivers;
        }
        throw error;
      });
    },
    async listRuntimeEnvironmentAssessments() {
      return fetchClient.listRuntimeEnvironmentAssessments().catch(async (error) => {
        if (isOfflineError(error) || isMissingEndpointError(error)) {
          return desktopRuntimeMock.environmentAssessments;
        }
        throw error;
      });
    },
    async assessRuntimeEnvironment(payload) {
      return fetchClient.assessRuntimeEnvironment(payload).catch(async (error) => {
        if (isOfflineError(error) || isMissingEndpointError(error)) {
          return createMockClient().assessRuntimeEnvironment(payload);
        }
        throw error;
      });
    },
    async listRuntimeTemplates() {
      return fetchClient.listRuntimeTemplates().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopRuntimeMock.templates;
        }
        throw error;
      });
    },
    async listRuntimePatches() {
      return fetchClient.listRuntimePatches().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopRuntimeMock.patches;
        }
        throw error;
      });
    },
    async listRuntimeReplans() {
      return fetchClient.listRuntimeReplans().catch(async (error) => {
        if (isOfflineError(error) || isMissingEndpointError(error)) {
          return desktopRuntimeMock.replans;
        }
        throw error;
      });
    },
    async replanRuntimePlan(payload) {
      return fetchClient.replanRuntimePlan(payload).catch(async (error) => {
        if (isOfflineError(error) || isMissingEndpointError(error)) {
          return createMockClient().replanRuntimePlan(payload);
        }
        throw error;
      });
    },
    async approveRuntimePatch(id, reason) {
      return fetchClient.approveRuntimePatch(id, reason).catch(async (error) => {
        if (isOfflineError(error)) {
          return createMockClient().approveRuntimePatch(id, reason);
        }
        throw error;
      });
    },
    async rejectRuntimePatch(id, reason) {
      return fetchClient.rejectRuntimePatch(id, reason).catch(async (error) => {
        if (isOfflineError(error)) {
          return createMockClient().rejectRuntimePatch(id, reason);
        }
        throw error;
      });
    },
    async getSyncStatus() {
      return fetchClient.getSyncStatus().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopSyncStatusMock;
        }
        throw error;
      });
    },
    async listSyncBacklog() {
      return fetchClient.listSyncBacklog().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopSyncBacklogMock;
        }
        throw error;
      });
    },
    async flushSyncBacklog() {
      return fetchClient.flushSyncBacklog().catch(async (error) => {
        if (isOfflineError(error)) {
          return createMockClient().flushSyncBacklog();
        }
        throw error;
      });
    },
    async listCandidates() {
      return fetchClient.listCandidates().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.candidates;
        }
        throw error;
      });
    },
    async listWorkflows() {
      return fetchClient.listWorkflows().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.workflows;
        }
        throw error;
      });
    },
    async listSkills() {
      return fetchClient.listSkills().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.skills;
        }
        throw error;
      });
    },
    async listApprovals() {
      return fetchClient.listApprovals().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.approvals;
        }
        throw error;
      });
    },
    async getSettings() {
      return fetchClient.getSettings().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.settings;
        }
        throw error;
      });
    },
    async getAgentSnapshot() {
      return fetchClient.getAgentSnapshot().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.agent;
        }
        throw error;
      });
    },
    async listAgentQueue() {
      return fetchClient.listAgentQueue().catch(async (error) => {
        if (isOfflineError(error) || isMissingEndpointError(error)) {
          return desktopAgentQueueMock;
        }
        throw error;
      });
    },
    async approveItem(id) {
      try {
        await fetchClient.approveItem(id);
      } catch (error) {
        if (!isOfflineError(error)) {
          throw error;
        }
      }
    },
    async rejectItem(id, reason) {
      try {
        await fetchClient.rejectItem(id, reason);
      } catch (error) {
        if (!isOfflineError(error)) {
          throw error;
        }
      }
    },
    async updateSettings(settings) {
      try {
        return await fetchClient.updateSettings(settings);
      } catch (error) {
        if (isOfflineError(error)) {
          return { ...desktopMockSnapshot.settings, ...settings };
        }
        throw error;
      }
    },
    async runAgentOnce() {
      try {
        return await fetchClient.runAgentOnce();
      } catch (error) {
        if (isOfflineError(error)) {
          return { processed: false, status: "mock-offline" };
        }
        throw error;
      }
    },
    async queueTask(task) {
      try {
        return await fetchClient.queueTask(task);
      } catch (error) {
        if (isOfflineError(error)) {
          return {
            taskId: `mock-${task.taskType}`,
            taskType: task.taskType,
            priority: task.priority ?? 100,
            queueDepth: desktopMockSnapshot.agent.queueDepth + 1,
          };
        }
        throw error;
      }
    },
    subscribeToAgentStream(onEvent) {
      try {
        return fetchClient.subscribeToAgentStream(onEvent);
      } catch {
        return () => undefined;
      }
    },
  };
}

const runtimeBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8741";

export const apiClient = Object.assign(createDesktopApiClient(runtimeBaseUrl), {
  describe(): ApiDescription {
    return {
      baseUrl: runtimeBaseUrl || "mock://desktop",
      transport: runtimeBaseUrl ? "http" : "mock",
    };
  },
});
