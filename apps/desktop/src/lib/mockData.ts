import type {
  ApprovalItem,
  AgentSnapshot,
  CandidateRecord,
  DashboardSummary,
  SettingsSnapshot,
  SkillRecord,
  TimelineEvent,
  WorkflowDefinition,
} from "./types";

const now = new Date();
const iso = (offsetMinutes: number): string => new Date(now.getTime() + offsetMinutes * 60_000).toISOString();

const candidates: CandidateRecord[] = [
  {
    id: "cand-001",
    name: "Mia Chen",
    title: "Senior Frontend Engineer",
    platform: "Boss直聘",
    location: "Shanghai",
    status: "screening",
    workflowNode: "initial_screening",
    jdTitle: "Frontend Platform Engineer",
    matchScore: 92,
    experienceYears: 8,
    nextAction: "Verify system design depth and React performance examples.",
    summary: "Strong product sense, clear ownership, and good balance of UI craft and engineering depth.",
    tags: ["React", "Design Systems", "Performance"],
    resumeAvailable: true,
    lastContactedAt: iso(-120),
  },
  {
    id: "cand-002",
    name: "Jason Li",
    title: "Backend Engineer",
    platform: "Boss直聘",
    location: "Hangzhou",
    status: "pending_communication",
    workflowNode: "initiate_communication",
    jdTitle: "Platform Engineer",
    matchScore: 84,
    experienceYears: 6,
    nextAction: "Send outreach message with salary range and team scope.",
    summary: "Reliable service design experience with strong ownership in backend operations.",
    tags: ["Go", "PostgreSQL", "APIs"],
    resumeAvailable: false,
  },
  {
    id: "cand-003",
    name: "Luna Wang",
    title: "Product Manager",
    platform: "Boss直聘",
    location: "Beijing",
    status: "cooldown",
    workflowNode: "cooldown",
    jdTitle: "Product Lead",
    matchScore: 73,
    experienceYears: 7,
    nextAction: "Respect cooldown until the next contact window opens.",
    summary: "Rejected after communication. Store on hold and avoid repeated outreach.",
    tags: ["Discovery", "Roadmap", "Analytics"],
    resumeAvailable: true,
    cooldownUntil: iso(60 * 24 * 18),
    lastContactedAt: iso(-1440),
  },
];

const workflows: WorkflowDefinition[] = [
  {
    id: "wf-screening",
    name: "Discovery to Screening",
    jdTitle: "Frontend Platform Engineer",
    status: "active",
    version: "v1.3",
    updatedAt: iso(-180),
    nodes: [
      { id: "discover", name: "Discover candidates", kind: "discover", status: "approved", owner: "Scheduler", description: "Search and ingest candidate profiles." },
      { id: "initial_screening", name: "Initial screening", kind: "screen", status: "running", owner: "Agent", description: "Read resumes and evaluate against JD criteria." },
      { id: "initiate_communication", name: "Initiate communication", kind: "communicate", status: "idle", owner: "Agent", description: "Send outreach using approved message templates." },
      { id: "request_resume", name: "Request resume", kind: "resume", status: "idle", owner: "Agent", description: "Collect structured resume artifacts." },
      { id: "candidate_scoring", name: "Candidate scoring", kind: "score", status: "idle", owner: "Agent", description: "Produce scoring and reasoning payloads." },
      { id: "hr_review", name: "HR review", kind: "review", status: "blocked", owner: "Human", description: "Await approval before talent pool sync." },
    ],
  },
  {
    id: "wf-talent-pool",
    name: "Talent Pool Handoff",
    jdTitle: "Platform Engineer",
    status: "draft",
    version: "v0.8",
    updatedAt: iso(-75),
    nodes: [
      { id: "screen", name: "Screen", kind: "screen", status: "approved", owner: "Agent", description: "Score against criteria." },
      { id: "talent_pool_upload", name: "Upload to talent pool", kind: "review", status: "idle", owner: "Human", description: "Push qualified candidates to the internal system." },
    ],
  },
];

