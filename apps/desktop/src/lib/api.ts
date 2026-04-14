import { desktopMockSnapshot } from "./mockData";
import type {
  ApprovalItem,
  AgentEvent,
  AgentSnapshot,
  AgentRunResult,
  AgentTaskEnqueueResult,
  AgentTaskRequest,
  CandidateRecord,
  DashboardSummary,
  SettingsSnapshot,
  SkillRecord,
  WorkflowDefinition,
} from "./types";

export interface DesktopApiClient {
  getDashboardSummary(): Promise<DashboardSummary>;
  listCandidates(): Promise<CandidateRecord[]>;
  listWorkflows(): Promise<WorkflowDefinition[]>;
  listSkills(): Promise<SkillRecord[]>;
  listApprovals(): Promise<ApprovalItem[]>;
  getSettings(): Promise<SettingsSnapshot>;
  getAgentSnapshot(): Promise<AgentSnapshot>;
  approveItem(id: string): Promise<void>;
  rejectItem(id: string, reason?: string): Promise<void>;
  updateSettings(settings: Partial<SettingsSnapshot>): Promise<SettingsSnapshot>;
  runAgentOnce(): Promise<AgentRunResult>;
  queueTask(task: AgentTaskRequest): Promise<AgentTaskEnqueueResult>;
  subscribeToAgentStream(onEvent: (event: AgentEvent) => void): () => void;
}

export interface ApiDescription {
  baseUrl: string;
  transport: "mock" | "http";
}

type JsonRecord = Record<string, unknown>;

function isOfflineError(error: unknown): boolean {
  return error instanceof Error && /fetch|network|failed|offline/i.test(error.message);
}

