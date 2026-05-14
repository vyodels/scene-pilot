import type {
  AgentDefinition as SharedAgentDefinition,
  AgentDefinitionConfig as SharedAgentDefinitionConfig,
  AgentProductBinding as SharedAgentProductBinding,
  ApplicationStatusTransition,
  CompileTaskRequest as SharedCompileTaskRequest,
  CompileTaskResponse as SharedCompileTaskResponse,
  DomainPackRecord as SharedDomainPackRecord,
  JobDescriptionPageParams as SharedJobDescriptionPageParams,
  JobDescriptionPageRecord as SharedJobDescriptionPageRecord,
  JobDescriptionSummaryRecord as SharedJobDescriptionSummaryRecord,
  LearningDraft as SharedLearningDraft,
  RuntimeActionAffordance as SharedRuntimeActionAffordance,
  RuntimeCapabilityDriver as SharedRuntimeCapabilityDriver,
  RuntimeCompilerContract as SharedRuntimeCompilerContract,
  RuntimeEnvironmentAssessment as SharedRuntimeEnvironmentAssessment,
  RuntimeEnvironmentAssessmentRequest as SharedRuntimeEnvironmentAssessmentRequest,
  RuntimeEpisode as SharedRuntimeEpisode,
  RuntimeEpisodeReplay as SharedRuntimeEpisodeReplay,
  RuntimeExecutionPlan as SharedRuntimeExecutionPlan,
  RuntimeLearningOutcome as SharedRuntimeLearningOutcome,
  RuntimeObservedEntity as SharedRuntimeObservedEntity,
  RuntimePatch as SharedRuntimePatch,
  RuntimePlanLaunchResult as SharedRuntimePlanLaunchResult,
  RuntimePlanReplanRequest as SharedRuntimePlanReplanRequest,
  RuntimePlanReplanResult as SharedRuntimePlanReplanResult,
  RuntimePlannerGuidance as SharedRuntimePlannerGuidance,
  RuntimeSceneProfile as SharedRuntimeSceneProfile,
  RuntimeSnapshot as SharedRuntimeSnapshot,
  RuntimeTaskSpec as SharedRuntimeTaskSpec,
  RuntimeTemplate as SharedRuntimeTemplate,
  RuntimeWorkspaceData as SharedRuntimeWorkspaceData,
} from "@recruit-agent/shared";

export type WorkspaceTab =
  | "home"
  | "applicationFunnel"
  | "applicationFollowUp"
  | "jdManagement"
  | "agents"
  | "settings";

export type ProviderKind = "openai-compatible" | "anthropic";
export type ApiTransport = "http" | "offline";
export type HealthStatus = "healthy" | "warning" | "critical";
export type ApprovalStatus = "pending" | "approved" | "rejected";
export type ApplicationStatus = string;
export type AgentKind = "assistant" | "autonomous";
export type ChatOverlayPanelKey =
  | "conversation"
  | "config"
  | "capabilities"
  | "outputs"
  | "runs";

export interface PersonSummaryRecord {
  personId?: string | null;
  platformCandidateId?: string | null;
  name: string;
  title: string;
  location: string;
  age?: number | null;
  experienceYears: number | null;
  education?: string | null;
  tags: string[];
  contactInfo: Record<string, unknown>;
  resumePath?: string | null;
  onlineResumeText?: string | null;
}

export type JobDescriptionSummaryRecord = SharedJobDescriptionSummaryRecord;
export type JobDescriptionPageRecord = SharedJobDescriptionPageRecord;
export type JobDescriptionPageParams = SharedJobDescriptionPageParams;

export interface JobDescriptionFunnelStepRecord {
  key: string;
  label: string;
  value: number;
  percent: number;
}

export interface JobDescriptionFunnelStatsRecord {
  jobDescriptionId: string;
  steps: JobDescriptionFunnelStepRecord[];
  applications: number;
  communicating: number;
  interviewing: number;
  offers: number;
  hired: number;
  withContact: number;
  withResume: number;
  withAiScore: number;
  byStatus: Record<string, number>;
}

