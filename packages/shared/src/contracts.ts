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
