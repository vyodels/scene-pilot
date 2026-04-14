export type WorkspaceTab =
  | "dashboard"
  | "runtime"
  | "trials"
  | "templates"
  | "patches"
  | "domains"
  | "recruiting"
  | "skills"
  | "approvals"
  | "monitor"
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
  kind: "skill" | "workflow" | "workflow_patch" | "system_command" | "candidate_override";
  title: string;
  detail: string;
  requester: string;
  status: ApprovalStatus;
  createdAt: string;
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
  defaultCapabilities: string[];
  sampleTasks: string[];
  defaultConstraints: Record<string, unknown>;
  defaultOutputContract: Record<string, unknown>;
  templateKeys: string[];
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
  skillHealth?: Record<string, unknown> | null;
}

export interface RuntimeWorkspaceData {
  domainPacks: DomainPackRecord[];
  taskSpecs: RuntimeTaskSpec[];
  plans: RuntimeExecutionPlan[];
  episodes: RuntimeEpisode[];
  snapshots: RuntimeSnapshot[];
  templates: RuntimeTemplate[];
  patches: RuntimePatch[];
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
