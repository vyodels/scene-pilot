import React, { startTransition, useEffect, useMemo, useState } from "react";
import type {
  CandidateTransitionPayload,
  RecruitmentStateMachine,
  RecruitmentStateMachineUpdatePayload,
} from "@scene-pilot/shared";
import { AppLayout, MetricCard, Panel, SectionTabs, Sidebar, StatusBadge, TopBar } from "../../components";
import { apiClient } from "../../lib/api";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
import type {
  AgentEvent,
  AgentGlobalMemoryRecord,
  AgentSnapshot,
  AgentQueueItem,
  CandidateMemoryRecord,
  CandidateThreadRecord,
  DashboardSummary,
  ExecutionGraphProjectionRecord,
  ExecutionTraceRecord,
  EvolutionArtifactRecord,
  GoalSpecRecord,
  JobMemoryRecord,
  McpPresetTemplateRecord,
  McpServerRecord,
  OperatorInteractionRecord,
  RecruitAgentProfileRecord,
  RuntimeEpisodeReplay,
  RuntimeWorkspaceData,
  SettingsSnapshot,
  SkillRecord,
  StrategyFragmentRecord,
  SyncBacklogItem,
  SyncStatusSnapshot,
  WorkspaceTab,
} from "../../lib/types";
import { AgentInboxView } from "../agent-inbox/AgentInboxView";
import { CandidatesKanbanView, type CandidatesKanbanTab } from "../candidates/CandidatesKanbanView";
import { CommunicationsView } from "../communications/CommunicationsView";
import { DashboardView } from "../dashboard/DashboardView";
import { EvolutionView } from "../evolution/EvolutionView";
import { buildCandidateViewModels } from "../kanban-shared/kanbanUtils";
import { RecruitAgentView } from "../recruit-agent/RecruitAgentView";
import { SettingsView } from "../settings/SettingsView";

const emptySettings: SettingsSnapshot = {
  locale: "en-US",
  timezone: "Asia/Shanghai",
  intranetEnabled: false,
  desktopApprovalsOnly: true,
  autonomyEnabled: false,
  skillHealthAutonomyEnabled: false,
  skillHealthAutonomyIntervalSeconds: 300,
  providers: [],
  intranetSync: {
    enabled: false,
    apiPath: "/api/recruit-agent/sync",
    timeoutSeconds: 10,
  },
  platform: {
    name: "本地执行配置",
    account: "未连接",
    cooldownDays: 30,
    allowOutboundMessaging: false,
    maxConcurrentRuns: 1,
    minFunnelCandidates: 0,
  },
};

function resolveMacroStage(status: string, stageKey: string, resumeAvailable: boolean): string {
  const fingerprint = `${status} ${stageKey}`.toLowerCase();
  if (/(rejected|cooldown|archive)/i.test(fingerprint)) {
    return "Archived";
  }
  if (/(offer|decision|hired|accepted|final)/i.test(fingerprint)) {
    return "Decision";
  }
  if (/(interview|schedule)/i.test(fingerprint)) {
    return "Interview";
  }
  if (resumeAvailable || /(resume|profile|attachment)/i.test(fingerprint)) {
    return "Resume";
  }
  if (/(contact|reply|message|communicat|outreach)/i.test(fingerprint)) {
    return "Outreach";
  }
  if (/(review|screen|assessment|probe|score)/i.test(fingerprint)) {
    return "Review";
  }
  return "New";
}

function macroStageTone(stage: string): "positive" | "neutral" | "warning" | "critical" {
  if (stage === "Archived") {
    return "critical";
  }
  if (stage === "Decision" || stage === "Interview") {
    return "positive";
  }
  if (stage === "Review" || stage === "Outreach" || stage === "Resume") {
    return "warning";
  }
  return "neutral";
}

const primaryActionStyle: React.CSSProperties = {
  border: `1px solid ${theme.colors.accent}`,
  borderRadius: "var(--radius-sm)",
  background: theme.colors.accent,
  color: "var(--text-inverse)",
  minHeight: "var(--space-8)",
  padding: "0 var(--space-4)",
  cursor: "pointer",
  fontWeight: 600,
};

const defaultActionStyle: React.CSSProperties = {
  border: "1px solid var(--border-input)",
  borderRadius: "var(--radius-sm)",
  background: "var(--bg-card)",
  color: "var(--text-primary)",
  minHeight: "var(--space-8)",
  padding: "0 var(--space-4)",
  cursor: "pointer",
  fontWeight: 500,
};

const surfaceRowButtonStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "var(--space-4)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-line)",
  background: "var(--bg-card)",
  cursor: "pointer",
};

