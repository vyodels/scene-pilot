import React, { startTransition, useEffect, useMemo, useState } from "react";
import type {
  ApplicationTransitionPayload,
  RecruitmentStateMachine,
  RecruitmentStateMachineUpdatePayload,
} from "@scene-pilot/shared";
import { AppLayout, Panel, SectionTabs, Sidebar, StatusBadge, TopBar } from "../../components";
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
  ApplicationThreadRecord,
  DashboardSummary,
  ExecutionGraphProjectionRecord,
  ExecutionTraceRecord,
  EvolutionArtifactRecord,
  GoalSpecRecord,
  JobMemoryRecord,
  McpPresetTemplateRecord,
  McpServerRecord,
  OperatorInteractionRecord,
  PersonMemoryRecord,
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
import { DashboardView } from "../dashboard/DashboardView";
import { EvolutionView } from "../evolution/EvolutionView";
import { buildApplicationViewModels } from "../kanban-shared/kanbanUtils";
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

const surfaceRowButtonStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "var(--space-4)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-line)",
  background: "var(--bg-card)",
  cursor: "pointer",
};

function JdWorkspaceSurface({
  applications,
  onOpenApplication,
}: {
  applications: DashboardSummary["applications"];
  onOpenApplication?(filter?: string, applicationId?: string): void;
}): JSX.Element {
  const { copy } = useI18n();
  const jdGroups = Object.entries(
    applications.reduce<Record<string, DashboardSummary["applications"]>>((accumulator, application) => {
      const key = application.jobDescription.title || copy("Unassigned role", "未分配岗位");
      accumulator[key] = [...(accumulator[key] ?? []), application];
      return accumulator;
    }, {}),
  ).sort((left, right) => right[1].length - left[1].length);

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(calc(var(--space-12) * 3 + var(--space-10) + var(--space-10) + var(--space-5) + var(--space-4)), 1fr))", gap: "var(--space-3)" }}>
        {jdGroups.slice(0, 4).map(([jdTitle, jdApplications]) => {
          const macroCounts = jdApplications.reduce<Record<string, number>>((accumulator, application) => {
            const stage = resolveMacroStage(application.currentStatus, application.stageKey, application.resumeAvailable);
            accumulator[stage] = (accumulator[stage] ?? 0) + 1;
            return accumulator;
          }, {});
          return (
            <article key={jdTitle} style={{ padding: "var(--space-4)", borderRadius: "var(--radius-md)", background: "var(--bg-card)", border: "1px solid var(--border-line)" }}>
              <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{jdTitle}</div>
              <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-size-sm)", color: "var(--text-secondary)" }}>
                {copy(`${jdApplications.length} applications in this funnel.`, `该漏斗下共有 ${jdApplications.length} 条申请。`)}
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

      <div style={{ display: "grid", gap: "var(--space-3)" }}>
        {jdGroups.map(([jdTitle, jdApplications]) => (
          <Panel
            key={jdTitle}
            title={jdTitle}
            eyebrow={copy("Role funnel", "岗位漏斗")}
            description={copy("Applications currently grouped under this role.", "当前归属到该岗位的申请。")}
          >
            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              {jdApplications.map((application) => {
                const macroStage = resolveMacroStage(application.currentStatus, application.stageKey, application.resumeAvailable);
                return (
                  <button
                    key={application.id}
                    type="button"
                    onClick={() => onOpenApplication?.("application", application.id)}
                    style={surfaceRowButtonStyle}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)", alignItems: "start" }}>
                      <div>
                        <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{application.person.name}</div>
                        <div style={{ marginTop: "var(--space-1)", fontSize: "var(--font-size-sm)", color: "var(--text-secondary)" }}>
                          {application.person.title} · {application.person.location}
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", justifyContent: "end" }}>
                        <StatusBadge tone={macroStageTone(macroStage)}>{macroStage}</StatusBadge>
                        <StatusBadge tone="neutral">{copy(`score ${application.matchScore}`, `分数 ${application.matchScore}`)}</StatusBadge>
                      </div>
                    </div>
                    <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-size-sm)", color: "var(--text-regular)", lineHeight: 1.6 }}>{application.nextAction}</div>
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
  applications: [],
  applicationFollowUpSummaryDefinitions: [],
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
  const [personMemories, setPersonMemories] = useState<PersonMemoryRecord[]>([]);
  const [jobMemories, setJobMemories] = useState<JobMemoryRecord[]>([]);
  const [globalMemory, setGlobalMemory] = useState<AgentGlobalMemoryRecord | null>(null);
  const [applicationThreads, setApplicationThreads] = useState<ApplicationThreadRecord[]>([]);
  const [stateMachine, setStateMachine] = useState<RecruitmentStateMachine | null>(null);
  const [evolutionArtifacts, setEvolutionArtifacts] = useState<EvolutionArtifactRecord[]>([]);
  const [goals, setGoals] = useState<GoalSpecRecord[]>([]);
  const [executionTraces, setExecutionTraces] = useState<ExecutionTraceRecord[]>([]);
  const [executionGraphs, setExecutionGraphs] = useState<ExecutionGraphProjectionRecord[]>([]);
  const [strategyFragments, setStrategyFragments] = useState<StrategyFragmentRecord[]>([]);
  const [operatorInteractions, setOperatorInteractions] = useState<OperatorInteractionRecord[]>([]);
  const [mcpPresets, setMcpPresets] = useState<McpPresetTemplateRecord[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServerRecord[]>([]);
  const [candidateWorkspaceFocus, setCandidateWorkspaceFocus] = useState<{ applicationId?: string; conversationToken: number }>({
    applicationId: undefined,
    conversationToken: 0,
  });
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
        nextApplicationThreads,
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
        apiClient.listPersonMemories(),
        apiClient.listJobMemories(),
        apiClient.getAgentGlobalMemory(),
        apiClient.listApplicationThreads(),
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
        setPersonMemories(nextCandidateMemories);
        setJobMemories(nextJobMemories);
        setGlobalMemory(nextGlobalMemory);
        setApplicationThreads(nextApplicationThreads);
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
          operatorInteractions.filter((item) => !item.applicationId && item.status === "pending").length +
          summary.skills.filter((skill) => skill.status !== "active" || skill.health !== "healthy").length +
          evolutionArtifacts.filter((artifact) => /(pending|draft|review)/i.test(artifact.status)).length,
        candidates: summary.applications.filter((application) => !/(rejected|cooldown)/i.test(application.currentStatus)).length,
      }) satisfies Partial<Record<WorkspaceTab, number>>,
    [copy, evolutionArtifacts, operatorInteractions, summary],
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
    () => (stateMachine ? buildApplicationViewModels(summary.applications, applicationThreads, stateMachine) : []),
    [applicationThreads, stateMachine, summary.applications],
  );

  const candidateKanbanTabItems = useMemo(
    () => [
      {
        key: "funnel",
        label: copy("Candidate funnel", "候选人漏斗"),
        count: summary.applications.length,
      },
      {
        key: "status",
        label: copy("Candidate follow-up", "候选人跟进"),
        count: candidateKanbanModels.filter((item) => item.humanRequired).length,
      },
      {
        key: "jd",
        label: copy("JD management", "JD 管理"),
        count: new Set(summary.applications.map((application) => application.jobDescription.title || copy("Unassigned role", "未分配岗位"))).size,
      },
    ],
    [candidateKanbanModels, copy, summary.applications],
  );

  const importActivityGoals = useMemo(
    () => goals.filter((goal) => /(import|extract|capture|resume|candidate|sourcing|zhipin)/i.test(`${goal.title} ${goal.goalText} ${goal.summary ?? ""}`)).slice(0, 4),
    [goals],
  );

  const importActivityTraces = useMemo(
    () => executionTraces.filter((trace) => /(candidate|resume|import|source)/i.test(`${trace.title} ${trace.summary ?? ""}`)).slice(0, 4),
    [executionTraces],
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
      const firstApplication = summary.applications[0];
      if (!firstApplication) {
        await loadWorkspace(copy("No candidate available for adaptive review.", "当前没有可用于目标驱动评估的候选人。"));
        return;
      }
      await apiClient.createGoal({
        title: copy(`Review ${firstApplication.person.name}`, `评估 ${firstApplication.person.name}`),
        goalText: copy(
          `Review application ${firstApplication.person.name} for ${firstApplication.jobDescription.title}. Use real external capabilities to inspect the candidate, assess fit, and distill a reusable screening strategy.`,
          `围绕候选人 ${firstApplication.person.name} 和岗位 ${firstApplication.jobDescription.title} 启动一次目标驱动评估。请使用真实外部能力完成候选人查看、匹配判断，并沉淀可复用筛选策略。`,
        ),
        summary: copy("Create a goal-driven candidate review run.", "创建一个目标驱动的候选人评估 run。"),
        priority: 180,
        constraints: {
          application_id: firstApplication.id,
          platform: firstApplication.platform,
        },
        contextHints: {
          application_id: firstApplication.id,
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

  const handleUpdatePersonMemory = async (personId: string, payload: Partial<PersonMemoryRecord>) => {
    await apiClient.updatePersonMemory(personId, payload);
    await loadWorkspace(copy("Candidate memory updated.", "候选人 memory 已更新。"));
  };

  const handleCompactPersonMemory = async (personId: string) => {
    await apiClient.compactPersonMemory(personId, "manual_compact", true);
    await loadWorkspace(copy("Candidate memory compacted.", "候选人 memory 已 compact。"));
  };

  const handleUpdateJobMemory = async (jobDescriptionId: string, payload: Partial<JobMemoryRecord>) => {
    await apiClient.updateJobMemory(jobDescriptionId, payload);
    await loadWorkspace(copy("JD memory updated.", "JD memory 已更新。"));
  };

  const handleCompactJobMemory = async (jobDescriptionId: string) => {
    await apiClient.compactJobMemory(jobDescriptionId, "manual_compact", true);
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

  const handleCreateApplicationEntry = async (applicationId: string, payload: { direction: string; content: string; messageType?: string; platform?: string }) => {
    await apiClient.createApplicationEntry(applicationId, payload);
    await loadWorkspace(copy("Conversation entry added.", "沟通记录已追加。"));
  };

  const handleTransitionApplicationState = async (
    applicationId: string,
    payload: ApplicationTransitionPayload,
  ) => {
    await apiClient.transitionApplicationState(applicationId, payload);
    await loadWorkspace(copy("Application state updated.", "申请状态已更新。"));
  };

  const resolveApplicationId = (subjectId?: string) => {
    const normalized = String(subjectId ?? "").trim();
    if (!normalized) {
      return undefined;
    }
    const direct = summary.applications.find(
      (application) => application.id === normalized || application.applicationId === normalized,
    );
    if (direct) {
      return direct.applicationId || direct.id;
    }
    const byPerson = summary.applications.find((application) => application.personId === normalized);
    return byPerson ? byPerson.applicationId || byPerson.id : undefined;
  };

  const openApplicationWorkspace = (statusFilter?: string, applicationIdLike?: string) => {
    const applicationId = resolveApplicationId(applicationIdLike);
    setCandidateKanbanTab("status");
    setCandidateWorkspaceFocus((current) => ({
      applicationId,
      conversationToken: applicationId ? current.conversationToken + 1 : current.conversationToken,
    }));
    setTab("candidates");
  };

  const openJdManagement = () => {
    setCandidateKanbanTab("jd");
    setTab("candidates");
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
            onOpenJdWorkspace={openJdManagement}
            onOpenCommunications={() => openApplicationWorkspace("active")}
            onOpenAiReview={() => openAiReview("all")}
            onOpenAiStrategy={() => setTab("ai-strategy")}
          />
        );
      case "candidates":
        return (
          <CandidatesKanbanView
            applications={summary.applications}
            threads={applicationThreads}
            stateMachine={stateMachine}
            summaryDefinitions={summary.applicationFollowUpSummaryDefinitions}
            activeTab={candidateKanbanTab}
            preferredApplicationId={candidateWorkspaceFocus.applicationId}
            preferredConversationToken={candidateWorkspaceFocus.conversationToken}
            onOpenApplication={(applicationId) => openApplicationWorkspace("application", applicationId)}
            onRefresh={() => loadWorkspace(copy("Manual refresh completed.", "已完成手动刷新。"))}
            onCreateEntry={handleCreateApplicationEntry}
            onTransition={handleTransitionApplicationState}
            jdContent={<JdWorkspaceSurface applications={summary.applications} onOpenApplication={openApplicationWorkspace} />}
          />
        );
      case "ai-strategy":
        return (
          <RecruitAgentView
            profile={profile}
            stateMachine={stateMachine}
            applications={summary.applications}
            skills={summary.skills}
            personMemories={personMemories}
            jobMemories={jobMemories}
            globalMemory={globalMemory}
            onSaveProfile={handleSaveProfile}
            onSaveStateMachine={handleSaveStateMachine}
            onUpdateSkill={handleUpdateSkill}
            onDeleteSkill={handleDeleteSkill}
            onUpdatePersonMemory={handleUpdatePersonMemory}
            onCompactPersonMemory={handleCompactPersonMemory}
            onUpdateJobMemory={handleUpdateJobMemory}
            onCompactJobMemory={handleCompactJobMemory}
            onUpdateGlobalMemory={handleUpdateGlobalMemory}
            onCompactGlobalMemory={handleCompactGlobalMemory}
          />
        );
      case "ai-review":
        return (
          <div style={{ display: "grid", gap: "var(--space-4)" }}>
            <Panel
              title={copy("Recent import activity", "最近导入动态")}
              eyebrow={copy("Execution updates", "执行动态")}
              description={copy(
                "Recent sourcing and resume-acquisition work is shown here after the import center was removed.",
                "导入中心下线后，最近的 sourcing 与简历获取执行动态统一临时放在这里查看。",
              )}
            >
              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                {importActivityGoals.map((goal) => (
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
                {importActivityTraces.map((trace) => (
                  <article key={trace.id} style={{ padding: "var(--space-3) 0", borderBottom: "1px solid var(--border-line)" }}>
                    <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{trace.title}</div>
                    <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-size-sm)", color: "var(--text-secondary)", lineHeight: 1.6 }}>
                      {trace.summary || copy("Execution note captured for recruiter review.", "已记录一条供招聘方查看的执行说明。")}
                    </div>
                  </article>
                ))}
                {!importActivityGoals.length && !importActivityTraces.length ? (
                  <div style={{ fontSize: "var(--font-size-sm)", color: "var(--text-secondary)" }}>
                    {copy("No recent import activity.", "当前没有最近导入动态。")}
                  </div>
                ) : null}
              </div>
            </Panel>
            <SectionTabs
              items={[
                {
                  key: "queue",
                  label: copy("Review queue", "审阅队列"),
                  detail: copy("Approvals, operator interactions, and blocked work.", "审批、人工介入项和阻塞任务。"),
                  count:
                    operatorInteractions.filter((item) => !item.applicationId && item.status === "pending").length +
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
                onOpenApplication={(applicationId) => openApplicationWorkspace("application", applicationId)}
                onOpenEvolution={openEvolution}
              />
            ) : (
              <EvolutionView
                profile={profile}
                applications={summary.applications}
                approvals={summary.approvals}
                skills={summary.skills}
                artifacts={evolutionArtifacts}
                personMemories={personMemories}
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
                onUpdatePersonMemory={handleUpdatePersonMemory}
                onCompactPersonMemory={handleCompactPersonMemory}
                onUpdateJobMemory={handleUpdateJobMemory}
                onCompactJobMemory={handleCompactJobMemory}
                onUpdateGlobalMemory={handleUpdateGlobalMemory}
                onCompactGlobalMemory={handleCompactGlobalMemory}
                onUpdateArtifact={handleUpdateEvolutionArtifact}
                onOpenApplication={(applicationId) => openApplicationWorkspace("application", applicationId)}
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
              <div className="workspace-topbar__candidate-tabs">
                <SectionTabs
                  variant="topbar"
                  items={candidateKanbanTabItems}
                  active={candidateKanbanTab}
                  onChange={(key) => setCandidateKanbanTab(key as CandidatesKanbanTab)}
                />
              </div>
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