async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`);
  }

  return (await response.json()) as T;
}

function asRecord(value: unknown): JsonRecord {
  return typeof value === "object" && value !== null ? (value as JsonRecord) : {};
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function normalizeAgentSnapshot(raw: unknown): AgentSnapshot {
  const record = asRecord(raw);
  return {
    status: String(record.status ?? "idle") as AgentSnapshot["status"],
    activeTask: String(record.activeTask ?? record.active_task ?? "Idle"),
    browserLock: String(record.browserLock ?? record.browser_lock ?? "free") as AgentSnapshot["browserLock"],
    uptime: String(record.uptime ?? "00:00:00"),
    queueDepth: Number(record.queueDepth ?? record.queue_depth ?? 0),
    tokenBudgetUsed: Number(record.tokenBudgetUsed ?? record.token_budget_used ?? 0),
    health: String(record.health ?? "warning") as AgentSnapshot["health"],
  };
}

function normalizeSettings(raw: unknown): SettingsSnapshot {
  const record = asRecord(raw);
  const platform = asRecord(record.platform);
  return {
    locale: String(record.locale ?? "en-US"),
    timezone: String(record.timezone ?? "Asia/Shanghai"),
    intranetEnabled: Boolean(record.intranetEnabled ?? record.intranet_enabled ?? false),
    desktopApprovalsOnly: Boolean(record.desktopApprovalsOnly ?? (record.approval_source ?? "desktop_app") === "desktop_app"),
    providers: asArray<JsonRecord>(record.providers).map((provider) => ({
      kind: String(provider.kind ?? "openai-compatible") as SettingsSnapshot["providers"][number]["kind"],
      name: String(provider.name ?? "Provider"),
      model: String(provider.model ?? "unknown"),
      baseUrl: provider.baseUrl ? String(provider.baseUrl) : undefined,
      enabled: Boolean(provider.enabled ?? false),
      temperature: Number(provider.temperature ?? 0.2),
    })),
    platform: {
      name: String(platform.name ?? "Boss直聘"),
      account: String(platform.account ?? "recruiter-01"),
      cooldownDays: Number(platform.cooldownDays ?? platform.cooldown_days ?? 30),
      allowOutboundMessaging: Boolean(
        platform.allowOutboundMessaging ?? platform.allow_outbound_messaging ?? false,
      ),
    },
  };
}

function normalizeDashboard(raw: unknown): DashboardSummary {
  const record = asRecord(raw);
  return {
    metrics: asArray(record.metrics) as DashboardSummary["metrics"],
    pipeline: asArray(record.pipeline) as DashboardSummary["pipeline"],
    timeline: asArray(record.timeline) as DashboardSummary["timeline"],
    alerts: asArray(record.alerts) as DashboardSummary["alerts"],
    candidates: asArray(record.candidates) as CandidateRecord[],
    workflows: asArray(record.workflows) as WorkflowDefinition[],
    skills: asArray(record.skills) as SkillRecord[],
    approvals: asArray(record.approvals) as ApprovalItem[],
    agent: normalizeAgentSnapshot(record.agent),
    settings: normalizeSettings(record.settings),
  };
}

function normalizeAgentRunResult(raw: unknown): AgentRunResult {
  const record = asRecord(raw);
  return {
    processed: Boolean(record.processed ?? false),
    status: String(record.status ?? "idle"),
    taskId: record.taskId ? String(record.taskId) : record.task_id ? String(record.task_id) : undefined,
    enqueuedFollowUps: Number(record.enqueuedFollowUps ?? record.enqueued_follow_ups ?? 0),
    error: record.error ? String(record.error) : null,
  };
}

function normalizeAgentTaskEnqueueResult(raw: unknown): AgentTaskEnqueueResult {
  const record = asRecord(raw);
  return {
    taskId: String(record.taskId ?? record.task_id ?? ""),
    taskType: String(record.taskType ?? record.task_type ?? ""),
    priority: Number(record.priority ?? 0),
    queueDepth: Number(record.queueDepth ?? record.queue_depth ?? 0),
  };
}

function resolveWebSocketUrl(baseUrl: string): string {
  const url = new URL(baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/agent-stream";
  url.search = "";
  return url.toString();
}

function createFetchClient(baseUrl: string): DesktopApiClient {
  return {
    getDashboardSummary: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")),
    listCandidates: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).candidates,
    listWorkflows: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).workflows,
    listSkills: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).skills,
    listApprovals: async () => normalizeDashboard(await requestJson<unknown>(baseUrl, "/api/dashboard")).approvals,
    getSettings: async () => normalizeSettings(await requestJson<unknown>(baseUrl, "/api/settings")),
    getAgentSnapshot: async () => normalizeAgentSnapshot(await requestJson<unknown>(baseUrl, "/api/agent")),
    approveItem: async (id) => {
      await requestJson<unknown>(baseUrl, `/api/approvals/${id}/approve`, {
        method: "POST",
        body: JSON.stringify({ reviewer: "desktop-user" }),
      });
    },
    rejectItem: async (id, reason) => {
      await requestJson<unknown>(baseUrl, `/api/approvals/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reviewer: "desktop-user", reason }),
      });
    },
    updateSettings: async (settings) =>
      normalizeSettings(
        await requestJson<unknown>(baseUrl, "/api/settings", {
          method: "PATCH",
          body: JSON.stringify(settings),
        }),
      ),
    runAgentOnce: async () =>
      normalizeAgentRunResult(
        await requestJson<unknown>(baseUrl, "/api/agent/run-once", {
          method: "POST",
        }),
      ),
    queueTask: async (task) =>
      normalizeAgentTaskEnqueueResult(
        await requestJson<unknown>(baseUrl, "/api/agent/tasks", {
          method: "POST",
          body: JSON.stringify({
            task_type: task.taskType,
            payload: task.payload ?? {},
            priority: task.priority ?? 100,
            candidate_id: task.candidateId,
            workflow_id: task.workflowId,
            workflow_node_id: task.workflowNodeId,
          }),
        }),
      ),
    subscribeToAgentStream(onEvent) {
      const socket = new WebSocket(resolveWebSocketUrl(baseUrl));
      socket.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(String(event.data)) as JsonRecord;
          if (payload.type === "heartbeat") {
            return;
          }
          onEvent({
            id: String(payload.id ?? `stream-${Date.now()}`),
            level: String(payload.level ?? "info") as AgentEvent["level"],
            source: String(payload.source ?? "agent"),
            message: String(payload.message ?? ""),
            at: String(payload.at ?? new Date().toISOString()),
          });
        } catch {
          return;
        }
      });
      return () => socket.close();
    },
  };
}

