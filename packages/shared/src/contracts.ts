export const applicationStatuses = [
  "discovered",
  "online_resume_fetching",
  "online_resume_acquired",
  "online_resume_passed",
  "online_resume_rejected",
  "offline_resume_fetching",
  "offline_resume_acquired",
  "offline_resume_passed",
  "offline_resume_rejected",
  "human_screening",
  "human_screening_passed",
  "human_screening_rejected",
  "profile_ready",
  "interview_pending",
  "interview_scheduled",
  "interview_passed",
  "interview_rejected",
  "offer_sent",
  "offer_accepted",
  "offer_rejected",
  "exception_closed",
] as const;

export type ApplicationStatus = (typeof applicationStatuses)[number];

export const skillStatuses = [
  "draft",
  "pending_review",
  "approved",
  "active",
  "degraded",
  "disabled",
] as const;

export type SkillStatus = (typeof skillStatuses)[number];

export type ApplicationRecord = {
  id: string;
  applicationId: string;
  personId?: string;
  jobDescriptionId: string;
  platform: string;
  currentStatus: ApplicationStatus;
  currentStageKey: string;
  lastContactedAt?: string;
  updatedAt: string;
  aiDecision?: "pass" | "reject" | "review";
};

export type JobDescriptionSummaryRecord = {
  jobDescriptionId?: string | null;
  title: string;
  companyName?: string | null;
  department?: string | null;
  location?: string | null;
  employmentType?: string | null;
  headcount?: number | null;
  salaryMin?: number | null;
  salaryMax?: number | null;
  compensationText?: string | null;
  experienceRequirement?: string | null;
  educationRequirement?: string | null;
  summary?: string | null;
  description?: string | null;
  requirements?: string | null;
  benefitTags: string[];
  detailMetadata: Record<string, unknown>;
  status?: string | null;
  source?: string | null;
  createdAt?: string | number | null;
  updatedAt?: string | number | null;
};

export type JobDescriptionPageRecord = {
  items: JobDescriptionSummaryRecord[];
  total: number;
  limit: number;
  offset: number;
  hasNext: boolean;
};

export type JobDescriptionPageParams = {
  limit?: number;
  offset?: number;
  status?: string | null;
  location?: string | null;
  department?: string | null;
  owner?: string | null;
  keyword?: string | null;
  applicantKeyword?: string | null;
};

export type PlaybookRecord = {
  id: string;
  name: string;
  scopeKind: "global" | "jd" | "environment";
  scopeRef?: string;
  status: "draft" | "active" | "archived";
  version: number;
  updatedAt: string;
};

export type SkillRecord = {
  id: string;
  skillId: string;
  name: string;
  version: string;
  status: SkillStatus;
  platform: string;
  boundToStage: string;
  lastHealthStatus: "healthy" | "warning" | "failed" | "unknown";
  updatedAt: string;
};

export type ApprovalRecord = {
  id: string;
  type: "skill_activation" | "playbook_change" | "system_command";
  title: string;
  status: "pending" | "approved" | "rejected";
  createdAt: string;
  requestedBy: string;
  summary: string;
};

export type MetricSnapshot = {
  label: string;
  value: string;
  trend: string;
};

export type AgentEvent = {
  id: string;
  level: "info" | "warning" | "error";
  category: "scheduler" | "runtime" | "playbook" | "approval" | "sync";
  message: string;
  timestamp: string;
};

export type SettingsRecord = {
  appMode: "local" | "hybrid";
  defaultProvider: "openai_compatible" | "anthropic";
  intranetEnabled: boolean;
  enableAutoLearning: boolean;
  enableOutboundMessaging: boolean;
  enableSystemCommands: boolean;
};

export type DomainPackRecord = {
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
};

export type RuntimeCompilerContract = {
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
};

export type RuntimeTaskSpec = {
  id: string;
  title: string;
  description?: string | null;
  instruction: string;
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
};

export type RuntimeExecutionPlan = {
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
};

export type RuntimeEpisode = {
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
};

export type RuntimeSnapshot = {
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
};

export type RuntimeCapabilityDriver = {
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
};

