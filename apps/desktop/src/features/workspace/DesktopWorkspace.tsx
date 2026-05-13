import React, { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import type {
  ApplicationTransitionPayload,
  RecruitmentStateMachine,
} from "@recruit-agent/shared";
import { AppLayout, Sidebar, ToastNotification, TopBar } from "../../components";
import { ChatOverlay, useChatOverlay } from "../chat-overlay";
import { apiClient } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import type {
  AgentSnapshot,
  ApplicationThreadRecord,
  DashboardSummary,
  JobDescriptionSummaryRecord,
  McpPresetTemplateRecord,
  McpServerRecord,
  SettingsSnapshot,
  WorkspaceTab,
} from "../../lib/types";
import { CandidatesKanbanView, type CandidatesKanbanTab } from "../candidates/CandidatesKanbanView";
import { DashboardView } from "../dashboard/DashboardView";
import { buildApplicationViewModels } from "../kanban-shared/kanbanUtils";
import { JdManagementView } from "../jd-management";
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

export function DesktopWorkspace(): JSX.Element {
  const { copy } = useI18n();
  const { focusAgent } = useChatOverlay();
  const [tab, setTab] = useState<WorkspaceTab>("home");
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [summary, setSummary] = useState<DashboardSummary>(emptySummary);
  const [jobDescriptions, setJobDescriptions] = useState<JobDescriptionSummaryRecord[]>([]);
  const [applicationThreads, setApplicationThreads] = useState<ApplicationThreadRecord[]>([]);
  const [stateMachine, setStateMachine] = useState<RecruitmentStateMachine | null>(null);
  const [mcpPresets, setMcpPresets] = useState<McpPresetTemplateRecord[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServerRecord[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [transport, setTransport] = useState(apiClient.describe().transport);
  const [errorMessage, setErrorMessage] = useState<string>();
  const [dismissedErrorMessage, setDismissedErrorMessage] = useState<string>();
  const [candidateWorkspaceFocus, setCandidateWorkspaceFocus] = useState<{
    applicationId?: string;
    conversationToken: number;
  }>({
    applicationId: undefined,
    conversationToken: 0,
  });

  const loadCoreWorkspace = useCallback(async () => {
    setRefreshing(true);
    try {
      const [nextSummary, nextThreads, nextStateMachine, nextJobDescriptions] = await Promise.all([
        apiClient.getDashboardSummary(),
        apiClient.listApplicationThreads(),
        apiClient.getStateMachine(),
        apiClient.listJobDescriptions(),
      ]);

      startTransition(() => {
        setSummary(nextSummary);
        setJobDescriptions(nextJobDescriptions);
        setApplicationThreads(nextThreads);
        setStateMachine(nextStateMachine);
      });
      setTransport("http");
      setErrorMessage(undefined);
      setDismissedErrorMessage(undefined);
    } catch (error) {
      const backendReachable = await apiClient.checkHealth();
      setTransport(backendReachable ? "http" : "offline");
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to refresh workspace.", "刷新工作区失败。"));
    } finally {
      setRefreshing(false);
    }
  }, [copy]);

  const loadSettingsWorkspace = useCallback(async () => {
    try {
      const [nextPresets, nextServers] = await Promise.all([
        apiClient.listMcpPresets(),
        apiClient.listMcpServers(),
      ]);
      setMcpPresets(nextPresets);
      setMcpServers(nextServers);
      setSettingsLoaded(true);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to load settings tools.", "加载设置工具失败。"));
    }
  }, [copy]);

  const refreshWorkspace = useCallback(async () => {
    await loadCoreWorkspace();
    if (tab === "settings" || settingsLoaded) {
      await loadSettingsWorkspace();
    }
  }, [loadCoreWorkspace, loadSettingsWorkspace, settingsLoaded, tab]);

  useEffect(() => {
    void loadCoreWorkspace();

    const interval = window.setInterval(() => {
      void loadCoreWorkspace();
    }, 10000);

    return () => {
      window.clearInterval(interval);
    };
  }, [loadCoreWorkspace]);

  useEffect(() => {
    if (tab === "settings" && !settingsLoaded) {
      void loadSettingsWorkspace();
    }
  }, [loadSettingsWorkspace, settingsLoaded, tab]);

  useEffect(() => {
    if (tab === "jdManagement") {
      setSidebarExpanded(true);
    }
  }, [tab]);

  const sectionMeta = useMemo(
    (): Record<WorkspaceTab, { eyebrow: string; title: string; description: string }> => ({
      home: {
        eyebrow: copy("Today", "今日工作"),
        title: copy("Home", "首页"),
        description: copy(
          "Start from recruiter queues, blocked items, and the next actions that matter today.",
          "从招聘待办、阻塞事项和今天最重要的下一步动作开始。",
        ),
      },
      applicationFunnel: {
        eyebrow: copy("Application funnel", "投递记录漏斗"),
        title: copy("Application funnel", "投递记录漏斗"),
        description: copy(
          "Track application records by funnel milestone and inspect the current pool for each role.",
          "按漏斗阶段查看投递记录，并检查各岗位当前池子。",
        ),
      },
      applicationFollowUp: {
        eyebrow: copy("Application follow-up", "投递记录跟进"),
        title: copy("Application follow-up", "投递记录跟进"),
        description: copy(
          "Follow up application records through communication, scoring, interviews, and offers.",
          "围绕沟通、评分、面试与 Offer 推进投递记录。",
        ),
      },
      jdManagement: {
        eyebrow: copy("JD management", "JD 管理"),
        title: copy("JD management", "JD 管理"),
        description: copy(
          "Inspect synced job descriptions and their related application funnel snapshots.",
          "查看已同步 JD 以及对应投递漏斗快照。",
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
      agents: {
        eyebrow: copy("Agent operations", "Agent 运行管理"),
        title: copy("Agent management", "Agent 管理"),
        description: copy(
          "Inspect agent runs, sessions, approvals, memory, skills, tools, and execution configuration.",
          "查看 Agent 运行、会话、确认项、Memory、Skill、工具和执行配置。",
        ),
      },
    }),
    [copy],
  );

  const candidateKanbanModels = useMemo(
    () => (stateMachine ? buildApplicationViewModels(summary.applications, applicationThreads, stateMachine) : []),
    [applicationThreads, stateMachine, summary.applications],
  );

  const counts = useMemo(
    () => {
      const followUpCount = candidateKanbanModels.filter((item) => {
          const node = item.displayNode;
          if (!node || node.uiConfig?.showInKanban === false) {
            return false;
          }
          if (item.displayStatus === "exception_closed") {
            return false;
          }
          return node.phase !== "I" && (((!node.isTerminal && !node.isSoftTerminal) || node.isSuccess));
      }).length;
      return {
        applicationFunnel: candidateKanbanModels.length,
        applicationFollowUp: followUpCount,
        jdManagement: jobDescriptions.length,
        settings: mcpServers.filter((server) => !server.enabled || !/healthy/i.test(server.healthStatus)).length,
      } satisfies Partial<Record<WorkspaceTab, number>>;
    },
    [candidateKanbanModels, jobDescriptions.length, mcpServers],
  );

  const handleSaveSettings = async (patch: Partial<SettingsSnapshot>) => {
    setSettingsSaving(true);
    try {
      const nextSettings = await apiClient.updateSettings(patch);
      startTransition(() => {
        setSummary((current) => ({ ...current, settings: nextSettings }));
      });
      await loadCoreWorkspace();
    } finally {
      setSettingsSaving(false);
    }
  };

  const handleInstallMcpPreset = async (
    presetKey: string,
    payload?: { serverKey?: string; name?: string; endpoint?: string },
  ) => {
    await apiClient.installMcpPreset(presetKey, payload);
    await loadSettingsWorkspace();
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
    await loadSettingsWorkspace();
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
    await loadSettingsWorkspace();
  };

  const handleDeleteMcpServer = async (serverId: string) => {
    await apiClient.deleteMcpServer(serverId);
    await loadSettingsWorkspace();
  };

  const handleHealthcheckMcpServer = async (serverId: string) => {
    await apiClient.healthcheckMcpServer(serverId);
    await loadSettingsWorkspace();
  };

  const handleCreateApplicationEntry = async (
    applicationId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ) => {
    await apiClient.createApplicationEntry(applicationId, payload);
    await loadCoreWorkspace();
  };

  const handleTransitionApplicationState = async (
    applicationId: string,
    payload: ApplicationTransitionPayload,
  ) => {
    await apiClient.transitionApplicationState(applicationId, payload);
    await loadCoreWorkspace();
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
    setCandidateWorkspaceFocus((current) => ({
      applicationId,
      conversationToken: applicationId ? current.conversationToken + 1 : current.conversationToken,
    }));
    setTab(statusFilter || applicationId ? "applicationFollowUp" : "applicationFunnel");
  };

  const openJdManagement = () => {
    setTab("jdManagement");
  };

  const openApplicationFunnel = () => {
    setTab("applicationFunnel");
  };

  const openDashboard = () => {
    setTab("home");
  };

  const openAgents = (panel: "conversation" | "config", agent: "assistant" | "autonomous") => {
    focusAgent(agent, panel);
    setTab("agents");
  };

  const content = (() => {
    switch (tab) {
      case "home":
        return (
          <DashboardView
            summary={summary}
            onOpenCandidates={openApplicationFunnel}
            onOpenJdWorkspace={openJdManagement}
            onOpenCommunications={() => openApplicationWorkspace("active")}
            onOpenAgentRuntime={() => openAgents("conversation", "autonomous")}
            onOpenAgentConfig={() => openAgents("config", "assistant")}
          />
        );
      case "applicationFunnel":
        return (
          <CandidatesKanbanView
            applications={summary.applications}
            threads={applicationThreads}
            stateMachine={stateMachine}
            summaryDefinitions={summary.applicationFollowUpSummaryDefinitions}
            activeTab={"funnel" satisfies CandidatesKanbanTab}
            preferredApplicationId={candidateWorkspaceFocus.applicationId}
            preferredConversationToken={candidateWorkspaceFocus.conversationToken}
            onOpenApplication={(applicationId) => openApplicationWorkspace("application", applicationId)}
            onRefresh={() => void refreshWorkspace()}
            onCreateEntry={handleCreateApplicationEntry}
            onTransition={handleTransitionApplicationState}
            onOpenDashboard={openDashboard}
            jdContent={null}
          />
        );
      case "applicationFollowUp":
        return (
          <CandidatesKanbanView
            applications={summary.applications}
            threads={applicationThreads}
            stateMachine={stateMachine}
            summaryDefinitions={summary.applicationFollowUpSummaryDefinitions}
            activeTab={"status" satisfies CandidatesKanbanTab}
            preferredApplicationId={candidateWorkspaceFocus.applicationId}
            preferredConversationToken={candidateWorkspaceFocus.conversationToken}
            onOpenApplication={(applicationId) => openApplicationWorkspace("application", applicationId)}
            onRefresh={() => void refreshWorkspace()}
            onCreateEntry={handleCreateApplicationEntry}
            onTransition={handleTransitionApplicationState}
            onOpenDashboard={openDashboard}
            jdContent={null}
          />
        );
      case "jdManagement":
        return (
          <JdManagementView
            applications={candidateKanbanModels}
            jobDescriptions={jobDescriptions}
            onRefresh={refreshWorkspace}
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
      case "agents":
        return <ChatOverlay transport={transport} workspaceAgent={summary.agent} variant="page" />;
      default:
        return <DashboardView summary={summary} stateMachine={stateMachine} />;
    }
  })();
  const applicationSurface =
    tab === "applicationFunnel" || tab === "applicationFollowUp" || tab === "jdManagement";
  const visibleErrorMessage = errorMessage && errorMessage !== dismissedErrorMessage ? errorMessage : undefined;
  const runtimeGateCount = summary.agent.status === "waiting_human" ? 1 : 0;

  return (
    <>
      <AppLayout
        hideTopbar={tab === "applicationFollowUp" || tab === "jdManagement" || tab === "agents"}
        sidebarExpanded={sidebarExpanded}
        sidebar={
          <Sidebar
            active={tab}
            onChange={setTab}
            counts={counts}
            expanded={sidebarExpanded}
            onExpandedChange={setSidebarExpanded}
            agentStatus={summary.agent.status}
            agentCount={runtimeGateCount}
            onOpenAgents={() => openAgents("conversation", "autonomous")}
          />
        }
        topbar={
          <TopBar
            settings={summary.settings}
            transport={transport}
            sectionEyebrow={sectionMeta[tab].eyebrow}
            sectionTitle={sectionMeta[tab].title}
            hideSectionSummary={applicationSurface}
            onRefresh={() => void refreshWorkspace()}
            refreshing={refreshing}
          />
        }
      >
        {content}
      </AppLayout>

      {visibleErrorMessage ? (
        <ToastNotification
          title={copy("Workspace refresh failed", "工作区刷新失败")}
          message={visibleErrorMessage}
          onClose={() => setDismissedErrorMessage(visibleErrorMessage)}
        />
      ) : null}

    </>
  );
}