function createMockClient(): DesktopApiClient {
  const snapshot = desktopMockSnapshot;

  return {
    getDashboardSummary: async () => snapshot,
    listCandidates: async () => snapshot.candidates,
    listWorkflows: async () => snapshot.workflows,
    listSkills: async () => snapshot.skills,
    listApprovals: async () => snapshot.approvals,
    getSettings: async () => snapshot.settings,
    getAgentSnapshot: async () => snapshot.agent,
    approveItem: async () => undefined,
    rejectItem: async () => undefined,
    updateSettings: async (settings) => ({ ...snapshot.settings, ...settings }),
    runAgentOnce: async () => ({ processed: false, status: "mock" }),
    queueTask: async (task) => ({
      taskId: `mock-${task.taskType}`,
      taskType: task.taskType,
      priority: task.priority ?? 100,
      queueDepth: snapshot.agent.queueDepth + 1,
    }),
    subscribeToAgentStream: () => () => undefined,
  };
}

export function createDesktopApiClient(baseUrl?: string): DesktopApiClient {
  if (!baseUrl) {
    return createMockClient();
  }

  const fetchClient = createFetchClient(baseUrl);
  return {
    async getDashboardSummary() {
      try {
        return await fetchClient.getDashboardSummary();
      } catch (error) {
        if (isOfflineError(error)) {
          return desktopMockSnapshot;
        }
        throw error;
      }
    },
    async listCandidates() {
      return fetchClient.listCandidates().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.candidates;
        }
        throw error;
      });
    },
    async listWorkflows() {
      return fetchClient.listWorkflows().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.workflows;
        }
        throw error;
      });
    },
    async listSkills() {
      return fetchClient.listSkills().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.skills;
        }
        throw error;
      });
    },
    async listApprovals() {
      return fetchClient.listApprovals().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.approvals;
        }
        throw error;
      });
    },
    async getSettings() {
      return fetchClient.getSettings().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.settings;
        }
        throw error;
      });
    },
    async getAgentSnapshot() {
      return fetchClient.getAgentSnapshot().catch(async (error) => {
        if (isOfflineError(error)) {
          return desktopMockSnapshot.agent;
        }
        throw error;
      });
    },
    async approveItem(id) {
      try {
        await fetchClient.approveItem(id);
      } catch (error) {
        if (!isOfflineError(error)) {
          throw error;
        }
      }
    },
    async rejectItem(id, reason) {
      try {
        await fetchClient.rejectItem(id, reason);
      } catch (error) {
        if (!isOfflineError(error)) {
          throw error;
        }
      }
    },
    async updateSettings(settings) {
      try {
        return await fetchClient.updateSettings(settings);
      } catch (error) {
        if (isOfflineError(error)) {
          return { ...desktopMockSnapshot.settings, ...settings };
        }
        throw error;
      }
    },
    async runAgentOnce() {
      try {
        return await fetchClient.runAgentOnce();
      } catch (error) {
        if (isOfflineError(error)) {
          return { processed: false, status: "mock-offline" };
        }
        throw error;
      }
    },
    async queueTask(task) {
      try {
        return await fetchClient.queueTask(task);
      } catch (error) {
        if (isOfflineError(error)) {
          return {
            taskId: `mock-${task.taskType}`,
            taskType: task.taskType,
            priority: task.priority ?? 100,
            queueDepth: desktopMockSnapshot.agent.queueDepth + 1,
          };
        }
        throw error;
      }
    },
    subscribeToAgentStream(onEvent) {
      try {
        return fetchClient.subscribeToAgentStream(onEvent);
      } catch {
        return () => undefined;
      }
    },
  };
}

const runtimeBaseUrl =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8741";

export const apiClient = Object.assign(createDesktopApiClient(runtimeBaseUrl), {
  describe(): ApiDescription {
    return {
      baseUrl: runtimeBaseUrl || "mock://desktop",
      transport: runtimeBaseUrl ? "http" : "mock",
    };
  },
});
