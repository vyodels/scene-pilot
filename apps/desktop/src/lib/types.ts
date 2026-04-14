export type WorkspaceTab =
  | "dashboard"
  | "candidates"
  | "workflows"
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
  kind: "skill" | "workflow" | "system_command" | "candidate_override";
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
