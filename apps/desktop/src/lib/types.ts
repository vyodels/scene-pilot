export type WorkspaceTab =
  | "dashboard"
  | "workflow-management"
  | "workbench"
  | "skills"
  | "approvals"
  | "settings";

export type ProviderKind = "openai-compatible" | "anthropic";
export type ApiTransport = "mock" | "http";
export type HealthStatus = "healthy" | "warning" | "critical";
export type ApprovalStatus = "pending" | "approved" | "rejected";
export type CandidateStatus =
  | "discovered"
  | "screening"
  | "pending_communication"
  | "communicating"
  | "waiting_reply"
  | "pending_resume"
  | "scoring"
  | "passed_to_talent_pool"
  | "hr_review"
  | "team_review"
  | "interview_scheduled"
  | "offer"
  | "rejected"
  | "cooldown";

export interface MetricSummary {
  label: string;
  value: string;
  delta: string;
  tone: "positive" | "neutral" | "warning";
  caption: string;
}

export interface PipelineStage {
  label: string;
  value: number;
  target?: number;
}

export interface TimelineEvent {
  id: string;
  label: string;
  detail: string;
  at: string;
  tone: "positive" | "neutral" | "warning" | "critical";
}

export interface CandidateRecord {
  id: string;
  name: string;
  title: string;
  platform: string;
  location: string;
  status: CandidateStatus;
  workflowNode: string;
  jdTitle: string;
  matchScore: number;
  experienceYears: number;
  nextAction: string;
  summary: string;
  tags: string[];
  resumeAvailable: boolean;
  cooldownUntil?: string;
  lastContactedAt?: string;
}

export interface WorkflowNodeSummary {
  id: string;
  name: string;
  kind: "discover" | "screen" | "communicate" | "resume" | "score" | "review";
  status: "idle" | "running" | "blocked" | "approved";
  owner: string;
  description: string;
}

export interface WorkflowDefinition {
  id: string;
  name: string;
  jdTitle: string;
  status: "draft" | "active" | "archived";
  version: string;
  nodes: WorkflowNodeSummary[];
  updatedAt: string;
}

export interface SkillRecord {
  id: string;
  name: string;
  version: string;
  status: "draft" | "pending_review" | "approved" | "active" | "degraded" | "disabled";
  boundNode: string;
  platform: string;
  health: HealthStatus;
  lastCheckedAt: string;
  summary: string;
}

export interface ApprovalItem {
  id: string;
  kind: string;
  title: string;
  detail: string;
  requester: string;
  status: ApprovalStatus;
  createdAt: string;
  targetType?: string;
  targetId?: string;
  reviewedBy?: string | null;
  reviewedAt?: string | null;
  payload?: Record<string, unknown>;
  notes?: string | null;
  updatedAt?: string;
}

export interface AgentEvent {
  id: string;
  level: "info" | "success" | "warning" | "error";
  source: string;
  message: string;
  at: string;
}

export interface AgentSnapshot {
  status: "idle" | "running" | "waiting_human" | "degraded" | "paused";
  activeTask: string;
  browserLock: "free" | "held";
  uptime: string;
  queueDepth: number;
  tokenBudgetUsed: number;
  health: HealthStatus;
}

export interface AgentQueueAuditEvent {
  kind: string;
  at: string;
  status?: string | null;
  priority?: number | null;
  attempts?: number | null;
  lockedBy?: string | null;
  error?: string | null;
}

export interface AgentQueueItem {
  taskId: string;
  taskType: string;
  priority: number;
  status: string;
  attempts: number;
  scheduledFor?: string | null;
  lockedAt?: string | null;
  lockedBy?: string | null;
  candidateId?: string | null;
  workflowId?: string | null;
  workflowNodeId?: string | null;
  payload: Record<string, unknown>;
  queueAudit: AgentQueueAuditEvent[];
  createdAt: string;
  updatedAt: string;
}

export interface ProviderConfig {
  kind: ProviderKind;
  name: string;
  model: string;
  baseUrl?: string;
  enabled: boolean;
  temperature: number;
}