export interface CommunicationTemplateRecord {
  templateId: string;
  name: string;
  category: string;
  messageType: string;
  body: string;
  variables: string[];
  status: string;
}

export interface CommunicationTemplateRenderRecord {
  templateId: string;
  name: string;
  category: string;
  messageType: string;
  content: string;
  missingVariables: string[];
}

export type JobDescriptionPayload = Pick<JobDescriptionSummaryRecord, "title"> &
  Partial<
    Pick<
      JobDescriptionSummaryRecord,
      | "companyName"
      | "department"
      | "location"
      | "employmentType"
      | "headcount"
      | "salaryMin"
      | "salaryMax"
      | "compensationText"
      | "experienceRequirement"
      | "educationRequirement"
      | "summary"
      | "description"
      | "requirements"
      | "benefitTags"
      | "detailMetadata"
      | "status"
      | "source"
    >
  >;

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

export interface ApplicationRecord {
  id: string;
  applicationId: string;
  personId?: string | null;
  jobDescriptionId?: string | null;
  platform: string;
  currentStatus: ApplicationStatus;
  stageKey: string;
  deepestMilestone?: string | null;
  matchScore: number | null;
  nextAction: string;
  summary: string;
  resumeAvailable: boolean;
  person: PersonSummaryRecord;
  jobDescription: JobDescriptionSummaryRecord;
  stateSnapshot?: ApplicationStateSnapshotRecord;
  contactSnapshot: Record<string, unknown>;
  resumeSnapshot: Record<string, unknown>;
  aiScores?: Record<string, unknown>;
  cooldownUntil?: string;
  lastContactedAt?: string;
}

export interface ApplicationStateSnapshotRecord {
  currentPhaseKey?: string | null;
  currentPhaseLabel?: string | null;
  currentStageKey?: string | null;
  currentStageLabel?: string | null;
  contactStatus?: string | null;
  contactChannels: string[];
  contactAcquired: boolean;
  resumeStatus?: string | null;
  aiAssessmentStatus?: string | null;
  humanAssessmentStatus?: string | null;
  operatorFlags: string[];
  nextRecommendedStages: string[];
  interviewPlan: Record<string, unknown>;
  latestNote?: string | null;
  latestTransitionAt?: string | null;
  latestTransitionSource?: string | null;
  snapshotMetadata: Record<string, unknown>;
}