const skills: SkillRecord[] = [
  {
    id: "skill-001",
    name: "Boss Outreach Drafting",
    version: "1.2.0",
    status: "active",
    boundNode: "initiate_communication",
    platform: "Boss直聘",
    health: "healthy",
    lastCheckedAt: iso(-30),
    summary: "Produces short, respectful outreach with role-specific context.",
  },
  {
    id: "skill-002",
    name: "Resume Screening",
    version: "1.0.4",
    status: "pending_review",
    boundNode: "initial_screening",
    platform: "Boss直聘",
    health: "warning",
    lastCheckedAt: iso(-90),
    summary: "Drafted from recent candidate examples and pending approval.",
  },
  {
    id: "skill-003",
    name: "Talent Pool Packaging",
    version: "0.9.1",
    status: "degraded",
    boundNode: "candidate_scoring",
    platform: "Boss直聘",
    health: "critical",
    lastCheckedAt: iso(-240),
    summary: "Selector drift detected in the last browser run.",
  },
];

const approvals: ApprovalItem[] = [
  {
    id: "apr-001",
    kind: "skill",
    title: "Approve resume screening Skill",
    detail: "Review the new initial screening strategy before it can become active.",
    requester: "Agent",
    status: "pending",
    createdAt: iso(-45),
  },
  {
    id: "apr-002",
    kind: "workflow",
    title: "Activate talent pool handoff",
    detail: "Enables the workflow path from scoring to human review.",
    requester: "Ops",
    status: "pending",
    createdAt: iso(-65),
  },
  {
    id: "apr-003",
    kind: "system_command",
    title: "Allow local package inspection command",
    detail: "Registers a safe command under whitelist control.",
    requester: "Agent",
    status: "rejected",
    createdAt: iso(-180),
  },
];

const agent: AgentSnapshot = {
  status: "running",
  activeTask: "Initial screening for Mia Chen",
  browserLock: "held",
  uptime: "03:12:41",
  queueDepth: 4,
  tokenBudgetUsed: 38,
  health: "warning",
};

const events: TimelineEvent[] = [
  {
    id: "evt-001",
    label: "Workflow node advanced",
    detail: "Moved Mia Chen into the screening step.",
    at: iso(-12),
    tone: "positive",
  },
  {
    id: "evt-002",
    label: "Approval pending",
    detail: "Resume screening Skill is waiting for review.",
    at: iso(-32),
    tone: "warning",
  },
  {
    id: "evt-003",
    label: "Cooldown applied",
    detail: "Luna Wang was marked to avoid repeat outreach.",
    at: iso(-48),
    tone: "neutral",
  },
];

const alerts: TimelineEvent[] = [
  {
    id: "alert-001",
    label: "Selector drift detected",
    detail: "Talent pool packaging requires a refresh before full automation.",
    at: iso(-22),
    tone: "critical",
  },
];

const settings: SettingsSnapshot = {
  locale: "en-US",
  timezone: "Asia/Shanghai",
  intranetEnabled: false,
  desktopApprovalsOnly: true,
  providers: [
    { kind: "openai-compatible", name: "Primary OpenAI API", model: "gpt-5.4", enabled: true, temperature: 0.2, baseUrl: "https://api.openai.com/v1" },
    { kind: "anthropic", name: "Fallback Anthropic", model: "claude-sonnet-4", enabled: false, temperature: 0.2, baseUrl: "https://api.anthropic.com" },
  ],
  platform: {
    name: "Boss直聘",
    account: "recruiter-01",
    cooldownDays: 18,
    allowOutboundMessaging: false,
  },
};

const metrics = [
  { label: "Candidates screened", value: "126", delta: "+14%", tone: "positive" as const, caption: "Past 7 days" },
  { label: "Reply rate", value: "41%", delta: "+6%", tone: "positive" as const, caption: "Outreach to response" },
  { label: "Budget used", value: "$182", delta: "-9%", tone: "neutral" as const, caption: "Token spend this week" },
  { label: "Manual approvals", value: "3", delta: "1 pending", tone: "warning" as const, caption: "Human gate queue" },
];

const pipeline = [
  { label: "Discovery", value: 18, target: 20 },
  { label: "Screening", value: 12, target: 16 },
  { label: "Communication", value: 7, target: 10 },
  { label: "Scoring", value: 4, target: 6 },
  { label: "Human review", value: 3, target: 4 },
];

export const desktopMockSnapshot: DashboardSummary = {
  metrics,
  pipeline,
  timeline: events,
  alerts,
  candidates,
  workflows,
  skills,
  approvals,
  agent,
  settings,
};