function ImportCenterSurface({
  candidates,
  goals,
  traces,
  onCreateGoal,
  onOpenCommunications,
}: {
  candidates: DashboardSummary["candidates"];
  goals: GoalSpecRecord[];
  traces: ExecutionTraceRecord[];
  onCreateGoal?(payload: {
    title: string;
    goalText: string;
    goalKind?: string;
    summary?: string;
    constraints?: Record<string, unknown>;
    successCriteria?: Record<string, unknown>;
    contextHints?: Record<string, unknown>;
    trialBudget?: Record<string, unknown>;
    runPreferences?: Record<string, unknown>;
    priority?: number;
  }): void;
  onOpenCommunications?(filter?: string, candidateId?: string): void;
}): JSX.Element {
  const { copy } = useI18n();
  const stagedCandidates = candidates.filter((candidate) => !/(rejected|cooldown)/i.test(candidate.status));
  const importQueue = goals.filter((goal) => /(import|extract|capture|resume|candidate|sourcing|zhipin)/i.test(`${goal.title} ${goal.goalText} ${goal.summary ?? ""}`)).slice(0, 6);
  const executionNotes = traces
    .filter((trace) => /(candidate|resume|import|source)/i.test(`${trace.title} ${trace.summary ?? ""}`))
    .slice(0, 5);

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <Panel
        title={copy("Import Center", "导入中心")}
        eyebrow={copy("Source and stage", "来源与入库")}
        description={copy(
          "Capture active sourcing pages, stage imported candidates, and keep resume acquisition visible before records move deeper into the funnel.",
          "采集当前 sourcing 页面、暂存导入候选人，并在候选人进入后续漏斗前清晰展示简历获取状态。",
        )}
        actions={
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() =>
                onCreateGoal?.({
                  title: copy("Capture current sourcing page", "采集当前 sourcing 页面"),
                  goalText: copy(
                    "Inspect the currently active sourcing page, extract visible candidate records, and stage them for recruiter review without mutating the source site.",
                    "检查当前激活的 sourcing 页面，提取可见候选人记录，并在不改动来源站点的前提下把它们暂存到招聘审阅队列。",
                  ),
                  summary: copy("Create a staged import batch from the active sourcing page.", "从当前 sourcing 页面创建一个候选人暂存批次。"),
                  runPreferences: { initial_stage: "candidate_discovery" },
                  priority: 180,
                })
              }
              style={primaryActionStyle}
            >
              {copy("Capture page", "采集页面")}
            </button>
            <button
              type="button"
              onClick={() =>
                onCreateGoal?.({
                  title: copy("Request one resume artifact", "请求一份简历制品"),
                  goalText: copy(
                    "Collect one candidate resume artifact from the current sourcing workflow and save it into local structured storage for recruiter review.",
                    "从当前 sourcing 工作流中收集 1 份候选人简历制品，并保存到本地结构化存储，供招聘方审阅。",
                  ),
                  summary: copy("Acquire one resume artifact and store it locally.", "获取 1 份简历制品并存入本地。"),
                  runPreferences: { initial_stage: "resume_collection" },
                  priority: 160,
                })
              }
              style={defaultActionStyle}
            >
              {copy("Request resume", "请求简历")}
            </button>
          </div>
        }
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(calc(var(--layout-left-list-width) - var(--space-10)), 1fr))", gap: "var(--space-3)" }}>
          <MetricCard
            label={copy("Staged candidates", "暂存候选人")}
            value={String(stagedCandidates.length)}
            delta={copy("review", "待审")}
            tone={stagedCandidates.length ? "warning" : "neutral"}
            caption={copy("Ready for recruiter review and triage.", "已准备好进入招聘方审阅与分流。")}
          />
          <MetricCard
            label={copy("Open import tasks", "进行中的导入任务")}
            value={String(importQueue.length)}
            delta={copy("active", "进行中")}
            tone={importQueue.length ? "warning" : "neutral"}
            caption={copy("Recent capture, extraction, and resume acquisition requests.", "最近的采集、提取和简历获取请求。")}
          />
          <MetricCard
            label={copy("Resume-ready records", "已有简历记录")}
            value={String(candidates.filter((candidate) => candidate.resumeAvailable).length)}
            delta={copy("stored", "已落库")}
            tone={candidates.some((candidate) => candidate.resumeAvailable) ? "positive" : "neutral"}
            caption={copy("Candidates with visible resume artifacts already stored.", "已经可见并落库简历制品的候选人。")}
          />
        </div>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.2fr) var(--layout-right-panel-width)", gap: "var(--space-4)" }}>
        <Panel
          title={copy("Staging Queue", "暂存队列")}
          eyebrow={copy("Recruiter review", "招聘方审阅")}
          description={copy("Candidates recently captured or enriched before they move into the main pipeline.", "最近完成采集或补充资料、等待进入主漏斗的候选人。")}
        >
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            {stagedCandidates.slice(0, 6).map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                onClick={() => onOpenCommunications?.("candidate", candidate.id)}
                style={surfaceRowButtonStyle}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)", alignItems: "start" }}>
                  <div>
                    <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{candidate.name}</div>
                    <div style={{ marginTop: "var(--space-1)", fontSize: "var(--font-size-sm)", color: "var(--text-secondary)" }}>
                      {candidate.title} · {candidate.jdTitle} · {candidate.location}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", justifyContent: "end" }}>
                    <StatusBadge tone={macroStageTone(resolveMacroStage(candidate.status, candidate.stageKey, candidate.resumeAvailable))}>
                      {resolveMacroStage(candidate.status, candidate.stageKey, candidate.resumeAvailable)}
                    </StatusBadge>
                    {candidate.resumeAvailable ? <StatusBadge tone="positive">{copy("resume ready", "已有简历")}</StatusBadge> : null}
                  </div>
                </div>
                <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-size-sm)", color: "var(--text-regular)", lineHeight: 1.6 }}>{candidate.nextAction}</div>
              </button>
            ))}
          </div>
        </Panel>
        <Panel
          title={copy("Recent import activity", "最近导入动态")}
          eyebrow={copy("Execution notes", "执行记录")}
          description={copy("Latest capture and import execution notes that affect the sourcing funnel.", "影响 sourcing 漏斗的最新采集与导入执行记录。")}
        >
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            {importQueue.map((goal) => (
              <article key={goal.id} style={{ padding: "var(--space-3) 0", borderBottom: "1px solid var(--border-line)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)", alignItems: "start" }}>
                  <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{goal.title}</div>
                  <StatusBadge tone={/completed|approved/i.test(goal.status) ? "positive" : /failed|rejected/i.test(goal.status) ? "critical" : "warning"}>
                    {translateUiToken(goal.status, copy)}
                  </StatusBadge>
                </div>
                <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-size-sm)", color: "var(--text-secondary)", lineHeight: 1.6 }}>
                  {goal.summary || goal.goalText}
                </div>
                <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-size-xs)", color: "var(--text-placeholder)" }}>{formatCompactDate(goal.updatedAt)}</div>
              </article>
            ))}
            {executionNotes.map((trace) => (
              <article key={trace.id} style={{ padding: "var(--space-3) 0", borderBottom: "1px solid var(--border-line)" }}>
                <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{trace.title}</div>
                <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-size-sm)", color: "var(--text-secondary)", lineHeight: 1.6 }}>
                  {trace.summary || copy("Execution note captured for recruiter review.", "已记录一条供招聘方查看的执行说明。")}
                </div>
              </article>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function JdWorkspaceSurface({
  candidates,
  onOpenCommunications,
}: {
  candidates: DashboardSummary["candidates"];
  onOpenCommunications?(filter?: string, candidateId?: string): void;
}): JSX.Element {
  const { copy } = useI18n();
  const jdGroups = Object.entries(
    candidates.reduce<Record<string, DashboardSummary["candidates"]>>((accumulator, candidate) => {
      const key = candidate.jdTitle || copy("Unassigned role", "未分配岗位");
      accumulator[key] = [...(accumulator[key] ?? []), candidate];
      return accumulator;
    }, {}),
  ).sort((left, right) => right[1].length - left[1].length);

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <Panel
        title={copy("JD Workspace", "岗位工作区")}
        eyebrow={copy("Role-centered view", "岗位中心视角")}
        description={copy(
          "Review pipeline volume, stage mix, and recruiter next actions by role without opening raw runtime diagnostics.",
          "以岗位为中心查看漏斗规模、阶段分布和下一步动作，而不暴露原始 runtime 诊断信息。",
        )}
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(calc(var(--space-12) * 3 + var(--space-10) + var(--space-10) + var(--space-5) + var(--space-4)), 1fr))", gap: "var(--space-3)" }}>
          {jdGroups.slice(0, 4).map(([jdTitle, jdCandidates]) => {
            const macroCounts = jdCandidates.reduce<Record<string, number>>((accumulator, candidate) => {
              const stage = resolveMacroStage(candidate.status, candidate.stageKey, candidate.resumeAvailable);
              accumulator[stage] = (accumulator[stage] ?? 0) + 1;
              return accumulator;
            }, {});
            return (
              <article key={jdTitle} style={{ padding: "var(--space-4)", borderRadius: "var(--radius-md)", background: "var(--bg-card)", border: "1px solid var(--border-line)" }}>
                <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{jdTitle}</div>
                <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-size-sm)", color: "var(--text-secondary)" }}>
                  {copy(`${jdCandidates.length} candidates in this funnel.`, `该漏斗下共有 ${jdCandidates.length} 位候选人。`)}
                </div>
                <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginTop: "var(--space-3)" }}>
                  {Object.entries(macroCounts).map(([label, count]) => (
                    <StatusBadge key={label} tone={macroStageTone(label)}>
                      {label} · {count}
                    </StatusBadge>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      </Panel>

      <div style={{ display: "grid", gap: "var(--space-3)" }}>
        {jdGroups.map(([jdTitle, jdCandidates]) => (
          <Panel
            key={jdTitle}
            title={jdTitle}
            eyebrow={copy("Role funnel", "岗位漏斗")}
            description={copy("Candidates currently grouped under this role.", "当前归属到该岗位的候选人。")}
          >
            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              {jdCandidates.map((candidate) => {
                const macroStage = resolveMacroStage(candidate.status, candidate.stageKey, candidate.resumeAvailable);
                return (
                  <button
                    key={candidate.id}
                    type="button"
                    onClick={() => onOpenCommunications?.("candidate", candidate.id)}
                    style={surfaceRowButtonStyle}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)", alignItems: "start" }}>
                      <div>
                        <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{candidate.name}</div>
                        <div style={{ marginTop: "var(--space-1)", fontSize: "var(--font-size-sm)", color: "var(--text-secondary)" }}>
                          {candidate.title} · {candidate.location}
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", justifyContent: "end" }}>
                        <StatusBadge tone={macroStageTone(macroStage)}>{macroStage}</StatusBadge>
                        <StatusBadge tone="neutral">{copy(`score ${candidate.matchScore}`, `分数 ${candidate.matchScore}`)}</StatusBadge>
                      </div>
                    </div>
                    <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-size-sm)", color: "var(--text-regular)", lineHeight: 1.6 }}>{candidate.nextAction}</div>
                  </button>
                );
              })}
            </div>
          </Panel>
        ))}
      </div>
    </div>
  );
}

const emptyAgent: AgentSnapshot = {
  status: "idle",
  activeTask: "waiting_for_backend",
  browserLock: "free",
  uptime: "00:00:00",
  queueDepth: 0,
  tokenBudgetUsed: 0,
  health: "warning",
};

const emptySummary: DashboardSummary = {
  metrics: [],
  pipeline: [],
  timeline: [],
  alerts: [],
  candidates: [],
  playbooks: [],
  skills: [],
  approvals: [],
  agent: emptyAgent,
  settings: emptySettings,
};

const emptyRuntime: RuntimeWorkspaceData = {
  compilerContract: null,
  domainPacks: [],
  taskSpecs: [],
  plans: [],
  episodes: [],
  snapshots: [],
  capabilityDrivers: [],
  environmentAssessments: [],
  templates: [],
  patches: [],
  replans: [],
};

const emptySyncStatus: SyncStatusSnapshot = {
  enabled: false,
  mode: "local_only",
  remoteAvailable: false,
  pendingCount: 0,
  recentErrors: [],
};

export function DesktopWorkspace(): JSX.Element {
  const { copy } = useI18n();
  const [tab, setTab] = useState<WorkspaceTab>("home");
  const [summary, setSummary] = useState<DashboardSummary>(emptySummary);
  const [runtimeData, setRuntimeData] = useState<RuntimeWorkspaceData>(emptyRuntime);
  const [events, setEvents] = useState<AgentEvent[]>([
    {
      id: "stream-001",
      level: "info",
      source: "bootstrap",
      message: copy("Recruit Agent workspace loaded.", "Recruit Agent 工作区已加载。"),
      at: copy("now", "刚刚"),
    },
  ]);
  const [refreshing, setRefreshing] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [runtimeActionBusy, setRuntimeActionBusy] = useState(false);
  const [approvalActionId, setApprovalActionId] = useState<string>();
  const [selectedEpisodeId, setSelectedEpisodeId] = useState<string>();
  const [selectedReplay, setSelectedReplay] = useState<RuntimeEpisodeReplay | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatusSnapshot>(emptySyncStatus);
  const [syncBacklog, setSyncBacklog] = useState<SyncBacklogItem[]>([]);
  const [queueItems, setQueueItems] = useState<AgentQueueItem[]>([]);
  const [syncingBacklog, setSyncingBacklog] = useState(false);
  const [transport, setTransport] = useState(apiClient.describe().transport);
  const [errorMessage, setErrorMessage] = useState<string>();
  const [profile, setProfile] = useState<RecruitAgentProfileRecord | null>(null);
  const [candidateMemories, setCandidateMemories] = useState<CandidateMemoryRecord[]>([]);
  const [jobMemories, setJobMemories] = useState<JobMemoryRecord[]>([]);
  const [globalMemory, setGlobalMemory] = useState<AgentGlobalMemoryRecord | null>(null);
  const [candidateThreads, setCandidateThreads] = useState<CandidateThreadRecord[]>([]);
  const [stateMachine, setStateMachine] = useState<RecruitmentStateMachine | null>(null);
  const [evolutionArtifacts, setEvolutionArtifacts] = useState<EvolutionArtifactRecord[]>([]);
  const [goals, setGoals] = useState<GoalSpecRecord[]>([]);
  const [executionTraces, setExecutionTraces] = useState<ExecutionTraceRecord[]>([]);
  const [executionGraphs, setExecutionGraphs] = useState<ExecutionGraphProjectionRecord[]>([]);
  const [strategyFragments, setStrategyFragments] = useState<StrategyFragmentRecord[]>([]);
  const [operatorInteractions, setOperatorInteractions] = useState<OperatorInteractionRecord[]>([]);
  const [mcpPresets, setMcpPresets] = useState<McpPresetTemplateRecord[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServerRecord[]>([]);
  const [communicationsFocus, setCommunicationsFocus] = useState<{ candidateId?: string; statusFilter?: string }>({});
  const [agentInboxFocus, setAgentInboxFocus] = useState<{ filter?: string; itemId?: string }>({});
  const [evolutionFocus, setEvolutionFocus] = useState<{ section?: string; itemId?: string }>({});
  const [aiReviewSection, setAiReviewSection] = useState<"queue" | "changes">("queue");
  const [candidateKanbanTab, setCandidateKanbanTab] = useState<CandidatesKanbanTab>("funnel");

  const appendEvent = (event: AgentEvent) => {
    setEvents((current) => [...current.slice(-49), event]);
  };

  const loadWorkspace = async (reason?: string) => {
    setRefreshing(true);
    try {
      const [
        nextSummary,
        nextRuntime,
        nextAgent,
        nextSyncStatus,
        nextSyncBacklog,
        nextQueueItems,
        nextApprovals,
        nextSkills,
        nextProfile,
        nextGoals,
        nextExecutionTraces,
        nextExecutionGraphs,
        nextStrategyFragments,
        nextOperatorInteractions,
        nextCandidateMemories,
        nextJobMemories,
        nextGlobalMemory,
        nextCandidateThreads,
        nextStateMachine,
        nextEvolutionArtifacts,
        nextMcpPresets,
        nextMcpServers,
      ] = await Promise.all([
        apiClient.getDashboardSummary(),
        apiClient.getRuntimeWorkspaceData(),
        apiClient.getAgentSnapshot(),
        apiClient.getSyncStatus(),
        apiClient.listSyncBacklog(),
        apiClient.listAgentQueue(),
        apiClient.listApprovals(),
        apiClient.listSkills(),
        apiClient.getRecruitAgentProfile(),
        apiClient.listGoals(),
        apiClient.listExecutionTraces(),
        apiClient.listExecutionGraphs(),
        apiClient.listStrategyFragments(),
        apiClient.listOperatorInteractions(),
        apiClient.listCandidateMemories(),
        apiClient.listJobMemories(),
        apiClient.getAgentGlobalMemory(),
        apiClient.listCandidateThreads(),
        apiClient.getStateMachine(),
        apiClient.listEvolutionArtifacts(),
        apiClient.listMcpPresets(),
        apiClient.listMcpServers(),
      ]);

      startTransition(() => {
        setSummary({
          ...nextSummary,
          agent: nextAgent,
          approvals: nextApprovals,
          skills: nextSkills,
        });
        setRuntimeData(nextRuntime);
        setSyncStatus(nextSyncStatus);
        setSyncBacklog(nextSyncBacklog);
        setQueueItems(nextQueueItems);
        setProfile(nextProfile);
        setGoals(nextGoals);
        setExecutionTraces(nextExecutionTraces);
        setExecutionGraphs(nextExecutionGraphs);
        setStrategyFragments(nextStrategyFragments);
        setOperatorInteractions(nextOperatorInteractions);
        setCandidateMemories(nextCandidateMemories);
        setJobMemories(nextJobMemories);
        setGlobalMemory(nextGlobalMemory);
        setCandidateThreads(nextCandidateThreads);
        setStateMachine(nextStateMachine);
        setEvolutionArtifacts(nextEvolutionArtifacts);
        setMcpPresets(nextMcpPresets);
        setMcpServers(nextMcpServers);
      });
      setSelectedEpisodeId((current) => current ?? nextRuntime.episodes[0]?.id);
      setTransport("http");
      setErrorMessage(undefined);
      if (reason) {
        appendEvent({
          id: `local-${Date.now()}`,
          level: "success",
          source: "desktop",
          message: reason,
          at: new Date().toISOString(),
        });
      }
    } catch (error) {
      setTransport("offline");
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to refresh workspace.", "刷新工作区失败。"));
      appendEvent({
        id: `local-error-${Date.now()}`,
        level: "warning",
        source: "desktop",
        message: copy("Backend unavailable. Waiting for a real backend connection.", "本地后端不可用，等待真实后端连接。"),
        at: new Date().toISOString(),
      });
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    void loadWorkspace(copy("Workspace loaded.", "工作区已加载。"));

    const interval = window.setInterval(() => {
      void loadWorkspace();
    }, 10000);

    return () => {
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    const unsubscribe = apiClient.subscribeToAgentStream((payload) => {
      if (!payload.id || !payload.message) {
        return;
      }
      setTransport("http");
      appendEvent({
        id: String(payload.id),
        level: payload.level,
        source: payload.source,
        message: payload.message,
        at: payload.at,
      });
      void loadWorkspace();
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    const episodeId = selectedEpisodeId;
    if (!episodeId) {
      setSelectedReplay(null);
      return;
    }

    let active = true;
    void (async () => {
      try {
        const replay = await apiClient.getRuntimeReplay(episodeId);
        if (active) {
          setSelectedReplay(replay);
        }
      } catch {
        if (active) {
          setSelectedReplay(null);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, [selectedEpisodeId]);

  const counts = useMemo(
    () =>
      ({
        "ai-strategy": summary.skills.filter((skill) => skill.status !== "active" || skill.health !== "healthy").length,
        "ai-review":
          operatorInteractions.filter((item) => !item.candidateId && item.status === "pending").length +
          summary.skills.filter((skill) => skill.status !== "active" || skill.health !== "healthy").length +
          evolutionArtifacts.filter((artifact) => /(pending|draft|review)/i.test(artifact.status)).length,
        candidates: summary.candidates.filter((candidate) => !/(rejected|cooldown)/i.test(candidate.status)).length,
        communications: candidateThreads.filter(
          (thread) =>
            thread.runtimeInteractions.some((interaction) => interaction.status === "pending") ||
            /(contact_required|contact_acquired|pending_communication|communicating|waiting_reply|resume_requested)/i.test(thread.candidate.status),
        ).length,
        "import-center": goals.filter((goal) => /(import|extract|capture|resume|candidate|sourcing|zhipin)/i.test(`${goal.title} ${goal.goalText} ${goal.summary ?? ""}`)).length,
        "jd-workspace": new Set(summary.candidates.map((candidate) => candidate.jdTitle || copy("Unassigned role", "未分配岗位"))).size,
      }) satisfies Partial<Record<WorkspaceTab, number>>,
    [candidateThreads, copy, evolutionArtifacts, goals, operatorInteractions, summary],
  );

  const sectionMeta = useMemo(
    (): Record<WorkspaceTab, { eyebrow: string; title: string; description: string }> => ({
      home: {
        eyebrow: copy("Today", "今日工作"),
        title: copy("Home", "首页"),
        description: copy("Start from recruiter queues, blocked items, and the next actions that matter today.", "从招聘待办、阻塞事项和今天最重要的下一步动作开始。"),
      },
      candidates: {
        eyebrow: copy("Candidate pipeline", "候选人漏斗"),
        title: copy("Candidates", "候选人"),
        description: copy("Review, triage, and progress active candidates through the hiring workflow.", "在招聘工作流中审阅、分流并推进活跃候选人。"),
      },
      "import-center": {
        eyebrow: copy("Source operations", "来源作业"),
        title: copy("Import Center", "导入中心"),
        description: copy("Capture active sourcing pages, stage imports, and keep resume acquisition visible.", "采集当前 sourcing 页面、暂存导入结果，并清晰展示简历获取状态。"),
      },
      "jd-workspace": {
        eyebrow: copy("Role-centered view", "岗位中心视角"),
        title: copy("JD Workspace", "岗位工作区"),
        description: copy("Track funnel health, notes, and next actions by role.", "以岗位为中心查看漏斗健康度、策略笔记和下一步动作。"),
      },
      communications: {
        eyebrow: copy("Candidate cockpit", "候选人驾驶舱"),
        title: copy("Communications", "沟通中心"),
        description: copy("Keep communication history, resume facts, assessments, and next recommended actions in one candidate view.", "在单一候选人视图中整合沟通历史、简历事实、评估和下一步建议。"),
      },
      "ai-review": {
        eyebrow: copy("Review operations", "审查作业"),
        title: copy("AI Review Center", "AI 审阅中心"),
        description: copy(
          "Review AI suggestions, blocked automation, and strategy changes without mixing them into candidate conversations.",
          "把 AI 建议、受阻自动化和策略变更放在独立审查面，不混入候选人沟通流程。",
        ),
      },
      "ai-strategy": {
        eyebrow: copy("Strategy workspace", "策略工作台"),
        title: copy("AI Strategy", "AI 策略"),
        description: copy(
          "Define recruiting strategy, memory boundaries, and automation rules for the workspace.",
          "为当前工作台定义招聘策略、记忆边界和自动化规则。",
        ),
      },
      settings: {
        eyebrow: copy("Tools and connections", "工具与连接"),
        title: copy("Settings", "设置"),
        description: copy(
          "Configure model access, external tools, sync preferences, and local review rules.",
          "配置模型接入、外部工具、同步偏好和本地复核规则。",
        ),
      },
    }),
    [copy],
  );

  const candidateKanbanModels = useMemo(
    () => (stateMachine ? buildCandidateViewModels(summary.candidates, candidateThreads, stateMachine) : []),
    [candidateThreads, stateMachine, summary.candidates],
  );

  const candidateKanbanTabItems = useMemo(
    () => [
      {
        key: "funnel",
        label: copy("Candidate funnel", "候选人漏斗"),
        count: summary.candidates.length,
      },
      {
        key: "status",
        label: copy("Candidate follow-up", "候选人跟进"),
        count: candidateKanbanModels.filter((item) => item.humanRequired).length,
      },
    ],
    [candidateKanbanModels, copy, summary.candidates.length],
  );

  const handleApprove = async (id: string) => {
    setApprovalActionId(id);
    try {
      await apiClient.approveItem(id);
      await loadWorkspace(copy(`Approval ${id} accepted.`, `已批准审批项 ${id}。`));
    } finally {
      setApprovalActionId(undefined);
    }
  };

  const handleReject = async (id: string) => {
    setApprovalActionId(id);
    try {
      await apiClient.rejectItem(id, "由桌面工作区拒绝。");
      await loadWorkspace(copy(`Approval ${id} rejected.`, `已拒绝审批项 ${id}。`));
    } finally {
      setApprovalActionId(undefined);
    }
  };

  const handleSaveSettings = async (patch: Partial<SettingsSnapshot>) => {
    setSettingsSaving(true);
    try {
      const nextSettings = await apiClient.updateSettings(patch);
      startTransition(() => {
        setSummary((current) => ({ ...current, settings: nextSettings }));
      });
      await loadWorkspace(copy("Settings saved.", "设置已保存。"));
    } finally {
      setSettingsSaving(false);
    }
  };

  const handleInstallMcpPreset = async (
    presetKey: string,
    payload?: { serverKey?: string; name?: string; endpoint?: string },
  ) => {
    await apiClient.installMcpPreset(presetKey, payload);
    await loadWorkspace(copy("MCP preset installed.", "MCP 预置模板已安装。"));
  };

  const handleCreateMcpServer = async (payload: {
    serverKey: string;
    name: string;
    transportKind: string;
    protocol: string;
    endpoint: string;
    enabled?: boolean;
    tools?: Array<{
      name: string;
      description: string;
      parameters?: Record<string, unknown>;
      capabilities?: string[];
      enabled?: boolean;
      riskLevel?: string;
      remoteName?: string | null;
      toolMetadata?: Record<string, unknown>;
    }>;
  }) => {
    await apiClient.createMcpServer(payload);
    await loadWorkspace(copy("MCP server created.", "MCP 服务已创建。"));
  };

  const handleUpdateMcpServer = async (
    serverId: string,
    payload: Partial<{
      serverKey: string;
      name: string;
      transportKind: string;
      protocol: string;
      endpoint: string;
      enabled: boolean;
      tools: Array<{
        name: string;
        description: string;
        parameters?: Record<string, unknown>;
        capabilities?: string[];
        enabled?: boolean;
        riskLevel?: string;
        remoteName?: string | null;
        toolMetadata?: Record<string, unknown>;
      }>;
    }>,
  ) => {
    await apiClient.updateMcpServer(serverId, payload);
    await loadWorkspace(copy("MCP server updated.", "MCP 服务已更新。"));
  };

  const handleDeleteMcpServer = async (serverId: string) => {
    await apiClient.deleteMcpServer(serverId);
    await loadWorkspace(copy("MCP server deleted.", "MCP 服务已删除。"));
  };

  const handleHealthcheckMcpServer = async (serverId: string) => {
    await apiClient.healthcheckMcpServer(serverId);
    await loadWorkspace(copy("MCP health check finished.", "MCP 健康检查已完成。"));
  };

  const handleRunOnce = async () => {
    setRuntimeActionBusy(true);
    try {
      const result = await apiClient.runAgentOnce();
      await loadWorkspace(copy(`Run once completed with status ${result.status}.`, `单次运行已完成，状态为 ${translateUiToken(result.status, copy)}。`));
    } finally {
      setRuntimeActionBusy(false);
    }
  };

  const handleQueueScreeningTask = async () => {
    setRuntimeActionBusy(true);
    try {
      const firstCandidate = summary.candidates[0];
      if (!firstCandidate) {
        await loadWorkspace(copy("No candidate available for adaptive review.", "当前没有可用于目标驱动评估的候选人。"));
        return;
      }
      await apiClient.createGoal({
        title: copy(`Review ${firstCandidate.name}`, `评估 ${firstCandidate.name}`),
        goalText: copy(
          `Review candidate ${firstCandidate.name} for ${firstCandidate.jdTitle}. Use real external capabilities to inspect the candidate, assess fit, and distill a reusable screening strategy.`,
          `围绕候选人 ${firstCandidate.name} 和岗位 ${firstCandidate.jdTitle} 启动一次目标驱动评估。请使用真实外部能力完成候选人查看、匹配判断，并沉淀可复用筛选策略。`,
        ),
        summary: copy("Create a goal-driven candidate review run.", "创建一个目标驱动的候选人评估 run。"),
        priority: 180,
        constraints: {
          candidate_id: firstCandidate.id,
          platform: firstCandidate.platform,
        },
        contextHints: {
          candidate_id: firstCandidate.id,
          adaptive_stage: "candidate_probe",
        },
        runPreferences: {
          initial_stage: "candidate_probe",
        },
      });
      await loadWorkspace(copy("Adaptive candidate review goal created.", "已创建目标驱动的候选人评估任务。"));
    } finally {
      setRuntimeActionBusy(false);
    }
  };

  const handleFlushSync = async () => {
    setSyncingBacklog(true);
    try {
      const result = await apiClient.flushSyncBacklog();
      await loadWorkspace(result.message);
    } finally {
      setSyncingBacklog(false);
    }
  };

  const handleSaveProfile = async (payload: Partial<RecruitAgentProfileRecord>) => {
    await apiClient.updateRecruitAgentProfile(payload);
    await loadWorkspace(copy("Recruit Agent profile saved.", "Recruit Agent 配置已保存。"));
  };

  const handleSaveStateMachine = async (payload: RecruitmentStateMachineUpdatePayload) => {
    await apiClient.updateStateMachine(payload);
    await loadWorkspace(copy("State machine updated.", "状态机已更新。"));
  };

  const handleCreateGoal = async (payload: {
    title: string;
    goalText: string;
    goalKind?: string;
    summary?: string;
    constraints?: Record<string, unknown>;
    successCriteria?: Record<string, unknown>;
    contextHints?: Record<string, unknown>;
    trialBudget?: Record<string, unknown>;
    runPreferences?: Record<string, unknown>;
    priority?: number;
  }) => {
    setRuntimeActionBusy(true);
    try {
      await apiClient.createGoal(payload);
      await loadWorkspace(copy("Adaptive goal created.", "已创建目标驱动任务。"));
    } finally {
      setRuntimeActionBusy(false);
    }
  };

  const handleResolveInteraction = async (interactionId: string, action: string, comment?: string) => {
    setApprovalActionId(interactionId);
    try {
      await apiClient.resolveOperatorInteraction(interactionId, {
        action,
        comment,
        operator: "desktop-user",
      });
      await loadWorkspace(copy("Operator interaction resolved.", "已处理人工介入项。"));
    } finally {
      setApprovalActionId(undefined);
    }
  };

  const handleUpdateSkill = async (skillId: string, payload: Partial<SkillRecord>) => {
    await apiClient.updateSkill(skillId, payload);
    await loadWorkspace(copy("Skill updated.", "Skill 已更新。"));
  };

  const handleDeleteSkill = async (skillId: string) => {
    await apiClient.deleteSkill(skillId);
    await loadWorkspace(copy("Skill deleted.", "Skill 已删除。"));
  };

  const handleUpdateCandidateMemory = async (candidateId: string, payload: Partial<CandidateMemoryRecord>) => {
    await apiClient.updateCandidateMemory(candidateId, payload);
    await loadWorkspace(copy("Candidate memory updated.", "候选人 memory 已更新。"));
  };

  const handleCompactCandidateMemory = async (candidateId: string) => {
    await apiClient.compactCandidateMemory(candidateId, "manual_compact", true);
    await loadWorkspace(copy("Candidate memory compacted.", "候选人 memory 已 compact。"));
  };

  const handleUpdateJobMemory = async (jdId: string, payload: Partial<JobMemoryRecord>) => {
    await apiClient.updateJobMemory(jdId, payload);
    await loadWorkspace(copy("JD memory updated.", "JD memory 已更新。"));
  };

  const handleCompactJobMemory = async (jdId: string) => {
    await apiClient.compactJobMemory(jdId, "manual_compact", true);
    await loadWorkspace(copy("JD memory compacted.", "JD memory 已 compact。"));
  };

  const handleUpdateGlobalMemory = async (payload: Partial<AgentGlobalMemoryRecord>) => {
    await apiClient.updateAgentGlobalMemory(payload);
    await loadWorkspace(copy("Global memory updated.", "全局 memory 已更新。"));
  };

  const handleCompactGlobalMemory = async () => {
    await apiClient.compactAgentGlobalMemory("manual_compact", true);
    await loadWorkspace(copy("Global memory compacted.", "全局 memory 已 compact。"));
  };

  const handleUpdateEvolutionArtifact = async (artifactId: string, payload: Partial<EvolutionArtifactRecord>) => {
    await apiClient.updateEvolutionArtifact(artifactId, payload);
    await loadWorkspace(copy("Evolution artifact updated.", "演进产物已更新。"));
  };

  const handleCreateThreadEntry = async (candidateId: string, payload: { direction: string; content: string; messageType?: string; platform?: string }) => {
    await apiClient.createCandidateThreadEntry(candidateId, payload);
    await loadWorkspace(copy("Conversation entry added.", "沟通记录已追加。"));
  };

  const handleTransitionCandidateState = async (
    candidateId: string,
    payload: CandidateTransitionPayload,
  ) => {
    await apiClient.transitionCandidateState(candidateId, payload);
    await loadWorkspace(copy("Candidate state updated.", "候选人状态已更新。"));
  };

  const handleCreateCandidateAssessment = async (
    candidateId: string,
    payload: {
      assessmentType: string;
      stageKey?: string;
      status?: string;
      decision?: string;
      score?: number;
      summary?: string;
      evidenceRefs?: unknown[];
      metadata?: Record<string, unknown>;
      createdBy?: string;
      reviewedBy?: string;
    },
  ) => {
    await apiClient.createCandidateAssessment(candidateId, payload);
    await loadWorkspace(copy("Assessment saved.", "评估已保存。"));
  };

  const openCommunications = (statusFilter?: string, candidateId?: string) => {
    setCommunicationsFocus({ statusFilter, candidateId });
    setTab("communications");
  };

  const openAiReview = (filter?: string, itemId?: string) => {
    setAiReviewSection("queue");
    setAgentInboxFocus({ filter, itemId });
    setTab("ai-review");
  };

  const openEvolution = (section?: string, itemId?: string) => {
    setAiReviewSection("changes");
    setEvolutionFocus({ section, itemId });
    setTab("ai-review");
  };

  const content = (() => {
    switch (tab) {
      case "home":
        return (
          <DashboardView
            summary={summary}
            onOpenCandidates={() => setTab("candidates")}
            onOpenImportCenter={() => setTab("import-center")}
            onOpenJdWorkspace={() => setTab("jd-workspace")}
            onOpenCommunications={() => openCommunications("active")}
            onOpenAiReview={() => openAiReview("all")}
            onOpenAiStrategy={() => setTab("ai-strategy")}
          />
        );
      case "candidates":
        return (
          <CandidatesKanbanView
            candidates={summary.candidates}
            threads={candidateThreads}
            stateMachine={stateMachine}
            activeTab={candidateKanbanTab}
            onOpenCandidate={(candidateId) => openCommunications("candidate", candidateId)}
            onCreateEntry={handleCreateThreadEntry}
            onTransition={handleTransitionCandidateState}
          />
        );
      case "import-center":
        return (
          <ImportCenterSurface
            candidates={summary.candidates}
            goals={goals}
            traces={executionTraces}
            onCreateGoal={handleCreateGoal}
            onOpenCommunications={openCommunications}
          />
        );
      case "jd-workspace":
        return <JdWorkspaceSurface candidates={summary.candidates} onOpenCommunications={openCommunications} />;
      case "ai-strategy":
        return (
          <RecruitAgentView
            profile={profile}
            stateMachine={stateMachine}
            candidates={summary.candidates}
            skills={summary.skills}
            candidateMemories={candidateMemories}
            jobMemories={jobMemories}
            globalMemory={globalMemory}
            onSaveProfile={handleSaveProfile}
            onSaveStateMachine={handleSaveStateMachine}
            onUpdateSkill={handleUpdateSkill}
            onDeleteSkill={handleDeleteSkill}
            onUpdateCandidateMemory={handleUpdateCandidateMemory}
            onCompactCandidateMemory={handleCompactCandidateMemory}
            onUpdateJobMemory={handleUpdateJobMemory}
            onCompactJobMemory={handleCompactJobMemory}
            onUpdateGlobalMemory={handleUpdateGlobalMemory}
            onCompactGlobalMemory={handleCompactGlobalMemory}
          />
        );
      case "communications":
        return (
          <CommunicationsView
            profile={profile}
            threads={candidateThreads}
            preferredCandidateId={communicationsFocus.candidateId}
            preferredStatusFilter={communicationsFocus.statusFilter}
            pendingActionId={approvalActionId}
            onApprove={handleApprove}
            onReject={handleReject}
            onCreateEntry={handleCreateThreadEntry}
            onTransitionState={handleTransitionCandidateState}
            onCreateAssessment={handleCreateCandidateAssessment}
          />
        );
      case "ai-review":
        return (
          <div style={{ display: "grid", gap: "var(--space-4)" }}>
            <SectionTabs
              items={[
                {
                  key: "queue",
                  label: copy("Review queue", "审阅队列"),
                  detail: copy("Approvals, operator interactions, and blocked work.", "审批、人工介入项和阻塞任务。"),
                  count:
                    operatorInteractions.filter((item) => !item.candidateId && item.status === "pending").length +
                    summary.approvals.filter((approval) => approval.status === "pending").length,
                },
                {
                  key: "changes",
                  label: copy("AI changes", "AI 变更"),
                  detail: copy("Skill health, memory refresh, and change proposals.", "Skill 健康、Memory 刷新和变更提案。"),
                  count: evolutionArtifacts.filter((artifact) => /(pending|draft|review)/i.test(artifact.status)).length,
                },
              ]}
              active={aiReviewSection}
              onChange={(key) => setAiReviewSection(key as "queue" | "changes")}
            />
            {aiReviewSection === "queue" ? (
              <AgentInboxView
                interactions={operatorInteractions}
                approvals={summary.approvals}
                skills={summary.skills}
                artifacts={evolutionArtifacts}
                events={events}
                goals={goals}
                traces={executionTraces}
                graphs={executionGraphs}
                pendingActionId={approvalActionId}
                requestedFilter={agentInboxFocus.filter}
                requestedItemId={agentInboxFocus.itemId}
                onApprove={handleApprove}
                onReject={handleReject}
                onResolveInteraction={handleResolveInteraction}
                onOpenCandidate={(candidateId) => openCommunications("candidate", candidateId)}
                onOpenEvolution={openEvolution}
              />
            ) : (
              <EvolutionView
                profile={profile}
                candidates={summary.candidates}
                approvals={summary.approvals}
                skills={summary.skills}
                artifacts={evolutionArtifacts}
                candidateMemories={candidateMemories}
                jobMemories={jobMemories}
                globalMemory={globalMemory}
                pendingActionId={approvalActionId}
                requestedSection={evolutionFocus.section}
                requestedItemId={evolutionFocus.itemId}
                onApprove={handleApprove}
                onReject={handleReject}
                onSaveProfile={handleSaveProfile}
                onUpdateSkill={handleUpdateSkill}
                onDeleteSkill={handleDeleteSkill}
                onUpdateCandidateMemory={handleUpdateCandidateMemory}
                onCompactCandidateMemory={handleCompactCandidateMemory}
                onUpdateJobMemory={handleUpdateJobMemory}
                onCompactJobMemory={handleCompactJobMemory}
                onUpdateGlobalMemory={handleUpdateGlobalMemory}
                onCompactGlobalMemory={handleCompactGlobalMemory}
                onUpdateArtifact={handleUpdateEvolutionArtifact}
                onOpenCandidate={(candidateId) => openCommunications("candidate", candidateId)}
              />
            )}
          </div>
        );
      case "settings":
        return (
          <SettingsView
            settings={summary.settings}
            mcpPresets={mcpPresets}
            mcpServers={mcpServers}
            saving={settingsSaving}
            onSave={handleSaveSettings}
            onInstallMcpPreset={handleInstallMcpPreset}
            onCreateMcpServer={handleCreateMcpServer}
            onUpdateMcpServer={handleUpdateMcpServer}
            onDeleteMcpServer={handleDeleteMcpServer}
            onHealthcheckMcpServer={handleHealthcheckMcpServer}
          />
        );
      default:
        return <DashboardView summary={summary} />;
    }
  })();

  return (
    <AppLayout
      sidebar={<Sidebar active={tab} onChange={setTab} counts={counts} />}
      topbar={
        <TopBar
          agent={summary.agent}
          settings={summary.settings}
          transport={transport}
          sectionEyebrow={sectionMeta[tab].eyebrow}
          sectionTitle={sectionMeta[tab].title}
          hideSectionSummary={tab === "candidates"}
          leadingContent={
            tab === "candidates" ? (
              <SectionTabs
                variant="topbar"
                items={candidateKanbanTabItems}
                active={candidateKanbanTab}
                onChange={(key) => setCandidateKanbanTab(key as CandidatesKanbanTab)}
              />
            ) : undefined
          }
          onRefresh={() => void loadWorkspace(copy("Manual refresh completed.", "已完成手动刷新。"))}
          refreshing={refreshing}
        />
      }
    >
      {errorMessage ? (
        <div
          style={{
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--danger)",
            background: "var(--danger-soft)",
            color: "var(--danger)",
            padding: "var(--space-3) var(--space-4)",
            fontSize: "var(--font-size-sm)",
            lineHeight: "var(--line-height-base)",
          }}
        >
          {errorMessage}
        </div>
      ) : null}
      {content}
    </AppLayout>
  );
}