export interface SettingsSnapshot {
  locale: string;
  timezone: string;
  intranetEnabled: boolean;
  desktopApprovalsOnly: boolean;
  skillHealthAutonomyEnabled: boolean;
  skillHealthAutonomyIntervalSeconds?: number | null;
  providers: ProviderConfig[];
  intranetSync?: {
    enabled: boolean;
    baseUrl?: string;
    apiPath: string;
    timeoutSeconds: number;
  };
  platform: {
    name: string;
    account: string;
    cooldownDays: number;
    allowOutboundMessaging: boolean;
  };
}

export interface DashboardSummary {
  metrics: MetricSummary[];
  pipeline: PipelineStage[];
  timeline: TimelineEvent[];
  alerts: TimelineEvent[];
  candidates: CandidateRecord[];
  workflows: WorkflowDefinition[];
  skills: SkillRecord[];
  approvals: ApprovalItem[];
  agent: AgentSnapshot;
  settings: SettingsSnapshot;
}

export interface AgentRunResult {
  processed: boolean;
  status: string;
  taskId?: string;
  enqueuedFollowUps?: number;
  error?: string | null;
}

export interface AgentTaskRequest {
  taskType: string;
  payload?: Record<string, unknown>;
  priority?: number;
  candidateId?: string;
  workflowId?: string;
  workflowNodeId?: string;
}

export interface AgentTaskEnqueueResult {
  taskId: string;
  taskType: string;
  priority: number;
  queueDepth: number;
}

export interface DomainPackRecord {
  key: string;
  name: string;
  description: string;
  version: string;
  maturity: string;
  runtimeOnly: boolean;
  defaultCapabilities: string[];
  sampleTasks: string[];
  defaultConstraints: Record<string, unknown>;
  defaultOutputContract: Record<string, unknown>;
  templateKeys: string[];
  compilerHints: string[];
  qualityGates: Record<string, unknown>;
  sceneExpectations: string[];
  trialExpectations: Record<string, unknown>;
  templateCount: number;
  activeTemplateCount: number;
}

export interface RuntimeCompilerContract {
  contractVersion: string;
  strategy: string;
  fallbackStrategy: string;
  promptAsset: string;
  requiredFields: string[];
  optionalFields: string[];
  invariants: string[];
  qualityGates: string[];
  repairPolicy: Record<string, unknown>;
  availableDomains: DomainPackRecord[];
  availableCapabilities: RuntimeCapabilityDriver[];
}

