import { desktopMockSnapshot, desktopRuntimeMock } from "./mockData";
import type {
  ApprovalItem,
  AgentEvent,
  AgentSnapshot,
  AgentRunResult,
  AgentTaskEnqueueResult,
  AgentTaskRequest,
  CandidateRecord,
  CompileTaskRequest,
  CompileTaskResponse,
  DashboardSummary,
  DomainPackRecord,
  RuntimeEpisode,
  RuntimeLearningOutcome,
  RuntimePatch,
  RuntimeSnapshot,
  RuntimeTaskSpec,
  RuntimeTemplate,
  RuntimeWorkspaceData,
  SettingsSnapshot,
  SkillRecord,
  WorkflowDefinition,
} from "./types";

export interface DesktopApiClient {
  getDashboardSummary(): Promise<DashboardSummary>;
  getRuntimeWorkspaceData(): Promise<RuntimeWorkspaceData>;
  listDomainPacks(): Promise<DomainPackRecord[]>;
  listRuntimeTasks(): Promise<RuntimeTaskSpec[]>;
  compileRuntimeTask(payload: CompileTaskRequest): Promise<CompileTaskResponse>;
  listRuntimePlans(): Promise<RuntimeWorkspaceData["plans"]>;
  createTrialRun(taskSpecId: string, executionPlanId: string, notes?: string): Promise<RuntimeEpisode>;
  listRuntimeEpisodes(): Promise<RuntimeEpisode[]>;
  executeTrialRun(episodeId: string, notes?: string): Promise<RuntimeLearningOutcome>;
  refreshRuntimeLearning(episodeId: string): Promise<RuntimeLearningOutcome>;
  confirmTrialRun(episodeId: string, reason?: string): Promise<RuntimeLearningOutcome>;
  listRuntimeSnapshots(): Promise<RuntimeSnapshot[]>;
  listRuntimeTemplates(): Promise<RuntimeTemplate[]>;
  listRuntimePatches(): Promise<RuntimePatch[]>;
  approveRuntimePatch(id: string, reason?: string): Promise<RuntimePatch>;
  rejectRuntimePatch(id: string, reason?: string): Promise<RuntimePatch>;
  listCandidates(): Promise<CandidateRecord[]>;
  listWorkflows(): Promise<WorkflowDefinition[]>;
  listSkills(): Promise<SkillRecord[]>;
  listApprovals(): Promise<ApprovalItem[]>;
  getSettings(): Promise<SettingsSnapshot>;
  getAgentSnapshot(): Promise<AgentSnapshot>;
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

function asRecord(value: unknown): JsonRecord {
  return typeof value === "object" && value !== null ? (value as JsonRecord) : {};
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
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

function normalizeSettings(raw: unknown): SettingsSnapshot {
  const record = asRecord(raw);
  const platform = asRecord(record.platform);
  const intranetSync = asRecord(record.intranetSync ?? record.intranet_sync);
  return {
    locale: String(record.locale ?? "en-US"),
    timezone: String(record.timezone ?? "Asia/Shanghai"),
    intranetEnabled: Boolean(record.intranetEnabled ?? record.intranet_enabled ?? false),
    desktopApprovalsOnly: Boolean(record.desktopApprovalsOnly ?? (record.approval_source ?? "desktop_app") === "desktop_app"),
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
      name: String(platform.name ?? "Boss直聘"),
      account: String(platform.account ?? "recruiter-01"),
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
    defaultCapabilities: asArray<string>(record.defaultCapabilities ?? record.default_capabilities),
    sampleTasks: asArray<string>(record.sampleTasks ?? record.sample_tasks),
    defaultConstraints: asRecord(record.defaultConstraints ?? record.default_constraints),
    defaultOutputContract: asRecord(record.defaultOutputContract ?? record.default_output_contract),
    templateKeys: asArray<string>(record.templateKeys ?? record.template_keys),
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

function normalizeRuntimeLearningOutcome(raw: unknown): RuntimeLearningOutcome {
  const record = asRecord(raw);
  const approval = asRecord(record.approval);
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
    skillHealth: record.skillHealth ? asRecord(record.skillHealth) : record.skill_health ? asRecord(record.skill_health) : null,
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

function createFetchClient(baseUrl: string): DesktopApiClient {
  return {
    getDashboardSummary: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")),
    getRuntimeWorkspaceData: async () => {
      const [domainPacks, taskSpecs, plans, episodes, snapshots, templates, patches] = await Promise.all([
        requestJson<unknown>(baseUrl, "/api/runtime/domain-packs"),
        requestJson<unknown>(baseUrl, "/api/runtime/task-specs"),
        requestJson<unknown>(baseUrl, "/api/runtime/plans"),
        requestJson<unknown>(baseUrl, "/api/runtime/trial-runs"),
        requestJson<unknown>(baseUrl, "/api/runtime/environment-snapshots"),
        requestJson<unknown>(baseUrl, "/api/runtime/templates"),
        requestJson<unknown>(baseUrl, "/api/runtime/workflow-patches"),
      ]);
      return {
        domainPacks: asArray(domainPacks).map(normalizeDomainPack),
        taskSpecs: asArray(taskSpecs).map(normalizeRuntimeTask),
        plans: asArray(plans).map(normalizeRuntimePlan),
        episodes: asArray(episodes).map(normalizeRuntimeEpisode),
        snapshots: asArray(snapshots).map(normalizeRuntimeSnapshot),
        templates: asArray(templates).map(normalizeRuntimeTemplate),
        patches: asArray(patches).map(normalizeRuntimePatch),
      };
    },
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
    listRuntimeSnapshots: async () => asArray(await requestJson<unknown>(baseUrl, "/api/runtime/environment-snapshots")).map(normalizeRuntimeSnapshot),
    listRuntimeTemplates: async () => asArray(await requestJson<unknown>(baseUrl, "/api/runtime/templates")).map(normalizeRuntimeTemplate),
    listRuntimePatches: async () => asArray(await requestJson<unknown>(baseUrl, "/api/runtime/workflow-patches")).map(normalizeRuntimePatch),
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
    listCandidates: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).candidates,
    listWorkflows: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).workflows,
    listSkills: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).skills,
    listApprovals: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).approvals,
    getSettings: async () => normalizeSettings(await requestJson<unknown>(baseUrl, "/api/settings")),
    getAgentSnapshot: async () => normalizeAgentSnapshot(await requestJson<unknown>(baseUrl, "/api/agent")),
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
    updateSettings: async (settings) =>
      normalizeSettings(
        await requestJson<unknown>(baseUrl, "/api/settings", {
          method: "PATCH",
          body: JSON.stringify(settings),
        }),
      ),
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

  return {
    getDashboardSummary: async () => snapshot,
    getRuntimeWorkspaceData: async () => desktopRuntimeMock,
    listDomainPacks: async () => desktopRuntimeMock.domainPacks,
    listRuntimeTasks: async () => desktopRuntimeMock.taskSpecs,
    compileRuntimeTask: async (payload) => ({
      domainPack: desktopRuntimeMock.domainPacks.find((item) => item.key === payload.domainHint) ?? desktopRuntimeMock.domainPacks[0],
      compilerNotes: ["Backend unavailable. Returning mock runtime compilation."],
      taskSpec: desktopRuntimeMock.taskSpecs[0],
      executionPlan: desktopRuntimeMock.plans[0],
    }),
    listRuntimePlans: async () => desktopRuntimeMock.plans,
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
    listRuntimeSnapshots: async () => desktopRuntimeMock.snapshots,
    listRuntimeTemplates: async () => desktopRuntimeMock.templates,
    listRuntimePatches: async () => desktopRuntimeMock.patches,
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
    listCandidates: async () => snapshot.candidates,
    listWorkflows: async () => snapshot.workflows,
    listSkills: async () => snapshot.skills,
    listApprovals: async () => snapshot.approvals,
    getSettings: async () => snapshot.settings,
    getAgentSnapshot: async () => snapshot.agent,
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
    async listRuntimeSnapshots() {
      return fetchClient.listRuntimeSnapshots().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopRuntimeMock.snapshots;
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
