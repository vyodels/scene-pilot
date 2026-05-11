import type {
  ApplicationStatusTransition,
  JobDescriptionPageParams as SharedJobDescriptionPageParams,
  JobDescriptionPageRecord as SharedJobDescriptionPageRecord,
  JobDescriptionSummaryRecord as SharedJobDescriptionSummaryRecord,
} from "@recruit-agent/shared";

export type WorkspaceTab =
  | "home"
  | "applicationFunnel"
  | "applicationFollowUp"
  | "jdManagement"
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
  | "runs"
  | "approvals"
  | "memory"
  | "skills"
  | "tools";

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

export interface MemoryDisclosureRecord {
  preview?: string;
  operatorSummary?: string;
  modelContext?: string;
  tiers: Array<Record<string, unknown>>;
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
}

export interface GoalSpecRecord {
  id: string;
  agentProfileId: string;
  title: string;
  goalText: string;
  goalKind: string;
  status: string;
  source: string;
  sourceText?: string | null;
  requestedBy?: string | null;
  constraints: Record<string, unknown>;
  successCriteria: Record<string, unknown>;
  contextHints: Record<string, unknown>;
  trialBudget: Record<string, unknown>;
  runPreferences: Record<string, unknown>;
  summary?: string | null;
  latestRunId?: string | null;
  lastActivityAt?: string | null;
  goalMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface ExecutionTraceRecord {
  id: string;
  sessionId: string;
  runId?: string | null;
  goalSpecId?: string | null;
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
  goalSpecId?: string | null;
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
  agentProfileId: string;
  goalSpecId?: string | null;
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
  goalSpecId?: string | null;
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

export interface RecruitAgentProfileRecord {
  id: string;
  agentKey: string;
  name: string;
  status: string;
  description?: string;
  isPrimary: boolean;
  roleDefinition: Record<string, unknown>;
  promptConfig: Record<string, unknown>;
  playbookBlueprint: Record<string, unknown>;
  memoryPolicy: Record<string, unknown>;
  dashboardConfig: Record<string, unknown>;
  channelConfig: Record<string, unknown>;
  agentMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface PersonMemoryRecord {
  id: string;
  agentProfileId: string;
  personId: string;
  status: string;
  memorySchemaVersion: string;
  summary?: string;
  rawContent: Record<string, unknown>;
  content: Record<string, unknown>;
  disclosure: MemoryDisclosureRecord;
  tokenEstimate: number;
  sourceCount: number;
  compactedAt?: string | null;
  compactedReason?: string | null;
  memoryMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface JobMemoryRecord {
  id: string;
  agentProfileId: string;
  jobDescriptionId: string;
  status: string;
  memorySchemaVersion: string;
  summary?: string;
  rawContent: Record<string, unknown>;
  content: Record<string, unknown>;
  disclosure: MemoryDisclosureRecord;
  tokenEstimate: number;
  sourceCount: number;
  compactedAt?: string | null;
  compactedReason?: string | null;
  memoryMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface AgentGlobalMemoryRecord {
  id: string;
  agentProfileId: string;
  status: string;
  memorySchemaVersion: string;
  summary?: string;
  rawContent: Record<string, unknown>;
  content: Record<string, unknown>;
  disclosure: MemoryDisclosureRecord;
  tokenEstimate: number;
  sourceCount: number;
  compactedAt?: string | null;
  compactedReason?: string | null;
  memoryMetadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

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
  agentProfileId?: string | null;
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

export interface AgentProfileSummary {
  kind: AgentKind;
  name: string;
  description?: string | null;
  status: AgentSnapshot["status"] | string;
  health: HealthStatus;
  activeTask?: string | null;
  activeGoal?: string | null;
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
  scope: "candidate" | "job" | "global";
  title: string;
  summary: string;
  status: string;
  updatedAt: string;
}

export interface AgentToolSummary {
  id: string;
  serverId?: string | null;
  serverName: string;
  name: string;
  riskLevel: string;
  businessTool?: boolean;
  businessDomain?: string | null;
  resourceTargetKind?: string | null;
  permissionScope?: string | null;
  enabled: boolean;
  endpoint?: string | null;
}

export interface SharedSceneTemplateRecord {
  key: string;
  title: string;
  summary: string;
  goalKind: string;
  defaultGoalText: string;
  requiresJd: boolean;
  supportsCandidateCountTarget: boolean;
  defaultCandidateCountTarget?: number | null;
  directRunnable: boolean;
  constraints: Record<string, unknown>;
  successCriteria: Record<string, unknown>;
  contextHints: Record<string, unknown>;
}

export interface AgentWorkspaceRecord {
  agent: AgentProfileSummary;
  conversations: AgentConversationSummary[];
  runs: AgentRunRecord[];
  approvals: ApprovalItem[];
  memories: AgentMemorySummary[];
  skills: SkillRecord[];
  tools: AgentToolSummary[];
  config: {
    systemPrompt: string;
    goalTemplate: string;
    scoringRubric: string;
    boundaries: string[];
    providerLabel?: string | null;
    modelLabel?: string | null;
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

export interface AutonomousGoalStartRequest {
  title: string;
  goalText: string;
  goalKind?: string | null;
  jdId?: string | null;
  candidateCountTarget?: number | null;
  conversationId?: string | null;
  constraints?: Record<string, unknown>;
  successCriteria?: Record<string, unknown>;
  contextHints?: Record<string, unknown>;
  trialBudget?: Record<string, unknown>;
}

export interface AutonomousGoalStartResult {
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
  key: "all" | "active" | "human" | "no_response" | "cooldown" | "archived" | "candidate_withdrew";
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