export type RuntimeEnvironmentAssessment = {
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
};

export type RuntimeObservedEntity = {
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
};

export type RuntimeActionAffordance = {
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
};

export type RuntimeSceneProfile = {
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
};

export type RuntimePlannerGuidance = {
  posture: string;
  requiredCapabilities: string[];
  insertedCapabilities: string[];
  preferredNextActions: string[];
  requiresSceneAssessment: boolean;
  requiresHumanReview: boolean;
  shouldCheckpoint: boolean;
  rationale: string[];
};

export type AgentDefinitionConfig = {
  identity: Record<string, unknown>;
  systemPrompt: string;
  duties: string[];
  boundaries: string[];
  successCriteria: string[];
  toolScope: Record<string, unknown>;
  permissionPolicy: Record<string, unknown>;
  outputPolicy: Record<string, unknown>;
  budgetPolicy: Record<string, unknown>;
  modelConfig: Record<string, unknown>;
  runtimeMetadata: Record<string, unknown>;
};

export type AgentDefinition = {
  id: string;
  key: string;
  name: string;
  description?: string | null;
  status: string;
  config: AgentDefinitionConfig;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type AgentProductBinding = {
  id?: string | null;
  agentKind: "assistant" | "autonomous" | string;
  productAdapterKey: string;
  agentDefinitionId?: string | null;
  agentDefinitionKey?: string | null;
  status: string;
  adapterConfig: Record<string, unknown>;
  bindingMetadata: Record<string, unknown>;
  updatedAt?: string | null;
};

export type RuntimeTemplate = {
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
};

export type RuntimePatch = {
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
};

export type LearningDraft = {
  id: string;
  content: string;
  tags: string[];
  sourceTaskId?: string | null;
  consolidatedAt?: string | null;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
};

export type RuntimeLearningOutcome = {
  episode: RuntimeEpisode;
  template?: RuntimeTemplate | null;
  patch?: RuntimePatch | null;
  learningDraft?: LearningDraft | null;
  approval?: RuntimeApprovalSummary | null;
  templateApproval?: RuntimeApprovalSummary | null;
  skillHealth?: Record<string, unknown> | null;
};

export type RuntimeApprovalSummary = {
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
};

export type RuntimeTimelineEvent = {
  id: string;
  label: string;
  detail: string;
  at: string;
  tone: "positive" | "neutral" | "warning" | "critical";
};

export type RuntimeEpisodeReplay = {
  episode: RuntimeEpisode;
  taskSpec?: RuntimeTaskSpec | null;
  executionPlan?: RuntimeExecutionPlan | null;
  snapshots: RuntimeSnapshot[];
  patch?: RuntimePatch | null;
  template?: RuntimeTemplate | null;
  approval?: RuntimeApprovalSummary | null;
  diagnostics: RuntimeTimelineEvent[];
  notes: string[];
};

export type RuntimeEnvironmentAssessmentRequest = {
  taskSpecId?: string;
  executionPlanId?: string;
  executionEpisodeId?: string;
  snapshotId?: string;
  snapshot?: Partial<RuntimeSnapshot>;
  compilerPayload?: Record<string, unknown>;
  planContext?: Record<string, unknown>;
};

export type RuntimePlanReplanRequest = {
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
};

export type RuntimePlanReplanResult = {
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
};

export type RuntimePlanLaunchResult = {
  taskId: string;
  taskType: string;
  priority: number;
  queueDepth: number;
  taskSpecId: string;
  executionPlanId: string;
  executionEpisode: RuntimeEpisode;
};

export type RuntimeWorkspaceData = {
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
};

export type CompileTaskRequest = {
  instruction: string;
  title?: string;
  description?: string;
  domainHint?: string;
  inputs?: Record<string, unknown>;
  constraints?: Record<string, unknown>;
  preferredCapabilities?: string[];
};

export type CompileTaskResponse = {
  domainPack: DomainPackRecord;
  compilerNotes: string[];
  taskSpec: RuntimeTaskSpec;
  executionPlan?: RuntimeExecutionPlan | null;
};
