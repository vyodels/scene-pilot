import React, { startTransition, useEffect, useMemo, useState } from "react";
import { Sidebar, TopBar } from "../../components";
import { apiClient } from "../../lib/api";
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
import { CommunicationsView } from "../communications/CommunicationsView";
import { DashboardView } from "../dashboard/DashboardView";
import { EvolutionView } from "../evolution/EvolutionView";
import { RecruitAgentView } from "../recruit-agent/RecruitAgentView";
import { SettingsView } from "../settings/SettingsView";
import { WorkbenchView } from "../workbench/WorkbenchView";

const emptySettings: SettingsSnapshot = {
  locale: "en-US",
  timezone: "Asia/Shanghai",
  intranetEnabled: false,
  desktopApprovalsOnly: true,
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
  },
};

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
  workflows: [],
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
  const [tab, setTab] = useState<WorkspaceTab>("dashboard");
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
      "recruit-agent": summary.skills.filter((skill) => skill.status !== "active" || skill.health !== "healthy").length,
        "agent-inbox":
          operatorInteractions.filter((item) => !item.candidateId && item.status === "pending").length +
          summary.skills.filter((skill) => skill.status !== "active" || skill.health !== "healthy").length +
          evolutionArtifacts.filter((artifact) => /(pending|draft|review)/i.test(artifact.status)).length,
        workbench: summary.candidates.filter((candidate) => !/(rejected|cooldown)/i.test(candidate.status)).length,
        communications: candidateThreads.filter(
          (thread) =>
            thread.runtimeInteractions.some((interaction) => interaction.status === "pending") ||
            /(contact_required|contact_acquired|pending_communication|communicating|waiting_reply|resume_requested)/i.test(thread.candidate.status),
        ).length,
        evolution:
          summary.approvals.filter((approval) => approval.surface === "evolution" && approval.status === "pending").length +
          summary.skills.filter((skill) => skill.status !== "active" || skill.health !== "healthy").length,
      }) satisfies Partial<Record<WorkspaceTab, number>>,
    [candidateThreads, evolutionArtifacts, operatorInteractions, summary],
  );

  const sectionMeta = useMemo(
    (): Record<WorkspaceTab, { eyebrow: string; title: string; description: string }> => ({
      dashboard: {
        eyebrow: copy("Recruit Agent", "Recruit Agent"),
        title: copy("Overview", "概览"),
        description: copy("A concise view of candidate progress, approvals, and recent agent movement.", "集中查看候选人进度、审批状态和最近的 agent 动作。"),
      },
      "agent-inbox": {
        eyebrow: copy("Operator chat", "操作员会话"),
        title: copy("Agent IM", "Agent IM"),
        description: copy("Handle non-candidate run-time confirmations and blocked flow without leaving the main chat surface.", "在主聊天窗口里处理非候选人的运行时确认和阻塞流。"),
      },
      "recruit-agent": {
        eyebrow: copy("Agent configuration", "Agent 配置"),
        title: copy("Recruit Agent", "招聘 Agent"),
        description: copy("Expose role, prompt, execution blueprint, memory, and skill contracts directly to the operator.", "把角色、提示词、执行蓝图、memory 与 skill 契约直接暴露给操作员。"),
      },
      workbench: {
        eyebrow: copy("Operations", "运行操作"),
        title: copy("Workbench", "工作台"),
        description: copy("Focus on candidate progress and recent Recruit Agent execution results.", "聚焦候选人进度与最近的 Recruit Agent 执行结果。"),
      },
      communications: {
        eyebrow: copy("Runtime inbox", "运行时收件箱"),
        title: copy("Communications", "沟通中心"),
        description: copy("Manage candidate-scoped threads, confirmations, and communication history without cross-candidate leakage.", "按候选人管理线程、确认和沟通历史，避免跨候选人串线。"),
      },
      evolution: {
        eyebrow: copy("Self-learning", "自学习演进"),
        title: copy("Evolution", "自学习/演进"),
        description: copy("Handle skill degradation, memory compaction, and non-candidate approvals in one place.", "集中处理 skill 退化、memory compact 和非候选人审批。"),
      },
      settings: {
        eyebrow: copy("Local operator settings", "本地操作设置"),
        title: copy("Settings", "设置"),
        description: copy("Manage providers, local sync behavior, and desktop approval controls.", "管理 provider、本地同步行为和桌面端审批控制。"),
      },
    }),
    [copy],
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
    payload: {
      toStatus: string;
      phaseKey?: string;
      phaseLabel?: string;
      stageKey?: string;
      stageLabel?: string;
      note?: string;
      source?: string;
      actor?: string;
      metadata?: Record<string, unknown>;
      interviewRound?: number;
      contactChannels?: string[];
    },
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

  const openAgentInbox = (filter?: string, itemId?: string) => {
    setAgentInboxFocus({ filter, itemId });
    setTab("agent-inbox");
  };

  const openEvolution = (section?: string, itemId?: string) => {
    setEvolutionFocus({ section, itemId });
    setTab("evolution");
  };

  const content = (() => {
    switch (tab) {
      case "dashboard":
        return <DashboardView summary={summary} onOpenAgentInbox={() => openAgentInbox("all")} onOpenCommunications={openCommunications} onOpenEvolution={openEvolution} />;
      case "agent-inbox":
        return (
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
        );
      case "recruit-agent":
        return (
          <RecruitAgentView
            profile={profile}
            candidates={summary.candidates}
            skills={summary.skills}
            candidateMemories={candidateMemories}
            jobMemories={jobMemories}
            globalMemory={globalMemory}
            onSaveProfile={handleSaveProfile}
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
      case "workbench":
        return (
          <WorkbenchView
            summary={summary}
            data={runtimeData}
            agent={summary.agent}
            events={events}
            selectedEpisodeId={selectedEpisodeId}
            replay={selectedReplay}
            syncStatus={syncStatus}
            syncBacklog={syncBacklog}
            queueItems={queueItems}
            goals={goals}
            traces={executionTraces}
            graphs={executionGraphs}
            runningAction={runtimeActionBusy}
            syncingAction={syncingBacklog}
            onRunOnce={handleRunOnce}
            onQueueScreeningTask={handleQueueScreeningTask}
            onCreateGoal={handleCreateGoal}
            onFlushSync={handleFlushSync}
            onSelectEpisode={setSelectedEpisodeId}
            onOpenCommunications={openCommunications}
            onOpenAgentInbox={() => openAgentInbox("all")}
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
      case "evolution":
        return (
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
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: "248px minmax(0, 1fr)",
        background: "linear-gradient(180deg, #0a101a 0%, #0d1320 100%)",
        color: theme.colors.text,
      }}
    >
      <Sidebar active={tab} onChange={setTab} counts={counts} />
      <main style={{ display: "grid", gridTemplateRows: "auto 1fr", minWidth: 0 }}>
        <TopBar
          agent={summary.agent}
          settings={summary.settings}
          transport={transport}
          sectionEyebrow={sectionMeta[tab].eyebrow}
          sectionTitle={sectionMeta[tab].title}
          sectionDescription={sectionMeta[tab].description}
          onRefresh={() => void loadWorkspace(copy("Manual refresh completed.", "已完成手动刷新。"))}
          refreshing={refreshing}
        />
        <div style={{ padding: "0 22px 22px", minWidth: 0, display: "grid", gap: "18px" }}>
          {errorMessage ? (
            <div
              style={{
                borderRadius: "16px",
                border: "1px solid rgba(255,122,122,0.18)",
                background: "rgba(255,122,122,0.08)",
                color: "#ffdede",
                padding: "12px 14px",
                fontSize: "13px",
              }}
            >
              {errorMessage}
            </div>
          ) : null}
          {content}
        </div>
      </main>
    </div>
  );
}