export interface ApplicationStageEventRecord {
  id: string;
  applicationId: string;
  personId?: string | null;
  eventType: string;
  fromStatus?: string | null;
  toStatus: string;
  phaseKey?: string | null;
  phaseLabel?: string | null;
  stageKey?: string | null;
  stageLabel?: string | null;
  actor?: string | null;
  source: string;
  note?: string | null;
  payload: Record<string, unknown>;
  occurredAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ApplicationAssessmentRecord {
  id: string;
  applicationId: string;
  personId?: string | null;
  assessmentType: string;
  stageKey?: string | null;
  status: string;
  decision?: string | null;
  score?: number | null;
  summary?: string | null;
  evidenceRefs: Array<unknown>;
  metadata: Record<string, unknown>;
  createdBy?: string | null;
  reviewedBy?: string | null;
  reviewedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ApplicationAssignmentRecord {
  id: string;
  applicationId: string;
  personId?: string | null;
  assignee: string;
  ownerRole: string;
  status: string;
  note?: string | null;
  assignmentMetadata: Record<string, unknown>;
  assignedAt?: string | null;
  releasedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ResumeArtifactRecord {
  id: string;
  applicationId: string;
  personId?: string | null;
  source: string;
  artifactType: string;
  fileName?: string | null;
  filePath?: string | null;
  extractedText?: string | null;
  contactSnapshot: Record<string, unknown>;
  artifactMetadata: Record<string, unknown>;
  capturedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ApplicationScorecardRecord {
  id: string;
  applicationId: string;
  personId?: string | null;
  stageKey?: string | null;
  source: string;
  rubricVersion: string;
  scoreTotal?: number | null;
  verdict?: string | null;
  summary?: string | null;
  dimensionScores: Record<string, unknown>;
  evidenceRefs: Array<unknown>;
  scorecardMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface ApplicationReviewDecisionRecord {
  id: string;
  applicationId: string;
  personId?: string | null;
  stageKey?: string | null;
  decision: string;
  rationale?: string | null;
  decisionSource: string;
  decidedBy?: string | null;
  scorecardId?: string | null;
  reviewMetadata: Record<string, unknown>;
  decidedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface TalentPoolSyncRecord {
  id: string;
  applicationId: string;
  personId?: string | null;
  destination: string;
  status: string;
  externalRef?: string | null;
  payloadSnapshot: Record<string, unknown>;
  errorMessage?: string | null;
  syncedAt?: string | null;
  lastAttemptedAt?: string | null;
  syncMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface BlueprintNodeSummary {
  id: string;
  name: string;
  kind: "discover" | "screen" | "communicate" | "resume" | "score" | "review";
  status: "idle" | "running" | "blocked" | "approved";
  owner: string;
  description: string;
}

export interface PlaybookDefinition {
  id: string;
  name: string;
  description?: string | null;
  scopeKind: string;
  scopeRef?: string | null;
  status: "draft" | "active" | "archived";
  version: string;
  nodes: BlueprintNodeSummary[];
  updatedAt: string;
}

export interface SkillRecord {
  id: string;
  skillId: string;
  name: string;
  description?: string;
  category?: string;
  version: string;
  status: "draft" | "pending_review" | "approved" | "active" | "degraded" | "disabled";
  boundStage: string;
  platform: string;
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  strategy?: Record<string, unknown>;
  executionHints?: Record<string, unknown>;
  healthCheckConfig?: Record<string, unknown>;
  riskLevel?: string;
  skillMetadata?: Record<string, unknown>;
  health: HealthStatus;
  lastCheckedAt: string;
  summary: string;
}

export type ApprovalSurface = "runtime" | "evolution";

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
  surface: ApprovalSurface;
  relatedApplicationId?: string | null;
  sourceKind?: AgentKind | string | null;
  runPk?: string | null;
  turnPk?: string | null;
  toolName?: string | null;
}

export interface ExecutionTraceRecord {
  id: string;
  sessionId: string;
  runId?: string | null;
  personId?: string | null;
  applicationId?: string | null;
  lane: string;
  traceKind: string;
  status: string;
  title: string;
  summary?: string | null;
  rawTrace: Record<string, unknown>;
  distilledTrace: Record<string, unknown>;
  outcome: Record<string, unknown>;
  traceMetadata: Record<string, unknown>;
  startedAt?: string | null;
  finishedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ExecutionGraphProjectionRecord {
  id: string;
  runId?: string | null;
  personId?: string | null;
  applicationId?: string | null;
  graphKind: string;
  title: string;
  summary?: string | null;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  renderedText?: string | null;
  graphMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface StrategyFragmentRecord {
  id: string;
  agentDefinitionId: string;
  runId?: string | null;
  personId?: string | null;
  jobDescriptionId?: string | null;
  scope: string;
  fragmentKind: string;
  title: string;
  summary?: string | null;
  content: Record<string, unknown>;
  evidence: Record<string, unknown>;
  status: string;
  adoptionCount: number;
  lastAppliedAt?: string | null;
  fragmentMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface OperatorInteractionRecord {
  id: string;
  sessionId: string;
  runId?: string | null;
  checkpointId?: string | null;
  approvalId?: string | null;
  personId?: string | null;
  applicationId?: string | null;
  lane: string;
  interactionType: string;
  status: string;
  title: string;
  agentPrompt: string;
  suggestedOptions: Array<Record<string, unknown>>;
  operatorResponse: Record<string, unknown>;
  effectSummary?: string | null;
  scope: string;
  interactionMetadata: Record<string, unknown>;
  surfacedAt: string;
  resolvedAt?: string | null;
  resolvedBy?: string | null;
  createdAt: string;
  updatedAt: string;
}

export type AgentDefinitionConfig = SharedAgentDefinitionConfig;
export type AgentDefinitionRecord = SharedAgentDefinition;
export type AgentProductBindingRecord = SharedAgentProductBinding;

export interface ApplicationConversationEntry {
  id: string;
  applicationId?: string | null;
  direction: string;
  content: string;
  messageType: string;
  platform: string;
  metadata?: Record<string, unknown>;
  timestamp?: string | null;
}

export interface ApplicationThreadRecord {
  applicationId?: string | null;
  personId?: string | null;
  jobDescriptionId?: string | null;
  application: ApplicationRecord;
  sessionStatus: string;
  contextSummary?: string;
  facts: Record<string, unknown>;
  recentMessages: Array<Record<string, unknown>>;
  communicationLogs: ApplicationConversationEntry[];
  stateSnapshot: ApplicationStateSnapshotRecord;
  stageEvents: ApplicationStageEventRecord[];
  statusTransitions: ApplicationStatusTransition[];
  assessments: ApplicationAssessmentRecord[];
  assignments: ApplicationAssignmentRecord[];
  resumeArtifacts: ResumeArtifactRecord[];
  scorecards: ApplicationScorecardRecord[];
  reviewDecisions: ApplicationReviewDecisionRecord[];
  syncRecords: TalentPoolSyncRecord[];
  availableStatuses: string[];
  availableTransitions: Array<Record<string, unknown>>;
  runtimeApprovals: ApprovalItem[];
  runtimeInteractions: OperatorInteractionRecord[];
}

export type EvolutionArtifactKind = "skill_draft" | "prompt_patch" | "memory_policy_patch" | "playbook_patch" | "playbook_patch";
export type EvolutionArtifactStatus = "draft" | "pending_review" | "approved" | "applied" | "rejected" | "archived";

export interface EvolutionArtifactRecord {
  id: string;
  agentDefinitionId?: string | null;
  artifactKind: EvolutionArtifactKind;
  title: string;
  summary?: string | null;
  status: EvolutionArtifactStatus;
  relatedApplicationId?: string | null;
  relatedSkillId?: string | null;
  proposedBy?: string | null;
  reviewedBy?: string | null;
  reviewedAt?: string | null;
  appliedAt?: string | null;
  artifactBody: Record<string, unknown>;
  artifactMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
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

export type AgentConversationStatus =
  | "idle"
  | "active"
  | "running"
  | "queued"
  | "draft"
  | "waiting_human"
  | "blocked"
  | "completed"
  | "failed";
export type ChatMessageRole = "user" | "assistant" | "system" | "tool";
export type ChatMessageKind = "message" | "tool_use" | "tool_result" | "status";

export interface AgentDefinitionSummary {
  kind: AgentKind;
  name: string;
  description?: string | null;
  definitionKey?: string | null;
  productAdapterKey?: string | null;
  status: AgentSnapshot["status"] | string;
  health: HealthStatus;
  activeTask?: string | null;
  activeInstruction?: string | null;
  defaultModel?: string | null;
  pendingApprovals: number;
  unreadCount: number;
  updatedAt: string;
}

export interface AgentConversationSummary {
  id: string;
  agentKind: AgentKind;
  title: string;
  preview?: string | null;
  status: AgentConversationStatus;
  unreadCount: number;
  updatedAt: string;
  refId?: string | null;
}

export interface AgentConversationMessage {
  id: string;
  conversationId: string;
  role: ChatMessageRole;
  kind: ChatMessageKind;
  content: string;
  createdAt: string;
  status?: "pending" | "sent" | "streaming" | "failed";
  title?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AgentConversationRecord {
  conversation: AgentConversationSummary;
  messages: AgentConversationMessage[];
}

export interface AgentRunRecord {
  id: string;
  agentKind: AgentKind;
  title: string;
  status: string;
  summary?: string | null;
  startedAt?: string | null;
  updatedAt: string;
  refId?: string | null;
}

export interface AgentMemorySummary {
  id: string;
  scope: "conversation" | "candidate" | "job" | "global";
  title: string;
  summary: string;
  status: string;
  source?: string | null;
  metadata?: Record<string, unknown>;
  updatedAt: string;
}

export interface AgentToolSummary {
  id: string;
  serverId?: string | null;
  serverName: string;
  name: string;
  description?: string | null;
  sourceKind: "business_tool" | "system_tool" | "mcp_tool" | "memory_tool" | string;
  source: string;
  status: string;
  riskLevel: string;
  businessTool?: boolean;
  businessDomain?: string | null;
  resourceTargetKind?: string | null;
  permissionScope?: string | null;
  capabilities: string[];
  inputSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
  parameters: Record<string, unknown>;
  toolMetadata: Record<string, unknown>;
  enabled: boolean;
  endpoint?: string | null;
}

export interface AgentWorkspaceRecord {
  agent: AgentDefinitionSummary;
  conversations: AgentConversationSummary[];
  runs: AgentRunRecord[];
  approvals: ApprovalItem[];
  memories: AgentMemorySummary[];
  skills: SkillRecord[];
  tools: AgentToolSummary[];
  agentDefinition: AgentDefinitionRecord;
  productBinding: AgentProductBindingRecord;
  definitionConfig: AgentDefinitionConfig;
  productAdapterConfig: {
    recruitingPolicy: RecruitingPolicyConfig;
    scoringRubric: string;
    triggers: Record<string, unknown>;
    approvalPolicy: Record<string, unknown>;
    contextPolicy: Record<string, unknown>;
    memoryPolicy: Record<string, unknown>;
    adapterMetadata: Record<string, unknown>;
    providerLabel?: string | null;
    modelLabel?: string | null;
  };
  config: {
    systemPrompt: string;
    scoringRubric: string;
    recruitingPolicy: RecruitingPolicyConfig;
    boundaries: string[];
    providerLabel?: string | null;
    modelLabel?: string | null;
  };
}

export interface RecruitingPolicyConfig {
  jdStandards: string;
  perJdEvaluation: string;
  onlineResumeCriteria: string;
  offlineResumeCriteria: string;
  communicationEvidence: string;
  compositeScoring: string;
  screeningRules: string;
  interviewScheduling: string;
  offerHandoff: string;
  scoreWeights: {
    jdMatch: number;
    onlineResume: number;
    offlineResume: number;
    communication: number;
    stability: number;
  };
  thresholds: {
    onlinePass: number;
    offlinePass: number;
    compositePass: number;
    manualReviewMin: number;
    interviewRecommend: number;
  };
}

export interface AssistantConversationRecord {
  conversationId: string;
  userId?: string | null;
  title: string;
  status: string;
}

export interface AssistantTurnStreamEvent {
  event: string;
  data: Record<string, unknown>;
  receivedAt: string;
}

export interface AssistantMessageRequest {
  conversationId: string;
  message: string;
}

export interface AssistantMessageRequestResult {
  conversationId: string;
  requestId?: string | null;
  status: string;
}

export interface AutonomousRunStartRequest {
  title: string;
  instruction: string;
  kind?: string | null;
  jdId?: string | null;
  candidateCountTarget?: number | null;
  conversationId?: string | null;
  constraints?: Record<string, unknown>;
  successCriteria?: Record<string, unknown>;
  contextHints?: Record<string, unknown>;
  trialBudget?: Record<string, unknown>;
}

export interface AutonomousRunStartResult {
  conversationId: string;
  runId?: string | null;
  status: string;
}

export interface AgentStreamEvent {
  id: string;
  message: string;
  level: AgentEvent["level"];
  source: string;
  at: string;
  role?: ChatMessageRole;
  kind?: ChatMessageKind;
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
  adaptiveStage: string;
  priority: number;
  status: string;
  attempts: number;
  scheduledFor?: string | null;
  lockedAt?: string | null;
  lockedBy?: string | null;
  personId?: string | null;
  applicationId?: string | null;
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
  apiKey?: string;
  timeoutSeconds: number;
  enabled: boolean;
  temperature: number;
}

export interface ProviderHealthcheckResult {
  ok: boolean;
  status: string;
  latencyMs?: number | null;
  message?: string | null;
}

export interface McpToolRecord {
  id: string;
  serverId: string;
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  capabilities: string[];
  enabled: boolean;
  riskLevel: string;
  remoteName?: string | null;
  toolMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface McpServerRecord {
  id: string;
  serverKey: string;
  name: string;
  transportKind: string;
  protocol: string;
  endpoint: string;
  enabled: boolean;
  presetKey?: string | null;
  authConfig: Record<string, unknown>;
  serverMetadata: Record<string, unknown>;
  healthStatus: string;
  healthError?: string | null;
  lastHealthAt?: string | null;
  tools: McpToolRecord[];
  createdAt: string;
  updatedAt: string;
}

export interface McpPresetTemplateRecord {
  key: string;
  name: string;
  description: string;
  transportKind: string;
  protocol: string;
  endpointExample: string;
  tools: Array<{
    name: string;
    description: string;
    parameters: Record<string, unknown>;
    capabilities: string[];
    enabled: boolean;
    riskLevel: string;
    remoteName?: string | null;
    toolMetadata: Record<string, unknown>;
  }>;
}

export interface SettingsSnapshot {
  locale: string;
  timezone: string;
  intranetEnabled: boolean;
  desktopApprovalsOnly: boolean;
  autonomyEnabled: boolean;
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
    maxConcurrentRuns: number;
    minFunnelCandidates: number;
  };
  userProfile: {
    nickname: string;
    avatarUrl?: string | null;
  };
}

export interface DashboardSummary {
  metrics: MetricSummary[];
  pipeline: PipelineStage[];
  timeline: TimelineEvent[];
  alerts: TimelineEvent[];
  applications: ApplicationRecord[];
  applicationFollowUpSummaryDefinitions: ApplicationFollowUpSummaryDefinition[];
  playbooks: PlaybookDefinition[];
  skills: SkillRecord[];
  approvals: ApprovalItem[];
  agent: AgentSnapshot;
  settings: SettingsSnapshot;
}

export interface ApplicationFollowUpSummaryDefinition {
  key: string;
  label: string;
  summary: string;
  relation?: string | null;
  matchingMode: "all" | "status_set";
  includeStatuses: string[];
  excludeStatuses: string[];
  includeLabels: string[];
  excludeLabels: string[];
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
  applicationId?: string;
}

export interface AgentTaskEnqueueResult {
  taskId: string;
  taskType: string;
  priority: number;
  queueDepth: number;
}

export type DomainPackRecord = SharedDomainPackRecord;
export type RuntimeCompilerContract = SharedRuntimeCompilerContract;
export type RuntimeTaskSpec = SharedRuntimeTaskSpec;
export type RuntimeExecutionPlan = SharedRuntimeExecutionPlan;
export type RuntimeEpisode = SharedRuntimeEpisode;
export type RuntimeSnapshot = SharedRuntimeSnapshot;
export type RuntimeCapabilityDriver = SharedRuntimeCapabilityDriver;
export type RuntimeEnvironmentAssessment = SharedRuntimeEnvironmentAssessment;
export type RuntimeObservedEntity = SharedRuntimeObservedEntity;
export type RuntimeActionAffordance = SharedRuntimeActionAffordance;
export type RuntimeSceneProfile = SharedRuntimeSceneProfile;
export type RuntimePlannerGuidance = SharedRuntimePlannerGuidance;
export type RuntimeTemplate = SharedRuntimeTemplate;
export type RuntimePatch = SharedRuntimePatch;
export type LearningDraft = SharedLearningDraft;
export type RuntimeLearningOutcome = SharedRuntimeLearningOutcome;
export type RuntimeEpisodeReplay = SharedRuntimeEpisodeReplay;
export type RuntimeEnvironmentAssessmentRequest = SharedRuntimeEnvironmentAssessmentRequest;
export type RuntimePlanReplanRequest = SharedRuntimePlanReplanRequest;
export type RuntimePlanReplanResult = SharedRuntimePlanReplanResult;
export type RuntimePlanLaunchResult = SharedRuntimePlanLaunchResult;
export type RuntimeWorkspaceData = SharedRuntimeWorkspaceData;
export type CompileTaskRequest = SharedCompileTaskRequest;
export type CompileTaskResponse = SharedCompileTaskResponse;

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