export interface RuntimeTaskSpec {
  id: string;
  title: string;
  description?: string | null;
  goal: string;
  domain: string;
  status: string;
  sourceKind: string;
  sourceText?: string | null;
  inputs: Record<string, unknown>;
  constraints: Record<string, unknown>;
  successCriteria: Record<string, unknown>;
  approvalPolicy: Record<string, unknown>;
  outputContract: Record<string, unknown>;
  preferredCapabilities: string[];
  preferredDomains: string[];
  compiledPayload: Record<string, unknown>;
  activePlanId?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface RuntimeExecutionPlan {
  id: string;
  taskSpecId: string;
  name: string;
  mode: string;
  status: string;
  version: number;
  approvalState: string;
  planBody: {
    steps: Array<Record<string, unknown>>;
    instruction?: string;
    domain?: string;
  };
  environmentRequirements: Record<string, unknown>;
  checkpoints: Array<Record<string, unknown>>;
  runtimeMetadata: Record<string, unknown>;
  compiledFromPatchId?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface RuntimeEpisode {
  id: string;
  taskSpecId: string;
  executionPlanId: string;
  mode: string;
  status: string;
  requestedBy?: string | null;
  requiresConfirmation: boolean;
  startedAt?: string | null;
  finishedAt?: string | null;
  resultSummary?: string | null;
  observations: Array<Record<string, unknown>>;
  actions: Array<Record<string, unknown>>;
  metrics: Record<string, unknown>;
  divergenceDetected: boolean;
  patchId?: string | null;
  runtimeMetadata: Record<string, unknown>;
  lastError?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface RuntimeSnapshot {
  id: string;
  taskSpecId?: string | null;
  executionPlanId?: string | null;
  executionEpisodeId?: string | null;
  source: string;
  environmentKey?: string | null;
  status: string;
  url?: string | null;
  title?: string | null;
  pageType?: string | null;
  capabilityHints: string[];
  observedEntities: Array<Record<string, unknown>>;
  affordances: Array<Record<string, unknown>>;
  runtimeMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface RuntimeCapabilityDriver {
  id: string;
  key: string;
  name: string;
  category: string;
  status: string;
  scope: string;
  description: string;
  safetyMode: string;
  supportsWrite: boolean;
  sceneTypes: string[];
  signalLabels: string[];
  supportedDomains?: string[];
  requiresSupervision?: boolean;
  executorMode?: string;
  replanOnError?: boolean;
  sceneRequired?: boolean;
  preferredTools?: string[];
  checkpointPolicy?: Record<string, unknown>;
  updatedAt: string;
}

export interface RuntimeEnvironmentAssessment {
  id: string;
  taskSpecId?: string | null;
  executionPlanId?: string | null;
  executionEpisodeId?: string | null;
  snapshotId?: string | null;
  environmentKey: string;
  sceneLabel: string;
  sceneType: string;
  status: string;
  confidence: number;
  summary: string;
  observedEntities: RuntimeObservedEntity[];
  affordances: RuntimeActionAffordance[];
  sceneProfile: RuntimeSceneProfile;
  plannerGuidance: RuntimePlannerGuidance;
  capabilityKeys: string[];
  observedLabels: string[];
  affordanceLabels: string[];
  driftSignals: string[];
  recommendedActions: string[];
  checkpoints?: Array<Record<string, unknown>>;
  environmentRequirements?: Record<string, unknown>;
  notes?: string[];
  auditMetadata?: Record<string, unknown>;
  updatedAt: string;
}

export interface RuntimeObservedEntity {
  kind: string;
  label: string;
  entityId?: string | null;
  role?: string | null;
  confidence?: number | null;
  state?: string | null;
  interactive: boolean;
  signals: string[];
  locator: Record<string, unknown>;
  attributes: Record<string, unknown>;
}

export interface RuntimeActionAffordance {
  kind: string;
  label: string;
  action: string;
  target?: string | null;
  confidence?: number | null;
  enabled: boolean;
  requiresConfirmation: boolean;
  signals: string[];
  locator: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface RuntimeSceneProfile {
  source: string;
  sceneType: string;
  interactionMode: string;
  volatility: string;
  authState: string;
  entityCount: number;
  affordanceCount: number;
  primaryTargets: string[];
  signals: string[];
  blockers: string[];
  evidence: Record<string, unknown>;
}

export interface RuntimePlannerGuidance {
  posture: string;
  requiredCapabilities: string[];
  insertedCapabilities: string[];
  preferredNextActions: string[];
  requiresSceneAssessment: boolean;
  requiresHumanReview: boolean;
  shouldCheckpoint: boolean;
  rationale: string[];
}

export interface RuntimeTemplate {
  id: string;
  templateKey: string;
  name: string;
  domain: string;
  status: string;
  version: number;
  sourceTaskSpecId?: string | null;
  templateBody: Record<string, unknown>;
  activationStrategy: Record<string, unknown>;
  validationSummary?: string | null;
  lastValidatedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface RuntimePatch {
  id: string;
  title: string;
  patchKind: string;
  status: string;
  templateId?: string | null;
  taskSpecId?: string | null;
  executionPlanId?: string | null;
  executionEpisodeId?: string | null;
  proposedBy?: string | null;
  reviewedBy?: string | null;
  reviewedAt?: string | null;
  appliedAt?: string | null;
  divergenceSummary?: string | null;
  rationale?: string | null;
  patchBody: Record<string, unknown>;
  runtimeMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface LearningDraft {
  id: string;
  content: string;
  tags: string[];
  sourceTaskId?: string | null;
  consolidatedAt?: string | null;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface RuntimeLearningOutcome {
  episode: RuntimeEpisode;
  template?: RuntimeTemplate | null;
  patch?: RuntimePatch | null;
  learningDraft?: LearningDraft | null;
  approval?: {
    id: string;
    targetType: string;
    targetId: string;
    title: string;
    status: string;
    requestedBy?: string | null;
    reviewedBy?: string | null;
    reviewedAt?: string | null;
    payload?: Record<string, unknown>;
    notes?: string | null;
    createdAt?: string;
    updatedAt?: string;
  } | null;
  templateApproval?: RuntimeLearningOutcome["approval"] | null;
  skillHealth?: Record<string, unknown> | null;
}

export interface RuntimeEpisodeReplay {
  episode: RuntimeEpisode;
  taskSpec?: RuntimeTaskSpec | null;
  executionPlan?: RuntimeExecutionPlan | null;
  snapshots: RuntimeSnapshot[];
  patch?: RuntimePatch | null;
  template?: RuntimeTemplate | null;
  approval?: RuntimeLearningOutcome["approval"] | null;
  diagnostics: TimelineEvent[];
  notes: string[];
}

export interface RuntimeEnvironmentAssessmentRequest {
  taskSpecId?: string;
  executionPlanId?: string;
  executionEpisodeId?: string;
  snapshotId?: string;
  snapshot?: Partial<RuntimeSnapshot>;
  compilerPayload?: Record<string, unknown>;
  planContext?: Record<string, unknown>;
}

export interface RuntimePlanReplanRequest {
  executionPlanId: string;
  taskSpecId?: string;
  executionEpisodeId?: string;
  snapshotId?: string;
  snapshot?: Partial<RuntimeSnapshot>;
  trigger?: string;
  reason?: string;
  notes?: string;
  requestedBy?: string;
  preferredCapabilityKeys?: string[];
  compilerPayload?: Record<string, unknown>;
  planContext?: Record<string, unknown>;
  runtimeMetadata?: Record<string, unknown>;
  checkpoints?: Array<Record<string, unknown>>;
  preserveActivePlan?: boolean;
}

export interface RuntimePlanReplanResult {
  id: string;
  taskSpecId?: string | null;
  baseExecutionPlanId: string;
  executionPlan: RuntimeExecutionPlan;
  status: string;
  trigger: string;
  summary: string;
  compilerNotes: string[];
  recommendedCapabilityKeys: string[];
  environmentAssessment?: RuntimeEnvironmentAssessment | null;
  patch?: RuntimePatch | null;
  auditMetadata?: Record<string, unknown>;
  createdAt: string;
}

export interface RuntimePlanLaunchResult {
  taskId: string;
  taskType: string;
  priority: number;
  queueDepth: number;
  taskSpecId: string;
  executionPlanId: string;
  executionEpisode: RuntimeEpisode;
}

export interface SyncBacklogItem {
  id: string;
  target: string;
  entityType: string;
  entityId?: string | null;
  status: string;
  attemptCount: number;
  protocolVersion?: string | null;
  deliveryMode?: string | null;
  lastAttemptedAt?: string | null;
  nextAttemptAt?: string | null;
  payloadSummary?: string | null;
  lastError?: string | null;
  payload?: Record<string, unknown>;
  targetMetadata?: Record<string, unknown>;
  updatedAt: string;
}

export interface SyncStatusSnapshot {
  enabled: boolean;
  mode: "local_only" | "remote_ready" | "remote_unavailable";
  remoteAvailable: boolean;
  protocolVersion?: string | null;
  source?: string | null;
  target?: Record<string, unknown>;
  pendingCount: number;
  syncedCount?: number;
  failedDeliveryCount?: number;
  deferredCount?: number;
  backlogTotal?: number;
  lastAttemptAt?: string | null;
  lastSuccessAt?: string | null;
  latestError?: string | null;
  nextAttemptAt?: string | null;
  byStatus?: Record<string, number>;
  recentErrors: string[];
}

export interface SyncFlushResult {
  attempted: number;
  synced: number;
  failed: number;
  remoteAvailable: boolean;
  message: string;
}

export interface RuntimeWorkspaceData {
  compilerContract?: RuntimeCompilerContract | null;
  domainPacks: DomainPackRecord[];
  taskSpecs: RuntimeTaskSpec[];
  plans: RuntimeExecutionPlan[];
  episodes: RuntimeEpisode[];
  snapshots: RuntimeSnapshot[];
  capabilityDrivers: RuntimeCapabilityDriver[];
  environmentAssessments: RuntimeEnvironmentAssessment[];
  templates: RuntimeTemplate[];
  patches: RuntimePatch[];
  replans: RuntimePlanReplanResult[];
}

export interface CompileTaskRequest {
  instruction: string;
  title?: string;
  description?: string;
  domainHint?: string;
  inputs?: Record<string, unknown>;
  constraints?: Record<string, unknown>;
  preferredCapabilities?: string[];
}

export interface CompileTaskResponse {
  domainPack: DomainPackRecord;
  compilerNotes: string[];
  taskSpec: RuntimeTaskSpec;
  executionPlan?: RuntimeExecutionPlan | null;
}
