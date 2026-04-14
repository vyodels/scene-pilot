import type {
  AgentEvent,
  ApprovalRecord,
  CandidateRecord,
  MetricSnapshot,
  SettingsRecord,
  SkillRecord,
  WorkflowRecord,
} from "./contracts";

const now = new Date().toISOString();

export const mockCandidates: CandidateRecord[] = [
  {
    id: "cand_001",
    name: "Chen Miao",
    platform: "boss",
    jdId: "jd_frontend_001",
    status: "screening",
    currentWorkflowNode: "initial_screening",
    updatedAt: now,
    aiDecision: "review",
  },
  {
    id: "cand_002",
    name: "Lin Qiao",
    platform: "boss",
    jdId: "jd_backend_001",
    status: "waiting_reply",
    currentWorkflowNode: "waiting_reply",
    lastContactedAt: now,
    updatedAt: now,
    aiDecision: "pass",
  },
];

export const mockWorkflows: WorkflowRecord[] = [
  {
    id: "wf_frontend",
    name: "Frontend Hiring Flow",
    jdId: "jd_frontend_001",
    status: "active",
    version: 3,
    updatedAt: now,
  },
  {
    id: "wf_backend",
    name: "Backend Hiring Flow",
    jdId: "jd_backend_001",
    status: "draft",
    version: 1,
    updatedAt: now,
  },
];

export const mockSkills: SkillRecord[] = [
  {
    id: "skill_screening_boss",
    skillId: "boss_initial_screening",
    name: "Boss Screening",
    version: "1.2.0",
    status: "active",
    platform: "boss",
    boundToWorkflowNode: "initial_screening",
    lastHealthStatus: "healthy",
    updatedAt: now,
  },
  {
    id: "skill_followup_draft",
    skillId: "boss_followup_sequence",
    name: "Boss Follow-up",
    version: "0.3.0",
    status: "pending_review",
    platform: "boss",
    boundToWorkflowNode: "communicating",
    lastHealthStatus: "warning",
    updatedAt: now,
  },
];

export const mockApprovals: ApprovalRecord[] = [
  {
    id: "approval_001",
    type: "skill_activation",
    title: "Activate updated screening skill",
    status: "pending",
    createdAt: now,
    requestedBy: "agent",
    summary: "New selector fallback path discovered after Boss page layout change.",
  },
  {
    id: "approval_002",
    type: "workflow_change",
    title: "Change scoring threshold for frontend JD",
    status: "pending",
    createdAt: now,
    requestedBy: "hr_lead",
    summary: "Raise screening pass score from 7.0 to 7.5 for React roles.",
  },
];

export const mockMetrics: MetricSnapshot[] = [
  { label: "Candidates Today", value: "48", trend: "+12%" },
  { label: "Pass Rate", value: "31%", trend: "+4%" },
  { label: "Token Spend", value: "$18.20", trend: "-6%" },
  { label: "Skill Health", value: "96%", trend: "+1%" },
];

export const mockEvents: AgentEvent[] = [
  {
    id: "evt_001",
    level: "info",
    category: "scheduler",
    message: "Reply-priority queue resumed candidate cand_002.",
    timestamp: now,
  },
  {
    id: "evt_002",
    level: "warning",
    category: "approval",
    message: "Outbound messaging remains disabled by feature flag.",
    timestamp: now,
  },
];

export const mockSettings: SettingsRecord = {
  appMode: "local",
  defaultProvider: "openai_compatible",
  intranetEnabled: false,
  enableAutoLearning: false,
  enableOutboundMessaging: false,
  enableSystemCommands: false,
};

