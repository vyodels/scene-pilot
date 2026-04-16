export const candidateStatuses = [
  "discovered",
  "screening",
  "pending_communication",
  "communicating",
  "waiting_reply",
  "pending_resume",
  "scoring",
  "passed_to_talent_pool",
  "hr_review",
  "team_review",
  "interview_scheduled",
  "offer",
  "rejected",
  "cooldown",
  "timeout_closed",
] as const;

export type CandidateStatus = (typeof candidateStatuses)[number];

export const skillStatuses = [
  "draft",
  "pending_review",
  "approved",
  "active",
  "degraded",
  "disabled",
] as const;

export type SkillStatus = (typeof skillStatuses)[number];

export type CandidateRecord = {
  id: string;
  name: string;
  platform: string;
  jdId: string;
  currentStatus: CandidateStatus;
  currentStageKey: string;
  lastContactedAt?: string;
  updatedAt: string;
  aiDecision?: "pass" | "reject" | "review";
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
